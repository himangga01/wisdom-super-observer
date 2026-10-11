"""Synthetic provider custody contracts; no SDK, process or recorder access."""

import importlib
import importlib.util
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from wso_core.tvt.local_media_mux_types import (
    _GRANT_SEAL,
    MasterReservation,
    MuxScopeKey,
    TransportGrant,
)
from wso_tvt_bridge import windows_socket as windows
from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget


def provider_module():
    name = "wso_tvt_bridge.local_live_mux_provider"
    assert importlib.util.find_spec(name), "original mux provider is missing"
    return importlib.import_module(name)


class Admission:
    def current_dedicated_startup(self, lease, registration, selection, *, budget):
        budget.remaining_ms()
        return self.current(lease)

    def current_transport(self, grant):
        return True

    def current_slot(self, grant):
        return True

    def current_viewer(self, grant):
        return True


def prepared_inputs():
    budget = MuxOriginalBudget(worker_epoch=uuid4())
    scope = MuxScopeKey(
        uuid4(),
        1,
        uuid4(),
        b"s" * 32,
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        uuid4(),
        1,
        budget.worker_epoch,
    )
    grant = TransportGrant(
        scope=scope,
        expires_monotonic=time.monotonic() + 20,
        native_generation=uuid4(),
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    master = MasterReservation(
        scope=scope,
        master_id=uuid4(),
        creator=True,
        transport=grant,
        deadline_monotonic=grant.expires_monotonic,
        _seal=_GRANT_SEAL,
    )
    return budget, master


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(windows, "PENDING_OWNERS", [])
    yield
    for owner in windows.pending_owner_snapshot():
        assert owner.child is None or owner.child._child_created is False, (
            "this suite must never launch a child"
        )
        owner.finish()
        windows.remove_confirmed_owner(owner)


def test_prepared_original_retained_before_any_acquisition():
    module = provider_module()
    budget, reservation = prepared_inputs()
    original = budget.reserve("base")
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, original)
    assert master.custodian.budget is budget
    owner = master.custodian.owner
    assert owner is not None and owner in windows.pending_owner_snapshot()
    assert owner.child is owner.job is owner.writer is owner.service is None
    assert master.issued_receipt() is None
    assert master.binding_for(b"c" * 16) is None
    receipt = master.close()
    assert receipt is master.issued_receipt()
    assert receipt.original_state == "NOT_CREATED"
    budget.release_confirmed(original, receipt)


def test_foreign_budget_reservation_cannot_prepare_or_free_original():
    module = provider_module()
    budget, reservation = prepared_inputs()
    other = MuxOriginalBudget(worker_epoch=budget.worker_epoch)
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    with pytest.raises(windows.ProviderError):
        provider.prepare_master(reservation, other.reserve("base"))
    assert windows.pending_owner_snapshot() == ()


def test_original_cannot_be_reprepared_or_adopt_new_scope():
    module = provider_module()
    budget, reservation = prepared_inputs()
    original = budget.reserve("base")
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, original)
    with pytest.raises(windows.ProviderError):
        provider.prepare_master(
            replace(reservation, master_id=uuid4(), _seal=_GRANT_SEAL), original
        )
    assert len(windows.pending_owner_snapshot()) == 1
    receipt = master.close()
    budget.release_confirmed(original, receipt)


def viewer_rig(*, started=True):
    from types import SimpleNamespace

    from test_local_live_mux_ipc import rig
    from wso_core.tvt.local_media_mux_types import ViewerGrant
    from wso_core.tvt.local_media_service import LocalLiveProof
    from wso_core.tvt.local_service import LocalVerifyBudget

    parent, _remote, callback, owner, (slot,) = rig()
    _budget, reservation = prepared_inputs()
    grant = ViewerGrant(
        scope=reservation.scope,
        expires_monotonic=time.monotonic() + 20,
        _authority=object(),
        _seal=_GRANT_SEAL,
        slot=slot,
        lease_id=uuid4(),
        registration=uuid4(),
    )
    master = SimpleNamespace(
        parent=parent,
        owner=owner,
        allowed=True,
        proof=LocalLiveProof(True, True, True, True, True),
    )
    master.viewer_current = lambda given: master.allowed and given is grant
    master.heartbeat = lambda deadline: None
    from threading import RLock

    master.io_lock = RLock()
    viewer = provider_module().MuxSlotViewer(master, grant)
    if started:
        viewer.start(budget=LocalVerifyBudget(5000))
    return viewer, master, callback, slot


def test_post_cut_viewer_frames_keep_real_task_not_local_generation():
    from test_local_mux_callback import invoke, key

    viewer, master, callback, slot = viewer_rig()
    try:
        invoke(callback, key(slot))
        frames = viewer.read_frames(
            max_frames=2, max_bytes=1 << 20, deadline_monotonic=time.monotonic() + 1
        )
        assert len(frames) == 1 and frames[0].slot is slot
        assert frames[0].ingress.first > viewer.cut.after_ordinal
        assert master.parent.credit_usage(slot)[0] == 1
        viewer.release_frames(frames)
        assert master.parent.credit_usage(slot) == (0, 0)
        with pytest.raises(windows.ProviderError):
            viewer.release_frames(frames)
    finally:
        master.owner.confirmed = True
        master.parent.close()


def test_cut_read_rechecks_current_after_callback():
    from test_local_mux_callback import invoke, key

    viewer, master, callback, slot = viewer_rig()
    real_read = master.parent.read_frames

    def revoke_after_read(*args, **kwargs):
        frames = real_read(*args, **kwargs)
        master.allowed = False
        return frames

    master.parent.read_frames = revoke_after_read
    try:
        invoke(callback, key(slot))
        with pytest.raises(provider_module().LocalDeviceFailure):
            viewer.read_frames(
                max_frames=2, max_bytes=1 << 20, deadline_monotonic=time.monotonic() + 1
            )
        assert master.parent.credit_usage(slot) == (0, 0)
    finally:
        master.owner.confirmed = True
        master.parent.close()


