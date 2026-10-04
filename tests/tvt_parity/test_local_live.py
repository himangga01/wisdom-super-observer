"""Inert fixtures for the source-limited local N9000 live boundary."""

import dataclasses
import importlib.util
import json
import pickle
import struct

import pytest


def test_local_live_codec_exists():
    assert importlib.util.find_spec("wso_core.tvt.local_live") is not None


def api():
    from wso_core.tvt import local_live

    return local_live


SESSION = bytes(range(16))
CHANNEL = bytes(range(16, 32))
TASK = bytes(range(32, 48))
REQUEST = bytes(range(48, 64))


def identity(**changes):
    values = {"generation": 7, "session": SESSION, "channel": CHANNEL, "task": TASK}
    return api().LiveIdentity(**(values | changes))


def codec(**changes):
    values = {
        "identity": identity(),
        "peer_capability": 4,
        "channel_number": 3,
        "stream": 2,
        "authorize": lambda _: True,
    }
    return api().LiveCodec(**(values | changes))


def yz(action=1, session=SESSION, channel=CHANNEL, task=TASK, request=REQUEST):
    return request + session + channel + b"\x02\0\0\0" + task + bytes([action, 0, 0, 0])


def packet(command, body, sequence=9, declared=None, flags=2, version=5):
    inner = (
        struct.pack(
            "<HBBIII",
            version,
            flags,
            1,
            command,
            sequence,
            len(body) - 72 if declared is None else declared,
        )
        + body
    )
    return struct.pack("<Ii", 825307441, len(inner)) + inner


def media(
    index=1,
    extension=None,
    payload=b"\0\0\0\1\x65inert",
    kind=2,
    frame_type=0,
    channel=CHANNEL,
    ip=0x80,
    key=0,
    extra=b"",
):
    if extension is None:
        extension = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 0)
    body = struct.pack(
        "<BBBBiQQ",
        frame_type,
        len(extension),
        ip,
        0,
        len(payload),
        116444736000010000,
        116444736000020000,
    )
    body += extension + payload + bytes((-len(payload)) % 4) + extra
    return (
        struct.pack("<4sHBB", b"SHFL", 1, kind, key)
        + channel
        + struct.pack("<iQii", len(body), 116444736000000000, index, 0)
        + body
    )


@pytest.mark.parametrize(
    "capability,stream,command",
    [(4, 1, 1281), (4, 2, 1281), (5, 1, 1281), (5, 2, 1285)],
)
def test_open_exact_source_layout(capability, stream, command):
    c = codec(peer_capability=capability, stream=stream)
    raw = c.open(request_guid=REQUEST, sequence=9).private_bytes()
    assert struct.unpack_from("<IiHBBIII", raw) == (
        825307441,
        len(raw) - 8,
        3,
        2,
        1,
        command,
        9,
        len(raw) - 96,
    )
    assert raw[24:96] == yz()
    if command == 1281:
        assert raw[96:] == CHANNEL + bytes(52) + struct.pack(
            "<iBBBB", stream, 3, 0, 0, 0
        )
    else:
        assert raw[96:] == (
            b"<?xml version='1.0' encoding='utf-8'?><request version='1.0' "
            b"systemType='NVMS-9000' clientType='SYS'><destId>{13121110-1514-1716-1819-1A1B1C1D1E1F}</destId>"
            b"<taskId>{23222120-2524-2726-2829-2A2B2C2D2E2F}</taskId><chNo>3</chNo><audio>0</audio>"
            b"<streamType>2</streamType></request>"
        )


def test_ack_is_separate_from_media_and_close_fences():
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    ack = c.feed(packet(0x10000501, yz()), generation=7)
    assert ack == (api().LiveAcknowledgement(1281),)
    close = c.close_request(request_guid=REQUEST, sequence=10).private_bytes()
    assert close[24:96] == yz(action=2)
    assert struct.unpack_from("<I", close, 12)[0] == 1282
    assert c.feed(packet(0x10000502, yz(action=2), sequence=10), generation=7) == (
        api().LiveAcknowledgement(1282),
    )
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media()), generation=7)


