"""Normal startup uses actual installed SQL configuration and protected keys."""

import os
import sys
import time
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from wso_api.assets import bootstrap
from wso_api.assets.settings import AssetMaintenanceSettings, AssetSettings
from wso_core.assets import AssetFailure
from wso_core.storage import (
    AssetAAD,
    InstallationNamespace,
    IOBudget,
    ObjectLocator,
    S3Credentials,
    S3RuntimeConfig,
    StorageFailure,
)

from tests.support.job_handlers import verify_fixture_database
from tests.support.secure_keys import secure_key


@pytest.fixture(scope="module")
def owned_database():
    url = os.environ.get("WSO_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("requires explicit owned PostgreSQL role URLs")
    engine = create_engine(url, hide_parameters=True)
    verify_fixture_database(engine, domain_only=sys.platform == "win32")
    try:
        with engine.begin() as db:
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_asset_runtime_configuration()")
                )
                .mappings()
                .one()
            )
            if row["installation_id"] is None:
                db.execute(text("SET LOCAL ROLE wso_migrator"))
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:i,:b)"
                    ),
                    {
                        "i": UUID("8aef7c82-258d-4f72-8012-21bc64a1abb1"),
                        "b": "wso-owned-assets-test",
                    },
                )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def startup_settings(owned_database, tmp_path):
    with owned_database.connect() as db:
        row = (
            db.execute(text("SELECT * FROM public.wso_asset_runtime_configuration()"))
            .mappings()
            .one()
        )
    return AssetSettings(
        app_database_url=os.environ["WSO_TEST_APP_DATABASE_URL"],
        identity_database_url=os.environ["WSO_TEST_IDENTITY_DATABASE_URL"],
        session_database_url=os.environ["WSO_TEST_SESSION_DATABASE_URL"],
        s3=S3RuntimeConfig(
            endpoint_url="https://storage.example.test",
            region="us-east-1",
            credentials=S3Credentials("startup-unit-access", "startup-unit-secret"),
            namespace=InstallationNamespace(row["installation_id"], row["bucket"]),
        ),
        active_key_id="K2",
        key_files={"K2": secure_key(tmp_path / "active.key", b"2" * 32)},
    )


def test_actual_startup_caches_every_sql_policy_field_and_forwards_callback(
    startup_settings, owned_database
):
    callback = [].append
    runtime = bootstrap.start_asset_runtime(
        settings=startup_settings, on_event=callback
    )
    with owned_database.connect() as db:
        row = (
            db.execute(text("SELECT * FROM public.wso_asset_runtime_configuration()"))
            .mappings()
            .one()
        )
    assert runtime.configuration.namespace == startup_settings.s3.namespace
    for key, expected in row.items():
        if key not in {"installation_id", "bucket"}:
            assert getattr(runtime.configuration.policy, key) == expected
    assert runtime.images.policy is runtime.configuration.policy
    assert runtime.objects.namespace is runtime.configuration.namespace
    prepared = runtime.cipher.prepare(
        AssetAAD(
            UUID(int=1),
            UUID(int=2),
            UUID(int=3),
            None,
            None,
            "IMPORT_PHOTO",
            1,
            "image/png",
            "a" * 64,
        )
    )
    assert prepared.envelope.key_id == "K2"
    assert runtime.on_event is callback


@pytest.mark.parametrize("foreign", ["installation", "bucket"])
def test_namespace_mismatch_rejects_before_key_provider_is_constructed(
    startup_settings, monkeypatch, foreign
):
    def forbidden_provider(**kwargs):
        pytest.fail("keys were loaded before SQL namespace matched")

    monkeypatch.setattr(bootstrap, "LocalAssetKeyProvider", forbidden_provider)
    namespace = startup_settings.s3.namespace
    replacement = InstallationNamespace(
        uuid4() if foreign == "installation" else namespace.installation_id,
        "foreign-private-bucket" if foreign == "bucket" else namespace.bucket,
    )
    settings = replace(
        startup_settings, s3=replace(startup_settings.s3, namespace=replacement)
    )
    with pytest.raises(AssetFailure) as denied:
        bootstrap.start_asset_runtime(settings=settings)
    assert denied.value.code == "ASSET_CONFIGURATION_UNAVAILABLE"


