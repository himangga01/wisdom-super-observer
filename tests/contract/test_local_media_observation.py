"""Offline observation contracts; no service, recorder or database starts."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def observation():
    path = ROOT / "scripts/test-local-devices/observation.py"
    assert path.is_file(), "optional observation helper missing"
    spec = importlib.util.spec_from_file_location("fixture_observation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_off_never_queries_identity(observation):
    assert observation.identity_fields(enabled=False, role="api") == {}


def test_shared_schema3_preserves_original_writer_terminal_digest_gate(observation):
    written = []
    observer = observation.MediaObservation(written.append, shared=True)
    observer.sample_mux_credits()
    observer.start()
    terminal = observer.close()
    snapshot = written[-1]
    assert snapshot["schema_version"] == 3
    assert snapshot["mux"]["credits"]["basis"] == "SAMPLED_CURRENT_NOT_ACTUAL_PEAK"
    assert snapshot["mux"]["credits"]["samples"] >= 1
    assert observation.complete_observation(snapshot, terminal)
    snapshot["mux"]["credits"]["host_bytes_sampled_max"] += 1
    assert not observation.complete_observation(snapshot, terminal)


def test_shared_focus_ordinal_bounds_omit_and_prevent_complete(observation):
    from uuid import uuid4

    written = []
    observer = observation.MediaObservation(written.append, shared=True, limit=2)
    identifiers = [uuid4() for _ in range(3)]
    for ref in identifiers:
        observer.record_mux_focus(ref, "RESERVE_RETURNED")
    observer.start()
    terminal = observer.close()
    snapshot = written[-1]
    assert len(snapshot["mux"]["focus"]) == 2
    assert snapshot["mux"]["omitted"] == 1
    assert terminal["status"] == "FAILED"
    assert not observation.complete_observation(snapshot, terminal)
    encoded = json.dumps(snapshot)
    assert all(
        str(ref) not in encoded and ref.hex not in encoded for ref in identifiers
    )


def test_shared_invalid_observation_is_sticky_failure_not_private_text(observation):
    from uuid import uuid4

    written = []
    observer = observation.MediaObservation(written.append, shared=True)
    observer.record_mux_focus(uuid4(), "private-secret")
    observer.start()
    terminal = observer.close()
    assert terminal["status"] == "FAILED"
    assert "private-secret" not in json.dumps(written)


def shared_prepared_fixture():
    from uuid import uuid4

    from wso_core.tvt.local_media_mux_types import (
        IngressCut,
        MasterLoginProof,
        MuxEpochIdentity,
        MuxSlotIdentity,
    )

    slot = MuxSlotIdentity(
        MuxEpochIdentity(7, uuid4().bytes), uuid4().bytes, uuid4().bytes, 2
    )
    registration = uuid4()
    grant = SimpleNamespace(slot=slot, registration=registration, lease_id=uuid4())
    cut = IngressCut(slot.epoch, slot, registration, 5, 10, 1e12)

    class Viewer:
        def __init__(self):
            self.registration, self.cut = registration, cut

        def start(self, **kwargs):
            return None

        def read_frames(self, **kwargs):
            return ()

        def close(self):
            return None

        def issued_receipt(self):
            return None

        def current_grant(self):
            return grant

    viewer = Viewer()

    class Master:
        def __init__(self):
            self.parent = SimpleNamespace(
                wire_observation=lambda _: ((2, 1, 0x10000505, 9, False), None)
            )

        def start(self, *args, **kwargs):
            return MasterLoginProof(True, True, True, True, True, 6)

        def open_slot(self, *args, **kwargs):
            return slot

        def prepare_viewer(self, *args, **kwargs):
            return viewer

        def close(self):
            return None

        def binding_for(self, *args):
            return None

        def issued_receipt(self):
            return None

    master = Master()
    reservation = SimpleNamespace(
        master_id=uuid4(), scope=SimpleNamespace(connection_id=uuid4())
    )
    provider = SimpleNamespace(prepare_master=lambda *args: master)
    selection = SimpleNamespace(ordinal=2, stream="sub")
    return provider, master, viewer, reservation, selection, grant


def test_shared_pre_registration_hooks_keep_exact_originals_and_issuers(observation):
    observer = observation.MediaObservation(lambda _: None, shared=True)
    provider, master, viewer, reservation, selection, grant = shared_prepared_fixture()
    binding, receipt = master.binding_for, master.issued_receipt
    observer.begin_source()
    wrapped = observer.wrap_mux_provider(provider)
    assert wrapped.prepare_master(reservation, object()) is master
    assert master.binding_for == binding and master.issued_receipt == receipt
    captured = master.start
    master.start(object(), object())
    assert master.start is captured
    assert master.open_slot(selection, grant) is grant.slot
    assert master.prepare_viewer(grant) is viewer
    viewer.start()
    captured_read = viewer.read_frames
    assert viewer.read_frames() == () and viewer.read_frames is captured_read
    assert viewer.close() is None
    assert master.close() is None
    snapshot = observer.snapshot()
    assert snapshot["mux"]["masters"][0]["login_proof"] == "VERIFIED_RETURN"
    assert snapshot["mux"]["slots"][0]["wire"]["ack"]["command"] == 0x10000505
    assert snapshot["mux"]["viewers"][0]["cut"]["control_sequence"] == 5
    assert snapshot["mux"]["viewers"][0]["cleanup"] == "RETAINED"
    assert snapshot["observation_failures"] == 0
    text = json.dumps(snapshot)
    assert str(grant.registration) not in text and grant.slot.channel.hex() not in text


def test_shared_projection_failure_never_masks_original_return_or_exception(
    observation,
):
    observer = observation.MediaObservation(lambda _: None, shared=True)
    provider, master, _, reservation, selection, grant = shared_prepared_fixture()
    master.parent.wire_observation = lambda _: "private-secret"
    wrapped = observer.wrap_mux_provider(provider)
    assert wrapped.prepare_master(reservation, object()) is master
    assert master.open_slot(selection, grant) is grant.slot
    assert observer.snapshot()["observation_failures"] == 1
    assert "private-secret" not in json.dumps(observer.snapshot())


def test_shared_control_facade_preserves_actual_result_and_failure(observation):
    from uuid import uuid4

    observer = observation.MediaObservation(lambda _: None, shared=True)
    result = SimpleNamespace(id=uuid4())
    error = RuntimeError("private-secret")

    def fail(*a, **k):
        raise error

    adapter = SimpleNamespace(focus_reserve=lambda *a, **k: result, focus_settle=fail)
    wrapped = observer.wrap_mux_controls(adapter)
    assert wrapped.focus_reserve("opaque-ticket") is result
    with pytest.raises(RuntimeError) as caught:
        wrapped.focus_settle("opaque-ticket")
    assert caught.value is error
    focus = observer.snapshot()["mux"]["focus"]
    assert focus[0]["reserve_returns"] == 1 and focus[0]["settle_returns"] == 0


def test_shared_viewer_receipt_cannot_certify_native_epoch(observation):
    from uuid import uuid4

    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, ViewerCleanupReceipt

    provider, master, _, reservation, _, _ = shared_prepared_fixture()
    receipt = ViewerCleanupReceipt(
        lease_id=uuid4(),
        registration_id=uuid4(),
        decoder_settled=True,
        peer_settled=True,
        media_cleared=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    master.close = lambda: receipt
    observer = observation.MediaObservation(lambda _: None, shared=True)
    assert (
        observer.wrap_mux_provider(provider).prepare_master(reservation, object())
        is master
    )
    assert master.close() is receipt
    snapshot = observer.snapshot()
    assert snapshot["observation_failures"] == 1
    assert snapshot["mux"]["masters"][0]["cleanup"] == "RETAINED"


def test_shared_exact_frame_cut_kind_peer_correlation_and_no_private_ids(observation):
    from wso_core.tvt.local_live import LiveIdentity
    from wso_core.tvt.local_media_mux_types import (
        _WIRE_SEAL,
        IngressSpan,
        MuxValidatedFrame,
    )
    from wso_core.tvt.windows_decode import DecodeBinding

    from tests.tvt_parity.test_local_media_source import frame

    provider, master, viewer, reservation, selection, grant = shared_prepared_fixture()
    raw = frame()
    object.__setattr__(
        raw,
        "identity",
        LiveIdentity(
            generation=7,
            session=grant.slot.epoch.session,
            channel=grant.slot.channel,
            task=grant.slot.task,
        ),
    )
    object.__setattr__(raw, "source_context", (3, 2, 0, 0, 128))
    item = MuxValidatedFrame(
        raw, grant.slot, IngressSpan(11, 12), 1000, 1, _seal=_WIRE_SEAL
    )
    original_batch = (item,)
    viewer.read_frames = lambda **kwargs: original_batch
    master.parent.wire_observation = lambda _: (
        (2, 1, 0x10000505, 9, False),
        (0, 1, 65537, 0),
    )
    observer = observation.MediaObservation(lambda _: None, shared=True)
    observer.begin_source()
    observer.wrap_mux_provider(provider).prepare_master(reservation, object())
    master.start(object(), object())
    master.open_slot(selection, grant)
    assert master.prepare_viewer(grant) is viewer
    viewer.start()
    assert viewer.read_frames() is original_batch

    class Peer:
        def __init__(self, **kwargs):
            pass

        def enable_observation(self):
            return {"withheld_datagrams": 0}

    module = SimpleNamespace(LocalWebRtcSession=Peer)
    observer.install_peer_observer(module)
    module.LocalWebRtcSession(
        binding=DecodeBinding(
            generation=7,
            owner=grant.slot.epoch.session,
            channel=grant.slot.channel,
            task=grant.slot.task,
        )
    )
    value = observer.snapshot()
    assert value["observation_failures"] == 0
    assert value["peers"][0]["attempt"] == value["mux"]["viewers"][0]["attempt"]
    first = value["mux"]["viewers"][0]["first"]
    assert first["selected_stream_kind"] == 2 and first["ingress_first"] == 11
    assert value["mux"]["slots"][0]["wire"]["media"]["wire_kind"] == 1
    assert value["mux"]["viewers"][0]["cut"]["control_sequence"] == 5
    assert value["mux"]["slots"][0]["wire"]["ack"]["sequence"] == 9
    assert not any(
        token in json.dumps(value)
        for token in [
            str(grant.registration),
            grant.slot.task.hex(),
            grant.slot.epoch.session.hex(),
        ]
    )


def test_shared_dedicated_correlation_preserves_original_session_and_issuer(
    observation,
):
    from uuid import uuid4

    from tests.tvt_parity.test_local_media_source import frame

    registration = uuid4()
    batch = (frame(),)
    session = SimpleNamespace(read_frames=lambda **kwargs: batch)
    native_issuer, viewer_issuer = object(), object()
    prepared = SimpleNamespace(
        start=lambda *a, **k: session,
        close_native=lambda: None,
        close_viewer=lambda: None,
        native_issuer=native_issuer,
        viewer_issuer=viewer_issuer,
    )
    provider = SimpleNamespace(prepare_dedicated=lambda *a: prepared)
    observer = observation.MediaObservation(lambda _: None, shared=True)
    actual = observer.wrap_mux_provider(provider).prepare_dedicated(
        object(), object(), object(), registration
    )
    assert (
        actual is prepared
        and actual.native_issuer is native_issuer
        and actual.viewer_issuer is viewer_issuer
    )
    assert actual.start(object(), object()) is session
    assert session.read_frames() is batch
    assert actual.close_viewer() is None and actual.close_native() is None
    value = observer.snapshot()
    assert value["observation_failures"] == 0
    assert value["mux"]["viewers"][0]["stream"] == "main"
    assert value["mux"]["dedicated"][0]["cleanup_scope"] == "DEDICATED_NATIVE"
    assert value["mux"]["viewers"][0]["cleanup_scope"] == "VIEWER"


def test_shared_unavailable_wire_never_becomes_ack_from_success(observation):
    provider, master, _, reservation, selection, grant = shared_prepared_fixture()
    del master.parent.wire_observation
    observer = observation.MediaObservation(lambda _: None, shared=True)
    observer.wrap_mux_provider(provider).prepare_master(reservation, object())
    assert master.open_slot(selection, grant) is grant.slot
    wire = observer.snapshot()["mux"]["slots"][0]["wire"]
    assert wire == {"ack": None, "media": None, "status": "UNAVAILABLE"}


def test_shared_late_projection_cannot_mutate_sticky_terminal_snapshot(observation):
    import threading

    provider, master, _, reservation, selection, grant = shared_prepared_fixture()
    entered, released = threading.Event(), threading.Event()

    def delayed(slot):
        entered.set()
        assert released.wait(2)
        return ((2, 1, 0x10000505, 9, False), None)

    master.parent.wire_observation = delayed
    observer = observation.MediaObservation(lambda _: None, shared=True)
    observer.wrap_mux_provider(provider).prepare_master(reservation, object())
    operation = threading.Thread(target=lambda: master.open_slot(selection, grant))
    operation.start()
    try:
        assert entered.wait(1)
        observer.start()
        terminal = observer.close()
        before = observer.snapshot()
        released.set()
        operation.join(1)
        assert not operation.is_alive()
        assert observer.snapshot() == before
        assert observer.close() == terminal
    finally:
        released.set()
        operation.join(2)


def test_shared_bounded_roster_still_publishes_under_r143_snapshot_cap(
    observation, tmp_path
):
    from uuid import uuid4

    path = tmp_path / "shared-observation.json"
    observer = observation.MediaObservation(
        lambda value: observation.write_snapshot(path, value), shared=True
    )
    populate_observation_roster(observation, observer, 192, maximum=True)
    for _ in range(64):
        record = observer.begin_source()
        provider, master, viewer, reservation, selection, grant = (
            shared_prepared_fixture()
        )
        observer.wrap_mux_provider(provider).prepare_master(reservation, object())
        master.start(object(), object())
        master.open_slot(selection, grant)
        master.prepare_viewer(grant)
        viewer.start()
        for _ in range(16):
            record("transition_format", "hevc,4096,1365,hevc,4096,1365")
        observer.record_mux_focus(uuid4(), "RESERVE_RETURNED")
    observer.start()
    terminal = observer.close()
    value = json.loads(path.read_bytes())
    assert value["schema_version"] == 3 and len(value["source_attempts"]) == 256
    assert len(value["mux"]["viewers"]) == len(value["mux"]["slots"]) == 64
    assert value["mux"]["omitted"] == 0
    assert path.stat().st_size <= 1024 * 1024
    assert observation.complete_observation(value, terminal)


def populate_observation_roster(observation, observer, count, *, maximum=False):
    """Exercise the real projection; substitute only native/peer resource owners."""
    from wso_core.tvt.windows_decode import DecodeBinding

    from tests.tvt_parity.test_local_media_source import frame

    item = frame()
    session = SimpleNamespace(
        _authority=SimpleNamespace(frames=[item], sub_stream_adaptation_off=False)
    )
    provider = observer.wrap_provider(
        SimpleNamespace(open_session=lambda *a, **k: session)
    )
    credentials = SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret")
    selection = SimpleNamespace(stream="main", ordinal=4096)
    binding = DecodeBinding(
        generation=item.identity.generation,
        owner=item.identity.session,
        channel=item.identity.channel,
        task=item.identity.task,
    )

    class Peer:
        def __init__(self, **kwargs):
            pass

        def enable_observation(self):
            return dict.fromkeys(
                (
                    "permit_lapse_episodes",
                    "withheld_datagrams",
                    "withheld_decoded_frames",
                ),
                2**64 - 1 if maximum else 0,
            )

    module = SimpleNamespace(LocalWebRtcSession=Peer)
    observer.install_peer_observer(module)
    for _ in range(count):
        record = observer.begin_source()
        assert provider.open_session(credentials, selection) is session
        module.LocalWebRtcSession(binding=binding)
        for stage in (
            "first_adapter_packet",
            "first_decoded_frame",
            "binding_ready",
            "peer_created",
            "peer_connected",
        ):
            record("milestone", stage)
        if maximum:
            record("timestamp_failure", "regression,-2147483647,1")
            for _ in range(16):
                record("transition_format", "hevc,4096,1365,hevc,4096,1365")
            for stage in (
                "started",
                "decoder_rotated",
                "inter_picture_omitted",
                "output_verified",
                "late_output_omitted",
            ):
                record("transition", stage)


@pytest.mark.parametrize("count", [91, 201, 256])
def test_observation_writer_publishes_complete_large_roster(
    observation, tmp_path, count
):
    path = tmp_path / "media-observation.json"
    assert callable(getattr(observation, "write_snapshot", None))
    observer = observation.MediaObservation(
        lambda value: observation.write_snapshot(path, value)
    )
    populate_observation_roster(observation, observer, count, maximum=count == 256)
    before = observer.snapshot()
    assert len((json.dumps(before, indent=2) + "\n").encode()) > 65536
    observer.start()
    terminal = observer.close()
    value = json.loads(path.read_bytes())
    assert (
        len(value["attempts"])
        == len(value["source_attempts"])
        == len(value["peers"])
        == count
    )
    assert value["stop_requested"] is True
    assert observation.complete_observation(value, terminal) is True
    assert path.stat().st_size <= 1024 * 1024
    assert "private-secret" not in path.read_text()
    assert not path.with_name(path.name + ".tmp").exists()


def test_observation_oversize_preserves_preimage_and_fails_terminal(
    observation, tmp_path
):
    path = tmp_path / "media-observation.json"
    assert callable(getattr(observation, "write_snapshot", None))
    oversized = [False]

    def write(value):
        if oversized[0]:
            value = value | {"oversize": "x" * (1024 * 1024)}
        observation.write_snapshot(path, value)

    observer = observation.MediaObservation(write)
    observer.publish()
    original = path.read_bytes()
    oversized[0] = True
    observer.publish()
    observer.start()
    terminal = observer.close()
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".tmp").exists()
    assert terminal["status"] == "FAILED"
    assert terminal["writer_settled"] is True
    assert terminal["observation_failures"] == 2
    assert terminal["snapshot_sha256"] == observation.snapshot_digest(
        json.loads(original)
    )
    assert observation.complete_observation(json.loads(original), terminal) is False


def test_observation_writer_does_not_adopt_existing_temporary(observation, tmp_path):
    path = tmp_path / "media-observation.json"
    assert callable(getattr(observation, "write_snapshot", None))
    observation.write_snapshot(path, {"original": True})
    original = path.read_bytes()
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(b"existing-owner")
    with pytest.raises(FileExistsError):
        observation.write_snapshot(path, {"replacement": True})
    assert path.read_bytes() == original
    assert temporary.read_bytes() == b"existing-owner"


def maximal_counter_envelope(value):
    """A documented 64-bit width envelope, not a bound on Python integers."""
    for row in value["source_attempts"]:
        row["first_failure"]["elapsed_ms"] = 2147483647
        # The accepted unsaturated boundary uses the one-byte-longer false.
        row["first_failure"]["timestamp"]["delta_saturated"] = False
        for entry in row["milestones"] + row["format_transitions"]:
            entry["elapsed_ms"] = 2147483647
        row["transition_counts"] = dict.fromkeys(row["transition_counts"], 2147483647)
        row["omitted_format_transitions"] = 2147483647
    for row in value["attempts"]:
        row["width"], row["height"] = 4096, 2160
    for key in (
        "attempt_count",
        "omitted_attempts",
        "observation_failures",
        "source_attempt_count",
        "omitted_source_attempts",
        "omitted_peers",
    ):
        value[key] = 2**64 - 1
    return value


def test_maximum_roster_counter_envelope_fits_finite_snapshot_bound(
    observation, tmp_path
):
    observer = observation.MediaObservation(lambda value: None)
    populate_observation_roster(observation, observer, 256, maximum=True)
    value = maximal_counter_envelope(observer.snapshot())
    path = tmp_path / "media-observation.json"
    observation.write_snapshot(path, value)
    assert json.loads(path.read_bytes()) == value
    assert path.stat().st_size < 1024 * 1024
    assert all(
        len(row["milestones"]) == 6 and len(row["format_transitions"]) == 16
        for row in value["source_attempts"]
    )
    assert "private-secret" not in path.read_text()


def test_context_writer_retains_64k_cap(observation, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "bounded_private_runtime", ROOT / "scripts/test-local-devices/runtime.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    helper = runtime.borrowed_helpers()
    path = tmp_path / "context.json"
    helper.write_private(path, {"original": True})
    original = path.read_bytes()
    with pytest.raises(ValueError):
        helper.write_private(path, {"oversize": "x" * 65536})
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "method,parent",
    [
        ("is_symlink", False),
        ("is_symlink", True),
        ("is_junction", False),
        ("is_junction", True),
    ],
)
def test_snapshot_refuses_linked_path_before_replacement(
    observation, tmp_path, monkeypatch, method, parent
):
    path = tmp_path / "media-observation.json"
    observation.write_snapshot(path, {"original": True})
    original = path.read_bytes()
    linked = path.parent if parent else path
    monkeypatch.setattr(Path, method, lambda candidate: candidate == linked)
    with pytest.raises(ValueError):
        observation.write_snapshot(path, {"replacement": True})
    assert path.read_bytes() == original


def test_snapshot_replace_failure_keeps_preimage_and_removes_owned_temporary(
    observation, tmp_path, monkeypatch
):
    path = tmp_path / "media-observation.json"
    observation.write_snapshot(path, {"original": True})
    original = path.read_bytes()

    def refused(*args):
        raise OSError("private-secret")

    monkeypatch.setattr(observation.os, "replace", refused)
    observer = observation.MediaObservation(
        lambda value: observation.write_snapshot(path, value)
    )
    observer.publish()
    assert observer.snapshot()["observation_failures"] == 1
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".tmp").exists()


def test_historical_duplicate_timestamp_event_remains_a_closed_failure(observation):
    observer = observation.MediaObservation(lambda value: None)
    observer.begin_source()("timestamp_failure", "duplicate,0,0")
    failure = observer.snapshot()["source_attempts"][0]["first_failure"]
    assert failure["reason"] == "timestamp_invalid"
    assert failure["timestamp"] == {
        "kind": "duplicate",
        "delta_us": 0,
        "delta_saturated": False,
    }
    assert observer.snapshot()["observation_failures"] == 0


@pytest.mark.parametrize(
    "timestamp,kind,delta,saturated",
    [
        (None, "missing", None, False),
        (999000, "regression", -1000, False),
        (-(2**63), "regression", -2147483647, True),
        (2**63, "invalid", None, False),
    ],
)
def test_timestamp_failure_reaches_sticky_deep_copied_terminal_hash(
    observation, timestamp, kind, delta, saturated
):
    from wso_tvt_media.codec import MediaDenied
    from wso_tvt_media.native_source import NativeFrameAdapter

    from tests.tvt_parity.test_local_media_source import PROOF, frame

    written = []
    now = [1.0]
    observer = observation.MediaObservation(written.append, clock=lambda: now[0])
    record = observer.begin_source()
    adapter = NativeFrameAdapter(PROOF, observe=record)
    adapter.packet(frame())
    now[0] = 1.25
    with pytest.raises(MediaDenied):
        adapter.packet(frame(timestamp=timestamp))
    expected = {
        "stage": "adapter",
        "reason": "timestamp_invalid",
        "elapsed_ms": 250,
        "timestamp": {"kind": kind, "delta_us": delta, "delta_saturated": saturated},
    }
    record("timestamp_failure", "regression,-5000,0")
    record("source", "explicit_close")
    snapshot = observer.snapshot()
    assert snapshot["source_attempts"][0]["first_failure"] == expected
    snapshot["source_attempts"][0]["first_failure"]["timestamp"]["kind"] = (
        "private-secret"
    )
    assert observer.snapshot()["source_attempts"][0]["first_failure"] == expected
    assert written == []
    observer.start()
    terminal = observer.close()
    assert terminal["status"] == "COMPLETE"
    assert observation.complete_observation(written[-1], terminal) is True
    record("timestamp_failure", "missing,,0")
    assert observer.snapshot()["source_attempts"][0]["first_failure"] == expected
    written[-1]["source_attempts"][0]["first_failure"]["timestamp"]["delta_us"] = -123
    assert observation.complete_observation(written[-1], terminal) is False
    assert observer.snapshot()["source_attempts"][0]["first_failure"] == expected


@pytest.mark.parametrize(
    "event",
    [
        "private-secret",
        "regression,-1,0,private-secret",
        "regression,1,0",
        "regression,-2147483648,1",
        "regression,-1,1",
        "duplicate,-1,0",
        "missing,0,0",
        "invalid,,1",
        "duplicate,0,1",
        "regression,-01,0",
        "regression," + "9" * 1000 + ",0",
        {"kind": "private-secret"},
    ],
)
def test_timestamp_metadata_rejects_untrusted_schema_and_fails_completion(
    observation, event
):
    written = []
    observer = observation.MediaObservation(written.append)
    record = observer.begin_source()
    record("timestamp_failure", event)
    value = observer.snapshot()
    assert value["source_attempts"][0]["first_failure"] is None
    assert value["observation_failures"] == 1
    assert "private-secret" not in json.dumps(value)
    observer.start()
    assert observer.close()["status"] == "FAILED"


@pytest.mark.parametrize("reason", ["format_changed", "timestamp_invalid"])
def test_timestamp_metadata_cannot_replace_prior_failure_or_exceed_row_bound(
    observation, reason
):
    observer = observation.MediaObservation(lambda value: None, limit=1)
    record = observer.begin_source()
    record("adapter", reason)
    record("timestamp_failure", "regression,-1,0")
    observer.begin_source()("timestamp_failure", "regression,-1,0")
    value = observer.snapshot()
    assert value["source_attempts"][0]["first_failure"]["reason"] == reason
    assert "timestamp" not in value["source_attempts"][0]["first_failure"]
    assert value["omitted_source_attempts"] == 1


def test_first_failure_sticky_bounded_and_closed_schema(observation):
    now = [10.0]
    observer = observation.MediaObservation(
        lambda value: None, limit=1, clock=lambda: now[0]
    )
    record = observer.begin_source()
    now[0] = 10.125
    record("adapter", "format_changed")
    now[0] = 20.0
    record("source", "explicit_close")
    assert observer.snapshot()["source_attempts"] == [
        {
            "source_attempt": 1,
            "first_failure": {
                "stage": "adapter",
                "reason": "format_changed",
                "elapsed_ms": 125,
            },
            "milestones": [],
            "transition_counts": {
                "started": 0,
                "decoder_rotated": 0,
                "inter_picture_omitted": 0,
                "output_verified": 0,
                "late_output_omitted": 0,
            },
            "format_transitions": [],
            "omitted_format_transitions": 0,
        }
    ]
    observer.begin_source()("private-secret", "private-secret")
    assert observer.snapshot()["omitted_source_attempts"] == 1
    assert "private-secret" not in json.dumps(observer.snapshot())
    observer.start()
    assert observer.close()["status"] == "FAILED"


def test_failed_pre_peer_start_keeps_native_source_correlation(observation):
    from tests.tvt_parity.test_local_media_source import frame

    observer = observation.MediaObservation(lambda value: None)
    record = observer.begin_source()
    session = SimpleNamespace(
        _authority=SimpleNamespace(frames=[frame()], sub_stream_adaptation_off=False)
    )
    wrapped = observer.wrap_provider(
        SimpleNamespace(open_session=lambda *a, **k: session)
    )
    assert (
        wrapped.open_session(
            SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret"),
            SimpleNamespace(stream="sub", ordinal=1),
        )
        is session
    )
    record("decoder_decode", "failure")
    value = observer.snapshot()
    assert value["attempts"][0]["source_attempt"] == 1
    assert value["source_attempts"][0]["first_failure"]["stage"] == "decoder_decode"
    assert value["peers"] == []
    assert "private-secret" not in json.dumps(value)


def test_milestones_bounded_unique_and_invalid_events_fail_evidence(observation):
    now = [1.0]
    observer = observation.MediaObservation(lambda value: None, clock=lambda: now[0])
    record = observer.begin_source()
    now[0] = 1.25
    record("milestone", "native_return")
    now[0] = 1.5
    record("milestone", "native_return")
    record("private-secret", "failure")
    record("adapter", "private-secret")
    value = observer.snapshot()
    assert value["source_attempts"][0]["milestones"] == [
        {"stage": "native_return", "elapsed_ms": 250}
    ]
    assert value["observation_failures"] == 2
    assert value["source_attempts"][0]["first_failure"] is None
    assert "private-secret" not in json.dumps(value)


def test_format_transitions_have_safe_bounded_metadata_and_counters(observation):
    observer = observation.MediaObservation(lambda value: None)
    record = observer.begin_source()
    for _ in range(20):
        record("transition_format", "hevc,352,240,hevc,1280,720")
        record("transition", "started")
        record("transition", "decoder_rotated")
        record("transition", "inter_picture_omitted")
        record("transition", "output_verified")
    value = observer.snapshot()
    row = value["source_attempts"][0]
    assert row["first_failure"] is None and value["observation_failures"] == 0
    assert len(row["format_transitions"]) == 16
    assert row["omitted_format_transitions"] == 4
    assert row["transition_counts"] == {
        "started": 20,
        "decoder_rotated": 20,
        "inter_picture_omitted": 20,
        "output_verified": 20,
        "late_output_omitted": 0,
    }
    assert row["format_transitions"][0]["old"] == {
        "codec": "hevc",
        "width": 352,
        "height": 240,
    }
    assert row["format_transitions"][0]["new"] == {
        "codec": "hevc",
        "width": 1280,
        "height": 720,
    }
    record("transition_format", "private-secret")
    record("transition_format", "hevc,352,240,h264,1280,720")
    record("transition_format", "hevc,352,240,hevc,9000,720")
    record("transition", "private-secret")
    record("format_transition", "rotation_limit")
    value = observer.snapshot()
    assert value["observation_failures"] == 4
    assert value["source_attempts"][0]["first_failure"]["reason"] == "rotation_limit"
    assert "private-secret" not in json.dumps(value)


def test_source_queue_wait_timeout_is_a_fixed_sticky_failure(observation):
    observer = observation.MediaObservation(lambda value: None)
    record = observer.begin_source()
    record("ingress_queue", "wait_timeout")
    record("source", "explicit_close")
    value = observer.snapshot()
    assert value["observation_failures"] == 0
    failure = value["source_attempts"][0]["first_failure"]
    assert failure["stage"] == "ingress_queue" and failure["reason"] == "wait_timeout"


def test_identity_schema_preserves_exact_filetime_and_rejects_unknown_role(observation):
    value = observation.owner_identity("worker", 42, 134000000000000001)
    assert value == {
        "role": "worker",
        "pid": 42,
        "creation_filetime": "134000000000000001",
    }
    with pytest.raises(ValueError):
        observation.owner_identity("private-secret", 42, 1)
    with pytest.raises(ValueError):
        observation.owner_identity("api", True, 1)


def test_metadata_uses_parsed_kind_not_requested_stream_and_closed_schema(observation):
    from tests.tvt_parity.test_local_media_source import frame

    item = frame()
    value = observation.first_media(item, "sub", True)
    assert value == {
        "requested_stream": "sub",
        "media_kind": 1,
        "codec": "h265",
        "width": 64,
        "height": 48,
        "sub_stream_adaptation_off": True,
    }
    assert not any(
        word in json.dumps(value)
        for word in ("session", "channel", "task", "payload", "sdp")
    )
    with pytest.raises(ValueError):
        observation.first_media(item, "secret", True)


def test_observer_failure_returns_original_session_and_preserves_close(observation):
    from tests.tvt_parity.test_local_media_source import frame

    session = SimpleNamespace(
        _authority=SimpleNamespace(frames=[frame()], sub_stream_adaptation_off=False)
    )
    provider = SimpleNamespace(open_session=lambda *a, **k: session)
    observer = observation.MediaObservation(
        lambda value: (_ for _ in ()).throw(OSError("private-secret"))
    )
    wrapped = observer.wrap_provider(provider)
    credentials = SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret")
    selection = SimpleNamespace(stream="sub", ordinal=3)
    assert wrapped.open_session(credentials, selection) is session
    observer.publish()
    assert observer.snapshot()["observation_failures"] == 1
    assert "private-secret" not in json.dumps(observer.snapshot())


def test_bounded_attempts_and_private_recorder_correlation(observation):
    from tests.tvt_parity.test_local_media_source import frame

    session = SimpleNamespace(
        _authority=SimpleNamespace(frames=[frame()], sub_stream_adaptation_off=False)
    )
    observer = observation.MediaObservation(lambda value: None, limit=2)
    wrapped = observer.wrap_provider(
        SimpleNamespace(open_session=lambda *a, **k: session)
    )
    credentials = SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret")
    for _ in range(3):
        assert (
            wrapped.open_session(credentials, SimpleNamespace(stream="sub", ordinal=4))
            is session
        )
    result = observer.snapshot()
    assert result["attempt_count"] == 3 and result["omitted_attempts"] == 1
    assert [row["attempt"] for row in result["attempts"]] == [1, 2]
    assert result["attempts"][0]["channel_ordinal"] == 4
    assert "private-secret" not in json.dumps(result)


def test_runtime_opt_in_and_source_closure(observation, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "obs_runtime", ROOT / "scripts/test-local-devices/runtime.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    assert runtime.observation_enabled() is False
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", "1")
    assert runtime.observation_enabled() is False
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    assert runtime.observation_enabled() is True
    assert "scripts/test-local-devices/observation.py" in runtime.MEDIA_SOURCES
    assert "tests/contract/test_local_media_observation.py" in runtime.MEDIA_SOURCES


def test_node_self_identity_default_off_exact_bits_and_fixed_failure():
    import subprocess

    script = """
      import assert from 'node:assert/strict';
      import { measurementIdentity } from './scripts/test-local-devices/server.mjs';
      assert.deepEqual(measurementIdentity('next', {enabled:false, run:()=>{throw Error('unexpected')}}), {});
      const result = measurementIdentity('next', {enabled:true, run:(exe,args,options)=>{
        if (args.includes('-c')) return {status:0, stdout:JSON.stringify(process.execPath)};
        assert.equal(args.at(-2), String(process.pid));
        assert.equal(options.shell, false);
        assert.equal(options.timeout, 5000);
        return {status:0, stdout:JSON.stringify({role:'next',pid:process.pid,creation_filetime:'134000000000000001'})};
      }});
      assert.equal(result.measurement_owner.creation_filetime, '134000000000000001');
      assert.deepEqual(measurementIdentity('next', {enabled:true, run:()=>({status:1,stderr:'private-secret'})}), {measurement_owner_error:'IDENTITY_UNAVAILABLE'});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows self identity")
