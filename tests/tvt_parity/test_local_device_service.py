"""Local verify gates: inert provider only; no native/device or SQL effects."""

from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from wso_contracts.tvt.local_device import LocalDeviceView, LocalVerifyRequest
from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_service import (
    LocalDeviceFailure,
    LocalInventoryChannel,
    LocalInventoryObservation,
    LocalVerificationExecutor,
)


class Admission:
    """Test substitute for external PostgreSQL; verifies callback decisions."""

    def __init__(self):
        self.allowed = True
        self.published = False
        self.closed = False

    def redeem(self, ticket, *, budget):
        budget.remaining_ms()
        return object()

    def run(self, lease, callback, *, budget):
        def current():
            budget.remaining_ms()
            return self.allowed

        value = callback(
            LocalDeviceCredentials(
                serial="TEST123", username="private-user", password="private-password"
            ),
            current,
        )
        assert isinstance(value, LocalInventoryObservation)
        budget.remaining_ms()
        if not self.allowed:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        self.published = True
        return LocalDeviceView(
            connection_id=uuid4(),
            device_id=uuid4(),
            store_id=uuid4(),
            connection_generation=1,
            inventory_revision=1,
            inventory_state="AVAILABLE",
            observed_at=datetime.now(UTC),
            channels=[],
            request_id="verify-test",
        )

    def close(self, lease, *, budget):
        self.closed = True


class Provider:
    def __init__(self, action=None, **changes):
        self.action = action
        self.changes = changes
        self.calls = 0

    def verify(self, credentials, *, deadline_monotonic, current, cancel):
        self.calls += 1
        assert credentials.serial == "TEST123"
        assert current()
        if self.action:
            self.action()
        fields = {
            "login_accepted": True,
            "same_original_session": True,
            "serial_matched": True,
            "channels_complete": True,
            "cleanup_confirmed": True,
            "channels": (
                LocalInventoryChannel(
                    guid=UUID("10000000-0000-0000-0000-000000000001").bytes_le,
                    raw_index=42,
                    window_index=7,
                    ordinal=1,
                    kind="digital",
                ),
            ),
            "group_provenance": "empty",
            "metadata_branch_complete": True,
            "permissions_complete": False,
        }
        return LocalInventoryObservation(**(fields | self.changes))


def execute(admission=None, provider=None, **kwargs):
    admission = admission or Admission()
    executor = LocalVerificationExecutor(admission, provider)
    return executor.verify(
        "a" * 64, deadline_ms=20000, correlation_id="verify-test", **kwargs
    )


@pytest.mark.parametrize("bad", [0, True, 20001, 60000])
def test_invalid_budget_never_calls_provider(bad):
    admission, provider = Admission(), Provider()
    with pytest.raises(LocalDeviceFailure):
        LocalVerificationExecutor(admission, provider).verify(
            "a" * 64, deadline_ms=bad, correlation_id="verify-test"
        )
    assert provider.calls == 0 and not admission.published


def test_missing_provider_never_grants_inventory():
    admission = Admission()
    with pytest.raises(LocalDeviceFailure) as caught:
        execute(admission)
    assert caught.value.code == "LOCAL_DEVICE_UNAVAILABLE"
    assert not admission.published


def test_available_result_requires_private_observation_and_remains_redacted():
    admission = Admission()
    view = execute(admission, Provider())
    assert view.inventory_state == "AVAILABLE" and admission.published
    assert admission.closed
    for secret in ("TEST123", "private-user", "private-password", "raw_index", "guid"):
        assert secret not in view.model_dump_json()


@pytest.mark.parametrize(
    "flag",
    [
        "same_original_session",
        "serial_matched",
        "channels_complete",
        "cleanup_confirmed",
    ],
)
def test_missing_proof_prevents_publication(flag):
    admission = Admission()
    with pytest.raises(LocalDeviceFailure):
        execute(admission, Provider(**{flag: False}))
    assert not admission.published and admission.closed


def test_revoke_during_provider_prevents_publication():
    admission = Admission()
    with pytest.raises(LocalDeviceFailure):
        execute(admission, Provider(lambda: setattr(admission, "allowed", False)))
    assert not admission.published and admission.closed


def test_cancellation_during_provider_prevents_publication():
    admission, cancel = Admission(), Event()
    with pytest.raises(LocalDeviceFailure) as caught:
        execute(admission, Provider(cancel.set), cancel=cancel)
    assert caught.value.code == "LOCAL_DEVICE_CANCELLED"
    assert not admission.published and admission.closed


def test_cancelled_request_never_dispatches():
    admission, provider, cancel = Admission(), Provider(), Event()
    cancel.set()
    with pytest.raises(LocalDeviceFailure):
        execute(admission, provider, cancel=cancel)
    assert provider.calls == 0