def test_partial_multiple_and_context_without_extension():
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    first = packet(65537, yz() + media())
    assert c.feed(first[:17], generation=7) == ()
    frames = c.feed(
        first[17:] + packet(65537, yz() + media(index=2, extension=b"")), generation=7
    )
    assert len(frames) == 2
    for f in frames:
        assert f.summary() == api().LiveSummary(1, 10, "h264", 640, 480)
        assert f.private_bytes() == b"\0\0\0\1\x65inert"
        assert f.device_timestamp.unix_microseconds == 1000
        assert f.ecm_timestamp.unix_microseconds == 2000
        assert f.key_frame is True


@pytest.mark.parametrize("change", [{"task": b"t" * 16}])
def test_foreign_correlation_rejected(change):
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz(**change) + media()), generation=7)


def test_wrong_generation_and_duplicate_frame_fail_closed():
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(b"", generation=8)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    c.feed(packet(65537, yz() + media()), generation=7)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media()), generation=7)


def test_current_authority_and_close_during_publication():
    calls = []

    def authority(i):
        calls.append(i)
        return len(calls) == 1

    c = codec(authorize=authority)
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveDenied):
        c.feed(packet(65537, yz() + media()), generation=7)
    assert len(calls) == 2

    def close_now(_):
        c.close()
        return True

    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    c._authorize = close_now
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media()), generation=7)


@pytest.mark.parametrize(
    "variant",
    [
        "encrypted",
        "audio",
        "playback",
        "wrongstream",
        "frame_type",
        "noformat",
        "trailer",
    ],
)
def test_unsupported_media_paths_are_explicit(variant):
    args = {}
    if variant == "encrypted":
        args["extension"] = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 1)
        args["payload"] = bytes(128)
    if variant == "audio":
        args["kind"] = 6
    if variant == "playback":
        args["kind"] = 7
    if variant == "wrongstream":
        args["kind"] = 1
    if variant == "frame_type":
        args["frame_type"] = 1
    if variant == "noformat":
        args["extension"] = b""
    if variant == "trailer":
        args["extra"] = b"opaque"
    data = media(**args)
    if variant == "magic":
        data = b"XXXX" + data[4:]
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().UnsupportedLive):
        c.feed(packet(65537, yz() + data), generation=7)


def fragments(raw):
    inner = raw[8:]
    split = 80
    return [
        struct.pack("<Ii6i", 825307441, -1, 123, 2, len(inner), i, len(part), 77) + part
        for i, part in enumerate((inner[:split], inner[split:]), 1)
    ]


def test_fragments_reassemble_and_reject_order_interleaving():
    raw = packet(65537, yz() + media())
    parts = fragments(raw)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    assert c.feed(parts[0], generation=7) == ()
    assert len(c.feed(parts[1], generation=7)) == 1
    for bad in (parts[1], parts[0] + parts[0], parts[0] + raw):
        c = codec()
        c.open(request_guid=REQUEST, sequence=9)
        with pytest.raises(api().LiveError):
            c.feed(bad, generation=7)


@pytest.mark.parametrize(
    "bad",
    [
        struct.pack("<Ii", 825307441, 2**30),
        packet(65537, yz() + media(channel=b"x" * 16)),
    ],
)
def test_bad_lengths_identity_and_quota(bad):
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(bad, generation=7)
    with pytest.raises(api().LiveError):
        c.feed(b"", generation=7)


def test_session_and_packet_quotas():
    raw = packet(65537, yz() + media())
    c = codec(max_session_bytes=180)
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(raw, generation=7)
    c = codec(max_packets=1)
    c.open(request_guid=REQUEST, sequence=9)
    c.feed(raw, generation=7)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media(index=2)), generation=7)


