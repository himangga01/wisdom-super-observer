"""Synthetic worker behavior; PostgreSQL authority is tested separately."""

import base64
import hashlib
import importlib
import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from wso_contracts.tvt.account_flows import (
    AccountDynamicCodeRequest,
    AccountFlowCancel,
    AccountFlowReference,
    AccountFlowStart,
    AccountRecoverySubmit,
    AccountRegistrationSubmit,
)
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.account_protocol import parse_response


def subject():
    assert importlib.util.find_spec("wso_api.tvt.flow_service") is not None
    return importlib.import_module("wso_api.tvt.flow_service")


class AdmissionBoundary:
    """Only SQL is substituted here; no production authority derives from UUIDs."""

    def __init__(self):
        self.flows, self.tickets, self.holds = {}, {}, set()
        self.intents = {}
        self.valid = True

    def issue(self, operation, body, actor=None, session="a" * 64):
        actor = actor or UUID(int=2)
        from wso_core.tvt.flow_admission import _SEAL, FlowLease

        if operation == "start":
            flow_id = uuid4()
            self.flows[flow_id] = FlowLease(
                "",
                UUID(int=1),
                actor,
                session,
                flow_id,
                body.region,
                body.brand,
                body.purpose,
                1,
                "CREATED",
                datetime.now(UTC) + timedelta(seconds=300),
                operation,
                _SEAL,
                key_commitment=hashlib.sha256(bytes(range(32))).hexdigest(),
            )
        else:
            flow_id = body.flow_id
        ticket = uuid4().hex
        self.tickets[ticket] = replace(
            self.flows[flow_id], value=ticket, operation=operation
        )
        return ticket

    def redeem(self, ticket, operation):
        value = self.tickets.pop(ticket, None)
        if not self.valid or value is None or value.operation != operation:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return value

    def check(self, lease):
        if not self.valid or self.flows[lease.flow_id].generation != lease.generation:
            raise AccountFailure("ACCOUNT_DENIED", 404)

    def claim(self, lease, intent=None):
        self.check(lease)
        if intent is not None:
            if intent in self.holds:
                return "UNKNOWN_OUTCOME"
            self.holds.add(intent)
            self.intents[lease.flow_id] = intent
            self.flows[lease.flow_id] = replace(lease, state="UNKNOWN_OUTCOME")
        return "CLAIMED"

    def publish(self, lease, state):
        self.check(lease)
        if state in {"COMPLETE", "FAILED"} and lease.flow_id in self.intents:
            self.holds.discard(self.intents[lease.flow_id])
        updated = replace(lease, state=state, generation=lease.generation + 1)
        self.flows[lease.flow_id] = updated
        return updated


def response(data=None, code=200, status=200):
    return parse_response(
        status, json.dumps({"basic": {"msgcode": code}, "data": data}).encode()
    )