def test_viewer_receipt_waits_for_exact_returned_batch_and_media_custody():
    from test_local_mux_callback import invoke, key
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, ViewerCleanupReceipt

    viewer, master, callback, slot = viewer_rig()
    receipt = ViewerCleanupReceipt(
        lease_id=viewer.current_grant().lease_id,
        registration_id=viewer.registration,
        decoder_settled=True,
        peer_settled=True,
        media_cleared=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    viewer.attach_retirement(lambda: receipt)
    try:
        invoke(callback, key(slot))
        frames = viewer.read_frames(
            max_frames=2, max_bytes=1 << 20, deadline_monotonic=time.monotonic() + 1
        )
        assert viewer.close() is None
        assert master.parent.credit_usage(slot)[0] == 1
        viewer.release_frames(frames)
        assert viewer.close() is receipt
        assert viewer.issued_receipt() is receipt
        assert not master.owner.confirmed
    finally:
        master.owner.confirmed = True
        master.parent.close()


@pytest.fixture(autouse=True)
def retire_mux_parents():
    from test_local_live_mux_ipc import PARENTS

    yield
    for parent in PARENTS:
        returned = tuple(
            row[0]
            for row in parent._held.values()
            if all(row[0] not in queue for queue in parent._queues.values())
        )
        if returned:
            parent.release_frames(returned)
        parent._owner.confirmed = True
        parent.close()
    PARENTS.clear()


def test_native_mux_bootstrap_retains_real_login_and_inventory_before_epoch():
    from test_windows_socket import GEN, LiveNative
    from wso_tvt_bridge import windows_socket_worker as worker
    from wso_tvt_bridge.local_inventory_ipc import decode

    assert hasattr(worker, "NativeMuxWorker"), "owned mux worker branch missing"

    class Bootstrap(worker.NativeMuxWorker):
        def require(self, purpose):
            self.purposes.append(purpose)

        def publish(self, raw):
            self.observation = decode(raw)

        def serve(self, native, handle, callback, setup):
            assert callback._mux_epoch.session.hex() == setup["session"]
            assert callback._mux_epoch.generation == setup["callback_generation"]
            self.served = True

    service = Bootstrap(
        None, GEN, time.monotonic() + 2, callback_generation=int(GEN[:15], 16) + 1
    )
    service.purposes = []
    service.served = False
    native = LiveNative(group="value")
    request = windows.PrivateRequest(
        "live",
        "KR",
        "synthetic9",
        "syntheticUser",
        "syntheticSecret",
        metadata_read_opt_in=True,
        live_read_opt_in=True,
        store_ref="SERVICE",
        channel_position=1,
        stream=2,
    )
    result = worker.drive(
        native,
        request,
        GEN,
        time.monotonic() + 2,
        lambda *args: None,
        service_authority=service,
    )
    assert result.reply_accepted and result.inventory_replies == 4
    assert service.served and len(native.wires) == 5
    assert service.observation["channels"][0]["basis"] == "explicit_lp"
    assert service.observation["channels"][0]["raw_index"] == 3
    assert service.observation["same_original_session"] is True


def test_legacy_custodian_retains_pipe_and_blocks_receipt_during_supplier(monkeypatch):
    import threading

    from wso_tvt_bridge import local_live_mux_ownership as ownership
    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
    from wso_tvt_bridge.local_live_provider import LiveSelection

    budget, reservation = prepared_inputs()
    original = budget.reserve("main")
    custodian = budget.prepare(
        original,
        scope=reservation.scope,
        master_id=reservation.master_id,
        native_generation=reservation.transport.native_generation,
    )
    owner = windows.ChildOwner(None, None, ())
    windows.register_pending_owner(owner)
    custodian.register(owner)

    class Endpoint:
        closed = False

        def close(self):
            self.closed = True

    pair = Endpoint(), Endpoint()
    monkeypatch.setattr(ownership.multiprocessing, "Pipe", lambda **kwargs: pair)
    authority = LiveParentAuthority(
        time.monotonic() + 10,
        threading.Event(),
        LiveSelection(b"c" * 16, 0, 0, 1, "main"),
    )
    assert hasattr(custodian, "create_legacy_pipe"), (
        "dedicated original pipe custody missing"
    )
    with custodian.constructing():
        custodian.create_legacy_pipe(authority)
    with custodian.external_operation():
        assert not owner.finish()
        assert custodian.receipt() is None
    assert owner.finish()
    receipt = custodian.receipt()
    assert receipt is not None and all(endpoint.closed for endpoint in pair)
    budget.release_confirmed(original, receipt)


def test_dedicated_has_distinct_native_and_viewer_issuers_and_shared_budget():
    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease

    module = provider_module()
    budget, reservation = prepared_inputs()
    lease = LocalMediaLease(
        "synthetic-authority", budget.worker_epoch, uuid4(), uuid4(), _SEAL
    )
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    original = budget.reserve("main")
    assert hasattr(provider, "prepare_dedicated"), "dedicated prepared custody missing"
    main = provider.prepare_dedicated(lease, reservation.scope, original, uuid4())
    assert main.native_issuer is not main.viewer_issuer
    assert main.custodian.budget is budget
    assert main.close_native() is main.native_issuer.issued_receipt()
    assert main.close_native().master_id == lease.id
    assert main.close_native().native_generation == lease.native_generation
    budget.release_confirmed(original, main.close_native())


def test_cancelled_bootstrap_refunds_only_after_original_constructor_settles(
    monkeypatch,
):
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_service import LocalVerifyBudget
    from wso_tvt_bridge import local_live_mux_ipc as ipc

    module = provider_module()
    budget, reservation = prepared_inputs()
    original = budget.reserve("base")
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, original)
    before = ipc.media_credit_usage()
    operation = LocalVerifyBudget(5000)

    def cancelled(native, *args, **kwargs):
        assert native.owner is master.owner
        with native._mux_custodian.constructing():
            assert master.close() is None
            assert ipc.media_credit_usage()[0] == before[0] + ipc.RAW_STAGING_BYTES
            operation.cancel.set()
            raise windows.ProviderError()

    monkeypatch.setattr(windows.WindowsSocketProvider, "open_mux", cancelled)
    with pytest.raises(windows.ProviderError):
        master.start(
            LocalDeviceCredentials(
                serial="synthetic9",
                country="KR",
                username="syntheticUser",
                password="syntheticSecret",
            ),
            reservation.transport,
            budget=operation,
        )
    receipt = master.issued_receipt()
    assert receipt is not None and receipt.original_state == "NOT_CREATED"
    assert ipc.media_credit_usage() == before
    assert master.binding_for(b"c" * 16) is None
    budget.release_confirmed(original, receipt)


