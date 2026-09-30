"""Coordinator boundaries; no provider acceptance is inferred from these tests."""

import importlib
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


def lifecycle():
    try:
        return importlib.import_module("wso_core.assets")
    except ModuleNotFoundError:
        pytest.fail("asset lifecycle boundary is missing", pytrace=False)


def test_admission_has_no_wait_queue_and_release_is_idempotent():
    assets = lifecycle()
    controller = assets.AssetAdmissionController(upload_slots=1, read_slots=1)
    permit = controller.try_acquire(kind="UPLOAD")
    with pytest.raises(assets.AssetAdmissionRejected) as rejected:
        controller.try_acquire(kind="UPLOAD")
    assert rejected.value.code == "BUSY"
    permit.release(cleanup_complete=True)
    permit.release(cleanup_complete=True)
    controller.try_acquire(kind="UPLOAD")
    with pytest.raises(assets.AssetAdmissionRejected):
        controller.try_acquire(kind="UPLOAD")


def test_unreaped_local_resource_closes_all_admission():
    assets = lifecycle()
    controller = assets.AssetAdmissionController(upload_slots=2, read_slots=2)
    controller.try_acquire(kind="READ").release(cleanup_complete=False)
    for kind in ("READ", "UPLOAD"):
        with pytest.raises(assets.AssetAdmissionRejected) as rejected:
            controller.try_acquire(kind=kind)
        assert rejected.value.code == "UNAVAILABLE"


def test_admission_retirement_is_atomic_with_acquisition():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    assets = lifecycle()
    controller = assets.AssetAdmissionController(upload_slots=1, read_slots=1)
    barrier = Barrier(2)

    def acquire():
        barrier.wait(timeout=2)
        try:
            return controller.try_acquire(kind="READ")
        except assets.AssetAdmissionRejected as rejected:
            return rejected.code

    def retire():
        barrier.wait(timeout=2)
        return controller.retire_if_idle()

    with ThreadPoolExecutor(max_workers=2) as pool:
        acquisition = pool.submit(acquire)
        retirement = pool.submit(retire)
        permit, retired = acquisition.result(timeout=3), retirement.result(timeout=3)
    if retired:
        assert permit == "UNAVAILABLE" and controller.active_count == 0
    else:
        assert not isinstance(permit, str) and controller.active_count == 1
        assert controller.retire_if_idle() is False
        permit.release(cleanup_complete=True)
        assert controller.retire_if_idle() is True
    with pytest.raises(assets.AssetAdmissionRejected):
        controller.try_acquire(kind="UPLOAD")


def test_actor_identity_validates_digest_and_hides_it_from_repr():
    assets = lifecycle()
    values = {
        "tenant_id": uuid4(),
        "user_id": uuid4(),
        "session_digest": "a" * 64,
        "session_expires_at": datetime.now(UTC) + timedelta(minutes=1),
        "correlation_id": "request",
    }
    assert values["session_digest"] not in repr(assets.AssetActor(**values))
    with pytest.raises(ValueError):
        assets.AssetActor(**{**values, "session_digest": "forged"})


def test_configuration_conversion_rejects_absent_namespace_and_boolean_policy():
    assets = lifecycle()
    from dataclasses import asdict

    from wso_core.storage import AssetPolicy

    class Result:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def all(self):
            return [self.row]

    class Database:
        def __init__(self, row):
            self.row = row

        def execute(self, _):
            return Result(self.row)

    row = {
        "installation_id": uuid4(),
        "bucket": "owned-assets",
        **asdict(AssetPolicy(version=1)),
    }
    converted = assets.read_asset_runtime_configuration(Database(row))
    assert converted.namespace.installation_id == row["installation_id"]
    for changes in ({"installation_id": None}, {"max_bytes": True}, {"unexpected": 1}):
        with pytest.raises(assets.AssetFailure) as failure:
            assets.read_asset_runtime_configuration(Database({**row, **changes}))
        assert failure.value.code == "ASSET_CONFIGURATION_UNAVAILABLE"