@pytest.fixture
def public_key():
    return base64.b64encode(
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode()


def build(
    monkeypatch,
    replies=(),
    *,
    admission=None,
    binding_key=bytes(range(32)),
    default_domain="source.example.invalid",
):
    module = subject()
    import wso_core.tvt.account_client as client
    from wso_api.tvt.session_service import AccountEndpoint

    queue, requests = iter(replies), []

    class Boundary:
        def send(self, request):
            requests.append(request)
            value = next(queue)
            if callable(value):
                value = value(request)
            if isinstance(value, BaseException):
                raise value
            return value

        def close(self):
            pass

    monkeypatch.setattr(client, "ProcessAccountTransport", lambda *a, **k: Boundary())
    admission = admission or AdmissionBoundary()
    worker = module.AccountFlowWorkerExecutor(
        admission,
        (
            AccountEndpoint(
                "test",
                "brand",
                "https://localhost:1",
                "en",
                "KR",
                "1.18.1",
                "app",
                "already-hashed-do-not-use",
            ),
        ),
        {("test", "brand"): module.FlowEndpointConfig(default_domain)},
        binding_key,
    )
    return worker, admission, requests


def start(worker, admission, **changes):
    body = AccountFlowStart.model_validate(
        {
            "region": "test",
            "brand": "brand",
            "purpose": "register",
            "mode": "email",
            "account": "alice@example.invalid",
        }
        | changes
    )
    return call(worker, admission, "start", body)


def ref(view, kind=AccountFlowReference, **extra):
    return kind(
        region=view.region,
        brand=view.brand,
        purpose=view.purpose,
        flow_id=view.flow_id,
        **extra,
    )


def call(worker, admission, operation, body, deadline=3000):
    return getattr(worker, operation)(
        admission.issue(operation, body),
        body,
        deadline_ms=deadline,
        correlation_id="flow-test",
    )


@pytest.mark.parametrize("exists", [True, False])
def test_phone_existence_uses_real_native_wire_and_closed_view(monkeypatch, exists):
    worker, admission, requests = build(monkeypatch, [response({"isExist": exists})])
    view = start(
        worker, admission, mode="phone", account="1012345678", country_code="82"
    )
    assert view.state == "CREATED" and not requests
    result = call(worker, admission, "existence", ref(view))
    assert result.state == "EXISTENCE" and result.exists is exists
    assert result.request_id == "flow-test"
    assert requests[0].path == "/user/info/phone/is-exist"
    assert json.loads(requests[0].body)["data"] == {
        "mobile": "82+1012345678",
        "customerAppId": "app",
    }
    assert "1012345678" not in result.model_dump_json()


@pytest.mark.parametrize("data", [None, {}, {"isExist": None}, {"isExist": 0}])
def test_missing_existence_is_protocol_failure(monkeypatch, data):
    worker, admission, _ = build(monkeypatch, [response(data)])
    view = start(worker, admission)
    result = call(worker, admission, "existence", ref(view))
    assert result.state == "FAILED" and result.error_code == "ACCOUNT_PROTOCOL_INVALID"
    assert result.exists is None


def test_image_pair_replaced_and_cleared_before_dispatch(monkeypatch, public_key):
    media = base64.b64encode(b"\xff\xd8\xffimage\xff\xd9").decode()
    worker, admission, requests = build(
        monkeypatch,
        [
            response(
                {
                    "idCode": "private-image",
                    "imgCodeImgData": media,
                    "publicKey": public_key,
                }
            ),
            response({"publicKey": public_key}),
            response({}),
        ],
    )
    view = start(worker, admission)
    image = call(worker, admission, "image", ref(view))
    assert image.image and image.image.generation == 1
    invalid = ref(
        view,
        AccountDynamicCodeRequest,
        challenge_id=uuid4(),
        challenge_generation=1,
        image_code="secret-image-text",
    )
    bad = call(worker, admission, "issue_code", invalid)
    assert bad.error_code == "FLOW_IMAGE_MISSING" and len(requests) == 1
    # A wrong selector must not destroy the actual admitted image.
    good = ref(
        view,
        AccountDynamicCodeRequest,
        challenge_id=image.image.challenge_id,
        challenge_generation=1,
        image_code="secret-image-text",
    )
    sent = call(worker, admission, "issue_code", good)
    assert sent.state == "CODE_SENT" and sent.resend_wait_seconds == 120
    assert json.loads(requests[1].body)["data"]["idCode"] == "private-image"
    assert (
        call(worker, admission, "issue_code", good).error_code == "FLOW_IMAGE_MISSING"
    )
    assert len(requests) == 2


def test_completion_returns_login_and_allows_new_completed_business_intent(
    monkeypatch, public_key
):
    worker, admission, requests = build(
        monkeypatch,
        [
            response({"publicKey": public_key}),
            response({"token": "MUST-NOT-LEAK"}),
            response({"publicKey": public_key}),
            response({}),
        ],
    )
    view = start(worker, admission)
    call(worker, admission, "issue_code", ref(view, AccountDynamicCodeRequest))
    submit = ref(
        view,
        AccountRegistrationSubmit,
        password="Secret-password",
        dynamic_code="123456",
    )
    result = call(worker, admission, "register", submit)
    assert result.state == "COMPLETE" and result.return_to_login
    assert "token" not in result.model_dump_json()
    again = start(worker, admission)
    call(worker, admission, "issue_code", ref(again, AccountDynamicCodeRequest))
    result = call(
        worker,
        admission,
        "register",
        ref(again, AccountRegistrationSubmit, password="other", dynamic_code="654321"),
    )
    assert result.state == "COMPLETE" and len(requests) == 4


def test_uncertain_final_survives_restart_and_new_flow(monkeypatch):
    from wso_core.tvt.account_transport import AccountTransportError

    worker, admission, requests = build(
        monkeypatch, [AccountTransportError("private secret")]
    )
    view = start(worker, admission, purpose="recover")
    result = call(
        worker,
        admission,
        "recover",
        ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        ),
    )
    assert result.state == "UNKNOWN_OUTCOME"
    successor, _, _ = build(monkeypatch, admission=admission)
    assert call(successor, admission, "state", ref(view)).state == "UNKNOWN_OUTCOME"
    fresh = start(successor, admission, purpose="recover")
    assert (
        call(
            successor,
            admission,
            "recover",
            ref(
                fresh,
                AccountRecoverySubmit,
                new_password="password2",
                dynamic_code="654321",
            ),
        ).state
        == "UNKNOWN_OUTCOME"
    )
    assert len(requests) == 1


