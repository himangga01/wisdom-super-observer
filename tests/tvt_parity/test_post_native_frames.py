"""NEW1: literal APK post-JNI layouts; synthetic data is not device acceptance."""

import importlib
import struct
import zlib

import pytest


def api():
    return importlib.import_module("wso_core.tvt.frames")


GUID = bytes.fromhex("00112233445566778899aabbccddeeff")
SENTINEL = b"PRIVATE-PAYLOAD-SENTINEL"


def packet(extension=b"", payload=b"", *, kind=1, extra=b"", trailing=b""):
    # Independent literals: ep3 reader 44 bytes, y41 reader 24 bytes.
    return (
        struct.pack(
            "<4sHBB16siQii",
            b"SHFL",
            0xFEDC,
            kind,
            0xFE,
            GUID,
            24 + len(extension) + len(payload) + len(extra),
            116444736000012345,
            -1234567,
            -7654321,
        )
        + struct.pack(
            "<BBBBiQQ",
            5,
            len(extension),
            0x80,
            0xA5,
            len(payload),
            116444736000029999,
            116444736000030000,
        )
        + extension
        + payload
        + extra
        + trailing
    )


def video(codec=b"H264", *, width=1920, height=1080, flag=None, crc=0, tail=b""):
    base = struct.pack("<BBH4shh", 0x81, 0x82, 0xFEDC, codec, width, height)
    return base if flag is None else base + struct.pack("<IB", crc, flag) + tail


def parse(data, context="video", **kwargs):
    m = api()
    return m.parse_post_native_frame(
        data, extension_context=m.ExtensionContext(context), **kwargs
    )


def test_exact_video_headers_fields_timestamps_and_private_payload():
    frame = parse(packet(video(), SENTINEL))
    assert frame.consumed_length == 68 + 12 + len(SENTINEL)
    assert frame.envelope.magic == b"SHFL"
    assert frame.envelope.version == 0xFEDC
    assert frame.envelope.kind == 1
    assert frame.envelope.key_marker == 0xFE
    assert frame.envelope.guid == GUID
    assert frame.envelope.frame_index == -1234567
    assert frame.envelope.other_value == -7654321
    assert frame.envelope.timestamp.ticks == 116444736000012345
    assert frame.envelope.timestamp.unix_microseconds == 1000
    assert frame.header.frame_type == 5
    assert frame.header.extension_length == 12
    assert frame.header.ip_frame_type == 0x80
    assert frame.header.reserved == 0xA5
    assert frame.header.device_timestamp.unix_microseconds == 2000
    assert frame.header.ecm_timestamp.unix_microseconds == 3000
    assert frame.extension.marker_a == 0x81
    assert frame.extension.marker_b == 0x82
    assert frame.extension.other_value == 0xFEDC
    assert frame.extension.fourcc == b"H264"
    assert frame.extension.codec == "h264"
    assert (frame.extension.width, frame.extension.height) == (1920, 1080)
    assert frame.plaintext_payload() == SENTINEL
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(frame)


@pytest.mark.parametrize("codec,expected", [(b"H265", "h265"), (b"HEVC", "h265")])
def test_known_video_codecs_preserve_raw_fourcc(codec, expected):
    frame = parse(packet(video(codec), b"abc"))
    assert frame.extension.fourcc == codec
    assert frame.extension.codec == expected


@pytest.mark.parametrize("kind", [1, 2, 3, 6, 7, 8, 255])
def test_context_is_explicit_and_kind_never_overrides_it(kind):
    extension = struct.pack("<BBhhhi", 0xFE, 0xFD, -12, -2, 3, -16000)
    frame = parse(packet(extension, SENTINEL, kind=kind), "audio")
    assert frame.envelope.kind == kind
    assert frame.extension.codec == -12
    assert frame.extension.parameter_d == -2
    assert frame.extension.parameter_e == 3
    assert frame.extension.rate == -16000
    assert frame.extension.known_rate_marker is False
    assert frame.plaintext_payload() == SENTINEL


@pytest.mark.parametrize(
    "codec,tail", [(9, b""), (10, bytes(range(32))), (123, b"x" * 115)]
)
def test_audio_base_and_optional_tail_preserve_numeric_metadata(codec, tail):
    frame = parse(
        packet(struct.pack("<BBhhhi", 1, 2, codec, 16, 1, 8000) + tail, b"audio"),
        "audio",
    )
    assert frame.extension.codec == codec
    assert frame.extension.rate == 8000
    assert frame.extension.known_rate_marker == (codec in (9, 10))
    assert frame.extension.opaque_tail == tail