def test_private_values_block_generic_exports_and_exception_causes():
    c = codec()
    wire = c.open(request_guid=REQUEST, sequence=9)
    f = c.feed(packet(65537, yz() + media()), generation=7)[0]
    for obj in (identity(), c, wire, f):
        assert "private" in repr(obj)
        assert not dataclasses.is_dataclass(obj)
        for exporter in (pickle.dumps, json.dumps, vars, dataclasses.asdict):
            with pytest.raises(TypeError):
                exporter(obj)

    def denied(_):
        raise ValueError("secret detail")

    c = codec(authorize=denied)
    with pytest.raises(api().LiveDenied) as caught:
        c.open(request_guid=REQUEST, sequence=9)
    assert caught.value.__suppress_context__
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stream", 0),
        ("stream", 3),
        ("stream", True),
        ("peer_capability", 0),
        ("peer_capability", 32768),
        ("channel_number", -1),
        ("channel_number", 256),
        ("max_packet", 100),
        ("max_fragments", 0),
    ],
)
def test_invalid_admission_numeric_fields(field, value):
    with pytest.raises(api().LiveError):
        codec(**{field: value})


@pytest.mark.parametrize(
    "change",
    [
        {"generation": True},
        {"session": bytes(16)},
        {"channel": b"short"},
        {"task": bytearray(16)},
    ],
)
def test_identity_is_typed_and_immutable(change):
    with pytest.raises(api().LiveError):
        identity(**change)
    i = identity()
    with pytest.raises(AttributeError):
        i.task = b"x" * 16
    with pytest.raises(AttributeError):
        del i.task


@pytest.mark.parametrize("variant", ["sequence", "command", "duplicate"])
def test_ack_must_match_outstanding_request(variant):
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    h = yz()
    sequence = 9
    command = 0x10000501
    if variant == "sequence":
        sequence = 10
    if variant == "request":
        h = yz(request=b"x" * 16)
    if variant == "task":
        h = yz(task=b"x" * 16)
    if variant == "command":
        command = 0x10000502
    if variant == "body":
        h += bytes(4)
    if variant == "duplicate":
        c.feed(packet(command, h), generation=7)
    with pytest.raises(api().LiveError):
        c.feed(packet(command, h, sequence=sequence), generation=7)


@pytest.mark.parametrize("field,value", [(12, 0), (16, 2**30), (20, 0), (24, 2**30)])
def test_fragment_declared_bounds(field, value):
    raw = bytearray(fragments(packet(65537, yz() + media()))[0])
    struct.pack_into("<i", raw, field, value)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(bytes(raw), generation=7)


def test_authority_denies_open_close_and_reentrant_close():
    c = codec(authorize=lambda _: False)
    with pytest.raises(api().LiveDenied):
        c.open(request_guid=REQUEST, sequence=9)
    state = {"allowed": True}
    c = codec(authorize=lambda _: state["allowed"])
    c.open(request_guid=REQUEST, sequence=9)
    state["allowed"] = False
    with pytest.raises(api().LiveDenied):
        c.close_request(request_guid=REQUEST, sequence=10)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media()), generation=7)


@pytest.mark.parametrize("fourcc", [b"H265", b"HEVC"])
def test_h265_and_stream1_and_source_context(fourcc):
    ext = struct.pack("<BBH4shhIB", 0, 0, 0, fourcc, 320, 240, 0, 0)
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    f = c.feed(
        packet(65537, yz() + media(kind=1, extension=ext, key=1, ip=0)), generation=7
    )[0]
    assert f.summary() == api().LiveSummary(1, 10, "h265", 320, 240)
    assert f.source_context == (1, 1, 1, 0, 0)
    assert f.key_frame


def test_empty_extension_cannot_reuse_another_tasks_format():
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    c.feed(packet(65537, yz() + media()), generation=7)
    c.close()
    new = codec(identity=identity(task=b"n" * 16))
    new.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().UnsupportedLive):
        new.feed(packet(65537, yz(task=b"n" * 16) + media(extension=b"")), generation=7)


def test_raw_source_format_stays_private_and_is_preserved():
    extension = struct.pack("<BBH4shhIB", 1, 2, 300, b"HEVC", 320, 240, 42, 0) + bytes(
        27
    )
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    frame = c.feed(packet(65537, yz() + media(extension=extension)), generation=7)[0]
    assert frame.source_extension.private_bytes() == extension
    assert "HEVC" not in repr(frame.source_extension)


def test_short_encrypted_prefix_is_still_typed_unsupported():
    ext = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 1)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().UnsupportedLive):
        c.feed(packet(65537, yz() + media(extension=ext)), generation=7)