def test_validation_closes_claim_transaction_before_storage_and_rechecks_before_ready(
    monkeypatch,
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from wso_core.storage import (
        AssetAAD,
        AssetLease,
        AssetPolicy,
        Envelope,
        ImageInfo,
        InstallationNamespace,
        ObjectLocator,
        ReadManifest,
        VerifiedPlaintext,
        WrappedKey,
    )

    assets = lifecycle()
    trace = []
    active = False
    tenant, identifier, attempt = uuid4(), uuid4(), uuid4()
    namespace = InstallationNamespace(uuid4(), "owned-assets")
    policy = AssetPolicy(version=1)
    manifest = ReadManifest(
        "VALIDATE",
        ObjectLocator(namespace.installation_id, tenant, identifier, attempt),
        AssetAAD(
            tenant,
            identifier,
            attempt,
            None,
            None,
            "IMPORT_PHOTO",
            9,
            "image/png",
            "a" * 64,
        ),
        Envelope("test", WrappedKey(b"a" * 12, b"b" * 48), b"c" * 12),
        AssetLease(
            uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30), 30000, "d" * 64
        ),
        1,
        None,
        1,
    )

    @contextmanager
    def transactions(action, *, deadline_monotonic):
        nonlocal active
        assert not active
        active = True
        trace.append("transaction")
        try:
            yield SimpleNamespace(execute=lambda *_: None)
        finally:
            active = False
            trace.append("closed")

    class Repository:
        def __init__(self, *_):
            pass

        def begin_validation(self, asset_id):
            assert active and asset_id == identifier
            trace.append("claim")
            return manifest

        def finish_validation(self, value, receipt):
            assert active and receipt.byte_size == 9
            trace.append("finish")
            return "ready"

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            trace.append("reader_closed")

        def read(self, _):
            return b""

    def get(*args, **kwargs):
        assert not active
        trace.append("get")
        return Reader()

    def decrypt(*args, **kwargs):
        assert not active
        trace.append("decrypt")
        return VerifiedPlaintext(b"123456789", 9, "a" * 64)

    def validate(*args, **kwargs):
        assert not active
        trace.append("decode")
        return ImageInfo("image/png", 1, 1, 1, 1, 1)

    monkeypatch.setattr(assets, "_AssetRepository", Repository, raising=False)
    monkeypatch.setattr(
        assets,
        "read_asset_runtime_configuration",
        lambda _: assets.AssetRuntimeConfiguration(namespace, policy),
    )
    store = assets.AssetStore(
        actor=assets.AssetActor(
            tenant, uuid4(), "f" * 64, datetime.now(UTC) + timedelta(minutes=5), "test"
        ),
        transactions=transactions,
        budget=assets.IOBudget(time.monotonic() + 30),
        objects=SimpleNamespace(
            namespace=namespace, get=get, local_cleanup_complete=lambda: True
        ),
        cipher=SimpleNamespace(decrypt_verified=decrypt),
        images=SimpleNamespace(validate=validate),
        policy=policy,
        admission=assets.AssetAdmissionController(upload_slots=1, read_slots=1),
        on_event=None,
    )
    assert store.complete_upload(identifier) == "ready"
    assert trace == [
        "transaction",
        "claim",
        "closed",
        "get",
        "decrypt",
        "reader_closed",
        "decode",
        "transaction",
        "finish",
        "closed",
    ]
    assert store.admission.active_count == 0


@pytest.mark.asyncio
async def test_busy_upload_does_not_consume_body_or_claim_write():
    from types import SimpleNamespace

    assets = lifecycle()
    controller = assets.AssetAdmissionController(upload_slots=1, read_slots=1)
    controller.try_acquire(kind="UPLOAD")
    store = SimpleNamespace(admission=controller)

    async def chunks():
        pytest.fail("busy gateway consumed request body")
        yield b"never"

    with pytest.raises(assets.AssetAdmissionRejected) as rejected:
        await assets.AssetGateway(store=store).put_content(
            uuid4(),
            uuid4(),
            chunks(),
            content_type="image/png",
            content_length=1,
            content_encoding=None,
        )
    assert rejected.value.code == "BUSY"


