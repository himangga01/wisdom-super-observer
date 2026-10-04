"""API port only. Worker construction belongs exclusively to bridge bootstrap."""

from threading import Event
from typing import Protocol

from wso_contracts.tvt.local_device import LocalDeviceView


class LocalDeviceWorker(Protocol):
    def verify(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalDeviceView: ...
