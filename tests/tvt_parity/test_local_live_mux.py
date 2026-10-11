"""Synthetic wire tests: immutable original slots, never recorder acceptance."""

import importlib
import importlib.util
import pickle
import struct
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest
from test_local_live import REQUEST, SESSION, fragments, media, oz, packet, yz
from wso_core.tvt.local_live import LiveError, LiveRefused


def api():
    name = "wso_core.tvt.local_live_mux"
    assert importlib.util.find_spec(name), (
        "immutable multiplex codec is not implemented"
    )
    return importlib.import_module(name)


def types():
    api()
    return importlib.import_module("wso_core.tvt.local_media_mux_types")


def setup(count=1, capability=6, authorize=lambda _: True, **options):
    t = types()
    epoch = t.MuxEpochIdentity(7, SESSION)
    c = api().MultiplexLiveCodec(
        epoch=epoch, peer_capability=capability, authorize=authorize, **options
    )
    slots = [
        t.MuxSlotIdentity(epoch, bytes([i + 1]) * 16, bytes([i + 65]) * 16, 2)
        for i in range(count)
    ]
    for i, slot in enumerate(slots):
        c.register_slot(slot, channel_number=i)
    return c, slots


def feed(c, data, first=1, last=None, generation=7):
    return c.feed(
        types().IngressChunk(
            data, types().IngressSpan(first, first if last is None else last)
        ),
        generation=generation,
    )


def opened(c, slot, sequence=1, ordinal=1, capability=6, code=0):
    request = c.open_slot(slot, request_guid=REQUEST, sequence=sequence)
    command = 1285 if capability >= 5 else 1281
    assert struct.unpack_from("<I", request.private_bytes(), 12)[0] == command
    body = (
        yz(channel=slot.channel, task=slot.task) + oz(code) if command == 1285 else b""
    )
    (ack,) = feed(
        c, packet(0x10000000 | command, body, sequence=sequence, declared=0), ordinal
    )
    assert ack.slot == slot and ack.accepted
    return ack


def wire(slot, index=1, route=0, kind=2, task=None, payload=None):
    data = media(
        channel=slot.channel,
        index=index,
        kind=kind,
        **({} if payload is None else {"payload": payload}),
    )
    header = (
        yz(channel=slot.channel, task=slot.task if task is None else task)
        if route == 2
        else b""
    )
    return packet(65537, header + data, flags=route, sequence=0, declared=len(data))


def test_twelve_interleaved_slots_keep_original_identity():
    c, slots = setup(12)
    for i, slot in enumerate(slots):
        opened(c, slot, i + 1, i + 1)
    for index in range(1, 4):
        for i, slot in enumerate(reversed(slots)):
            ordinal = 12 + (index - 1) * 12 + i + 1
            (f,) = feed(c, wire(slot, index, route=2 if i % 2 else 0), ordinal)
            assert f.slot == slot and f.frame.identity.task == slot.task
            assert f.frame.source_context[1] == 2
            assert f.ingress == types().IngressSpan(ordinal, ordinal)
            assert f.slot_ordinal == index
            assert f.mapped_timestamp_us == 1000 + (index - 1) * 24


def test_second_open_same_channel_fences_epoch():
    c, (slot,) = setup()
    opened(c, slot)
    with pytest.raises(LiveError):
        c.open_slot(slot, request_guid=REQUEST, sequence=2)
    with pytest.raises(LiveError):
        feed(c, wire(slot), 2)


def test_route0_cannot_bind_unregistered_channel():
    c, (slot,) = setup()
    opened(c, slot)
    other = types().MuxSlotIdentity(slot.epoch, b"z" * 16, b"y" * 16, 2)
    with pytest.raises(LiveError):
        feed(c, wire(other), 2)