def test_busy_download_does_not_redeem_ticket():
    from types import SimpleNamespace

    assets = lifecycle()
    controller = assets.AssetAdmissionController(upload_slots=1, read_slots=1)
    controller.try_acquire(kind="READ")
    with pytest.raises(assets.AssetAdmissionRejected) as rejected:
        assets.AssetGateway(store=SimpleNamespace(admission=controller)).open_download(
            uuid4(), "a" * 64
        )
    assert rejected.value.code == "BUSY"


def test_maintenance_commits_one_claim_before_io_and_finishes_before_next_claim():
    from contextlib import contextmanager
    from types import SimpleNamespace

    from wso_core.storage import InstallationNamespace, MultipartPage, ObjectPage

    try:
        from wso_core.retention import AssetMaintenance
    except ModuleNotFoundError:
        pytest.fail("maintenance lifecycle is missing", pytrace=False)
    namespace = InstallationNamespace(uuid4(), "owned-assets")
    row = {
        "work_id": uuid4(),
        "installation_id": namespace.installation_id,
        "tenant_id": uuid4(),
        "asset_id": uuid4(),
        "attempt_id": uuid4(),
        "operation": "DELETE_OBJECT",
        "multipart_id": None,
        "lease_id": uuid4(),
        "lease_generation": 1,
        "lease_expires_at": datetime.now(UTC) + timedelta(seconds=30),
        "lease_remaining_ms": 30000,
        "lease_token": "a" * 64,
    }
    active = False
    claimed = False
    finished = False

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def mappings(self):
            return self

        def all(self):
            return self.value

    class Database:
        def execute(self, sql, params=None):
            nonlocal claimed, finished
            statement = str(sql)
            if "current_user" in statement:
                return Result("wso_asset_maintenance")
            if "wso_flush_asset_audits" in statement:
                return Result(0)
            if "wso_sweep_assets" in statement:
                return Result(0)
            if "wso_claim_asset_cleanup" in statement:
                assert params["limit"] == 1
                if claimed:
                    assert finished
                    return Result([])
                claimed = True
                return Result([row])
            if "wso_finish_asset_cleanup" in statement:
                finished = True
                return Result(True)
            pytest.fail("unexpected maintenance control")

    @contextmanager
    def transactions():
        nonlocal active
        assert not active
        active = True
        try:
            yield Database()
        finally:
            active = False

    def delete(*args, **kwargs):
        assert not active

    def objects(**kwargs):
        assert not active
        return ObjectPage((), None)

    def multiparts(**kwargs):
        assert not active
        return MultipartPage((), None)

    store = SimpleNamespace(
        namespace=namespace,
        delete=delete,
        list_objects=objects,
        list_multipart=multiparts,
        local_cleanup_complete=lambda: True,
    )
    runner = AssetMaintenance(
        transactions=transactions, objects=store, worker_id="test", on_event=None
    )
    assert runner.run_once(limit=2) == 1
    assert finished


@pytest.mark.asyncio
async def test_download_deadline_covers_blocked_asgi_send_and_closes_permit():
    import time

    import anyio
    from wso_api.assets.router import AssetDeadlineMiddleware, _DownloadResponse

    closed = False

    class Download:
        content_type = "image/png"
        byte_size = 1
        deadline_monotonic = time.monotonic() + 0.05

        def iter_bytes(self):
            yield b"x"

        def close(self):
            nonlocal closed
            closed = True

    download = Download()
    response = _DownloadResponse(download)

    async def receive():
        await anyio.sleep_forever()

    async def send(message):
        if message["type"] == "http.response.body":
            await anyio.sleep_forever()

    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "wso_asset_download_deadline": download.deadline_monotonic,
    }
    with pytest.raises(TimeoutError):
        await AssetDeadlineMiddleware(response)(scope, receive, send)
    assert closed and time.monotonic() - download.deadline_monotonic < 1


