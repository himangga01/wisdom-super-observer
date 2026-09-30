"""Private encrypted object transport and immutable asset boundary values."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from types import TracebackType
from typing import Literal, Protocol, Self
from urllib.parse import urlsplit
from uuid import UUID

from wso_contracts.assets import AssetPurpose

ImageMime = Literal["image/jpeg", "image/png"]
StorageCode = Literal[
    "NOT_FOUND",
    "DENIED",
    "UNAVAILABLE",
    "DEADLINE",
    "LIMIT",
    "INTEGRITY",
    "UNSUPPORTED",
]
S3Operation = Literal[
    "PUT",
    "GET",
    "HEAD",
    "DELETE",
    "CREATE_MULTIPART",
    "UPLOAD_PART",
    "COMPLETE_MULTIPART",
    "ABORT_MULTIPART",
    "LIST_OBJECTS",
    "LIST_MULTIPART",
    "PRESIGN_GET",
]
MAX_BYTES = 20971520
CHUNK_BYTES = 262144
PART_BYTES = 5242880


class StorageFailure(Exception):
    def __init__(self, code: StorageCode, *, outcome_unknown: bool = False) -> None:
        self.code = code
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


def strict_int(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid bounded integer")


def _uuid(*values: UUID) -> None:
    if any(type(value) is not UUID for value in values):
        raise ValueError("invalid UUID")


def _date(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("UTC timestamp required")


def _hex(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid digest")


def key_id_valid(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is None:
        raise ValueError("invalid key identifier")


def opaque_valid(value: str, cap: int = 1024) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= cap
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("invalid opaque value")


@dataclass(frozen=True, slots=True)
class AssetPolicy:
    version: int
    max_bytes: int = MAX_BYTES
    max_pixels: int = 25000000
    max_dimension: int = 10000
    max_frames: int = 1
    chunk_bytes: int = CHUNK_BYTES
    multipart_part_bytes: int = PART_BYTES
    upload_seconds: int = 120
    verification_seconds: int = 30
    download_seconds: int = 30
    job_read_seconds: int = 10
    decoder_seconds: int = 10
    decoder_memory_bytes: int = 536870912

    def __post_init__(self) -> None:
        caps = (
            2147483647,
            MAX_BYTES,
            25000000,
            10000,
            1,
            CHUNK_BYTES,
            PART_BYTES,
            120,
            30,
            30,
            10,
            10,
            536870912,
        )
        for item, cap in zip(fields(self), caps, strict=True):
            strict_int(getattr(self, item.name), 1, cap)
        if self.multipart_part_bytes != PART_BYTES:
            raise ValueError("fixed multipart size required")


@dataclass(frozen=True, slots=True)
class InstallationNamespace:
    installation_id: UUID
    bucket: str = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.installation_id)
        if (
            type(self.bucket) is not str
            or re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket) is None
            or ".." in self.bucket
        ):
            raise ValueError("invalid bucket")


@dataclass(frozen=True, slots=True, repr=False)
class ObjectLocator:
    installation_id: UUID
    tenant_id: UUID
    asset_id: UUID
    attempt_id: UUID

    def __post_init__(self) -> None:
        _uuid(self.installation_id, self.tenant_id, self.asset_id, self.attempt_id)


def installation_prefix(namespace: InstallationNamespace) -> str:
    return f"wso-assets/v1/{namespace.installation_id.hex}/"


def object_key(locator: ObjectLocator) -> str:
    return f"wso-assets/v1/{locator.installation_id.hex}/objects/{locator.tenant_id.hex}/{locator.asset_id.hex}/{locator.attempt_id.hex}.wso"


def parse_object_key(
    namespace: InstallationNamespace, key: str
) -> ObjectLocator | None:
    if type(key) is not str:
        return None
    match = re.fullmatch(
        re.escape(installation_prefix(namespace))
        + r"objects/([0-9a-f]{32})/([0-9a-f]{32})/([0-9a-f]{32})\.wso",
        key,
    )
    if match is None:
        return None
    return ObjectLocator(
        namespace.installation_id, *(UUID(hex=part) for part in match.groups())
    )


@dataclass(frozen=True, slots=True)
class AssetAAD:
    tenant_id: UUID
    asset_id: UUID
    attempt_id: UUID
    store_id: UUID | None
    parent_asset_id: UUID | None
    purpose: AssetPurpose
    byte_size: int
    content_type: ImageMime
    checksum_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.tenant_id, self.asset_id, self.attempt_id)
        for value in (self.store_id, self.parent_asset_id):
            if value is not None:
                _uuid(value)
        if self.purpose not in (
            "IMPORT_PHOTO",
            "IMPORT_CROP",
            "EVIDENCE",
        ) or self.content_type not in ("image/jpeg", "image/png"):
            raise ValueError("invalid asset type")
        strict_int(self.byte_size, 1, MAX_BYTES)
        _hex(self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class WrappedKey:
    wrap_nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.wrap_nonce) is not bytes
            or len(self.wrap_nonce) != 12
            or type(self.ciphertext) is not bytes
            or len(self.ciphertext) != 48
        ):
            raise ValueError("invalid wrapped key")


@dataclass(frozen=True, slots=True)
class Envelope:
    key_id: str = field(repr=False)
    wrapped_key: WrappedKey = field(repr=False)
    object_nonce: bytes = field(repr=False)

    def __post_init__(self) -> None:
        key_id_valid(self.key_id)
        if (
            not isinstance(self.wrapped_key, WrappedKey)
            or type(self.object_nonce) is not bytes
            or len(self.object_nonce) != 12
        ):
            raise ValueError("invalid envelope")


@dataclass(frozen=True, slots=True)
class AssetLease:
    id: UUID
    generation: int
    expires_at: datetime
    remaining_ms: int
    token: str | None = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.id)
        _date(self.expires_at)
        strict_int(self.generation, 1, 9223372036854775807)
        strict_int(self.remaining_ms, 1, 120000)
        if self.token is not None:
            _hex(self.token)


@dataclass(frozen=True, slots=True)
class UploadPreparation:
    session_id: UUID
    aad: AssetAAD
    session_expires_at: datetime
    policy_version: int

    def __post_init__(self) -> None:
        _uuid(self.session_id)
        _date(self.session_expires_at)
        strict_int(self.policy_version, 1, 2147483647)
        if self.session_id != self.aad.attempt_id:
            raise ValueError("attempt identity mismatch")


def _manifest(
    locator: ObjectLocator,
    aad: AssetAAD,
    lease: AssetLease,
    access: int,
    parent: int | None,
    policy: int,
) -> None:
    if (locator.tenant_id, locator.asset_id, locator.attempt_id) != (
        aad.tenant_id,
        aad.asset_id,
        aad.attempt_id,
    ):
        raise ValueError("manifest identity mismatch")
    strict_int(access, 1, 9223372036854775807)
    strict_int(policy, 1, 2147483647)
    if parent is not None:
        strict_int(parent, 1, 9223372036854775807)
    if (parent is None) != (aad.parent_asset_id is None):
        raise ValueError("parent generation mismatch")


@dataclass(frozen=True, slots=True)
class WriteManifest:
    upload_session_id: UUID
    locator: ObjectLocator = field(repr=False)
    aad: AssetAAD
    envelope: Envelope = field(repr=False)
    lease: AssetLease = field(repr=False)
    access_generation: int
    parent_access_generation: int | None
    policy_version: int

    def __post_init__(self) -> None:
        _manifest(
            self.locator,
            self.aad,
            self.lease,
            self.access_generation,
            self.parent_access_generation,
            self.policy_version,
        )
        if self.upload_session_id != self.aad.attempt_id or self.lease.token is None:
            raise ValueError("invalid write capability")


@dataclass(frozen=True, slots=True)
class ReadManifest:
    use: Literal["VALIDATE", "DOWNLOAD", "JOB"]
    locator: ObjectLocator = field(repr=False)
    aad: AssetAAD
    envelope: Envelope = field(repr=False)
    lease: AssetLease = field(repr=False)
    access_generation: int
    parent_access_generation: int | None
    policy_version: int

    def __post_init__(self) -> None:
        _manifest(
            self.locator,
            self.aad,
            self.lease,
            self.access_generation,
            self.parent_access_generation,
            self.policy_version,
        )
        if self.use not in ("VALIDATE", "DOWNLOAD", "JOB") or (
            self.lease.token is not None
        ) != (self.use == "VALIDATE"):
            raise ValueError("invalid read capability")
        strict_int(self.lease.remaining_ms, 1, 10000 if self.use == "JOB" else 30000)


@dataclass(frozen=True, slots=True)
class ImageInfo:
    content_type: ImageMime
    width: int
    height: int
    oriented_width: int
    oriented_height: int
    frame_count: int

    def __post_init__(self) -> None:
        if self.content_type not in ("image/jpeg", "image/png"):
            raise ValueError("invalid image MIME")
        for value in (
            self.width,
            self.height,
            self.oriented_width,
            self.oriented_height,
        ):
            strict_int(value, 1, 10000)
        strict_int(self.frame_count, 1, 1)


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    policy_version: int
    byte_size: int
    checksum_sha256: str = field(repr=False)
    image: ImageInfo

    def __post_init__(self) -> None:
        strict_int(self.policy_version, 1, 2147483647)
        strict_int(self.byte_size, 1, MAX_BYTES)
        _hex(self.checksum_sha256)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PreparedEncryption:
    aad: AssetAAD
    envelope: Envelope = field(repr=False)
    data_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.data_key) is not bytes or len(self.data_key) != 32:
            raise ValueError("invalid data key")


@dataclass(frozen=True, slots=True)
class EncryptionFinal:
    tail: bytes = field(repr=False)
    byte_size: int
    checksum_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        strict_int(self.byte_size, 1, MAX_BYTES)
        _hex(self.checksum_sha256)
        if type(self.tail) is not bytes or len(self.tail) < 16:
            raise ValueError("invalid final ciphertext")


@dataclass(frozen=True, slots=True)
class VerifiedPlaintext:
    data: bytes = field(repr=False)
    byte_size: int
    checksum_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        strict_int(self.byte_size, 1, MAX_BYTES)
        _hex(self.checksum_sha256)
        if type(self.data) is not bytes or len(self.data) != self.byte_size:
            raise ValueError("invalid plaintext length")


class AssetKeyProvider(Protocol):
    def active_key_id(self) -> str: ...
    def wrap(self, key_id: str, dek: bytes, aad: bytes) -> WrappedKey: ...
    def unwrap(self, key_id: str, envelope: WrappedKey, aad: bytes) -> bytes: ...


class EncryptingUpload(Protocol):
    def header(self) -> bytes: ...
    def update(self, plaintext: bytes) -> bytes: ...
    def finish(self) -> EncryptionFinal: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class IOBudget:
    deadline_monotonic: float
    call_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.deadline_monotonic, bool)
            or not math.isfinite(self.deadline_monotonic)
            or isinstance(self.call_timeout_seconds, bool)
            or not 0 < self.call_timeout_seconds <= 10
        ):
            raise ValueError("invalid I/O budget")

    def remaining_seconds(self) -> float:
        value = self.deadline_monotonic - time.monotonic()
        if value <= 0:
            raise StorageFailure("DEADLINE")
        return value

    @classmethod
    def from_remaining_ms(cls, remaining_ms: int) -> Self:
        strict_int(remaining_ms, 1, 120000)
        result = cls(time.monotonic() + remaining_ms / 1000 - 1)
        result.remaining_seconds()
        return result


@dataclass(frozen=True, slots=True)
class ObjectHead:
    byte_size: int
    etag: str = field(repr=False)

    def __post_init__(self) -> None:
        strict_int(self.byte_size, 0, MAX_BYTES + 36)
        opaque_valid(self.etag)


@dataclass(frozen=True, slots=True)
class UploadedPart:
    part_number: int
    etag: str = field(repr=False)

    def __post_init__(self) -> None:
        strict_int(self.part_number, 1, 10000)
        opaque_valid(self.etag)


@dataclass(frozen=True, slots=True)
class ObjectEntry:
    locator: ObjectLocator = field(repr=False)
    byte_size: int
    last_modified: datetime

    def __post_init__(self) -> None:
        strict_int(self.byte_size, 0, MAX_BYTES + 36)
        _date(self.last_modified)


@dataclass(frozen=True, slots=True)
class MultipartEntry:
    locator: ObjectLocator = field(repr=False)
    upload_id: str = field(repr=False)
    initiated_at: datetime

    def __post_init__(self) -> None:
        opaque_valid(self.upload_id)
        _date(self.initiated_at)


@dataclass(frozen=True, slots=True)
class ObjectPage:
    items: tuple[ObjectEntry, ...]
    next_cursor: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > 100
            or any(not isinstance(x, ObjectEntry) for x in self.items)
        ):
            raise ValueError("invalid page")
        if self.next_cursor is not None:
            opaque_valid(self.next_cursor, 4096)


@dataclass(frozen=True, slots=True)
class MultipartPage:
    items: tuple[MultipartEntry, ...]
    next_cursor: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > 100
            or any(not isinstance(x, MultipartEntry) for x in self.items)
        ):
            raise ValueError("invalid page")
        if self.next_cursor is not None:
            opaque_valid(self.next_cursor, 4096)


@dataclass(frozen=True, slots=True)
class CleanupWork:
    id: UUID
    locator: ObjectLocator = field(repr=False)
    operation: Literal["DELETE_OBJECT", "ABORT_MULTIPART"]
    multipart_id: str | None = field(repr=False)
    lease: AssetLease = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.id)
        if (
            self.operation not in ("DELETE_OBJECT", "ABORT_MULTIPART")
            or self.lease.token is None
        ):
            raise ValueError("invalid cleanup capability")
        strict_int(self.lease.remaining_ms, 1, 30000)
        if (self.multipart_id is not None) != (self.operation == "ABORT_MULTIPART"):
            raise ValueError("invalid cleanup operation")
        if self.multipart_id is not None:
            opaque_valid(self.multipart_id)


class CiphertextReader(Protocol):
    def read(self, max_bytes: int) -> bytes: ...
    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class S3Credentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None

    def __post_init__(self) -> None:
        opaque_valid(self.access_key_id, 4096)
        opaque_valid(self.secret_access_key, 4096)
        if self.session_token is not None:
            opaque_valid(self.session_token, 8192)


def endpoint_origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.hostname or "",
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


@dataclass(frozen=True, slots=True, repr=False)
class S3RuntimeConfig:
    endpoint_url: str
    region: str
    credentials: S3Credentials
    namespace: InstallationNamespace
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.endpoint_url) is not str
            or len(self.endpoint_url) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in self.endpoint_url)
            or "?" in self.endpoint_url
            or "#" in self.endpoint_url
        ):
            raise ValueError("invalid endpoint")
        p = urlsplit(self.endpoint_url)
        origin = endpoint_origin(self.endpoint_url)
        if (
            not p.hostname
            or p.username is not None
            or p.password is not None
            or p.query
            or p.fragment
            or p.path not in ("", "/")
            or p.scheme not in ("http", "https")
            or type(self.allow_loopback_http) is not bool
            or (p.port is not None and not 1 <= p.port <= 65535)
            or not isinstance(self.credentials, S3Credentials)
            or not isinstance(self.namespace, InstallationNamespace)
        ):
            raise ValueError("invalid endpoint")
        if p.scheme == "http" and not (
            self.allow_loopback_http and origin[1] in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("TLS endpoint required")
        if (
            type(self.region) is not str
            or re.fullmatch(r"[a-z0-9-]{1,64}", self.region) is None
        ):
            raise ValueError("invalid region")


@dataclass(frozen=True, slots=True, repr=False)
class S3Command:
    locator: ObjectLocator | None = None
    upload_id: str | None = None
    part_number: int | None = None
    body: bytes | None = None
    parts: tuple[UploadedPart, ...] = ()
    cursor: str | None = None
    limit: int | None = None
    expires_seconds: int | None = None
    max_bytes: int | None = None


type S3Result = (
    None | bytes | str | ObjectHead | UploadedPart | ObjectPage | MultipartPage
)


def validate_command(
    operation: S3Operation, args: S3Command, namespace: InstallationNamespace
) -> None:
    allowed = {
        "PUT": {"locator", "body"},
        "GET": {"locator", "max_bytes"},
        "HEAD": {"locator"},
        "DELETE": {"locator"},
        "CREATE_MULTIPART": {"locator"},
        "UPLOAD_PART": {"locator", "upload_id", "part_number", "body"},
        "COMPLETE_MULTIPART": {"locator", "upload_id", "parts"},
        "ABORT_MULTIPART": {"locator", "upload_id"},
        "LIST_OBJECTS": {"locator", "cursor", "limit"},
        "LIST_MULTIPART": {"locator", "cursor", "limit"},
        "PRESIGN_GET": {"locator", "expires_seconds"},
    }
    try:
        names = allowed[operation]
        if not isinstance(args, S3Command) or any(
            getattr(args, f.name) != (() if f.name == "parts" else None)
            for f in fields(args)
            if f.name not in names
        ):
            raise ValueError()
        if operation not in ("LIST_OBJECTS", "LIST_MULTIPART") and args.locator is None:
            raise ValueError()
        if args.locator is not None and (
            not isinstance(args.locator, ObjectLocator)
            or args.locator.installation_id != namespace.installation_id
        ):
            raise ValueError()
        if "upload_id" in names:
            opaque_valid(args.upload_id)  # type: ignore[arg-type]
        if "body" in names and (
            type(args.body) is not bytes
            or not 1
            <= len(args.body)
            <= (PART_BYTES if operation == "UPLOAD_PART" else PART_BYTES + 36)
        ):
            raise ValueError()
        if "part_number" in names:
            strict_int(args.part_number, 1, 10000)  # type: ignore[arg-type]
        if "parts" in names and (
            type(args.parts) is not tuple
            or not 1 <= len(args.parts) <= 10000
            or any(not isinstance(p, UploadedPart) for p in args.parts)
            or tuple(p.part_number for p in args.parts)
            != tuple(range(1, len(args.parts) + 1))
        ):
            raise ValueError()
        if args.cursor is not None:
            opaque_valid(args.cursor, 4096)
        if "limit" in names:
            strict_int(args.limit, 1, 100)  # type: ignore[arg-type]
        if "max_bytes" in names:
            strict_int(args.max_bytes, 1, MAX_BYTES + 36)  # type: ignore[arg-type]
        if "expires_seconds" in names:
            strict_int(args.expires_seconds, 1, 30)  # type: ignore[arg-type]
    except (KeyError, ValueError, TypeError, AttributeError):
        raise StorageFailure("INTEGRITY") from None


class S3ClientProtocol(Protocol):
    def local_cleanup_complete(self) -> bool: ...

    def execute(
        self, operation: S3Operation, args: S3Command, *, budget: IOBudget
    ) -> S3Result: ...


class SpawnS3Client:
    def __init__(self, *, config: S3RuntimeConfig) -> None:
        self._config = config

    def local_cleanup_complete(self) -> bool:
        from wso_core.asset_process import local_cleanup_complete

        return local_cleanup_complete()

    def execute(
        self, operation: S3Operation, args: S3Command, *, budget: IOBudget
    ) -> S3Result:
        from wso_core.asset_s3_worker import execute_owned

        validate_command(operation, args, self._config.namespace)
        return execute_owned(self._config, operation, args, budget)


class _MemoryReader:
    def __init__(self, data: bytes, budget: IOBudget) -> None:
        self._data = data
        self._position = 0
        self._budget = budget
        self._closed = False

    def read(self, max_bytes: int) -> bytes:
        strict_int(max_bytes, 1, CHUNK_BYTES)
        if self._closed:
            raise StorageFailure("INTEGRITY")
        self._budget.remaining_seconds()
        result = self._data[self._position : self._position + max_bytes]
        self._position += len(result)
        return result

    def close(self) -> None:
        self._closed = True
        self._data = b""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class PrivateObjectStore(Protocol):
    namespace: InstallationNamespace

    def local_cleanup_complete(self) -> bool: ...

    def put(
        self, locator: ObjectLocator, ciphertext: bytes, *, budget: IOBudget
    ) -> None: ...
    def get(
        self, locator: ObjectLocator, *, max_bytes: int, budget: IOBudget
    ) -> CiphertextReader: ...
    def head(self, locator: ObjectLocator, *, budget: IOBudget) -> ObjectHead: ...
    def delete(self, locator: ObjectLocator, *, budget: IOBudget) -> None: ...
    def create_multipart(self, locator: ObjectLocator, *, budget: IOBudget) -> str: ...
    def upload_part(
        self,
        locator: ObjectLocator,
        upload_id: str,
        part_number: int,
        ciphertext: bytes,
        *,
        budget: IOBudget,
    ) -> UploadedPart: ...
    def complete_multipart(
        self,
        locator: ObjectLocator,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
        *,
        budget: IOBudget,
    ) -> None: ...
    def abort_multipart(
        self, locator: ObjectLocator, upload_id: str, *, budget: IOBudget
    ) -> None: ...
    def list_objects(
        self,
        *,
        locator: ObjectLocator | None = None,
        cursor: str | None = None,
        limit: int = 100,
        budget: IOBudget,
    ) -> ObjectPage: ...
    def list_multipart(
        self,
        *,
        locator: ObjectLocator | None = None,
        cursor: str | None = None,
        limit: int = 100,
        budget: IOBudget,
    ) -> MultipartPage: ...
    def presign(
        self, locator: ObjectLocator, *, expires_seconds: int, budget: IOBudget
    ) -> str: ...


class S3ObjectStore:
    def __init__(
        self, *, client: S3ClientProtocol, namespace: InstallationNamespace
    ) -> None:
        self.namespace = namespace
        self._client = client

    def local_cleanup_complete(self) -> bool:
        return self._client.local_cleanup_complete()

    def _call(self, op: S3Operation, args: S3Command, budget: IOBudget) -> S3Result:
        validate_command(op, args, self.namespace)
        budget.remaining_seconds()
        result = self._client.execute(op, args, budget=budget)
        variants = {
            "PUT": type(None),
            "DELETE": type(None),
            "COMPLETE_MULTIPART": type(None),
            "ABORT_MULTIPART": type(None),
            "GET": bytes,
            "HEAD": ObjectHead,
            "CREATE_MULTIPART": str,
            "UPLOAD_PART": UploadedPart,
            "LIST_OBJECTS": ObjectPage,
            "LIST_MULTIPART": MultipartPage,
            "PRESIGN_GET": str,
        }
        if type(result) is not variants[op]:
            raise StorageFailure(
                "INTEGRITY",
                outcome_unknown=op
                in (
                    "PUT",
                    "DELETE",
                    "CREATE_MULTIPART",
                    "UPLOAD_PART",
                    "COMPLETE_MULTIPART",
                    "ABORT_MULTIPART",
                ),
            )
        try:
            budget.remaining_seconds()
        except StorageFailure:
            raise StorageFailure(
                "DEADLINE",
                outcome_unknown=op
                in (
                    "PUT",
                    "DELETE",
                    "CREATE_MULTIPART",
                    "UPLOAD_PART",
                    "COMPLETE_MULTIPART",
                    "ABORT_MULTIPART",
                ),
            ) from None
        return result

    def put(
        self, locator: ObjectLocator, ciphertext: bytes, *, budget: IOBudget
    ) -> None:
        self._call("PUT", S3Command(locator=locator, body=ciphertext), budget)

    def get(
        self, locator: ObjectLocator, *, max_bytes: int, budget: IOBudget
    ) -> CiphertextReader:
        result = self._call(
            "GET", S3Command(locator=locator, max_bytes=max_bytes), budget
        )
        assert isinstance(result, bytes)
        if len(result) > max_bytes:
            raise StorageFailure("LIMIT")
        return _MemoryReader(result, budget)

    def head(self, locator: ObjectLocator, *, budget: IOBudget) -> ObjectHead:
        result = self._call("HEAD", S3Command(locator=locator), budget)
        assert isinstance(result, ObjectHead)
        return result

    def delete(self, locator: ObjectLocator, *, budget: IOBudget) -> None:
        self._call("DELETE", S3Command(locator=locator), budget)

    def create_multipart(self, locator: ObjectLocator, *, budget: IOBudget) -> str:
        result = self._call("CREATE_MULTIPART", S3Command(locator=locator), budget)
        assert isinstance(result, str)
        try:
            opaque_valid(result)
        except ValueError:
            raise StorageFailure("INTEGRITY", outcome_unknown=True) from None
        return result

    def upload_part(
        self,
        locator: ObjectLocator,
        upload_id: str,
        part_number: int,
        ciphertext: bytes,
        *,
        budget: IOBudget,
    ) -> UploadedPart:
        result = self._call(
            "UPLOAD_PART",
            S3Command(
                locator=locator,
                upload_id=upload_id,
                part_number=part_number,
                body=ciphertext,
            ),
            budget,
        )
        assert isinstance(result, UploadedPart)
        if result.part_number != part_number:
            raise StorageFailure("INTEGRITY", outcome_unknown=True)
        return result

    def complete_multipart(
        self,
        locator: ObjectLocator,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
        *,
        budget: IOBudget,
    ) -> None:
        self._call(
            "COMPLETE_MULTIPART",
            S3Command(locator=locator, upload_id=upload_id, parts=parts),
            budget,
        )

    def abort_multipart(
        self, locator: ObjectLocator, upload_id: str, *, budget: IOBudget
    ) -> None:
        self._call(
            "ABORT_MULTIPART", S3Command(locator=locator, upload_id=upload_id), budget
        )

    def list_objects(
        self,
        *,
        locator: ObjectLocator | None = None,
        cursor: str | None = None,
        limit: int = 100,
        budget: IOBudget,
    ) -> ObjectPage:
        result = self._call(
            "LIST_OBJECTS",
            S3Command(locator=locator, cursor=cursor, limit=limit),
            budget,
        )
        assert isinstance(result, ObjectPage)
        self._check_page(result.items, locator)
        return result

    def list_multipart(
        self,
        *,
        locator: ObjectLocator | None = None,
        cursor: str | None = None,
        limit: int = 100,
        budget: IOBudget,
    ) -> MultipartPage:
        result = self._call(
            "LIST_MULTIPART",
            S3Command(locator=locator, cursor=cursor, limit=limit),
            budget,
        )
        assert isinstance(result, MultipartPage)
        self._check_page(result.items, locator)
        return result

    def _check_page(
        self,
        items: tuple[ObjectEntry, ...] | tuple[MultipartEntry, ...],
        locator: ObjectLocator | None,
    ) -> None:
        if any(
            x.locator.installation_id != self.namespace.installation_id
            or (locator is not None and x.locator != locator)
            for x in items
        ):
            raise StorageFailure("INTEGRITY")

    def presign(
        self, locator: ObjectLocator, *, expires_seconds: int, budget: IOBudget
    ) -> str:
        result = self._call(
            "PRESIGN_GET",
            S3Command(locator=locator, expires_seconds=expires_seconds),
            budget,
        )
        assert isinstance(result, str)
        return result
