"""Worker-only protected directory reads; API/RPC composition is separate."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from wso_contracts.tvt.directory import (
    ChannelDetailRequest,
    ChannelListRequest,
    DeviceDetailRequest,
    DeviceListRequest,
    DirectoryRequest,
    DirectoryView,
    ObservationField,
    ObservationName,
    ObservationObject,
    ObservationValue,
    ReceivedSharesRequest,
    SentSharesRequest,
    checked_request,
)
from wso_contracts.tvt.identity import AccountScope, TvtIdentityRef
from wso_core.tvt.account_client import _correlation
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.account_transport import OriginPolicy
from wso_core.tvt.directory_admission import DirectoryAdmission, DirectoryLease
from wso_core.tvt.directory_client import DirectoryClient
from wso_core.tvt.directory_projection import (
    ChannelDirectory,
    DevicePage,
    ObjectObservation,
    OpaqueObservation,
    SharePage,
)
from wso_core.tvt.ports import AccountClientError, AccountResult, PrivateToken
from wso_core.tvt.token_vault import remaining_budget, token_budget

from .session_service import AccountEndpoint, Budget


class DirectoryWorker(Protocol):
    def execute(
        self,
        method: str,
        ticket: str,
        body: DirectoryRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView: ...


def _object(value: ObjectObservation) -> ObservationObject:
    def projected(item: object) -> ObservationValue:
        if isinstance(item, ObjectObservation):
            return _object(item)
        if isinstance(item, tuple):
            return tuple(projected(child) for child in item)
        if isinstance(item, OpaqueObservation):
            return None
        if item is None or type(item) in (str, int, float, bool):
            return cast(ObservationValue, item)
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)

    return ObservationObject(
        fields=tuple(
            ObservationField(
                name=cast(ObservationName, key),
                state=observation.state.value,
                value=projected(observation.value),
                source_default=observation.source_default,
                opaque_kind=cast(
                    "None | Literal['object','array']",
                    observation.value.kind
                    if isinstance(observation.value, OpaqueObservation)
                    else None,
                ),
            )
            for key, observation in value.fields
        ),
        unknown_members=value.unknown_members,
    )


@dataclass(slots=True)
class _Reader:
    lease: DirectoryLease | None = field(default=None, repr=False)
    client: DirectoryClient | None = field(default=None, repr=False)
    done: threading.Event = field(default_factory=threading.Event)
    close_guard: threading.Lock = field(default_factory=threading.Lock)
    close_done: threading.Event = field(default_factory=threading.Event)
    close_started: bool = False
    failed: bool = False


class DirectoryWorkerExecutor:
    """No HTTP until exact SQL claim and vault snapshot transaction commit.

    Local policy: 32 concurrent readers, at most 4 per actor; SQL additionally
    limits pending tickets to128 total/4 per actor. Each client is owned once.
    """

    def __init__(
        self,
        admission: DirectoryAdmission,
        endpoints: tuple[AccountEndpoint, ...],
    ) -> None:
        valid = False
        try:
            valid = (
                type(endpoints) is tuple
                and 1 <= len(endpoints) <= 64
                and all(type(e) is AccountEndpoint for e in endpoints)
                and len({(e.region, e.brand) for e in endpoints}) == len(endpoints)
            )
            for endpoint in endpoints:
                OriginPolicy({endpoint.region: frozenset({endpoint.origin})})
        except Exception:  # noqa: BLE001 -- discard private configuration details
            valid = False
        if not valid:
            raise AccountFailure()
        self._admission = admission
        self._endpoints = MappingProxyType({(e.region, e.brand): e for e in endpoints})
        self._lock = threading.Lock()
        self._closed = False
        self._quarantined = False
        self._readers: dict[UUID, _Reader] = {}
        self._invalid: set[tuple[UUID, UUID, int]] = set()
        self._shutdown_end: float | None = None

    def _running(self) -> None:
        if self._closed or self._quarantined:
            raise AccountFailure(
                "ACCOUNT_QUARANTINED" if self._quarantined else "ACCOUNT_CANCELLED", 503
            )

    @staticmethod
    def _close_once(reader: _Reader) -> None:
        with reader.close_guard:
            if reader.close_started:
                return
            reader.close_started = True
        try:
            if reader.client is not None:
                reader.client.close()
        except BaseException:  # noqa: BLE001 -- retain custody without private errors
            reader.failed = True
        finally:
            reader.close_done.set()

    def close(self, *, deadline_ms: int = 1000) -> None:
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 5000:
            raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
        end = time.monotonic() + deadline_ms / 1000
        try:
            shared = remaining_budget()
        except AccountFailure:
            shared = 0
        if shared is not None:
            end = min(end, time.monotonic() + max(0, shared) / 1000)
        with self._lock:
            self._closed = True
            owner = self._shutdown_end is None
            if owner:
                self._shutdown_end = end
            end = min(end, cast(float, self._shutdown_end))
            readers = tuple(self._readers.values())
        if owner:
            for reader in readers:
                threading.Thread(
                    target=self._close_once, args=(reader,), daemon=True
                ).start()
        for reader in readers:
            settled = (
                reader.close_done.wait(max(0, end - time.monotonic()))
                and reader.done.wait(max(0, end - time.monotonic()))
                and not reader.failed
            )
            if not settled:
                reader.failed = True
                with self._lock:
                    self._quarantined = True
        if self._quarantined:
            raise AccountFailure("ACCOUNT_QUARANTINED", 503)

    def execute(
        self,
        method: str,
        ticket: str,
        body: DirectoryRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> DirectoryView:
        # Catch-and-recreate outside exception handlers; private causes never
        # become an RPC/log exception context.
        code, status = "ACCOUNT_UNAVAILABLE", 503
        try:
            if type(deadline_ms) is not int or not 1 <= deadline_ms <= 10000:
                raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
            _correlation(correlation_id)
            checked = checked_request(method, body)
            budget = Budget(deadline_ms)

            # Budget.remaining consults token_budget; do not bind that recursive
            # method as the context callback. Capture its original monotonic end.
            def remaining() -> int:
                value = int((budget._end - time.monotonic()) * 1000)
                if value < 1:
                    raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
                return value

            with token_budget(remaining):
                return self._execute(method, ticket, checked, budget, correlation_id)
        except AccountFailure as error:
            code, status = error.code, error.status
        except AccountClientError as error:
            code, status = error.code.value, 502
        except (ValueError, TypeError):
            code, status = "ACCOUNT_INPUT_INVALID", 422
        except Exception:  # noqa: BLE001 -- private provider/configuration causes stay private
            code, status = "ACCOUNT_UNAVAILABLE", 503
        raise AccountFailure(code, status) from None

    def _execute(
        self,
        method: str,
        ticket: str,
        body: DirectoryRequest,
        budget: Budget,
        correlation: str,
    ) -> DirectoryView:
        key = uuid4()
        reader = _Reader()
        with self._lock:
            self._running()
            if len(self._readers) >= 32:
                raise AccountFailure("ACCOUNT_UNAVAILABLE", 503)
            self._readers[key] = reader
        lease: DirectoryLease | None = None
        token: PrivateToken | None = None
        completed = False
        try:
            lease = self._admission.redeem(ticket, method, body)
            endpoint = self._endpoints.get((lease.region, lease.brand))
            if endpoint is None:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            identity = TvtIdentityRef(
                tenant_id=lease.tenant_id,
                actor_user_id=lease.actor_id,
                identity_id=lease.identity_id,
            )
            with self._lock:
                self._running()
                reader.lease = lease
                if (
                    lease.tenant_id,
                    lease.identity_id,
                    lease.generation,
                ) in self._invalid:
                    raise AccountFailure("DIRECTORY_REAUTHENTICATION_REQUIRED", 401)
                if (
                    sum(
                        r.lease is not None
                        and r.lease.actor_id == lease.actor_id
                        and r.lease.tenant_id == lease.tenant_id
                        for r in self._readers.values()
                    )
                    > 4
                ):
                    raise AccountFailure("ACCOUNT_UNAVAILABLE", 503)
                # Pure construction under the registry lock prevents a close
                # from settling an empty placeholder before it gains a client.
                client = DirectoryClient(
                    AccountScope(
                        **identity.model_dump(), region=lease.region, brand=lease.brand
                    ),
                    OriginPolicy({lease.region: frozenset({endpoint.origin})}),
                    origin=endpoint.origin,
                    identity=identity,
                )
                reader.client = client
            self._admission.claim(lease)
            # Admission's NullPool transaction reuses the managed account SQL
            # and SecretCipher, then commits before this private snapshot exits.
            token = self._admission.snapshot(lease)
            self._admission.check(lease)
            budget.remaining()
            with self._lock:
                self._running()
            result: (
                AccountResult[DevicePage]
                | AccountResult[ChannelDirectory]
                | AccountResult[ObjectObservation]
                | AccountResult[SharePage]
            )
            if isinstance(body, DeviceListRequest):
                result = client.device_list(
                    identity,
                    token,
                    body.page_num,
                    body.page_size,
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            elif isinstance(body, ChannelListRequest):
                result = client.channel_list(
                    identity,
                    token,
                    list(body.sn_list),
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            elif isinstance(body, DeviceDetailRequest):
                result = client.device_detail(
                    identity,
                    token,
                    body.sn,
                    body.return_chl,
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            elif isinstance(body, ChannelDetailRequest):
                result = client.channel_detail(
                    identity,
                    token,
                    body.sn,
                    body.chl_index,
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            elif isinstance(body, SentSharesRequest):
                result = client.sent_shares(
                    identity,
                    token,
                    body.page_num,
                    body.page_size,
                    list(body.resource_types),
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            elif isinstance(body, ReceivedSharesRequest):
                result = client.received_shares(
                    identity,
                    token,
                    body.page_num,
                    body.page_size,
                    list(body.resource_types),
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation,
                )
            else:
                raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
            token = None
            if not result.ok:
                if result.native_msgcode in {
                    7000,
                    7003,
                    10002,
                    11101,
                    7004,
                    7009,
                    7088,
                    7089,
                    7090,
                }:
                    with self._lock:
                        self._invalid.add(
                            (lease.tenant_id, lease.identity_id, lease.generation)
                        )
                    raise AccountFailure("DIRECTORY_REAUTHENTICATION_REQUIRED", 401)
                raise AccountFailure(
                    result.error_code.value
                    if result.error_code
                    else "ACCOUNT_UPSTREAM_REJECTED",
                    502,
                )
            observed = result.value
            if isinstance(observed, (DevicePage, SharePage)):
                records, total = observed.records, observed.total
            elif isinstance(observed, ChannelDirectory):
                records, total = observed.devices, None
            elif isinstance(observed, ObjectObservation):
                records, total = (observed,), None
            else:
                raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
            view = DirectoryView(
                identity_id=lease.identity_id,
                region=lease.region,
                brand=lease.brand,
                method=body.method,
                generation=lease.generation,
                request_id=correlation,
                records=tuple(_object(item) for item in records),
                total=total,
            )
            budget.remaining()
            self._admission.publish(lease)
            budget.remaining()
            with self._lock:
                self._running()
            completed = True
        except AccountClientError as error:
            if error.code.value == "ACCOUNT_QUARANTINED":
                reader.failed = True
            raise
        finally:
            token = None
            disposed = lease is None
            try:
                if lease is not None:
                    self._admission.dispose(lease)
                    disposed = True
            except AccountFailure:
                pass
            self._close_once(reader)
            with self._lock:
                reader.failed = reader.failed or not disposed
                if reader.failed or not reader.close_done.is_set():
                    self._quarantined = True
                    self._readers[key] = reader
                else:
                    self._readers.pop(key, None)
                # Signal settlement even when the terminal decision rejects the
                # view. Close cannot win this same lock between custody release
                # and the success decision; no blocking cleanup follows it.
                reader.done.set()
                if completed:
                    self._running()
                    budget.remaining()
        return view