def test_prepared_viewer_without_media_can_retire_its_empty_registration():
    viewer, master, _callback, _slot = viewer_rig()
    from dataclasses import replace

    grant = replace(viewer.current_grant(), registration=uuid4(), _seal=_GRANT_SEAL)
    prepared = provider_module().MuxSlotViewer(master, grant)
    receipt = prepared.close()
    assert receipt is not None and receipt is prepared.issued_receipt()
    assert receipt.registration_id == grant.registration


def test_one_login_carries_twelve_original_slots(monkeypatch):
    import ctypes as ct
    import struct
    from threading import Event
    from uuid import UUID

    import test_windows_socket as fixtures
    from test_local_live_mux_ipc import Owner, Pipe
    from wso_core.tvt.local_media_mux_types import MuxSlotIdentity
    from wso_tvt_bridge import local_live_mux_ipc as ipc
    from wso_tvt_bridge import windows_socket_worker as worker

    original_login = fixtures.inventory_login_reply
    first_guid = bytes.fromhex("67452301ab89efcd0123456789abcdef")
    channels = [first_guid] + [UUID(int=i + 100).bytes_le for i in range(11)]

    def login(**kwargs):
        raw = bytearray(original_login(with_tail=False))
        raw.extend(struct.pack("<hhhh", 1, 1, 20, 12))
        for i, guid in enumerate(channels):
            raw.extend(bytes((1, i + 2, i + 3, 0)) + guid)
        raw.extend(struct.pack("<hhhh", 2, 1, 12, 1) + b"SYNTHETIC9\0\0")
        struct.pack_into("<I", raw, 4, len(raw) - 8)
        struct.pack_into("<I", raw, 20, len(raw) - 24)
        return bytes(raw)

    monkeypatch.setattr(fixtures, "inventory_login_reply", login)
    # Shared codec deliberately rejects unsolicited startup notifications.
    monkeypatch.setattr(fixtures, "startup_chain", lambda: b"")

    class Bootstrap(worker.NativeMuxWorker):
        def require(self, purpose):
            pass

        def publish(self, raw):
            pass

        def serve(self, native, handle, callback, setup):
            assert len(setup["channels"]) == 12
            buffers = []

            def send(raw):
                first, second = ct.create_string_buffer(raw), ct.create_string_buffer(1)
                buffers.extend((first, second))
                return int(
                    native.call("send", handle, first, len(raw), second, 0, None, 0)
                )

            remote = ipc.MuxRemoteAuthority(
                epoch=callback._mux_epoch,
                callback=callback,
                deadline_monotonic=time.monotonic() + 20,
                peer_capability=setup["peer_capability"],
                native_send=send,
            )
            parent = ipc.MuxParentAuthority(
                epoch=callback._mux_epoch,
                authorize=lambda *args: True,
                clock=time.monotonic,
            )
            owner = Owner()
            try:
                parent.bind_original(
                    owner,
                    connection=Pipe(remote),
                    peer_capability=setup["peer_capability"],
                    deadline_monotonic=time.monotonic() + 20,
                    cancel=Event(),
                )
                for i, row in enumerate(setup["channels"]):
                    slot = MuxSlotIdentity(
                        callback._mux_epoch,
                        bytes.fromhex(row["guid"]),
                        UUID(int=i + 200).bytes_le,
                        2,
                    )
                    parent.register_slot(slot, channel_number=row["raw_index"])
                    parent.prepare_open(
                        slot, request_guid=UUID(int=i + 300).bytes_le, sequence=i + 6
                    )
                    parent.send_open(
                        slot, deadline_monotonic=time.monotonic() + 1, cancel=Event()
                    )
                    for _ in range(10):
                        parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
                        if parent.open_acknowledged(slot):
                            break
                    assert parent.open_acknowledged(slot)
                self.slots = tuple(parent._slots.values())
            finally:
                owner.confirmed = True
                parent.close()

    service = Bootstrap(
        None, fixtures.GEN, time.monotonic() + 20, callback_generation=7
    )
    native = fixtures.LiveNative(group="empty", frames=1)
    request = windows.PrivateRequest(
        "live",
        "KR",
        "synthetic9",
        "syntheticUser",
        "syntheticSecret",
        metadata_read_opt_in=True,
        live_read_opt_in=True,
        store_ref="SERVICE",
        channel_position=1,
        stream=2,
    )
    result = worker.drive(
        native,
        request,
        fixtures.GEN,
        time.monotonic() + 20,
        lambda *args: None,
        service_authority=service,
    )
    assert result.failure == "none"
    assert native.commands.count(257) == 1 and native.commands.count(1285) == 12
    assert len(service.slots) == 12 and len({slot.task for slot in service.slots}) == 12


def test_original_crash_quarantines_without_scope_adoption():
    module = provider_module()
    budget, reservation = prepared_inputs()
    original = budget.reserve("base")
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, original)
    with master.custodian.constructing():
        master.custodian.begin_process_creation()
        # Interrupted acquisition never returned an original process handle.
    assert master.close() is None and master.issued_receipt() is None
    assert not master.owner.confirmed
    assert master.binding_for(b"c" * 16) is None
    with pytest.raises(windows.ProviderError):
        provider.prepare_master(
            replace(reservation, master_id=uuid4(), _seal=_GRANT_SEAL), original
        )
    budget.reserve("base")
    with pytest.raises(windows.ProviderBusy):
        budget.reserve("base")