def test_cleanup_refuses_physical_delete_when_second_database_check_denies():
    import time
    from contextlib import contextmanager
    from types import SimpleNamespace

    from wso_core.retention import AssetMaintenance
    from wso_core.storage import (
        AssetLease,
        CleanupWork,
        InstallationNamespace,
        IOBudget,
        MultipartPage,
        ObjectEntry,
        ObjectLocator,
        ObjectPage,
        StorageFailure,
    )

    namespace = InstallationNamespace(uuid4(), "owned-assets")
    locator = ObjectLocator(namespace.installation_id, uuid4(), uuid4(), uuid4())
    work = CleanupWork(
        uuid4(),
        locator,
        "DELETE_OBJECT",
        None,
        AssetLease(
            uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30), 30000, "a" * 64
        ),
    )
    deleted = False

    class Database:
        def execute(self, statement, values=None):
            return SimpleNamespace(
                scalar_one=lambda: (
                    "wso_asset_maintenance"
                    if "current_user" in str(statement)
                    else False
                )
            )

    @contextmanager
    def transactions():
        yield Database()

    def delete(*args, **kwargs):
        nonlocal deleted
        deleted = True

    objects = SimpleNamespace(
        namespace=namespace,
        list_objects=lambda **_: ObjectPage(
            (ObjectEntry(locator, 1, datetime.now(UTC)),), None
        ),
        list_multipart=lambda **_: MultipartPage((), None),
        delete=delete,
    )
    runner = AssetMaintenance(
        transactions=transactions, objects=objects, worker_id="test", on_event=None
    )
    with pytest.raises(StorageFailure) as rejected:
        runner._perform(work, IOBudget(time.monotonic() + 10))
    assert rejected.value.code == "DENIED" and not deleted


def test_expired_download_close_skips_authorization_and_releases_local_resources():
    import time
    from threading import Lock
    from types import SimpleNamespace

    from wso_core.assets import AssetAdmissionController, VerifiedDownload
    from wso_core.storage import IOBudget

    gate = AssetAdmissionController(upload_slots=1, read_slots=1)
    download = object.__new__(VerifiedDownload)
    download._lock, download._closed, download._data = Lock(), False, b"secret"
    download._budget = IOBudget(time.monotonic() - 1)
    download._manifest = object()
    download._permit = gate.try_acquire(kind="READ")
    download._store = SimpleNamespace(
        objects=SimpleNamespace(local_cleanup_complete=lambda: True),
        _control=lambda *a, **k: pytest.fail(
            "expired close opened fresh authorization"
        ),
    )
    download.close()
    assert download._data == b"" and gate.active_count == 0


def test_expired_reject_skips_authorization_and_programmer_errors_propagate():
    import time

    from wso_core.assets import AssetStore
    from wso_core.storage import IOBudget

    store = object.__new__(AssetStore)

    def broken(*args, **kwargs):
        raise RuntimeError("programmer failure")

    store._control = broken
    store._reject(object(), "RETRY", budget=IOBudget(time.monotonic() - 1))
    with pytest.raises(RuntimeError, match="programmer failure"):
        store._reject(object(), "RETRY", budget=IOBudget(time.monotonic() + 5))


def test_control_rejects_expired_budget_before_transaction_and_releases_read_permit():
    import time
    from types import SimpleNamespace

    from wso_core.assets import AssetAdmissionController, AssetFailure, AssetStore
    from wso_core.storage import IOBudget

    store = object.__new__(AssetStore)
    store.budget = IOBudget(time.monotonic() - 1)
    store.admission = AssetAdmissionController(upload_slots=1, read_slots=1)
    store.objects = SimpleNamespace(local_cleanup_complete=lambda: True)
    store.transactions = lambda *a, **kw: pytest.fail("expired authorization started")
    with pytest.raises(AssetFailure) as failed:
        store.complete_upload(uuid4())
    assert failed.value.status == 503 and store.admission.active_count == 0


