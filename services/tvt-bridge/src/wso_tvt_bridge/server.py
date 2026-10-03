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
from wso_api.tvt.device_service import DirectoryWorker
from wso_api.tvt.flow_service import AccountFlowWorker
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
from wso_contracts.tvt.account_flows import (
    AccountDynamicCodeRequest,
    AccountFlowCancel,
    AccountFlowReference,
    AccountFlowStart,
    AccountFlowView,
    AccountRecoverySubmit,
    AccountRegistrationSubmit,
)
from wso_contracts.tvt.directory import REQUEST_TYPES, DirectoryRequest, DirectoryView
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.token_vault import token_budget

from .generated import tvt_bridge_pb2 as pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .selected import (
    GRPC_OPTIONS,
    MAX_DIRECTORY_FRAME_BYTES,
    MAX_FRAME_BYTES,
    checked_directory_view,
    decode_directory_input,
    decode_input,
    directory_failure,
    endpoint,
    failure,
    flow_failure,
    pem,
    required,
    validate_request,
)
from .session_pool import SessionPool

# Startup cannot return an owner on failure. Keep uncertain original callbacks
# alive; no retry, worker recreation or sweep can release this quarantine.
_BOOTSTRAP_QUARANTINE: list[tuple[Callable[[], object], ...]] = []


@dataclass(frozen=True, slots=True, repr=False)
class ServerConfig:
    bind: str
    ca: bytes
    certificate: bytes
    key: bytes
    client_sans: frozenset[str]
    capacity: int = 32


class _Service(rpc.AccountBridgeV1Servicer):  # type: ignore[misc]
    _reply = pb.AccountReply
    _failure = staticmethod(failure)

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
        directory_method: str | None = None,
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
        reply = self._reply(failure_code="ACCOUNT_UNAVAILABLE")
        try:
            directory_end = (
                time.monotonic()
                + min(context.time_remaining() or 0, request.context.deadline_ms / 1000)
                if directory_method
                else None
            )
            validate_request(request, directory=directory_method is not None)
            body = (
                decode_directory_input(getattr(request, field), directory_method)
                if directory_method
                else decode_input(getattr(request, field), model)
                if model is not None
                else None
            )
            rpc_left = context.time_remaining()
            if rpc_left is None or rpc_left <= 0:
                raise failure("ACCOUNT_DEADLINE_EXCEEDED")
            end = (
                directory_end
                if directory_end is not None
                else time.monotonic()
                + min(rpc_left, request.context.deadline_ms / 1000)
            )

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
                try:
                    clean = (
                        checked_directory_view(
                            cast(DirectoryView, result),
                            cast(DirectoryRequest, body),
                            request.context.correlation_id,
                        )
                        if directory_method
                        else output.model_validate_json(result.model_dump_json())
                    )
                except (ValueError, TypeError):
                    raise failure("ACCOUNT_PROTOCOL_INVALID") from None
                if (
                    output is AccountFlowView
                    and body is not None
                    and any(
                        getattr(clean, name, None) != getattr(body, name)
                        for name in ("region", "brand", "purpose", "flow_id")
                        if hasattr(body, name)
                    )
                ):
                    raise failure("ACCOUNT_PROTOCOL_INVALID")
                payload = clean.model_dump_json().encode("utf-8")
                reply = self._reply(public_json=payload)
                if reply.ByteSize() > (
                    MAX_DIRECTORY_FRAME_BYTES if directory_method else MAX_FRAME_BYTES
                ):
                    raise failure("ACCOUNT_PROTOCOL_INVALID")
                remaining()
        except AccountFailure as exc:
            code = (
                "UNKNOWN_OUTCOME"
                if dispatched and exc.code == "ACCOUNT_DEADLINE_EXCEEDED"
                else self._failure(exc.code).code
            )
            reply = self._reply(failure_code=code)
        except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
            # Never log exception/response/request, including validation error inputs.
            reply = self._reply(failure_code="ACCOUNT_UNAVAILABLE")
        finally:
            if slot is not None and not self.pool.settle(slot):
                reply = self._reply(failure_code="UNKNOWN_OUTCOME")
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