def test_missing_protected_key_fails_startup_without_secret_in_error(startup_settings):
    settings = replace(
        startup_settings,
        key_files={
            "K2": startup_settings.key_files["K2"].with_name("missing-private-key")
        },
    )
    with pytest.raises(AssetFailure) as denied:
        bootstrap.start_asset_runtime(settings=settings)
    assert denied.value.status == 503
    assert "startup-unit-secret" not in str(denied.value)
    assert "missing-private-key" not in str(denied.value)


def test_actual_maintenance_startup_is_key_free_and_uses_exact_role(
    startup_settings, monkeypatch
):
    def forbidden_key_provider(**kwargs):
        pytest.fail("maintenance constructed an API key provider")

    monkeypatch.setattr(bootstrap, "LocalAssetKeyProvider", forbidden_key_provider)
    settings = AssetMaintenanceSettings(
        maintenance_database_url=os.environ["WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"],
        s3=replace(
            startup_settings.s3,
            credentials=S3Credentials("maintenance-access", "maintenance-secret"),
        ),
        worker_id="maintenance-startup",
    )
    maintenance = bootstrap.start_asset_maintenance(settings=settings)
    with maintenance.transactions() as db:
        assert (
            db.execute(text("SELECT current_user")).scalar_one()
            == "wso_asset_maintenance"
        )
        statement, lock = db.execute(
            text(
                "SELECT extract(epoch FROM current_setting('statement_timeout')::interval)*1000, "
                "extract(epoch FROM current_setting('lock_timeout')::interval)*1000"
            )
        ).one()
        assert 0 < statement <= 5000
        assert 0 < lock <= 1000
    assert maintenance.on_event is None
    assert maintenance.objects.namespace == settings.s3.namespace
    locator = ObjectLocator(
        settings.s3.namespace.installation_id, UUID(int=1), UUID(int=2), UUID(int=3)
    )
    # Explicit local capability refusal happens without helper/network work.
    for operation in (
        lambda: maintenance.objects.get(
            locator, max_bytes=1, budget=IOBudget(time.monotonic() + 10)
        ),
        lambda: maintenance.objects.head(
            locator, budget=IOBudget(time.monotonic() + 10)
        ),
        lambda: maintenance.objects.presign(
            locator, expires_seconds=1, budget=IOBudget(time.monotonic() + 10)
        ),
    ):
        with pytest.raises(StorageFailure) as denied:
            operation()
        assert denied.value.code == "UNAVAILABLE"


@pytest.mark.parametrize("kind", ["api", "maintenance"])
def test_startup_refuses_ambient_libpq_configuration(
    startup_settings, monkeypatch, kind
):
    monkeypatch.setenv("PGAPPNAME", "ambient-startup-override")
    with pytest.raises(AssetFailure) as denied:
        if kind == "api":
            bootstrap.start_asset_runtime(settings=startup_settings)
        else:
            bootstrap.start_asset_maintenance(
                settings=AssetMaintenanceSettings(
                    maintenance_database_url=os.environ[
                        "WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"
                    ],
                    s3=startup_settings.s3,
                    worker_id="ambient-startup",
                )
            )
    assert denied.value.code == "ASSET_CONFIGURATION_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["api", "maintenance"])
def test_startup_uses_trusted_address_without_hostname_resolution(
    startup_settings, kind
):
    if kind == "api":
        url = make_url(startup_settings.app_database_url)
        assert url.host is not None
        settings = replace(
            startup_settings,
            app_database_url=url.set(
                host="unresolvable-startup.invalid"
            ).render_as_string(hide_password=False),
            db_hostaddr=url.host,
        )
        runtime = bootstrap.start_asset_runtime(settings=settings)
        assert runtime.configuration.namespace == startup_settings.s3.namespace
    else:
        url = make_url(os.environ["WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"])
        assert url.host is not None
        maintenance = bootstrap.start_asset_maintenance(
            settings=AssetMaintenanceSettings(
                maintenance_database_url=url.set(
                    host="unresolvable-startup.invalid"
                ).render_as_string(hide_password=False),
                db_hostaddr=url.host,
                s3=startup_settings.s3,
                worker_id="address-startup",
            )
        )
        with maintenance.transactions() as db:
            assert (
                db.execute(text("SELECT current_user")).scalar_one()
                == "wso_asset_maintenance"
            )