def test_route_authorization_keeps_original_deadline_and_shares_controls(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from wso_api.assets import router as route_module
    from wso_api.auth import SESSION_COOKIE
    from wso_core.db_budget import AuthorizationDbFactories
    from wso_core.storage import IOBudget

    clock = [100.0]
    monkeypatch.setattr(route_module.time, "monotonic", lambda: clock[0])
    from wso_core import db_budget

    monkeypatch.setattr(db_budget, "monotonic", lambda: clock[0])
    controls_seen = []
    principal = SimpleNamespace(
        user_id=uuid4(), expires_at=datetime.now(UTC) + timedelta(minutes=5)
    )

    def authenticate(request, *, db_controls):
        controls_seen.append(db_controls)
        clock[0] += 1
        return principal

    @contextmanager
    def require_tenant(*args, db_controls, **kwargs):
        assert db_controls is controls_seen[-1]
        yield SimpleNamespace(session="actual-session-placeholder")

    factories = AuthorizationDbFactories(None, None, None, None)
    monkeypatch.setattr(
        route_module,
        "asset_runtime",
        lambda request: SimpleNamespace(authorization=factories),
    )
    monkeypatch.setattr(route_module, "require_tenant", require_tenant)
    request = SimpleNamespace(
        cookies={SESSION_COOKIE: "opaque-cookie"},
        state=SimpleNamespace(request_id="test"),
    )
    _actor, transactions = route_module._authority(
        request,
        SimpleNamespace(authenticate=authenticate),
        uuid4(),
        mutation=False,
        budget=IOBudget(104),
    )
    with transactions("assets:read", deadline_monotonic=110) as session:
        assert session == "actual-session-placeholder"
    assert [item.deadline.deadline_monotonic for item in controls_seen] == [104, 104]
    clock[0] = 105
    with (
        pytest.raises(route_module.AssetFailure) as failed,
        transactions("assets:read", deadline_monotonic=110),
    ):
        pytest.fail("expired callback yielded")
    assert failed.value.status == 503 and len(controls_seen) == 2


@pytest.mark.asyncio
async def test_stalled_upload_receive_obeys_shorter_sql_lease_and_releases_permit():
    from types import SimpleNamespace

    import anyio
    from wso_core.assets import AssetAdmissionController, AssetFailure, AssetGateway
    from wso_core.storage import IOBudget

    closed = False
    gate = AssetAdmissionController(upload_slots=1, read_slots=1)

    class Stream:
        def header(self):
            return b""

        def close(self):
            nonlocal closed
            closed = True

    def control(action, method, *args, budget):
        if method == "prepare_write":
            return SimpleNamespace(
                aad=SimpleNamespace(content_type="image/png", byte_size=9)
            )
        if method == "begin_write":
            return SimpleNamespace(lease=SimpleNamespace(remaining_ms=100))
        pytest.fail("unexpected control")

    store = SimpleNamespace(
        admission=gate,
        budget=IOBudget(time.monotonic() + 1),
        policy=SimpleNamespace(upload_seconds=120),
        objects=SimpleNamespace(local_cleanup_complete=lambda: True),
        cipher=SimpleNamespace(
            prepare=lambda _: SimpleNamespace(envelope=object()),
            start=lambda _: Stream(),
        ),
        _control=control,
        _event=lambda *a: None,
        _reject=lambda *a, **k: None,
    )

    async def body():
        await anyio.sleep_forever()
        yield b"never"

    started = time.monotonic()
    with pytest.raises(AssetFailure) as failed, anyio.fail_after(0.5):
        await AssetGateway(store=store).put_content(
            uuid4(),
            uuid4(),
            body(),
            content_type="image/png",
            content_length=9,
            content_encoding=None,
        )
    assert failed.value.code == "ASSET_DEADLINE"
    assert time.monotonic() - started < 0.4 and closed and gate.active_count == 0
