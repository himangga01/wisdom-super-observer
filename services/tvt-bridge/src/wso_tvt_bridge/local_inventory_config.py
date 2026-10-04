"""Trusted worker deployment configuration; never a public request setting."""

from __future__ import annotations

import os
from pathlib import Path

from wso_core.tvt.local_service import LocalInventoryProvider

PREFIX = "WSO_TVT_WINDOWS_LOCAL_INVENTORY_"
ENV_KEYS = tuple(
    PREFIX + key
    for key in ("ENABLED", "BUNDLE", "STAGING", "SOURCE_REVIEW", "RUNTIME_REVIEW")
)


def load_local_inventory_provider() -> LocalInventoryProvider | None:
    if os.name != "nt" or os.environ.get(PREFIX + "ENABLED") != "1":
        return None
    values = [
        os.environ.get(PREFIX + key, "")
        for key in ("BUNDLE", "STAGING", "SOURCE_REVIEW", "RUNTIME_REVIEW")
    ]
    if not all(values):
        return None
    from .local_inventory_provider import NativeLocalInventoryProvider
    from .windows_socket import ProviderConfig, ProviderError

    try:
        return NativeLocalInventoryProvider(
            ProviderConfig(
                Path(values[0]), Path(values[1]), Path(values[2]), 20, Path(values[3])
            )
        )
    except (ProviderError, OSError, ValueError):
        return None
