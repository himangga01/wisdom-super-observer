"""Parent pressure keeps the original unread IPC message and authority."""

import pytest

from tests.contract.test_local_live_provider import (
    first_frame_parent,
    first_keyframe_wire,
    module,
)


def ready_parent(monkeypatch):
    parent, now = first_frame_parent(monkeypatch)
    parent.worker_connection.recv_bytes()  # Open acknowledgement's decision.
    parent.worker_connection.send_bytes(first_keyframe_wire(parent))
    assert parent.pump(lambda: True)
    parent.worker_connection.recv_bytes()
    assert len(parent.frames) == 1
    return parent, now


@pytest.mark.parametrize("kind", ["control", "malformed", "setup"])
def test_parent_holds_exact_message_until_consumer_credit(monkeypatch, kind):
    ipc = module("local_live_ipc")
    parent, _now = ready_parent(monkeypatch)
    try:
        sequence = parent._live_sequence
        message = {
            "type": "current",
            "purpose": "send",
            "generation": parent.generation,
            "sequence": sequence,
        }
        if kind == "malformed":
            message["sequence"] += 1
        elif kind == "setup":
            message = {
                "type": "setup",
                "data": {},
                "generation": parent.generation,
                "sequence": sequence,
            }
        parent.worker_connection.send_bytes(b"J" + ipc.encode(message))
        for _ in range(3):
            assert parent.pump(lambda: True)
            assert parent._live_sequence == sequence
            assert not parent.worker_connection.poll(0)
        # The original consumer releases exact ownership/accounting of the frame.
        original = parent.frames.popleft()
        parent.queued_bytes -= ipc.frame_storage(original)
        assert parent.pump(lambda: True) is (kind == "control")
        if kind == "control":
            answer = ipc.decode(parent.worker_connection.recv_bytes())
            assert answer["sequence"] == sequence and answer["allow"] is True
            assert parent._live_sequence == sequence + 1
        else:
            assert parent.failure == "protocol"
            assert not parent.worker_connection.poll(0)
    finally:
        parent.close()


@pytest.mark.parametrize("reason", ["denied", "cancelled", "deadline", "closed"])
def test_credit_pause_never_bypasses_current_cancel_expiry_or_close(
    monkeypatch, reason
):
    parent, now = ready_parent(monkeypatch)
    try:
        if reason == "cancelled":
            parent.cancel.set()
        elif reason == "deadline":
            now[0] = parent.deadline
        elif reason == "closed":
            parent.deny("closed")
        assert not parent.pump(lambda: reason != "denied")
        assert (
            parent.failure == reason and not parent.frames and parent.queued_bytes == 0
        )
    finally:
        parent.close()


def test_credit_pause_rechecks_truth_after_current_callback(monkeypatch):
    parent, now = ready_parent(monkeypatch)
    try:

        def changes_expiry():
            now[0] = parent.deadline
            return True

        assert not parent.pump(changes_expiry)
        assert parent.failure == "deadline"
    finally:
        parent.close()


def test_credit_pause_cannot_accept_truth_from_a_callback_that_closed_owner(
    monkeypatch,
):
    parent, _now = ready_parent(monkeypatch)
    try:

        def closes_owner():
            parent.deny("closed")
            return True

        assert not parent.pump(closes_owner)
        assert parent.failure == "closed" and not parent.frames
    finally:
        parent.close()
