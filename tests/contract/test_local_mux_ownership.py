"""Original custody tests: inert Python and owned Windows handles only."""

import ctypes as ct
import importlib
import io
import json
import subprocess
import threading
import time
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from wso_core.tvt.local_media_mux_types import (
    _CUSTODY_SEAL,
    MuxEpochIdentity,
    MuxScopeKey,
    MuxSlotIdentity,
)
from wso_tvt_bridge import windows_socket as p


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(p, "PENDING_OWNERS", [])


def prepared(kind="base"):
    budget = ownership().MuxOriginalBudget(worker_epoch=uuid4())
    reservation = budget.reserve(kind)
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
        UUID(int=11),  # Synthetic connection-secret version UUID.
        1,
        budget.worker_epoch,
    )
    custodian = budget.prepare(
        reservation, scope=scope, master_id=uuid4(), native_generation=uuid4()
    )
    return budget, reservation, custodian


def registered(custodian):
    owner = p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()))
    p.register_pending_owner(owner)
    custodian.register(owner)
    return owner


def ownership():
    return importlib.import_module("wso_tvt_bridge.local_live_mux_ownership")


def test_two_base_one_main_and_uncertain_owner_are_charged():
    budget = ownership().MuxOriginalBudget(worker_epoch=uuid4())
    base = [budget.reserve("base") for _ in range(2)]
    main = budget.reserve("main")
    assert base[0] is not base[1] and main.kind == "main"
    for kind in ("base", "main"):
        with pytest.raises(p.ProviderBusy):
            budget.reserve(kind)


@pytest.mark.parametrize("memory", [None, 512 << 20])
def test_original_job_memory_limit512mib(memory):
    job = p.OwnedJob(process_memory_bytes=memory)
    try:
        job.create()
        query = job.kernel.QueryInformationJobObject
        query.argtypes = [ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32, ct.c_void_p]
        query.restype = ct.c_int
        limits = p.JobExtendedLimits()
        assert query(job.handle, 9, ct.byref(limits), ct.sizeof(limits), None)
        assert limits.basic.flags == (0x2108 if memory else 0x2008)
        assert limits.basic.active_processes == 1
        assert limits.process_memory == (memory or 0)
    finally:
        job.close()


def test_not_created_requires_registered_quiescent_constructor_and_exact_receipt():
    budget, reservation, custodian = prepared()
    assert custodian.receipt() is None
    owner = registered(custodian)
    try:
        with custodian.constructing():
            assert custodian.receipt() is None
        assert owner.finish()
        receipt = custodian.receipt()
        assert receipt.original_state == "NOT_CREATED"
        for changed in (
            {"_authority": object()},
            {"master_id": uuid4()},
            {"native_generation": uuid4()},
            {"worker_epoch": uuid4()},
        ):
            with pytest.raises(p.ProviderError):
                budget.release_confirmed(
                    reservation, replace(receipt, **changed, _seal=_CUSTODY_SEAL)
                )
        budget.release_confirmed(reservation, receipt)
        assert budget.reserve("base")
        with pytest.raises(p.ProviderError):
            budget.release_confirmed(reservation, receipt)
    finally:
        owner.finish()
        p.remove_confirmed_owner(owner)


def test_failed_ownership_never_adopts_new_pid():
    budget, reservation, custodian = prepared()
    owner = registered(custodian)
    try:
        with custodian.constructing():
            custodian.begin_process_creation()
            # Interrupted Popen may have created an original without returning it.
        assert not owner.finish()
        assert not owner.confirmed and custodian.receipt() is None
        with pytest.raises(p.ProviderError):
            budget.bind_original(
                reservation, p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()))
            )
        budget.reserve("base")
        with pytest.raises(p.ProviderBusy):
            budget.reserve("base")
    finally:
        p.remove_confirmed_owner(owner)


def test_physical_slots_remain_charged_until_original_receipt():
    budget, reservation, custodian = prepared()
    owner = registered(custodian)
    epoch = MuxEpochIdentity(1, b"s" * 16)
    try:
        for n in range(16):
            budget.register_slot(
                reservation,
                MuxSlotIdentity(epoch, (n + 1).to_bytes(16), (n + 20).to_bytes(16), 2),
            )
        with pytest.raises(p.ProviderBusy):
            budget.register_slot(
                reservation, MuxSlotIdentity(epoch, b"x" * 16, b"y" * 16, 2)
            )
        with custodian.constructing():
            pass
        owner.finish()
        budget.release_confirmed(reservation, custodian.receipt())
        assert budget.reserve("base")
    finally:
        owner.finish()
        p.remove_confirmed_owner(owner)