@pytest.mark.parametrize("context", ["video", "audio"])
def test_zero_extension_does_not_invent_codec(context):
    frame = parse(packet(payload=SENTINEL), context)
    assert frame.extension is None
    assert frame.plaintext_payload() == SENTINEL


def test_opaque_extension_stays_private_and_cannot_feed_plaintext_decoder():
    frame = parse(
        packet(SENTINEL, SENTINEL, extra=SENTINEL, trailing=SENTINEL), "opaque"
    )
    assert frame.extension.data == SENTINEL
    assert frame.opaque_extra == SENTINEL
    assert frame.trailing_callback_bytes == SENTINEL
    assert frame.body_padding == b""
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(frame)
    with pytest.raises(api().UnsupportedFrame):
        frame.plaintext_payload()


def test_video_padding_extra_and_callback_batch_are_preserved_separately():
    second = packet(video(), b"next")
    first = packet(video(), b"abc", extra=b"\x99" + SENTINEL, trailing=second)
    frame = parse(first)
    assert frame.body_padding == b"\x99"
    assert frame.opaque_extra == SENTINEL
    assert frame.trailing_callback_bytes == second
    assert frame.consumed_length == 68 + 12 + 3 + 1 + len(SENTINEL)
    assert parse(first[frame.consumed_length :]).plaintext_payload() == b"next"
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(frame)


@pytest.mark.parametrize("length", range(68))
def test_every_header_truncation_is_rejected_without_partial_fields(length):
    with pytest.raises(api().FrameParseError):
        parse(packet()[:length])


@pytest.mark.parametrize(
    "offset,value", [(24, -1), (24, 23), (24, 2147483647), (48, -1), (48, 2147483647)]
)
def test_signed_body_and_payload_lengths_fail_closed(offset, value):
    data = bytearray(packet(video(), SENTINEL))
    struct.pack_into("<i", data, offset, value)
    with pytest.raises(api().FrameParseError):
        parse(bytes(data))


@pytest.mark.parametrize("length", range(128, 256))
def test_signed_negative_extension_bytes_are_unsupported(length):
    data = bytearray(packet(payload=SENTINEL))
    data[45] = length
    with pytest.raises(api().UnsupportedFrame):
        parse(bytes(data))


def test_extension_payload_sum_and_declared_body_are_bounded():
    data = packet(video(), SENTINEL)
    with pytest.raises(api().FrameParseError):
        parse(data[:-1])
    overrun = bytearray(data)
    overrun[45] = 127
    with pytest.raises(api().FrameParseError):
        parse(bytes(overrun))


@pytest.mark.parametrize(
    "context,length",
    [("video", n) for n in (*range(1, 12), *range(13, 17))]
    + [("audio", n) for n in range(1, 12)],
)
def test_context_specific_incomplete_extension_is_rejected(context, length):
    with pytest.raises(api().FrameParseError):
        parse(packet(b"x" * length, SENTINEL), context)


@pytest.mark.parametrize("length", [17, 18, 43, 44, 45, 127])
def test_video_crc_flag_extension_tail_is_bounded_and_opaque(length):
    tail = b"x" * (length - 17)
    frame = parse(packet(video(flag=0, tail=tail), b"abc"))
    assert frame.extension.opaque_tail == tail
    assert frame.extension.encryption_flag == 0
    assert frame.plaintext_payload() == b"abc"


@pytest.mark.parametrize(
    "changes",
    [
        {"codec": b"NOPE"},
        {"width": 0},
        {"width": -1},
        {"height": 0},
        {"height": -32768},
    ],
)
def test_unknown_codec_and_invalid_signed_dimensions_are_not_valid_video(changes):
    with pytest.raises(api().FrameParseError):
        parse(packet(video(**changes), SENTINEL))


def test_unknown_magic_is_typed_unsupported_without_payload_disclosure():
    with pytest.raises(api().UnsupportedFrame) as exc:
        parse(b"NOPE" + packet(video(), SENTINEL)[4:])
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(exc.value)


