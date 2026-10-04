"""Private binary-only owned worker. Execute with isolated Python (-I)."""

from __future__ import annotations

import struct
import sys
import time
from fractions import Fraction

REQUEST = struct.Struct("!4sBBQ56sIIqII")
RESPONSE = struct.Struct("!4sBQ56sI")
FRAME = struct.Struct("!IIqII")
CONFIG = struct.Struct("!4s9Id")


def read(size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        data = sys.stdin.buffer.read(size - len(value))
        if not data:
            raise ValueError()
        value.extend(data)
    return bytes(value)


def main() -> int:
    sequence = 0
    binding = bytes(56)
    try:
        (
            magic,
            max_width,
            max_height,
            max_packet,
            max_rgb,
            max_frames,
            max_packets,
            max_input,
            max_output,
            max_response,
            seconds,
        ) = CONFIG.unpack(read(CONFIG.size))
        caps = (
            4096,
            2160,
            4 * 1024 * 1024,
            4096 * 2160 * 3,
            1024,
            1024,
            64 * 1024 * 1024,
            256 * 1024 * 1024,
            32,
        )
        limits = (
            max_width,
            max_height,
            max_packet,
            max_rgb,
            max_frames,
            max_packets,
            max_input,
            max_output,
            max_response,
        )
        if (
            magic != b"WDC1"
            or any(not 1 <= v <= c for v, c in zip(limits, caps, strict=True))
            or not 0.05 <= seconds <= 60
        ):
            raise ValueError()
        deadline = time.monotonic() + seconds
        # No PyAV/FFmpeg load until owner has assigned Windows memory/job bounds
        # and written the bounded configuration.
        if len(sys.argv) == 2:
            sys.path.insert(0, sys.argv[1])
        elif len(sys.argv) != 1:
            raise ValueError()
        import av

        if av.__version__ != "19.0.1":
            raise ValueError()

        av.logging.set_level(av.logging.PANIC)
        codec = None
        codec_id = 0
        dimensions = None
        pending = {}
        seen_timestamps = set()
        packets = total_input = frames_total = output_total = 0
        last_ordinal = -1
        while True:
            (
                magic,
                operation,
                incoming_codec,
                incoming_sequence,
                incoming_binding,
                width,
                height,
                ts,
                ordinal,
                length,
            ) = REQUEST.unpack(read(REQUEST.size))
            if (
                time.monotonic() >= deadline
                or magic != b"WDQ1"
                or operation not in (1, 2)
                or incoming_codec not in (1, 2)
                or incoming_sequence != sequence + 1
                or not 1 <= width <= max_width
                or not 1 <= height <= max_height
                or width * height * 3 > max_rgb
                or len(incoming_binding) != 56
                or struct.unpack_from("!Q", incoming_binding)[0] == 0
                or any(incoming_binding[i : i + 16] == bytes(16) for i in (8, 24, 40))
            ):
                raise ValueError()
            if codec is not None and (
                incoming_codec != codec_id
                or incoming_binding != binding
                or dimensions != (width, height)
            ):
                raise ValueError()
            sequence, binding = incoming_sequence, incoming_binding
            if codec is None:
                if operation != 1:
                    raise ValueError()
                codec_id, dimensions = incoming_codec, (width, height)
                codec = av.CodecContext.create("h264" if codec_id == 1 else "hevc", "r")
                codec.thread_count = 1
                codec.copy_opaque = True
                codec.options = {
                    "max_pixels": str(max_width * max_height),
                    "threads": "1",
                }
                codec.open()
            if operation == 1:
                if (
                    not 1 <= length <= max_packet
                    or packets >= max_packets
                    or total_input + length > max_input
                    or ts in seen_timestamps
                    or ordinal <= last_ordinal
                ):
                    raise ValueError()
                payload = read(length)
                if not payload.startswith((b"\x00\x00\x01", b"\x00\x00\x00\x01")):
                    raise ValueError()
                seen_timestamps.add(ts)
                pending[ts] = ordinal
                last_ordinal = ordinal
                packets += 1
                total_input += length
                packet = av.Packet(payload)
                packet.pts = ts
                packet.time_base = Fraction(1, 1000000)
                packet.opaque = (ts, ordinal)
                decoded = codec.decode(packet)
            else:
                if length or ts or ordinal:
                    raise ValueError()
                decoded = codec.decode(None)
            if len(decoded) > max_response or frames_total + len(decoded) > max_frames:
                raise ValueError()
            result = bytearray()
            for frame in decoded:
                if (frame.width, frame.height) != dimensions or frame.pts is None:
                    raise ValueError()
                # AV_CODEC_FLAG_COPY_OPAQUE preserves our exact private source
                # tuple through codec reordering, including decode(None) where
                # PyAV leaves frame.time_base unset. Unknown mapping is refused.
                context = frame.opaque
                if (
                    type(context) is not tuple
                    or len(context) != 2
                    or type(context[0]) is not int
                    or type(context[1]) is not int
                    or frame.pts != context[0]
                    or (
                        frame.time_base is not None
                        and frame.time_base != Fraction(1, 1000000)
                    )
                    or pending.get(context[0]) != context[1]
                ):
                    raise ValueError()
                timestamp = context[0]
                source_ordinal = pending.pop(timestamp)
                size = width * height * 3
                if size > max_rgb or output_total + size > max_output:
                    raise ValueError()
                rgb = frame.reformat(format="rgb24", threads=1)
                plane = rgb.planes[0]
                raw = bytes(plane)
                row_size = width * 3
                pixels = b"".join(
                    raw[row * plane.line_size : row * plane.line_size + row_size]
                    for row in range(height)
                )
                if len(pixels) != size:
                    raise ValueError()
                output_total += size
                result.extend(
                    FRAME.pack(width, height, timestamp, source_ordinal, size)
                )
                result.extend(pixels)
            frames_total += len(decoded)
            if time.monotonic() >= deadline or (operation == 2 and pending):
                raise ValueError()
            sys.stdout.buffer.write(
                RESPONSE.pack(b"WDR1", 0, sequence, binding, len(decoded))
            )
            sys.stdout.buffer.write(result)
            sys.stdout.buffer.flush()
            if operation == 2:
                return 0
    except BaseException:  # noqa: BLE001 - only fixed binary failure can leave worker
        try:
            sys.stdout.buffer.write(RESPONSE.pack(b"WDR1", 1, sequence, binding, 0))
            sys.stdout.buffer.flush()
        except BaseException:  # noqa: BLE001, S110 - no private/native error logging
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
