"""Retire a worker epoch without disposing resources still used by a call."""

from collections.abc import Callable
from threading import Lock

from .callback_registry import CallbackRegistry, CallSlot


class SessionPool:
    def __init__(self, *, capacity: int, dispose: Callable[[], None]) -> None:
        self.registry = CallbackRegistry(capacity=capacity)
        self._dispose = dispose
        self._lock = Lock()
        self._closing = False
        self._disposed = False

    def _dispose_if_idle(self) -> None:
        with self._lock:
            ready = (
                self._closing and not self._disposed and self.registry.active_count == 0
            )
            if ready:
                self._disposed = True
        if ready:
            self._dispose()

    def settle(self, slot: CallSlot) -> bool:
        deliver = self.registry.settle(slot)
        self._dispose_if_idle()
        return deliver

    def close(self, grace: float = 1.0) -> bool:
        # Close admission before marking closing to exclude resource-disposal races.
        self.registry.close()
        with self._lock:
            self._closing = True
        self.registry.drained.wait(max(0.0, min(grace, 5.0)))
        self._dispose_if_idle()
        return self.registry.active_count == 0