@pytest.mark.parametrize(
    "variant", ["epoch", "stream", "task", "ack_sequence", "no_ack", "route1"]
)
def test_wrong_epoch_stream_task_or_ack_sequence_rejected(variant):
    c, (slot,) = setup()
    if variant in ("ack_sequence", "no_ack"):
        c.open_slot(slot, request_guid=REQUEST, sequence=1)
    else:
        opened(c, slot)
    with pytest.raises(LiveError):
        if variant == "ack_sequence":
            feed(c, packet(0x10000505, yz(task=slot.task) + oz(), sequence=2), 2)
        else:
            feed(
                c,
                wire(
                    slot,
                    route=2 if variant == "task" else 1 if variant == "route1" else 0,
                    kind=1 if variant == "stream" else 2,
                    task=b"x" * 16,
                ),
                2,
                generation=8 if variant == "epoch" else 7,
            )
    with pytest.raises(LiveError):
        feed(c, b"", 3)


@pytest.mark.parametrize("fragmented", [False, True])
def test_cross_cut_partial_preserves_first_byte_origin(fragmented):
    c, (slot,) = setup()
    opened(c, slot)
    raw = wire(slot)
    parts = fragments(raw) if fragmented else (raw[:31], raw[31:])
    assert feed(c, parts[0], 2, 4) == ()
    (f,) = feed(c, parts[1], 8, 10)
    assert f.ingress == types().IngressSpan(2, 10)
    assert f.frame.source_outer_headers.private_bytes() == (
        b"".join(p[:32] for p in parts) if fragmented else raw[:8]
    )
    assert f.frame.source_header.private_bytes() == raw[8:24]


def test_slot_raw_order_survives_park():
    # Parking is an owner publication state: the codec continues validating.
    c, (slot,) = setup()
    opened(c, slot)
    for index in (1, 2, 3):
        (f,) = feed(c, wire(slot, index), index + 1)
        assert f.slot_ordinal == index
        assert f.mapped_timestamp_us == 1000 + (index - 1) * 24
    with pytest.raises(LiveError):
        feed(c, wire(slot, 2), 5)


@pytest.mark.parametrize("capability", [4, 6])
def test_source_refusal_and_warning(capability):
    c, (slot,) = setup(capability=capability)
    ack = opened(c, slot, capability=capability, code=0x20000060)
    assert ack.warning is (capability == 6)
    c, (slot,) = setup(capability=capability)
    c.open_slot(slot, request_guid=REQUEST, sequence=1)
    command = 1285 if capability == 6 else 1281
    with pytest.raises(LiveRefused) as caught:
        feed(
            c,
            packet(
                0x20000000 | command, yz(task=slot.task) + oz(0x20000030), sequence=99
            ),
        )
    assert caught.value.reason == "busy"


def test_continuous_feed_exceeds_legacy_capture_limits():
    c, (slot,) = setup()
    opened(c, slot)
    total = 0
    for index in range(1, 4201):
        raw = wire(slot, index, payload=bytes(8192))
        total += len(raw)
        (f,) = feed(c, raw, index + 1)
        assert f.slot_ordinal == index
    assert total > 32 << 20
    assert not c._buffer and not c._assembly


def test_tombstone_and_sequence_never_reuse():
    c, slots = setup(2)
    opened(c, slots[0], sequence=0x7FFFFFFF)
    c.tombstone(slots[0])
    with pytest.raises(LiveError):
        c.open_slot(slots[1], request_guid=REQUEST, sequence=0)


def test_private_values_and_seal_reject_fabrication():
    c, (slot,) = setup()
    opened(c, slot)
    (f,) = feed(c, wire(slot), 2)
    assert "private" in repr(f)
    with pytest.raises(TypeError):
        pickle.dumps(f)
    with pytest.raises((TypeError, LiveError)):
        types().MuxValidatedFrame(f.frame, slot, f.ingress, 1000, 1)


def test_slot_clock_rejects_regression_and_overflow():
    clock = api().SlotMediaClock()
    assert clock.accept(1000, 1) == (1000, 1)
    assert clock.accept(1000, 2) == (1024, 2)
    assert clock.accept(1040, 3) == (1048, 3)
    with pytest.raises(LiveError):
        clock.accept(1039, 4)