def test_cancel_clears_private_registry_and_lost_registry_closes(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    assert (
        call(worker, admission, "cancel", ref(view, AccountFlowCancel)).state
        == "CLOSED"
    )
    assert not worker._registry and not requests
    view = start(worker, admission)
    successor, _, _ = build(monkeypatch, admission=admission)
    assert call(successor, admission, "state", ref(view)).state == "CLOSED"


def test_actor_capacity_rejects_and_cancel_releases_slot(monkeypatch):
    worker, admission, _ = build(monkeypatch)
    views = [
        start(worker, admission, account=f"a{i}@example.invalid") for i in range(4)
    ]
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        start(worker, admission, account="fifth@example.invalid")
    call(worker, admission, "cancel", ref(views[0], AccountFlowCancel))
    assert start(worker, admission, account="sixth@example.invalid").state == "CREATED"


def test_recovery_1005_is_failure_and_bad_media_never_published(monkeypatch):
    worker, admission, _ = build(
        monkeypatch,
        [
            response({"idCode": "secret", "imgData": "invalid"}, 1005),
            response({"idCode": "secret", "imgCodeImgData": "bad"}),
        ],
    )
    view = start(worker, admission, purpose="recover")
    assert (
        call(
            worker, admission, "issue_code", ref(view, AccountDynamicCodeRequest)
        ).state
        == "FAILED"
    )
    view = start(worker, admission)
    bad = call(worker, admission, "image", ref(view))
    assert bad.state == "FAILED" and bad.image is None


def test_revocation_during_final_denies_publication_but_keeps_hold(monkeypatch):
    admission = AdmissionBoundary()

    def revoked(_):
        admission.valid = False
        return response({})

    worker, _, _ = build(monkeypatch, [revoked], admission=admission)
    view = start(worker, admission, purpose="recover")
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        call(
            worker,
            admission,
            "recover",
            ref(
                view,
                AccountRecoverySubmit,
                new_password="password",
                dynamic_code="123456",
            ),
        )
    assert len(admission.holds) == 1
    assert admission.flows[view.flow_id].state == "UNKNOWN_OUTCOME"


@pytest.mark.parametrize("status", [400, 500])
def test_non2xx_final_is_durably_unknown_even_with_business_rejection(
    monkeypatch, status
):
    worker, admission, requests = build(
        monkeypatch, [response({}, code=1001, status=status)]
    )
    view = start(worker, admission, purpose="recover")
    result = call(
        worker,
        admission,
        "recover",
        ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        ),
    )
    assert result.state == "UNKNOWN_OUTCOME" and len(requests) == 1
    assert admission.flows[view.flow_id].state == "UNKNOWN_OUTCOME"


