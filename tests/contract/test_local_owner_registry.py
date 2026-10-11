"""Original-owner registry races: synthetic owners only, no SDK or child process."""

import io
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from wso_tvt_bridge import windows_socket as p
from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
from wso_tvt_bridge.local_live_provider import OwnedLocalLiveSession

from tests.contract.test_windows_socket import live_wait_fixture


class RetiringPredecessor:
    """Remove a confirmed predecessor between ordinary field-read iterations."""

    def __init__(self, at_read):
        self.reader = threading.get_ident()
        self.at_read = at_read
        self.reads = 0
        self.request = threading.Event()
        self.finished = threading.Event()
        self.stop = threading.Event()
        self.removed = False
        self.thread = threading.Thread(target=self.retire)
        self.thread.start()

    @property
    def confirmed(self):
        if threading.get_ident() == self.reader:
            self.reads += 1
            if self.reads == self.at_read:
                self.request.set()
                assert self.finished.wait(2), "registry must not lock field evaluation"
        return True

    def retire(self):
        self.request.wait()
        if not self.stop.is_set():
            remove = getattr(p, "remove_confirmed_owner", None)
            if remove is None:  # Exercise the old remover for the causal RED run.
                p.PENDING_OWNERS.remove(self)
            else:
                remove(self)
            self.removed = True
        self.finished.set()

    def join(self):
        self.stop.set()
        self.request.set()
        self.thread.join(2)
        assert not self.thread.is_alive()

    def passive_wait(self):
        pass


@pytest.mark.parametrize("race", [False, True])
def test_confirmed_predecessor_removal_cannot_skip_uncertain_owner(monkeypatch, race):
    config, request, authority = live_wait_fixture(monkeypatch)
    predecessor = RetiringPredecessor(3 if race else 10000)
    uncertain = p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()))
    monkeypatch.setattr(p, "PENDING_OWNERS", [predecessor, uncertain])
    reached = []

    def review(config):
        reached.append(True)
        raise p.ProviderError()

    monkeypatch.setattr(p, "verify_review", review)
    try:
        with pytest.raises(p.ProviderBusy):
            p.WindowsSocketProvider().run(
                config, request, service=authority, current=lambda: True
            )
        assert not reached and not uncertain.confirmed
        assert any(owner is uncertain for owner in tuple(p.PENDING_OWNERS))
        assert predecessor.removed is race
    finally:
        predecessor.join()
        authority.close()


@pytest.mark.parametrize("race", [False, True])
def test_confirmed_predecessor_removals_cannot_admit_seventeenth(monkeypatch, race):
    config, request, authority = live_wait_fixture(monkeypatch)
    healthy = LiveParentAuthority(time.monotonic() + 3, threading.Event())
    healthy.ready = healthy.handed_off = True
    owners = [
        p.ChildOwner(
            SimpleNamespace(poll=lambda: None),
            None,
            (io.BytesIO(), io.BytesIO()),
            service=healthy,
        )
        for _ in range(16)
    ]
    first = RetiringPredecessor(1 if race else 10000)
    second = RetiringPredecessor(3 if race else 10000)
    monkeypatch.setattr(p, "PENDING_OWNERS", [first, owners[0], second, *owners[1:]])
    reached = []

    def review(config):
        reached.append(True)
        raise p.ProviderError()

    monkeypatch.setattr(p, "verify_review", review)
    try:
        with pytest.raises(p.ProviderBusy):
            p.WindowsSocketProvider().run(
                config, request, service=authority, current=lambda: True
            )
        assert not reached
        assert sum(not owner.confirmed for owner in tuple(p.PENDING_OWNERS)) == 16
        assert first.removed is race
    finally:
        first.join()
        second.join()
        healthy.close()
        authority.close()


def test_registry_removal_is_confirmed_identity_only_and_idempotent(monkeypatch):
    original = p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()), confirmed=True)
    equal_but_distinct = replace(original)
    uncertain = replace(original, confirmed=False)
    assert original == equal_but_distinct and original is not equal_but_distinct
    monkeypatch.setattr(p, "PENDING_OWNERS", [])
    for owner in (equal_but_distinct, original, uncertain):
        p.register_pending_owner(owner)
    snapshot = p.pending_owner_snapshot()
    assert isinstance(snapshot, tuple) and len(snapshot) == 3
    assert p.remove_confirmed_owner(uncertain) is False
    assert p.remove_confirmed_owner(original) is True
    assert p.remove_confirmed_owner(original) is False
    assert [id(owner) for owner in p.pending_owner_snapshot()] == [
        id(equal_but_distinct),
        id(uncertain),
    ]
    assert len(snapshot) == 3  # The read snapshot never shifts under its reader.


@pytest.mark.parametrize("retirement", ["close", "reaper"])
def test_original_retirement_progresses_while_attempt_waits(monkeypatch, retirement):
    config, request, authority = live_wait_fixture(monkeypatch, deadline_left=2)
    owner = p.ChildOwner(None, None, (io.BytesIO(), io.BytesIO()))
    monkeypatch.setattr(p, "PENDING_OWNERS", [owner])
    reached, failures = [], []

    def review(config):
        reached.append(owner.confirmed)
        raise p.ProviderError()

    monkeypatch.setattr(p, "verify_review", review)
    original_finish = p.ChildOwner.finish

    def finish(self, *args, **kwargs):
        assert not p.PENDING_OWNERS_LOCK.locked()
        assert p.ATTEMPT_LOCK.locked()
        return original_finish(self, *args, **kwargs)

    monkeypatch.setattr(p.ChildOwner, "finish", finish)

    def attempt():
        try:
            p.WindowsSocketProvider().run(
                config, request, service=authority, current=lambda: True
            )
        except Exception as error:  # noqa: BLE001 -- report the test thread failure to its caller
            failures.append(type(error).__name__)

    caller = threading.Thread(target=attempt)
    retired = LiveParentAuthority(time.monotonic() + 3, threading.Event())
    try:
        caller.start()
        end = time.monotonic() + 1
        while not p.ATTEMPT_LOCK.locked():
            assert time.monotonic() < end
            time.sleep(0.001)
        if retirement == "reaper":
            retired.start_watchdog(owner.request_stop)
            retired.deny("closed")
            assert retired.wait_retirement(1)
        else:
            session = object.__new__(OwnedLocalLiveSession)
            session._owner = owner
            session._authority = retired
            session._lock = threading.RLock()
            assert session.close()
        caller.join(2)
        assert not caller.is_alive() and not failures and reached == [True]
        assert owner.confirmed and all(
            item is not owner for item in p.pending_owner_snapshot()
        )
    finally:
        owner.confirmed = True
        caller.join(3)
        retired.close()
        authority.close()
