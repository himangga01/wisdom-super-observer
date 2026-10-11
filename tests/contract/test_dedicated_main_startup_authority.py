"""Dedicated MAIN phase composition with real guards and inert SQL/native edges."""

import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, MuxScopeKey
from wso_core.tvt.local_media_service import LocalLiveProof
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
from wso_tvt_bridge import windows_socket as windows
from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget
from wso_tvt_bridge.local_live_mux_provider import NativeLocalMuxProvider

from tests.tvt_parity.test_local_media_contracts import local_values


class Key:
    def encryption_key(self):
        return bytes(range(32))


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class PhaseSQL:
    """SQL phase/authority model; real predicates require Root's owned SQL gate."""

    def __init__(self, scope, credentials, cipher):
        self.scope = scope
        self.lease_id, self.master_id = uuid4(), uuid4()
        self.phase, self.allowed = "LOGIN", True
        self.checked_out = 0
        self.calls = []
        self.during_selection = None
        self.selection = {
            "guid": (b"C" * 16).hex(),
            "raw_index": 0,
            "window_index": 0,
            "ordinal": 1,
            "kind": "digital",
            "stream": "main",
        }
        self.view = {**local_values(), "id": self.lease_id}
        self.envelope = cipher.seal(
            scope.tenant_id,
            scope.connection_id,
            scope.secret_version,
            credentials.to_encrypt_bytes(),
        )

    @contextmanager
    def begin(self):
        self.checked_out += 1
        try:
            yield self
        finally:
            self.checked_out -= 1

    def execute(self, statement, parameters=None):
        query = str(statement)
        if query == "SELECT current_user":
            return Result("wso_connection_worker")
        if "set_config(" in query:
            return Result(None)
        self.calls.append(query)
        if "media_redeem(" in query:
            return Result(self.lease_id)
        if "media_dedicated_register(" in query:
            scope = self.scope
            return Result(
                {
                    **{
                        name: getattr(scope, name)
                        for name in scope.__dataclass_fields__
                    },
                    "session_digest": scope.session_digest.hex(),
                    "lease_id": self.lease_id,
                    "master_id": self.master_id,
                    "dedicated_native_generation": parameters["n"],
                }
            )
        if "media_viewer_selection(" in query:
            value = (
                self.selection.copy()
                if self.allowed and self.phase in {"LOGIN", "CLAIMED"}
                else None
            )
            if self.during_selection is not None:
                self.during_selection()
            return Result(value)
        if "media_use(" in query:
            assert self.phase == "LOGIN"
            self.phase = "CLAIMED"
            return Result(
                {
                    **self.selection,
                    "guid": b"C" * 16,
                    "tenant_id": self.scope.tenant_id,
                    "connection_id": self.scope.connection_id,
                    "version_id": self.scope.secret_version,
                    "nonce": self.envelope.nonce,
                    "ciphertext": self.envelope.ciphertext,
                }
            )
        if "media_activate(" in query:
            assert self.phase == "CLAIMED"
            self.phase = "NEGOTIATING"
            return Result(self.view)
        if "media_observe(" in query:
            return Result(
                self.view
                if self.allowed and self.phase in {"NEGOTIATING", "PLAYING"}
                else None
            )
        raise AssertionError("unexpected synthetic SQL operation")

    def dispose(self):
        assert self.checked_out == 0


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(windows, "PENDING_OWNERS", [])
    gate = SqlMuxAdmission("postgresql+psycopg://unused", Key())
    gate._engine.dispose()
    scope = MuxScopeKey(
        uuid4(),
        1,
        uuid4(),
        b"s" * 32,
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        uuid4(),
        1,
        gate.worker_epoch,
    )
    credentials = LocalDeviceCredentials(
        serial="synthetic9", country="KR", username="inert", password="inert"
    )
    sql = PhaseSQL(scope, credentials, gate._cipher)
    gate._engine = sql
    lease = gate.redeem("a" * 64, budget=LocalVerifyBudget(1000))
    originals = MuxOriginalBudget(worker_epoch=gate.worker_epoch)
    monkeypatch.setattr(windows.ProviderConfig, "__post_init__", lambda self: None)
    config = windows.ProviderConfig(
        Path("X:/inert"), Path("X:/inert"), Path("X:/inert"), 5
    )
    provider = NativeLocalMuxProvider(
        windows.WindowsSocketProvider(mux_config=config),
        budget=originals,
        admission=gate,
    )
    registration = uuid4()
    prepared = provider.prepare_dedicated(
        lease, scope, originals.reserve("main"), registration
    )
    gate.register_dedicated(
        lease,
        prepared.native_issuer,
        prepared.viewer_issuer,
        registration=registration,
        budget=LocalVerifyBudget(1000),
    )
    selected = gate.prepare_viewer(lease, budget=LocalVerifyBudget(1000))
    decrypted, channel = gate.prepare_dedicated(lease, budget=LocalVerifyBudget(1000))
    assert channel == selected and sql.phase == "CLAIMED" and sql.checked_out == 0
    try:
        yield gate, sql, prepared, decrypted, channel
    finally:
        receipt = prepared.close_native()
        assert receipt is prepared.native_issuer.issued_receipt()
        assert prepared.owner.child is prepared.owner.job is None
        assert prepared._raw_credit is None
        assert not windows.pending_owner_snapshot()
        assert sql.checked_out == 0