def test_original_budget_spans_admission_and_final_response(monkeypatch):
    admission = AdmissionBoundary()
    worker, _, requests = build(
        monkeypatch,
        [lambda _: (time.sleep(0.04), response({}))[1]],
        admission=admission,
    )
    view = start(worker, admission, purpose="recover")
    with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
        call(
            worker,
            admission,
            "recover",
            ref(
                view,
                AccountRecoverySubmit,
                new_password="password",
                dynamic_code="123456",
            ),
            deadline=20,
        )
    assert len(requests) == 1 and len(admission.holds) == 1
    assert admission.flows[view.flow_id].state == "UNKNOWN_OUTCOME"


def test_overlapping_operation_rejected_before_upstream(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocking(_):
        entered.set()
        assert release.wait(2)
        return response({"isExist": True})

    worker, admission, requests = build(monkeypatch, [blocking])
    view = start(worker, admission)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(call(worker, admission, "existence", ref(view)))
    )
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
            call(worker, admission, "image", ref(view))
    finally:
        release.set()
        thread.join(2)
    assert len(requests) == 1 and result[0].exists is True


def test_expired_registry_slot_returns_expired_without_io(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    worker._registry[view.flow_id].expiry = 0
    assert call(worker, admission, "state", ref(view)).state == "EXPIRED"
    assert not requests and not worker._registry


def test_wrong_purpose_and_bad_correlation_deny_before_io(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    body = ref(view).model_copy(update={"purpose": "recover"})
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        call(worker, admission, "existence", body)
    from wso_core.tvt.ports import AccountClientError

    with pytest.raises(AccountClientError):
        worker.state(
            "secret-ticket",
            ref(view),
            deadline_ms=1000,
            correlation_id="unsafe secret\n",
        )
    assert not requests


def test_registry_capacity_has_no_silent_active_eviction(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    for index in range(128):
        body = AccountFlowStart(
            region="test",
            brand="brand",
            purpose="recover",
            mode="email",
            account=f"a{index}@example.invalid",
        )
        ticket = admission.issue("start", body, actor=UUID(int=1000 + index))
        worker.start(ticket, body, deadline_ms=3000, correlation_id="capacity")
    body = AccountFlowStart(
        region="test",
        brand="brand",
        purpose="recover",
        mode="email",
        account="overflow@example.invalid",
    )
    ticket = admission.issue("start", body, actor=UUID(int=9999))
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        worker.start(ticket, body, deadline_ms=3000, correlation_id="capacity")
    assert len(worker._registry) == 128 and not requests


def test_hmac_hold_cannot_be_bypassed_by_actor_session_case_or_password(monkeypatch):
    from wso_core.tvt.account_transport import AccountTransportError

    worker, admission, requests = build(monkeypatch, [AccountTransportError("failed")])
    view = start(worker, admission, purpose="recover")
    call(
        worker,
        admission,
        "recover",
        ref(view, AccountRecoverySubmit, new_password="first", dynamic_code="123456"),
    )
    body = AccountFlowStart(
        region="test",
        brand="brand",
        purpose="recover",
        mode="email",
        account="ALICE@EXAMPLE.INVALID",
    )
    ticket = admission.issue("start", body, actor=UUID(int=3), session="b" * 64)
    view = worker.start(ticket, body, deadline_ms=3000, correlation_id="flow-test")
    result = call(
        worker,
        admission,
        "recover",
        ref(view, AccountRecoverySubmit, new_password="changed", dynamic_code="654321"),
    )
    assert (
        result.state == "UNKNOWN_OUTCOME"
        and len(requests) == 1
        and len(admission.holds) == 1
    )


def test_slow_admission_cannot_restart_upstream_budget(monkeypatch):
    worker, admission, requests = build(monkeypatch, [response({})])
    view = start(worker, admission, purpose="recover")
    original = admission.redeem

    def slow(ticket, operation):
        result = original(ticket, operation)
        time.sleep(0.025)
        return result

    admission.redeem = slow
    with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
        call(
            worker,
            admission,
            "recover",
            ref(
                view,
                AccountRecoverySubmit,
                new_password="password",
                dynamic_code="123456",
            ),
            deadline=10,
        )
    assert not requests and not admission.holds


def test_bad_runtime_key_is_safe_and_never_final_dispatches(monkeypatch):
    worker, admission, requests = build(
        monkeypatch, [response({"publicKey": "private-malformed-rsa-secret"})]
    )
    view = start(worker, admission)
    result = call(worker, admission, "issue_code", ref(view, AccountDynamicCodeRequest))
    assert (
        result.state == "UNKNOWN_OUTCOME"
        and result.error_code == "ACCOUNT_PROTOCOL_INVALID"
    )
    assert "private-malformed" not in result.model_dump_json() and len(requests) == 1


def test_model_construct_input_is_revalidated_without_private_error_context(
    monkeypatch,
):
    worker, _admission, requests = build(monkeypatch)
    bad = AccountFlowStart.model_construct(
        region="test",
        brand="brand",
        purpose="register",
        mode="email",
        account="raw-secret",
    )
    with pytest.raises(AccountFailure) as error:
        worker.start("ticket", bad, deadline_ms=1000, correlation_id="safe")
    assert (
        str(error.value) == "ACCOUNT_INPUT_INVALID" and error.value.__context__ is None
    )
    assert not requests


def test_final_dc_hint_never_settles_a_known_failure_or_retries(monkeypatch):
    worker, admission, requests = build(
        monkeypatch,
        [response({"domain": "elsewhere.invalid", "httpPrefix": "https://"}, code=404)],
    )
    view = start(worker, admission, purpose="recover")
    result = call(
        worker,
        admission,
        "recover",
        ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        ),
    )
    assert (
        result.state == "UNKNOWN_OUTCOME"
        and len(requests) == 1
        and len(admission.holds) == 1
    )


def test_revocation_after_redemption_clears_settled_private_registry(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)

    def denied(_):
        raise AccountFailure("ACCOUNT_DENIED", 404)

    admission.check = denied
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        call(worker, admission, "existence", ref(view))
    assert not worker._registry and not requests


def test_restart_with_different_binding_key_cannot_bypass_uncertain_intent(monkeypatch):
    from wso_core.tvt.account_transport import AccountTransportError

    worker, admission, requests = build(monkeypatch, [AccountTransportError("failed")])
    view = start(worker, admission, purpose="recover")
    call(
        worker,
        admission,
        "recover",
        ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        ),
    )
    successor, _, successor_requests = build(
        monkeypatch, admission=admission, binding_key=b"x" * 32
    )
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        start(successor, admission, purpose="recover")
    assert len(requests) == 1 and len(admission.holds) == 1 and not successor_requests


def test_terminal_projection_cannot_return_after_original_deadline(monkeypatch):
    from wso_contracts.tvt.account_flows import AccountFlowView

    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    call(worker, admission, "cancel", ref(view, AccountFlowCancel))
    original = AccountFlowView.model_validate

    def delayed_projection(*args, **kwargs):
        # Simulate scheduling/validation latency at the actual public boundary.
        time.sleep(0.025)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        AccountFlowView, "model_validate", staticmethod(delayed_projection)
    )
    with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
        call(worker, admission, "state", ref(view), deadline=10)
    assert not requests


