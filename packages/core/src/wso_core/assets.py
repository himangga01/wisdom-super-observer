"""Private asset controls, with fresh transactions around each bounded operation."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from functools import partial
from threading import Lock
from types import TracebackType
from typing import Any, Literal, Protocol, Self, cast
from uuid import UUID

import anyio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from wso_contracts.assets import (
    Asset,
    AssetPurpose,
    BeginUpload,
    Checksum,
    DownloadTicket,
    UploadSession,
)
from wso_contracts.models import JobScope

from wso_core.asset_crypto import AssetCipher, AssetCryptoFailure
from wso_core.asset_images import ImageValidationFailure, ImageValidator
from wso_core.db_budget import DbUnavailable
from wso_core.storage import (
    AssetAAD,
    AssetLease,
    AssetPolicy,
    Envelope,
    InstallationNamespace,
    IOBudget,
    ObjectLocator,
    PrivateObjectStore,
    ReadManifest,
    StorageFailure,
    UploadPreparation,
    ValidationReceipt,
    VerifiedPlaintext,
    WrappedKey,
    WriteManifest,
    object_key,
)

_LOG = logging.getLogger(__name__)

AssetAction = Literal["assets:read", "assets:write"]
AdmissionKind = Literal["UPLOAD", "READ"]
AssetEventName = Literal[
    "UPLOAD_INTENT_COMMITTED",
    "MULTIPART_CREATED_BEFORE_RECORD",
    "OBJECT_COMPLETED_BEFORE_SEAL",
    "VALIDATED_BEFORE_FINALIZE",
    "DOWNLOAD_FIRST_CHUNK",
    "CLEANUP_EFFECT_BEFORE_ACK",
]


class AssetFailure(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status, self.code = status, code
        super().__init__(code)


class AssetAdmissionRejected(Exception):
    def __init__(self, code: Literal["BUSY", "UNAVAILABLE"]) -> None:
        self.code = code
        super().__init__(code)


class AssetPermit:
    def __init__(
        self, controller: AssetAdmissionController, kind: AdmissionKind
    ) -> None:
        self._controller, self._kind, self._released = controller, kind, False

    def release(self, *, cleanup_complete: bool) -> None:
        with self._controller._lock:
            if self._released:
                return
            self._released = True
            if cleanup_complete:
                self._controller._used[self._kind] -= 1
            else:
                self._controller._closed = True


class AssetAdmissionController:
    def __init__(self, *, upload_slots: int, read_slots: int) -> None:
        if any(
            type(n) is not int or n not in (1, 2) for n in (upload_slots, read_slots)
        ):
            raise ValueError("invalid asset admission capacity")
        self._limits = {"UPLOAD": upload_slots, "READ": read_slots}
        self._used = {"UPLOAD": 0, "READ": 0}
        self._closed = False
        self._lock = Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(self._used.values())

    def try_acquire(self, *, kind: AdmissionKind) -> AssetPermit:
        if kind not in self._limits:
            raise ValueError("invalid asset admission kind")
        with self._lock:
            if self._closed:
                raise AssetAdmissionRejected("UNAVAILABLE")
            if self._used[kind] >= self._limits[kind]:
                raise AssetAdmissionRejected("BUSY")
            self._used[kind] += 1
            return AssetPermit(self, kind)

    def close_admission(self) -> None:
        with self._lock:
            self._closed = True

    def retire_if_idle(self) -> bool:
        with self._lock:
            if any(self._used.values()):
                return False
            self._closed = True
            return True


@dataclass(frozen=True, slots=True)
class AssetEvent:
    name: AssetEventName
    asset_id: UUID
    work_id: UUID | None = None


AssetEventCallback = Callable[[AssetEvent], None]


@dataclass(frozen=True, slots=True)
class AssetActor:
    tenant_id: UUID
    user_id: UUID
    session_digest: str = field(repr=False)
    session_expires_at: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tenant_id, UUID)
            or not isinstance(self.user_id, UUID)
            or not re.fullmatch(r"[0-9a-f]{64}", self.session_digest)
            or self.session_expires_at.tzinfo is None
            or self.session_expires_at.utcoffset() is None
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", self.correlation_id)
        ):
            raise ValueError("invalid asset actor")


class AuthorizedTransactions(Protocol):
    def __call__(
        self, action: AssetAction, *, deadline_monotonic: float
    ) -> AbstractContextManager[Session]: ...


@dataclass(frozen=True, slots=True)
class AssetRuntimeConfiguration:
    namespace: InstallationNamespace
    policy: AssetPolicy


def _configuration(row: Mapping[str, Any]) -> AssetRuntimeConfiguration:
    names = {item.name for item in fields(AssetPolicy)}
    if (
        set(row) != names | {"installation_id", "bucket"}
        or not isinstance(row["installation_id"], UUID)
        or type(row["bucket"]) is not str
        or any(type(row[name]) is not int for name in names)
    ):
        raise ValueError("invalid configuration shape")
    return AssetRuntimeConfiguration(
        InstallationNamespace(row["installation_id"], row["bucket"]),
        AssetPolicy(**{name: row[name] for name in names}),
    )


def read_asset_runtime_configuration(session: Session) -> AssetRuntimeConfiguration:
    try:
        rows = (
            session.execute(
                text("SELECT * FROM public.wso_asset_runtime_configuration()")
            )
            .mappings()
            .all()
        )
        if len(rows) != 1:
            raise ValueError("invalid configuration count")
        return _configuration(dict(rows[0]))
    except (SQLAlchemyError, TypeError, ValueError, KeyError):
        raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE") from None


def _asset(row: Mapping[str, Any]) -> Asset:
    return Asset.model_validate(
        {
            key: row[key]
            for key in (
                "id",
                "tenant_id",
                "store_id",
                "purpose",
                "parent_asset_id",
                "state",
                "byte_size",
                "content_type",
                "expires_at",
                "created_at",
            )
        }
        | {"checksum": {"algorithm": "SHA256", "value": row["checksum_sha256"]}}
    )


def _aad(row: Mapping[str, Any]) -> AssetAAD:
    return AssetAAD(
        **{
            key: row[key]
            for key in (
                "tenant_id",
                "asset_id",
                "attempt_id",
                "store_id",
                "parent_asset_id",
                "purpose",
                "byte_size",
                "content_type",
                "checksum_sha256",
            )
        }
    )


def _lease(row: Mapping[str, Any]) -> AssetLease:
    return AssetLease(
        row["lease_id"],
        row["lease_generation"],
        _timestamp(row["lease_expires_at"]),
        row["lease_remaining_ms"],
        row["lease_token"],
    )


def _timestamp(value: Any) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("aware timestamp required")
    return value.astimezone(UTC)


def _binary(value: Any, length: int) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)) or len(value) != length:
        raise ValueError("invalid binary manifest field")
    return bytes(value)


def _manifest(
    row: Mapping[str, Any], *, write: bool = False
) -> WriteManifest | ReadManifest:
    try:
        locator = ObjectLocator(
            row["installation_id"], row["tenant_id"], row["asset_id"], row["attempt_id"]
        )
        if object_key(locator) != row["object_key"]:
            raise ValueError("locator mismatch")
        values = {
            "locator": locator,
            "aad": _aad(row),
            "envelope": Envelope(
                row["key_id"],
                WrappedKey(
                    _binary(row["wrap_nonce"], 12), _binary(row["wrapped_dek"], 48)
                ),
                _binary(row["object_nonce"], 12),
            ),
            "lease": _lease(row),
            "access_generation": row["access_generation"],
            "parent_access_generation": row["parent_access_generation"],
            "policy_version": row["policy_version"],
        }
        if write:
            return WriteManifest(upload_session_id=row["upload_session_id"], **values)
        return ReadManifest(use=row["read_use"], **values)
    except (KeyError, TypeError, ValueError):
        raise AssetFailure(503, "ASSET_INTEGRITY") from None


def _database_failure(error: SQLAlchemyError) -> AssetFailure:
    code = getattr(getattr(error, "orig", None), "sqlstate", None)
    status, public = {
        "42501": (403, "ASSET_DENIED"),
        "P0002": (404, "ASSET_NOT_FOUND"),
        "55000": (409, "ASSET_CONFLICT"),
        "WA410": (410, "ASSET_UPLOAD_EXPIRED"),
        "54000": (413, "ASSET_LIMIT"),
        "22023": (422, "ASSET_INVALID"),
        "22P02": (422, "ASSET_INVALID"),
        "0A000": (503, "CAPABILITY_UNSUPPORTED"),
        "WA503": (503, "ASSET_CONFIGURATION_UNAVAILABLE"),
    }.get(str(code), (503, "ASSET_UNAVAILABLE"))
    return AssetFailure(status, public)


class _AssetRepository:
    def __init__(self, session: Session, actor: AssetActor) -> None:
        self.session, self.actor = session, actor

    def query(self, name: str, arguments: str, **values: Any) -> Mapping[str, Any]:
        return dict(
            self.session.execute(
                text(f"SELECT * FROM public.{name}({arguments})"),
                {"session": self.actor.session_digest, **values},
            )
            .mappings()
            .one()
        )

    def get(self, asset_id: UUID) -> Asset:
        row = (
            self.session.execute(
                text("SELECT * FROM public.assets WHERE id=:id"), {"id": asset_id}
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AssetFailure(404, "ASSET_NOT_FOUND")
        return _asset(dict(row))

    def begin(self, request: BeginUpload) -> UploadSession:
        row = self.query(
            "wso_begin_asset_upload",
            "CAST(:request AS jsonb),:session",
            request=request.model_dump_json(),
        )
        return UploadSession.model_validate(dict(row))

    def prepare_write(self, asset_id: UUID, session_id: UUID) -> UploadPreparation:
        row = self.query(
            "wso_prepare_asset_write",
            ":id,:upload,:session",
            id=asset_id,
            upload=session_id,
        )
        return UploadPreparation(
            row["upload_session_id"],
            _aad(row),
            _timestamp(row["session_expires_at"]),
            row["policy_version"],
        )

    def begin_write(
        self, asset_id: UUID, session_id: UUID, envelope: Envelope
    ) -> WriteManifest:
        encoded = {
            "key_id": envelope.key_id,
            "wrapped_dek": envelope.wrapped_key.ciphertext.hex(),
            "wrap_nonce": envelope.wrapped_key.wrap_nonce.hex(),
            "object_nonce": envelope.object_nonce.hex(),
        }
        return cast(
            WriteManifest,
            _manifest(
                self.query(
                    "wso_begin_asset_write",
                    ":id,:upload,:session,CAST(:envelope AS jsonb)",
                    id=asset_id,
                    upload=session_id,
                    envelope=json.dumps(encoded),
                ),
                write=True,
            ),
        )

    def record_multipart(self, manifest: WriteManifest, multipart_id: str) -> None:
        self.query(
            "wso_record_asset_multipart",
            ":id,:generation,:token,:multipart,:session",
            id=manifest.aad.asset_id,
            generation=manifest.lease.generation,
            token=manifest.lease.token,
            multipart=multipart_id,
        )

    def begin_completion(self, manifest: WriteManifest) -> None:
        self.query(
            "wso_begin_asset_completion",
            ":id,:generation,:token,:session",
            id=manifest.aad.asset_id,
            generation=manifest.lease.generation,
            token=manifest.lease.token,
        )

    def seal(self, manifest: WriteManifest) -> None:
        self.query(
            "wso_seal_asset_upload",
            ":id,:generation,:token,:session",
            id=manifest.aad.asset_id,
            generation=manifest.lease.generation,
            token=manifest.lease.token,
        )

    def begin_validation(self, asset_id: UUID) -> Asset | ReadManifest:
        row = self.query("wso_begin_asset_validation", ":id,:session", id=asset_id)
        if row["already_ready"] is True:
            return _asset(dict(row))
        if row["already_ready"] is not False:
            raise AssetFailure(503, "ASSET_INTEGRITY")
        return cast(ReadManifest, _manifest(dict(row)))

    def finish_validation(
        self, manifest: ReadManifest, receipt: ValidationReceipt
    ) -> Asset:
        encoded = {
            "policy_version": receipt.policy_version,
            "byte_size": receipt.byte_size,
            "checksum_sha256": receipt.checksum_sha256,
            **asdict(receipt.image),
        }
        return _asset(
            self.query(
                "wso_finish_asset_validation",
                ":id,:generation,:token,CAST(:receipt AS jsonb),:session",
                id=manifest.aad.asset_id,
                generation=manifest.lease.generation,
                token=manifest.lease.token,
                receipt=json.dumps(encoded),
            )
        )

    def reject(self, manifest: WriteManifest | ReadManifest, code: str) -> None:
        self.query(
            "wso_reject_asset_upload",
            ":id,:generation,:token,:failure,:session",
            id=manifest.aad.asset_id,
            generation=manifest.lease.generation,
            token=manifest.lease.token,
            failure=code,
        )

    def issue_ticket(self, asset_id: UUID) -> DownloadTicket:
        return DownloadTicket.model_validate(
            dict(self.query("wso_issue_asset_ticket", ":id,:session", id=asset_id))
        )

    def redeem(self, asset_id: UUID, token: str) -> ReadManifest:
        return cast(
            ReadManifest,
            _manifest(
                self.query(
                    "wso_redeem_asset_ticket",
                    ":id,:token,:session",
                    id=asset_id,
                    token=token,
                )
            ),
        )

    def revalidate(self, manifest: ReadManifest) -> bool:
        return (
            self.query(
                "wso_revalidate_asset_read",
                ":id,:lease,:session",
                id=manifest.aad.asset_id,
                lease=manifest.lease.id,
            )["wso_revalidate_asset_read"]
            is True
        )

    def close_read(self, manifest: ReadManifest) -> None:
        self.query(
            "wso_close_asset_read",
            ":id,:lease,:session",
            id=manifest.aad.asset_id,
            lease=manifest.lease.id,
        )

    def tombstone(self, asset_id: UUID) -> Asset:
        return _asset(self.query("wso_tombstone_asset", ":id,:session", id=asset_id))


def _budget(
    lease: AssetLease, started: float, cap: int, enclosing: IOBudget | None = None
) -> IOBudget:
    return IOBudget(
        min(
            started + cap,
            started + lease.remaining_ms / 1000,
            enclosing.deadline_monotonic if enclosing is not None else float("inf"),
        )
    )


def _subbudget(budget: IOBudget, seconds: int) -> IOBudget:
    return IOBudget(min(budget.deadline_monotonic, time.monotonic() + seconds))


def _read_plain(
    objects: PrivateObjectStore,
    cipher: AssetCipher,
    manifest: ReadManifest,
    budget: IOBudget,
    chunk_bytes: int,
) -> VerifiedPlaintext:
    with objects.get(
        manifest.locator, max_bytes=manifest.aad.byte_size + 36, budget=budget
    ) as reader:

        def chunks() -> Iterator[bytes]:
            while True:
                chunk = reader.read(chunk_bytes)
                if not chunk:
                    return
                yield chunk

        return cipher.decrypt_verified(manifest, chunks(), budget=budget)


def _failure(error: Exception) -> AssetFailure:
    if isinstance(error, AssetFailure):
        return error
    code = getattr(error, "code", "UNAVAILABLE")
    if isinstance(error, ImageValidationFailure):
        return AssetFailure(
            415
            if code == "TYPE"
            else 413
            if code in ("PIXELS", "DIMENSIONS")
            else 503
            if code in ("DEADLINE", "UNAVAILABLE")
            else 422,
            "ASSET_" + code,
        )
    if isinstance(error, AssetCryptoFailure):
        return AssetFailure(
            413 if code == "LIMIT" else 422 if code == "INTEGRITY" else 503,
            "ASSET_" + code,
        )
    return AssetFailure(503, "ASSET_UNAVAILABLE")


def _local_cleanup(objects: PrivateObjectStore) -> bool:
    from wso_core.asset_process import local_cleanup_complete

    return objects.local_cleanup_complete() and local_cleanup_complete()


class AssetStore:
    def __init__(
        self,
        *,
        actor: AssetActor,
        transactions: AuthorizedTransactions,
        budget: IOBudget,
        objects: PrivateObjectStore,
        cipher: AssetCipher,
        images: ImageValidator,
        policy: AssetPolicy,
        admission: AssetAdmissionController,
        on_event: AssetEventCallback | None,
    ) -> None:
        self.actor, self.transactions, self.budget = actor, transactions, budget
        self.objects, self.cipher, self.images = objects, cipher, images
        self.policy, self.admission, self.on_event = policy, admission, on_event

    def _control(
        self, action: AssetAction, method: str, *args: Any, budget: IOBudget
    ) -> Any:
        try:
            budget.remaining_seconds()
            with self.transactions(
                action, deadline_monotonic=budget.deadline_monotonic
            ) as session:
                session.execute(
                    text("SELECT set_config('wso.asset_request_id',:request,true)"),
                    {"request": self.actor.correlation_id},
                )
                configuration = read_asset_runtime_configuration(session)
                if (
                    configuration.policy != self.policy
                    or configuration.namespace != self.objects.namespace
                ):
                    self.admission.close_admission()
                    raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
                result = getattr(_AssetRepository(session, self.actor), method)(*args)
                budget.remaining_seconds()
            budget.remaining_seconds()
            return result
        except SQLAlchemyError as error:
            raise _database_failure(error) from None
        except DbUnavailable:
            raise AssetFailure(503, "ASSET_AUTHORIZATION_TIMEOUT") from None
        except StorageFailure:
            raise AssetFailure(503, "ASSET_DEADLINE") from None

    def _event(self, name: AssetEventName, asset_id: UUID) -> None:
        if self.on_event is not None:
            self.on_event(AssetEvent(name, asset_id))

    def begin_upload(
        self,
        scope: JobScope,
        purpose: AssetPurpose,
        content_type: str,
        byte_size: int,
        checksum: Checksum,
        *,
        parent_asset_id: UUID | None = None,
    ) -> UploadSession:
        if scope.tenant_id != self.actor.tenant_id:
            raise AssetFailure(404, "ASSET_NOT_FOUND")
        if purpose == "EVIDENCE":
            raise AssetFailure(503, "CAPABILITY_UNSUPPORTED")
        request = BeginUpload.model_validate(
            {
                "scope": scope,
                "purpose": purpose,
                "content_type": content_type,
                "byte_size": byte_size,
                "checksum": checksum,
                "parent_asset_id": parent_asset_id,
            }
        )
        return cast(
            UploadSession,
            self._control("assets:write", "begin", request, budget=self.budget),
        )

    def get(self, asset_id: UUID) -> Asset:
        return cast(
            Asset, self._control("assets:read", "get", asset_id, budget=self.budget)
        )

    def authorize_download(self, actor: UUID, asset_id: UUID) -> DownloadTicket:
        if actor != self.actor.user_id:
            raise AssetFailure(404, "ASSET_NOT_FOUND")
        return cast(
            DownloadTicket,
            self._control("assets:read", "issue_ticket", asset_id, budget=self.budget),
        )

    def delete_asset(self, asset_id: UUID) -> Asset:
        return cast(
            Asset,
            self._control("assets:write", "tombstone", asset_id, budget=self.budget),
        )

    def _reject(
        self, manifest: WriteManifest | ReadManifest, code: str, *, budget: IOBudget
    ) -> None:
        if time.monotonic() >= budget.deadline_monotonic:
            return
        try:
            self._control("assets:write", "reject", manifest, code, budget=budget)
        except AssetFailure:
            # Committed attempt/lease remains recoverable by independent maintenance.
            _LOG.warning("Asset bookkeeping deferred to independent lease expiry")

    def complete_upload(self, asset_id: UUID) -> Asset:
        permit = self.admission.try_acquire(kind="READ")
        manifest: ReadManifest | None = None
        plain: VerifiedPlaintext | None = None
        budget = self.budget
        try:
            started = time.monotonic()
            result = self._control(
                "assets:write", "begin_validation", asset_id, budget=budget
            )
            if isinstance(result, Asset):
                return result
            manifest = cast(ReadManifest, result)
            budget = _budget(
                manifest.lease, started, self.policy.verification_seconds, self.budget
            )
            plain = _read_plain(
                self.objects,
                self.cipher,
                manifest,
                _subbudget(budget, 10),
                self.policy.chunk_bytes,
            )
            info = self.images.validate(
                plain,
                expected_type=manifest.aad.content_type,
                budget=_subbudget(budget, self.policy.decoder_seconds),
            )
            receipt = ValidationReceipt(
                manifest.policy_version, plain.byte_size, plain.checksum_sha256, info
            )
            self._event("VALIDATED_BEFORE_FINALIZE", asset_id)
            budget.remaining_seconds()
            return cast(
                Asset,
                self._control(
                    "assets:write",
                    "finish_validation",
                    manifest,
                    receipt,
                    budget=budget,
                ),
            )
        except (
            StorageFailure,
            AssetCryptoFailure,
            ImageValidationFailure,
            AssetFailure,
        ) as error:
            if manifest is not None:
                terminal = (
                    isinstance(error, AssetCryptoFailure)
                    and error.code in ("INTEGRITY", "LIMIT")
                    or isinstance(error, ImageValidationFailure)
                    and error.code not in ("DEADLINE", "UNAVAILABLE")
                )
                self._reject(
                    manifest, str(error.code) if terminal else "RETRY", budget=budget
                )
            raise _failure(error) from None
        finally:
            plain = None
            permit.release(cleanup_complete=_local_cleanup(self.objects))


class AssetGateway:
    def __init__(self, *, store: AssetStore) -> None:
        self.store = store

    async def put_content(
        self,
        asset_id: UUID,
        session_id: UUID,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str,
        content_length: int | None,
        content_encoding: str | None,
    ) -> None:
        store = self.store
        permit = store.admission.try_acquire(kind="UPLOAD")
        manifest: WriteManifest | None = None
        stream = None
        buffer = bytearray()
        failure_code = "REMOTE_UNKNOWN"
        finished = False
        budget = store.budget

        async def worker(
            function: Callable[..., Any], *args: Any, **kwargs: Any
        ) -> Any:
            # Do not abandon a thread that still owns a Session/helper/crypto state.
            return await anyio.to_thread.run_sync(
                partial(function, *args, **kwargs), abandon_on_cancel=False
            )

        try:
            started = time.monotonic()
            with anyio.fail_after(budget.remaining_seconds()) as upload_scope:
                preparation = await worker(
                    store._control,
                    "assets:write",
                    "prepare_write",
                    asset_id,
                    session_id,
                    budget=budget,
                )
                if (
                    content_encoding not in (None, "identity")
                    or content_type.lower() != preparation.aad.content_type
                ):
                    raise AssetFailure(415, "ASSET_TYPE")
                if content_length is not None and (
                    type(content_length) is not int
                    or content_length != preparation.aad.byte_size
                ):
                    raise AssetFailure(422, "ASSET_LENGTH")
                prepared = await worker(store.cipher.prepare, preparation.aad)
                manifest = await worker(
                    store._control,
                    "assets:write",
                    "begin_write",
                    asset_id,
                    session_id,
                    prepared.envelope,
                    budget=budget,
                )
                budget = _budget(
                    manifest.lease, started, store.policy.upload_seconds, store.budget
                )
                upload_scope.deadline = min(
                    upload_scope.deadline,
                    anyio.current_time() + budget.remaining_seconds(),
                )
                await worker(store._event, "UPLOAD_INTENT_COMMITTED", asset_id)
                budget.remaining_seconds()
                stream = await worker(store.cipher.start, prepared)
                prepared = None
                buffer.extend(stream.header())
                prefix = bytearray()
                multipart_id: str | None = None
                parts: list[Any] = []
                received = 0
                async for incoming in chunks:
                    budget.remaining_seconds()
                    if type(incoming) is not bytes:
                        raise AssetFailure(422, "ASSET_INVALID")
                    received += len(incoming)
                    if received > preparation.aad.byte_size:
                        failure_code = "LIMIT"
                        raise AssetFailure(413, "ASSET_LIMIT")
                    for offset in range(0, len(incoming), store.policy.chunk_bytes):
                        chunk = incoming[offset : offset + store.policy.chunk_bytes]
                        prefix.extend(chunk[: max(0, 32 - len(prefix))])
                        if multipart_id is None and len(prefix) >= min(
                            32, preparation.aad.byte_size
                        ):
                            if (
                                store.images.sniff(bytes(prefix))
                                != preparation.aad.content_type
                            ):
                                raise ImageValidationFailure("TYPE")
                            multipart_id = await worker(
                                store.objects.create_multipart,
                                manifest.locator,
                                budget=budget,
                            )
                            await worker(
                                store._event,
                                "MULTIPART_CREATED_BEFORE_RECORD",
                                asset_id,
                            )
                            budget.remaining_seconds()
                            await worker(
                                store._control,
                                "assets:write",
                                "record_multipart",
                                manifest,
                                multipart_id,
                                budget=budget,
                            )
                        buffer.extend(await worker(stream.update, chunk))
                        if (
                            len(buffer) >= store.policy.multipart_part_bytes
                            and multipart_id is not None
                        ):
                            part = bytes(buffer[: store.policy.multipart_part_bytes])
                            del buffer[: store.policy.multipart_part_bytes]
                            parts.append(
                                await worker(
                                    store.objects.upload_part,
                                    manifest.locator,
                                    multipart_id,
                                    len(parts) + 1,
                                    part,
                                    budget=budget,
                                )
                            )
                            part = b""
                final = await worker(stream.finish)
                buffer.extend(final.tail)
                if multipart_id is None:
                    raise AssetFailure(422, "ASSET_LENGTH")
                if buffer:
                    parts.append(
                        await worker(
                            store.objects.upload_part,
                            manifest.locator,
                            multipart_id,
                            len(parts) + 1,
                            bytes(buffer),
                            budget=budget,
                        )
                    )
                    buffer.clear()
                # A failed/uncertain fence commit never dispatches Complete.
                await worker(
                    store._control,
                    "assets:write",
                    "begin_completion",
                    manifest,
                    budget=budget,
                )
                budget.remaining_seconds()
                await worker(
                    store.objects.complete_multipart,
                    manifest.locator,
                    multipart_id,
                    tuple(parts),
                    budget=budget,
                )
                await worker(store._event, "OBJECT_COMPLETED_BEFORE_SEAL", asset_id)
                budget.remaining_seconds()
                await worker(
                    store._control, "assets:write", "seal", manifest, budget=budget
                )
                finished = True
        except (
            StorageFailure,
            AssetCryptoFailure,
            ImageValidationFailure,
            AssetFailure,
        ) as error:
            if isinstance(
                error, (AssetCryptoFailure, ImageValidationFailure)
            ) and error.code in (
                "TYPE",
                "INTEGRITY",
                "LIMIT",
                "DECODE",
                "PIXELS",
                "DIMENSIONS",
                "FRAMES",
            ):
                failure_code = error.code
            raise _failure(error) from None
        except TimeoutError:
            raise AssetFailure(503, "ASSET_DEADLINE") from None
        finally:
            with anyio.CancelScope(shield=True):
                if stream is not None:
                    stream.close()
                buffer.clear()
                try:
                    if manifest is not None and not finished:
                        await worker(
                            store._reject, manifest, failure_code, budget=budget
                        )
                finally:
                    permit.release(cleanup_complete=_local_cleanup(store.objects))

    def open_download(self, asset_id: UUID, ticket_token: str) -> VerifiedDownload:
        store = self.store
        permit = store.admission.try_acquire(kind="READ")
        manifest: ReadManifest | None = None
        transferred = False
        budget = store.budget
        try:
            if not re.fullmatch(r"[0-9a-f]{64}", ticket_token):
                raise AssetFailure(404, "ASSET_NOT_FOUND")
            started = time.monotonic()
            manifest = store._control(
                "assets:read", "redeem", asset_id, ticket_token, budget=budget
            )
            assert manifest is not None
            budget = _budget(
                manifest.lease, started, store.policy.download_seconds, store.budget
            )
            plain = _read_plain(
                store.objects, store.cipher, manifest, budget, store.policy.chunk_bytes
            )
            if not store._control("assets:read", "revalidate", manifest, budget=budget):
                raise AssetFailure(404, "ASSET_NOT_FOUND")
            budget.remaining_seconds()
            result = VerifiedDownload(store, manifest, plain, budget, permit)
            transferred = True
            return result
        except (StorageFailure, AssetCryptoFailure, AssetFailure) as error:
            raise _failure(error) from None
        finally:
            if not transferred:
                try:
                    if (
                        manifest is not None
                        and time.monotonic() < budget.deadline_monotonic
                    ):
                        try:
                            store._control(
                                "assets:read", "close_read", manifest, budget=budget
                            )
                        except AssetFailure:
                            _LOG.warning(
                                "Asset bookkeeping deferred to independent lease expiry"
                            )
                finally:
                    permit.release(cleanup_complete=_local_cleanup(store.objects))


class VerifiedDownload:
    def __init__(
        self,
        store: AssetStore,
        manifest: ReadManifest,
        plaintext: VerifiedPlaintext,
        budget: IOBudget,
        permit: AssetPermit,
    ) -> None:
        self.asset_id = manifest.aad.asset_id
        self.content_type = manifest.aad.content_type
        self.byte_size = plaintext.byte_size
        self.expires_at = manifest.lease.expires_at
        self.deadline_monotonic = budget.deadline_monotonic
        self._data, self._store, self._manifest = plaintext.data, store, manifest
        self._budget, self._permit = budget, permit
        self._closed = False
        self._started = False
        self._lock = Lock()

    def iter_bytes(self, chunk_size: int = 262144) -> Iterator[bytes]:
        if type(chunk_size) is not int or not 1 <= chunk_size <= 262144:
            raise ValueError("invalid download chunk size")
        with self._lock:
            if self._started or self._closed:
                raise AssetFailure(404, "ASSET_NOT_FOUND")
            self._started = True
        self._store._event("DOWNLOAD_FIRST_CHUNK", self.asset_id)
        if not self._store._control(
            "assets:read", "revalidate", self._manifest, budget=self._budget
        ):
            raise AssetFailure(404, "ASSET_NOT_FOUND")
        for offset in range(0, self.byte_size, chunk_size):
            self._budget.remaining_seconds()
            if self._closed:
                raise AssetFailure(404, "ASSET_NOT_FOUND")
            yield self._data[offset : offset + chunk_size]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._data = b""
        try:
            if time.monotonic() < self._budget.deadline_monotonic:
                self._store._control(
                    "assets:read", "close_read", self._manifest, budget=self._budget
                )
        except AssetFailure:
            _LOG.warning("Asset bookkeeping deferred to independent lease expiry")
        finally:
            self._permit.release(cleanup_complete=_local_cleanup(self._store.objects))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class JobAssetReader:
    def __init__(
        self,
        *,
        objects: PrivateObjectStore,
        cipher: AssetCipher,
        policy: AssetPolicy,
        admission: AssetAdmissionController,
        on_event: AssetEventCallback | None,
    ) -> None:
        self.objects, self.cipher, self.policy = objects, cipher, policy
        self.admission, self.on_event = admission, on_event

    def read(self, step: Any, asset_id: UUID) -> bytes:
        permit = self.admission.try_acquire(kind="READ")
        manifest: ReadManifest | None = None
        try:
            configuration = read_asset_runtime_configuration(step.session)
            if (
                configuration.policy != self.policy
                or configuration.namespace != self.objects.namespace
            ):
                self.admission.close_admission()
                raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
            started = time.monotonic()
            row = (
                step.session.execute(
                    text("SELECT * FROM public.wso_begin_job_asset_read(:id)"),
                    {"id": asset_id},
                )
                .mappings()
                .one()
            )
            manifest = cast(ReadManifest, _manifest(dict(row)))
            budget = _budget(manifest.lease, started, self.policy.job_read_seconds)
            plain = _read_plain(
                self.objects, self.cipher, manifest, budget, self.policy.chunk_bytes
            )
            if (
                step.session.execute(
                    text("SELECT public.wso_revalidate_asset_read(:id,:lease)"),
                    {"id": asset_id, "lease": manifest.lease.id},
                ).scalar_one()
                is not True
            ):
                raise AssetFailure(404, "ASSET_UNAVAILABLE")
            budget.remaining_seconds()
            return plain.data
        except SQLAlchemyError as error:
            raise _database_failure(error) from None
        except (StorageFailure, AssetCryptoFailure) as error:
            raise _failure(error) from None
        finally:
            try:
                if manifest is not None:
                    step.session.execute(
                        text("SELECT public.wso_close_asset_read(:id,:lease)"),
                        {"id": asset_id, "lease": manifest.lease.id},
                    )
            finally:
                permit.release(cleanup_complete=_local_cleanup(self.objects))