def test_dedicated_main_consumes_one_of_sixteen_physical_slots():
    budget, reservation, _ = prepared()
    budget.reserve("main")
    epoch = MuxEpochIdentity(1, b"s" * 16)
    for n in range(15):
        budget.register_slot(
            reservation,
            MuxSlotIdentity(epoch, (n + 1).to_bytes(16), (n + 20).to_bytes(16), 2),
        )
    with pytest.raises(p.ProviderBusy):
        budget.register_slot(
            reservation, MuxSlotIdentity(epoch, b"x" * 16, b"y" * 16, 2)
        )


def test_no_main_original_when_all_physical_slots_are_retained():
    budget, reservation, _ = prepared()
    epoch = MuxEpochIdentity(1, b"s" * 16)
    for n in range(16):
        budget.register_slot(
            reservation,
            MuxSlotIdentity(epoch, (n + 1).to_bytes(16), (n + 20).to_bytes(16), 2),
        )
    with pytest.raises(p.ProviderBusy):
        budget.reserve("main")


@pytest.mark.parametrize("case", ["cancel", "current", "deadline"])
def test_cut_current_and_cancel_precede_open(case):
    cancel = threading.Event()
    if case == "cancel":
        cancel.set()
    provider = p.WindowsSocketProvider()
    with pytest.raises(p.ProviderError):
        provider.open_mux(
            b"{}",
            deadline_monotonic=time.monotonic() + (-1 if case == "deadline" else 1),
            current=lambda: case != "current",
            cancel=cancel,
        )
    assert provider.owner is None


def launch(tmp_path, monkeypatch):
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_tvt_bridge.local_live_mux_ipc import make_mux_worker_input

    budget, reservation, custodian = prepared()
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    config = p.ProviderConfig(tmp_path, tmp_path, tmp_path / "review", 3)
    provider = p.WindowsSocketProvider(mux_config=config, mux_custodian=custodian)
    packet = make_mux_worker_input(
        LocalDeviceCredentials(
            serial="SYNTHETIC9", country="KR", username="inert", password="inert-secret"
        ),
        generation=1,
        initial_expiry_ms=3000,
    )
    return provider, packet, budget, reservation, custodian


def inert_entry(monkeypatch):
    direct = str(p.direct_interpreter()[0])
    script = """import sys,json,time,ctypes as ct
assert sys.stdin.buffer.readline()==b"J\\n"
packet=json.loads(sys.stdin.buffer.read(32769))
assert packet["version"]==1 and packet["mode"]=="mux"
assert packet["job_admitted"] is True and packet["mux_input"]["mode"]=="mux"
k=ct.WinDLL("kernel32",use_last_error=True)
k.GetCurrentProcess.restype=ct.c_void_p
k.IsProcessInJob.argtypes=[ct.c_void_p,ct.c_void_p,ct.POINTER(ct.c_int)]
inside=ct.c_int()
assert k.IsProcessInJob(k.GetCurrentProcess(),None,ct.byref(inside)) and inside.value
from multiprocessing.connection import PipeConnection
connection=PipeConnection(packet["service_authority_handle"])
connection.send_bytes(b"admitted")
time.sleep(8)
"""
    monkeypatch.setattr(
        p, "mux_worker_command", lambda: [direct, "-I", "-S", "-c", script]
    )
    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "runtime_override", lambda config: {})
    monkeypatch.setattr(p, "validate_bundle", lambda *args: None)
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)


def attach_parent(custodian, owner, authorize=lambda *args: True):
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority

    parent = MuxParentAuthority(
        epoch=MuxEpochIdentity(1, b"s" * 16), authorize=authorize, clock=time.monotonic
    )
    custodian.attach_parent(
        parent,
        epoch=parent.epoch,
        peer_capability=6,
        deadline_monotonic=time.monotonic() + 3,
        cancel=threading.Event(),
    )
    return parent