def test_explicit_empty_domain_registers_exact_apk_empty_md5(monkeypatch, public_key):
    worker, admission, requests = build(
        monkeypatch,
        [response({"publicKey": public_key}), response({})],
        default_domain="",
    )
    view = start(worker, admission)
    call(worker, admission, "issue_code", ref(view, AccountDynamicCodeRequest))
    result = call(
        worker,
        admission,
        "register",
        ref(
            view, AccountRegistrationSubmit, password="password", dynamic_code="123456"
        ),
    )
    assert result.state == "COMPLETE"
    assert "customerMark" not in json.loads(requests[0].body)["data"]
    assert (
        json.loads(requests[1].body)["data"]["customerMark"]
        == "d41d8cd98f00b204e9800998ecf8427e"
    )


def test_close_stops_admission_clears_private_slots_and_closes_once(monkeypatch):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    slot = worker._registry[view.flow_id]
    original = slot.flow.close
    calls = []

    def closing():
        calls.append(1)
        original()

    monkeypatch.setattr(slot.flow, "close", closing)
    assert callable(getattr(worker, "close", None)), (
        "worker shutdown must stop admission and clear private ownership"
    )
    worker.close(deadline_ms=1000)
    worker.close(deadline_ms=1000)
    assert calls == [1] and not worker._registry and not worker._binding_key
    with pytest.raises(AccountFailure):
        start(worker, admission)
    with pytest.raises(AccountFailure):
        call(worker, admission, "state", ref(view))
    assert not requests


