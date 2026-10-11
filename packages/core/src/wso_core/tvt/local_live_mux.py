"""Immutable per-channel tasks on one original connection; no transport or SDK.

Route 0 has no task on the wire. Its binding is the registered channel's one
accepted original task, never a synthesized wire field. An owner serializes all
methods and retains this codec for the entire original epoch, including parks.
"""

from __future__ import annotations

import struct
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from .local_live import (
    _REFUSAL_REASONS,
    LiveDenied,
    LiveError,
    LiveIdentity,
    LiveRefused,
    LiveSummary,
    PrivateLiveBytes,
    PrivateLiveFrame,
    UnsupportedLive,
    _guid,
    _integer,
    _Private,
    _raw_timestamp,
)
from .local_media_mux_types import (
    _WIRE_SEAL,
    MAX_ORDINAL,
    IngressChunk,
    IngressSpan,
    MuxAcknowledgement,
    MuxEpochIdentity,
    MuxSlotIdentity,
    MuxValidatedFrame,
)
from .local_n9000_notifications import _is_startup_header

_MAX_PACKET = 1 << 20
_MAX_FRAGMENTS = 256
_MAX_SEGMENTS = 4096

_WireAck = tuple[int, int, int, int, bool]
_WireMedia = tuple[int, int, int, int]
_WireObservation = tuple[_WireAck | None, _WireMedia | None]
_NO_WIRE: _WireObservation = (None, None)


class _ConsumedControl(Enum):
    VALIDATED = 1


class SlotMediaClock(_Private):
    """R142 raw nondecreasing time plus lifetime strict index and 24us mapping."""

    def __init__(self) -> None:
        self._raw: int | None = None
        self._mapped: int | None = None
        self._index: int | None = None
        self._ordinal = 0
        self._failed = False

    def accept(self, raw_timestamp_us: int, wire_frame_index: int) -> tuple[int, int]:
        try:
            _integer(raw_timestamp_us, -(1 << 63), (1 << 63) - 1)
            _integer(wire_frame_index, -(1 << 31), (1 << 31) - 1)
            if (
                self._failed
                or (self._raw is not None and raw_timestamp_us < self._raw)
                or (self._index is not None and wire_frame_index <= self._index)
            ):
                raise LiveError()
            mapped = (
                raw_timestamp_us
                if self._mapped is None
                else max(raw_timestamp_us, self._mapped + 24)
            )
            _integer(mapped, -(1 << 63), (1 << 63) - 1)
            _integer(self._ordinal + 1, 1, MAX_ORDINAL)
            self._raw, self._mapped, self._index = (
                raw_timestamp_us,
                mapped,
                wire_frame_index,
            )
            self._ordinal += 1
            return mapped, self._ordinal
        except LiveError:
            self._failed = True
            raise


@dataclass(repr=False)
class _Slot:
    identity: MuxSlotIdentity
    channel_number: int
    state: str = "registered"
    format: tuple[str, int, int] | None = None
    clock: SlotMediaClock = field(default_factory=SlotMediaClock)
    wire_ack: _WireAck | None = None
    wire_media: _WireMedia | None = None


