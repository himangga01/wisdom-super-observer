"""Protected W06 worker composition. RPC/API factories remain separate."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from wso_contracts.tvt.account_flows import (
    AccountDynamicCodeRequest,
    AccountFlowCancel,
    AccountFlowImage,
    AccountFlowReference,
    AccountFlowStart,
    AccountFlowView,
    AccountRecoverySubmit,
    AccountRegistrationSubmit,
)
from wso_contracts.tvt.identity import AccountScope
from wso_core.tvt.account_client import _correlation
from wso_core.tvt.account_flows import (
    AccountBinding,
    AccountMode,
    FlowError,
    FlowPurpose,
    FlowResult,
    PreloginAccountFlow,
)
from wso_core.tvt.account_projection import AccountFailure, project_image
from wso_core.tvt.account_transport import OriginPolicy
from wso_core.tvt.flow_admission import FlowAdmission, FlowLease
from wso_core.tvt.ports import AccountClientError
from wso_core.tvt.token_vault import remaining_budget

from .session_service import AccountEndpoint, Budget, worker_budget

type Body = AccountFlowStart | AccountFlowReference
TERMINAL = frozenset({"COMPLETE", "FAILED", "UNKNOWN_OUTCOME", "CLOSED", "EXPIRED"})


class AccountFlowWorker(Protocol):
    def start(
        self,
        ticket: str,
        body: AccountFlowStart,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def state(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def existence(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def image(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def issue_code(
        self,
        ticket: str,
        body: AccountDynamicCodeRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def register(
        self,
        ticket: str,
        body: AccountRegistrationSubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def recover(
        self,
        ticket: str,
        body: AccountRecoverySubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...
    def cancel(
        self,
        ticket: str,
        body: AccountFlowCancel,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView: ...


@dataclass(frozen=True, slots=True, repr=False)
class FlowEndpointConfig:
    """Explicit unhashed APK default_domain; customer_mark is unrelated."""

    default_domain: str
    terminal_id: str = ""


@dataclass(slots=True, repr=False)
class _Slot:
    lease: FlowLease
    flow: PreloginAccountFlow
    scope: AccountScope
    intent: str
    view: AccountFlowView
    expiry: float
    lock: Any = field(default_factory=threading.Lock)
    image_generation: int = 0
    close_guard: Any = field(default_factory=threading.Lock)
    close_done: Any = field(default_factory=threading.Event)
    close_started: bool = False
    close_failed: bool = False
    native_quarantined: bool = False


class AccountFlowWorkerExecutor:
    def __init__(
        self,
        admission: FlowAdmission | None,
        endpoints: tuple[AccountEndpoint, ...],
        flow_config: Mapping[tuple[str, str], FlowEndpointConfig] | None,
        binding_key: bytes | None,
    ) -> None:
        good = (
            admission is not None
            and bool(endpoints)
            and flow_config is not None
            and type(binding_key) is bytes
            and len(binding_key) == 32
        )
        if good:
            try:
                assert flow_config is not None
                selections = {(e.region, e.brand) for e in endpoints}
                good = len(selections) == len(endpoints) and selections == set(
                    flow_config
                )
                for endpoint in endpoints:
                    OriginPolicy({endpoint.region: frozenset({endpoint.origin})})
                    config = flow_config[(endpoint.region, endpoint.brand)]
                    good = good and type(config) is FlowEndpointConfig
                    for value in (
                        config.default_domain,
                        config.terminal_id,
                        endpoint.language,
                        endpoint.country,
                        endpoint.customer_app_id,
                    ):
                        good = (
                            good
                            and type(value) is str
                            and len(value.encode("utf-8")) <= 4096
                            and not any(
                                ord(c) == 0
                                or ord(c) > 0xFFFF
                                or 0xD800 <= ord(c) <= 0xDFFF
                                for c in value
                            )
                        )
            except Exception:  # noqa: BLE001 -- discard private configuration context
                good = False
        if not good:
            raise AccountFailure() from None
        self._admission = cast(FlowAdmission, admission)
        self._endpoints = {(e.region, e.brand): e for e in endpoints}
        self._config = dict(
            cast(Mapping[tuple[str, str], FlowEndpointConfig], flow_config)
        )
        self._binding_key = cast(bytes, binding_key)
        self._key_commitment = hashlib.sha256(self._binding_key).hexdigest()
        self._registry: dict[UUID, _Slot] = {}
        self._registry_lock = threading.Lock()
        self._closed = threading.Event()
        self._quarantined = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_end = 0.0
        self._shutdown_done = threading.Event()
        self._shutdown_pending: dict[UUID, _Slot] = {}
        self._quarantine: dict[UUID, _Slot] = {}

    def _running(self) -> None:
        if self._closed.is_set():
            raise AccountFailure(
                "ACCOUNT_QUARANTINED"
                if self._quarantined.is_set()
                else "ACCOUNT_CANCELLED",
                503,
            )

    @staticmethod
    def _close_once(slot: _Slot) -> None:
        with slot.close_guard:
            if slot.close_started:
                return
            slot.close_started = True
        try:
            slot.flow.close()
        except BaseException:  # noqa: BLE001 -- never retain private close exceptions
            slot.close_failed = True
        finally:
            slot.close_done.set()

    def _shutdown_slot(self, flow_id: UUID, slot: _Slot) -> None:
        self._close_once(slot)
        finished = slot.close_done.wait(max(0.0, self._shutdown_end - time.monotonic()))
        settled = finished and not slot.close_failed and not slot.native_quarantined
        if settled:
            settled = slot.lock.acquire(
                timeout=max(0.0, self._shutdown_end - time.monotonic())
            )
            if settled:
                slot.lock.release()
        with self._shutdown_lock:
            if settled:
                self._shutdown_pending.pop(flow_id, None)
                self._quarantine.pop(flow_id, None)
            else:
                self._quarantined.set()
            if not self._shutdown_pending:
                self._shutdown_done.set()

    def close(self, *, deadline_ms: int = 1000) -> None:
        """Stop admission once; bounded aggregate cleanup, explicit quarantine.

        Native close signals cancellation; the active adapter retains its own
        original settlement budget. At most128 daemon cancellation tasks avoid
        serial native waits. Unproved resources stay owned, and repeated close
        never starts new tasks or refreshes the original shutdown deadline.
        FlowAdmission disposal remains owned by the outer worker factory.
        """
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 5000:
            raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
        self._closed.set()
        self._binding_key = b""
        self._key_commitment = ""
        self._config.clear()
        self._endpoints.clear()
        end = time.monotonic() + deadline_ms / 1000
        shared = 0
        try:
            shared_value = remaining_budget()
            shared = deadline_ms if shared_value is None else shared_value
        except AccountFailure:
            pass
        end = min(end, time.monotonic() + max(0, shared) / 1000)
        if not self._shutdown_lock.acquire(timeout=max(0.0, end - time.monotonic())):
            self._quarantined.set()
            raise AccountFailure("ACCOUNT_QUARANTINED", 503)
        try:
            owner = not self._shutdown_started
            if owner:
                self._shutdown_started = True
                self._shutdown_end = end
            end = min(end, self._shutdown_end)
        finally:
            self._shutdown_lock.release()
        if owner:
            if not self._registry_lock.acquire(
                timeout=max(0.0, end - time.monotonic())
            ):
                self._quarantined.set()
                raise AccountFailure("ACCOUNT_QUARANTINED", 503)
            try:
                slots = dict(self._quarantine) | self._registry
                self._shutdown_pending.update(slots)
                self._registry.clear()
            finally:
                self._registry_lock.release()
            if not slots:
                self._shutdown_done.set()
            for flow_id, slot in slots.items():
                if time.monotonic() >= end:
                    break
                try:
                    threading.Thread(
                        target=self._shutdown_slot,
                        args=(flow_id, slot),
                        name="account-flow-shutdown",
                        daemon=True,
                    ).start()
                except (RuntimeError, OSError):
                    self._quarantined.set()
                    break
        finished = self._shutdown_done.wait(max(0.0, end - time.monotonic()))
        if not finished or self._quarantined.is_set():
            self._quarantined.set()
            raise AccountFailure("ACCOUNT_QUARANTINED", 503)

    @staticmethod
    def _view(
        lease: FlowLease, request_id: str, state: str, **extra: Any
    ) -> AccountFlowView:
        seconds = min(300, int((lease.expires_at - datetime.now(UTC)).total_seconds()))
        return AccountFlowView.model_validate(
            {
                "region": lease.region,
                "brand": lease.brand,
                "purpose": lease.purpose,
                "flow_id": lease.flow_id,
                "request_id": request_id,
                "state": state,
                "return_to_login": state == "COMPLETE",
                "expires_in_seconds": seconds
                if seconds > 0 and state not in TERMINAL
                else None,
            }
            | extra
        )

    def _drop(self, flow_id: UUID, slot: _Slot) -> None:
        self._close_once(slot)
        with self._registry_lock:
            if self._registry.get(flow_id) is slot:
                del self._registry[flow_id]
            if slot.close_failed or slot.native_quarantined:
                self._quarantine[flow_id] = slot
                self._quarantined.set()

    def _new(self, lease: FlowLease, body: AccountFlowStart, correlation: str) -> _Slot:
        self._running()
        if self._quarantined.is_set():
            raise AccountFailure("ACCOUNT_QUARANTINED", 503)
        selection = (lease.region, lease.brand)
        endpoint, config = self._endpoints.get(selection), self._config.get(selection)
        if endpoint is None or config is None:
            raise AccountFailure()
        binding = (
            AccountBinding.phone(
                cast(str, body.country_code), body.account.get_secret_value()
            )
            if body.mode == "phone"
            else AccountBinding(AccountMode.EMAIL, body.account.get_secret_value())
        )
        canonical = (
            binding.account.casefold() if body.mode == "email" else binding.account
        )
        intent = hmac.new(
            self._binding_key,
            json.dumps(
                [
                    "wso-tvt-flow-intent-v1",
                    str(lease.tenant_id),
                    lease.purpose,
                    int(binding.mode),
                    canonical,
                ],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        scope = AccountScope(
            tenant_id=lease.tenant_id,
            actor_user_id=lease.actor_id,
            region=lease.region,
            brand=lease.brand,
        )
        lifetime = min(300.0, (lease.expires_at - datetime.now(UTC)).total_seconds())
        if lifetime <= 0:
            raise AccountFailure("FLOW_EXPIRED", 409)
        with self._registry_lock:
            self._running()
            if self._quarantined.is_set():
                raise AccountFailure("ACCOUNT_QUARANTINED", 503)
            # Only settled, unlocked expired slots may be discarded. Final
            # witnesses live independently in PostgreSQL and are never removed.
            for flow_id, old in list(self._registry.items()):
                if time.monotonic() >= old.expiry and old.lock.acquire(blocking=False):
                    try:
                        self._close_once(old)
                        if old.close_failed or old.native_quarantined:
                            self._quarantine[flow_id] = old
                            self._quarantined.set()
                            raise AccountFailure("ACCOUNT_QUARANTINED", 503)
                        del self._registry[flow_id]
                    finally:
                        old.lock.release()
            if (
                len(self._registry) >= 128
                or sum(
                    s.lease.tenant_id == lease.tenant_id
                    and s.lease.actor_id == lease.actor_id
                    for s in self._registry.values()
                )
                >= 4
                or lease.flow_id in self._registry
            ):
                raise AccountFailure()
            flow = PreloginAccountFlow(
                scope,
                binding,
                FlowPurpose.REGISTER
                if body.purpose == "register"
                else FlowPurpose.RECOVER,
                OriginPolicy({lease.region: frozenset({endpoint.origin})}),
                origin=endpoint.origin,
                language=endpoint.language,
                country=endpoint.country,
                customer_app_id=endpoint.customer_app_id,
                default_domain=config.default_domain,
                terminal_id=config.terminal_id,
                lifetime_seconds=lifetime,
                code_interval_seconds=120,
            )
            slot = _Slot(
                lease,
                flow,
                scope,
                intent,
                self._view(lease, correlation, "CREATED"),
                time.monotonic() + lifetime,
            )
            self._registry[lease.flow_id] = slot
        return slot

    def _project(
        self, lease: FlowLease, slot: _Slot, result: FlowResult, correlation: str
    ) -> AccountFlowView:
        if result.correlation_id != correlation:
            raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
        state = result.state.value
        if result.error_code == "ACCOUNT_QUARANTINED":
            slot.native_quarantined = True
        if lease.operation in {"register", "recover"} and (
            result.http_status is None
            or not 200 <= result.http_status <= 299
            or result.native_msgcode == 404
        ):
            state = "UNKNOWN_OUTCOME"
        values: dict[str, Any] = {}
        if state == "COMPLETE" and not result.return_to_login:
            raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
        if state == "EXISTENCE":
            if type(result.exists) is not bool:
                raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
            values["exists"] = result.exists
        if state in {"IMAGE_AVAILABLE", "IMAGE_REQUIRED", "IMAGE_REJECTED"}:
            if result.challenge is None or not result.challenge.image_id:
                raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
            media_type, image = project_image(result.challenge.private_image_data)
            slot.image_generation += 1
            values["image"] = AccountFlowImage(
                challenge_id=uuid4(),
                generation=slot.image_generation,
                media_type=cast(Any, media_type),
                image_base64=image,
            )
        if state == "CODE_SENT":
            values["resend_wait_seconds"] = 120
        if result.error_code is not None:
            values["error_code"] = result.error_code.value
        return self._view(lease, correlation, state, **values)

    def _execute(
        self,
        operation: str,
        ticket: str,
        body: Body,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        self._running()
        if self._quarantined.is_set():
            raise AccountFailure("ACCOUNT_QUARANTINED", 503)
        budget = Budget(deadline_ms)
        correlation = _correlation(correlation_id)
        kinds: dict[str, type[Body]] = {
            "start": AccountFlowStart,
            "state": AccountFlowReference,
            "existence": AccountFlowReference,
            "image": AccountFlowReference,
            "issue_code": AccountDynamicCodeRequest,
            "register": AccountRegistrationSubmit,
            "recover": AccountRecoverySubmit,
            "cancel": AccountFlowCancel,
        }
        checked = None
        try:
            if type(body) is kinds[operation]:
                checked = kinds[operation].model_validate(
                    body.model_dump(exclude_unset=True)
                )
        except (ValidationError, ValueError, TypeError):
            pass
        if checked is None:
            raise AccountFailure("ACCOUNT_INPUT_INVALID", 422) from None
        body = checked
        lease = self._admission.redeem(ticket, operation)
        self._running()
        if not hmac.compare_digest(lease.key_commitment, self._key_commitment):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        if (
            body.region != lease.region
            or body.brand != lease.brand
            or body.purpose != lease.purpose
            or (
                isinstance(body, AccountFlowReference) and body.flow_id != lease.flow_id
            )
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        budget.remaining()
        with self._registry_lock:
            slot = self._registry.get(lease.flow_id)
        if lease.state in TERMINAL:
            view = self._view(lease, correlation, lease.state)
            self._admission.check(lease)
            budget.remaining()
            self._running()
            return view
        if operation == "start":
            slot = self._new(lease, cast(AccountFlowStart, body), correlation)
        if slot is None:
            claim = self._admission.claim(lease)
            if claim != "CLAIMED":
                raise AccountFailure()
            state = "EXPIRED" if lease.expires_at <= datetime.now(UTC) else "CLOSED"
            view = self._view(lease, correlation, state)
            self._admission.publish(lease, state)
            budget.remaining()
            self._running()
            return view
        if not slot.lock.acquire(blocking=False):
            raise AccountFailure()
        final = operation in {"register", "recover"}
        admitted = False
        matching_slot = False
        try:
            if (
                slot.lease.tenant_id,
                slot.lease.actor_id,
                slot.lease.session_digest,
                slot.lease.generation,
            ) != (
                lease.tenant_id,
                lease.actor_id,
                lease.session_digest,
                lease.generation,
            ):
                raise AccountFailure("ACCOUNT_DENIED", 404)
            matching_slot = True
            self._admission.check(lease)
            if operation == "state" and time.monotonic() < slot.expiry:
                budget.remaining()
                view = AccountFlowView.model_validate(
                    slot.view.model_dump()
                    | {
                        "request_id": correlation,
                        "expires_in_seconds": max(
                            1, int(slot.expiry - time.monotonic())
                        ),
                    }
                )
                self._admission.check(lease)
                budget.remaining()
                self._running()
                return view
            if (
                isinstance(body, AccountDynamicCodeRequest)
                and body.image_code is not None
            ):
                image = slot.view.image
                if (
                    image is None
                    or image.challenge_id != body.challenge_id
                    or image.generation != body.challenge_generation
                ):
                    self._admission.check(lease)
                    budget.remaining()
                    view = self._view(
                        lease, correlation, "FAILED", error_code="FLOW_IMAGE_MISSING"
                    )
                    budget.remaining()
                    self._running()
                    return view
            budget.remaining()
            self._running()
            expired = time.monotonic() >= slot.expiry
            claim = self._admission.claim(
                lease, slot.intent if final and not expired else None
            )
            if claim == "BUSY":
                raise AccountFailure()
            admitted = final
            if claim == "UNKNOWN_OUTCOME":
                view = self._view(lease, correlation, "UNKNOWN_OUTCOME")
            elif expired:
                view = self._view(
                    lease, correlation, "EXPIRED", error_code="FLOW_EXPIRED"
                )
            elif operation == "cancel":
                view = self._view(lease, correlation, "CLOSED")
            elif operation == "start":
                view = slot.view
            else:
                self._admission.check(lease)
                self._running()
                result: FlowResult | None = None
                error_code = None
                proved_no_dispatch = False
                try:
                    kwargs: dict[str, Any] = {
                        "deadline_ms": budget.remaining(),
                        "correlation_id": correlation,
                    }
                    if isinstance(body, AccountRegistrationSubmit):
                        result = slot.flow.register(
                            slot.scope,
                            body.password.get_secret_value(),
                            body.dynamic_code.get_secret_value(),
                            **kwargs,
                        )
                    elif isinstance(body, AccountRecoverySubmit):
                        result = slot.flow.recover(
                            slot.scope,
                            body.new_password.get_secret_value(),
                            body.dynamic_code.get_secret_value(),
                            **kwargs,
                        )
                    elif isinstance(body, AccountDynamicCodeRequest):
                        result = slot.flow.issue_code(
                            slot.scope,
                            image_code=body.image_code.get_secret_value()
                            if body.image_code
                            else "",
                            **kwargs,
                        )
                    else:
                        result = getattr(
                            slot.flow,
                            "exists" if operation == "existence" else operation,
                        )(slot.scope, **kwargs)
                    budget.remaining()
                    view = self._project(lease, slot, result, correlation)
                except FlowError as error:
                    # Reviewed PreloginAccountFlow raises this exact class/code
                    # only at its RSA precondition, before _client._run or the
                    # request callback. Transport/protocol exceptions never
                    # establish zero I/O and remain uncertain after admission.
                    proved_no_dispatch = final and error.code == "FLOW_KEY_MISSING"
                    error_code = error.code
                except (AccountClientError, AccountFailure) as error:
                    error_code = str(error.code)
                except (ValueError, TypeError):
                    error_code = "ACCOUNT_PROTOCOL_INVALID"
                if error_code is not None:
                    if error_code == "ACCOUNT_QUARANTINED":
                        slot.native_quarantined = True
                    view = self._view(
                        lease,
                        correlation,
                        "UNKNOWN_OUTCOME"
                        if final and not proved_no_dispatch
                        else "FAILED",
                        error_code=error_code,
                    )
            budget.remaining()
            self._running()
            if time.monotonic() >= slot.expiry and view.state not in {
                "EXPIRED",
                "CLOSED",
            }:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
            updated = self._admission.publish(lease, view.state)
            slot.lease, slot.view = updated, view
            budget.remaining()
            if view.state in TERMINAL:
                self._drop(lease.flow_id, slot)
            budget.remaining()
            self._running()
            return view
        except BaseException:
            # An admitted final remains UNKNOWN in SQL if settlement or current
            # authority cannot be proved. Removing local secrets never releases it.
            if matching_slot or admitted or operation == "start":
                self._drop(lease.flow_id, slot)
            raise
        finally:
            slot.lock.release()

    @worker_budget
    def start(
        self,
        ticket: str,
        body: AccountFlowStart,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("start", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def state(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("state", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def existence(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("existence", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def image(
        self,
        ticket: str,
        body: AccountFlowReference,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("image", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def issue_code(
        self,
        ticket: str,
        body: AccountDynamicCodeRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("issue_code", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def register(
        self,
        ticket: str,
        body: AccountRegistrationSubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("register", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def recover(
        self,
        ticket: str,
        body: AccountRecoverySubmit,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("recover", ticket, body, deadline_ms, correlation_id)

    @worker_budget
    def cancel(
        self,
        ticket: str,
        body: AccountFlowCancel,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountFlowView:
        return self._execute("cancel", ticket, body, deadline_ms, correlation_id)