def test_mux_entry_requires_review_before_os_acquisition(tmp_path, monkeypatch):
    provider, packet, budget, reservation, custodian = launch(tmp_path, monkeypatch)
    monkeypatch.setattr(p, "mux_worker_command", lambda: ["synthetic-unlaunched"])
    monkeypatch.setattr(p, "verify_review", lambda config: p.fail())
    with pytest.raises(p.ProviderError):
        provider.open_mux(
            packet,
            deadline_monotonic=time.monotonic() + 2,
            current=lambda: True,
            cancel=threading.Event(),
        )
    assert provider.owner.child is None and provider.owner.job is None
    receipt = custodian.receipt()
    assert receipt.original_state == "NOT_CREATED"
    budget.release_confirmed(reservation, receipt)


def test_real_original_launch_input_admission_and_reaped_receipt(tmp_path, monkeypatch):
    provider, packet, budget, reservation, custodian = launch(tmp_path, monkeypatch)
    inert_entry(monkeypatch)
    owner = provider.open_mux(
        packet,
        deadline_monotonic=time.monotonic() + 3,
        current=lambda: True,
        cancel=threading.Event(),
    )
    try:
        assert custodian.pipe.connection.poll(2)
        assert custodian.pipe.connection.recv_bytes(64) == b"admitted"
        attach_parent(custodian, owner)
        assert owner in p.pending_owner_snapshot() and owner.child.poll() is None
        assert custodian.receipt() is None
        assert owner.finish(1)
        receipt = custodian.receipt()
        assert receipt.original_state == "REAPED"
        assert owner.job.closed and owner.child.returncode is not None
        budget.release_confirmed(reservation, receipt)
        assert p.remove_confirmed_owner(owner)
    finally:
        owner.finish(1)


def test_reaped_child_does_not_settle_active_parent_supplier(tmp_path, monkeypatch):
    provider, packet, budget, reservation, custodian = launch(tmp_path, monkeypatch)
    inert_entry(monkeypatch)
    owner = provider.open_mux(
        packet,
        deadline_monotonic=time.monotonic() + 3,
        current=lambda: True,
        cancel=threading.Event(),
    )
    entered, release = threading.Event(), threading.Event()
    running = False

    def authorize(*args):
        if running:
            entered.set()
            release.wait(2)
        return True

    thread = None
    try:
        assert custodian.pipe.connection.poll(2)
        assert custodian.pipe.connection.recv_bytes(64) == b"admitted"
        parent = attach_parent(custodian, owner, authorize)
        running = True

        def renew():
            try:
                parent.renew(deadline_monotonic=time.monotonic() + 2)
            except ValueError:
                pass

        thread = threading.Thread(target=renew)
        thread.start()
        assert entered.wait(1)
        assert not owner.finish(0.1)
        assert owner.child.returncode is not None and thread.is_alive()
        assert not owner.confirmed and custodian.receipt() is None
        assert not custodian.pipe.connection.closed
        release.set()
        thread.join(1)
        assert not thread.is_alive() and owner.finish(1)
        budget.release_confirmed(reservation, custodian.receipt())
    finally:
        release.set()
        if thread is not None:
            thread.join(2)
        owner.finish(1)


def test_current_callback_stays_on_original_caller(tmp_path, monkeypatch):
    provider, packet, _, _, custodian = launch(tmp_path, monkeypatch)
    inert_entry(monkeypatch)
    caller = threading.get_ident()
    seen = []

    def current():
        seen.append(threading.get_ident())
        return True

    owner = provider.open_mux(
        packet,
        deadline_monotonic=time.monotonic() + 3,
        current=current,
        cancel=threading.Event(),
    )
    try:
        assert set(seen) == {caller}
    finally:
        attach_parent(custodian, owner)
        owner.finish(1)


def test_replacement_original_resources_cannot_be_certified():
    _, _, custodian = prepared()
    owner = registered(custodian)
    with custodian.constructing():
        pass
    originals = owner.outputs
    owner.outputs = (io.BytesIO(), io.BytesIO())
    for stream in owner.outputs:
        stream.close()
    try:
        assert not owner.finish()
        assert custodian.receipt() is None
    finally:
        owner.outputs = originals
        assert owner.finish()


def test_replacement_child_is_never_signalled():
    _, _, custodian = prepared()
    owner = registered(custodian)
    with custodian.constructing():
        pass

    class Foreign:
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, **kwargs):
            raise RuntimeError("unowned")

    foreign = Foreign()
    owner.child = foreign
    try:
        assert not owner.finish()
        assert not foreign.killed
    finally:
        owner.child = None
        owner.finish()