@pytest.mark.parametrize("field", ["received", "packets", "clock", "ingress"])
def test_checked_lifetime_counters_fence_before_wrap(field):
    c, (slot,) = setup()
    opened(c, slot)
    if field in ("received", "packets"):
        setattr(c, "_" + field, (1 << 64) - 1)
        with pytest.raises(LiveError):
            feed(c, wire(slot), 2)
        with pytest.raises(LiveError):
            feed(c, b"", 3)
    elif field == "clock":
        clock = api().SlotMediaClock()
        assert clock.accept((1 << 63) - 24, 1)[1] == 1
        with pytest.raises(LiveError):
            clock.accept((1 << 63) - 24, 2)
        with pytest.raises(LiveError):
            clock.accept(0, 3)
    else:
        with pytest.raises(LiveError):
            types().IngressSpan(1, 1 << 64)


@pytest.mark.parametrize("action", ["deny", "close", "reenter"])
def test_postparse_authority_cannot_release_returned_batch(action):
    state = {"frames": 0, "armed": False}

    def authorize(slot):
        if not state["armed"]:
            return True
        state["frames"] += 1
        if state["frames"] == 2:
            if action == "deny":
                return False
            if action == "close":
                c.close()
            else:
                c.open_slot(slot, request_guid=REQUEST, sequence=2)
        return True

    c, (slot,) = setup(authorize=authorize)
    opened(c, slot)
    state["armed"] = True
    with pytest.raises(LiveError):
        feed(c, wire(slot), 2)
    with pytest.raises(LiveError):
        feed(c, wire(slot, 2), 3)


def test_multi_packet_chunk_and_partial_tail_preserve_span():
    c, (slot,) = setup()
    opened(c, slot)
    a, b = wire(slot, 1), wire(slot, 2)
    (first,) = feed(c, a + b[:12], 2, 5)
    assert first.ingress == types().IngressSpan(2, 5)
    (second,) = feed(c, b[12:], 6, 9)
    assert second.ingress == types().IngressSpan(2, 9)


@pytest.mark.parametrize(
    "variant",
    ["pending", "duplicate_channel", "task_reuse", "tombstone", "foreign_epoch"],
)
def test_immutable_slot_registry_rejects_ambiguity(variant):
    c, (first, second) = setup(2)
    if variant == "pending":
        c.open_slot(first, request_guid=REQUEST, sequence=1)
        with pytest.raises(LiveError):
            c.open_slot(second, request_guid=REQUEST, sequence=2)
    else:
        opened(c, first)
        if variant == "tombstone":
            c.tombstone(first)
            with pytest.raises(LiveError):
                feed(c, wire(first), 2)
        else:
            slot = types().MuxSlotIdentity(
                types().MuxEpochIdentity(8, SESSION)
                if variant == "foreign_epoch"
                else first.epoch,
                first.channel if variant == "duplicate_channel" else b"z" * 16,
                first.task if variant == "task_reuse" else b"y" * 16,
                2,
            )
            with pytest.raises(LiveError):
                c.register_slot(slot, channel_number=3)
    with pytest.raises(LiveError):
        feed(c, b"", 3)


@pytest.mark.parametrize(
    "variant",
    [
        "negative_body",
        "negative_payload",
        "huge_extension",
        "encrypted",
        "missing_format",
        "bad_fragments",
    ],
)
def test_malformed_raw_media_fences_entire_epoch(variant):
    c, (slot,) = setup()
    opened(c, slot)
    raw = bytearray(wire(slot))
    if variant == "negative_body":
        struct.pack_into("<i", raw, 24 + 24, -1)
    elif variant == "negative_payload":
        struct.pack_into("<i", raw, 24 + 48, -1)
    elif variant == "huge_extension":
        raw[24 + 45] = 128
    elif variant == "encrypted":
        raw[24 + 68 + 16] = 1
    elif variant == "missing_format":
        data = media(channel=slot.channel, extension=b"")
        raw = bytearray(packet(65537, data, flags=0, declared=len(data)))
    else:
        raw = bytearray(fragments(bytes(raw))[0])
        struct.pack_into("<i", raw, 8 + 4, 257)
    with pytest.raises(LiveError):
        feed(c, bytes(raw), 2)