def test_live_self_identity_probe_has_exact_private_record(observation):
    import os
    import subprocess

    value = observation.windows_identity("api")
    assert value["pid"] == os.getpid()
    assert int(value["creation_filetime"]) > 0
    with pytest.raises(ValueError):
        observation.windows_identity("api", caller=os.getpid())
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import {measurementIdentity} from './scripts/test-local-devices/server.mjs'; const v=measurementIdentity('next',{enabled:true}); if (!v.measurement_owner) process.exitCode=1;",
        ],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""


def test_failed_open_is_counted_and_original_error_preserved(observation):
    error = ValueError("private-secret")

    def fail(*args, **kwargs):
        raise error

    observer = observation.MediaObservation(lambda value: None)
    wrapped = observer.wrap_provider(SimpleNamespace(open_session=fail))
    with pytest.raises(ValueError) as caught:
        wrapped.open_session(
            SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret"),
            SimpleNamespace(stream="sub", ordinal=3),
        )
    assert caught.value is error
    result = observer.snapshot()
    assert result["attempts"] == [
        {
            "attempt": 1,
            "recorder_ordinal": 1,
            "channel_ordinal": 3,
            "requested_stream": "sub",
            "outcome": "OPEN_FAILED",
        }
    ]
    assert result["omitted_attempts"] == 0
    assert "private-secret" not in json.dumps(result)


