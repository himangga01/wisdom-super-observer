"""Bounded APK ep3/y41 parsing of post-JNI callback bytes.

SHFL is evidenced by an app writer, not an observed live callback. This module
does not classify worker tasks, decrypt with keys, decode media, or describe a
socket protocol. Extension interpretation must come from the worker context.
"""

import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum


class FrameParseError(ValueError):
    """Malformed bounded callback; messages never contain callback bytes."""


class UnsupportedFrame(FrameParseError):
    """A callback or interpretation outside the evidenced bounded format."""


class EncryptedPayloadUnavailable(FrameParseError):
    """An encrypted prefix has not passed the explicit decrypt/CRC boundary."""


class FrameDecryptionError(FrameParseError):
    """The supplied decryptor did not produce a verified complete prefix."""


class ExtensionContext(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    OPAQUE = "opaque"


@dataclass(frozen=True, slots=True)
class FrameTimestamp:
    ticks: int
    unix_microseconds: int | None


@dataclass(frozen=True, slots=True)
class EnvelopeHeader:
    magic: bytes
    version: int
    kind: int
    key_marker: int
    guid: bytes
    body_length: int
    timestamp: FrameTimestamp
    frame_index: int
    other_value: int


@dataclass(frozen=True, slots=True)
class FrameHeader:
    # Bytes stay raw u8, including Java's signed-byte IP marker -128 (0x80).
    frame_type: int
    extension_length: int
    ip_frame_type: int
    reserved: int
    payload_length: int
    device_timestamp: FrameTimestamp
    ecm_timestamp: FrameTimestamp


@dataclass(frozen=True, slots=True)
class VideoExtension:
    marker_a: int
    marker_b: int
    other_value: int
    fourcc: bytes
    codec: str
    width: int
    height: int
    expected_crc32: int | None
    encryption_flag: int
    opaque_tail: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class AudioExtension:
    marker_a: int
    marker_b: int
    codec: int
    parameter_d: int
    parameter_e: int
    rate: int
    opaque_tail: bytes = field(repr=False)

    @property
    def known_rate_marker(self) -> bool:
        """Only codec markers 9/10 have evidenced use of this field as rate."""
        return self.codec in (9, 10)


@dataclass(frozen=True, slots=True)
class OpaqueExtension:
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PostNativeFrame:
    envelope: EnvelopeHeader
    header: FrameHeader
    extension_context: ExtensionContext
    extension: VideoExtension | AudioExtension | OpaqueExtension | None
    consumed_length: int
    encrypted: bool
    decrypted: bool
    _payload: bytes = field(repr=False)
    body_padding: bytes = field(repr=False)
    opaque_extra: bytes = field(repr=False)
    trailing_callback_bytes: bytes = field(repr=False)

    def plaintext_payload(self) -> bytes:
        """Return compressed bytes only when this interpretation allows it.

        This is not codec or browser acceptance. Opaque interpretation cannot
        establish plaintext status, and encrypted video requires verification.
        """
        if self.extension_context is ExtensionContext.OPAQUE:
            raise UnsupportedFrame("Opaque payload interpretation is unsupported")
        if self.encrypted and not self.decrypted:
            raise EncryptedPayloadUnavailable("Encrypted payload is unavailable")
        return self._payload


def _timestamp(ticks: int) -> FrameTimestamp:
    # u41 uses signed Java long division. No derived time for its negative range.
    micros = (
        ((ticks // 10000) - 11644473600000) * 1000
        if ticks <= 0x7FFFFFFFFFFFFFFF
        else None
    )
    return FrameTimestamp(ticks, micros)


def _video_extension(data: bytes) -> VideoExtension:
    if len(data) < 12 or 12 < len(data) < 17:
        raise FrameParseError("Incomplete video extension")
    marker_a, marker_b, other_value = struct.unpack_from("<BBH", data)
    fourcc = data[4:8]
    if fourcc == b"H264":
        codec = "h264"
    elif fourcc in (b"H265", b"HEVC"):
        codec = "h265"
    else:
        raise UnsupportedFrame("Unsupported video codec")
    width, height = struct.unpack_from("<hh", data, 8)
    if width <= 0 or height <= 0:
        raise FrameParseError("Invalid video dimensions")
    crc = struct.unpack_from("<I", data, 12)[0] if len(data) >= 17 else None
    flag = data[16] if len(data) >= 17 else 0
    if flag not in (0, 1):
        raise UnsupportedFrame("Unsupported video encryption flag")
    return VideoExtension(
        marker_a,
        marker_b,
        other_value,
        fourcc,
        codec,
        width,
        height,
        crc,
        flag,
        data[17:] if len(data) >= 17 else b"",
    )


def _audio_extension(data: bytes) -> AudioExtension:
    if len(data) < 12:
        raise FrameParseError("Incomplete audio extension")
    marker_a, marker_b, codec, parameter_d, parameter_e, rate = struct.unpack_from(
        "<BBhhhi", data
    )
    # Unknown numeric codecs stay metadata, with no decoding or codec fallback.
    return AudioExtension(
        marker_a, marker_b, codec, parameter_d, parameter_e, rate, data[12:]
    )


def parse_post_native_frame(
    callback: bytes,
    *,
    extension_context: ExtensionContext,
    max_callback_size: int = 8 * 1024 * 1024,
) -> PostNativeFrame:
    """Parse one envelope, preserving body leftovers and callback batch bytes.

    Size and checked lengths precede payload/extension copying. A caller may
    advance by consumed_length to parse a subsequent envelope in the callback.
    Video residual bytes are split at the app's four-byte payload alignment;
    their contents remain opaque and their presence is not a live-format proof.
    """
    if type(max_callback_size) is not int or not 68 <= max_callback_size <= 33554432:
        raise FrameParseError("Invalid callback size limit")
    if type(callback) is not bytes:
        raise FrameParseError("Callback must be bytes")
    if len(callback) > max_callback_size:
        raise FrameParseError("Callback size limit exceeded")
    if not isinstance(extension_context, ExtensionContext):
        raise UnsupportedFrame("Unsupported extension context")
    if len(callback) < 68:
        raise FrameParseError("Incomplete frame headers")
    if callback[:4] != b"SHFL":
        raise UnsupportedFrame("Unsupported frame magic")

    version, kind, key_marker = struct.unpack_from("<HBB", callback, 4)
    body_length, ticks, frame_index, other_value = struct.unpack_from(
        "<iQii", callback, 24
    )
    if body_length < 24:
        raise FrameParseError("Invalid frame body length")
    consumed = 44 + body_length
    if consumed > len(callback):
        raise FrameParseError("Incomplete frame body")
    frame_type, ext_length, ip_frame_type, reserved, payload_length, device, ecm = (
        struct.unpack_from("<BBBBiQQ", callback, 44)
    )
    if ext_length > 127:
        raise UnsupportedFrame("Unsupported signed extension length")
    if payload_length < 0:
        raise FrameParseError("Invalid payload length")
    if 24 + ext_length + payload_length > body_length:
        raise FrameParseError("Extension or payload exceeds frame body")

    extension_data = callback[68 : 68 + ext_length]
    extension: VideoExtension | AudioExtension | OpaqueExtension | None
    if not ext_length:
        extension = None
    elif extension_context is ExtensionContext.VIDEO:
        extension = _video_extension(extension_data)
    elif extension_context is ExtensionContext.AUDIO:
        extension = _audio_extension(extension_data)
    else:
        extension = OpaqueExtension(extension_data)
    encrypted = isinstance(extension, VideoExtension) and extension.encryption_flag == 1
    if encrypted and payload_length < 128:
        raise FrameParseError("Encrypted payload prefix is incomplete")
    payload_start = 68 + ext_length
    payload_end = payload_start + payload_length
    padding_length = (
        min((-payload_length) % 4, consumed - payload_end)
        if extension_context is ExtensionContext.VIDEO
        else 0
    )
    extra_start = payload_end + padding_length
    return PostNativeFrame(
        envelope=EnvelopeHeader(
            b"SHFL",
            version,
            kind,
            key_marker,
            callback[8:24],
            body_length,
            _timestamp(ticks),
            frame_index,
            other_value,
        ),
        header=FrameHeader(
            frame_type,
            ext_length,
            ip_frame_type,
            reserved,
            payload_length,
            _timestamp(device),
            _timestamp(ecm),
        ),
        extension_context=extension_context,
        extension=extension,
        consumed_length=consumed,
        encrypted=encrypted,
        decrypted=False,
        _payload=callback[payload_start:payload_end],
        body_padding=callback[payload_end:extra_start],
        opaque_extra=callback[extra_start:consumed],
        trailing_callback_bytes=callback[consumed:],
    )


def decrypt_frame_prefix(
    frame: PostNativeFrame, decryptor: Callable[[bytes], bytes]
) -> PostNativeFrame:
    """Replace the first 128 bytes only after exact output size and CRC agree.

    Decryptor owns its crypto/session boundary; no key is accepted or retained
    here. The input frame is immutable and remains unavailable on any failure.
    """
    if (
        not frame.encrypted
        or frame.decrypted
        or frame.extension_context is not ExtensionContext.VIDEO
        or not isinstance(frame.extension, VideoExtension)
        or frame.extension.encryption_flag != 1
        or frame.extension.expected_crc32 is None
        or len(frame._payload) < 128
    ):
        raise FrameDecryptionError("Frame is not eligible for prefix decryption")
    try:
        clear = decryptor(frame._payload[:128])
    except Exception:  # noqa: BLE001 - injected decryptors must not disclose payloads
        raise FrameDecryptionError("Prefix decryptor failed") from None
    if type(clear) is not bytes or len(clear) != 128:
        raise FrameDecryptionError("Invalid decrypted prefix")
    if zlib.crc32(clear) != frame.extension.expected_crc32:
        raise FrameDecryptionError("Decrypted prefix CRC mismatch")
    return replace(frame, _payload=clear + frame._payload[128:], decrypted=True)
