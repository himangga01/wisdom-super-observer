"""Bound RGB and PTS adaptation; neither a decoder nor an authority source."""

from dataclasses import dataclass
from fractions import Fraction

from av import VideoFrame
from wso_core.tvt.windows_decode import DecodeBinding, PrivateRGBFrame


class MediaDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("local media unavailable")


@dataclass(frozen=True, slots=True)
class FrameLimits:
    max_width: int = 4096
    max_height: int = 2160
    max_frame_bytes: int = 16 * 1024 * 1024

    def validate(self) -> None:
        for value, high in (
            (self.max_width, 4096),
            (self.max_height, 2160),
            (self.max_frame_bytes, 4096 * 2160 * 3),
        ):
            if type(value) is not int or not 1 <= value <= high:
                raise MediaDenied()


def validate_frame(
    frame: PrivateRGBFrame, binding: DecodeBinding, limits: FrameLimits
) -> bytes:
    limits.validate()
    if (
        type(frame) is not PrivateRGBFrame
        or type(frame.binding) is not DecodeBinding
        or frame.binding._wire() != binding._wire()
        or type(frame.width) is not int
        or type(frame.height) is not int
        or not 1 <= frame.width <= limits.max_width
        or not 1 <= frame.height <= limits.max_height
        or type(frame.timestamp_us) is not int
        or not -(2**63) <= frame.timestamp_us <= 2**63 - 1
        or type(frame.ordinal) is not int
        or not 1 <= frame.ordinal <= 2**63 - 1
    ):
        raise MediaDenied()
    data = frame.private_rgb()
    if (
        type(data) is not bytes
        or len(data) != frame.width * frame.height * 3
        or len(data) > limits.max_frame_bytes
    ):
        raise MediaDenied()
    return data


def frame_to_video(
    frame: PrivateRGBFrame, binding: DecodeBinding, limits: FrameLimits
) -> VideoFrame:
    data = validate_frame(frame, binding, limits)
    video = VideoFrame(frame.width, frame.height, "rgb24")
    plane = video.planes[0]
    row_bytes = frame.width * 3
    if plane.line_size == row_bytes:
        plane.update(data)
    else:
        padded = bytearray(plane.buffer_size)
        for row in range(frame.height):
            padded[row * plane.line_size : row * plane.line_size + row_bytes] = data[
                row * row_bytes : (row + 1) * row_bytes
            ]
        plane.update(bytes(padded))
    video.pts = frame.timestamp_us
    video.time_base = Fraction(1, 1_000_000)
    return video