class _FlowService(_Service, rpc.FlowBridgeV1Servicer):  # type: ignore[misc]
    _reply = pb.FlowReply
    _failure = staticmethod(flow_failure)

    def __init__(
        self, worker: AccountFlowWorker | None, config: ServerConfig, pool: SessionPool
    ) -> None:
        self.flow_worker, self.config, self.pool = worker, config, pool

    @staticmethod
    def _unavailable(*args: Any, **kwargs: Any) -> AccountFlowView:
        raise failure("ACCOUNT_UNAVAILABLE")

    def Start(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.start
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request, context, invoke, AccountFlowView, AccountFlowStart, "private_json"
        )

    def State(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.state
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountFlowReference,
            "private_json",
        )

    def Existence(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.existence
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountFlowReference,
            "private_json",
        )

    def Image(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.image
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountFlowReference,
            "private_json",
        )

    def IssueCode(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.issue_code
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountDynamicCodeRequest,
            "private_json",
        )

    def Register(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.register
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountRegistrationSubmit,
            "private_json",
        )

    def Recover(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.recover
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request,
            context,
            invoke,
            AccountFlowView,
            AccountRecoverySubmit,
            "private_json",
        )

    def Cancel(self, request: Any, context: grpc.ServicerContext) -> Any:
        invoke = (
            self.flow_worker.cancel
            if self.flow_worker is not None
            else self._unavailable
        )
        return self._execute(
            request, context, invoke, AccountFlowView, AccountFlowCancel, "private_json"
        )


