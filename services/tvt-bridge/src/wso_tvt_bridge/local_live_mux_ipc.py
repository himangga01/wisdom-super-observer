"""Private original-pipe mux control and bounded raw transport.

No deserialized value is a validated picture. Only the retained original codec
parses raw bytes. SQL grant issuers and native original custody remain callers'
responsibilities; this module never loads an SDK or adopts a process by PID.
"""

from __future__ import annotations

import json
import math
import struct
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import InitVar, dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, Literal, NoReturn, SupportsIndex
from uuid import UUID

from wso_core.tvt.local_live_mux import MultiplexLiveCodec, _WireObservation
from wso_core.tvt.local_media_mux_types import (
    MAX_ORDINAL,
    IngressChunk,
    IngressCut,
    IngressSpan,
    MuxAcknowledgement,
    MuxEpochIdentity,
    MuxPurpose,
    MuxSlotIdentity,
    MuxValidatedFrame,
)

if TYPE_CHECKING:
    from wso_core.tvt.local_credentials import LocalDeviceCredentials

MAX_ENVELOPE = 1 << 20
MAX_RAW = MAX_ENVELOPE - 4096
MAX_SLOT_BYTES = 4 << 20
MAX_TOTAL_BYTES = 64 << 20
MAX_SLOT_FRAMES = 16
POLL_SECONDS = 0.05
PRESSURE_SECONDS = 5.0
_FIELDS = {
    "version",
    "generation",
    "session",
    "sequence",
    "operation",
    "purpose",
    "slot",
    "registration",
    "expiry",
    "body",
}
_GLOBAL_LOCK = threading.Lock()
_GLOBAL_BYTES = 0
MAX_HOST_BYTES = 1 << 30
RAW_STAGING_BYTES = 8 << 20
_HOST_BYTES = 0


class MuxIpcError(ValueError):
    def __init__(self) -> None:
        super().__init__("Private mux channel failed.")


_CREDIT_SEAL = object()
_SLOT_CREDITS: dict[MuxSlotIdentity | UUID, tuple[int, int]] = {}
_MEDIA_CREDITS: dict[int, MediaCreditToken] = {}
MediaCreditStage = Literal[
    "callback", "parent", "source", "decode", "rgb", "conversion", "raw"
]
_ENCODED_STAGES = frozenset(("callback", "parent", "source", "decode"))


@dataclass(frozen=True, slots=True, repr=False)
class MediaCreditToken:
    key: MuxSlotIdentity | UUID
    frames: int
    size: int
    stage: MediaCreditStage
    _seal: InitVar[object]

    def __post_init__(self, _seal: object) -> None:
        if _seal is not _CREDIT_SEAL:
            raise MuxIpcError()

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("Private credit cannot be serialized")


def _change_slot_credit(key: MuxSlotIdentity | UUID, frames: int, size: int) -> None:
    # Caller holds the original shared global lock.
    prior_frames, prior_size = _SLOT_CREDITS.get(key, (0, 0))
    value = prior_frames + frames, prior_size + size
    if value[0] < 0 or value[1] < 0:
        raise MuxIpcError()
    if value == (0, 0):
        _SLOT_CREDITS.pop(key, None)
    else:
        _SLOT_CREDITS[key] = value


def reserve_media_credit(
    *,
    slot: MuxSlotIdentity | None,
    registration: UUID | None,
    frames: int,
    bytes: int,
    stage: MediaCreditStage,
) -> MediaCreditToken | None:
    global _HOST_BYTES, _GLOBAL_BYTES
    if (
        slot is not None
        and type(slot) is not MuxSlotIdentity
        or registration is not None
        and (type(registration) is not UUID or not registration.int)
        or slot is None
        and registration is None
        or type(stage) is not str
        or stage not in _ENCODED_STAGES | {"rgb", "conversion", "raw"}
    ):
        raise MuxIpcError()
    _integer(frames, 0, MAX_SLOT_FRAMES)
    _integer(bytes, 1, MAX_HOST_BYTES)
    encoded = stage in _ENCODED_STAGES
    if encoded and (frames == 0 or bytes > MAX_SLOT_BYTES):
        raise MuxIpcError()
    key = slot if slot is not None else registration
    assert key is not None
    with _GLOBAL_LOCK:
        prior_frames, prior_size = _SLOT_CREDITS.get(key, (0, 0))
        if (
            _HOST_BYTES + bytes > MAX_HOST_BYTES
            or encoded
            and (
                prior_frames + frames > MAX_SLOT_FRAMES
                or prior_size + bytes > MAX_SLOT_BYTES
                or _GLOBAL_BYTES + bytes > MAX_TOTAL_BYTES
            )
        ):
            return None
        token = MediaCreditToken(key, frames, bytes, stage, _CREDIT_SEAL)
        _MEDIA_CREDITS[id(token)] = token
        _HOST_BYTES += bytes
        if encoded:
            _GLOBAL_BYTES += bytes
            _change_slot_credit(key, frames, bytes)
        return token


def release_media_credit(token: MediaCreditToken) -> None:
    global _HOST_BYTES, _GLOBAL_BYTES
    with _GLOBAL_LOCK:
        if (
            type(token) is not MediaCreditToken
            or _MEDIA_CREDITS.get(id(token)) is not token
        ):
            raise MuxIpcError()
        del _MEDIA_CREDITS[id(token)]
        _HOST_BYTES -= token.size
        if token.stage in _ENCODED_STAGES:
            _GLOBAL_BYTES -= token.size
            _change_slot_credit(token.key, -token.frames, -token.size)


def media_credit_usage() -> tuple[int, int]:
    with _GLOBAL_LOCK:
        return _HOST_BYTES, _GLOBAL_BYTES


def _integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise MuxIpcError()
    return value


