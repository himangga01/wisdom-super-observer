"""Provider-independent public contracts for authenticated private images."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from wso_contracts.models import JobScope, WireModel

MAX_ASSET_BYTES = 20_971_520
AssetPurpose = Literal["IMPORT_PHOTO", "IMPORT_CROP", "EVIDENCE"]
AssetState = Literal["PENDING", "READY", "DELETING", "DELETED", "REJECTED"]
ImageMime = Literal["image/jpeg", "image/png"]
AssetBytes = Annotated[StrictInt, Field(ge=1, le=MAX_ASSET_BYTES)]


class AssetWire(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(UTC)


def _access_path(asset_id: UUID, path: str) -> None:
    parsed = urlsplit(path)
    try:
        tenant_id = UUID(parsed.query.removeprefix("tenant_id="))
    except ValueError:
        raise ValueError("authenticated asset path required") from None
    expected = f"/api/v1/assets/{asset_id}/content?tenant_id={tenant_id}"
    if path != expected or parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("authenticated asset path required")


class Checksum(AssetWire):
    algorithm: Literal["SHA256"]
    value: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class BeginUpload(AssetWire):
    scope: JobScope
    purpose: AssetPurpose
    content_type: ImageMime
    byte_size: AssetBytes
    checksum: Checksum
    parent_asset_id: UUID | None = None

    @model_validator(mode="after")
    def purpose_scope(self) -> BeginUpload:
        if (self.purpose == "IMPORT_CROP") != (self.parent_asset_id is not None):
            raise ValueError("crop requires a parent; other purposes forbid one")
        if self.purpose == "EVIDENCE" and self.scope.scope_kind != "STORE":
            raise ValueError("evidence requires store scope")
        return self


class Asset(AssetWire):
    id: UUID
    tenant_id: UUID
    store_id: UUID | None
    purpose: AssetPurpose
    parent_asset_id: UUID | None
    state: AssetState
    checksum: Checksum
    byte_size: AssetBytes
    content_type: ImageMime
    expires_at: datetime
    created_at: datetime

    @field_validator("expires_at", "created_at")
    @classmethod
    def timestamps(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def immutable_scope(self) -> Asset:
        if (self.purpose == "IMPORT_CROP") != (self.parent_asset_id is not None):
            raise ValueError("invalid asset parent")
        if self.purpose == "EVIDENCE" and self.store_id is None:
            raise ValueError("evidence requires a store")
        if self.expires_at <= self.created_at:
            raise ValueError("asset retention must follow creation")
        return self


class UploadSession(AssetWire):
    id: UUID
    asset_id: UUID
    upload_path: Annotated[StrictStr, Field(max_length=200)]
    expires_at: datetime
    max_bytes: AssetBytes

    @field_validator("expires_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def path(self) -> UploadSession:
        _access_path(self.asset_id, self.upload_path)
        return self


class DownloadTicket(AssetWire):
    id: UUID
    asset_id: UUID
    download_path: Annotated[StrictStr, Field(max_length=200)]
    token: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$", repr=False)]
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def path(self) -> DownloadTicket:
        _access_path(self.asset_id, self.download_path)
        return self
