"""Worker-only service port; no credential or native owner survives success."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any, Literal, cast

from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_service import (
    LocalDeviceFailure,
    LocalInventoryChannel,
    LocalInventoryObservation,
)

from .local_inventory_ipc import ParentAuthority, decode
from .windows_socket import (
    PENDING_OWNERS,
    ProviderBusy,
    ProviderConfig,
    WindowsSocketProvider,
)


def observation(raw: bytes, *, cleanup_confirmed: bool) -> LocalInventoryObservation:
    data = decode(raw)
    if set(data) != {
        "login_accepted",
        "same_original_session",
        "serial_matched",
        "channels_complete",
        "channels",
        "group_provenance",
        "metadata_branch_complete",
        "permissions_complete",
        "proof_verified",
    }:
        raise ValueError("Invalid private observation")
    if type(data["channels"]) is not list or len(data["channels"]) > 256:
        raise ValueError("Invalid private observation")
    channels: list[LocalInventoryChannel] = []
    for row in data["channels"]:
        if type(row) is not dict or set(row) != {
            "guid",
            "raw_index",
            "window_index",
            "ordinal",
            "kind",
        }:
            raise ValueError("Invalid private observation")
        if type(row["guid"]) is not str or len(row["guid"]) != 32:
            raise ValueError("Invalid private observation")
        guid = bytes.fromhex(row["guid"])
        if guid.hex() != row["guid"]:
            raise ValueError("Invalid private observation")
        channels.append(
            LocalInventoryChannel(
                guid, row["raw_index"], row["window_index"], row["ordinal"], row["kind"]
            )
        )
    result = LocalInventoryObservation(
        data["login_accepted"],
        data["same_original_session"],
        data["serial_matched"],
        data["channels_complete"],
        cleanup_confirmed,
        tuple(channels),
        cast(
            Literal["unavailable", "missing", "empty", "value"],
            data["group_provenance"],
        ),
        data["metadata_branch_complete"],
        data["permissions_complete"],
        data["proof_verified"],
    )
    result.validate()
    if not result.metadata_branch_complete or result.group_provenance == "unavailable":
        raise ValueError("Incomplete private observation")
    return result


_FAILURES = {
    "cancelled": ("LOCAL_DEVICE_CANCELLED", 409),
    "deadline": ("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504),
    "denied": ("LOCAL_DEVICE_DENIED", 404),
    "protocol": ("LOCAL_DEVICE_PROTOCOL_INVALID", 502),
    "rejected": ("LOCAL_DEVICE_UPSTREAM_REJECTED", 502),
    "codec": ("LOCAL_DEVICE_PROTOCOL_INVALID", 502),
    "unsupported": ("LOCAL_DEVICE_PROTOCOL_INVALID", 502),
}


class NativeLocalInventoryProvider:
    __slots__ = ("_config",)

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def verify(
        self,
        credentials: LocalDeviceCredentials,
        *,
        deadline_monotonic: float,
        current: Callable[[], bool],
        cancel: threading.Event,
    ) -> LocalInventoryObservation:
        from .windows_socket import PrivateRequest

        failure: tuple[str, int] = ("LOCAL_DEVICE_UNAVAILABLE", 503)
        result: LocalInventoryObservation | None = None
        native: WindowsSocketProvider | None = None
        service: ParentAuthority | None = None
        request: Any = None
        try:
            if (
                type(credentials) is not LocalDeviceCredentials
                or not callable(current)
                or type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic > time.monotonic() + 20
            ):
                failure = ("LOCAL_DEVICE_INPUT_INVALID", 422)
            else:
                service = ParentAuthority(deadline_monotonic, cancel)
                if service.check(current):
                    request = PrivateRequest(
                        "inventory",
                        credentials.country,
                        credentials.serial,
                        credentials.username,
                        credentials.password,
                        metadata_read_opt_in=True,
                    )
                    native = WindowsSocketProvider()
                    safe = native.run(
                        self._config, request, service=service, current=current
                    )
                    if service.failure:
                        failure = _FAILURES.get(service.failure, failure)
                    elif not safe.reaped or safe.failure != "none":
                        failure = _FAILURES.get(safe.failure, failure)
                    elif service.observation is None:
                        failure = ("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
                    else:
                        result = observation(
                            service.observation, cleanup_confirmed=safe.reaped
                        )
                        if (
                            len(result.channels) != safe.channel_count
                            or result.metadata_branch_complete
                            != safe.metadata_branch_complete
                            or result.permissions_complete != safe.permissions_complete
                            or result.proof_verified != safe.proof_verified
                        ):
                            result = None
                            failure = ("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
                else:
                    failure = _FAILURES.get(service.failure, failure)
        except ProviderBusy:
            result = None
            failure = ("LOCAL_DEVICE_BUSY", 429)
        except LocalDeviceFailure as error:
            result = None
            failure = (error.code, error.status)
        except Exception:  # noqa: BLE001 -- fixed private service boundary
            result = None
            failure = ("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        finally:
            if service is not None:
                service.observation = None
                if native is None or native.owner is None:
                    service.close()
            if (
                native is not None
                and native.owner is not None
                and native.owner.confirmed
            ):
                owner = native.owner
                if owner in PENDING_OWNERS:
                    PENDING_OWNERS.remove(owner)
                native.owner = None
            request = None
            del credentials
        if result is not None and service is not None and not service.check(current):
            result = None
            failure = _FAILURES.get(service.failure, failure)
        del current
        if result is not None:
            return result
        raise LocalDeviceFailure(*failure) from None
