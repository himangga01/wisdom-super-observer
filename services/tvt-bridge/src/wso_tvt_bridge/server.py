"""Private account RPC server. TLS identity admits RPC; SQL alone grants authority."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, cast

import grpc
from pydantic import BaseModel
from wso_api.tvt.session_service import AccountWorker
from wso_contracts.tvt.account import (
    AccountIdentity,
    AccountLogin,
    AccountLogoutView,
    AccountProfileView,
    AccountRefresh,
    ImageChallengeView,
    ImageCheckRequest,
    ImageCheckView,
)
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.token_vault import token_budget

from .generated import tvt_bridge_pb2 as pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .selected import (
    GRPC_OPTIONS,
    MAX_FRAME_BYTES,
    decode_input,
    endpoint,
    failure,
    pem,
    required,
    validate_request,
)
from .session_pool import SessionPool


@dataclass(frozen=True, slots=True, repr=False)
class ServerConfig:
    bind: str
    ca: bytes
    certificate: bytes
    key: bytes
    client_sans: frozenset[str]
    capacity: int = 32


class _Service(rpc.AccountBridgeV1Servicer):  # type: ignore[misc]
    def __init__(
        self, worker: AccountWorker, config: ServerConfig, pool: SessionPool
    ) -> None:
        self.worker, self.config, self.pool = worker, config, pool

    def _execute(
        self,
        request: Any,
        context: grpc.ServicerContext,
        invoke: Callable[..., BaseModel],
        output: type[BaseModel],
        model: type[BaseModel] | None = None,
        field: str = "",
    ) -> Any:
        # TLS auth_context is authority for peer identity, never request metadata.
        auth = cast(Mapping[str, Sequence[bytes]], context.auth_context())
        identities = auth.get("x509_subject_alternative_name", ())
        allowed = {value.encode("ascii") for value in self.config.client_sans}
        if (
            auth.get("transport_security_type") != [b"ssl"]
            or context.peer_identity_key() != "x509_subject_alternative_name"
            or len(identities) != 1
            or identities[0] not in allowed
        ):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "ACCOUNT_DENIED")
        slot = None
        dispatched = False
        reply = pb.AccountReply(failure_code="ACCOUNT_UNAVAILABLE")
        try:
            validate_request(request)
            body = (
                decode_input(getattr(request, field), model)
                if model is not None
                else None
            )
            rpc_left = context.time_remaining()
            if rpc_left is None or rpc_left <= 0:
                raise failure("ACCOUNT_DEADLINE_EXCEEDED")
            end = time.monotonic() + min(rpc_left, request.context.deadline_ms / 1000)

            def remaining() -> int:
                left = int((end - time.monotonic()) * 1000)
                if left < 1 or not context.is_active():
                    raise failure("ACCOUNT_DEADLINE_EXCEEDED")
                return left

            remaining()
            slot = self.pool.registry.admit(request.context.correlation_id)
            owned = slot
            if not context.add_callback(lambda: self.pool.registry.abandon(owned)):
                self.pool.registry.abandon(slot)
                raise failure("ACCOUNT_DEADLINE_EXCEEDED")
            with token_budget(remaining):
                left = remaining()
                dispatched = True
                kwargs = {
                    "deadline_ms": left,
                    "correlation_id": request.context.correlation_id,
                }
                result = (
                    invoke(request.context.ticket, body, **kwargs)
                    if model is not None
                    else invoke(request.context.ticket, **kwargs)
                )
                remaining()
                if (
                    type(result) is not output
                    or getattr(result, "request_id", None)
                    != request.context.correlation_id
                ):
                    raise failure("ACCOUNT_PROTOCOL_INVALID")
                # Revalidation rejects model_construct/extra and stale mutated outputs.
                clean = output.model_validate_json(result.model_dump_json())
                payload = clean.model_dump_json().encode("utf-8")
                reply = pb.AccountReply(public_json=payload)
                if reply.ByteSize() > MAX_FRAME_BYTES:
                    raise failure("ACCOUNT_PROTOCOL_INVALID")
                remaining()
        except AccountFailure as exc:
            code = (
                "UNKNOWN_OUTCOME"
                if dispatched and exc.code == "ACCOUNT_DEADLINE_EXCEEDED"
                else failure(exc.code).code
            )
            reply = pb.AccountReply(failure_code=code)
        except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
            # Never log exception/response/request, including validation error inputs.
            reply = pb.AccountReply(failure_code="ACCOUNT_UNAVAILABLE")
        finally:
            if slot is not None and not self.pool.settle(slot):
                reply = pb.AccountReply(failure_code="UNKNOWN_OUTCOME")
        return reply

    def Login(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(
            request,
            context,
            self.worker.login,
            AccountIdentity,
            AccountLogin,
            "account_login_json",
        )

    def ImageChallenge(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(
            request, context, self.worker.image_challenge, ImageChallengeView
        )

    def CheckImage(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(
            request,
            context,
            self.worker.check_image,
            ImageCheckView,
            ImageCheckRequest,
            "image_check_json",
        )

    def Profile(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(request, context, self.worker.profile, AccountProfileView)

    def Renew(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(
            request,
            context,
            self.worker.renew,
            AccountIdentity,
            AccountRefresh,
            "account_refresh_json",
        )

    def Logout(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._execute(request, context, self.worker.logout, AccountLogoutView)


class AccountRpcServer:
    def __init__(
        self,
        config: ServerConfig,
        worker: AccountWorker,
        *,
        dispose: Callable[[], None] = lambda: None,
    ) -> None:
        target = endpoint(config.bind, bind=True)
        if (
            not all(
                type(value) is bytes and 0 < len(value) <= 65536
                for value in (config.ca, config.certificate, config.key)
            )
            or not 1 <= len(config.client_sans) <= 64
            or any(
                not value.isascii()
                or not 1 <= len(value) <= 255
                or any(c.isspace() for c in value)
                for value in config.client_sans
            )
        ):
            raise failure("ACCOUNT_UNAVAILABLE")
        self._lock = Lock()
        self._closed = False
        self._started = False
        self.pool = SessionPool(capacity=config.capacity, dispose=dispose)
        self._threads = ThreadPoolExecutor(
            max_workers=config.capacity, thread_name_prefix="account-rpc"
        )
        self._server = grpc.server(
            self._threads, options=GRPC_OPTIONS, maximum_concurrent_rpcs=config.capacity
        )
        rpc.add_AccountBridgeV1Servicer_to_server(
            _Service(worker, config, self.pool), self._server
        )
        credentials = grpc.ssl_server_credentials(
            [(config.key, config.certificate)],
            root_certificates=config.ca,
            require_client_auth=True,
        )
        try:
            self._port = self._server.add_secure_port(target, credentials)
            if not self._port:
                raise ValueError
        except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
            self._threads.shutdown(wait=False, cancel_futures=True)
            raise failure("ACCOUNT_UNAVAILABLE") from None

    def start(self) -> int:
        with self._lock:
            if self._closed or self._started:
                raise failure("ACCOUNT_UNAVAILABLE")
            self._server.start()
            self._started = True
            return self._port

    def close(self, grace: float = 1.0) -> bool:
        with self._lock:
            self._closed = True
            self._server.stop(0)
        drained = self.pool.close(grace)
        self._threads.shutdown(wait=False, cancel_futures=True)
        return drained


def create_server_from_environment() -> AccountRpcServer:
    # These worker capabilities are imported only by the worker bootstrap.
    from wso_api.tvt.session_service import (
        AccountWorkerExecutor,
        load_account_endpoints,
    )
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.token_vault import TokenVault

    env = os.environ
    vault = None
    try:
        allowed = json.loads(required(env, "WSO_TVT_BRIDGE_CLIENT_SANS_JSON"))
        if type(allowed) is not list or any(type(item) is not str for item in allowed):
            raise ValueError
        config = ServerConfig(
            bind=required(env, "WSO_TVT_BRIDGE_BIND"),
            ca=pem(required(env, "WSO_TVT_BRIDGE_CA_FILE")),
            certificate=pem(required(env, "WSO_TVT_BRIDGE_SERVER_CERT_FILE")),
            key=pem(required(env, "WSO_TVT_BRIDGE_SERVER_KEY_FILE")),
            client_sans=frozenset(allowed),
        )
        provider = FileKeyProvider(Path(required(env, "WSO_CONNECTION_KEY_FILE")))
        provider.encryption_key()  # Fail at startup on absent/invalid key.
        vault = TokenVault(required(env, "WSO_WORKER_DATABASE_URL"), provider)
        endpoints = load_account_endpoints()
        return AccountRpcServer(
            config,
            cast(AccountWorker, AccountWorkerExecutor(vault, endpoints)),
            dispose=vault.close,
        )
    except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
        if vault is not None:
            vault.close()
    raise failure("ACCOUNT_UNAVAILABLE") from None