@pytest.mark.parametrize(
    "kind", ["busy", "unknown", "unreaped", "foreign", "malformed", "owner_substituted"]
)
def test_mux_busy_recovery_requires_exact_original_retired_result(tmp_path, kind):
    native = windows.WindowsSocketProvider()
    generation = uuid4().hex
    folder = tmp_path / generation
    folder.mkdir()
    result_path = folder / "result.json"
    result = windows.SafeResult(
        generation,
        stage="handshake",
        failure="rejected",
        loaded=True,
        initialized=True,
        transport=True,
        connect_status=1,
        greeting_bytes=64,
        send_count=64,
        received_bytes=292,
        native_error=0x20000030,
        cleanup_attempted=True,
    )
    if kind == "unknown":
        result.native_error = 17
    if kind == "foreign":
        result.generation = uuid4().hex
    result_path.write_bytes(result.to_json() if kind != "malformed" else b"{")
    native._original_result_paths = (
        folder,
        windows.identity(folder, directory=True),
        result_path,
        windows.identity(result_path),
        generation,
    )
    native.owner = windows.ChildOwner(None, None, ())
    native.owner.confirmed = kind != "unreaped"
    native._result_owner = native.owner
    if kind == "owner_substituted":
        native.owner = windows.ChildOwner(None, None, ())
        native.owner.confirmed = True
    recovered = native.recover_retired_login_busy()
    assert (recovered is not None) == (kind == "busy")
    if recovered is not None:
        assert recovered.reaped and windows.is_login_busy(recovered)


def test_bootstrap_original_endpoint_substitution_cannot_settle(monkeypatch):
    from threading import Event

    from wso_tvt_bridge import local_live_mux_ownership as ownership

    budget, reservation = prepared_inputs()
    original = budget.reserve("base")
    custodian = budget.prepare(
        original,
        scope=reservation.scope,
        master_id=reservation.master_id,
        native_generation=reservation.transport.native_generation,
    )
    owner = windows.ChildOwner(None, None, ())
    windows.register_pending_owner(owner)
    custodian.register(owner)

    class Endpoint:
        closed = False

        def close(self):
            self.closed = True

    left, right, foreign = Endpoint(), Endpoint(), Endpoint()
    monkeypatch.setattr(
        ownership.multiprocessing, "Pipe", lambda **kwargs: (left, right)
    )
    with custodian.constructing():
        pipe = custodian.create_pipe(time.monotonic() + 5, Event())
    pipe.connection = foreign
    assert not owner.finish() and custodian.receipt() is None
    assert not foreign.closed and not left.closed
    pipe.connection = left
    assert owner.finish()
    budget.release_confirmed(original, custodian.receipt())


@pytest.mark.parametrize("supplier_kind", ["current", "retirement"])
def test_r1_stop_publishes_while_viewer_supplier_is_blocked(supplier_kind):
    from threading import Event, Thread

    viewer, master, _callback, _slot = viewer_rig()
    entered, release, stopped = Event(), Event(), Event()
    results = []

    def supplier(*args):
        entered.set()
        assert release.wait(2)
        return True if supplier_kind == "current" else None

    if supplier_kind == "current":
        master.viewer_current = supplier
        worker = Thread(target=lambda: results.append(viewer.current()))
    else:
        viewer.attach_retirement(supplier)
        worker = Thread(target=lambda: results.append(viewer.close()))
    worker.start()
    assert entered.wait(1)
    closer = Thread(target=lambda: (results.append(viewer.close()), stopped.set()))
    closer.start()
    try:
        assert stopped.wait(0.2), "Stop blocked behind viewer supplier"
        assert viewer._stopping and viewer.issued_receipt() is None
    finally:
        release.set()
        worker.join(2)
        closer.join(2)
    assert not worker.is_alive() and not closer.is_alive()
    if supplier_kind == "current":
        assert results == [None, False]


@pytest.mark.parametrize("mutation", ["exit", "owner_child", "custody"])
def test_r1_transport_rechecks_original_after_admission(mutation):
    from types import SimpleNamespace

    module = provider_module()
    budget, reservation = prepared_inputs()
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, budget.reserve("base"))
    live = [True]
    valid = [True]
    child = SimpleNamespace(poll=lambda: None if live[0] else 0)
    master.owner.child = child
    master._ready = True
    original_custodian = master.custodian
    master.custodian = SimpleNamespace(resources_current=lambda: valid[0])

    def current(grant):
        if mutation == "exit":
            live[0] = False
        if mutation == "owner_child":
            master.owner.child = SimpleNamespace(poll=lambda: None)
        if mutation == "custody":
            valid[0] = False
        return True

    provider.admission.current_transport = current
    try:
        assert master._transport_current() is False
    finally:
        master._ready = False
        master.owner.child = None
        master.custodian = original_custodian
        master.close()


