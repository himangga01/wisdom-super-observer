"""Private mux values and ports. Runtime closure is stdlib and pure wire only.

Seals prevent accidental construction at public boundaries; they are not a
sandbox against code executing in this Python process. Admission and original
custodians must retain their own issuer token and compare it by identity.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from enum import Enum
from threading import Event
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from .local_live import LiveError, PrivateLiveFrame, _guid, _integer, _Private

if TYPE_CHECKING:
    from wso_contracts.tvt.local_media import LocalLiveResponse
    from wso_contracts.tvt.media import MediaLease

    from .local_credentials import LocalDeviceCredentials
    from .local_media_service import LocalLiveProof, LocalMediaChannel
    from .local_service import LocalVerifyBudget

MAX_ORDINAL = (1 << 64) - 1
_WIRE_SEAL = object()
_GRANT_SEAL = object()
_CUSTODY_SEAL = object()


class _NativeBindingSeal:
    __slots__ = ()


_NATIVE_BINDING_SEAL = _NativeBindingSeal()


def _uuid(value: UUID) -> None:
    if type(value) is not UUID or value.int == 0:
        raise LiveError()


def _expiry(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise LiveError()


@dataclass(frozen=True, slots=True, repr=False)
class MuxEpochIdentity(_Private):
    generation: int
    session: bytes

    def __post_init__(self) -> None:
        _integer(self.generation, 1, (1 << 63) - 1)
        _guid(self.session)


@dataclass(frozen=True, slots=True, repr=False)
class MuxSlotIdentity(_Private):
    epoch: MuxEpochIdentity
    channel: bytes
    task: bytes
    stream: int

    def __post_init__(self) -> None:
        if type(self.epoch) is not MuxEpochIdentity:
            raise LiveError()
        _guid(self.channel)
        _guid(self.task)
        _integer(self.stream, 2, 2)


@dataclass(frozen=True, slots=True, repr=False)
class IngressSpan(_Private):
    first: int
    last: int

    def __post_init__(self) -> None:
        _integer(self.first, 1, MAX_ORDINAL)
        _integer(self.last, self.first, MAX_ORDINAL)


@dataclass(frozen=True, slots=True, repr=False)
class IngressChunk(_Private):
    data: bytes
    span: IngressSpan

    def __post_init__(self) -> None:
        if type(self.data) is not bytes or len(self.data) > 1 << 20:
            raise LiveError()
        if type(self.span) is not IngressSpan:
            raise LiveError()


@dataclass(frozen=True, slots=True, repr=False)
class IngressCut(_Private):
    epoch: MuxEpochIdentity
    slot: MuxSlotIdentity
    registration: UUID
    control_sequence: int
    after_ordinal: int
    expires_monotonic: float

    def __post_init__(self) -> None:
        if (
            type(self.epoch) is not MuxEpochIdentity
            or type(self.slot) is not MuxSlotIdentity
            or self.slot.epoch != self.epoch
        ):
            raise LiveError()
        _uuid(self.registration)
        _integer(self.control_sequence, 1, MAX_ORDINAL)
        _integer(self.after_ordinal, 0, MAX_ORDINAL)
        _expiry(self.expires_monotonic)


@dataclass(frozen=True, slots=True, repr=False)
class MuxValidatedFrame(_Private):
    frame: PrivateLiveFrame
    slot: MuxSlotIdentity
    ingress: IngressSpan
    mapped_timestamp_us: int
    slot_ordinal: int
    _seal: InitVar[object] = field(kw_only=True)

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _WIRE_SEAL
            or type(self.frame) is not PrivateLiveFrame
            or type(self.slot) is not MuxSlotIdentity
            or type(self.ingress) is not IngressSpan
        ):
            raise LiveError()
        i, s = self.frame.identity, self.slot
        if (i.generation, i.session, i.channel, i.task) != (
            s.epoch.generation,
            s.epoch.session,
            s.channel,
            s.task,
        ) or self.frame.source_context[1] != s.stream:
            raise LiveError()
        _integer(self.mapped_timestamp_us, -(1 << 63), (1 << 63) - 1)
        _integer(self.slot_ordinal, 1, MAX_ORDINAL)


@dataclass(frozen=True, slots=True, repr=False)
class MuxAcknowledgement(_Private):
    slot: MuxSlotIdentity
    accepted: bool
    warning: bool
    _seal: InitVar[object] = field(kw_only=True)

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _WIRE_SEAL
            or type(self.slot) is not MuxSlotIdentity
            or self.accepted is not True
            or type(self.warning) is not bool
        ):
            raise LiveError()


class MuxPurpose(Enum):
    TRANSPORT = "TRANSPORT"
    SLOT_CONTROL = "SLOT_CONTROL"
    SLOT_RETENTION = "SLOT_RETENTION"
    VIEWER = "VIEWER"


class CleanupScope(Enum):
    VIEWER = "VIEWER"
    DEDICATED_NATIVE = "DEDICATED_NATIVE"
    LAST_VIEWER_AND_DEVICE_EPOCH = "LAST_VIEWER_AND_DEVICE_EPOCH"


@dataclass(frozen=True, slots=True, repr=False)
class MuxScopeKey(_Private):
    tenant_id: UUID
    tenant_epoch: int
    actor_user_id: UUID
    session_digest: bytes
    wall_id: UUID
    store_id: UUID
    device_id: UUID
    connection_id: UUID
    connection_generation: int
    secret_version: UUID
    inventory_revision: int
    worker_epoch: UUID

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id,
            self.actor_user_id,
            self.wall_id,
            self.store_id,
            self.device_id,
            self.connection_id,
            self.secret_version,
            self.worker_epoch,
        ):
            _uuid(value)
        for n in (
            self.tenant_epoch,
            self.connection_generation,
            self.inventory_revision,
        ):
            _integer(n, 1, (1 << 63) - 1)
        if type(self.session_digest) is not bytes or len(self.session_digest) != 32:
            raise LiveError()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class _Grant(_Private):
    scope: MuxScopeKey
    expires_monotonic: float
    _authority: object
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _GRANT_SEAL
            or type(self.scope) is not MuxScopeKey
            or type(self._authority) is not object
        ):
            raise LiveError()
        _expiry(self.expires_monotonic)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class TransportGrant(_Grant):
    native_generation: UUID

    def __post_init__(self, _seal: object) -> None:
        _Grant.__post_init__(self, _seal)
        _uuid(self.native_generation)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class SlotRetentionGrant(_Grant):
    slot: MuxSlotIdentity

    def __post_init__(self, _seal: object) -> None:
        _Grant.__post_init__(self, _seal)
        if type(self.slot) is not MuxSlotIdentity:
            raise LiveError()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class ViewerGrant(SlotRetentionGrant):
    lease_id: UUID
    registration: UUID

    def __post_init__(self, _seal: object) -> None:
        SlotRetentionGrant.__post_init__(self, _seal)
        _uuid(self.lease_id)
        _uuid(self.registration)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class FocusGrant(_Grant):
    lease_id: UUID
    direction: Literal["FORWARD", "RETURN"]
    admitted_monotonic: float

    def __post_init__(self, _seal: object) -> None:
        _Grant.__post_init__(self, _seal)
        _uuid(self.lease_id)
        _expiry(self.admitted_monotonic)
        if (
            self.direction not in ("FORWARD", "RETURN")
            or not self.admitted_monotonic
            < self.expires_monotonic
            <= self.admitted_monotonic + 20
        ):
            raise LiveError()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class MasterReservation(_Private):
    scope: MuxScopeKey
    master_id: UUID
    creator: bool
    transport: TransportGrant
    deadline_monotonic: float
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _GRANT_SEAL
            or type(self.scope) is not MuxScopeKey
            or type(self.transport) is not TransportGrant
            or self.transport.scope != self.scope
            or type(self.creator) is not bool
        ):
            raise LiveError()
        _uuid(self.master_id)
        _expiry(self.deadline_monotonic)
        if self.deadline_monotonic > self.transport.expires_monotonic:
            raise LiveError()


@dataclass(frozen=True, slots=True, repr=False)
class MasterLoginProof(_Private):
    login_accepted: bool
    same_original_session: bool
    serial_matched: bool
    device_matched: bool
    inventory_session_matched: bool
    peer_capability: int

    def __post_init__(self) -> None:
        if any(
            type(v) is not bool
            for v in (
                self.login_accepted,
                self.same_original_session,
                self.serial_matched,
                self.device_matched,
                self.inventory_session_matched,
            )
        ):
            raise LiveError()
        _integer(self.peer_capability, 1, 32767)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class OriginalMuxBinding(_Private):
    """Original provider evidence; SQL identity never manufactures wire identity.

    Only the registered original issuer retains/mints this exact object. Its
    consumer must compare returned object identity, issuer, scope and channel;
    a matching record or caller-supplied ownership boolean is not provenance.
    The type alone does not attest login acceptance or current channel rights.
    """

    scope: MuxScopeKey
    master_id: UUID
    native_generation: UUID
    epoch: MuxEpochIdentity
    channel: bytes
    proof: MasterLoginProof
    _authority: object
    _seal: InitVar[_NativeBindingSeal]

    def __post_init__(self, _seal: _NativeBindingSeal) -> None:
        if (
            _seal is not _NATIVE_BINDING_SEAL
            or type(self.scope) is not MuxScopeKey
            or type(self.epoch) is not MuxEpochIdentity
            or type(self.proof) is not MasterLoginProof
            or type(self._authority) is not object
        ):
            raise LiveError()
        _uuid(self.master_id)
        _uuid(self.native_generation)
        _guid(self.channel)


class OriginalMuxBindingIssuer(Protocol):
    def binding_for(self, channel: bytes) -> OriginalMuxBinding | None: ...


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class MuxOriginalReservation(_Private):
    id: UUID
    kind: Literal["base", "main"]
    worker_epoch: UUID
    _authority: object
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _CUSTODY_SEAL
            or type(self._authority) is not object
            or self.kind not in ("base", "main")
        ):
            raise LiveError()
        _uuid(self.id)
        _uuid(self.worker_epoch)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class ViewerCleanupReceipt(_Private):
    lease_id: UUID
    registration_id: UUID
    decoder_settled: bool
    peer_settled: bool
    media_cleared: bool
    _authority: object
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _CUSTODY_SEAL
            or type(self._authority) is not object
            or any(
                v is not True
                for v in (self.decoder_settled, self.peer_settled, self.media_cleared)
            )
        ):
            raise LiveError()
        _uuid(self.lease_id)
        _uuid(self.registration_id)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class EpochCleanupReceipt(_Private):
    master_id: UUID
    worker_epoch: UUID
    native_generation: UUID
    original_state: Literal["NOT_CREATED", "REAPED"]
    callback_settled: bool
    ipc_settled: bool
    job_settled: bool
    _authority: object
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if (
            _seal is not _CUSTODY_SEAL
            or type(self._authority) is not object
            or self.original_state not in ("NOT_CREATED", "REAPED")
            or any(
                v is not True
                for v in (self.callback_settled, self.ipc_settled, self.job_settled)
            )
        ):
            raise LiveError()
        for value in (self.master_id, self.worker_epoch, self.native_generation):
            _uuid(value)


class EpochReceiptIssuer(Protocol):
    def issued_receipt(self) -> EpochCleanupReceipt | None: ...


class MuxOriginalBudgetPort(Protocol):
    def reserve(self, kind: Literal["base", "main"]) -> MuxOriginalReservation: ...
    def release_confirmed(
        self, reservation: MuxOriginalReservation, receipt: EpochCleanupReceipt
    ) -> None: ...


class MuxViewerHandle(Protocol):
    @property
    def registration(self) -> UUID: ...
    @property
    def cut(self) -> IngressCut: ...
    @property
    def proof(self) -> LocalLiveProof: ...
    def read_frames(
        self, *, max_frames: int, max_bytes: int, deadline_monotonic: float
    ) -> tuple[MuxValidatedFrame, ...]: ...
    def current(self) -> bool: ...
    def attach_retirement(
        self, check: Callable[[], ViewerCleanupReceipt | None]
    ) -> None: ...
    def close(self) -> ViewerCleanupReceipt | None: ...


class OwnedRecorderMaster(Protocol):
    def open_slot(
        self,
        selection: LocalMediaChannel,
        grant: SlotRetentionGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> MuxSlotIdentity: ...
    def attach_viewer(
        self, grant: ViewerGrant, *, budget: LocalVerifyBudget
    ) -> MuxViewerHandle: ...
    def close(self) -> EpochCleanupReceipt | None: ...


class RecorderMasterPort(Protocol):
    def open_master(
        self,
        credentials: LocalDeviceCredentials,
        scope: MuxScopeKey,
        grant: TransportGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> OwnedRecorderMaster: ...


class MuxMediaExecutor(Protocol):
    def start(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalLiveResponse: ...
    def read_mux_frames(
        self, lease_id: UUID, *, max_frames: int, max_bytes: int, deadline_ms: int
    ) -> tuple[MuxValidatedFrame, ...]: ...
    def current(self, lease_id: UUID) -> bool: ...
    def lease(self, lease_id: UUID) -> MediaLease: ...
    def proof(self, lease_id: UUID) -> LocalLiveProof: ...
    def playing(self, lease_id: UUID, proof: LocalLiveProof) -> MediaLease: ...
    def authorize_control(
        self,
        ticket: str,
        purpose: str,
        *,
        deadline_ms: int,
        cancel: Event | None = None,
    ) -> UUID: ...
    def stop(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalLiveResponse: ...
    def finish_stop(
        self, lease_id: UUID, *, correlation_id: str
    ) -> LocalLiveResponse: ...
    def read_frames(
        self, lease_id: UUID, *, max_frames: int, max_bytes: int, deadline_ms: int
    ) -> tuple[PrivateLiveFrame, ...]:
        """Shared implementations must reject the legacy raw-reader boundary."""
        ...

    def shutdown(self) -> bool: ...