@pytest.mark.parametrize(
    "ticks,expected",
    [
        (0, -11644473600000000),
        (9223372036854775807, 910692730085477000),
        (9223372036854775808, None),
        (18446744073709551615, None),
    ],
)
def test_timestamp_raw_unsigned_ticks_and_supported_native_signed_range(
    ticks, expected
):
    data = bytearray(packet())
    for offset in (28, 52, 60):
        struct.pack_into("<Q", data, offset, ticks)
    frame = parse(bytes(data))
    for timestamp in (
        frame.envelope.timestamp,
        frame.header.device_timestamp,
        frame.header.ecm_timestamp,
    ):
        assert timestamp.ticks == ticks
        assert timestamp.unix_microseconds == expected


def test_encrypted_payload_never_appears_as_plaintext_until_verified_decryption():
    clear = bytes(range(128))
    encrypted = SENTINEL.ljust(128, b"x") + b"untouched suffix"
    frame = parse(packet(video(flag=1, crc=zlib.crc32(clear)), encrypted))
    assert frame.encrypted is True
    assert frame.decrypted is False
    with pytest.raises(api().EncryptedPayloadUnavailable):
        frame.plaintext_payload()
    seen = []

    def decrypt(prefix):
        seen.append(prefix)
        return clear

    result = api().decrypt_frame_prefix(frame, decrypt)
    assert seen == [encrypted[:128]]
    assert result.encrypted is True
    assert result.decrypted is True
    assert result.plaintext_payload() == clear + b"untouched suffix"
    with pytest.raises(api().EncryptedPayloadUnavailable):
        frame.plaintext_payload()
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(frame)


@pytest.mark.parametrize("length", [0, 1, 127])
def test_short_encrypted_payload_rejected(length):
    with pytest.raises(api().FrameParseError):
        parse(packet(video(flag=1), b"x" * length))


@pytest.mark.parametrize("flag", [2, 255])
def test_unknown_encryption_flag_is_unsupported(flag):
    with pytest.raises(api().UnsupportedFrame):
        parse(packet(video(flag=flag), SENTINEL.ljust(128, b"x")))


@pytest.mark.parametrize("output", [b"x" * 127, b"x" * 129, bytearray(128), b"x" * 128])
def test_decrypt_size_type_or_crc_failure_never_returns_partial_plaintext(output):
    frame = parse(
        packet(
            video(flag=1, crc=zlib.crc32(bytes(range(128)))), SENTINEL.ljust(128, b"x")
        )
    )
    with pytest.raises(api().FrameDecryptionError) as exc:
        api().decrypt_frame_prefix(frame, lambda _: output)
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(exc.value)
    with pytest.raises(api().EncryptedPayloadUnavailable):
        frame.plaintext_payload()


def test_decrypt_exception_is_replaced_with_fixed_private_error():
    frame = parse(packet(video(flag=1), SENTINEL.ljust(128, b"x")))

    def bad(_):
        raise RuntimeError(SENTINEL.decode())

    with pytest.raises(api().FrameDecryptionError) as exc:
        api().decrypt_frame_prefix(frame, bad)
    assert exc.value.__suppress_context__
    assert "PRIVATE-PAYLOAD-SENTINEL" not in repr(exc.value)


@pytest.mark.parametrize("maximum", [True, False, 67, 33554433, 68.0, "68", None])
def test_callback_max_requires_native_integer_in_supported_bounds(maximum):
    with pytest.raises(api().FrameParseError):
        parse(packet(), max_callback_size=maximum)


def test_callback_limit_checked_and_boundaries_allowed():
    assert parse(packet(), max_callback_size=68).consumed_length == 68
    assert parse(packet(), max_callback_size=33554432).consumed_length == 68
    with pytest.raises(api().FrameParseError):
        parse(packet(payload=b"x"), max_callback_size=68)
    with pytest.raises(api().FrameParseError):
        parse(packet() + b"x" * (8388608 - 67))


def test_bytes_and_explicit_context_required():
    m = api()
    with pytest.raises(m.FrameParseError):
        m.parse_post_native_frame(
            bytearray(packet()), extension_context=m.ExtensionContext.VIDEO
        )
    with pytest.raises(m.UnsupportedFrame):
        m.parse_post_native_frame(packet(), extension_context="video")
    with pytest.raises(TypeError):
        m.parse_post_native_frame(packet())


def test_decryptor_only_applies_to_undecoded_encrypted_video():
    frame = parse(packet(video(), SENTINEL))
    with pytest.raises(api().FrameDecryptionError):
        api().decrypt_frame_prefix(frame, lambda _: b"x" * 128)
