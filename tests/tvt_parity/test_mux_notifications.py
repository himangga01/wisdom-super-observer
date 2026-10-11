"""Ordinary N9000 controls consume original ingress without media effects."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_live import fragments
from test_local_live_mux import feed, opened, setup, wire
from wso_core.tvt.local_live import LiveError

LENGTHS = {2561: 92, 2562: 40, 2563: 36}


def test_native_mux_bootstrap_keeps_stdlib_only_import_boundary():
    source = Path(__file__).resolve().parents[2] / "packages/core/src"
    code = (
        "import sys; sys.path.insert(0,sys.argv[1]); "
        "from wso_core.tvt.local_live_mux import MultiplexLiveCodec; "
        "from wso_core.tvt.local_media_mux_types import MuxEpochIdentity; "
        "assert not any(n.startswith(('cryptography','sqlalchemy','pydantic',"
        "'wso_tvt_bridge','wso_contracts')) for n in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(source)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        "pure native mux import unexpectedly needs site packages"
    )


def notification(
    command=2563,
    *,
    version=5,
    route=0,
    encoding=0,
    sequence=0,
    declared=None,
    length=None,
    magic=825307441,
):
    body = bytes(LENGTHS[command] if length is None else length)
    inner = (
        struct.pack(
            "<HBBIII",
            version,
            route,
            encoding,
            command,
            sequence,
            len(body) if declared is None else declared,
        )
        + body
    )
    return struct.pack("<Ii", magic, len(inner)) + inner


@pytest.mark.parametrize("command", LENGTHS)
@pytest.mark.parametrize("version", [1, 5, 32767])
def test_exact_ordinary_control_consumed_then_media_progresses(command, version):
    codec, (slot,) = setup()
    ack = opened(codec, slot)
    assert feed(codec, notification(command, version=version), 2, 4) == ()
    assert codec.pending_bytes == 0 and not codec.blocked
    (frame,) = feed(codec, wire(slot), 8, 10)
    assert frame.slot == slot and frame.slot_ordinal == 1
    assert frame.ingress.first == 8 and frame.ingress.last == 10
    assert codec.wire_observation(slot)[0] == (2, 1, 0x10000505, 1, False)
    assert ack.accepted


@pytest.mark.parametrize("command", LENGTHS)
def test_every_split_preserves_one_notification_then_original_media(command):
    raw = notification(command)
    for offset in range(1, len(raw)):
        codec, (slot,) = setup()
        opened(codec, slot)
        assert feed(codec, raw[:offset], 2) == ()
        (frame,) = feed(codec, raw[offset:] + wire(slot), 3, 5)
        assert frame.ingress.first == 3 and frame.ingress.last == 5
        assert frame.slot_ordinal == 1 and codec.pending_bytes == 0


def test_controls_coalesced_with_media_do_not_claim_encoded_credit_or_block():
    claims = []
    allow = [False]

    def reserve(slot, count):
        claims.append((slot, count))
        return allow[0]

    codec, (slot,) = setup(reserve=reserve)
    opened(codec, slot)
    raw_media = wire(slot)
    controls = b"".join(notification(command) for command in LENGTHS)
    assert feed(codec, controls + raw_media, 2, 6) == ()
    assert claims == [(slot, len(raw_media))]
    assert codec.blocked and codec.pending_bytes == len(raw_media)
    allow[0] = True
    (frame,) = codec.drain(generation=7)
    assert frame.ingress.first == 2 and frame.ingress.last == 6
    assert frame.slot_ordinal == 1 and codec.pending_bytes == 0
    assert len(claims) == 2


def test_notification_does_not_satisfy_pending_ack_or_reset_slot_clock():
    codec, (slot,) = setup()
    codec.open_slot(slot, request_guid=bytes([9]) * 16, sequence=1)
    assert feed(codec, notification(), 1) == ()
    assert codec.wire_observation(slot) == (None, None)
    from test_local_live import oz, packet, yz

    feed(
        codec, packet(0x10000505, yz(task=slot.task) + oz(), sequence=1, declared=0), 2
    )
    (first,) = feed(codec, wire(slot, 1), 3)
    assert feed(codec, notification(), 4) == ()
    (second,) = feed(codec, wire(slot, 2), 5)
    assert second.slot_ordinal == first.slot_ordinal + 1
    with pytest.raises(LiveError):
        feed(codec, wire(slot, 2), 6)


def test_control_flood_counts_original_bytes_packets_and_preserves_counter_bound():
    codec, (slot,) = setup()
    opened(codec, slot)
    before = codec._received, codec._packets
    raw = notification() * 1000
    assert feed(codec, raw, 2, 9) == ()
    assert (codec._received, codec._packets) == (before[0] + len(raw), before[1] + 1000)
    assert codec.pending_bytes == 0 and not codec.blocked
    assert codec.wire_observation(slot)[1] is None
    codec._packets = (1 << 64) - 1
    with pytest.raises(LiveError):
        feed(codec, notification(), 10)


@pytest.mark.parametrize("command", LENGTHS)
@pytest.mark.parametrize(
    "variant",
    [
        {"version": 0},
        {"version": 32768},
        {"route": 1},
        {"route": 2},
        {"encoding": 1},
        {"sequence": 1},
        {"declared": 0},
        {"magic": 0},
        {"length": 1},
        {"length": 100},
    ],
)
def test_malformed_recognized_control_still_fences(command, variant):
    codec, (slot,) = setup()
    opened(codec, slot)
    with pytest.raises(LiveError):
        feed(codec, notification(command, **variant), 2)
    with pytest.raises(LiveError):
        feed(codec, wire(slot), 3)


@pytest.mark.parametrize("command", LENGTHS)
def test_fragmented_control_remains_unsupported(command):
    codec, (slot,) = setup()
    opened(codec, slot)
    with pytest.raises(LiveError):
        for ordinal, part in enumerate(fragments(notification(command)), 2):
            feed(codec, part, ordinal)


@pytest.mark.parametrize("command", [2560, 2564, 0x10000A03, 0x20000A03])
def test_unknown_action_or_family_still_fences(command):
    codec, (slot,) = setup()
    opened(codec, slot)
    raw = bytearray(notification())
    struct.pack_into("<I", raw, 12, command)
    with pytest.raises(LiveError):
        feed(codec, bytes(raw), 2)