def test_close_during_admitted_final_preserves_hold_and_suppresses_late_result(
    monkeypatch,
):
    entered, release = threading.Event(), threading.Event()

    def blocked(_):
        entered.set()
        assert release.wait(2)
        return response({})

    worker, admission, requests = build(monkeypatch, [blocked])
    view = start(worker, admission, purpose="recover")
    slot = worker._registry[view.flow_id]
    original = slot.flow.close
    close_calls, outcomes = [], []

    def closing():
        close_calls.append(1)
        original()
        release.set()

    monkeypatch.setattr(slot.flow, "close", closing)

    def perform():
        try:
            outcomes.append(
                call(
                    worker,
                    admission,
                    "recover",
                    ref(
                        view,
                        AccountRecoverySubmit,
                        new_password="password",
                        dynamic_code="123456",
                    ),
                )
            )
        except AccountFailure as error:
            outcomes.append(error)

    thread = threading.Thread(target=perform)
    thread.start()
    assert entered.wait(2)
    try:
        assert callable(getattr(worker, "close", None))
        worker.close(deadline_ms=1000)
    finally:
        release.set()
        thread.join(2)
    assert len(requests) == 1 and close_calls == [1]
    assert len(outcomes) == 1 and isinstance(outcomes[0], AccountFailure)
    assert (
        admission.flows[view.flow_id].state == "UNKNOWN_OUTCOME"
        and len(admission.holds) == 1
    )
    assert not worker._registry and not worker._binding_key


def test_cancel_then_shutdown_does_not_close_native_flow_twice(monkeypatch):
    worker, admission, _ = build(monkeypatch)
    view = start(worker, admission)
    original = worker._registry[view.flow_id].flow.close
    calls = []

    def closing():
        calls.append(1)
        original()

    monkeypatch.setattr(worker._registry[view.flow_id].flow, "close", closing)
    call(worker, admission, "cancel", ref(view, AccountFlowCancel))
    assert callable(getattr(worker, "close", None))
    worker.close(deadline_ms=1000)
    assert calls == [1]


def test_shutdown_has_one_total_budget_for_128_slots_and_no_retry(monkeypatch):
    worker, admission, _ = build(monkeypatch)
    release = threading.Event()
    calls = []
    slots = []
    for index in range(128):
        body = AccountFlowStart(
            region="test",
            brand="brand",
            purpose="recover",
            mode="email",
            account=f"close{index}@example.invalid",
        )
        view = worker.start(
            admission.issue("start", body, actor=UUID(int=1000 + index)),
            body,
            deadline_ms=3000,
            correlation_id="close-capacity",
        )
        slot = worker._registry[view.flow_id]
        slots.append(slot)
        original = slot.flow.close

        def blocking_close(original=original):
            calls.append(1)
            release.wait()
            original()

        monkeypatch.setattr(slot.flow, "close", blocking_close)
    started = time.monotonic()
    try:
        with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
            worker.close(deadline_ms=30)
        assert time.monotonic() - started < 0.5
        assert len(worker._shutdown_pending) == 128 and not worker._registry
        assert not worker._binding_key
        previous = len(calls)
        started = time.monotonic()
        with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
            worker.close(deadline_ms=1000)
        assert time.monotonic() - started < 0.1 and len(calls) == previous
    finally:
        release.set()
        for slot in slots:
            if slot.close_started:
                assert slot.close_done.wait(1)


