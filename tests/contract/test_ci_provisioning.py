"""The CI bootstrap must refuse shared databases before any mutation."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/dev/provision-ci-postgres.py"
OWNER = "a" * 32
ADMIN = "postgresql+psycopg://postgres:fixture-secret@127.0.0.1:55432/wso_ci_test"


@pytest.fixture
def provisioning():
    assert SCRIPT.is_file(), "CI provisioning implementation is missing"
    spec = importlib.util.spec_from_file_location("ci_provisioning", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://postgres:secret@192.0.2.1:55432/wso_ci_test",
        "postgresql+psycopg://postgres:secret@localhost:55432/wso_ci_test",
        "postgresql+psycopg://postgres:secret@127.0.0.1:55432/wso_test",
        "postgresql+psycopg://postgres:secret@127.0.0.1:55432/postgres",
        "postgresql+psycopg://postgres:secret@127.0.0.1/wso_ci_test",
        "postgresql+psycopg://wso_app:secret@127.0.0.1:55432/wso_ci_test",
        "postgresql+psycopg://postgres@127.0.0.1:55432/wso_ci_test",
        "postgresql://postgres:secret@127.0.0.1:55432/wso_ci_test",
        ADMIN + "?host=192.0.2.1",
        ADMIN + "\nINJECTED=value",
        "not-a-url",
    ],
)
def test_refuses_shared_or_redirected_database_urls(provisioning, url):
    with pytest.raises(ValueError):
        provisioning.parse_admin_url(url, ci="true", disposable="1")


@pytest.mark.parametrize("ci,disposable", [("", "1"), ("false", "1"), ("true", "")])
def test_requires_both_ci_and_disposable_opt_in(provisioning, ci, disposable):
    with pytest.raises(ValueError):
        provisioning.parse_admin_url(ADMIN, ci=ci, disposable=disposable)


def test_accepts_explicit_loopback_disposable_admin_url(provisioning):
    url = provisioning.parse_admin_url(ADMIN, ci="true", disposable="1")
    assert (url.host, url.port, url.database) == ("127.0.0.1", 55432, "wso_ci_test")


def clean_database():
    return {
        "database": "wso_ci_test",
        "user": "postgres",
        "owner": "postgres",
        "superuser": True,
        "version": 170011,
        "schemas": ["public"],
        "objects": 0,
        "extensions": ["plpgsql"],
        "databases": ["postgres", "wso_ci_test"],
        "custom_roles": ["postgres"],
    }


def test_accepts_only_fresh_dedicated_postgres_cluster(provisioning):
    provisioning.assert_fresh_database(clean_database())


@pytest.mark.parametrize(
    "field,value",
    [
        ("database", "wso_test"),
        ("user", "other"),
        ("owner", "other"),
        ("superuser", False),
        ("version", 170010),
        ("schemas", ["public", "wso_private"]),
        ("objects", 1),
        ("extensions", ["plpgsql", "other"]),
        ("databases", ["postgres", "wso_ci_test", "business"]),
        ("custom_roles", ["postgres", "wso_app"]),
    ],
)
def test_existing_schema_roles_or_wrong_cluster_abort(provisioning, field, value):
    state = clean_database()
    state[field] = value
    with pytest.raises(ValueError):
        provisioning.assert_fresh_database(state)


def owned_container():
    return {
        "Name": f"/wso-ci-postgres-{OWNER}",
        "Config": {
            "Labels": {"wso.ci.owner": OWNER},
            "Image": "postgres@sha256:" + "b" * 64,
        },
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}],
            }
        },
    }


def test_requires_owned_running_container_on_the_same_endpoint(provisioning):
    url = provisioning.parse_admin_url(ADMIN, ci="true", disposable="1")
    provisioning.assert_owned_container(owned_container(), OWNER, url)
    for mutate in (
        lambda data: data["Config"]["Labels"].update({"wso.ci.owner": "other"}),
        lambda data: data.update({"Name": "/unrelated"}),
        lambda data: data["State"].update({"Running": False}),
        lambda data: data["Config"].update({"Image": "postgres:17"}),
        lambda data: data["NetworkSettings"]["Ports"].update(
            {
                "5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "55432"}],
            }
        ),
        lambda data: data["NetworkSettings"]["Ports"].update(
            {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}],
            }
        ),
    ):
        data = owned_container()
        mutate(data)
        with pytest.raises(ValueError):
            provisioning.assert_owned_container(data, OWNER, url)


def test_restricted_role_catalog_rejects_privileges_membership_and_missing_role(
    provisioning,
):
    safe = {role: (False,) * 6 + (True, 0) for role in provisioning.ROLES.values()}
    provisioning.assert_restricted_roles(safe)
    for index in range(8):
        rows = safe.copy()
        values = list(rows["wso_app"])
        values[index] = index != 6
        rows["wso_app"] = tuple(values)
        with pytest.raises(ValueError):
            provisioning.assert_restricted_roles(rows)
    with pytest.raises(ValueError):
        provisioning.assert_restricted_roles({})


def test_export_escapes_passwords_masks_all_secrets_and_writes_eight_urls(
    provisioning,
    tmp_path,
    capsys,
):
    url = provisioning.parse_admin_url(ADMIN, ci="true", disposable="1")
    output = tmp_path / "github-env"
    passwords = {role: f"different-{role}:/@%" for role in provisioning.ROLES.values()}
    provisioning.export_environment(url, passwords, output)
    lines = output.read_text().splitlines()
    assert len(lines) == 8
    assert lines[0] == "WSO_TEST_ADMIN_DATABASE_URL=" + ADMIN
    assert any("wso_app:different-wso_app%3A%2F%40%25@" in line for line in lines)
    masks = capsys.readouterr().out.splitlines()
    assert all(line.startswith("::add-mask::") for line in masks)
    assert "::add-mask::fixture-secret" in masks
    assert len(masks) == 16


def test_job_and_dispatch_logins_are_separate_required_runtime_roles(provisioning):
    assert provisioning.ROLES["DISPATCH"] == "wso_dispatcher"
    assert provisioning.ROLES["JOB"] == "wso_job_worker"
    assert len(set(provisioning.ROLES.values())) == 7
    safe = {role: (False,) * 6 + (True, 0) for role in provisioning.ROLES.values()}
    for role in ("wso_dispatcher", "wso_job_worker"):
        missing = safe.copy()
        del missing[role]
        with pytest.raises(ValueError):
            provisioning.assert_restricted_roles(missing)


def test_export_refuses_multiline_secret_before_writing_environment(
    provisioning,
    tmp_path,
):
    url = provisioning.parse_admin_url(ADMIN, ci="true", disposable="1")
    output = tmp_path / "github-env"
    passwords = {role: "safe" for role in provisioning.ROLES.values()}
    passwords["wso_app"] = "secret\nINJECTED=1"
    with pytest.raises(ValueError):
        provisioning.export_environment(url, passwords, output)
    assert not output.exists()


def test_cli_refusal_is_sanitized_and_has_no_driver_trace(provisioning):
    env = {
        **os.environ,
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_CI_ADMIN_DATABASE_URL": ADMIN.replace("wso_ci_test", "wso_test"),
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "refused or failed" in result.stderr
    assert "fixture-secret" not in result.stdout + result.stderr
    assert "postgresql" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