class _DirectoryService(_Service, rpc.DirectoryBridgeV1Servicer):  # type: ignore[misc]
    _reply = pb.DirectoryReply
    _failure = staticmethod(directory_failure)

    def __init__(
        self, worker: DirectoryWorker | None, config: ServerConfig, pool: SessionPool
    ) -> None:
        self.directory_worker, self.config, self.pool = worker, config, pool

    def _directory(
        self, request: Any, context: grpc.ServicerContext, method: str
    ) -> Any:
        def invoke(ticket: str, body: Any, **kwargs: Any) -> DirectoryView:
            if self.directory_worker is None:
                raise failure("ACCOUNT_UNAVAILABLE")
            return self.directory_worker.execute(method, ticket, body, **kwargs)

        return self._execute(
            request,
            context,
            invoke,
            DirectoryView,
            cast(type[BaseModel], REQUEST_TYPES[method]),
            "query_json",
            method,
        )

    def DeviceList(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "device_list")

    def ChannelList(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "channel_list")

    def DeviceDetail(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "device_detail")

    def ChannelDetail(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "channel_detail")

    def SentShares(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "sent_shares")

    def ReceivedShares(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._directory(request, context, "received_shares")


class AccountRpcServer:
    def __init__(
        self,
        config: ServerConfig,
        worker: AccountWorker,
        *,
        dispose: Callable[[], object] = lambda: None,
        flow_worker: AccountFlowWorker | None = None,
        directory_worker: DirectoryWorker | None = None,
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
        self._cleanup_proved = False
        # Retain the disposer (and quarantined worker ownership) for this epoch.
        self._dispose = dispose

        def dispose_resources() -> None:
            try:
                closed = self._dispose()
                if closed is not None and closed is not True:
                    raise directory_failure("ACCOUNT_QUARANTINED")
            except Exception:  # noqa: BLE001 -- fixed uncertainty, never private errors
                self._cleanup_proved = False
            else:
                self._cleanup_proved = True

        self.pool = SessionPool(capacity=config.capacity, dispose=dispose_resources)
        self._threads = ThreadPoolExecutor(
            max_workers=config.capacity, thread_name_prefix="account-rpc"
        )
        native = None
        try:
            native = grpc.server(
                self._threads,
                options=GRPC_OPTIONS,
                maximum_concurrent_rpcs=config.capacity,
            )
            self._server = native
            rpc.add_AccountBridgeV1Servicer_to_server(
                _Service(worker, config, self.pool), self._server
            )
            rpc.add_FlowBridgeV1Servicer_to_server(
                _FlowService(flow_worker, config, self.pool), self._server
            )
            rpc.add_DirectoryBridgeV1Servicer_to_server(
                _DirectoryService(directory_worker, config, self.pool), self._server
            )
            credentials = grpc.ssl_server_credentials(
                [(config.key, config.certificate)],
                root_certificates=config.ca,
                require_client_auth=True,
            )
            self._port = self._server.add_secure_port(target, credentials)
            if not self._port:
                raise ValueError
        except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
            if native is not None:
                native.stop(0)
            self.pool.close(grace=0)
            self._threads.shutdown(wait=False, cancel_futures=True)
            raise failure("ACCOUNT_UNAVAILABLE") from None

    def start(self) -> int:
        with self._lock:
            if self._closed or self._started:
                raise failure("ACCOUNT_UNAVAILABLE")
            try:
                self._server.start()
            except Exception:  # noqa: BLE001, S110 -- redact native startup errors
                pass
            else:
                self._started = True
                return self._port
        self.close(grace=0)
        raise failure("ACCOUNT_UNAVAILABLE") from None

    def close(self, grace: float = 1.0) -> bool:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._server.stop(0)
        drained = self.pool.close(grace)
        self._threads.shutdown(wait=False, cancel_futures=True)
        return drained and self._cleanup_proved


def create_server_from_environment() -> AccountRpcServer:
    # These worker capabilities are imported only by the worker bootstrap.
    from wso_api.tvt.session_service import (
        AccountWorkerExecutor,
        load_account_endpoints,
    )
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.token_vault import TokenVault

    env = os.environ
    resources: list[Callable[[], object]] = []
    disposal_proved = False
    disposed = False
    disposal_lock = Lock()

    def dispose() -> object:
        nonlocal disposed, disposal_proved
        with disposal_lock:
            if disposed:
                return None if disposal_proved else False
            disposed = True
        proved = True
        for close in reversed(resources):
            try:
                closed = close()
                if closed is not None and closed is not True:
                    proved = False
            except Exception:  # noqa: BLE001 -- clean all owned resources without private logs
                proved = False
        disposal_proved = proved
        if not proved:
            _BOOTSTRAP_QUARANTINE.append(tuple(resources))
            raise flow_failure("ACCOUNT_QUARANTINED") from None
        return None

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
        resources.append(vault.close)
        endpoints = load_account_endpoints()
        from .flow_config import load_flow_configuration

        flow_settings = load_flow_configuration(env, endpoints)
        flow_worker = None
        if flow_settings is not None:
            from wso_api.tvt.flow_service import AccountFlowWorkerExecutor
            from wso_core.tvt.flow_admission import FlowAdmission

            admission = FlowAdmission(
                required(env, "WSO_WORKER_DATABASE_URL"), flow_settings.key_commitment
            )
            resources.append(admission.close)
            flow_worker = AccountFlowWorkerExecutor(
                admission, endpoints, flow_settings.profiles, flow_settings.binding_key
            )
            resources.append(lambda: flow_worker.close(deadline_ms=1000))
        from .directory_config import load_directory_configuration

        directory_policies = load_directory_configuration(env, endpoints)
        directory_worker = None
        if directory_policies is not None:
            from wso_api.tvt.device_service import DirectoryWorkerExecutor
            from wso_core.tvt.directory_admission import DirectoryAdmission

            directory_admission = DirectoryAdmission(
                required(env, "WSO_WORKER_DATABASE_URL"), directory_policies, provider
            )
            resources.append(directory_admission.close)
            directory_worker = DirectoryWorkerExecutor(directory_admission, endpoints)
            resources.append(lambda: directory_worker.close(deadline_ms=1000))
        return AccountRpcServer(
            config,
            cast(AccountWorker, AccountWorkerExecutor(vault, endpoints)),
            dispose=dispose,
            flow_worker=flow_worker,
            **(
                {"directory_worker": directory_worker}
                if directory_worker is not None
                else {}
            ),
        )
    except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
        try:
            dispose()
        except AccountFailure:
            pass
    raise failure("ACCOUNT_UNAVAILABLE") from None