def test_r1_outputs_replaced_inside_constructor_never_become_original():
    budget, reservation, custodian = prepared()
    owner = registered(custodian)
    originals = owner.outputs
    substitutes = (io.BytesIO(), io.BytesIO())
    try:
        with custodian.constructing():
            owner.outputs = substitutes
        assert not owner.finish()
        assert custodian.receipt() is None
        assert all(not stream.closed for stream in (*originals, *substitutes))
        budget.reserve("base")
        with pytest.raises(p.ProviderBusy):
            budget.reserve("base")
        owner.outputs = originals
        assert owner.finish()
        budget.release_confirmed(reservation, custodian.receipt())
        assert all(stream.closed for stream in originals)
    finally:
        owner.outputs = originals
        owner.finish()
        for stream in substitutes:
            stream.close()


class Endpoint:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def synthetic_pipe_owner(monkeypatch):
    budget, reservation, custodian = prepared()
    owner = registered(custodian)
    endpoints = (Endpoint(), Endpoint())
    monkeypatch.setattr(ownership().multiprocessing, "Pipe", lambda **kwargs: endpoints)
    with custodian.constructing():
        custodian.configure_input(1)
        custodian.create_pipe(time.monotonic() + 3, threading.Event())
    return budget, reservation, custodian, owner, endpoints


@pytest.mark.parametrize("boundary", ["receipt", "release"])
@pytest.mark.parametrize("substitute", ["pipe", "endpoint"])
def test_r2_confirmation_substitution_never_closes_foreign_resource(
    monkeypatch, boundary, substitute
):
    budget, reservation, custodian, owner, endpoints = synthetic_pipe_owner(monkeypatch)
    parent = attach_parent(custodian, owner)
    assert owner.finish()
    receipt = custodian.receipt() if boundary == "release" else None
    original_pipe = custodian.pipe
    original_connection = original_pipe.connection
    original_confirm = parent.confirmed_closed

    class Foreign:
        calls = 0
        closed = False

        def close(self, *args):
            self.calls += 1
            self.closed = True
            return True

    foreign = Foreign()

    def substituted():
        assert original_confirm()
        if substitute == "pipe":
            custodian.pipe = foreign
        else:
            original_pipe.connection = foreign
        return True

    monkeypatch.setattr(parent, "confirmed_closed", substituted)
    try:
        if boundary == "receipt":
            assert custodian.receipt() is None
        else:
            with pytest.raises(p.ProviderError):
                budget.release_confirmed(reservation, receipt)
        assert foreign.calls == 0 and not foreign.closed
        budget.reserve("base")
        with pytest.raises(p.ProviderBusy):
            budget.reserve("base")
    finally:
        monkeypatch.setattr(parent, "confirmed_closed", original_confirm)
        custodian.pipe = original_pipe
        original_pipe.connection = original_connection
        assert owner.finish()
        budget.release_confirmed(reservation, custodian.receipt())
        assert all(endpoint.closed for endpoint in endpoints)
        assert not parent._watchdog.is_alive()


def test_r1_partial_output_acquisition_retains_and_closes_actual_handles():
    _, _, custodian = prepared()
    owner = registered(custodian)
    original = io.BytesIO()
    with pytest.raises(OSError), custodian.constructing():
        custodian.retain_output(original)
        raise OSError("next acquisition failed")
    assert owner.finish() and original.closed
    assert custodian.receipt().original_state == "NOT_CREATED"


@pytest.mark.parametrize("field", ["job", "writer", "pipe"])
def test_r1_resource_replacement_during_constructor_keeps_original_charge(
    monkeypatch, field
):
    _, _, custodian = prepared()
    owner = registered(custodian)
    with custodian.constructing():
        if field == "job":
            original = object.__new__(p.OwnedJob)
            original.handle = None
            custodian.retain_job(original)
            owner.job = object.__new__(p.OwnedJob)
            owner.job.handle = None
        elif field == "writer":
            original = threading.Thread(target=lambda: None)
            custodian.retain_writer(original)
            owner.writer = threading.Thread(target=lambda: None)
        else:
            endpoints = (Endpoint(), Endpoint())
            monkeypatch.setattr(
                ownership().multiprocessing, "Pipe", lambda **kwargs: endpoints
            )
            original = custodian.create_pipe(time.monotonic() + 1, threading.Event())
            custodian.pipe = object()
    assert not owner.finish() and custodian.receipt() is None
    if field == "pipe":
        custodian.pipe = original
    else:
        setattr(owner, field, original)
    assert owner.finish()
    assert custodian.receipt().original_state == "NOT_CREATED"