@pytest.mark.parametrize(
    "name",
    [
        "TransportGrant",
        "SlotRetentionGrant",
        "ViewerGrant",
        "FocusGrant",
        "MuxOriginalReservation",
        "ViewerCleanupReceipt",
        "EpochCleanupReceipt",
        "MasterReservation",
    ],
)
def test_authority_and_custody_values_require_private_seals(name):
    t = types()
    scope = t.MuxScopeKey(
        UUID(int=1),
        1,
        UUID(int=2),
        bytes(32),
        UUID(int=3),
        UUID(int=4),
        UUID(int=5),
        UUID(int=6),
        1,
        UUID(int=11),
        1,
        UUID(int=7),
    )
    _, (slot,) = setup()
    values = {
        "scope": scope,
        "expires_monotonic": 10.0,
        "_authority": object(),
        "_seal": object(),
    }
    if name == "TransportGrant":
        values["native_generation"] = UUID(int=8)
    elif name == "SlotRetentionGrant":
        values["slot"] = slot
    elif name == "ViewerGrant":
        values.update(slot=slot, lease_id=UUID(int=9), registration=UUID(int=10))
    elif name == "FocusGrant":
        values.update(lease_id=UUID(int=9), direction="FORWARD", admitted_monotonic=1.0)
    elif name == "MuxOriginalReservation":
        values = {
            "id": UUID(int=1),
            "kind": "base",
            "worker_epoch": UUID(int=7),
            "_authority": object(),
            "_seal": True,
        }
    elif name == "ViewerCleanupReceipt":
        values = {
            "lease_id": UUID(int=9),
            "registration_id": UUID(int=10),
            "decoder_settled": True,
            "peer_settled": True,
            "media_cleared": True,
            "_authority": object(),
            "_seal": True,
        }
    elif name == "EpochCleanupReceipt":
        values = {
            "master_id": UUID(int=1),
            "worker_epoch": UUID(int=7),
            "native_generation": UUID(int=8),
            "original_state": "REAPED",
            "callback_settled": True,
            "ipc_settled": True,
            "job_settled": True,
            "_authority": object(),
            "_seal": True,
        }
    else:
        values = {
            "scope": scope,
            "master_id": UUID(int=1),
            "creator": True,
            "transport": True,
            "deadline_monotonic": 10.0,
            "_seal": True,
        }
    with pytest.raises(LiveError):
        getattr(t, name)(**values)


def test_private_values_reject_numeric_coercion_and_stream_one():
    t = types()
    for bad in (True, 1.0, "1", 0, -1, 1 << 64):
        with pytest.raises(LiveError):
            t.IngressSpan(bad, bad)
    with pytest.raises(LiveError):
        t.MuxSlotIdentity(t.MuxEpochIdentity(7, SESSION), b"c" * 16, b"t" * 16, 1)


def test_credit_coalesced_frames_stop_before_seventeenth_allocation(monkeypatch):
    claims = []

    def reserve(slot, size):
        if len(claims) == 16:
            return False
        claims.append((slot, size))
        return True

    c, (slot,) = setup(reserve=reserve)
    opened(c, slot)
    allocated = []
    real_media = c._media

    def watched(*args):
        allocated.append(1)
        return real_media(*args)

    monkeypatch.setattr(c, "_media", watched)
    packets = [wire(slot, i) for i in range(1, 21)]
    assert len(feed(c, b"".join(packets), 2)) == 1
    for _ in range(15):
        assert len(c.drain(generation=7)) == 1
    before = c._packets
    assert c.drain(generation=7) == () and c.blocked
    assert len(allocated) == len(claims) == 16
    assert c._slots[slot.channel].clock._ordinal == 16
    assert c._packets == before
    assert c.pending_bytes == sum(map(len, packets[16:]))
    assert c.input_capacity == (1 << 20) - c.pending_bytes
    assert all(size == len(packets[0]) for _, size in claims)