def test_close_respects_exhausted_shared_budget_without_new_cleanup_window(monkeypatch):
    from wso_core.tvt.token_vault import token_budget

    worker, admission, _ = build(monkeypatch)
    start(worker, admission)
    with (
        token_budget(lambda: 0),
        pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"),
    ):
        worker.close(deadline_ms=1000)
    assert not worker._binding_key and worker._shutdown_pending
    started = time.monotonic()
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
        worker.close(deadline_ms=1000)
    assert time.monotonic() - started < 0.1


def test_native_quarantine_remains_owned_and_closes_new_admission(monkeypatch):
    from wso_core.tvt.account_process import AccountProcessError

    worker, admission, requests = build(
        monkeypatch,
        [AccountProcessError("Account process settlement could not be proved.")],
    )
    view = start(worker, admission, purpose="recover")
    result = call(
        worker,
        admission,
        "recover",
        ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        ),
    )
    assert (
        result.state == "UNKNOWN_OUTCOME" and result.error_code == "ACCOUNT_QUARANTINED"
    )
    assert len(worker._quarantine) == 1 and len(requests) == 1
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
        start(worker, admission)
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
        worker.close(deadline_ms=10)
    assert worker._shutdown_pending and not worker._binding_key


def test_shutdown_thread_failure_is_fixed_quarantine_without_raw_context(monkeypatch):
    worker, admission, _ = build(monkeypatch)
    start(worker, admission)

    def rejected(_):
        raise RuntimeError("private-runtime-error")

    monkeypatch.setattr(threading.Thread, "start", rejected)
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED") as error:
        worker.close(deadline_ms=10)
    assert error.value.__context__ is None and worker._shutdown_pending


def test_protected_worker_requires_explicit_configuration():
    """Missing worker configuration must not expose a permissive executor."""
    assert importlib.util.find_spec("wso_api.tvt.flow_service") is not None, (
        "Protected flow worker must exist and fail closed without configuration"
    )
    import pytest
    from wso_api.tvt.flow_service import AccountFlowWorkerExecutor
    from wso_core.tvt.account_projection import AccountFailure

    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        AccountFlowWorkerExecutor(None, (), None, None)


def test_missing_domain_mapping_still_denies_and_concurrent_close_is_once(monkeypatch):
    worker, admission, _ = build(monkeypatch, default_domain="")
    with pytest.raises(AccountFailure):
        subject().AccountFlowWorkerExecutor(
            admission, tuple(worker._endpoints.values()), {}, bytes(range(32))
        )
    view = start(worker, admission)
    slot = worker._registry[view.flow_id]
    original = slot.flow.close
    entered, release = threading.Event(), threading.Event()
    calls, outcomes = [], []

    def closing():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        original()

    monkeypatch.setattr(slot.flow, "close", closing)

    def shutdown():
        try:
            outcomes.append(worker.close(deadline_ms=1000))
        except AccountFailure as error:
            outcomes.append(error)

    first = threading.Thread(target=shutdown)
    second = threading.Thread(target=shutdown)
    first.start()
    assert entered.wait(1)
    second.start()
    release.set()
    first.join(2)
    second.join(2)
    assert calls == [1] and outcomes == [None, None]


def test_missing_registration_key_proves_zero_io_and_settles_only_local_failure(
    monkeypatch,
):
    worker, admission, requests = build(monkeypatch)
    view = start(worker, admission)
    result = call(
        worker,
        admission,
        "register",
        ref(
            view, AccountRegistrationSubmit, password="password", dynamic_code="123456"
        ),
    )
    assert result.state == "FAILED" and result.error_code == "FLOW_KEY_MISSING"
    assert not requests and not admission.holds


def test_cancellation_after_final_admission_retains_unknown_hold(monkeypatch):
    import asyncio

    worker, admission, requests = build(monkeypatch, [asyncio.CancelledError()])
    view = start(worker, admission, purpose="recover")
    with pytest.raises(asyncio.CancelledError):
        call(
            worker,
            admission,
            "recover",
            ref(
                view,
                AccountRecoverySubmit,
                new_password="password",
                dynamic_code="123456",
            ),
        )
    assert len(requests) == 1 and len(admission.holds) == 1
    assert (
        admission.flows[view.flow_id].state == "UNKNOWN_OUTCOME"
        and not worker._registry
    )