@pytest.mark.parametrize(
    "field", ["owner", "connection", "epoch", "pipe_connection", "parent"]
)
def test_r1_parent_provenance_is_rechecked_at_cleanup(monkeypatch, field):
    _, _, custodian, owner, endpoints = synthetic_pipe_owner(monkeypatch)
    parent = attach_parent(custodian, owner)
    original_scope = parent.epoch
    foreign = Endpoint()
    if field == "owner":
        parent._owner = p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()))
    elif field == "connection":
        parent.connection = foreign
    elif field == "epoch":
        parent.epoch = MuxEpochIdentity(2, b"t" * 16)
    elif field == "pipe_connection":
        custodian.pipe.connection = foreign
    else:
        custodian.parent = object()
    try:
        assert not owner.finish()
        assert custodian.receipt() is None
        assert not endpoints[0].closed and not foreign.closed
    finally:
        if field == "owner":
            parent._owner.finish()
        parent._owner = owner
        parent.connection = endpoints[0]
        parent.epoch = original_scope
        custodian.pipe.connection = endpoints[0]
        custodian.parent = parent
        assert owner.finish()
        assert custodian.receipt() is not None
        foreign.close()


def test_r1_parent_is_retained_before_fallible_initialization(monkeypatch):
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority

    _, _, custodian, owner, endpoints = synthetic_pipe_owner(monkeypatch)
    seen = []

    def deny(*args):
        seen.append(
            custodian.parent is parent
            and parent._owner is owner
            and parent.connection is endpoints[0]
        )
        return False

    parent = MuxParentAuthority(
        epoch=MuxEpochIdentity(1, b"s" * 16), authorize=deny, clock=time.monotonic
    )
    with pytest.raises(ValueError):
        custodian.attach_parent(
            parent,
            epoch=parent.epoch,
            peer_capability=6,
            deadline_monotonic=time.monotonic() + 2,
            cancel=threading.Event(),
        )
    assert seen == [True] and custodian.parent is parent
    replacement = MuxParentAuthority(
        epoch=parent.epoch, authorize=lambda *args: True, clock=time.monotonic
    )
    with pytest.raises(p.ProviderError):
        custodian.attach_parent(
            replacement,
            epoch=replacement.epoch,
            peer_capability=6,
            deadline_monotonic=time.monotonic() + 2,
            cancel=threading.Event(),
        )
    assert replacement._owner is None and replacement._watchdog is None
    assert owner.finish() and custodian.receipt() is not None


