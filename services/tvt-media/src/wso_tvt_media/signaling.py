"""One bounded receive-only video offer. No caller supplied ICE servers."""

from dataclasses import dataclass

from aiortc.sdp import SessionDescription


class SignalingDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("local media signaling unavailable")


@dataclass(frozen=True, slots=True)
class SessionAnswer:
    sdp: str
    type: str = "answer"


def validate_offer(sdp: str) -> None:
    if type(sdp) is not str:
        raise SignalingDenied()
    try:
        size = len(sdp.encode("utf-8"))
    except UnicodeError:
        raise SignalingDenied() from None
    if not 1 <= size <= 65536:
        raise SignalingDenied()
    lines = sdp.splitlines()
    if (
        len(lines) > 512
        or any(len(line) > 2048 for line in lines)
        or sum(line.startswith("a=candidate:") for line in lines) > 64
        or any("\x00" in line for line in lines)
        # RTP extension identifiers are URIs, not resources to fetch.
        or any(
            any(
                token in line.lower()
                for token in ("http:", "https:", "file:", "stun:", "turn:", "turns:")
            )
            and not line.startswith("a=extmap:")
            for line in lines
        )
    ):
        raise SignalingDenied()
    try:
        parsed = SessionDescription.parse(sdp)
        if len(parsed.media) != 1:
            raise SignalingDenied()
        media = parsed.media[0]
        if (
            media.kind != "video"
            or media.direction != "recvonly"
            or not media.rtcp_mux
            or media.port == 0
            or len(media.rtp.codecs) > 32
            or not any(
                codec.mimeType.lower() == "video/vp8" for codec in media.rtp.codecs
            )
        ):
            raise SignalingDenied()
    except (
        ValueError,
        AssertionError,
        IndexError,
        KeyError,
        TypeError,
        AttributeError,
        StopIteration,
    ):
        raise SignalingDenied() from None