async def test_peer_counts_correlate_to_private_attempt_without_id_export(
    observation, monkeypatch
):
    import time

    from wso_tvt_media.live import BoundedDecodedSource, LocalWebRtcSession
    from wso_tvt_media.native_source import NativeFrameAdapter

    from tests.tvt_parity.test_local_media_source import PROOF, frame

    item = frame()
    binding = NativeFrameAdapter(PROOF).packet(item).binding
    observer = observation.MediaObservation(lambda value: None)
    wrapped = observer.wrap_provider(
        SimpleNamespace(
            open_session=lambda *a, **k: SimpleNamespace(
                _authority=SimpleNamespace(
                    frames=[item], sub_stream_adaptation_off=True
                )
            )
        )
    )
    wrapped.open_session(
        SimpleNamespace(to_encrypt_bytes=lambda: b"private-secret"),
        SimpleNamespace(stream="sub", ordinal=3),
    )
    module = SimpleNamespace(LocalWebRtcSession=LocalWebRtcSession)
    observer.install_peer_observer(module)
    peer = module.LocalWebRtcSession(
        binding=binding,
        source=BoundedDecodedSource(binding=binding, current=lambda: True),
        current=lambda: True,
        permitted=lambda: False,
        expires_at=time.monotonic() + 15,
    )
    try:
        peer._permitted()
        result = observer.snapshot()
        assert result["peers"] == [
            {
                "peer_ordinal": 1,
                "attempt": 1,
                "permit_lapse_episodes": 1,
                "withheld_datagrams": 0,
                "withheld_decoded_frames": 0,
            }
        ]
        assert "private-secret" not in json.dumps(result)
    finally:
        await peer.close()