@pytest.mark.parametrize("fragmented", [False, True])
def test_credit_blocked_partial_keeps_origin_and_uninitialized_state(fragmented):
    allow = [False]
    c, (slot,) = setup(
        reserve=lambda *_: allow[0],
        reserve_scratch=lambda _: True,
        release_scratch=lambda _: None,
    )
    opened(c, slot)
    raw = wire(slot)
    parts = fragments(raw) if fragmented else (raw[:31], raw[31:])
    assert feed(c, parts[0], 2, 4) == ()
    assert feed(c, parts[1], 8, 10) == () and c.blocked
    pending = sum(map(len, parts))
    assert c.pending_bytes == pending
    assert c._slots[slot.channel].format is None
    assert c._slots[slot.channel].clock._ordinal == 0
    before = c._packets
    assert c.drain(generation=7) == ()
    assert c._packets == before and c.pending_bytes == pending
    allow[0] = True
    (frame,) = c.drain(generation=7)
    assert frame.ingress == types().IngressSpan(2, 10)
    assert frame.slot_ordinal == 1 and frame.mapped_timestamp_us == 1000
    assert c.pending_bytes == 0 and not c.blocked


@pytest.mark.parametrize("action", ["deny", "close", "reenter"])
def test_credit_callback_late_authority_fences_without_allocating(action, monkeypatch):
    current = [True]
    claims = []

    def reserve(slot, size):
        claims.append((slot, size))
        if action == "deny":
            current[0] = False
        elif action == "close":
            c.close()
        else:
            c.drain(generation=7)
        return True

    c, (slot,) = setup(reserve=reserve, authorize=lambda _: current[0])
    opened(c, slot)
    allocated = []
    monkeypatch.setattr(c, "_media", lambda *args: allocated.append(1))
    with pytest.raises(LiveError):
        feed(c, wire(slot), 2)
    assert len(claims) == 1 and allocated == []
    assert c.pending_bytes == 0 and c.input_capacity == 0


def test_credit_fragment_and_input_share_one_raw_budget():
    c, (slot,) = setup(
        reserve=lambda *_: False,
        reserve_scratch=lambda _: True,
        release_scratch=lambda _: None,
    )
    opened(c, slot)
    first, last = fragments(wire(slot, payload=bytes(700000)))
    assert feed(c, first, 2) == ()
    assert c.pending_bytes == len(first)
    assert c.input_capacity == (1 << 20) - len(first)
    # Buffered and assembled bytes cannot each retain an independent MiB.
    with pytest.raises(LiveError):
        feed(c, last + bytes(c.input_capacity + 1 - len(last)), 3)
    assert c.pending_bytes == 0


def test_credit_ack_needs_no_frame_claim_and_bad_lengths_claim_nothing():
    calls = []
    c, (slot,) = setup(reserve=lambda *args: calls.append(args) or False)
    opened(c, slot)
    assert not calls
    raw = bytearray(wire(slot))
    struct.pack_into("<i", raw, 48, -1)
    with pytest.raises(LiveError):
        feed(c, bytes(raw), 2)
    assert not calls


def test_drain_does_not_make_none_a_valid_feed_chunk():
    c, (slot,) = setup(reserve=lambda *_: False)
    opened(c, slot)
    with pytest.raises(LiveError):
        c.feed(None, generation=7)


def test_fragment_transfer_claims_exact_scratch_before_allocation_and_releases():
    borrowed = [0]
    peaks = []
    allow = [False]

    def claim(size):
        assert borrowed[0] == 0
        if not allow[0]:
            return False
        borrowed[0] = size
        return True

    def release(size):
        assert borrowed[0] == size
        assert c.pending_bytes <= 1 << 20
        borrowed[0] = 0

    class WatchedAssembly(bytearray):
        def extend(self, data):
            assert isinstance(data, memoryview)
            assert borrowed[0] == len(data) + 32
            peaks.append(c.pending_bytes + len(data))
            super().extend(data)

    c, (slot,) = setup(
        reserve=lambda *_: True, reserve_scratch=claim, release_scratch=release
    )
    c._assembly = WatchedAssembly()
    opened(c, slot)
    parts = fragments(wire(slot, payload=bytes(700000)))
    assert feed(c, b"".join(parts), 2) == ()
    assert c.blocked and c.pending_bytes == sum(map(len, parts))
    assert not peaks and not c._assembly
    allow[0] = True
    (frame,) = c.drain(generation=7)
    assert frame.slot_ordinal == 1 and borrowed[0] == 0
    assert len(peaks) == 2 and max(peaks) <= 2 << 20
    assert max(peaks) > 1 << 20
    assert c.pending_bytes == 0


