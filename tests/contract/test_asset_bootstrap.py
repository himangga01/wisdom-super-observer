"""Startup wiring shares actual gates and never creates a runtime on request."""

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from wso_api.assets.bootstrap import AssetRuntime, asset_runtime, configure_assets
from wso_core.asset_crypto import AssetCipher
from wso_core.asset_images import ImageValidator
from wso_core.assets import (
    AssetActor,
    AssetAdmissionController,
    AssetAdmissionRejected,
    AssetFailure,
    AssetRuntimeConfiguration,
)
from wso_core.db_budget import AuthorizationDbFactories, create_budgeted_provider
from wso_core.storage import (
    AssetPolicy,
    InstallationNamespace,
    IOBudget,
    S3Credentials,
    S3ObjectStore,
    S3RuntimeConfig,
    SpawnS3Client,
)


def runtime():
    namespace = InstallationNamespace(UUID(int=1), "private-unit-bucket")
    policy = AssetPolicy(version=7)
    objects = S3ObjectStore(
        client=SpawnS3Client(
            config=S3RuntimeConfig(
                endpoint_url="https://storage.example.test",
                region="us-east-1",
                credentials=S3Credentials("unit-access", "unit-secret"),
                namespace=namespace,
            )
        ),
        namespace=namespace,
    )
    # Constructor-only test: no encryption is requested and no key is read.
    cipher = AssetCipher(None)
    return AssetRuntime(
        configuration=AssetRuntimeConfiguration(namespace, policy),
        objects=objects,
        cipher=cipher,
        images=ImageValidator(policy=policy),
        admission=AssetAdmissionController(upload_slots=2, read_slots=2),
        on_event=None,
        authorization=AuthorizationDbFactories(
            **{
                name: create_budgeted_provider(
                    "postgresql+psycopg://wso_app:unit@127.0.0.1/wso",
                    null_pool=name == "redemption",
                )
                for name in ("web_session", "identity", "tenant", "redemption")
            }
        ),
    )


def forbidden_transaction(action):
    pytest.fail("facade construction opened a transaction")


def actor():
    return AssetActor(
        tenant_id=UUID(int=2),
        user_id=UUID(int=3),
        session_digest="a" * 64,
        session_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id="bootstrap-unit",
    )


def request(app):
    return Request({"type": "http", "app": app})


def test_facades_share_dependency_and_gate_identity_without_io():
    installed = runtime()
    budget = IOBudget(time.monotonic() + 30)
    first = installed.store_for(
        actor=actor(), transactions=forbidden_transaction, budget=budget
    )
    second = installed.gateway_for(
        actor=actor(), transactions=forbidden_transaction, budget=budget
    )
    for facade in (first, second.store):
        assert facade.admission is installed.admission
        assert facade.objects is installed.objects
        assert facade.cipher is installed.cipher
        assert facade.images is installed.images
        assert facade.policy is installed.configuration.policy
        assert facade.on_event is None
    held = [first.admission.try_acquire(kind="READ") for _ in range(2)]
    with pytest.raises(AssetAdmissionRejected) as busy:
        second.store.admission.try_acquire(kind="READ")
    assert busy.value.code == "BUSY"
    for permit in held:
        permit.release(cleanup_complete=True)


def test_runtime_lookup_fails_closed_without_lazy_initialization():
    app = FastAPI()
    for _ in range(2):
        with pytest.raises(AssetFailure) as unavailable:
            asset_runtime(request(app))
        assert unavailable.value.status == 503
        assert unavailable.value.code == "ASSET_CONFIGURATION_UNAVAILABLE"
        assert not hasattr(app.state, "asset_runtime")
    configure_assets(app, runtime=None)
    with pytest.raises(AssetFailure):
        asset_runtime(request(app))


def test_registration_returns_same_instance_and_refuses_active_replacement():
    app = FastAPI()
    original = runtime()
    configure_assets(app, runtime=original)
    assert asset_runtime(request(app)) is original
    held = original.admission.try_acquire(kind="UPLOAD")
    configure_assets(app, runtime=original)
    for replacement in (None, runtime()):
        with pytest.raises(AssetFailure):
            configure_assets(app, runtime=replacement)
        assert asset_runtime(request(app)) is original
    held.release(cleanup_complete=True)
    replacement = runtime()
    configure_assets(app, runtime=replacement)
    assert asset_runtime(request(app)) is replacement


def test_terminal_cleanup_permit_cannot_be_replaced_in_same_process():
    app = FastAPI()
    original = runtime()
    configure_assets(app, runtime=original)
    original.admission.try_acquire(kind="UPLOAD").release(cleanup_complete=False)
    with pytest.raises(AssetFailure):
        configure_assets(app, runtime=runtime())
    assert asset_runtime(request(app)) is original