def test_r1_two_prepared_masters_do_not_wait_on_excluded_sibling(monkeypatch):
    from threading import Event

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_tvt_bridge.local_live_mux_ipc import make_mux_worker_input

    module = provider_module()
    budget, reservation = prepared_inputs()
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    masters = [
        provider.prepare_master(reservation, budget.reserve("base")),
        provider.prepare_master(
            replace(reservation, master_id=uuid4(), _seal=_GRANT_SEAL),
            budget.reserve("base"),
        ),
    ]
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    from pathlib import Path

    config = windows.ProviderConfig(
        Path("X:/synthetic"), Path("X:/synthetic"), Path("X:/synthetic"), 5
    )
    masters[0].native._mux_config = config
    monkeypatch.setattr(windows, "LIVE_ATTEMPT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(windows, "mux_worker_command", lambda: ["never-launched"])
    reached = []

    def sentinel(config):
        reached.append(True)
        raise windows.ProviderError()

    monkeypatch.setattr(windows, "verify_review", sentinel)
    packet = make_mux_worker_input(
        LocalDeviceCredentials(
            serial="synthetic9", country="KR", username="inert", password="inert"
        ),
        generation=7,
        initial_expiry_ms=5000,
    )
    try:
        with pytest.raises(windows.ProviderError):
            masters[0].native.open_mux(
                packet,
                deadline_monotonic=time.monotonic() + 5,
                current=lambda: True,
                cancel=Event(),
            )
        assert reached == [True], "safe sibling prevented reaching source gate"
    finally:
        for master in masters:
            master.close()


def test_r1_actual_provider_worker_bootstrap_agrees_deadline_before_first_open(
    monkeypatch,
):
    import queue
    from threading import Thread

    import test_windows_socket as fixture
    from test_windows_socket import LiveNative
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_media_mux_types import MuxSlotIdentity, SlotRetentionGrant
    from wso_core.tvt.local_service import LocalVerifyBudget
    from wso_tvt_bridge import local_live_mux_ipc as ipc
    from wso_tvt_bridge import local_live_mux_ownership as ownership
    from wso_tvt_bridge import windows_socket_worker as worker

    class Endpoint:
        def __init__(self):
            self.incoming = queue.Queue()
            self.pending = None
            self.closed = False

        def poll(self, timeout=0):
            if self.closed:
                raise EOFError()
            if self.pending is not None:
                return True
            try:
                self.pending = self.incoming.get(timeout=timeout)
            except queue.Empty:
                return False
            return True

        def send_bytes(self, raw):
            if self.closed:
                raise EOFError()
            self.other.incoming.put(raw)

        def recv_bytes(self, maximum):
            if self.pending is None:
                assert self.poll(1)
            raw, self.pending = self.pending, None
            assert len(raw) <= maximum
            return raw

        def close(self):
            self.closed = True

    left, right = Endpoint(), Endpoint()
    left.other, right.other = right, left
    monkeypatch.setattr(
        ownership.multiprocessing, "Pipe", lambda **kwargs: (left, right)
    )
    monkeypatch.setattr(fixture, "startup_chain", lambda: b"")
    budget, reservation = prepared_inputs()
    provider = provider_module().NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    original = budget.reserve("base")
    master = provider.prepare_master(reservation, original)
    worker_services, threads, child_results = [], [], []
    native_surface = LiveNative(group="empty", frames=1)

    def launch(native, raw, *, deadline_monotonic, current, cancel):
        credentials, generation, _ = ipc.parse_mux_worker_input(raw)
        custodian = native._mux_custodian
        child = object.__new__(windows.subprocess.Popen)
        child._child_created = False
        child.returncode = None
        child.stdin = None
        child.poll = lambda: child.returncode
        child.kill = lambda: setattr(child, "returncode", 0)
        child.wait = lambda **kwargs: child.returncode
        with custodian.constructing():
            custodian.configure_input(generation)
            custodian.create_pipe(deadline_monotonic, cancel)
            custodian.begin_process_creation()
            native.owner.child = child
            custodian.retain_process(child)
        service = worker.NativeMuxWorker(
            right,
            custodian.native_generation.hex,
            deadline_monotonic,
            callback_generation=generation,
        )
        worker_services.append(service)
        request = windows.PrivateRequest(
            "live",
            credentials.country,
            credentials.serial,
            credentials.username,
            credentials.password,
            metadata_read_opt_in=True,
            live_read_opt_in=True,
            store_ref="SERVICE",
            channel_position=1,
            stream=2,
        )

        def run():
            child_results.append(
                worker.drive(
                    native_surface,
                    request,
                    custodian.native_generation.hex,
                    deadline_monotonic,
                    lambda *args: None,
                    service_authority=service,
                )
            )

        thread = Thread(target=run)
        threads.append(thread)
        thread.start()
        time.sleep(0.01)  # Deliberately separate parent/child clock reads.
        return native.owner

    monkeypatch.setattr(windows.WindowsSocketProvider, "open_mux", launch)
    startup = LocalVerifyBudget(5000)
    try:
        proof = master.start(
            LocalDeviceCredentials(
                serial="synthetic9",
                country="KR",
                username="syntheticUser",
                password="syntheticSecret",
            ),
            reservation.transport,
            budget=startup,
        )
        assert proof.login_accepted
        selection = next(iter(master._channels.values()))
        slot = MuxSlotIdentity(master._epoch, selection.guid, uuid4().bytes_le, 2)
        grant = SlotRetentionGrant(
            scope=reservation.scope,
            expires_monotonic=reservation.transport.expires_monotonic,
            _authority=object(),
            _seal=_GRANT_SEAL,
            slot=slot,
        )
        assert (
            master.open_slot(selection, grant, budget=LocalVerifyBudget(2000)) == slot
        )
        assert master.parent.deadline == worker_services[0].dispatch.deadline
        assert native_surface.commands.count(257) == 1
        assert native_surface.commands.count(1285) == 1
    finally:
        for service in worker_services:
            service.close()
        master.close()
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
        receipt = master.close()
        if receipt is not None:
            budget.release_confirmed(original, receipt)


@pytest.mark.parametrize("operation", ["slot", "renew"])
def test_r1_master_stop_publishes_during_blocked_slot_or_renewal(operation):
    from contextlib import nullcontext
    from threading import Event, Thread
    from types import SimpleNamespace

    from wso_core.tvt.local_media_mux_types import (
        MuxEpochIdentity,
        MuxSlotIdentity,
        SlotRetentionGrant,
    )
    from wso_core.tvt.local_media_service import LocalMediaChannel
    from wso_core.tvt.local_service import LocalVerifyBudget

    module = provider_module()
    budget, reservation = prepared_inputs()
    provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, budget.reserve("base"))
    epoch = MuxEpochIdentity(7, b"s" * 16)
    slot = MuxSlotIdentity(epoch, b"c" * 16, b"t" * 16, 2)
    selection = LocalMediaChannel(slot.channel, 0, 0, 1, "digital", "sub")
    grant = SlotRetentionGrant(
        scope=reservation.scope,
        expires_monotonic=reservation.transport.expires_monotonic,
        _authority=object(),
        _seal=_GRANT_SEAL,
        slot=slot,
    )
    entered, release, stopped = Event(), Event(), Event()
    calls, errors = [], []

    def blocked(*args, **kwargs):
        calls.append(operation)
        entered.set()
        assert release.wait(2)

    parent = SimpleNamespace(
        caller_operation=lambda **kwargs: nullcontext(),
        register_slot=blocked,
        prepare_open=lambda *args, **kwargs: calls.append("prepare"),
        send_open=lambda *args, **kwargs: calls.append("send"),
        open_acknowledged=lambda *args: True,
        renew=blocked,
    )
    master._parent, master._epoch, master._ready = parent, epoch, True
    master._channels[slot.channel] = selection

    def work():
        try:
            if operation == "slot":
                master.open_slot(selection, grant, budget=LocalVerifyBudget(1500))
            else:
                master.replace_grant(
                    reservation.transport,
                    replace(
                        reservation.transport,
                        expires_monotonic=reservation.transport.expires_monotonic + 1,
                        _seal=_GRANT_SEAL,
                    ),
                )
        except Exception as error:  # noqa: BLE001 -- retain thread outcome for assertion
            errors.append(type(error))

    thread = Thread(target=work)
    thread.start()
    assert entered.wait(1)
    closer = Thread(target=lambda: (master.close(), stopped.set()))
    closer.start()
    try:
        assert stopped.wait(0.2), "Master Stop blocked behind supplier"
        assert master._closed and master.issued_receipt() is None
    finally:
        release.set()
        thread.join(2)
        closer.join(2)
        master._ready = False
        master._parent = None
        master.close()
    assert not thread.is_alive() and not closer.is_alive()
    assert calls == [operation]
    assert errors == [windows.ProviderError]