def test_optional_writer_start_failure_never_raises_or_joins_unstarted_thread(
    observation, monkeypatch
):
    observer = observation.MediaObservation(lambda value: None)

    def fail_start(self):
        raise RuntimeError("private-secret")

    monkeypatch.setattr(observation.threading.Thread, "start", fail_start)
    observer.start()
    observer.close()
    assert observer.snapshot()["observation_failures"] == 1


def test_blocked_optional_writer_never_blocks_resource_cleanup(observation):
    import threading

    started, release = threading.Event(), threading.Event()

    def write(value):
        started.set()
        release.wait(3)

    observer = observation.MediaObservation(write)
    observer.start()
    try:
        assert started.wait(2)
        import time

        before = time.monotonic()
        observer.close()
        assert time.monotonic() - before < 1
        assert observer.snapshot()["observation_failures"] == 1
    finally:
        release.set()


def test_blocked_final_publish_cannot_certify_after_close_returns(
    observation, tmp_path
):
    import threading
    import time

    entered, release = threading.Event(), threading.Event()
    summary_path, terminal_path = (
        tmp_path / "summary.json",
        tmp_path / "worker-close.json",
    )
    written = []

    def write(value):
        entered.set()
        release.wait(3)
        written.append(value)
        summary_path.write_text(json.dumps(value), encoding="utf-8")

    observer = observation.MediaObservation(write)
    observer.start()
    try:
        before = time.monotonic()
        terminal = observer.close()
        assert time.monotonic() - before < 1
        assert entered.is_set()
        assert terminal is not None, (
            "close must return an independent terminal decision"
        )
        assert terminal["status"] == "FAILED"
        assert terminal["writer_settled"] is False
        assert terminal["observation_failures"] == 1
        terminal_path.write_text(
            json.dumps({"mediaObservation": terminal}), encoding="utf-8"
        )
        release.set()
        observer._thread.join(timeout=1)
        assert written[-1]["stop_requested"] is True
        assert written[-1]["observation_failures"] == 0
        assert (
            observation.complete_observation(
                json.loads(summary_path.read_text()),
                observation.read_terminal(terminal_path),
            )
            is False
        )
        assert observer.close() == terminal
        assert observation.complete_observation(written[-1], terminal) is False
    finally:
        release.set()
        observer._thread.join(timeout=1)


