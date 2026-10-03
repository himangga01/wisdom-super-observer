"""API-side mTLS AccountWorker. No vault, DB URL or decrypt-key imports."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any, Self, TypeVar, cast

import grpc
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel
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
from wso_contracts.tvt.directory import (
    ChannelDetailRequest,
    ChannelListRequest,
    DeviceDetailRequest,
    DeviceListRequest,
    DirectoryRequest,
    DirectoryView,
    ReceivedSharesRequest,
    SentSharesRequest,
)
from wso_core.tvt.account_projection import AccountFailure

from .callback_registry import CallbackRegistry
from .generated import tvt_bridge_pb2 as pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .selected import (
    GRPC_OPTIONS,
    MAX_DIRECTORY_FRAME_BYTES,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    Budget,
    decode_directory_public,
    decode_public,
    directory_failure,
    encode_directory_input,
    encode_input,
    endpoint,
    failure,
    flow_failure,
    pem,
    reject_unknown,
    required,
    validate_request,
)

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True, repr=False)
class ClientConfig:
    endpoint: str
    ca: bytes
    certificate: bytes
    key: bytes


def _certificate_chain(data: bytes) -> list[x509.Certificate]:
    # Parse every block and reject trailing garbage or non-certificate PEM objects.
    if (
        re.fullmatch(
            rb"(?:\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----)+\s*",
            data,
        )
        is None
    ):
        raise ValueError
    return x509.load_pem_x509_certificates(data)


def _validate_tls(config: ClientConfig) -> None:
    valid = False
    try:
        if not all(
            type(value) is bytes and 0 < len(value) <= 65536
            for value in (config.ca, config.certificate, config.key)
        ):
            raise ValueError
        _certificate_chain(config.ca)
        chain = _certificate_chain(config.certificate)
        if (
            re.fullmatch(
                rb"\s*-----BEGIN (PRIVATE KEY|RSA PRIVATE KEY|EC PRIVATE KEY|DSA PRIVATE KEY)-----"
                rb"[A-Za-z0-9+/=\s]+-----END \1-----\s*",
                config.key,
            )
            is None
        ):
            raise ValueError
        private = serialization.load_pem_private_key(config.key, password=None)
        public_format = serialization.PublicFormat.SubjectPublicKeyInfo
        valid = chain[0].public_key().public_bytes(
            serialization.Encoding.DER, public_format
        ) == private.public_key().public_bytes(
            serialization.Encoding.DER, public_format
        )
    except (ValueError, TypeError, UnsupportedAlgorithm):
        pass
    if not valid:
        raise failure("ACCOUNT_UNAVAILABLE") from None


class AccountRpcClient:
    def __init__(self, config: ClientConfig, *, capacity: int = 32) -> None:
        self._registry = CallbackRegistry(capacity=capacity)
        target = endpoint(config.endpoint)
        _validate_tls(config)
        credentials = grpc.ssl_channel_credentials(
            config.ca, config.key, config.certificate
        )
        self._channel = grpc.secure_channel(target, credentials, options=GRPC_OPTIONS)
        self._stub = rpc.AccountBridgeV1Stub(self._channel)
        self._flow_stub = rpc.FlowBridgeV1Stub(self._channel)
        self._directory_stub = rpc.DirectoryBridgeV1Stub(self._channel)
        self._close_lock = Lock()
        self._closed = False

    def _call(
        self,
        method: Any,
        request_type: Any,
        ticket: str,
        deadline_ms: int,
        correlation_id: str,
        model: type[T],
        *,
        body: BaseModel | None = None,
        body_field: str = "",
        flow: bool = False,
        directory_method: str | None = None,
    ) -> T:
        safe_failure = (
            directory_failure if directory_method else flow_failure if flow else failure
        )
        if directory_method and (
            type(deadline_ms) is not int or not 1 <= deadline_ms <= 10000
        ):
            raise failure("ACCOUNT_INPUT_INVALID")
        budget = Budget(deadline_ms)
        request = request_type(
            context=pb.RpcContext(
                protocol_version=PROTOCOL_VERSION,
                ticket=ticket,
                deadline_ms=budget.remaining(),
                correlation_id=correlation_id,
            )
        )
        if body is not None:
            setattr(
                request,
                body_field,
                encode_directory_input(directory_method, cast(DirectoryRequest, body))
                if directory_method
                else encode_input(body),
            )
        validate_request(request, directory=directory_method is not None)
        slot = self._registry.admit(correlation_id)
        answer = None
        code = "ACCOUNT_UNAVAILABLE"
        dispatched = False
        try:
            # The single timeout includes connect/TLS/remote queue/execution. No retries.
            request.context.deadline_ms = budget.remaining()
            pending = method.future(
                request, timeout=budget.remaining() / 1000, wait_for_ready=False
            )
            dispatched = True
            self._registry.attach_cancel(slot, pending.cancel)
            reply = pending.result()
            budget.remaining()
            reject_unknown(reply)
            if reply.ByteSize() > (
                MAX_DIRECTORY_FRAME_BYTES if directory_method else MAX_FRAME_BYTES
            ) or bool(reply.failure_code) == bool(reply.public_json):
                raise failure("ACCOUNT_PROTOCOL_INVALID")
            if reply.failure_code:
                raise safe_failure(reply.failure_code)
            answer = (
                cast(
                    T,
                    decode_directory_public(
                        reply.public_json, cast(DirectoryRequest, body), correlation_id
                    ),
                )
                if directory_method
                else decode_public(reply.public_json, model)
            )
            if getattr(answer, "request_id", None) != correlation_id:
                raise failure("ACCOUNT_PROTOCOL_INVALID")
            if (
                flow
                and body is not None
                and any(
                    getattr(answer, name, None) != getattr(body, name)
                    for name in ("region", "brand", "purpose", "flow_id")
                    if hasattr(body, name)
                )
            ):
                raise failure("ACCOUNT_PROTOCOL_INVALID")
            budget.remaining()
        except AccountFailure as exc:
            answer = None
            code = exc.code
            if dispatched and code == "ACCOUNT_DEADLINE_EXCEEDED":
                code = "UNKNOWN_OUTCOME"
        except grpc.RpcError as exc:
            code = {
                grpc.StatusCode.PERMISSION_DENIED: "ACCOUNT_DENIED",
                grpc.StatusCode.RESOURCE_EXHAUSTED: "SESSION_BUSY",
            }.get(exc.code(), "UNKNOWN_OUTCOME")
        except grpc.FutureCancelledError:
            code = "UNKNOWN_OUTCOME"
        except (ValueError, TypeError):
            answer = None
            code = "ACCOUNT_PROTOCOL_INVALID"
        finally:
            deliver = self._registry.settle(slot)
        if not deliver:
            raise failure("UNKNOWN_OUTCOME") from None
        if answer is None:
            raise safe_failure(code) from None
        return answer

    def login(
        self, ticket: str, body: AccountLogin, *, deadline_ms: int, correlation_id: str
    ) -> AccountIdentity:
        return self._call(
            self._stub.Login,
            pb.LoginRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountIdentity,
            body=body,
            body_field="account_login_json",
        )

    def image_challenge(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> ImageChallengeView:
        return self._call(
            self._stub.ImageChallenge,
            pb.ImageChallengeRequest,
            ticket,
            deadline_ms,
            correlation_id,
            ImageChallengeView,
        )

    def check_image(
        self,
        ticket: str,
        body: ImageCheckRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> ImageCheckView:
        return self._call(
            self._stub.CheckImage,
            pb.CheckImageRequest,
            ticket,
            deadline_ms,
            correlation_id,
            ImageCheckView,
            body=body,
            body_field="image_check_json",
        )

    def profile(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountProfileView:
        return self._call(
            self._stub.Profile,
            pb.ProfileRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountProfileView,
        )

    def renew(
        self,
        ticket: str,
        body: AccountRefresh,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountIdentity:
        return self._call(
            self._stub.Renew,
            pb.RenewRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountIdentity,
            body=body,
            body_field="account_refresh_json",
        )

    def logout(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountLogoutView:
        return self._call(
            self._stub.Logout,
            pb.LogoutRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountLogoutView,
        )

    def start(
        self,
        ticket: str,
        body: AccountFlowStart,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountFlowStart:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Start,
            pb.FlowStartRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def state(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountFlowReference:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.State,
            pb.FlowStateRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def existence(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountFlowReference:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Existence,
            pb.FlowExistenceRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def image(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountFlowReference:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Image,
            pb.FlowImageRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def issue_code(
        self,
        ticket: str,
        body: AccountDynamicCodeRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountDynamicCodeRequest:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.IssueCode,
            pb.FlowIssueCodeRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def register(
        self,
        ticket: str,
        body: AccountRegistrationSubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountRegistrationSubmit:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Register,
            pb.FlowRegisterRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def recover(
        self,
        ticket: str,
        body: AccountRecoverySubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountRecoverySubmit:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Recover,
            pb.FlowRecoverRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def cancel(
        self,
        ticket: str,
        body: AccountFlowCancel,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        if type(body) is not AccountFlowCancel:
            raise failure("ACCOUNT_INPUT_INVALID")
        return self._call(
            self._flow_stub.Cancel,
            pb.FlowCancelRequest,
            ticket,
            deadline_ms,
            correlation_id,
            AccountFlowView,
            body=body,
            body_field="private_json",
            flow=True,
        )

    def directory_device_list(
        self,
        ticket: str,
        body: DeviceListRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.DeviceList,
            pb.DirectoryDeviceListRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="device_list",
        )

    def directory_channel_list(
        self,
        ticket: str,
        body: ChannelListRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.ChannelList,
            pb.DirectoryChannelListRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="channel_list",
        )

    def directory_device_detail(
        self,
        ticket: str,
        body: DeviceDetailRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.DeviceDetail,
            pb.DirectoryDeviceDetailRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="device_detail",
        )

    def directory_channel_detail(
        self,
        ticket: str,
        body: ChannelDetailRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.ChannelDetail,
            pb.DirectoryChannelDetailRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="channel_detail",
        )

    def directory_sent_shares(
        self,
        ticket: str,
        body: SentSharesRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.SentShares,
            pb.DirectorySentSharesRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="sent_shares",
        )

    def directory_received_shares(
        self,
        ticket: str,
        body: ReceivedSharesRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        return self._call(
            self._directory_stub.ReceivedShares,
            pb.DirectoryReceivedSharesRequest,
            ticket,
            deadline_ms,
            correlation_id,
            DirectoryView,
            body=body,
            body_field="query_json",
            directory_method="received_shares",
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._registry.close()
            self._channel.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def create_account_worker_client(
    env: Mapping[str, str] | None = None,
) -> AccountRpcClient:
    settings = os.environ if env is None else env
    return AccountRpcClient(
        ClientConfig(
            endpoint=required(settings, "WSO_TVT_BRIDGE_ENDPOINT"),
            ca=pem(required(settings, "WSO_TVT_BRIDGE_CA_FILE")),
            certificate=pem(required(settings, "WSO_TVT_BRIDGE_CLIENT_CERT_FILE")),
            key=pem(required(settings, "WSO_TVT_BRIDGE_CLIENT_KEY_FILE")),
        )
    )