@pytest.mark.parametrize(
    "legacy_state", ["current", "expired", "cancelled", "substituted"]
)
def test_r1_base_acquisition_allows_retained_current_dedicated_original(
    monkeypatch, legacy_state
):
    from pathlib import Path
    from threading import Event

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
    from wso_tvt_bridge import local_live_mux_ownership as ownership
    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
    from wso_tvt_bridge.local_live_mux_ipc import make_mux_worker_input
    from wso_tvt_bridge.local_live_provider import LiveSelection

    budget, reservation = prepared_inputs()
    provider = provider_module().NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    base = provider.prepare_master(reservation, budget.reserve("base"))
    main = provider.prepare_dedicated(
        LocalMediaLease("inert", budget.worker_epoch, uuid4(), uuid4(), _SEAL),
        reservation.scope,
        budget.reserve("main"),
        uuid4(),
    )

    class Endpoint:
        closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        ownership.multiprocessing, "Pipe", lambda **kwargs: (Endpoint(), Endpoint())
    )
    legacy = LiveParentAuthority(
        time.monotonic() + 10, Event(), LiveSelection(b"C" * 16, 0, 0, 1, "main")
    )
    child = object.__new__(windows.subprocess.Popen)
    child._child_created, child.returncode, child.stdin = False, None, None
    child.poll = lambda: child.returncode
    child.kill = lambda: setattr(child, "returncode", 0)
    child.wait = lambda **kwargs: child.returncode
    with main.custodian.constructing():
        main.custodian.create_legacy_pipe(legacy)
        main.custodian.begin_process_creation()
        main.owner.child = child
        main.custodian.retain_process(child)
    legacy._authorized = True
    legacy._setup(
        {
            "session": (b"S" * 16).hex(),
            "channel": (b"C" * 16).hex(),
            "task": (b"T" * 16).hex(),
            "open_request": (b"R" * 16).hex(),
            "peer_version": 4,
            "callback_generation": int(legacy.generation[:15], 16) + 1,
            "raw_index": 0,
            "window_index": 0,
            "ordinal": 1,
            "stream": 1,
            "live_basis": "legacy_no_group",
            "login_accepted": True,
            "serial_matched": True,
        }
    )
    # Inert retained handoff state; this is not native or first-frame acceptance.
    legacy.ready = legacy.handed_off = True
    original_connection = legacy.connection
    if legacy_state == "expired":
        legacy.deadline = time.monotonic() - 1
    if legacy_state == "cancelled":
        legacy.cancel.set()
    if legacy_state == "substituted":
        legacy.connection = Endpoint()
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    base.native._mux_config = windows.ProviderConfig(
        Path("X:/inert"), Path("X:/inert"), Path("X:/inert"), 5
    )
    monkeypatch.setattr(windows, "mux_worker_command", lambda: ["never-launched"])
    monkeypatch.setattr(windows, "LIVE_ATTEMPT_WAIT_SECONDS", 0.05)
    reached = []

    def sentinel(config):
        reached.append(True)
        raise windows.ProviderError()

    monkeypatch.setattr(windows, "verify_review", sentinel)
    raw = make_mux_worker_input(
        LocalDeviceCredentials(
            serial="synthetic9", country="KR", username="inert", password="inert"
        ),
        generation=7,
        initial_expiry_ms=5000,
    )
    try:
        with pytest.raises(windows.ProviderError):
            base.native.open_mux(
                raw,
                deadline_monotonic=time.monotonic() + 5,
                current=lambda: True,
                cancel=Event(),
            )
        assert reached == ([True] if legacy_state == "current" else []), (
            "dedicated custody/current gate mismatch"
        )
        legacy.cancel.set()
        assert not main.custodian.healthy()
    finally:
        legacy.connection = original_connection
        base.close()
        main.close_native()


@pytest.mark.parametrize("phase", ["register", "prepare", "ack"])
def test_r1_slot_caller_cancel_is_checked_after_each_control_callback(phase):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from wso_core.tvt.local_media_mux_types import (
        MuxEpochIdentity,
        MuxSlotIdentity,
        SlotRetentionGrant,
    )
    from wso_core.tvt.local_media_service import LocalMediaChannel
    from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

    budget, reservation = prepared_inputs()
    provider = provider_module().NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, budget.reserve("base"))
    epoch = MuxEpochIdentity(7, b"s" * 16)
    slot = MuxSlotIdentity(epoch, b"c" * 16, b"t" * 16, 2)
    selection = LocalMediaChannel(slot.channel, 0, 0, 1, "digital", "sub")
    grant = SlotRetentionGrant(
        scope=reservation.scope,
        expires_monotonic=reservation.transport.expires_monotonic,
        _authority=object(),
        _seal=_GRANT_SEAL,
        slot=slot,
    )
    caller = LocalVerifyBudget(1500)
    calls = []

    def control(name):
        def run(*args, **kwargs):
            calls.append(name)
            if phase == name:
                caller.cancel.set()
            return name == "ack"

        return run

    parent = SimpleNamespace(
        caller_operation=lambda **kwargs: nullcontext(),
        register_slot=control("register"),
        prepare_open=control("prepare"),
        send_open=control("send"),
        open_acknowledged=control("ack"),
    )
    master._parent, master._epoch, master._ready = parent, epoch, True
    master._channels[slot.channel] = selection
    try:
        with pytest.raises(LocalDeviceFailure) as error:
            master.open_slot(selection, grant, budget=caller)
        assert error.value.code == "LOCAL_DEVICE_CANCELLED"
        assert (
            calls
            == {
                "register": ["register"],
                "prepare": ["register", "prepare"],
                "ack": ["register", "prepare", "send", "ack"],
            }[phase]
        )
    finally:
        master._ready, master._parent = False, None
        master.close()