def test_claimed_dedicated_start_reaches_native_review_without_hot_observe(
    rig, monkeypatch
):
    """Using activated current for startup fails before the native review gate."""
    gate, sql, prepared, credentials, channel = rig
    reached = []

    def stop_before_native_resources(config):
        reached.append(sql.checked_out)
        raise windows.ProviderError()

    monkeypatch.setattr(windows, "verify_review", stop_before_native_resources)
    with pytest.raises(LocalDeviceFailure):
        prepared.start(credentials, channel, budget=LocalVerifyBudget(1000))
    assert reached == [0]
    assert not gate._authorities
    assert not any("media_observe(" in query for query in sql.calls)


def test_startup_authority_does_not_activate_or_seed_live_cache(rig):
    gate, sql, prepared, _, channel = rig
    assert gate.current_dedicated_startup(
        prepared.lease, prepared.registration, channel, budget=LocalVerifyBudget(1000)
    )
    assert sql.phase == "CLAIMED" and not gate._authorities
    proof = LocalLiveProof(True, True, True, True, True)
    assert (
        gate.activate(prepared.lease, proof, budget=LocalVerifyBudget(1000)).state
        == "NEGOTIATING"
    )
    assert gate.current(prepared.lease)
    # Revocation must remain sticky even after the SQL model becomes valid again.
    sql.allowed = False
    entry = gate._authorities[prepared.lease.token]
    entry.valid_until = 0
    assert gate.current(prepared.lease) is False
    sql.allowed = True
    assert gate.current(prepared.lease) is False


@pytest.mark.parametrize(
    "denial",
    [
        "foreign",
        "registration",
        "selection",
        "sub",
        "scope",
        "revoked",
        "cancel",
        "expired",
        "custody_closed",
        "hot_denied",
    ],
)
def test_startup_rejects_invalid_authority_before_native_resources(
    rig, monkeypatch, denial
):
    gate, sql, prepared, credentials, channel = rig
    request = LocalVerifyBudget(1000)
    if denial == "foreign":
        prepared.lease = replace(prepared.lease)
    elif denial == "registration":
        prepared.registration = uuid4()
    elif denial == "selection":
        channel = replace(channel, ordinal=2)
    elif denial == "sub":
        channel = replace(channel, stream="sub")
    elif denial == "scope":
        record = gate._dedicated[prepared.lease.id]
        gate._dedicated[prepared.lease.id] = replace(
            record, scope=replace(record.scope, worker_epoch=uuid4())
        )
    elif denial == "revoked":
        sql.allowed = False
    elif denial == "cancel":
        request.cancel.set()
    elif denial == "expired":
        request.deadline_monotonic = time.monotonic() - 1
    elif denial == "custody_closed":
        assert prepared.close_native() is not None
    else:
        assert gate.current(prepared.lease) is False  # CLAIMED hot denial is sticky.
    reached = []
    monkeypatch.setattr(windows, "verify_review", lambda config: reached.append(True))
    with pytest.raises((LocalDeviceFailure, windows.ProviderError)):
        prepared.start(credentials, channel, budget=request)
    assert not reached


