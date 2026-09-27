from __future__ import annotations

from typing import Protocol


class ReadinessCheck(Protocol):
    """Injected local dependency check; external service ports arrive with their models."""

    def __call__(self) -> bool: ...