@pytest.mark.parametrize("kind", ["unknown", "acquiring", "interrupted"])
def test_r1_unknown_or_uncertain_sibling_still_fences_global_acquisition(
    monkeypatch, kind
):
    from pathlib import Path
    from threading import Event

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_tvt_bridge.local_live_mux_ipc import make_mux_worker_input

    budget, reservation = prepared_inputs()
    provider = provider_module().NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    )
    master = provider.prepare_master(reservation, budget.reserve("base"))
    sibling = None
    if kind == "unknown":
        unknown = windows.ChildOwner(None, None, ())
        windows.register_pending_owner(unknown)
    else:
        sibling = provider.prepare_master(
            replace(reservation, master_id=uuid4(), _seal=_GRANT_SEAL),
            budget.reserve("base"),
        )
        with sibling.custodian.constructing():
            sibling.custodian.begin_acquisition()
            if kind == "interrupted":
                sibling.custodian.begin_process_creation()
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    master.native._mux_config = windows.ProviderConfig(
        Path("X:/inert"), Path("X:/inert"), Path("X:/inert"), 5
    )
    monkeypatch.setattr(windows, "mux_worker_command", lambda: ["never-launched"])
    monkeypatch.setattr(windows, "LIVE_ATTEMPT_WAIT_SECONDS", 0.02)
    reached = []
    monkeypatch.setattr(windows, "verify_review", lambda config: reached.append(True))
    raw = make_mux_worker_input(
        LocalDeviceCredentials(
            serial="synthetic9", country="KR", username="inert", password="inert"
        ),
        generation=7,
        initial_expiry_ms=5000,
    )
    try:
        with pytest.raises(windows.ProviderBusy):
            master.native.open_mux(
                raw,
                deadline_monotonic=time.monotonic() + 5,
                current=lambda: True,
                cancel=Event(),
            )
        assert not reached
        assert master.owner.child is None
    finally:
        master.close()
        if sibling is not None:
            sibling.close()


def test_r2_denied_read_refund_serializes_with_next_original_reservation():
    from threading import Event, Thread, current_thread

    from test_local_mux_callback import invoke, key
    from wso_core.tvt.local_service import LocalDeviceFailure
    from wso_tvt_bridge import local_live_mux_ipc as ipc

    viewer, master, callback, slot = viewer_rig()
    parent = master.parent
    refund_entered, resume_refund, sibling_attempted, sibling_reserved = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    real_read, real_release = parent.read_frames, parent.release_frames
    refund_phase = [False]
    outcomes = []

    class PausedUsage(dict):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            if refund_phase[0] and current_thread().name == "denied-reader":
                refund_entered.set()
                assert resume_refund.wait(2)
            return value

    parent._usage = PausedUsage(parent._usage)

    def denied(*args, **kwargs):
        frames = real_read(*args, **kwargs)
        master.allowed = False
        return frames

    def refund(frames):
        refund_phase[0] = True
        try:
            real_release(frames)
        finally:
            refund_phase[0] = False

    parent.read_frames, parent.release_frames = denied, refund
    invoke(callback, key(slot, 1))

    def read_denied():
        try:
            viewer.read_frames(
                max_frames=2, max_bytes=1 << 20, deadline_monotonic=time.monotonic() + 1
            )
        except LocalDeviceFailure as error:
            outcomes.append(error.code)

    def reserve_next():
        sibling_attempted.set()
        with master.io_lock:
            invoke(callback, key(slot, 2))
            parent.pump(master.owner, deadline_monotonic=time.monotonic() + 1)
            sibling_reserved.set()

    reader, sibling = (
        Thread(target=read_denied, name="denied-reader"),
        Thread(target=reserve_next),
    )
    reader.start()
    try:
        assert refund_entered.wait(1)
        sibling.start()
        assert sibling_attempted.wait(1)
        sibling_reserved.wait(0.1)
        assert viewer.close() is None  # The refund operation still retains custody.
        resume_refund.set()
        reader.join(2)
        sibling.join(2)
        assert not reader.is_alive() and not sibling.is_alive()
        assert outcomes == ["LOCAL_DEVICE_DENIED"]
        expected = (1, len(key(slot, 2)))
        assert parent.credit_usage(slot) == expected
        assert ipc._SLOT_CREDITS[slot] == expected
        assert len(parent._held) == 1
        assert sum(record[1] for record in parent._held.values()) == expected[1]
    finally:
        resume_refund.set()
        reader.join(2)
        if sibling.ident is not None:
            sibling.join(2)
        # Pre-fix reproduction leaves only its local diagnostic counter stale;
        # restore that counter after the assertion so original credits can settle.
        parent._usage[slot] = (
            len(parent._held),
            sum(record[1] for record in parent._held.values()),
        )
        master.owner.confirmed = True
        parent.close()


