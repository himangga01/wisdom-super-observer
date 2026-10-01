"""Bounded call ownership; cancellation suppresses delivery, not execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock
from uuid import UUID, uuid4

from .selected import failure


@dataclass(slots=True, repr=False)
class CallSlot:
    epoch: UUID
    correlation: str
    abandoned: bool = False
    settled: bool = False
    cancel: Callable[[], object] | None = field(default=None, repr=False)


class CallbackRegistry:
    def __init__(self, *, capacity: int = 32, history_limit: int = 65536) -> None:
        if not 1 <= capacity <= 256 or not capacity <= history_limit <= 65536:
            raise failure("ACCOUNT_INPUT_INVALID")
        self._capacity, self._limit = capacity, history_limit
        self._epoch = uuid4()
        self._lock = Lock()
        self._slots: dict[str, CallSlot] = {}
        self._active = 0
        self._closed = False
        self.drained = Event()
        self.drained.set()

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    def admit(self, correlation: str) -> CallSlot:
        with self._lock:
            if self._closed:
                raise failure("ACCOUNT_UNAVAILABLE")
            if correlation in self._slots:
                raise failure("ACCOUNT_INPUT_INVALID")
            if self._active >= self._capacity or len(self._slots) >= self._limit:
                raise failure("SESSION_BUSY")
            slot = CallSlot(self._epoch, correlation)
            self._slots[correlation] = slot
            self._active += 1
            self.drained.clear()
            return slot

    def _owns(self, slot: CallSlot) -> bool:
        return slot.epoch == self._epoch and self._slots.get(slot.correlation) is slot

    def attach_cancel(self, slot: CallSlot, cancel: Callable[[], object]) -> None:
        with self._lock:
            invoke = not self._owns(slot) or slot.abandoned or self._closed
            if not invoke and not slot.settled:
                slot.cancel = cancel
        if invoke:
            cancel()

    def abandon(self, slot: CallSlot) -> None:
        with self._lock:
            if not self._owns(slot) or slot.settled:
                return
            slot.abandoned = True
            cancel, slot.cancel = slot.cancel, None
        if cancel is not None:
            cancel()

    def settle(self, slot: CallSlot) -> bool:
        with self._lock:
            if not self._owns(slot) or slot.settled:
                return False
            slot.settled = True
            slot.cancel = None
            self._active -= 1
            if not self._active:
                self.drained.set()
            return not self._closed and not slot.abandoned

    def close(self) -> None:
        with self._lock:
            self._closed = True
            slots = tuple(slot for slot in self._slots.values() if not slot.settled)
        for slot in slots:
            self.abandon(slot)