def test_source_success_class_is_one_high_nibble_not_two():
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    assert c.feed(packet(0x10000501, yz()), generation=7) == (
        api().LiveAcknowledgement(1281),
    )
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(packet(0x20000501, yz()), generation=7)


def test_outgoing_xml_obeys_frame_quota():
    c = codec(peer_capability=5, max_packet=172)
    with pytest.raises(api().LiveError):
        c.open(request_guid=REQUEST, sequence=9)


@pytest.mark.parametrize("offset", [8, 28], ids=["group", "tag"])
def test_m1_fragment_changed_identity_fences(offset):
    parts = fragments(packet(65537, yz() + media()))
    last = bytearray(parts[1])
    struct.pack_into("<i", last, offset, 999)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    assert c.feed(parts[0], generation=7) == ()
    with pytest.raises(api().LiveError):
        c.feed(bytes(last), generation=7)
    with pytest.raises(api().LiveError):
        c.feed(parts[1], generation=7)


def test_m1_fragment_short_final_sum_fences():
    first, last = fragments(packet(65537, yz() + media()))
    last = bytearray(last[:-1])
    struct.pack_into("<i", last, 24, len(last) - 32)
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    c.feed(first, generation=7)
    with pytest.raises(api().LiveError):
        c.feed(bytes(last), generation=7)
    with pytest.raises(api().LiveError):
        c.feed(b"", generation=7)


def test_m1_heartbeat_exhausts_packet_quota():
    c = codec(max_packets=2)
    c.open(request_guid=REQUEST, sequence=9)
    heartbeat = struct.pack("<Ii", 825307441, 0)
    assert c.feed(heartbeat * 2, generation=7) == ()
    with pytest.raises(api().LiveError):
        c.feed(heartbeat, generation=7)
    with pytest.raises(api().LiveError):
        c.feed(b"", generation=7)


@pytest.mark.parametrize("cut", [7, 9, 31, 32, 50])
def test_m1_partial_fragment_header_and_payload(cut):
    first, last = fragments(packet(65537, yz() + media()))
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    assert c.feed(first[:cut], generation=7) == ()
    assert c.feed(first[cut:], generation=7) == ()
    frames = c.feed(last, generation=7)
    assert len(frames) == 1
    assert frames[0].private_bytes() == b"\0\0\0\1\x65inert"


@pytest.mark.parametrize(
    "route,body,declared",
    [
        (0, b"", 0),
        (1, b"opaque", 5),
        (2, bytes(72) + b"ignored", 7),
        (255, b"any ignored body", 0xFFFFFFFF),
    ],
)
def test_source_ack_ignores_routing_echo_and_body(route, body, declared):
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    raw = bytearray(
        packet(0x10000501, body, flags=route, declared=declared, version=0xFFFF)
    )
    raw[11] = 255
    assert c.feed(bytes(raw), generation=7) == (api().LiveAcknowledgement(1281),)
    c.close_request(request_guid=REQUEST, sequence=10)
    raw = packet(
        0x10000502, body, sequence=10, flags=route, declared=declared, version=0
    )
    assert c.feed(raw, generation=7) == (api().LiveAcknowledgement(1282),)


def test_source_media_ignores_only_fields_not_used_by_live_consumers():
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    routing = bytearray(
        yz(session=b"s" * 16, channel=b"c" * 16, request=b"r" * 16, action=255)
    )
    routing[48:52] = b"abcd"
    routing[69:72] = b"xyz"
    frame = bytearray(media(kind=1))
    frame[:4] = b"WIRE"
    frame[4:6] = b"\xff\xff"
    frame[47] = 255
    struct.pack_into("<i", frame, 40, -123)
    raw = bytearray(
        packet(
            65537, bytes(routing) + bytes(frame), declared=0xFFFFFFFF, version=0xFFFF
        )
    )
    raw[:4] = b"TRAN"
    raw[11] = 255
    result = c.feed(bytes(raw), generation=7)[0]
    assert result.private_bytes() == b"\0\0\0\1\x65inert"
    assert result.source_outer_headers.private_bytes() == bytes(raw[:8])
    assert result.source_header.private_bytes() == bytes(raw[8:96])
    assert result.source_envelope.private_bytes() == bytes(frame[:68])
    assert result.source_padding.private_bytes() == bytes(2)
    assert "WIRE" not in repr(result)