def test_final_writer_exception_is_sticky_and_clean_final_write_is_bound(observation):
    failed = observation.MediaObservation(
        lambda value: (_ for _ in ()).throw(OSError("private-secret"))
    )
    failed.start()
    terminal = failed.close()
    assert terminal is not None
    assert terminal["status"] == "FAILED"
    assert terminal["observation_failures"] == 1
    assert "private-secret" not in json.dumps(terminal)
    written = []
    clean = observation.MediaObservation(written.append)
    clean.start()
    terminal = clean.close()
    assert terminal["status"] == "COMPLETE"
    assert terminal["writer_settled"] is True
    assert observation.complete_observation(written[-1], terminal) is True
    changed = dict(written[-1], attempt_count=123)
    assert observation.complete_observation(changed, terminal) is False
    assert observation.complete_observation(written[-1], None) is False


def test_original_custodian_reads_closed_terminal_and_rejects_missing_or_extra(
    observation, tmp_path
):
    written = []
    observer = observation.MediaObservation(written.append)
    observer.start()
    terminal = observer.close()
    path = tmp_path / "worker-close.json"
    path.write_text(json.dumps({"mediaObservation": terminal}), encoding="utf-8")
    assert observation.read_terminal(path) == terminal
    path.write_text(
        json.dumps({"mediaObservation": {**terminal, "private": "secret"}}),
        encoding="utf-8",
    )
    assert observation.read_terminal(path) == {
        "schema_version": 1,
        "status": "UNAVAILABLE",
    }
    path.unlink()
    assert observation.read_terminal(path) == {
        "schema_version": 1,
        "status": "UNAVAILABLE",
    }