@pytest.mark.parametrize(
    "denial", ["cancel", "expired", "retired", "custody", "issuer", "closed"]
)
def test_startup_rechecks_custody_and_budget_after_short_sql_checkout(rig, denial):
    gate, sql, prepared, _, channel = rig
    request = LocalVerifyBudget(1000)

    def after_selection():
        if denial == "cancel":
            request.cancel.set()
        elif denial == "expired":
            request.deadline_monotonic = time.monotonic() - 1
        elif denial == "retired":
            gate._retire_authority(prepared.lease.token)
        elif denial == "custody":
            record = gate._dedicated[prepared.lease.id]
            gate._dedicated[prepared.lease.id] = replace(record)
        elif denial == "issuer":
            prepared.viewer_issuer.issued_receipt = lambda: None
        else:
            prepared.viewer_issuer.receipt = object()

    sql.during_selection = after_selection
    with pytest.raises(LocalDeviceFailure):
        gate.current_dedicated_startup(
            prepared.lease, prepared.registration, channel, budget=request
        )
    assert sql.checked_out == 0


def inert_reaped_receipt(prepared):
    """Model a native REAPED receipt; no child is launched by this fixture."""
    receipt = prepared.close_native()
    prepared.custodian._receipt = replace(
        receipt, original_state="REAPED", _seal=_CUSTODY_SEAL
    )
    return prepared.custodian._receipt


def test_original_login_busy_readback_uses_exact_retired_native_receipt(
    rig, monkeypatch
):
    gate, sql, prepared, credentials, channel = rig
    close = prepared.close_native

    def native_login_busy(config, request, *, service, current):
        assert service.check(current)
        service.failure = "protocol"
        return windows.SafeResult("1" * 32, failure="rejected")

    def reaped():
        receipt = close()
        prepared.custodian._receipt = replace(
            receipt, original_state="REAPED", _seal=_CUSTODY_SEAL
        )
        return prepared.custodian._receipt

    monkeypatch.setattr(prepared.native, "run", native_login_busy)
    monkeypatch.setattr(prepared, "close_native", reaped)
    monkeypatch.setattr(prepared.native, "recover_retired_login_busy", lambda: object())
    with pytest.raises(LocalDeviceFailure) as raised:
        prepared.start(credentials, channel, budget=LocalVerifyBudget(1000))
    assert (raised.value.code, raised.value.status) == ("LOCAL_DEVICE_BUSY", 429)
    assert not gate._authorities and sql.checked_out == 0


@pytest.mark.parametrize(
    "receipt_kind", ["exact", "missing", "copied", "foreign", "not_created"]
)
def test_retired_native_readback_cannot_authorize_normal_startup(rig, receipt_kind):
    gate, _, prepared, _, channel = rig
    not_created = prepared.close_native()
    receipt = inert_reaped_receipt(prepared)
    if receipt_kind == "missing":
        receipt = None
    elif receipt_kind == "copied":
        receipt = replace(receipt, _seal=_CUSTODY_SEAL)
    elif receipt_kind == "foreign":
        receipt = replace(receipt, master_id=uuid4(), _seal=_CUSTODY_SEAL)
    elif receipt_kind == "not_created":
        prepared.custodian._receipt = receipt = not_created
    if receipt_kind == "exact":
        assert gate.current_dedicated_startup(
            prepared.lease,
            prepared.registration,
            channel,
            budget=LocalVerifyBudget(1000),
            retired_native_receipt=receipt,
        )
        with pytest.raises(LocalDeviceFailure):
            gate.current_dedicated_startup(
                prepared.lease,
                prepared.registration,
                channel,
                budget=LocalVerifyBudget(1000),
            )
    else:
        with pytest.raises(LocalDeviceFailure):
            gate.current_dedicated_startup(
                prepared.lease,
                prepared.registration,
                channel,
                budget=LocalVerifyBudget(1000),
                retired_native_receipt=receipt,
            )