def test_credit_fragment_without_host_scratch_port_fences():
    c, (slot,) = setup(reserve=lambda *_: True)
    opened(c, slot)
    with pytest.raises(LiveError):
        feed(c, fragments(wire(slot))[0], 2)


def test_fragment_transfer_failure_clears_raw_before_scratch_release():
    outstanding = []

    def claim(size):
        outstanding.append(size)
        return True

    def release(size):
        assert c.pending_bytes == 0
        assert outstanding.pop() == size

    class BrokenAssembly(bytearray):
        def extend(self, data):
            raise ValueError("synthetic allocation failure")

    c, (slot,) = setup(
        reserve=lambda *_: True, reserve_scratch=claim, release_scratch=release
    )
    c._assembly = BrokenAssembly()
    opened(c, slot)
    with pytest.raises(LiveError):
        feed(c, fragments(wire(slot))[0], 2)
    assert not outstanding


SYNTHETIC_SECRET_VERSION = UUID(int=11)


def binding_scope(secret_version=SYNTHETIC_SECRET_VERSION):
    return types().MuxScopeKey(
        UUID(int=1),
        1,
        UUID(int=2),
        bytes(32),
        UUID(int=3),
        UUID(int=4),
        UUID(int=5),
        UUID(int=6),
        1,
        secret_version,
        1,
        UUID(int=7),
    )


def test_scope_secret_version_is_exact_nonzero_uuid():
    scope = binding_scope()
    assert scope.secret_version == UUID(int=11)


@pytest.mark.parametrize(
    "value", [1, True, "synthetic-version", bytes(16), UUID(int=0)]
)
def test_scope_secret_version_rejects_non_uuid_or_zero(value):
    with pytest.raises(LiveError):
        binding_scope(value)


def original_binding(**changes):
    t = types()
    assert hasattr(t, "OriginalMuxBinding"), "original native binding is not defined"
    values = {
        "scope": binding_scope(),
        "master_id": UUID(int=12),
        "native_generation": UUID(int=13),
        "epoch": t.MuxEpochIdentity(7, SESSION),
        "channel": b"c" * 16,
        "proof": t.MasterLoginProof(True, True, True, True, True, 6),
        "_authority": object(),
        "_seal": t._NATIVE_BINDING_SEAL,
    }
    return t.OriginalMuxBinding(**(values | changes))


def test_original_binding_preserves_wire_and_sql_identity_separately():
    binding = original_binding()
    assert binding.native_generation == UUID(int=13)
    assert binding.epoch.generation == 7 and binding.epoch.session == SESSION
    assert binding.channel == b"c" * 16
    assert "private" in repr(binding)
    with pytest.raises(TypeError):
        pickle.dumps(binding)
    with pytest.raises(FrozenInstanceError):
        binding.channel = b"f" * 16


@pytest.mark.parametrize(
    "field,value",
    [
        ("_seal", object()),
        ("_seal", True),
        ("_authority", True),
        ("scope", True),
        ("master_id", 1),
        ("native_generation", 7),
        ("epoch", UUID(int=13)),
        ("channel", bytes(16)),
        ("channel", b"short"),
        ("channel", bytearray(b"c" * 16)),
        ("proof", True),
    ],
)
def test_original_binding_rejects_forged_seal_and_invalid_fields(field, value):
    with pytest.raises(LiveError):
        original_binding(**{field: value})


@pytest.mark.parametrize("field", ["channel", "scope"])
def test_original_binding_cannot_be_rebound_to_foreign_channel_or_scope(field):
    binding = original_binding()
    foreign = (
        b"f" * 16
        if field == "channel"
        else replace(binding.scope, wall_id=UUID(int=20))
    )
    with pytest.raises(ValueError, match="InitVar"):
        replace(binding, **{field: foreign})


def test_original_binding_issuer_protocols_have_only_exact_object_ports():
    t = types()
    assert hasattr(t, "OriginalMuxBindingIssuer")
    assert hasattr(t, "EpochReceiptIssuer")
    assert callable(t.OriginalMuxBindingIssuer.binding_for)
    assert callable(t.EpochReceiptIssuer.issued_receipt)