def test_provider_failure_cannot_echo_credentials():
    class Rejected:
        def verify(self, credentials, **kwargs):
            raise RuntimeError(credentials.password)

    with pytest.raises(LocalDeviceFailure) as caught:
        execute(provider=Rejected())
    assert "private-password" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_expired_budget_after_provider_does_not_publish():
    ticks = [100.0]
    admission = Admission()
    executor = LocalVerificationExecutor(
        admission, Provider(lambda: ticks.__setitem__(0, 121)), clock=lambda: ticks[0]
    )
    with pytest.raises(LocalDeviceFailure) as caught:
        executor.verify("a" * 64, deadline_ms=20000, correlation_id="verify-test")
    assert caught.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert not admission.published


def test_count_only_and_duplicate_roster_are_rejected():
    class CountOnly:
        def verify(self, credentials, **kwargs):
            return {"channel_count": 8}

    with pytest.raises(LocalDeviceFailure):
        execute(provider=CountOnly())
    channel = LocalInventoryChannel(
        guid=uuid4().bytes_le, raw_index=7, window_index=7, ordinal=1, kind="digital"
    )
    with pytest.raises(LocalDeviceFailure):
        execute(provider=Provider(channels=(channel, channel)))


def test_private_projection_is_immutable_and_hides_native_selectors():
    channel = LocalInventoryChannel(
        guid=uuid4().bytes_le, raw_index=42, window_index=7, ordinal=1, kind="digital"
    )
    assert "42" not in repr(channel) and "guid" not in repr(channel)
    with pytest.raises(AttributeError):
        channel.raw_index = 2


def test_cleanup_failure_cannot_return_available_inventory():
    class FailedClose(Admission):
        def close(self, lease, *, budget):
            raise RuntimeError("private cleanup detail")

    with pytest.raises(LocalDeviceFailure):
        execute(FailedClose(), Provider())


def test_cleanup_that_exceeds_original_deadline_cannot_return_success():
    ticks = [100.0]

    class SlowClose(Admission):
        def close(self, lease, *, budget):
            ticks[0] = 121.0

    with pytest.raises(LocalDeviceFailure) as caught:
        LocalVerificationExecutor(
            SlowClose(), Provider(), clock=lambda: ticks[0]
        ).verify("a" * 64, deadline_ms=20000, correlation_id="verify-test")
    assert caught.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"


def test_request_rejects_authority_and_secret_fields():
    base = {"store_id": str(uuid4()), "expected_generation": 1}
    assert LocalVerifyRequest.model_validate(base).expected_generation == 1
    for name in ("serial", "password", "actor_id", "identity_id", "channel_count"):
        with pytest.raises(ValidationError):
            LocalVerifyRequest.model_validate(base | {name: "private"})


def test_public_counters_never_accept_unsafe_javascript_integers():
    with pytest.raises(ValidationError):
        LocalVerifyRequest(store_id=uuid4(), expected_generation=2**53)
    view = execute(provider=Provider())
    for key in ("connection_generation", "inventory_revision"):
        with pytest.raises(ValidationError):
            LocalDeviceView.model_validate(view.model_dump() | {key: 2**53})


def test_observation_requires_explicit_accepted_login():
    admission = Admission()
    with pytest.raises(LocalDeviceFailure):
        execute(admission, Provider(login_accepted=False))
    assert not admission.published


@pytest.mark.parametrize("failure", ["expiry", "cancel", "uncertain_commit"])
def test_actual_redemption_keeps_cleanup_ownership_when_commit_fails(failure):
    """Use real admission/executor; only the external SQL/commit is inert."""
    from wso_core.tvt.local_admission import LocalDeviceAdmission

    ticks, cancel = [100.0], Event()
    state = {"ticket": "ISSUED", "close_calls": 0, "provider_calls": 0}

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class DB:
        def execute(self, sql, parameters=None):
            statement = str(sql)
            if statement == "SELECT current_user":
                return Result("wso_connection_worker")
            if "wso_tvt_local_redeem" in statement:
                state["ticket"] = "REDEEMED"
                return Result(True)
            if "wso_tvt_local_close" in statement:
                state["ticket"] = "CLOSED"
                state["close_calls"] += 1
            return Result(None)

    class Engine:
        @contextmanager
        def begin(self):
            yield DB()
            if state["ticket"] == "REDEEMED":
                if failure == "expiry":
                    ticks[0] = 121.0
                elif failure == "cancel":
                    cancel.set()
                else:
                    raise RuntimeError("uncertain commit completion")

    class ForbiddenProvider:
        def verify(self, *args, **kwargs):
            state["provider_calls"] += 1
            pytest.fail("provider reached after failed redemption")

    admission = object.__new__(LocalDeviceAdmission)
    admission._engine = Engine()
    with pytest.raises(LocalDeviceFailure) as caught:
        LocalVerificationExecutor(
            admission, ForbiddenProvider(), clock=lambda: ticks[0]
        ).verify(
            "a" * 64, deadline_ms=20000, correlation_id="commit-test", cancel=cancel
        )
    assert (
        caught.value.code
        == {
            "expiry": "LOCAL_DEVICE_DEADLINE_EXCEEDED",
            "cancel": "LOCAL_DEVICE_CANCELLED",
            "uncertain_commit": "LOCAL_DEVICE_UNAVAILABLE",
        }[failure]
    )
    assert state == {"ticket": "CLOSED", "close_calls": 1, "provider_calls": 0}