class MultiplexLiveCodec(_Private):
    """Optional credit mode emits at most one item per feed/drain.

    A successful reserve belongs to the serialized caller's pending ledger:
    transfer it only with the returned frame, and settle it on any exception.
    The codec never releases encoded credit. Fragment scratch hooks are paired;
    their owner checks transport authority and charges global host bytes before
    returning True. Scratch refunds occur after the old input is consumed (or
    all raw storage is cleared on failure). No callback runs with exported views.
    """

    def __init__(
        self,
        *,
        epoch: MuxEpochIdentity,
        peer_capability: int,
        authorize: Callable[[MuxSlotIdentity], bool],
        reserve: Callable[[MuxSlotIdentity, int], bool] | None = None,
        reserve_scratch: Callable[[int], bool] | None = None,
        release_scratch: Callable[[int], None] | None = None,
    ) -> None:
        if type(epoch) is not MuxEpochIdentity or not callable(authorize):
            raise LiveError()
        if reserve is not None and not callable(reserve):
            raise LiveError()
        if (reserve_scratch is None) != (release_scratch is None) or (
            reserve_scratch is not None
            and (not callable(reserve_scratch) or not callable(release_scratch))
        ):
            raise LiveError()
        _integer(peer_capability, 1, 32767)
        self._epoch = epoch
        self._capability = peer_capability
        self._authorize = authorize
        self._reserve = reserve
        self._reserve_scratch = reserve_scratch
        self._release_scratch = release_scratch
        self._blocked = False
        self._assembled = False
        self._slots: dict[bytes, _Slot] = {}
        self._pending: tuple[_Slot, int, int] | None = None
        self._sequence = -1
        self._closed = False
        self._busy = False
        self._buffer = bytearray()
        self._spans: deque[tuple[int, IngressSpan]] = deque()
        self._assembly = bytearray()
        self._outer_headers = bytearray()
        self._assembly_span: IngressSpan | None = None
        self._fragment: tuple[int, int, int, int, int] | None = None
        self._received = self._packets = self._last_ingress = 0

    def close(self) -> None:
        self._closed = True
        self._buffer.clear()
        self._spans.clear()
        self._assembly.clear()
        self._outer_headers.clear()
        self._assembly_span = None
        self._fragment = None
        self._pending = None
        self._blocked = self._assembled = False

    @property
    def pending_bytes(self) -> int:
        """Raw bytes retained, including partial assembly and original headers."""
        return len(self._buffer) + len(self._assembly) + len(self._outer_headers)

    @property
    def input_capacity(self) -> int:
        if self._closed:
            return 0
        retained = (
            self.pending_bytes if self._reserve is not None else len(self._buffer)
        )
        return _MAX_PACKET - retained

    @property
    def blocked(self) -> bool:
        return self._blocked

    def wire_observation(self, slot: MuxSlotIdentity) -> _WireObservation:
        """Parsed scalar facts only; the original caller owns synchronization/current.

        No authority callback or parser action occurs here. Unavailable/foreign
        queries do not mutate the codec or infer an ACK from registered state.
        """
        if self._closed or self._busy or type(slot) is not MuxSlotIdentity:
            return _NO_WIRE
        owned = self._slots.get(slot.channel)
        if owned is None or owned.identity is not slot or owned.state == "tombstoned":
            return _NO_WIRE
        return owned.wire_ack, owned.wire_media

    def _check(self) -> None:
        if self._closed or self._busy:
            self.close()
            raise LiveError()

    def _slot(self, slot: MuxSlotIdentity) -> _Slot:
        if type(slot) is not MuxSlotIdentity or slot.epoch != self._epoch:
            raise LiveError()
        owned = self._slots.get(slot.channel)
        if owned is None or owned.identity != slot:
            raise LiveError()
        return owned

    def _authority(self, slot: _Slot) -> None:
        try:
            allowed = self._authorize(slot.identity)
        except Exception:  # noqa: BLE001 - authority may retain private device data
            self.close()
            raise LiveDenied() from None
        if allowed is not True:
            self.close()
            raise LiveDenied()
        if self._closed or slot.state == "tombstoned":
            raise LiveError()

    def register_slot(self, slot: MuxSlotIdentity, *, channel_number: int) -> None:
        self._check()
        try:
            _integer(channel_number, 0, 255)
            if (
                type(slot) is not MuxSlotIdentity
                or slot.epoch != self._epoch
                or slot.channel in self._slots
                or len(self._slots) >= 16
            ):
                raise LiveError()
            if any(
                s.identity.task == slot.task or s.channel_number == channel_number
                for s in self._slots.values()
            ):
                raise LiveError()
            self._slots[slot.channel] = _Slot(slot, channel_number)
        except LiveError:
            self.close()
            raise

    def open_slot(
        self, slot: MuxSlotIdentity, *, request_guid: bytes, sequence: int
    ) -> PrivateLiveBytes:
        self._check()
        self._busy = True
        try:
            owned = self._slot(slot)
            _guid(request_guid)
            _integer(sequence, 0, (1 << 31) - 1)
            if (
                owned.state != "registered"
                or self._pending is not None
                or sequence <= self._sequence
            ):
                raise LiveError()
            self._authority(owned)
            header = (
                request_guid
                + self._epoch.session
                + slot.channel
                + b"\x02\0\0\0"
                + slot.task
                + b"\x01\0\0\0"
            )
            command = 1285 if self._capability >= 5 else 1281
            if command == 1285:
                channel, task = (
                    str(UUID(bytes_le=slot.channel)).upper(),
                    str(UUID(bytes_le=slot.task)).upper(),
                )
                body = (
                    "<?xml version='1.0' encoding='utf-8'?><request version='1.0' "
                    "systemType='NVMS-9000' clientType='SYS'>"
                    f"<destId>{{{channel}}}</destId><taskId>{{{task}}}</taskId>"
                    f"<chNo>{owned.channel_number}</chNo><audio>0</audio>"
                    "<streamType>2</streamType></request>"
                ).encode("ascii")
            else:
                body = (
                    slot.channel
                    + bytes(52)
                    + struct.pack("<iBBBB", 2, owned.channel_number, 0, 0, 0)
                )
            raw = (
                struct.pack("<HBBIII", 3, 2, 1, command, sequence, len(body))
                + header
                + body
            )
            self._sequence = sequence
            self._pending = (owned, command, sequence)
            owned.state = "pending"
            return PrivateLiveBytes(struct.pack("<Ii", 825307441, len(raw)) + raw)
        except LiveError:
            self.close()
            raise
        finally:
            self._busy = False

    def tombstone(self, slot: MuxSlotIdentity) -> None:
        self._check()
        try:
            owned = self._slot(slot)
            if owned.state != "active":
                raise LiveError()
            owned.state = "tombstoned"
        except LiveError:
            self.close()
            raise

    def _consume_span(self, count: int) -> IngressSpan:
        first, last = self._spans[0][1].first, 0
        while count:
            length, span = self._spans.popleft()
            last = span.last
            used = min(count, length)
            count -= used
            if used < length:
                self._spans.appendleft((length - used, span))
        return IngressSpan(first, last)

    def _count(self) -> None:
        _integer(self._packets + 1, 1, MAX_ORDINAL)
        self._packets += 1

    def feed(
        self, chunk: IngressChunk, *, generation: int
    ) -> tuple[MuxValidatedFrame | MuxAcknowledgement, ...]:
        if type(chunk) is not IngressChunk:
            self.close()
            raise LiveError()
        return self._feed(chunk, generation=generation)

    def drain(
        self, *, generation: int
    ) -> tuple[MuxValidatedFrame | MuxAcknowledgement, ...]:
        """Retry the retained head. No ingress ordinal or received counter moves."""
        return self._feed(None, generation=generation)

    def _feed(
        self, chunk: IngressChunk | None, *, generation: int
    ) -> tuple[MuxValidatedFrame | MuxAcknowledgement, ...]:
        self._check()
        self._busy = True
        try:
            if (
                (chunk is not None and type(chunk) is not IngressChunk)
                or type(generation) is not int
                or generation != self._epoch.generation
            ):
                raise LiveError()
            if chunk is not None:
                if (
                    chunk.span.first < self._last_ingress
                    or len(chunk.data) > self.input_capacity
                ):
                    raise LiveError()
                _integer(self._received + len(chunk.data), 0, MAX_ORDINAL)
                self._received += len(chunk.data)
                self._last_ingress = chunk.span.last
                if chunk.data:
                    if len(self._spans) >= _MAX_SEGMENTS:
                        raise LiveError()
                    self._spans.append((len(chunk.data), chunk.span))
                    self._buffer.extend(chunk.data)
            self._blocked = False
            result: list[MuxValidatedFrame | MuxAcknowledgement] = []
            while self._assembled or len(self._buffer) >= 8:
                if self._assembled:
                    if self._assembly_span is None:
                        raise LiveError()
                    item = self._deliver(
                        self._assembly,
                        0,
                        len(self._assembly),
                        self._outer_headers,
                        len(self._outer_headers),
                        self._assembly_span,
                    )
                    if item is None:
                        break
                    if isinstance(item, _ConsumedControl):
                        raise LiveError()
                    self._count()
                    self._assembly.clear()
                    self._outer_headers.clear()
                    self._assembly_span = None
                    self._assembled = False
                    result.append(item)
                    if self._reserve is not None:
                        break
                    continue
                _, size = struct.unpack_from("<Ii", self._buffer)
                if size == -1:
                    if len(self._buffer) < 32:
                        break
                    group, count, total, index, length, tag = struct.unpack_from(
                        "<6i", self._buffer, 8
                    )
                    if not (
                        1 <= count <= _MAX_FRAGMENTS
                        and 1 <= index <= count
                        and 16 <= total <= _MAX_PACKET - 8
                        and 1 <= length <= total
                        and length + 32 <= _MAX_PACKET
                    ):
                        raise LiveError()
                    if len(self._buffer) < 32 + length:
                        break
                    if (
                        (index == 1 and self._fragment is not None)
                        or (
                            index != 1
                            and self._fragment != (group, count, total, index, tag)
                        )
                        or len(self._assembly) + length > total
                    ):
                        raise LiveError()
                    if not self._move_fragment(length):
                        break
                    span = self._consume_span(32 + length)
                    self._assembly_span = (
                        span
                        if self._assembly_span is None
                        else IngressSpan(self._assembly_span.first, span.last)
                    )
                    if index == count:
                        if len(self._assembly) != total:
                            raise LiveError()
                        self._fragment = None
                        self._assembled = True
                    else:
                        self._fragment = (group, count, total, index + 1, tag)
                    continue
                if self._fragment is not None:
                    raise LiveError()
                if size == 0:
                    self._consume_span(8)
                    del self._buffer[:8]
                    self._count()
                    continue
                if not 16 <= size <= _MAX_PACKET - 8:
                    raise LiveError()
                if len(self._buffer) < size + 8:
                    break
                ingress = self._peek_span(size + 8)
                item = self._deliver(self._buffer, 8, size, self._buffer, 8, ingress)
                if item is None:
                    break
                self._count()
                self._consume_span(size + 8)
                del self._buffer[: size + 8]
                if isinstance(item, _ConsumedControl):
                    continue
                result.append(item)
                if self._reserve is not None:
                    break
            # A sibling callback can revoke an earlier result in this same batch.
            for slot in {item.slot for item in result}:
                self._authority(self._slot(slot))
            if self._closed:
                raise LiveError()
            return tuple(result)
        except LiveError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 - never expose parser/private byte context
            self.close()
            raise LiveError() from None
        finally:
            self._busy = False

    def _move_fragment(self, length: int) -> bool:
        # The old raw input remains live while assembly grows. Charge that
        # temporary duplicate before extend, not just the final retained sum.
        scratch = length + 32
        claimed = False
        try:
            if self._reserve_scratch is not None:
                result = self._reserve_scratch(scratch)
                claimed = result is True
                if self._closed or type(result) is not bool:
                    raise LiveError()
                if not result:
                    self._blocked = True
                    return False
            elif self._reserve is not None:
                raise LiveError()
            with (
                memoryview(self._buffer) as raw,
                raw[:32] as header,
                raw[32:scratch] as payload,
            ):
                self._outer_headers.extend(header)
                self._assembly.extend(payload)
            del self._buffer[:scratch]
            return True
        except Exception:  # discard duplicate storage before refund
            self.close()
            raise
        finally:
            if claimed:
                assert self._release_scratch is not None
                self._release_scratch(scratch)
                if self._closed:
                    raise LiveError()

    def _peek_span(self, count: int) -> IngressSpan:
        first = self._spans[0][1].first
        for length, span in self._spans:
            count -= length
            if count <= 0:
                return IngressSpan(first, span.last)
        raise LiveError()

    def _deliver(
        self,
        storage: bytearray,
        start: int,
        size: int,
        outer_storage: bytearray,
        outer_size: int,
        ingress: IngressSpan,
    ) -> MuxValidatedFrame | MuxAcknowledgement | _ConsumedControl | None:
        # Never hold an exported bytearray view across arbitrary callbacks.
        with memoryview(storage) as whole, whole[start : start + size] as raw:
            media_slot = self._preflight(raw)
        if media_slot is not None:
            self._authority(media_slot)
            if self._reserve is not None:
                reserved = self._reserve(media_slot.identity, size + outer_size)
                self._authority(media_slot)
                if type(reserved) is not bool:
                    raise LiveError()
                if not reserved:
                    self._blocked = True
                    return None
        elif self._pending is not None:
            self._authority(self._pending[0])
        with (
            memoryview(storage) as whole,
            whole[start : start + size] as raw,
            memoryview(outer_storage) as outer_whole,
            outer_whole[:outer_size] as outer,
        ):
            return self._parse(raw, outer, ingress)

    def _preflight(self, raw: memoryview) -> _Slot | None:
        """Classify and check framing bounds before any encoded reservation/copy."""
        if len(raw) < 16:
            raise LiveError()
        _, route, _, command, _, _ = struct.unpack_from("<HBBIII", raw)
        if command != 65537:
            return None
        if route not in (0, 2):
            raise UnsupportedLive()
        offset = 16 if route == 0 else 88
        if len(raw) < offset + 68:
            raise LiveError()
        slot = self._slots.get(bytes(raw[offset + 8 : offset + 24]))
        if slot is None or slot.state != "active":
            raise UnsupportedLive()
        if route == 2 and raw[68:84] != slot.identity.task:
            raise LiveError()
        with raw[offset:] as data:
            if data[6] != 2 or data[44] != 0:
                raise UnsupportedLive()
            body = struct.unpack_from("<i", data, 24)[0]
            payload = struct.unpack_from("<i", data, 48)[0]
            extension = data[45]
            if body < 24 or 44 + body != len(data) or payload < 0:
                raise LiveError()
            if extension > 127:
                raise UnsupportedLive()
            end = 68 + extension + payload
            if end > len(data) or (
                extension and (extension < 12 or 12 < extension < 17)
            ):
                raise LiveError()
            if len(data) - end > (-payload) % 4:
                raise UnsupportedLive()
        return slot

    def _parse(
        self, raw: memoryview, outer: memoryview, ingress: IngressSpan
    ) -> MuxValidatedFrame | MuxAcknowledgement | _ConsumedControl:
        if len(raw) < 16:
            raise LiveError()
        version, route, wire_kind, command, sequence, declared = struct.unpack_from(
            "<HBBIII", raw
        )
        if command in (2561, 2562, 2563):
            # Match the greeting-bound N9000 ordinary notification profile.
            # Fragments remain unsupported; no private body is decoded/copied.
            if (
                len(outer) != 8
                or struct.unpack_from("<Ii", outer) != (825307441, len(raw))
                or not 1 <= version <= 32767
                or declared != len(raw) - 16
                or not _is_startup_header(command, sequence, route, wire_kind, declared)
            ):
                raise UnsupportedMuxPacket(command, route)
            return _ConsumedControl.VALIDATED
        if command in (0x10000501, 0x10000505):
            if self._pending is None:
                raise LiveError()
            owned, expected, expected_sequence = self._pending
            if (
                command != 0x10000000 | expected
                or sequence != expected_sequence
                or owned.state != "pending"
            ):
                raise LiveError()
            warning = False
            if expected == 1285:
                if len(raw) < 92:
                    raise LiveError()
                warning = struct.unpack_from("<i", raw, 88)[0] == 0x20000060
            owned.state = "active"
            self._pending = None
            result = MuxAcknowledgement(owned.identity, True, warning, _seal=_WIRE_SEAL)
            if owned.wire_ack is None:
                owned.wire_ack = route, wire_kind, command, sequence, warning
            return result
        if 0x20000000 <= command < 0x30000000:
            if self._pending is None:
                raise UnsupportedLive()
            owned, expected, _ = self._pending
            if (
                command & 0x0FFFFFFF != expected
                or len(raw) < 92
                or raw[68:84] != owned.identity.task
                or owned.state != "pending"
            ):
                raise UnsupportedLive()
            code = struct.unpack_from("<i", raw, 88)[0]
            raise LiveRefused(_REFUSAL_REASONS.get(code, "refused"))
        if command != 65537 or route not in (0, 2):
            raise UnsupportedMuxPacket(command, route)
        offset = 16 if route == 0 else 88
        if len(raw) < offset + 68:
            raise LiveError()
        media_slot = self._slots.get(bytes(raw[offset + 8 : offset + 24]))
        if media_slot is None or media_slot.state != "active":
            raise UnsupportedLive()
        if route == 2 and raw[68:84] != media_slot.identity.task:
            raise LiveError()
        with raw[offset:] as data, raw[:offset] as header:
            frame = self._media(media_slot, data, header, outer)
        stamp = frame.device_timestamp.unix_microseconds
        if stamp is None:
            raise LiveError()
        mapped, ordinal = media_slot.clock.accept(stamp, frame.frame_index)
        validated = MuxValidatedFrame(
            frame, media_slot.identity, ingress, mapped, ordinal, _seal=_WIRE_SEAL
        )
        media_slot.wire_media = route, wire_kind, command, sequence
        return validated

    def _media(
        self, owned: _Slot, data: memoryview, header: memoryview, outer: memoryview
    ) -> PrivateLiveFrame:
        # Independent stateful raw reader: never call or relax LiveCodec._media.
        if data[6] != 2 or data[44] != 0:
            raise UnsupportedLive()
        body_length, ticks, index, _ = struct.unpack_from("<iQii", data, 24)
        frame_type, ext_length, ip_type, _, payload_length, device, ecm = (
            struct.unpack_from("<BBBBiQQ", data, 44)
        )
        if body_length < 24 or 44 + body_length != len(data) or payload_length < 0:
            raise LiveError()
        if ext_length > 127:
            raise UnsupportedLive()
        payload_start = 68 + ext_length
        payload_end = payload_start + payload_length
        if payload_end > len(data):
            raise LiveError()
        if len(data) - payload_end > (-payload_length) % 4:
            raise UnsupportedLive()
        extension = bytes(data[68:payload_start])
        if ext_length:
            if ext_length < 12 or 12 < ext_length < 17:
                raise LiveError()
            if ext_length >= 17 and extension[16] != 0:
                raise UnsupportedLive()
            fourcc = extension[4:8]
            if fourcc == b"H264":
                codec = "h264"
            elif fourcc in (b"H265", b"HEVC"):
                codec = "h265"
            else:
                raise UnsupportedLive()
            width, height = struct.unpack_from("<hh", extension, 8)
            if width <= 0 or height <= 0:
                raise LiveError()
            owned.format = (codec, width, height)
        if owned.format is None:
            raise UnsupportedLive()
        codec, width, height = owned.format
        slot = owned.identity
        identity = LiveIdentity(
            generation=slot.epoch.generation,
            session=slot.epoch.session,
            channel=slot.channel,
            task=slot.task,
        )
        out = PrivateLiveFrame(bytes(data[payload_start:payload_end]))
        for name, value in (
            ("identity", identity),
            ("source_extension", PrivateLiveBytes(extension)),
            ("source_envelope", PrivateLiveBytes(bytes(data[:68]))),
            ("source_header", PrivateLiveBytes(bytes(header))),
            ("source_outer_headers", PrivateLiveBytes(bytes(outer))),
            ("source_padding", PrivateLiveBytes(bytes(data[payload_end:]))),
            ("device_timestamp", _raw_timestamp(device)),
            ("ecm_timestamp", _raw_timestamp(ecm)),
            ("envelope_timestamp", _raw_timestamp(ticks)),
            ("frame_index", index),
            ("key_frame", data[7] == 1 or ip_type == 128),
            (
                "source_context",
                (
                    struct.unpack_from("<h", data, 4)[0],
                    data[6],
                    data[7],
                    frame_type,
                    ip_type,
                ),
            ),
            (
                "_summary",
                LiveSummary(1, len(out.private_bytes()), codec, width, height),
            ),
        ):
            object.__setattr__(out, name, value)
        return out


class UnsupportedMuxPacket(UnsupportedLive):
    """Fixed parsed numeric facts for the existing unsupported packet boundary."""

    def __init__(self, command: int, route: int) -> None:
        if (
            type(command) is not int
            or not 0 <= command <= 0xFFFFFFFF
            or type(route) is not int
            or not 0 <= route <= 255
        ):
            raise UnsupportedLive()
        self.command, self.route = command, route
        super().__init__()