@pytest.mark.parametrize("route", [0, 1])
def test_source_media_without_wire_task_remains_unsupported(route):
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    header = b"" if route == 0 else yz()[:52]
    with pytest.raises(api().UnsupportedLive):
        c.feed(
            packet(
                65537, header + media(kind=1), flags=route, declared=len(media(kind=1))
            ),
            generation=7,
        )


@pytest.mark.parametrize(
    "variant", ["generation", "task", "channel", "denied", "closed"]
)
def test_source_relaxed_fields_keep_essential_fences(variant):
    allowed = {"value": True}
    c = codec(stream=1, authorize=lambda _: allowed["value"])
    c.open(request_guid=REQUEST, sequence=9)
    h = yz(session=b"s" * 16, channel=b"c" * 16, action=255)
    data = media(kind=1)
    generation = 7
    if variant == "generation":
        generation = 8
    if variant == "task":
        h = yz(task=b"t" * 16)
    if variant == "channel":
        data = media(kind=1, channel=b"c" * 16)
    if variant == "denied":
        allowed["value"] = False
    if variant == "closed":
        c.close()
    raw = packet(65537, h + b"WIRE" + data[4:])
    with pytest.raises(api().LiveError):
        c.feed(raw, generation=generation)


@pytest.mark.parametrize("offset,value", [(24, -1), (24, 2**30), (48, -1), (48, 2**30)])
def test_source_raw_lengths_are_bounded_without_magic_gate(offset, value):
    data = bytearray(media(kind=1))
    data[:4] = b"WIRE"
    struct.pack_into("<i", data, offset, value)
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + bytes(data)), generation=7)


def test_source_raw_postparse_authority_close_discards_media():
    calls = []

    def authority(_):
        calls.append(1)
        if len(calls) == 2:
            c.close()
        return True

    c = codec(stream=1, authorize=authority)
    c.open(request_guid=REQUEST, sequence=9)
    data = media(kind=1)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + b"WIRE" + data[4:]), generation=7)
    assert len(calls) == 2


@pytest.mark.parametrize("length", [0, 43, 44, 67])
def test_source_raw_header_truncation(length):
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media(kind=1)[:length]), generation=7)


@pytest.mark.parametrize(
    "extension",
    [
        bytes(11),
        bytes(14),
        bytes(128),
        struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 255),
    ],
)
def test_source_raw_extension_bounds_and_unknown_encryption(extension):
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz() + media(kind=1, extension=extension)), generation=7)


def test_source_fragment_original_headers_are_preserved_privately():
    parts = fragments(packet(65537, yz() + media()))
    parts = [b"WIRE" + p[4:] for p in parts]
    c = codec()
    c.open(request_guid=REQUEST, sequence=9)
    result = c.feed(b"".join(parts), generation=7)[0]
    assert result.source_outer_headers.private_bytes() == b"".join(
        p[:32] for p in parts
    )
    for private in (
        result.source_outer_headers,
        result.source_header,
        result.source_envelope,
        result.source_padding,
    ):
        assert "private" in repr(private)
        with pytest.raises(TypeError):
            pickle.dumps(private)


@pytest.mark.parametrize("ticks,expected", [(0, -11644473600000000), (2**63, None)])
def test_source_raw_timestamp_preserves_existing_supported_range(ticks, expected):
    data = bytearray(media(kind=1))
    for offset in (28, 52, 60):
        struct.pack_into("<Q", data, offset, ticks)
    c = codec(stream=1)
    c.open(request_guid=REQUEST, sequence=9)
    f = c.feed(packet(65537, yz() + bytes(data)), generation=7)[0]
    for stamp in (f.envelope_timestamp, f.device_timestamp, f.ecm_timestamp):
        assert stamp.ticks == ticks
        assert stamp.unix_microseconds == expected