def test_wire_observation_is_first_ack_latest_validated_media_per_original_slot():
    c, (first, second) = setup(2)
    assert callable(getattr(c, "wire_observation", None)), (
        "validated wire projection missing"
    )
    assert c.wire_observation(first) == (None, None)
    opened(c, first, sequence=11, ordinal=1, code=0x20000060)
    first_ack = (2, 1, 0x10000505, 11, True)
    assert c.wire_observation(first) == (first_ack, None)
    assert c.wire_observation(second) == (None, None)
    opened(c, second, sequence=12, ordinal=2)
    feed(c, wire(first, 1, route=0), 3)
    second_wire = packet(
        65537,
        yz(channel=second.channel, task=second.task)
        + media(channel=second.channel, kind=2),
        sequence=41,
    )
    feed(c, second_wire, 4)
    assert c.wire_observation(first) == (first_ack, (0, 1, 65537, 0))
    assert c.wire_observation(second) == (
        (2, 1, 0x10000505, 12, False),
        (2, 1, 65537, 41),
    )
    previous = c.wire_observation(first)
    feed(c, wire(first, 2, route=2), 5)
    assert c.wire_observation(first) == (first_ack, (2, 1, 65537, 0))
    assert previous == (first_ack, (0, 1, 65537, 0))
    assert c.pending_bytes == 0


@pytest.mark.parametrize("bad", ["route", "task", "channel", "ack_sequence"])
def test_wire_observation_never_projects_rejected_media_or_ack(bad):
    c, (slot,) = setup()
    assert callable(getattr(c, "wire_observation", None)), (
        "validated wire projection missing"
    )
    if bad == "ack_sequence":
        c.open_slot(slot, request_guid=REQUEST, sequence=1)
        raw = packet(
            0x10000505, yz(channel=slot.channel, task=slot.task) + oz(), sequence=2
        )
    else:
        opened(c, slot)
        raw = wire(
            replace(slot, channel=b"x" * 16) if bad == "channel" else slot,
            route=1 if bad == "route" else 2,
            task=b"x" * 16 if bad == "task" else slot.task,
        )
    with pytest.raises(LiveError):
        feed(c, raw, 2)
    assert c.wire_observation(slot) == (None, None)


def test_wire_observation_unknown_or_copied_slot_is_readonly_absence():
    c, (slot,) = setup()
    assert callable(getattr(c, "wire_observation", None)), (
        "validated wire projection missing"
    )
    for query in (replace(slot), replace(slot, channel=b"z" * 16), None):
        assert c.wire_observation(query) == (None, None)
    opened(c, slot)
    assert c.wire_observation(slot) == ((2, 1, 0x10000505, 1, False), None)


def test_wire_projection_codec_import_remains_pure(monkeypatch):
    import builtins
    import sys

    name = "wso_core.tvt._mux_projection_purity"
    original = builtins.__import__
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "pydantic",
        "wso_contracts",
        "wso_tvt_bridge",
        "wso_api",
    )

    def pure_import(name, *args, **kwargs):
        assert not name.startswith(forbidden), "non-pure import in wire projection"
        return original(name, *args, **kwargs)

    spec = importlib.util.spec_from_file_location(name, api().__file__)
    fresh = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, fresh)
    monkeypatch.setattr(builtins, "__import__", pure_import)
    spec.loader.exec_module(fresh)
    assert callable(getattr(fresh.MultiplexLiveCodec, "wire_observation", None)), (
        "validated wire projection missing"
    )


def test_wire_observation_fragmented_media_uses_inner_parsed_header():
    c, (slot,) = setup()
    opened(c, slot, sequence=23)
    wire_bytes = packet(
        65537,
        yz(channel=slot.channel, task=slot.task) + media(channel=slot.channel, kind=2),
        sequence=71,
    )
    chunks = fragments(wire_bytes)
    for index, chunk in enumerate(chunks):
        feed(c, chunk, index + 2)
    assert c.wire_observation(slot) == (
        (2, 1, 0x10000505, 23, False),
        (2, 1, 65537, 71),
    )