@pytest.mark.parametrize(
    "pending_state",
    ["valid", "unregistered", "foreign", "substituted", "expired", "cancelled"],
)
def test_r2_dedicated_start_uses_exact_mux_custody_for_every_pending_owner(
    monkeypatch, pending_state
):
    from pathlib import Path
    from threading import Event

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
    from wso_core.tvt.local_media_service import LocalMediaChannel
    from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
    from wso_tvt_bridge import local_live_mux_ownership as ownership
    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
    from wso_tvt_bridge.local_live_provider import LiveSelection

    module = provider_module()
    # Separate independently registered fixture originals exercise the process-wide
    # gate; this does not reserve two mains in one coordinator budget.
    target_budget, target_reservation = prepared_inputs()
    pending_budget, pending_reservation = prepared_inputs()
    target_provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=target_budget, admission=Admission()
    )
    pending_provider = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=pending_budget, admission=Admission()
    )
    target_provider.admission.current = lambda lease: True
    target = target_provider.prepare_dedicated(
        LocalMediaLease("target", target_budget.worker_epoch, uuid4(), uuid4(), _SEAL),
        target_reservation.scope,
        target_budget.reserve("main"),
        uuid4(),
    )
    pending = pending_provider.prepare_dedicated(
        LocalMediaLease(
            "pending", pending_budget.worker_epoch, uuid4(), uuid4(), _SEAL
        ),
        pending_reservation.scope,
        pending_budget.reserve("main"),
        uuid4(),
    )

    class Endpoint:
        closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        ownership.multiprocessing, "Pipe", lambda **kwargs: (Endpoint(), Endpoint())
    )
    legacy = LiveParentAuthority(
        time.monotonic() + 10, Event(), LiveSelection(b"C" * 16, 0, 0, 1, "main")
    )
    child = object.__new__(windows.subprocess.Popen)
    child._child_created, child.returncode, child.stdin = False, None, None
    child.poll = lambda: child.returncode
    child.kill = lambda: setattr(child, "returncode", 0)
    child.wait = lambda **kwargs: child.returncode
    with pending.custodian.constructing():
        pending.custodian.create_legacy_pipe(legacy)
        pending.custodian.begin_process_creation()
        pending.owner.child = child
        pending.custodian.retain_process(child)
    legacy._authorized = True
    legacy._setup(
        {
            "session": (b"S" * 16).hex(),
            "channel": (b"C" * 16).hex(),
            "task": (b"T" * 16).hex(),
            "open_request": (b"R" * 16).hex(),
            "peer_version": 4,
            "callback_generation": int(legacy.generation[:15], 16) + 1,
            "raw_index": 0,
            "window_index": 0,
            "ordinal": 1,
            "stream": 1,
            "live_basis": "legacy_no_group",
            "login_accepted": True,
            "serial_matched": True,
        }
    )
    legacy.ready = legacy.handed_off = True  # Explicit inert handoff-state fixture.
    if pending_state == "unregistered":
        pending.owner.mux_custodian = None
    if pending_state == "foreign":
        pending.owner.mux_custodian = object()
    if pending_state == "substituted":
        other = LiveParentAuthority(time.monotonic() + 10, Event(), legacy.selection)
        other.ready = other.handed_off = True
        pending.owner.service = other
    if pending_state == "expired":
        legacy.deadline = time.monotonic() - 1
    if pending_state == "cancelled":
        legacy.cancel.set()
    assert windows.mux_owner_can_coexist(pending.owner) is (pending_state == "valid")
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    target_provider.native._mux_config = windows.ProviderConfig(
        Path("X:/inert"), Path("X:/inert"), Path("X:/inert"), 5
    )
    monkeypatch.setattr(windows, "LIVE_ATTEMPT_WAIT_SECONDS", 0.02)
    reached = []

    def source_gate(config):
        reached.append(True)
        raise windows.ProviderError()

    monkeypatch.setattr(windows, "verify_review", source_gate)
    try:
        with pytest.raises((windows.ProviderError, LocalDeviceFailure)):
            target.start(
                LocalDeviceCredentials(
                    serial="synthetic9",
                    country="KR",
                    username="inert",
                    password="inert",
                ),
                LocalMediaChannel(b"C" * 16, 0, 0, 1, "digital", "main"),
                budget=LocalVerifyBudget(1000),
            )
        assert reached == ([True] if pending_state == "valid" else [])
        assert target.owner.child is None and target.owner.job is None
    finally:
        pending.owner.mux_custodian = pending.custodian
        pending.owner.service = legacy
        target.close_native()
        pending.close_native()
        if pending_state == "substituted":
            other.close()


def test_r2_nonmux_legacy_launch_retains_its_existing_coexistence_policy(monkeypatch):
    from pathlib import Path
    from threading import Event

    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
    from wso_tvt_bridge.local_live_provider import LiveSelection

    selection = LiveSelection(b"C" * 16, 0, 0, 1, "main")
    pending_service = LiveParentAuthority(time.monotonic() + 5, Event(), selection)
    pending_service.ready = pending_service.handed_off = True
    owner = windows.ChildOwner(None, None, ())
    child = object.__new__(windows.subprocess.Popen)
    child._child_created, child.returncode, child.stdin = False, None, None
    child.poll = lambda: child.returncode
    child.kill = lambda: setattr(child, "returncode", 0)
    child.wait = lambda **kwargs: child.returncode
    owner.child, owner.service = child, pending_service
    windows.register_pending_owner(owner)
    assert not windows.mux_owner_can_coexist(owner)
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    config = windows.ProviderConfig(
        Path("X:/inert"), Path("X:/inert"), Path("X:/inert"), 5
    )
    reached = []

    def source_gate(config):
        reached.append(True)
        raise windows.ProviderError()

    monkeypatch.setattr(windows, "verify_review", source_gate)
    native = windows.WindowsSocketProvider()
    service = LiveParentAuthority(time.monotonic() + 1, Event(), selection)
    try:
        result = native.run(
            config,
            windows.PrivateRequest(
                "live",
                "KR",
                "synthetic9",
                "inert",
                "inert",
                metadata_read_opt_in=True,
                live_read_opt_in=True,
                store_ref="SERVICE",
                channel_position=1,
                stream=1,
            ),
            service=service,
            current=lambda: True,
        )
        assert reached == [True] and result.failure == "custody"
        assert native.owner is None
    finally:
        service.close()
        owner.finish()
        windows.remove_confirmed_owner(owner)