def taskless_source_packet(channel=CHANNEL):
    # Inert source-shaped large frame: ep3+y41+12-byte HEVC extension, no padding.
    extension = struct.pack("<BBH4shh", 0, 0, 0, b"HEVC", 1280, 1936)
    data = bytearray(
        media(kind=1, channel=channel, extension=extension, payload=bytes(96483))
    )
    del data[-1:]
    struct.pack_into("<i", data, 24, len(data) - 44)
    return packet(65537, bytes(data), flags=0, sequence=0, declared=len(data))


def taskless_open_ack(c):
    c.open(request_guid=REQUEST, sequence=6)
    assert c.feed(
        packet(0x10000501, b"", flags=0, sequence=6, declared=0), generation=7
    ) == (api().LiveAcknowledgement(1281),)


def test_taskless_first_explicit_ack_two_fragments_preserve_wire():
    c = codec(stream=1, exclusive_first_task=True)
    taskless_open_ack(c)
    raw = taskless_source_packet()
    assert len(raw[8:]) == 96579
    first, last = fragments(raw)
    assert c.feed(first, generation=7) == ()
    result = c.feed(last, generation=7)[0]
    assert result.summary() == api().LiveSummary(1, 96483, "h265", 1280, 1936)
    assert result.source_header.private_bytes() == raw[8:24]
    assert result.source_envelope.private_bytes() == raw[24:92]
    assert result.identity.task == TASK
    assert result.private_bytes() == bytes(96483)


@pytest.mark.parametrize(
    "variant",
    ["default", "nonexclusive", "ackmissing", "channel", "generation", "revoked"],
)
def test_taskless_first_retains_admission_fences(variant):
    allowed = {"value": True}
    options = {"exclusive_first_task": variant != "nonexclusive"}
    if variant == "default":
        options = {}
    c = codec(stream=1, authorize=lambda _: allowed["value"], **options)
    if variant == "ackmissing":
        c.open(request_guid=REQUEST, sequence=6)
    else:
        taskless_open_ack(c)
    if variant == "revoked":
        allowed["value"] = False
    raw = taskless_source_packet(channel=b"c" * 16 if variant == "channel" else CHANNEL)
    with pytest.raises(api().LiveError):
        c.feed(raw, generation=8 if variant == "generation" else 7)
    with pytest.raises(api().LiveError):
        c.feed(b"", generation=7)


@pytest.mark.parametrize("value", [0, 1, None, "true"])
def test_taskless_first_option_requires_literal_bool(value):
    with pytest.raises(api().LiveError):
        codec(stream=1, exclusive_first_task=value)


def test_taskless_first_cannot_select_stream2_or_route1():
    with pytest.raises(api().UnsupportedLive):
        codec(stream=2, exclusive_first_task=True)
    c = codec(stream=1, exclusive_first_task=True)
    taskless_open_ack(c)
    with pytest.raises(api().UnsupportedLive):
        c.feed(
            packet(
                65537, yz()[:52] + media(kind=1), flags=1, declared=len(media(kind=1))
            ),
            generation=7,
        )


@pytest.mark.parametrize("action", ["duplicate_open", "close_reopen"])
def test_taskless_first_task_replacement_and_reuse_fail_closed(action):
    c = codec(stream=1, exclusive_first_task=True)
    taskless_open_ack(c)
    if action == "close_reopen":
        c.close()
    with pytest.raises(api().LiveError):
        c.open(request_guid=b"r" * 16, sequence=10)
    with pytest.raises(api().LiveError):
        c.feed(taskless_source_packet(), generation=7)


def test_taskless_first_does_not_bypass_route2_foreign_task():
    c = codec(stream=1, exclusive_first_task=True)
    taskless_open_ack(c)
    with pytest.raises(api().LiveError):
        c.feed(packet(65537, yz(task=b"t" * 16) + media(kind=1)), generation=7)


def test_taskless_first_wrong_ack_cannot_enable_media():
    c = codec(stream=1, exclusive_first_task=True)
    c.open(request_guid=REQUEST, sequence=6)
    with pytest.raises(api().LiveError):
        c.feed(packet(0x10000501, b"", flags=0, sequence=5, declared=0), generation=7)
    with pytest.raises(api().LiveError):
        c.feed(taskless_source_packet(), generation=7)
