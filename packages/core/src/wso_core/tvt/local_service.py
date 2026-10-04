"""Bounded local verification port. Inventory facts never grant live authority."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol

from wso_contracts.tvt.local_device import LocalDeviceView

from .local_credentials import LocalDeviceCredentials

LOCAL_DEVICE_FAILURES = {
    "LOCAL_DEVICE_INPUT_INVALID": 422,
    "LOCAL_DEVICE_DENIED": 404,
    "LOCAL_DEVICE_GENERATION_CONFLICT": 409,
    "LOCAL_DEVICE_BUSY": 429,
    "LOCAL_DEVICE_CANCELLED": 409,
    "LOCAL_DEVICE_PROTOCOL_INVALID": 502,
    "LOCAL_DEVICE_UPSTREAM_REJECTED": 502,
    "LOCAL_DEVICE_UNAVAILABLE": 503,
    "LOCAL_DEVICE_DEADLINE_EXCEEDED": 504,
}


class LocalDeviceFailure(Exception):
    def __init__(
        self, code: str = "LOCAL_DEVICE_UNAVAILABLE", status: int = 503
    ) -> None:
        if LOCAL_DEVICE_FAILURES.get(code) != status:
            code, status = "LOCAL_DEVICE_UNAVAILABLE", 503
        self.code, self.status = code, status
        super().__init__("Local device request failed")


class LocalVerifyBudget:
    def __init__(
        self,
        deadline_ms: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        cancel: Event | None = None,
    ) -> None:
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 20000:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        self._clock = clock
        self.cancel = cancel if cancel is not None else Event()
        self.deadline_monotonic = clock() + deadline_ms / 1000

    def remaining_ms(self) -> int:
        if self.cancel.is_set():
            raise LocalDeviceFailure("LOCAL_DEVICE_CANCELLED", 409)
        left = int((self.deadline_monotonic - self._clock()) * 1000)
        if left < 1:
            raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
        return left


@dataclass(frozen=True, slots=True, repr=False)
class LocalInventoryChannel:
    guid: bytes
    raw_index: int
    window_index: int
    ordinal: int
    kind: Literal["analog", "digital", "recorder"]

    def __repr__(self) -> str:
        return "<LocalInventoryChannel: private>"

    def __post_init__(self) -> None:
        if (
            type(self.guid) is not bytes
            or len(self.guid) != 16
            or self.guid == bytes(16)
            or type(self.raw_index) is not int
            or not -128 <= self.raw_index <= 65535
            or type(self.window_index) is not int
            or not -128 <= self.window_index <= 65535
            or type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 256
            or self.kind not in {"analog", "digital", "recorder"}
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)


@dataclass(frozen=True, slots=True, repr=False)
class LocalInventoryObservation:
    login_accepted: bool
    same_original_session: bool
    serial_matched: bool
    channels_complete: bool
    cleanup_confirmed: bool
    channels: tuple[LocalInventoryChannel, ...]
    group_provenance: Literal["unavailable", "missing", "empty", "value"] = (
        "unavailable"
    )
    metadata_branch_complete: bool = False
    permissions_complete: bool = False
    proof_verified: bool = False

    def __repr__(self) -> str:
        return "<LocalInventoryObservation: private>"

    def validate(self) -> None:
        flags = (
            self.login_accepted,
            self.same_original_session,
            self.serial_matched,
            self.channels_complete,
            self.cleanup_confirmed,
            self.metadata_branch_complete,
            self.permissions_complete,
            self.proof_verified,
        )
        if (
            any(type(v) is not bool for v in flags)
            or not all(flags[:5])
            or type(self.channels) is not tuple
            or len(self.channels) > 256
            or any(type(c) is not LocalInventoryChannel for c in self.channels)
            or len({c.guid for c in self.channels}) != len(self.channels)
            or len({c.ordinal for c in self.channels}) != len(self.channels)
            or self.group_provenance not in {"unavailable", "missing", "empty", "value"}
            or (self.group_provenance != "value" and self.permissions_complete)
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)


class LocalInventoryProvider(Protocol):
    """Trusted provider must discard credentials and settle its original owner.

    Check current/cancel/deadline after preparation before every native Send.
    Return actual same-session facts, never inferred SafeResult counts.
    """

    def verify(
        self,
        credentials: LocalDeviceCredentials,
        *,
        deadline_monotonic: float,
        current: Callable[[], bool],
        cancel: Event,
    ) -> LocalInventoryObservation: ...


class LocalAdmissionPort(Protocol):
    def redeem(self, ticket: str, *, budget: LocalVerifyBudget) -> object: ...
    def run(
        self,
        lease: object,
        callback: Callable[
            [LocalDeviceCredentials, Callable[[], bool]], LocalInventoryObservation
        ],
        *,
        budget: LocalVerifyBudget,
    ) -> LocalDeviceView: ...
    def close(self, lease: object, *, budget: LocalVerifyBudget) -> None: ...


class LocalVerificationExecutor:
    def __init__(
        self,
        admission: LocalAdmissionPort,
        provider: LocalInventoryProvider | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.admission, self.provider, self._clock = admission, provider, clock

    def verify(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalDeviceView:
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        if (
            type(ticket) is not str
            or re.fullmatch(r"[0-9a-f]{64}", ticket) is None
            or type(correlation_id) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", correlation_id) is None
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        budget.remaining_ms()
        if self.provider is None:
            raise LocalDeviceFailure()
        lease = None
        failure = None
        result = None
        try:
            lease = self.admission.redeem(ticket, budget=budget)

            def callback(
                credentials: LocalDeviceCredentials, current: Callable[[], bool]
            ) -> LocalInventoryObservation:
                def allowed() -> bool:
                    budget.remaining_ms()
                    return current()

                if not allowed():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                assert self.provider is not None
                observation = self.provider.verify(
                    credentials,
                    deadline_monotonic=budget.deadline_monotonic,
                    current=allowed,
                    cancel=budget.cancel,
                )
                if not allowed():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                if type(observation) is not LocalInventoryObservation:
                    raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
                observation.validate()
                return observation

            view = self.admission.run(lease, callback, budget=budget)
            budget.remaining_ms()
            if type(view) is not LocalDeviceView:
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
            result = view.model_copy(update={"request_id": correlation_id})
        except LocalDeviceFailure as exc:
            failure = (exc.code, exc.status)
        except Exception:  # noqa: BLE001 -- redact arbitrary trusted-provider failures.
            failure = ("LOCAL_DEVICE_UNAVAILABLE", 503)
        finally:
            if lease is not None:
                try:
                    self.admission.close(lease, budget=budget)
                except Exception:  # noqa: BLE001 -- failed cleanup cannot return success.
                    failure = ("LOCAL_DEVICE_UNAVAILABLE", 503)
        if failure is None and result is not None:
            budget.remaining_ms()
            return result
        assert failure is not None
        raise LocalDeviceFailure(*failure) from None
