"""Startup parsers cannot leak secrets, borrow ambient values or read key files."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from wso_api.assets.settings import (
    AssetMaintenanceSettings,
    AssetSettings,
    load_asset_maintenance_settings,
    load_asset_settings,
)


def configuration(tmp_path, *, maintenance=False):
    prefix = "WSO_ASSET_MAINTENANCE_S3" if maintenance else "WSO_ASSET_S3"
    result = {
        "WSO_ASSET_INSTALLATION_ID": "10000000-0000-4000-8000-000000000001",
        "WSO_ASSET_S3_BUCKET": "wso-private-fixture",
        "WSO_ASSET_S3_ENDPOINT_URL": "https://storage.example.test",
        "WSO_ASSET_S3_REGION": "us-east-1",
        prefix + "_ACCESS_KEY_ID": "PRIVATE_ACCESS_SENTINEL",
        prefix + "_SECRET_ACCESS_KEY": "PRIVATE_SECRET_SENTINEL",
    }
    if maintenance:
        result["WSO_ASSET_MAINTENANCE_DATABASE_URL"] = (
            "postgresql+psycopg://wso_asset_maintenance:PRIVATE_DB_SENTINEL@localhost/wso"
        )
        result["WSO_ASSET_MAINTENANCE_WORKER_ID"] = "cleanup-worker-1"
    else:
        result["WSO_APP_DATABASE_URL"] = (
            "postgresql+psycopg://wso_app:PRIVATE_DB_SENTINEL@localhost/wso"
        )
        result["WSO_ASSET_ACTIVE_KEY_ID"] = "K2"
        result["WSO_ASSET_KEY_FILES_JSON"] = json.dumps(
            {"K1": str(tmp_path / "old-key"), "K2": str(tmp_path / "active-key")}
        )
    return result


def test_api_settings_parse_without_opening_missing_key_files(tmp_path):
    settings = load_asset_settings(configuration(tmp_path))
    assert settings.active_key_id == "K2"
    assert set(settings.key_files) == {"K1", "K2"}
    assert not settings.key_files["K1"].exists()
    assert (
        settings.s3.namespace.installation_id.hex == "10000000000040008000000000000001"
    )
    assert settings.s3.credentials.secret_access_key == "PRIVATE_SECRET_SENTINEL"
    assert settings.s3.allow_loopback_http is False
    assert "PRIVATE_" not in repr(settings)


def test_maintenance_settings_need_no_api_credential_or_key_fields(tmp_path):
    settings = load_asset_maintenance_settings(
        configuration(tmp_path, maintenance=True)
    )
    assert settings.worker_id == "cleanup-worker-1"
    assert settings.s3.credentials.access_key_id == "PRIVATE_ACCESS_SENTINEL"
    assert "PRIVATE_" not in repr(settings)
    assert not hasattr(settings, "key_files")


def test_settings_and_key_mapping_cannot_be_mutated(tmp_path):
    settings = load_asset_settings(configuration(tmp_path))
    with pytest.raises(FrozenInstanceError):
        settings.active_key_id = "K1"
    with pytest.raises(TypeError):
        settings.key_files["K3"] = tmp_path / "third"


@pytest.mark.parametrize("maintenance", [False, True])
def test_missing_field_never_uses_ambient_secret(tmp_path, monkeypatch, maintenance):
    env = configuration(tmp_path, maintenance=maintenance)
    prefix = "WSO_ASSET_MAINTENANCE_S3" if maintenance else "WSO_ASSET_S3"
    missing = prefix + "_SECRET_ACCESS_KEY"
    monkeypatch.setenv(missing, env.pop(missing))
    loader = load_asset_maintenance_settings if maintenance else load_asset_settings
    with pytest.raises(ValueError) as rejected:
        loader(env)
    assert "PRIVATE_" not in str(rejected.value)


@pytest.mark.parametrize(
    "value",
    [
        '{"K2":"relative-key"}',
        '{"K2":"https://private.example/key"}',
        '{"K1":"/missing-key"}',
        '{"K2":"/first","K2":"/second"}',
        "[]",
        '{"bad key":"/key"}',
        '{"K2":123}',
        "PRIVATE_JSON_SENTINEL",
        " " * 16385,
    ],
)
def test_key_map_malformed_duplicate_or_missing_active_key_is_refused(tmp_path, value):
    env = configuration(tmp_path)
    env["WSO_ASSET_KEY_FILES_JSON"] = value
    with pytest.raises(ValueError) as rejected:
        load_asset_settings(env)
    assert "PRIVATE_" not in str(rejected.value)


@pytest.mark.parametrize("maintenance", [False, True])
def test_loopback_http_requires_explicit_owned_ci_configuration(tmp_path, maintenance):
    env = configuration(tmp_path, maintenance=maintenance)
    env["WSO_ASSET_S3_ENDPOINT_URL"] = "http://127.0.0.1:19000"
    env["WSO_ASSET_S3_ALLOW_LOOPBACK_HTTP"] = "1"
    loader = load_asset_maintenance_settings if maintenance else load_asset_settings
    with pytest.raises(ValueError):
        loader(env)
    env.update(CI="true", WSO_CI_DISPOSABLE_POSTGRES="1")
    assert loader(env).s3.allow_loopback_http is True


@pytest.mark.parametrize("maintenance", [False, True])
def test_role_url_and_query_cannot_redirect_database_authority(tmp_path, maintenance):
    env = configuration(tmp_path, maintenance=maintenance)
    name = (
        "WSO_ASSET_MAINTENANCE_DATABASE_URL" if maintenance else "WSO_APP_DATABASE_URL"
    )
    env[name] += "?user=postgres&host=foreign.example"
    loader = load_asset_maintenance_settings if maintenance else load_asset_settings
    with pytest.raises(ValueError) as rejected:
        loader(env)
    assert "PRIVATE_" not in str(rejected.value)


@pytest.mark.parametrize("maintenance", [False, True])
@pytest.mark.parametrize(
    "value",
    [
        "PRIVATE_DATABASE_SENTINEL",
        "postgresql+psycopg://postgres:PRIVATE_PASSWORD_SENTINEL@localhost/wso",
        "postgresql+psycopg://wso_app@localhost/wso",
    ],
)
def test_invalid_database_url_is_sanitized_value_error(tmp_path, maintenance, value):
    env = configuration(tmp_path, maintenance=maintenance)
    name = (
        "WSO_ASSET_MAINTENANCE_DATABASE_URL" if maintenance else "WSO_APP_DATABASE_URL"
    )
    env[name] = value
    loader = load_asset_maintenance_settings if maintenance else load_asset_settings
    with pytest.raises(ValueError) as rejected:
        loader(env)
    assert "PRIVATE_" not in str(rejected.value)


@pytest.mark.parametrize("maintenance", [False, True])
def test_explicit_settings_constructor_sanitizes_malformed_port(tmp_path, maintenance):
    api = load_asset_settings(configuration(tmp_path))
    s3 = api.s3
    database_url = (
        "postgresql+psycopg://wso_asset_maintenance:PRIVATE_PASSWORD@localhost:PRIVATE_PORT_SENTINEL/wso"
        if maintenance
        else "postgresql+psycopg://wso_app:PRIVATE_PASSWORD@localhost:PRIVATE_PORT_SENTINEL/wso"
    )

    with pytest.raises(ValueError) as rejected:
        if maintenance:
            AssetMaintenanceSettings(
                maintenance_database_url=database_url,
                s3=s3,
                worker_id="cleanup-worker-1",
            )
        else:
            AssetSettings(
                app_database_url=database_url,
                s3=s3,
                active_key_id="K2",
                key_files={"K2": Path(tmp_path / "active-key")},
            )

    assert "PRIVATE_PORT_SENTINEL" not in str(rejected.value)
    assert rejected.value.__suppress_context__ is True


def test_explicit_settings_constructor_rejects_del_in_key_path(tmp_path):
    api = load_asset_settings(configuration(tmp_path))

    with pytest.raises(ValueError):
        AssetSettings(
            app_database_url=configuration(tmp_path)["WSO_APP_DATABASE_URL"],
            s3=api.s3,
            active_key_id="K2",
            key_files={"K2": Path(f"{tmp_path}{chr(127)}key")},
        )