def test_r1_original_parent_active_supplier_blocks_replacement_and_refund(monkeypatch):
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority

    _, _, custodian, owner, endpoints = synthetic_pipe_owner(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    active = False

    def authorize(*args):
        if active:
            entered.set()
            release.wait(2)
        return True

    parent = attach_parent(custodian, owner, authorize)
    active = True

    def renew():
        try:
            parent.renew(deadline_monotonic=time.monotonic() + 1)
        except ValueError:
            pass

    thread = threading.Thread(target=renew)
    thread.start()
    try:
        assert entered.wait(1)
        assert not owner.finish(0.05) and custodian.receipt() is None
        replacement = MuxParentAuthority(
            epoch=parent.epoch, authorize=lambda *args: True, clock=time.monotonic
        )
        with pytest.raises(p.ProviderError):
            custodian.attach_parent(
                replacement,
                epoch=replacement.epoch,
                peer_capability=6,
                deadline_monotonic=time.monotonic() + 1,
                cancel=threading.Event(),
            )
        assert not endpoints[0].closed and thread.is_alive()
    finally:
        release.set()
        thread.join(2)
        assert not thread.is_alive() and owner.finish()
        assert custodian.receipt() is not None


def test_r1_callback_resource_substitution_is_rechecked_before_next_launch_step(
    tmp_path, monkeypatch
):
    provider, packet, _, _, _ = launch(tmp_path, monkeypatch)
    monkeypatch.setattr(p, "mux_worker_command", lambda: ["unexecuted"])

    def forbidden(config):
        raise AssertionError("launch continued after original resource substitution")

    monkeypatch.setattr(p, "verify_review", forbidden)
    substitutes = (io.BytesIO(), io.BytesIO())

    def current():
        if provider.owner is not None:
            provider.owner.outputs = substitutes
        return True

    try:
        with pytest.raises(p.ProviderError):
            provider.open_mux(
                packet,
                deadline_monotonic=time.monotonic() + 1,
                current=current,
                cancel=threading.Event(),
            )
        assert provider.owner.child is None and not provider.owner.confirmed
    finally:
        for stream in substitutes:
            stream.close()
        if provider.owner is not None:
            provider.owner.outputs = ()
            provider.owner.finish()


def test_r1_initial_output_container_is_copied_by_member_identity():
    _, _, custodian = prepared()
    originals = [io.BytesIO(), io.BytesIO()]
    original_handles = tuple(originals)
    owner = p.ChildOwner(None, None, originals)
    p.register_pending_owner(owner)
    custodian.register(owner)
    substitute = io.BytesIO()
    with custodian.constructing():
        originals[0] = substitute
    try:
        assert not owner.finish() and custodian.receipt() is None
    finally:
        owner.outputs = original_handles
        assert owner.finish()
        substitute.close()


def test_r1_foreign_parent_endpoint_is_rejected_even_for_same_owner():
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority

    _, _, custodian = prepared()
    owner = registered(custodian)
    original, foreign = Endpoint(), Endpoint()
    parent = MuxParentAuthority(
        epoch=MuxEpochIdentity(1, b"s" * 16),
        authorize=lambda *args: True,
        clock=time.monotonic,
    )

    class Pipe:
        connection = original

        def close(self, timeout):
            self.connection.close()
            return True

    try:
        with custodian.constructing():
            custodian.pipe = Pipe()
        parent.bind_original(
            owner,
            connection=foreign,
            peer_capability=6,
            deadline_monotonic=time.monotonic() + 2,
            cancel=threading.Event(),
        )
        with pytest.raises(p.ProviderError):
            custodian.attach_parent(parent)
    finally:
        parent.close()
        custodian.pipe = None
        owner.finish()
        original.close()
        foreign.close()


@pytest.mark.parametrize("reason", ["cancel", "current"])
def test_r1_contended_lock_checks_cancel_and_current_promptly(
    tmp_path, monkeypatch, reason
):
    provider, packet, _, _, _ = launch(tmp_path, monkeypatch)
    entered, cancel = threading.Event(), threading.Event()
    valid = True
    outcomes = []
    caller_threads = []

    def current():
        caller_threads.append(threading.get_ident())
        entered.set()
        return valid

    def opening():
        try:
            provider.open_mux(
                packet,
                deadline_monotonic=time.monotonic() + 1,
                current=current,
                cancel=cancel,
            )
        except p.ProviderError:
            outcomes.append("refused")

    p.ATTEMPT_LOCK.acquire()
    thread = threading.Thread(target=opening)
    try:
        thread.start()
        assert entered.wait(1)
        time.sleep(0.06)
        if reason == "cancel":
            cancel.set()
        else:
            valid = False
        thread.join(0.2)
        assert not thread.is_alive(), "startup lock ignored Stop/current"
        assert outcomes == ["refused"] and provider.owner is None
        assert set(caller_threads) == {thread.ident}
    finally:
        p.ATTEMPT_LOCK.release()
        thread.join(2)


def test_current_cut_after_job_admission_releases_no_private_input(
    tmp_path, monkeypatch
):
    provider, packet, _, _, custodian = launch(tmp_path, monkeypatch)
    inert_entry(monkeypatch)
    valid = True
    original = p.OwnedJob.admit

    def admit(job, child):
        nonlocal valid
        original(job, child)
        valid = False

    monkeypatch.setattr(p.OwnedJob, "admit", admit)
    with pytest.raises(p.ProviderError):
        provider.open_mux(
            packet,
            deadline_monotonic=time.monotonic() + 3,
            current=lambda: valid,
            cancel=threading.Event(),
        )
    owner = provider.owner
    assert owner.writer is None and owner.child.returncode is not None
    assert owner.job.closed
    assert not owner.confirmed
    # No native input ever released: process reap still does not fabricate parent proof.
    assert custodian.receipt() is None


def test_real_nested_worker_2gib_and_single_inert_512mib_original(tmp_path):
    # Test-only supervisor Job models Task12's future 2GiB process profile.
    # All children are retained Popen originals; no PID lookup or vendor code.
    direct = str(p.direct_interpreter()[0])
    sources = [
        str(p.ROOT / "services/tvt-bridge/src"),
        str(p.ROOT / "packages/core/src"),
    ]
    script = """import sys,os,time,json,ctypes as ct,subprocess
print("nested-worker-entered",file=sys.stderr,flush=True)
assert sys.stdin.buffer.read(1)==b"J"
print("nested-admitted",file=sys.stderr,flush=True)
sys.path[:0]=SOURCES
from wso_tvt_bridge import windows_socket as p
owners=[]
try:
    for index in range(1):
        print("original-start:"+str(index),file=sys.stderr,flush=True)
        owner=p.ChildOwner(None,None,(open(os.devnull,"wb"),open(os.devnull,"wb")))
        owners.append(owner)
        p.register_pending_owner(owner)
        owner.job=p.OwnedJob(process_memory_bytes=512<<20)
        owner.job.create()
        owner.child=subprocess.Popen([sys.executable,"-I","-S","-c","import sys,time;sys.stdin.buffer.read(1);time.sleep(20)"],stdin=subprocess.PIPE,stdout=owner.outputs[0],stderr=owner.outputs[1],creationflags=subprocess.CREATE_NO_WINDOW)
        owner.job.admit(owner.child)
        query=owner.job.kernel.QueryInformationJobObject
        query.argtypes=[ct.c_void_p,ct.c_int,ct.c_void_p,ct.c_uint32,ct.c_void_p]
        query.restype=ct.c_int
        limits=p.JobExtendedLimits()
        assert query(owner.job.handle,9,ct.byref(limits),ct.sizeof(limits),None)
        assert limits.basic.flags==0x2108 and limits.basic.active_processes==1 and limits.process_memory==512<<20
        owner.child.stdin.write(b"J");owner.child.stdin.flush()
    assert all(o.child.poll() is None for o in owners)
    print(json.dumps({"nested_originals":len(owners),"inner_flags":8456,"inner_process_memory":536870912}),flush=True)
finally:
    settled=[o.finish(2) for o in owners]
    assert len(settled)==1 and all(settled)
    assert all(o.job.closed and o.child.returncode is not None for o in owners)
    print("all-originals-reaped",flush=True)
""".replace("SOURCES", repr(sources))
    outputs = (
        (tmp_path / "nested.out").open("w+b"),
        (tmp_path / "nested.err").open("w+b"),
    )
    owner = p.ChildOwner(None, None, outputs)
    p.register_pending_owner(owner)
    try:
        owner.job = p.OwnedJob()
        owner.job.create()
        limits = p.JobExtendedLimits()
        limits.basic.flags = 0x2100
        limits.process_memory = 2 << 30
        assert owner.job.kernel.SetInformationJobObject(
            owner.job.handle, 9, ct.byref(limits), ct.sizeof(limits)
        )
        query = owner.job.kernel.QueryInformationJobObject
        query.argtypes = [ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32, ct.c_void_p]
        query.restype = ct.c_int
        actual = p.JobExtendedLimits()
        assert query(owner.job.handle, 9, ct.byref(actual), ct.sizeof(actual), None)
        assert actual.basic.flags == 0x2100 and actual.process_memory == 2 << 30
        owner.child = subprocess.Popen(
            [direct, "-I", "-S", "-c", script],
            stdin=subprocess.PIPE,
            stdout=outputs[0],
            stderr=outputs[1],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        owner.job.admit(owner.child)
        owner.child.stdin.write(b"J")
        owner.child.stdin.flush()
        owner.child.stdin.close()
        assert owner.child.wait(timeout=15) == 0
        outputs[0].seek(0)
        lines = outputs[0].read().splitlines()
        assert json.loads(lines[0])["nested_originals"] == 1
        assert lines[1] == b"all-originals-reaped"
        assert owner.finish(1) and owner.job.closed
    finally:
        assert owner.finish(2) and owner.job.closed
        assert owner.child.returncode is not None
        p.remove_confirmed_owner(owner)
