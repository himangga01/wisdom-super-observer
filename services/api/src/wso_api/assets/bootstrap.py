"""Explicit startup and process-wide private asset runtime wiring."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from wso_core.asset_crypto import AssetCipher, AssetCryptoFailure, LocalAssetKeyProvider
from wso_core.asset_images import ImageValidator
from wso_core.assets import (
    AssetActor,
    AssetAdmissionController,
    AssetAdmissionRejected,
    AssetEventCallback,
    AssetFailure,
    AssetGateway,
    AssetRuntimeConfiguration,
    AssetStore,
    AuthorizedTransactions,
    read_asset_runtime_configuration,
)
from wso_core.db_budget import (
    AuthorizationDbFactories,
    DbDeadline,
    DbUnavailable,
    create_budgeted_provider,
)
from wso_core.retention import AssetMaintenance
from wso_core.storage import (
    IOBudget,
    PrivateObjectStore,
    S3ClientProtocol,
    S3Command,
    S3ObjectStore,
    S3Operation,
    S3Result,
    SpawnS3Client,
    StorageFailure,
)

from wso_api.assets.settings import (
    AssetMaintenanceSettings,
    AssetSettings,
    load_asset_maintenance_settings,
    load_asset_settings,
)

__all__ = [
    "AssetMaintenanceSettings",
    "AssetRuntime",
    "AssetSettings",
    "asset_runtime",
    "configure_assets",
    "load_asset_maintenance_settings",
    "load_asset_settings",
    "start_asset_maintenance",
    "start_asset_runtime",
]

_registration_lock = RLock()


@dataclass(frozen=True, slots=True)
class AssetRuntime:
    configuration: AssetRuntimeConfiguration
    objects: PrivateObjectStore = field(repr=False)
    cipher: AssetCipher = field(repr=False)
    images: ImageValidator = field(repr=False)
    admission: AssetAdmissionController = field(repr=False)
    on_event: AssetEventCallback | None = field(repr=False)
    authorization: AuthorizationDbFactories = field(repr=False)

    def store_for(
        self,
        *,
        actor: AssetActor,
        transactions: AuthorizedTransactions,
        budget: IOBudget,
    ) -> AssetStore:
        return AssetStore(
            actor=actor,
            transactions=transactions,
            objects=self.objects,
            cipher=self.cipher,
            images=self.images,
            policy=self.configuration.policy,
            admission=self.admission,
            on_event=self.on_event,
            budget=budget,
        )

    def gateway_for(
        self,
        *,
        actor: AssetActor,
        transactions: AuthorizedTransactions,
        budget: IOBudget,
    ) -> AssetGateway:
        return AssetGateway(
            store=self.store_for(actor=actor, transactions=transactions, budget=budget)
        )


def configure_assets(app: FastAPI, *, runtime: AssetRuntime | None) -> None:
    app.add_exception_handler(AssetFailure, _asset_failure)
    app.add_exception_handler(AssetAdmissionRejected, _asset_admission_failure)
    with _registration_lock:
        previous = getattr(app.state, "asset_runtime", None)
        if previous is runtime:
            return
        if previous is not None and (
            not isinstance(previous, AssetRuntime)
            or not previous.admission.retire_if_idle()
        ):
            raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
        app.state.asset_runtime = runtime


def asset_runtime(request: Request) -> AssetRuntime:
    runtime = getattr(request.app.state, "asset_runtime", None)
    if not isinstance(runtime, AssetRuntime):
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
    return runtime


def start_asset_runtime(
    *, settings: AssetSettings, on_event: AssetEventCallback | None = None
) -> AssetRuntime:
    try:
        startup = create_budgeted_provider(
            settings.app_database_url, null_pool=True, hostaddr=settings.db_hostaddr
        )
        try:
            with startup(deadline=DbDeadline(monotonic() + 5)) as session:
                configuration = _configuration(session, "wso_app")
                if configuration.namespace != settings.s3.namespace:
                    raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
        finally:
            startup.dispose()
    except (SQLAlchemyError, DbUnavailable, ValueError):
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None
    try:
        provider = LocalAssetKeyProvider(
            active_key_id=settings.active_key_id, key_files=settings.key_files
        )
        return AssetRuntime(
            configuration=configuration,
            objects=S3ObjectStore(
                client=SpawnS3Client(config=settings.s3),
                namespace=configuration.namespace,
            ),
            cipher=AssetCipher(provider),
            images=ImageValidator(policy=configuration.policy),
            admission=AssetAdmissionController(upload_slots=2, read_slots=2),
            on_event=on_event,
            authorization=AuthorizationDbFactories(
                web_session=create_budgeted_provider(
                    settings.session_database_url, hostaddr=settings.db_hostaddr
                ),
                identity=create_budgeted_provider(
                    settings.identity_database_url, hostaddr=settings.db_hostaddr
                ),
                tenant=create_budgeted_provider(
                    settings.app_database_url, hostaddr=settings.db_hostaddr
                ),
                redemption=create_budgeted_provider(
                    settings.app_database_url,
                    null_pool=True,
                    hostaddr=settings.db_hostaddr,
                ),
            ),
        )
    except (AssetCryptoFailure, TypeError, ValueError):
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None


def _configuration(session: Session, role: str) -> AssetRuntimeConfiguration:
    if session.execute(text("SELECT current_user")).scalar_one() != role:
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
    return read_asset_runtime_configuration(session)


def start_asset_maintenance(
    *, settings: AssetMaintenanceSettings, on_event: AssetEventCallback | None = None
) -> AssetMaintenance:
    try:
        provider = create_budgeted_provider(
            settings.maintenance_database_url,
            null_pool=True,
            hostaddr=settings.db_hostaddr,
        )
    except ValueError:
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None
    try:
        with provider(deadline=DbDeadline(monotonic() + 5)) as session:
            configuration = _configuration(session, "wso_asset_maintenance")
            if configuration.namespace != settings.s3.namespace:
                raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
    except (SQLAlchemyError, DbUnavailable, AssetFailure):
        provider.dispose()
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None

    @contextmanager
    def transactions() -> Iterator[Session]:
        try:
            with provider(deadline=DbDeadline(monotonic() + 5)) as session:
                if _configuration(session, "wso_asset_maintenance") != configuration:
                    raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
                yield session
        except (SQLAlchemyError, DbUnavailable):
            raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None

    return AssetMaintenance(
        transactions=transactions,
        objects=S3ObjectStore(
            client=_MaintenanceS3Client(SpawnS3Client(config=settings.s3)),
            namespace=configuration.namespace,
        ),
        worker_id=settings.worker_id,
        on_event=on_event,
    )


class _MaintenanceS3Client:
    """Key-free transport facade with a fixed local maintenance capability set."""

    def __init__(self, client: S3ClientProtocol) -> None:
        self._client = client

    def local_cleanup_complete(self) -> bool:
        return self._client.local_cleanup_complete()

    def execute(
        self, op: S3Operation, args: S3Command, *, budget: IOBudget
    ) -> S3Result:
        if op not in {"DELETE", "LIST_OBJECTS", "LIST_MULTIPART", "ABORT_MULTIPART"}:
            raise StorageFailure("UNAVAILABLE")
        return self._client.execute(op, args, budget=budget)


_PUBLIC_CODES = frozenset(
    {
        "ASSET_AUTHENTICATION_REQUIRED",
        "ASSET_AUTHORIZATION_TIMEOUT",
        "ASSET_CONFIGURATION_UNAVAILABLE",
        "ASSET_CONFLICT",
        "ASSET_DEADLINE",
        "ASSET_DENIED",
        "ASSET_INTEGRITY",
        "ASSET_INVALID",
        "ASSET_LENGTH",
        "ASSET_LIMIT",
        "ASSET_LOCAL_CLEANUP_UNAVAILABLE",
        "ASSET_NOT_FOUND",
        "ASSET_TYPE",
        "ASSET_UNAVAILABLE",
        "ASSET_UPLOAD_EXPIRED",
        "CAPABILITY_UNSUPPORTED",
    }
)


async def _asset_failure(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, AssetFailure)
    known = error.code in _PUBLIC_CODES and error.status in {
        401,
        403,
        404,
        409,
        410,
        413,
        415,
        422,
        429,
        503,
    }
    return JSONResponse(
        status_code=error.status if known else 503,
        content={
            "error": {
                "code": error.code if known else "ASSET_UNAVAILABLE",
                "message": "Asset request failed",
            },
            "request_id": getattr(request.state, "request_id", None),
        },
        headers={"Cache-Control": "no-store", "Vary": "Cookie"},
    )


async def _asset_admission_failure(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, AssetAdmissionRejected)
    busy = error.code == "BUSY"
    return JSONResponse(
        status_code=429 if busy else 503,
        content={
            "error": {
                "code": "ASSET_BUSY" if busy else "ASSET_UNAVAILABLE",
                "message": "Asset request failed",
            },
            "request_id": getattr(request.state, "request_id", None),
        },
        headers={
            "Cache-Control": "no-store",
            "Vary": "Cookie",
            **({"Retry-After": "1"} if busy else {}),
        },
    )


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Private asset maintenance")
    parser.add_argument("command", choices=["maintenance"])
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    try:
        maintenance = start_asset_maintenance(
            settings=load_asset_maintenance_settings(os.environ)
        )
        if arguments.once:
            completed = maintenance.run_once()
            print(f"Private asset cleanup completed: {completed}")
        else:
            maintenance.run()
    except (AssetFailure, StorageFailure, ValueError):
        parser.exit(1, "Private asset maintenance unavailable.\n")


if __name__ == "__main__":
    main()
