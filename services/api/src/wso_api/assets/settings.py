"""Explicit private asset startup configuration; no environment or I/O lookup."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from wso_core.storage import (
    InstallationNamespace,
    S3Credentials,
    S3RuntimeConfig,
    key_id_valid,
    opaque_valid,
)


def _role_url(value: str, role: str) -> None:
    if type(value) is not str or not 1 <= len(value) <= 8192:
        raise ValueError("invalid private database configuration")
    try:
        url = make_url(value)
        port = url.port
    except (ArgumentError, ValueError):
        raise ValueError("invalid private database configuration") from None
    if (
        url.drivername != "postgresql+psycopg"
        or url.username != role
        or not url.password
        or not url.host
        or any(character in url.host for character in " /,\\\t\r\n")
        or not url.database
        or (port is not None and not 1 <= port <= 65535)
        or set(url.query)
        - {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout"}
    ):
        raise ValueError("invalid private database configuration")


def _key_mapping(value: Mapping[str, Path]) -> Mapping[str, Path]:
    if not 1 <= len(value) <= 32:
        raise ValueError("invalid private key configuration")
    result: dict[str, Path] = {}
    for identifier, path in value.items():
        key_id_valid(identifier)
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or len(str(path)) > 2048
        ):
            raise ValueError("invalid private key configuration")
        if any(ord(character) < 32 or ord(character) == 127 for character in str(path)):
            raise ValueError("invalid private key configuration")
        result[identifier] = path
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class AssetSettings:
    app_database_url: str
    s3: S3RuntimeConfig
    active_key_id: str
    key_files: Mapping[str, Path]

    def __post_init__(self) -> None:
        _role_url(self.app_database_url, "wso_app")
        key_id_valid(self.active_key_id)
        if not isinstance(self.s3, S3RuntimeConfig):
            raise TypeError("invalid private object configuration")
        keys = _key_mapping(self.key_files)
        if self.active_key_id not in keys:
            raise ValueError("active private key is absent")
        object.__setattr__(self, "key_files", keys)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class AssetMaintenanceSettings:
    maintenance_database_url: str
    s3: S3RuntimeConfig
    worker_id: str

    def __post_init__(self) -> None:
        _role_url(self.maintenance_database_url, "wso_asset_maintenance")
        if not isinstance(self.s3, S3RuntimeConfig):
            raise TypeError("invalid private object configuration")
        opaque_valid(self.worker_id, 128)


def _required(env: Mapping[str, str], name: str) -> str:
    value = env[name]
    if type(value) is not str or not value:
        raise ValueError("private asset configuration is incomplete")
    return value


def _s3_settings(env: Mapping[str, str], *, maintenance: bool) -> S3RuntimeConfig:
    flag = env.get("WSO_ASSET_S3_ALLOW_LOOPBACK_HTTP", "0")
    if flag not in {"0", "1"} or (
        flag == "1"
        and not (
            env.get("CI") == "true" and env.get("WSO_CI_DISPOSABLE_POSTGRES") == "1"
        )
    ):
        raise ValueError("owned fixture configuration required")
    prefix = "WSO_ASSET_MAINTENANCE_S3" if maintenance else "WSO_ASSET_S3"
    return S3RuntimeConfig(
        endpoint_url=_required(env, "WSO_ASSET_S3_ENDPOINT_URL"),
        region=_required(env, "WSO_ASSET_S3_REGION"),
        credentials=S3Credentials(
            access_key_id=_required(env, prefix + "_ACCESS_KEY_ID"),
            secret_access_key=_required(env, prefix + "_SECRET_ACCESS_KEY"),
            session_token=env.get(prefix + "_SESSION_TOKEN"),
        ),
        namespace=InstallationNamespace(
            UUID(_required(env, "WSO_ASSET_INSTALLATION_ID")),
            _required(env, "WSO_ASSET_S3_BUCKET"),
        ),
        allow_loopback_http=flag == "1",
    )


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate private key identifier")
        result[key] = value
    return result


def _load_keys(value: str) -> dict[str, Path]:
    if len(value.encode("utf-8")) > 16384:
        raise ValueError("private key configuration exceeds size bound")
    decoded: object = json.loads(value, object_pairs_hook=_unique_keys)
    if not isinstance(decoded, dict) or not 1 <= len(decoded) <= 32:
        raise ValueError("invalid private key configuration")
    keys: dict[str, Path] = {}
    for identifier, path in decoded.items():
        if type(identifier) is not str or type(path) is not str or not path:
            raise ValueError("invalid private key configuration")
        keys[identifier] = Path(path)
    return keys


def load_asset_settings(env: Mapping[str, str]) -> AssetSettings:
    try:
        return AssetSettings(
            app_database_url=_required(env, "WSO_APP_DATABASE_URL"),
            s3=_s3_settings(env, maintenance=False),
            active_key_id=_required(env, "WSO_ASSET_ACTIVE_KEY_ID"),
            key_files=_load_keys(_required(env, "WSO_ASSET_KEY_FILES_JSON")),
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("invalid private asset startup configuration") from None


def load_asset_maintenance_settings(env: Mapping[str, str]) -> AssetMaintenanceSettings:
    try:
        return AssetMaintenanceSettings(
            maintenance_database_url=_required(
                env, "WSO_ASSET_MAINTENANCE_DATABASE_URL"
            ),
            s3=_s3_settings(env, maintenance=True),
            worker_id=_required(env, "WSO_ASSET_MAINTENANCE_WORKER_ID"),
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("invalid private asset startup configuration") from None