def _deadline(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise MuxIpcError()
    return float(value)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in items:
        if name in result:
            raise MuxIpcError()
        result[name] = value
    return result


def _encode(message: dict[str, Any], raw: bytes = b"") -> bytes:
    metadata = json.dumps(message, separators=(",", ":"), allow_nan=False).encode()
    if len(metadata) > 4092 or len(raw) > MAX_RAW:
        raise MuxIpcError()
    return struct.pack("<I", len(metadata)) + metadata + raw


def _decode(raw: bytes) -> tuple[dict[str, Any], bytes]:
    if type(raw) is not bytes or not 4 <= len(raw) <= MAX_ENVELOPE:
        raise MuxIpcError()
    size = struct.unpack_from("<I", raw)[0]
    if not 1 <= size <= 4092 or size + 4 > len(raw):
        raise MuxIpcError()
    try:
        message = json.loads(raw[4 : 4 + size], object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise MuxIpcError() from None
    if type(message) is not dict or set(message) != _FIELDS:
        raise MuxIpcError()
    return message, raw[4 + size :]


def _slot_data(slot: MuxSlotIdentity | None) -> list[str] | None:
    return None if slot is None else [slot.channel.hex(), slot.task.hex()]


def _scope(
    epoch: MuxEpochIdentity, message: dict[str, Any]
) -> tuple[MuxPurpose, MuxSlotIdentity | None, UUID | None]:
    if (
        type(message["version"]) is not int
        or message["version"] != 1
        or type(message["generation"]) is not int
        or message["generation"] != epoch.generation
        or message["session"] != epoch.session.hex()
    ):
        raise MuxIpcError()
    _integer(message["sequence"], 1, MAX_ORDINAL)
    _deadline(message["expiry"])
    purpose = MuxPurpose(message["purpose"])
    value = message["slot"]
    slot = None
    if value is not None:
        if type(value) is not list or len(value) != 2:
            raise MuxIpcError()
        if any(type(v) is not str or len(v) != 32 for v in value):
            raise MuxIpcError()
        channel, task = (bytes.fromhex(v) for v in value)
        slot = MuxSlotIdentity(epoch, channel, task, 2)
        if _slot_data(slot) != value:
            raise MuxIpcError()
    registration = None
    if message["registration"] is not None:
        value = message["registration"]
        if type(value) is not str:
            raise MuxIpcError()
        registration = UUID(value)
        if not registration.int or registration.hex != value:
            raise MuxIpcError()
    if (
        (
            purpose is MuxPurpose.TRANSPORT
            and (slot is not None or registration is not None)
        )
        or (purpose is not MuxPurpose.TRANSPORT and slot is None)
        or (purpose is MuxPurpose.VIEWER and registration is None)
        or (purpose is not MuxPurpose.VIEWER and registration is not None)
    ):
        raise MuxIpcError()
    return purpose, slot, registration


def make_mux_worker_input(
    credentials: LocalDeviceCredentials, *, generation: int, initial_expiry_ms: int
) -> bytes:
    from wso_core.tvt.local_credentials import LocalDeviceCredentials

    if type(credentials) is not LocalDeviceCredentials:
        raise MuxIpcError()
    _integer(generation, 1, (1 << 63) - 1)
    _integer(initial_expiry_ms, 1, 30000)
    raw = json.dumps(
        {
            "version": 1,
            "mode": "mux",
            "generation": generation,
            "initial_expiry_ms": initial_expiry_ms,
            "credentials": {
                name: getattr(credentials, name)
                for name in ("serial", "country", "username", "password")
            },
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if len(raw) > 16384:
        raise MuxIpcError()
    return raw


def parse_mux_worker_input(raw: bytes) -> tuple[LocalDeviceCredentials, int, int]:
    from wso_core.tvt.local_credentials import LocalDeviceCredentials

    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 16384:
            raise MuxIpcError()
        value = json.loads(raw, object_pairs_hook=_pairs)
        if (
            type(value) is not dict
            or set(value)
            != {"version", "mode", "generation", "initial_expiry_ms", "credentials"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["mode"] != "mux"
        ):
            raise MuxIpcError()
        data = value["credentials"]
        if type(data) is not dict or set(data) != {
            "serial",
            "country",
            "username",
            "password",
        }:
            raise MuxIpcError()
        credentials = LocalDeviceCredentials(**data)
        generation = _integer(value["generation"], 1, (1 << 63) - 1)
        expiry = _integer(value["initial_expiry_ms"], 1, 30000)
        return credentials, generation, expiry
    except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
        raise MuxIpcError() from None


class MuxRemoteAuthority:
    """One original callback, one in-flight raw batch and one control at a time.

    The original private pipe is the authority boundary. The callback must have
    been bound after validated original login by the native provider. Merely
    constructing this inert dispatcher does not establish that login proof.
    """

    def __init__(
        self,
        *,
        epoch: MuxEpochIdentity,
        callback: Any,
        deadline_monotonic: float,
        clock: Callable[[], float] = time.monotonic,
        peer_capability: int | None = None,
        native_send: Callable[[bytes], int] | None = None,
        native_heartbeat: Callable[[], None] | None = None,
        native_slot_allowed: Callable[[MuxSlotIdentity, int], bool] | None = None,
    ) -> None:
        if type(epoch) is not MuxEpochIdentity:
            raise MuxIpcError()
        self.epoch, self.callback, self.clock = epoch, callback, clock
        self.deadline = _deadline(deadline_monotonic)
        if not 0 < self.deadline - self.clock() <= 30:
            raise MuxIpcError()
        self.closed = False
        self._sequence = 0
        self._slots: dict[MuxSlotIdentity, int] = {}
        self._tombstones: set[MuxSlotIdentity] = set()
        self._batch: deque[IngressChunk] = deque()
        self._offset = 0
        self._peer_capability, self._native_send = peer_capability, native_send
        self._native_heartbeat = native_heartbeat
        self._native_slot_allowed = native_slot_allowed
        self._sent: set[MuxSlotIdentity] = set()
        self._last_native_sequence = -1
        self._send_active = False
        self._lock = threading.Lock()

    def handle(self, raw: bytes) -> bytes:
        if not self._lock.acquire(blocking=False):
            self.closed = True
            raise MuxIpcError()
        try:
            if self._send_active:
                raise MuxIpcError()
            request, trailing = _decode(raw)
            purpose, slot, registration = _scope(self.epoch, request)
            expiry = request["expiry"]
            if (
                self.closed
                or trailing
                or request["sequence"] != self._sequence + 1
                or not self.clock() < expiry <= self.deadline
            ):
                raise MuxIpcError()
            self._sequence = request["sequence"]
            operation, body = request["operation"], request["body"]
            expected = {
                "current": MuxPurpose.TRANSPORT,
                "pull": MuxPurpose.TRANSPORT,
                "renew": MuxPurpose.TRANSPORT,
                "register": MuxPurpose.SLOT_CONTROL,
                "open": MuxPurpose.SLOT_CONTROL,
                "heartbeat": MuxPurpose.TRANSPORT,
                "cut": MuxPurpose.VIEWER,
                "park": MuxPurpose.SLOT_RETENTION,
                "tombstone": MuxPurpose.SLOT_CONTROL,
            }
            if operation not in expected or purpose is not expected[operation]:
                raise MuxIpcError()
            if slot in self._tombstones or (
                slot is not None and operation != "register" and slot not in self._slots
            ):
                raise MuxIpcError()
            reply: dict[str, Any] = {}
            payload = b""
            if operation == "register":
                if (
                    type(body) is not dict
                    or set(body) != {"channel_number"}
                    or slot is None
                ):
                    raise MuxIpcError()
                number = _integer(body["channel_number"], 0, 255)
                if (
                    slot in self._slots
                    or len(self._slots) >= 16
                    or number in self._slots.values()
                    or any(
                        s.channel == slot.channel or s.task == slot.task
                        for s in self._slots
                    )
                ):
                    raise MuxIpcError()
                if (
                    self._native_slot_allowed is not None
                    and self._native_slot_allowed(slot, number) is not True
                ):
                    raise MuxIpcError()
                self._slots[slot] = number
            elif operation == "heartbeat":
                if body != {} or self._native_heartbeat is None:
                    raise MuxIpcError()
                self._send_active = True
                self._lock.release()
                try:
                    if self.closed or self.clock() >= min(expiry, self.deadline):
                        raise MuxIpcError()
                    self._native_heartbeat()
                finally:
                    self._lock.acquire()
                    self._send_active = False
            elif operation == "open":
                if (
                    slot is None
                    or slot in self._sent
                    or self._native_send is None
                    or type(self._peer_capability) is not int
                    or type(body) is not dict
                    or set(body) != {"request", "request_guid", "wire_sequence"}
                ):
                    raise MuxIpcError()
                wire_sequence = _integer(body["wire_sequence"], 0, (1 << 31) - 1)
                if wire_sequence <= self._last_native_sequence:
                    raise MuxIpcError()
                if (
                    type(body["request"]) is not str
                    or len(body["request"]) > 2048
                    or type(body["request_guid"]) is not str
                    or len(body["request_guid"]) != 32
                ):
                    raise MuxIpcError()
                request_guid = bytes.fromhex(body["request_guid"])
                wire = bytes.fromhex(body["request"])
                # Command construction only: never feed a second media parser,
                # manufacture ACKs or rewrite wire headers for canonical matching.
                builder = MultiplexLiveCodec(
                    epoch=self.epoch,
                    peer_capability=self._peer_capability,
                    authorize=lambda candidate: candidate == slot,
                )
                try:
                    builder.register_slot(slot, channel_number=self._slots[slot])
                    canonical = builder.open_slot(
                        slot, request_guid=request_guid, sequence=wire_sequence
                    ).private_bytes()
                finally:
                    builder.close()
                if (
                    wire != canonical
                    or wire.hex() != body["request"]
                    or request_guid.hex() != body["request_guid"]
                ):
                    raise MuxIpcError()
                if (
                    self._native_slot_allowed is not None
                    and self._native_slot_allowed(slot, self._slots[slot]) is not True
                ):
                    raise MuxIpcError()
                self._sent.add(slot)
                self._last_native_sequence = wire_sequence
                self._send_active = True
                self._lock.release()
                try:
                    if self.closed or self.clock() >= min(expiry, self.deadline):
                        raise MuxIpcError()
                    sent = self._native_send(wire)
                finally:
                    # Only the original invocation may finish the in-flight send.
                    self._lock.acquire()
                    self._send_active = False
                if type(sent) is not int or sent != len(wire):
                    raise MuxIpcError()
            elif operation == "renew":
                if type(body) is not dict or set(body) != {"deadline"}:
                    raise MuxIpcError()
                renewed = _deadline(body["deadline"])
                if not self.clock() < renewed <= self.clock() + 30:
                    raise MuxIpcError()
                self.deadline = renewed
            elif body != {}:
                raise MuxIpcError()
            elif operation == "cut":
                cut = self.callback.cut_mux_ingress(
                    slot=slot,
                    registration=registration,
                    control_sequence=self._sequence,
                    expires_monotonic=expiry,
                )
                if (
                    type(cut) is not IngressCut
                    or cut.epoch != self.epoch
                    or cut.slot != slot
                    or cut.registration != registration
                    or cut.control_sequence != self._sequence
                    or cut.expires_monotonic != expiry
                ):
                    raise MuxIpcError()
                reply = {"after_ordinal": cut.after_ordinal}
            elif operation == "pull":
                if not self._batch:
                    batch = self.callback.take_mux_batch()
                    if (
                        type(batch) is not tuple
                        or len(batch) > 256
                        or any(type(c) is not IngressChunk for c in batch)
                        or sum(len(c.data) for c in batch) > MAX_ENVELOPE
                    ):
                        raise MuxIpcError()
                    self._batch.extend(batch)
                if self._batch:
                    chunk = self._batch[0]
                    payload = chunk.data[self._offset : self._offset + MAX_RAW]
                    self._offset += len(payload)
                    reply = {"first": chunk.span.first, "last": chunk.span.last}
                    if self._offset == len(chunk.data):
                        self._batch.popleft()
                        self._offset = 0
            elif operation == "tombstone":
                assert slot is not None
                self._tombstones.add(slot)
            if self.closed or self.clock() >= min(expiry, self.deadline):
                raise MuxIpcError()
            return _encode(request | {"body": reply}, payload)
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self.close()
            raise MuxIpcError() from None
        finally:
            self._lock.release()

    def serve_once(self, connection: Any) -> bool:
        if self.closed or self.clock() >= self.deadline:
            self.close()
            return False
        try:
            if not connection.poll(min(POLL_SECONDS, self.deadline - self.clock())):
                return True
            connection.send_bytes(self.handle(connection.recv_bytes(MAX_ENVELOPE)))
            return True
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self.close()
            return False

    def close(self) -> None:
        self.closed = True
        self._batch.clear()
        self._offset = 0


def _owned_invocation[**P, R](
    method: Callable[Concatenate[MuxParentAuthority, P], R],
) -> Callable[Concatenate[MuxParentAuthority, P], R]:
    @wraps(method)
    def invoke(self: MuxParentAuthority, /, *args: P.args, **kwargs: P.kwargs) -> R:
        token = self._enter_invocation()
        try:
            try:
                return method(self, *args, **kwargs)
            except Exception as error:
                # Unwound frames must not keep staged media alive after its credit
                # is returned. Executing outer invocations are cleared by their
                # own wrapper only after they, too, have unwound.
                pending: list[BaseException] = [error]
                cleared: set[int] = set()
                while pending:
                    current = pending.pop()
                    if id(current) in cleared:
                        continue
                    cleared.add(id(current))
                    traceback.clear_frames(current.__traceback__)
                    if current.__cause__ is not None:
                        pending.append(current.__cause__)
                    if current.__context__ is not None:
                        pending.append(current.__context__)
                raise
        finally:
            self._leave_invocation(token)

    return invoke


class MuxParentAuthority:
    def __init__(
        self,
        *,
        epoch: MuxEpochIdentity,
        authorize: Callable[[MuxPurpose, MuxSlotIdentity | None, UUID | None], bool],
        clock: Callable[[], float],
    ) -> None:
        if (
            type(epoch) is not MuxEpochIdentity
            or not callable(authorize)
            or not callable(clock)
        ):
            raise MuxIpcError()
        self.epoch, self.authorize, self.clock = epoch, authorize, clock
        self._owner: Any = None
        self.connection: Any = None
        self.codec: MultiplexLiveCodec | None = None
        self.deadline = 0.0
        self.cancel = threading.Event()
        self.failed = False
        self._sequence = 0
        self._stop = threading.Event()
        self._fenced = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._operation_deadline: float | None = None
        self._operation_cancel: threading.Event | None = None
        self._supplier_deadline: float | None = None
        self._supplier_cancel: threading.Event | None = None
        self._control = threading.Lock()
        self._operation_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._active_invocations: set[object] = set()
        self._scratch_release_pending = False
        self._slots: dict[bytes, MuxSlotIdentity] = {}
        self._tombstones: set[MuxSlotIdentity] = set()
        self._cuts: dict[MuxSlotIdentity, IngressCut] = {}
        self._activated: set[MuxSlotIdentity] = set()
        self._queues: dict[MuxSlotIdentity, deque[MuxValidatedFrame]] = {}
        self._held: dict[int, tuple[MuxValidatedFrame, int]] = {}
        self._usage: dict[MuxSlotIdentity, tuple[int, int]] = {}
        self._raw = b""
        self._raw_span: IngressSpan | None = None
        self._pending_credit: tuple[MuxSlotIdentity, int] | None = None
        self._opened: set[MuxSlotIdentity] = set()
        self._prepared_opens: dict[MuxSlotIdentity, tuple[bytes, bytes, int]] = {}
        self._pressure: float | None = None
        self._raw_reserved = False
        self.scratch_bytes = 0
        self._wire_lock = threading.Lock()
        self._wire_epoch = epoch
        self._wire_binding: (
            tuple[Any, Any, Any, MuxEpochIdentity, MultiplexLiveCodec] | None
        ) = None
        self._wire_values: dict[MuxSlotIdentity, _WireObservation] = {}

    @_owned_invocation
    def bind_original(
        self,
        owner: Any,
        *,
        connection: Any,
        peer_capability: int,
        deadline_monotonic: float,
        cancel: threading.Event,
    ) -> None:
        global _HOST_BYTES
        if self._owner is not None or owner is None or self.failed:
            self._fail()
        self._owner, self.connection = owner, connection
        try:
            self.deadline, self.cancel = _deadline(deadline_monotonic), cancel
            if not 0 < self.deadline - self.clock() <= 30:
                self._fail()
            self._watchdog = threading.Thread(
                target=self._watch, name="mux-original-watchdog", daemon=False
            )
            self._watchdog.start()
            self._check(MuxPurpose.TRANSPORT)
            with _GLOBAL_LOCK:
                if _HOST_BYTES + RAW_STAGING_BYTES > MAX_HOST_BYTES:
                    self._fail()
                _HOST_BYTES += RAW_STAGING_BYTES
                self._raw_reserved = True
            self.codec = MultiplexLiveCodec(
                epoch=self.epoch,
                peer_capability=peer_capability,
                authorize=lambda slot: self._codec_current(slot),
                reserve=self._reserve,
                reserve_scratch=self._reserve_scratch,
                release_scratch=self._release_scratch,
            )
            original_child = getattr(owner, "child", None)
            with self._wire_lock:
                if (
                    self.epoch is self._wire_epoch
                    and self._owner is owner
                    and self.connection is connection
                ):
                    self._wire_binding = (
                        owner,
                        original_child,
                        connection,
                        self._wire_epoch,
                        self.codec,
                    )
        except Exception:  # noqa: BLE001 -- retain partial original on construction failure
            self._fail()

    def _watch(self) -> None:
        while not self._stop.wait(0.01):
            if (
                self.cancel.is_set()
                or self.clock() >= self.deadline
                or self._operation_deadline is not None
                and self.clock() >= self._operation_deadline
                or self._operation_cancel is not None
                and self._operation_cancel.is_set()
                or self._supplier_deadline is not None
                and self.clock() >= self._supplier_deadline
                or self._supplier_cancel is not None
                and self._supplier_cancel.is_set()
                or self._pressure is not None
                and self.clock() >= self._pressure
            ):
                self._fence()
                return

    def _enter_invocation(self) -> object:
        with self._lifecycle_lock:
            if self.failed or self._fenced.is_set():
                raise MuxIpcError()
            token = object()
            self._active_invocations.add(token)
            return token

    def _leave_invocation(self, token: object) -> None:
        with self._lifecycle_lock:
            self._active_invocations.remove(token)
            if self.failed and not self._active_invocations:
                self._settle_locked()

    def _fence(self) -> None:
        with self._lifecycle_lock:
            self._fenced.set()
            self._stop.set()
            self.failed = True
        if self._owner is not None:
            self._owner.request_stop()

    def _settle_locked(self) -> bool:
        # The lifecycle lock and explicit invocation tokens, not reentrant lock
        # acquisition, establish that no supplier/operation still owns a stack.
        if self._active_invocations:
            return False
        if self.codec is not None:
            self.codec.close()
        self._raw = b""
        self._raw_span = None
        self._rollback_credit()
        for queue in self._queues.values():
            while queue:
                self._release(queue.popleft())
        self._queues.clear()
        self._cuts.clear()
        self._activated.clear()
        if self._scratch_release_pending:
            self._release_scratch(self.scratch_bytes)
        return self.scratch_bytes == 0

    def _fail(self) -> NoReturn:
        self._fence()
        with self._lifecycle_lock:
            self._settle_locked()
        raise MuxIpcError() from None

    @contextmanager
    def _operation(
        self, deadline: float, cancel: threading.Event | None = None
    ) -> Iterator[None]:
        # Nested pipe exchanges inherit the whole caller operation's budget.
        # Only this original's serialized caller may install or restore it.
        if not self._operation_lock.acquire(blocking=False):
            self._fail()
        previous_deadline, previous_cancel = (
            self._operation_deadline,
            self._operation_cancel,
        )
        try:
            self._operation_deadline = min(
                _deadline(deadline),
                self.deadline,
                self.deadline if previous_deadline is None else previous_deadline,
            )
            if (
                previous_cancel is not None
                and cancel is not None
                and previous_cancel is not cancel
            ):
                self._fail()  # no replacement of an active caller cancellation owner
            self._operation_cancel = previous_cancel if cancel is None else cancel
            yield
        finally:
            self._operation_deadline, self._operation_cancel = (
                previous_deadline,
                previous_cancel,
            )
            self._operation_lock.release()

    @contextmanager
    def caller_operation(
        self, *, deadline_monotonic: float, cancel: threading.Event
    ) -> Iterator[None]:
        """One retained caller bound covering register, prepare, send and ACK."""
        token = self._enter_invocation()
        try:
            with self._operation(deadline_monotonic, cancel):
                self._check(MuxPurpose.TRANSPORT)
                yield
                self._check(MuxPurpose.TRANSPORT)
        finally:
            self._leave_invocation(token)

    @_owned_invocation
    def _check(
        self,
        purpose: MuxPurpose,
        slot: MuxSlotIdentity | None = None,
        registration: UUID | None = None,
        *,
        deadline: float | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        if deadline is not None:
            _deadline(deadline)

        def expired() -> bool:
            return (
                self.failed
                or self._fenced.is_set()
                or self.cancel.is_set()
                or (cancel is not None and cancel.is_set())
                or (
                    self._operation_cancel is not None
                    and self._operation_cancel.is_set()
                )
                or self.clock()
                >= min(
                    self.deadline,
                    self.deadline if deadline is None else deadline,
                    self.deadline
                    if self._operation_deadline is None
                    else self._operation_deadline,
                )
                or (self._pressure is not None and self.clock() >= self._pressure)
            )

        if expired() or type(purpose) is not MuxPurpose:
            self._fail()
        if (
            purpose is MuxPurpose.TRANSPORT
            and (slot is not None or registration is not None)
            or purpose is not MuxPurpose.TRANSPORT
            and (type(slot) is not MuxSlotIdentity or slot.epoch != self.epoch)
            or purpose is MuxPurpose.VIEWER
            and type(registration) is not UUID
            or purpose is not MuxPurpose.VIEWER
            and registration is not None
            or slot in self._tombstones
        ):
            self._fail()
        previous_supplier = self._supplier_deadline, self._supplier_cancel
        self._supplier_deadline = min(
            self.deadline,
            self.deadline if deadline is None else deadline,
            self.deadline
            if self._operation_deadline is None
            else self._operation_deadline,
        )
        self._supplier_cancel = cancel
        try:
            allowed = self.authorize(purpose, slot, registration) is True
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            allowed = False
        finally:
            self._supplier_deadline, self._supplier_cancel = previous_supplier
        if not allowed or expired():
            self._fail()

    def _codec_current(self, slot: MuxSlotIdentity) -> bool:
        self._check(MuxPurpose.SLOT_RETENTION, slot)
        return True

    @_owned_invocation
    def _rpc(
        self,
        operation: str,
        purpose: MuxPurpose,
        slot: MuxSlotIdentity | None = None,
        registration: UUID | None = None,
        *,
        body: dict[str, Any] | None = None,
        deadline: float | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[dict[str, Any], bytes]:
        if not self._operation_lock.acquire(blocking=False):
            self._fail()
        if not self._control.acquire(blocking=False):
            self._operation_lock.release()
            self._fail()
        previous_deadline, previous_cancel = (
            self._operation_deadline,
            self._operation_cancel,
        )
        try:
            expiry = min(
                self.deadline,
                self.clock() + 30,
                self.deadline if previous_deadline is None else previous_deadline,
                self.deadline if deadline is None else _deadline(deadline),
            )
            if (
                previous_cancel is not None
                and cancel is not None
                and previous_cancel is not cancel
            ):
                self._fail()
            self._operation_deadline, self._operation_cancel = (
                expiry,
                previous_cancel if cancel is None else cancel,
            )
            self._check(purpose, slot, registration, deadline=expiry, cancel=cancel)
            self._sequence = _integer(self._sequence + 1, 1, MAX_ORDINAL)
            request = {
                "version": 1,
                "generation": self.epoch.generation,
                "session": self.epoch.session.hex(),
                "sequence": self._sequence,
                "operation": operation,
                "purpose": purpose.value,
                "slot": _slot_data(slot),
                "registration": None if registration is None else registration.hex,
                "expiry": expiry,
                "body": {} if body is None else body,
            }
            self.connection.send_bytes(_encode(request))
            while True:
                self._check(purpose, slot, registration, deadline=expiry, cancel=cancel)
                if self.connection.poll(
                    min(POLL_SECONDS, max(0, expiry - self.clock()))
                ):
                    break
            reply, raw = _decode(self.connection.recv_bytes(MAX_ENVELOPE))
            self._check(purpose, slot, registration, deadline=expiry, cancel=cancel)
            _scope(self.epoch, reply)
            if any(reply[k] != request[k] for k in _FIELDS - {"body"}):
                self._fail()
            if type(reply["body"]) is not dict or operation != "pull" and raw:
                self._fail()
            if operation not in ("pull", "cut") and reply["body"] != {}:
                self._fail()
            return reply, raw
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self._fail()
        finally:
            self._operation_deadline, self._operation_cancel = (
                previous_deadline,
                previous_cancel,
            )
            self._control.release()
            self._operation_lock.release()

    @_owned_invocation
    def renew(self, *, deadline_monotonic: float) -> None:
        self._check(MuxPurpose.TRANSPORT)
        renewed = _deadline(deadline_monotonic)
        if not self.clock() < renewed <= self.clock() + 30:
            self._fail()
        reply, _ = self._rpc("renew", MuxPurpose.TRANSPORT, body={"deadline": renewed})
        if reply["body"] != {}:
            self._fail()
        self._check(MuxPurpose.TRANSPORT)
        self.deadline = renewed
        self._check(MuxPurpose.TRANSPORT)

    @_owned_invocation
    def register_slot(self, slot: MuxSlotIdentity, *, channel_number: int) -> None:
        try:
            assert self.codec is not None
            self._check(MuxPurpose.SLOT_CONTROL, slot)
            self.codec.register_slot(slot, channel_number=channel_number)
            reply, _ = self._rpc(
                "register",
                MuxPurpose.SLOT_CONTROL,
                slot,
                body={"channel_number": channel_number},
            )
            if reply["body"] != {}:
                self._fail()
            self._slots[slot.channel] = slot
            self._queues[slot] = deque()
            self._usage[slot] = (0, 0)
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self._fail()

    @_owned_invocation
    def prepare_open(
        self, slot: MuxSlotIdentity, *, request_guid: bytes, sequence: int
    ) -> bytes:
        try:
            self._check(MuxPurpose.SLOT_CONTROL, slot)
            assert self.codec is not None
            result = self.codec.open_slot(
                slot, request_guid=request_guid, sequence=sequence
            )
            self._check(MuxPurpose.SLOT_CONTROL, slot)
            raw = result.private_bytes()
            self._prepared_opens[slot] = raw, request_guid, sequence
            return raw
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self._fail()

    @_owned_invocation
    def send_open(
        self,
        slot: MuxSlotIdentity,
        *,
        deadline_monotonic: float,
        cancel: threading.Event,
    ) -> None:
        with self._operation(deadline_monotonic, cancel):
            self._check(MuxPurpose.SLOT_CONTROL, slot)
            prepared = self._prepared_opens.pop(slot, None)
            if prepared is None:
                self._fail()
            raw, request_guid, sequence = prepared
            self._rpc(
                "open",
                MuxPurpose.SLOT_CONTROL,
                slot,
                body={
                    "request": raw.hex(),
                    "request_guid": request_guid.hex(),
                    "wire_sequence": sequence,
                },
                deadline=deadline_monotonic,
                cancel=cancel,
            )
            self._check(MuxPurpose.SLOT_CONTROL, slot)

    @_owned_invocation
    def heartbeat(self, *, deadline_monotonic: float) -> None:
        with self._operation(deadline_monotonic):
            for slot in tuple(self._slots.values()):
                self._check(MuxPurpose.SLOT_RETENTION, slot)
            self._rpc("heartbeat", MuxPurpose.TRANSPORT, deadline=deadline_monotonic)
            for slot in tuple(self._slots.values()):
                self._check(MuxPurpose.SLOT_RETENTION, slot)

    @_owned_invocation
    def admission_cut(
        self,
        slot: MuxSlotIdentity,
        *,
        registration: UUID,
        deadline_monotonic: float,
        cancel: threading.Event,
    ) -> IngressCut:
        if slot in self._cuts or self._slots.get(slot.channel) != slot:
            self._fail()
        reply, _ = self._rpc(
            "cut",
            MuxPurpose.VIEWER,
            slot,
            registration,
            deadline=deadline_monotonic,
            cancel=cancel,
        )
        if set(reply["body"]) != {"after_ordinal"}:
            self._fail()
        try:
            cut = IngressCut(
                self.epoch,
                slot,
                registration,
                reply["sequence"],
                reply["body"]["after_ordinal"],
                reply["expiry"],
            )
        except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
            self._fail()
        self._cuts[slot] = cut
        return cut

    @property
    def pending_raw_bytes(self) -> int:
        return len(self._raw) + (0 if self.codec is None else self.codec.pending_bytes)

    def credit_usage(self, slot: MuxSlotIdentity) -> tuple[int, int]:
        return self._usage[slot]

    def _reserve_scratch(self, size: int) -> bool:
        global _HOST_BYTES
        self._check(MuxPurpose.TRANSPORT)
        _integer(size, 1, MAX_ENVELOPE)
        if self.scratch_bytes or not self._raw_reserved:
            self._fail()
        with _GLOBAL_LOCK:
            if _HOST_BYTES + size > MAX_HOST_BYTES:
                return False
            _HOST_BYTES += size
            self.scratch_bytes = size
        try:
            self._check(MuxPurpose.TRANSPORT)
        except MuxIpcError:
            self._release_scratch(size)
            raise
        return True

    def _release_scratch(self, size: int) -> None:
        global _HOST_BYTES
        if self.scratch_bytes != size or not size:
            self._fail()
        with self._lifecycle_lock:
            if self.failed and self._active_invocations:
                self._scratch_release_pending = True
                return
            with _GLOBAL_LOCK:
                _HOST_BYTES -= size
                self.scratch_bytes = 0
                self._scratch_release_pending = False

    def _reserve(self, slot: MuxSlotIdentity, size: int) -> bool:
        global _GLOBAL_BYTES, _HOST_BYTES
        self._check(MuxPurpose.SLOT_RETENTION, slot)
        if self._pending_credit is not None or self._slots.get(slot.channel) != slot:
            self._fail()
        _integer(size, 1, MAX_SLOT_BYTES)
        frames, used = self._usage[slot]
        with _GLOBAL_LOCK:
            shared_frames, shared_size = _SLOT_CREDITS.get(slot, (0, 0))
            if (
                shared_frames >= MAX_SLOT_FRAMES
                or shared_size + size > MAX_SLOT_BYTES
                or _GLOBAL_BYTES + size > MAX_TOTAL_BYTES
                or _HOST_BYTES + size > MAX_HOST_BYTES
            ):
                return False
            _GLOBAL_BYTES += size
            _HOST_BYTES += size
            self._usage[slot] = frames + 1, used + size
            _change_slot_credit(slot, 1, size)
            self._pending_credit = slot, size
        self._check(MuxPurpose.SLOT_RETENTION, slot)
        return True

    def _rollback_credit(self) -> None:
        global _GLOBAL_BYTES, _HOST_BYTES
        if self._pending_credit is not None:
            slot, size = self._pending_credit
            frames, used = self._usage[slot]
            with _GLOBAL_LOCK:
                _GLOBAL_BYTES -= size
                _HOST_BYTES -= size
                self._usage[slot] = frames - 1, used - size
                _change_slot_credit(slot, -1, -size)
                self._pending_credit = None

    @_owned_invocation
    def open_acknowledged(self, slot: MuxSlotIdentity) -> bool:
        self._check(MuxPurpose.SLOT_CONTROL, slot)
        return slot in self._opened

    def _record_wire(self, item: MuxValidatedFrame | MuxAcknowledgement) -> None:
        # The single-item codec return has passed its final authority checks.
        # This projection carries no raw bytes and installs no observer callback.
        with self._wire_lock:
            binding = self._wire_binding
        if binding is None:
            return
        owner, child, connection, epoch, codec = binding
        if (
            self._owner is not owner
            or getattr(owner, "child", None) is not child
            or self.connection is not connection
            or self.epoch is not epoch
            or self.codec is not codec
            or self._slots.get(item.slot.channel) is not item.slot
        ):
            return
        ack, media = codec.wire_observation(item.slot)
        with self._wire_lock:
            if (
                self._wire_binding is not binding
                or self._owner is not owner
                or getattr(owner, "child", None) is not child
                or self.connection is not connection
                or self.epoch is not epoch
                or self.codec is not codec
                or self._slots.get(item.slot.channel) is not item.slot
                or self.failed
                or self._fenced.is_set()
            ):
                return
            previous_ack, previous_media = self._wire_values.get(
                item.slot, (None, None)
            )
            if type(item) is MuxAcknowledgement and item.accepted:
                if previous_ack is None and ack is not None:
                    self._wire_values[item.slot] = ack, previous_media
            elif type(item) is MuxValidatedFrame and media is not None:
                self._wire_values[item.slot] = previous_ack, media

    def wire_observation(self, slot: MuxSlotIdentity) -> _WireObservation:
        """Read first accepted ACK/latest validated media for this exact original.

        Current suppliers and child inspection run outside state/diagnostic locks.
        A failed observation is absence, not a new fence, publication grant or ACK.
        """
        if type(slot) is not MuxSlotIdentity:
            return None, None
        token: object | None = None
        try:
            token = self._enter_invocation()
            with self._wire_lock:
                binding = self._wire_binding
            if binding is None:
                return None, None
            owner, child, connection, epoch, codec = binding

            def retained() -> bool:
                now = self.clock()
                if (
                    self.failed
                    or self._fenced.is_set()
                    or self.cancel.is_set()
                    or now >= self.deadline
                    or self._pressure is not None
                    and now >= self._pressure
                    or self._wire_binding is not binding
                    or self._owner is not owner
                    or self.connection is not connection
                    or self.epoch is not epoch
                    or self.codec is not codec
                    or self._slots.get(slot.channel) is not slot
                    or slot in self._tombstones
                    or slot.epoch != epoch
                    or owner.confirmed
                    or getattr(owner, "kill_attempted", False)
                    or getattr(owner, "child", None) is not child
                    or connection.closed
                ):
                    return False
                return child is None or child.poll() is None

            if not retained():
                return None, None
            allowed = self.authorize(MuxPurpose.SLOT_RETENTION, slot, None)
            if allowed is not True or not retained():
                return None, None
            with self._wire_lock:
                value = self._wire_values.get(slot, (None, None))
            return value if retained() else (None, None)
        except Exception:  # noqa: BLE001 -- observation absence preserves original lifecycle
            return None, None
        finally:
            if token is not None:
                self._leave_invocation(token)

    def _accept(self, result: tuple[Any, ...]) -> None:
        if len(result) > 1:
            self._fail()
        for item in result:
            if type(item) is not MuxValidatedFrame:
                if self._pending_credit is not None:
                    self._fail()
                self._opened.add(item.slot)
                if type(item) is MuxAcknowledgement:
                    self._record_wire(item)
                continue
            if self._pending_credit is None or self._pending_credit[0] != item.slot:
                self._fail()
            stored = self._pending_credit[1]
            self._check(MuxPurpose.SLOT_RETENTION, item.slot)
            self._record_wire(item)
            cut = self._cuts.get(item.slot)
            if cut is None or item.ingress.first <= cut.after_ordinal:
                self._rollback_credit()
                continue  # parked/pre-cut publication is deliberately ineligible
            self._held[id(item)] = (item, stored)
            self._pending_credit = None
            self._queues[item.slot].append(item)
        if self._pending_credit is not None:
            self._fail()

    @_owned_invocation
    def pump(self, owner: Any, *, deadline_monotonic: float) -> bool:
        with self._operation(deadline_monotonic):
            try:
                if owner is not self._owner:
                    self._fail()
                self._check(MuxPurpose.TRANSPORT, deadline=deadline_monotonic)
                assert self.codec is not None
                self._accept(self.codec.drain(generation=self.epoch.generation))
                if self.codec.blocked:
                    if self._pressure is None:
                        self._pressure = min(
                            self.deadline,
                            deadline_monotonic,
                            self.clock() + PRESSURE_SECONDS,
                        )
                    return False
                self._pressure = None
                # One raw response retained. Do not pull while another chunk is owned.
                if not self._raw:
                    reply, self._raw = self._rpc(
                        "pull", MuxPurpose.TRANSPORT, deadline=deadline_monotonic
                    )
                    body = reply["body"]
                    if not self._raw:
                        if body != {}:
                            self._fail()
                        return True
                    if set(body) != {"first", "last"}:
                        self._fail()
                    self._raw_span = IngressSpan(body["first"], body["last"])
                assert self._raw_span is not None
                capacity = self.codec.input_capacity
                if not capacity:
                    self._fail()
                take = min(len(self._raw), capacity)
                chunk = IngressChunk(self._raw[:take], self._raw_span)
                self._raw = self._raw[take:]
                self._accept(self.codec.feed(chunk, generation=self.epoch.generation))
                self._check(MuxPurpose.TRANSPORT, deadline=deadline_monotonic)
                if self.codec.blocked:
                    self._pressure = min(
                        self.deadline,
                        deadline_monotonic,
                        self.clock() + PRESSURE_SECONDS,
                    )
                    return False
                return True
            except Exception:  # noqa: BLE001 -- fixed private boundary, no exception details
                self._fail()

    @_owned_invocation
    def read_frames(
        self,
        slot: MuxSlotIdentity,
        *,
        cut: IngressCut,
        max_frames: int,
        max_bytes: int,
        deadline_monotonic: float,
    ) -> tuple[MuxValidatedFrame, ...]:
        if type(cut) is not IngressCut or self._cuts.get(slot) is not cut:
            self._fail()
        initial = slot not in self._activated
        deadline = (
            min(deadline_monotonic, cut.expires_monotonic)
            if initial
            else deadline_monotonic
        )
        with self._operation(deadline):
            self._check(MuxPurpose.VIEWER, slot, cut.registration, deadline=deadline)
            _integer(max_frames, 1, MAX_SLOT_FRAMES)
            _integer(max_bytes, 1, MAX_SLOT_BYTES)
            result: list[MuxValidatedFrame] = []
            size = 0
            queue = self._queues[slot]
            # Unreturned candidates stay owned by the queue until the last check.
            # _fail therefore refunds them while preserving genuinely returned ones.
            if initial:
                while queue and not queue[0].frame.key_frame:
                    self._release(queue.popleft())
            for frame in queue:
                stored = self._held[id(frame)][1]
                if len(result) >= max_frames or size + stored > max_bytes:
                    break
                result.append(frame)
                size += stored
            handed_off = tuple(result)
            self._check(MuxPurpose.VIEWER, slot, cut.registration, deadline=deadline)
            if self._cuts.get(slot) is not cut:
                self._fail()
            # The final callback may have changed this queue through a reentrant
            # owner action. Validate the whole staged prefix before any dequeue.
            if len(queue) < len(result) or any(
                queue[index] is not frame for index, frame in enumerate(result)
            ):
                self._fail()
            for _ in result:
                queue.popleft()
            if initial and result:
                self._activated.add(slot)
            return handed_off

    def _release(self, frame: MuxValidatedFrame) -> None:
        global _GLOBAL_BYTES, _HOST_BYTES
        record = self._held.pop(id(frame), None)
        if record is None or record[0] is not frame:
            self._fail()
        frames, size = self._usage[frame.slot]
        with _GLOBAL_LOCK:
            _GLOBAL_BYTES -= record[1]
            _HOST_BYTES -= record[1]
            self._usage[frame.slot] = frames - 1, size - record[1]
            _change_slot_credit(frame.slot, -1, -record[1])

    def release_frames(self, frames: tuple[MuxValidatedFrame, ...]) -> None:
        for frame in frames:
            self._release(frame)

    @_owned_invocation
    def park(self, slot: MuxSlotIdentity) -> None:
        self._rpc("park", MuxPurpose.SLOT_RETENTION, slot)
        self._cuts.pop(slot, None)
        self._activated.discard(slot)
        while self._queues[slot]:
            self._release(self._queues[slot].popleft())

    @_owned_invocation
    def tombstone(self, slot: MuxSlotIdentity) -> None:
        self._rpc("tombstone", MuxPurpose.SLOT_CONTROL, slot)
        assert self.codec is not None
        self.codec.tombstone(slot)
        self._tombstones.add(slot)

    def close(self, timeout: float = 0.2) -> bool:
        global _HOST_BYTES
        self._fence()
        with self._lifecycle_lock:
            if not self._settle_locked():
                return False
        if (
            self._watchdog is not None
            and self._watchdog is not threading.current_thread()
        ):
            if self._watchdog.ident is None:
                return False  # interrupted start is not proof that no thread exists
            self._watchdog.join(timeout)
            if self._watchdog.is_alive():
                return False
        with self._lifecycle_lock:
            # Fencing prohibits any new invocation; keep the explicit check at
            # the actual pipe/refund boundary as well as before the bounded join.
            if not self._settle_locked():
                return False
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception:  # noqa: BLE001 -- retain failed IPC settlement
                    return False
            if (
                self._raw_reserved
                and self._owner is not None
                and self._owner.confirmed is True
            ):
                with _GLOBAL_LOCK:
                    _HOST_BYTES -= RAW_STAGING_BYTES
                    self._raw_reserved = False
        return True

    def confirmed_closed(self) -> bool:
        return (
            self.failed
            and self._owner is not None
            and self._owner.confirmed is True
            and self.close()
        )
