"""Private source-limited N9000 live wire codec; no transport or decoder.

One owner must serialize admission, authority changes, feed, delivery and close.
Q4 greeting version and S4 logged-in version are not peer R3 capability. Supply
R3 explicitly; outgoing wz0 version remains 3. See tvt-local-live-codec.md.
"""

from __future__ import annotations

import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, SupportsIndex

from .frames import FrameTimestamp


class LiveError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid local live state or data")


class UnsupportedLive(LiveError):
    def __init__(self) -> None:
        ValueError.__init__(self, "unsupported local live variant")


class LiveDenied(LiveError):
    def __init__(self) -> None:
        ValueError.__init__(self, "local live authority denied")


class _Private:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: private>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private local live value cannot be serialized")


class _Immutable(_Private):
    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private local live value is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private local live value is immutable")


def _integer(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise LiveError()


def _guid(value: bytes) -> bytes:
    if type(value) is not bytes or len(value) != 16 or value == bytes(16):
        raise LiveError()
    return value


def _raw_timestamp(ticks: int) -> FrameTimestamp:
    # u41.b: retain the established no-derived-time policy for negative Java long.
    micros = (
        ((ticks // 10000) - 11644473600000) * 1000
        if ticks <= 0x7FFFFFFFFFFFFFFF
        else None
    )
    return FrameTimestamp(ticks, micros)


class LiveIdentity(_Immutable):
    """Private immutable connection generation, session, channel and task GUIDs.

    GUIDs are exact GUid.l() wire bytes (UUID bytes_le), never display text.
    A caller must allocate a fresh task for each open and a fresh generation
    for each connection. Neither object construction nor login grants access.
    """

    __slots__ = ("channel", "generation", "session", "task")
    generation: int
    session: bytes
    channel: bytes
    task: bytes

    def __init__(self, *, generation: int, session: bytes, channel: bytes, task: bytes):
        _integer(generation, 1, 0x7FFFFFFFFFFFFFFF)
        object.__setattr__(self, "generation", generation)
        for name, value in (("session", session), ("channel", channel), ("task", task)):
            object.__setattr__(self, name, _guid(value))


class PrivateLiveBytes(_Immutable):
    __slots__ = ("_data",)
    _data: bytes

    def __init__(self, data: bytes) -> None:
        if type(data) is not bytes or len(data) > 32 * 1024 * 1024:
            raise LiveError()
        object.__setattr__(self, "_data", data)

    def private_bytes(self) -> bytes:
        """Explicit private transport/media boundary. Never log or serialize."""
        return self._data


@dataclass(frozen=True, slots=True)
class LiveAcknowledgement:
    command: int


@dataclass(frozen=True, slots=True)
class LiveSummary:
    frames: int
    compressed_bytes: int
    codec: str
    width: int
    height: int


class PrivateLiveFrame(PrivateLiveBytes):
    __slots__ = (
        "_summary",
        "device_timestamp",
        "ecm_timestamp",
        "envelope_timestamp",
        "frame_index",
        "identity",
        "key_frame",
        "source_context",
        "source_envelope",
        "source_extension",
        "source_header",
        "source_outer_headers",
        "source_padding",
    )
    identity: LiveIdentity
    device_timestamp: FrameTimestamp
    ecm_timestamp: FrameTimestamp
    envelope_timestamp: FrameTimestamp
    frame_index: int
    key_frame: bool
    source_context: tuple[int, int, int, int, int]
    source_extension: PrivateLiveBytes
    source_envelope: PrivateLiveBytes
    source_header: PrivateLiveBytes
    source_outer_headers: PrivateLiveBytes
    source_padding: PrivateLiveBytes
    _summary: LiveSummary

    def summary(self) -> LiveSummary:
        return self._summary


class LiveCodec(_Private):
    """Single-use task parser. Any invalid input permanently fences the task.

    Authority callback must check current read AND live rights for this exact
    identity. It may revoke/close the task, but may not feed/open recursively.
    Return is the publication boundary; delivery after returning requires a
    fresh authority check by the original owner in its serialized context.
    """

    __slots__ = (
        "_acked",
        "_assembly",
        "_authorize",
        "_buffer",
        "_busy",
        "_capability",
        "_channel_number",
        "_command",
        "_exclusive_first_task",
        "_format",
        "_fragment",
        "_identity",
        "_last_index",
        "_max_fragments",
        "_max_packet",
        "_max_packets",
        "_max_session",
        "_outer_headers",
        "_packets",
        "_received",
        "_request",
        "_sequence",
        "_state",
        "_stream",
    )

    def __init__(
        self,
        *,
        identity: LiveIdentity,
        peer_capability: int,
        channel_number: int,
        stream: int,
        authorize: Callable[[LiveIdentity], bool],
        exclusive_first_task: bool = False,
        max_packet: int = 1 << 20,
        max_session_bytes: int = 32 << 20,
        max_packets: int = 4096,
        max_fragments: int = 256,
    ) -> None:
        if type(identity) is not LiveIdentity or not callable(authorize):
            raise LiveError()
        if type(exclusive_first_task) is not bool:
            raise LiveError()
        _integer(peer_capability, 1, 32767)
        _integer(channel_number, 0, 255)
        _integer(stream, 1, 2)
        if exclusive_first_task and stream != 1:
            raise UnsupportedLive()
        _integer(max_packet, 172, 32 << 20)
        _integer(max_session_bytes, 1, 1 << 40)
        _integer(max_packets, 1, 1 << 20)
        _integer(max_fragments, 1, 4096)
        self._identity = identity
        self._capability = peer_capability
        self._channel_number = channel_number
        self._stream = stream
        self._authorize = authorize
        # Caller assertion, not parser proof: fresh original socket/generation,
        # first and only task, no replacement/reuse, stream1. Default stays strict.
        self._exclusive_first_task = exclusive_first_task
        self._max_packet = max_packet
        self._max_session = max_session_bytes
        self._max_packets = max_packets
        self._max_fragments = max_fragments
        self._received = self._packets = 0
        self._buffer = bytearray()
        self._assembly = bytearray()
        self._outer_headers = bytearray()
        self._fragment: tuple[int, int, int, int, int] | None = None
        self._state = "new"
        self._busy = False
        self._request = b""
        self._sequence = 0
        self._command = 0
        self._format: tuple[str, int, int] | None = None
        self._last_index: int | None = None
        self._acked = False

    def close(self) -> None:
        self._state = "closed"
        self._exclusive_first_task = False
        self._buffer.clear()
        self._assembly.clear()
        self._outer_headers.clear()
        self._fragment = None
        self._format = None

    def _authority(self, state: str) -> None:
        try:
            allowed = self._authorize(self._identity)
        except Exception:  # noqa: BLE001 - authority implementations may hold secrets
            self.close()
            raise LiveDenied() from None
        if allowed is not True:
            self.close()
            raise LiveDenied() from None
        if self._state != state:
            self.close()
            raise LiveError()

    def open(self, *, request_guid: bytes, sequence: int) -> PrivateLiveBytes:
        return self._request_bytes(request_guid, sequence, closing=False)

    def close_request(self, *, request_guid: bytes, sequence: int) -> PrivateLiveBytes:
        """Fence publication immediately; emit source legacy close for either open."""
        return self._request_bytes(request_guid, sequence, closing=True)

    def _request_bytes(
        self, guid: bytes, sequence: int, *, closing: bool
    ) -> PrivateLiveBytes:
        expected = "open" if closing else "new"
        if self._busy or self._state != expected:
            if self._exclusive_first_task:
                self.close()
            raise LiveError()
        self._busy = True
        try:
            guid = _guid(guid)
            _integer(sequence, 0, 0x7FFFFFFF)
            self._authority(expected)
            i = self._identity
            action = 2 if closing else 1
            header = (
                guid
                + i.session
                + i.channel
                + b"\x02\0\0\0"
                + i.task
                + bytes((action, 0, 0, 0))
            )
            command = 1282 if closing else 1281
            if not closing and self._capability >= 5 and self._stream == 2:
                command = 1285
                channel = str(uuid.UUID(bytes_le=i.channel)).upper()
                task = str(uuid.UUID(bytes_le=i.task)).upper()
                body = (
                    "<?xml version='1.0' encoding='utf-8'?><request version='1.0' "
                    "systemType='NVMS-9000' clientType='SYS'>"
                    f"<destId>{{{channel}}}</destId><taskId>{{{task}}}</taskId>"
                    f"<chNo>{self._channel_number}</chNo><audio>0</audio>"
                    "<streamType>2</streamType></request>"
                ).encode("ascii")
            else:
                body = (
                    i.channel
                    + bytes(52)
                    + struct.pack("<iBBBB", self._stream, self._channel_number, 0, 0, 0)
                )
            inner = (
                struct.pack("<HBBIII", 3, 2, 1, command, sequence, len(body))
                + header
                + body
            )
            if len(inner) + 8 > self._max_packet:
                raise LiveError()
            self._request, self._sequence, self._command = guid, sequence, command
            self._acked = False
            if closing:
                self.close()
                self._state = "closing"
            else:
                self._state = "open"
            return PrivateLiveBytes(struct.pack("<Ii", 825307441, len(inner)) + inner)
        except LiveError:
            self.close()
            raise
        finally:
            self._busy = False

    def feed(
        self, chunk: bytes, *, generation: int
    ) -> tuple[PrivateLiveFrame | LiveAcknowledgement, ...]:
        if self._busy or self._state not in ("open", "closing"):
            raise LiveError()
        self._busy = True
        try:
            if type(generation) is not int or generation != self._identity.generation:
                raise LiveError()
            if type(chunk) is not bytes or len(chunk) > self._max_packet:
                raise LiveError()
            if self._received + len(chunk) > self._max_session:
                raise LiveError()
            if len(self._buffer) + len(chunk) > self._max_packet:
                raise LiveError()
            self._received += len(chunk)
            self._buffer.extend(chunk)
            result: list[PrivateLiveFrame | LiveAcknowledgement] = []
            while len(self._buffer) >= 8:
                # h4 consumes gg0.b only. Preserve gg0.a privately, not as a gate.
                _, size = struct.unpack_from("<Ii", self._buffer)
                if size == -1:
                    if len(self._buffer) < 32:
                        break
                    group, count, total, index, length, tag = struct.unpack_from(
                        "<6i", self._buffer, 8
                    )
                    if not (
                        1 <= count <= self._max_fragments
                        and 1 <= index <= count
                        and 16 <= total <= self._max_packet - 8
                        and 1 <= length <= total
                    ):
                        raise LiveError()
                    if len(self._buffer) < 32 + length:
                        break
                    expected = self._fragment
                    if index == 1:
                        if expected is not None:
                            raise LiveError()
                    elif expected != (group, count, total, index, tag):
                        raise LiveError()
                    if len(self._assembly) + length > total:
                        raise LiveError()
                    self._outer_headers.extend(self._buffer[:32])
                    self._assembly.extend(self._buffer[32 : 32 + length])
                    del self._buffer[: 32 + length]
                    if index == count:
                        if len(self._assembly) != total:
                            raise LiveError()
                        raw = bytes(self._assembly)
                        outer_headers = bytes(self._outer_headers)
                        self._assembly.clear()
                        self._outer_headers.clear()
                        self._fragment = None
                        result.append(self._parse(raw, outer_headers))
                    else:
                        self._fragment = (group, count, total, index + 1, tag)
                    continue
                if self._fragment is not None:
                    raise LiveError()
                if size == 0:
                    del self._buffer[:8]
                    self._count_packet()
                    continue
                if not 16 <= size <= self._max_packet - 8:
                    raise LiveError()
                if len(self._buffer) < size + 8:
                    break
                raw = bytes(self._buffer[8 : size + 8])
                outer_header = bytes(self._buffer[:8])
                del self._buffer[: size + 8]
                result.append(self._parse(raw, outer_header))
            if any(isinstance(item, PrivateLiveFrame) for item in result):
                self._authority("open")
            return tuple(result)
        except LiveError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 - no parser context may expose private bytes
            self.close()
            raise LiveError() from None
        finally:
            self._busy = False

    def _count_packet(self) -> None:
        self._packets += 1
        if self._packets > self._max_packets:
            raise LiveError()

    def _parse(
        self, raw: bytes, outer_headers: bytes
    ) -> PrivateLiveFrame | LiveAcknowledgement:
        self._count_packet()
        if len(raw) < 16:
            raise LiveError()
        _, route, _, command, sequence, _ = struct.unpack_from("<HBBIII", raw)
        # ServerNVMSHeader.a(command)==2 is the0x1 prefix;0x2 is error.
        if command in (0x10000501, 0x10000502):
            base = command & 0x0FFFFFFF
            # Z9's1281/1282 cases consume no body/header fields. Command supplies
            # the acknowledged action; one pending original-owner sequence and
            # generation supplies correlation, never an invented body status.
            if (
                base != self._command
                or sequence != self._sequence
                or self._acked
                or self._state != ("closing" if base == 1282 else "open")
            ):
                raise LiveError()
            self._acked = True
            if base == 1282:
                self.close()
            return LiveAcknowledgement(base)
        # Z9's1285 response has oz0 error semantics; intentionally not a success ack.
        if command != 65537:
            raise UnsupportedLive()
        # Z9 initializes the X7 offset to0, changing it only for routes1/2.
        # No wire task exists on route0. The explicit original-owner first-task
        # assertion plus this task's matching accepted openACK is the binding.
        if route == 0:
            if not (
                self._exclusive_first_task
                and self._acked
                and self._command == 1281
                and self._state == "open"
            ):
                raise UnsupportedLive()
            return self._media(raw[16:], raw[:16], outer_headers)
        # Z9 selects52/72-byte offsets for routes1/2. Only route2 carries the
        # retained task field: taskless routes cannot fence a replaced task.
        if route != 2:
            raise UnsupportedLive()
        if len(raw) < 88 or self._state != "open":
            raise LiveError()
        if raw[68:84] != self._identity.task:
            raise LiveError()
        # X7 resolves ep3.e through s7; it never consumes routing session/channel
        # echoes, action, reserved bytes, wz0 version/encoding/declared length.
        # The original owner/generation binds the session; ep3.e binds channel.
        return self._media(raw[88:], raw[:88], outer_headers)

    def _media(
        self, data: bytes, header: bytes, outer_headers: bytes
    ) -> PrivateLiveFrame:
        if len(data) < 68:
            raise LiveError()
        # X7 0051/0054 ->071e; 0723 admits y41.a==0 only.
        if data[6] != self._stream or data[44] != 0:
            raise UnsupportedLive()
        if data[8:24] != self._identity.channel:
            raise LiveError()
        # Raw-specific ep3/y41/z41 readers: X7 never tests ep3.a (magic), ep3.b
        # (version), ep3.i or y41.d. Never rewrite them to satisfy a file reader.
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
            # X7 0880-089a sends bytes beyond four-byte alignment to Y7.
            raise UnsupportedLive()
        extension = data[68:payload_start]
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
            self._format = (codec, width, height)
        if self._last_index is not None and index <= self._last_index:
            raise LiveError()
        if self._format is None:
            raise UnsupportedLive()
        self._last_index = index
        codec, width, height = self._format
        out = PrivateLiveFrame(data[payload_start:payload_end])
        for name, value in (
            ("identity", self._identity),
            ("source_extension", PrivateLiveBytes(extension)),
            ("source_envelope", PrivateLiveBytes(data[:68])),
            ("source_header", PrivateLiveBytes(header)),
            ("source_outer_headers", PrivateLiveBytes(outer_headers)),
            ("source_padding", PrivateLiveBytes(data[payload_end:])),
            ("device_timestamp", _raw_timestamp(device)),
            ("ecm_timestamp", _raw_timestamp(ecm)),
            ("envelope_timestamp", _raw_timestamp(ticks)),
            ("frame_index", index),
            (
                "key_frame",
                data[7] == 1 or ip_type == 128,
            ),
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
