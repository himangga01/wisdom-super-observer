"""Independent full14 payload and restricted child-environment contracts."""

import json

import pytest


def owned_source(directory) -> dict[str, str]:
    return {
        "PATH": "synthetic-public-path",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(directory),
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_TEST_ADMIN_DATABASE_URL": "postgresql+psycopg://postgres:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_APP_DATABASE_URL": "postgresql+psycopg://wso_app:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_IDENTITY_DATABASE_URL": "postgresql+psycopg://wso_identity_bootstrap:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_SESSION_DATABASE_URL": "postgresql+psycopg://wso_web_session:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_MIGRATOR_DATABASE_URL": "postgresql+psycopg://wso_migrator:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_WORKER_DATABASE_URL": "postgresql+psycopg://wso_connection_worker:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_DISPATCH_DATABASE_URL": "postgresql+psycopg://wso_dispatcher:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_JOB_DATABASE_URL": "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL": "postgresql+psycopg://wso_asset_maintenance:synthetic@127.0.0.1:5432/fixture_db",
        "AWS_SECRET_ACCESS_KEY": "unrelated-synthetic-canary",
        "PYTHONPATH": "unrelated-synthetic-import-path",
    }


def owned_spec(directory):
    from uuid import UUID

    from wso_core.storage import InstallationNamespace, S3Credentials

    from tests.support.asset_process import ProcessSpec

    return ProcessSpec(
        owner="synthetic-owner",
        private_directory=directory,
        control_path=directory / "control.json",
        namespace=InstallationNamespace(UUID(int=1), "fixture-bucket"),
        endpoint_url="http://127.0.0.1:9000",
        region="us-east-1",
        gateway=S3Credentials("synthetic-gateway", "synthetic-gateway-secret"),
        maintenance=S3Credentials(
            "synthetic-maintenance", "synthetic-maintenance-secret"
        ),
        key_files={"fixture-key": directory / "fixture.key"},
        active_key_id="fixture-key",
        broker_url="redis://127.0.0.1:6379/0",
        worker_id="synthetic-worker",
    )


def test_job_process_env_excludes_api_admin_and_unrelated_secrets(tmp_path) -> None:
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_process import ProcessMode, build_process_env

    source = owned_source(tmp_path)
    before = dict(source)
    environment = build_process_env(
        ProcessMode.JOB_WORKER, source, owned_spec(tmp_path)
    )
    assert environment["WSO_TEST_JOB_DATABASE_URL"] == (
        "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:5432/fixture_db"
    )
    for forbidden in (
        "WSO_TEST_APP_DATABASE_URL",
        "WSO_TEST_IDENTITY_DATABASE_URL",
        "WSO_TEST_SESSION_DATABASE_URL",
        "WSO_APP_DATABASE_URL",
        "WSO_IDENTITY_DATABASE_URL",
        "WSO_SESSION_DATABASE_URL",
        "WSO_TEST_ADMIN_DATABASE_URL",
        "WSO_TEST_MIGRATOR_DATABASE_URL",
        "WSO_TEST_WORKER_DATABASE_URL",
        "AWS_SECRET_ACCESS_KEY",
        "PYTHONPATH",
    ):
        assert forbidden not in environment
    assert environment["WSO_ASSET_S3_ACCESS_KEY_ID"] == "synthetic-gateway"
    assert environment["WSO_ASSET_S3_SECRET_ACCESS_KEY"] == "synthetic-gateway-secret"
    assert json.loads(environment["WSO_ASSET_KEY_FILES_JSON"]) == {
        "fixture-key": str(tmp_path / "fixture.key")
    }
    assert environment["WSO_ASSET_FIXTURE_BROKER_URL"] == "redis://127.0.0.1:6379/0"
    assert environment["WSO_ASSET_FIXTURE_WORKER_ID"] == "synthetic-worker"
    assert source == before
    wrong_role = {
        **source,
        "WSO_TEST_JOB_DATABASE_URL": source["WSO_TEST_APP_DATABASE_URL"],
    }
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        build_process_env(ProcessMode.JOB_WORKER, wrong_role, owned_spec(tmp_path))


def expected_environment(mode, directory):
    common = {
        "PATH": "synthetic-public-path",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(directory),
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_ASSET_FIXTURE_OWNER": "synthetic-owner",
        "WSO_ASSET_FIXTURE_CONTROL": str(directory / "control.json"),
    }
    roles = {
        "WSO_APP_DATABASE_URL": "postgresql+psycopg://wso_app:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_IDENTITY_DATABASE_URL": "postgresql+psycopg://wso_identity_bootstrap:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_SESSION_DATABASE_URL": "postgresql+psycopg://wso_web_session:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_APP_DATABASE_URL": "postgresql+psycopg://wso_app:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_IDENTITY_DATABASE_URL": "postgresql+psycopg://wso_identity_bootstrap:synthetic@127.0.0.1:5432/fixture_db",
        "WSO_TEST_SESSION_DATABASE_URL": "postgresql+psycopg://wso_web_session:synthetic@127.0.0.1:5432/fixture_db",
    }
    s3 = {
        "WSO_ASSET_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
        "WSO_ASSET_S3_REGION": "us-east-1",
        "WSO_ASSET_S3_BUCKET": "fixture-bucket",
        "WSO_ASSET_INSTALLATION_ID": "00000000-0000-0000-0000-000000000001",
        "WSO_ASSET_S3_ALLOW_LOOPBACK_HTTP": "1",
    }
    gateway = {
        "WSO_ASSET_S3_ACCESS_KEY_ID": "synthetic-gateway",
        "WSO_ASSET_S3_SECRET_ACCESS_KEY": "synthetic-gateway-secret",
        "WSO_ASSET_ACTIVE_KEY_ID": "fixture-key",
        "WSO_ASSET_KEY_FILES_JSON": {"fixture-key": str(directory / "fixture.key")},
    }
    if mode in {"API", "PRODUCER"}:
        return common | roles | s3 | gateway
    if mode == "JOB_WORKER":
        return (
            common
            | s3
            | gateway
            | {
                "WSO_TEST_JOB_DATABASE_URL": "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:5432/fixture_db",
                "WSO_ASSET_FIXTURE_BROKER_URL": "redis://127.0.0.1:6379/0",
                "WSO_ASSET_FIXTURE_WORKER_ID": "synthetic-worker",
            }
        )
    if mode == "DISPATCH":
        return common | {
            "WSO_TEST_DISPATCH_DATABASE_URL": "postgresql+psycopg://wso_dispatcher:synthetic@127.0.0.1:5432/fixture_db",
            "WSO_ASSET_FIXTURE_BROKER_URL": "redis://127.0.0.1:6379/0",
        }
    return (
        common
        | s3
        | {
            "WSO_ASSET_MAINTENANCE_DATABASE_URL": "postgresql+psycopg://wso_asset_maintenance:synthetic@127.0.0.1:5432/fixture_db",
            "WSO_ASSET_MAINTENANCE_WORKER_ID": "synthetic-worker",
            "WSO_ASSET_MAINTENANCE_S3_ACCESS_KEY_ID": "synthetic-maintenance",
            "WSO_ASSET_MAINTENANCE_S3_SECRET_ACCESS_KEY": "synthetic-maintenance-secret",
        }
    )


@pytest.mark.parametrize(
    "mode", ["API", "PRODUCER", "JOB_WORKER", "DISPATCH", "MAINTENANCE", "RECONCILE"]
)
def test_each_mode_has_exact_owned_role_and_credential_custody(tmp_path, mode):
    from tests.support.asset_process import ProcessMode, build_process_env

    source = owned_source(tmp_path)
    before = dict(source)
    source.update(
        {
            "WSO_ASSET_S3_SECRET_ACCESS_KEY": "ambient-gateway-poison",
            "WSO_ASSET_MAINTENANCE_S3_SECRET_ACCESS_KEY": "ambient-maintenance-poison",
            "WSO_ASSET_ACTIVE_KEY_ID": "ambient-key-poison",
            "WSO_JOB_DATABASE_URL": "ambient-job-poison",
            "UNRELATED_TOKEN": "unrelated-synthetic-canary",
        }
    )
    supplied = dict(source)
    environment = build_process_env(ProcessMode(mode), source, owned_spec(tmp_path))
    if "WSO_ASSET_KEY_FILES_JSON" in environment:
        environment["WSO_ASSET_KEY_FILES_JSON"] = json.loads(
            environment["WSO_ASSET_KEY_FILES_JSON"]
        )
    assert environment == expected_environment(mode, tmp_path)
    assert source == supplied
    environment["CI"] = "changed-output"
    assert source["CI"] == before["CI"] == "true"


@pytest.mark.parametrize(
    "name",
    [
        "ADMIN",
        "APP",
        "IDENTITY",
        "SESSION",
        "MIGRATOR",
        "WORKER",
        "DISPATCH",
        "JOB",
        "ASSET_MAINTENANCE",
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-role",
        "foreign-host",
        "foreign-port",
        "foreign-db",
        "query",
        "fragment",
        "driver",
        "no-password",
        "missing",
        "native-type",
    ],
)
def test_all_nine_role_urls_are_validated_even_for_dispatch(tmp_path, name, mutation):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_process import ProcessMode, build_process_env

    source = owned_source(tmp_path)
    field = f"WSO_TEST_{name}_DATABASE_URL"
    value = source[field]
    if mutation == "wrong-role":
        source[field] = (
            "postgresql+psycopg://foreign_role:synthetic@127.0.0.1:5432/fixture_db"
        )
    elif mutation == "foreign-host":
        source[field] = value.replace("127.0.0.1", "localhost")
    elif mutation == "foreign-port":
        source[field] = value.replace(":5432/", ":5433/")
        if name == "ADMIN":
            source["WSO_TEST_APP_DATABASE_URL"] = source[
                "WSO_TEST_APP_DATABASE_URL"
            ].replace(":5432/", ":5434/")
    elif mutation == "foreign-db":
        source[field] = value.replace("fixture_db", "foreign_db")
        if name == "ADMIN":
            source["WSO_TEST_APP_DATABASE_URL"] = source[
                "WSO_TEST_APP_DATABASE_URL"
            ].replace("fixture_db", "another_db")
    elif mutation == "query":
        source[field] = value + "?sslmode=disable"
    elif mutation == "fragment":
        source[field] = value + "#fragment"
    elif mutation == "driver":
        source[field] = value.replace("postgresql+psycopg", "postgresql")
    elif mutation == "no-password":
        source[field] = value.replace(":synthetic@", "@")
    elif mutation == "missing":
        del source[field]
    else:
        source[field] = 7
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        build_process_env(ProcessMode.DISPATCH, source, owned_spec(tmp_path))


@pytest.mark.parametrize(
    "field,value",
    [
        ("CI", "True"),
        ("CI", "false"),
        ("WSO_CI_DISPOSABLE_POSTGRES", "0"),
        ("TMPDIR", "C:/outside-owned-fixture"),
    ],
)
def test_common_environment_requires_owned_ci_and_temp_directory(
    tmp_path, field, value
):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_process import ProcessMode, build_process_env

    with pytest.raises(FixtureContractError):
        build_process_env(
            ProcessMode.API,
            {**owned_source(tmp_path), field: value},
            owned_spec(tmp_path),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint_url", "http://localhost:9000"),
        ("endpoint_url", "http://127.0.0.2:9000"),
        ("endpoint_url", "https://127.0.0.1:9000"),
        ("endpoint_url", "http://127.0.0.1:9000/other"),
        ("endpoint_url", "http://127.0.0.1:9000?query"),
        ("broker_url", "redis://localhost:6379/0"),
        ("broker_url", "redis://127.0.0.1:6379/0#fragment"),
        ("owner", ""),
        ("owner", "owner\n"),
        ("owner", "é"),
        ("active_key_id", "absent-key"),
    ],
)
def test_process_spec_refuses_unowned_origins_and_authority(tmp_path, field, value):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        replace(owned_spec(tmp_path), **{field: value})


def test_process_spec_copies_key_mapping_and_confines_paths(tmp_path):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_process import ProcessMode, build_process_env

    keys = {"fixture-key": tmp_path / "fixture.key"}
    spec = replace(owned_spec(tmp_path), key_files=keys)
    keys.clear()
    result = build_process_env(ProcessMode.JOB_WORKER, owned_source(tmp_path), spec)
    assert json.loads(result["WSO_ASSET_KEY_FILES_JSON"]) == {
        "fixture-key": str(tmp_path / "fixture.key")
    }
    with pytest.raises(TypeError):
        spec.key_files["extra"] = tmp_path / "extra.key"
    for fields in (
        {"control_path": tmp_path.parent / "outside-control.json"},
        {"key_files": {"fixture-key": tmp_path.parent / "outside.key"}},
    ):
        with pytest.raises(FixtureContractError):
            replace(spec, **fields)


PAYLOAD = {
    "schema_version": 1,
    "operation_id": "00000000-0000-0000-0000-000000000005",
    "asset_id": "00000000-0000-0000-0000-000000000003",
}


@pytest.mark.parametrize("checkpoint", ["none", "after-read", "after-commit"])
def test_payload_roundtrips_only_native_public_fields(checkpoint):
    from tests.support.asset_job_handlers import AssetReadPayload

    expected = {**PAYLOAD, "checkpoint": checkpoint}
    model = AssetReadPayload.model_validate(expected)
    assert model.model_dump(mode="json") == expected
    assert json.loads(model.model_dump_json()) == expected
    assert (
        AssetReadPayload.model_validate_json(json.dumps(expected)).model_dump(
            mode="json"
        )
        == expected
    )
    assert AssetReadPayload.model_validate(PAYLOAD).checkpoint == "none"


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", "1"),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("operation_id", "00000000-0000-0000-0000-000000000000"),
        ("asset_id", "00000000-0000-0000-0000-000000000000"),
        ("asset_id", "invalid-uuid"),
        ("checkpoint", "after-part"),
        ("checkpoint", None),
        ("tenant_id", "00000000-0000-0000-0000-000000000007"),
        ("purpose", "PHOTO"),
        ("database_url", "synthetic-private-selector"),
        ("credential", "synthetic-private-selector"),
        ("plaintext", "synthetic-private-bytes"),
    ],
)
def test_payload_refuses_coercion_nil_and_authority_fields(field, value):
    from pydantic import ValidationError

    from tests.support.asset_job_handlers import AssetReadPayload

    with pytest.raises(ValidationError):
        AssetReadPayload.model_validate({**PAYLOAD, field: value})
    with pytest.raises(ValidationError):
        AssetReadPayload.model_validate_json(json.dumps({**PAYLOAD, field: value}))


def test_registry_exposes_only_four_read_kinds_and_five_purpose_bindings():
    from tests.support.asset_job_handlers import (
        ASSET_READ_BINDINGS,
        JOB_KIND_SPECS,
        REGISTRY,
        AssetReadPayload,
    )

    assert [
        (
            item.name,
            item.owner_scope,
            item.queue,
            item.effect,
            item.max_attempts,
            item.credential_use,
            item.reconcile,
        )
        for item in JOB_KIND_SPECS
    ] == [
        ("ASSET_FIXTURE_TENANT_READ", "OWNER", "wso.default", "READ", 3, False, None),
        ("ASSET_FIXTURE_STORE_READ", "OWNER", "wso.default", "READ", 3, False, None),
        ("ASSET_FIXTURE_PHOTO_ONLY", "OWNER", "wso.default", "READ", 3, False, None),
        ("ASSET_FIXTURE_NO_ASSET_READ", "OWNER", "wso.default", "READ", 3, False, None),
    ]
    assert [(item.kind, item.purpose, item.scope) for item in ASSET_READ_BINDINGS] == [
        ("ASSET_FIXTURE_TENANT_READ", "PHOTO", "TENANT"),
        ("ASSET_FIXTURE_TENANT_READ", "CROP", "TENANT"),
        ("ASSET_FIXTURE_STORE_READ", "PHOTO", "STORE"),
        ("ASSET_FIXTURE_STORE_READ", "CROP", "STORE"),
        ("ASSET_FIXTURE_PHOTO_ONLY", "PHOTO", "TENANT"),
    ]
    assert set(REGISTRY.kinds) == {
        "ASSET_FIXTURE_TENANT_READ",
        "ASSET_FIXTURE_STORE_READ",
        "ASSET_FIXTURE_PHOTO_ONLY",
        "ASSET_FIXTURE_NO_ASSET_READ",
    }
    for name, scope in (
        ("ASSET_FIXTURE_TENANT_READ", "TENANT"),
        ("ASSET_FIXTURE_STORE_READ", "STORE"),
        ("ASSET_FIXTURE_PHOTO_ONLY", "TENANT"),
        ("ASSET_FIXTURE_NO_ASSET_READ", "TENANT"),
    ):
        kind = REGISTRY.get(name)
        assert kind.scope_kind == scope
        assert kind.payload_model is AssetReadPayload
        assert (
            kind.permission,
            kind.queue,
            kind.effect_mode,
            kind.max_attempts,
            kind.credential_use,
            kind.reconcile,
        ) == ("OWNER", "wso.default", "READ", 3, False, None)
        assert callable(kind.handler)


def test_process_spec_rejects_parent_escape_for_control_and_key_paths(tmp_path):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError

    original = owned_spec(tmp_path)
    for fields in (
        {"control_path": tmp_path / ".." / "escaped-control.json"},
        {"key_files": {"fixture-key": tmp_path / ".." / "escaped-key.key"}},
    ):
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            replace(original, **fields)


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint_url", "http://127.0.0.1:synthetic-port-poison"),
        ("broker_url", "redis://127.0.0.1:synthetic-port-poison/0"),
        ("endpoint_url", "http://127.0.0.1:65536"),
        ("broker_url", "redis://127.0.0.1:-1/0"),
    ],
    ids=[
        "endpoint-text-port",
        "broker-text-port",
        "endpoint-overflow",
        "broker-negative",
    ],
)
def test_process_spec_malformed_port_is_fixed_error_without_supplied_text(
    tmp_path, field, value
):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError) as failure:
        replace(owned_spec(tmp_path), **{field: value})
    assert str(failure.value) == "invalid fixture contract"
    assert "synthetic-port-poison" not in repr(failure.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", True),
        ("namespace", None),
        ("endpoint_url", 9000),
        ("region", False),
        ("gateway", {"access_key_id": "synthetic-secret-poison"}),
        ("maintenance", None),
        ("key_files", []),
        ("active_key_id", None),
        ("broker_url", 6379),
        ("worker_id", True),
    ],
    ids=[
        "owner-bool",
        "namespace-null",
        "endpoint-int",
        "region-bool",
        "gateway-map",
        "maintenance-null",
        "key-files-list",
        "active-null",
        "broker-int",
        "worker-bool",
    ],
)
def test_process_spec_native_types_never_escape_fixed_contract_error(
    tmp_path, field, value
):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError) as failure:
        replace(owned_spec(tmp_path), **{field: value})
    assert str(failure.value) == "invalid fixture contract"
    assert "synthetic-secret-poison" not in repr(failure.value)


@pytest.mark.parametrize("field", ["private_directory", "control_path", "key_files"])
def test_process_spec_requires_native_paths_without_implicit_conversion(
    tmp_path, field
):
    from dataclasses import replace

    from tests.support.asset_faults import FixtureContractError

    value = (
        {"fixture-key": str(tmp_path / "fixture.key")}
        if field == "key_files"
        else str(
            tmp_path if field == "private_directory" else tmp_path / "control.json"
        )
    )
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        replace(owned_spec(tmp_path), **{field: value})


@pytest.mark.parametrize("name", ["ADMIN", "APP", "JOB", "ASSET_MAINTENANCE"])
def test_environment_bad_role_port_cannot_leak_url_or_ambient_secret(tmp_path, name):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_process import ProcessMode, build_process_env

    source = owned_source(tmp_path)
    source[f"WSO_TEST_{name}_DATABASE_URL"] = (
        "postgresql+psycopg://synthetic-user:synthetic-url-poison@"
        "127.0.0.1:synthetic-port-poison/fixture_db"
    )
    with pytest.raises(FixtureContractError) as failure:
        build_process_env(ProcessMode.DISPATCH, source, owned_spec(tmp_path))
    assert str(failure.value) == "invalid fixture contract"
    assert "synthetic-url-poison" not in repr(failure.value)
    assert "unrelated-synthetic-canary" not in repr(failure.value)


@pytest.fixture
def identity_worker(tmp_path, monkeypatch):
    """Register the actual child handlers without starting Celery or opening clients."""
    from celery.signals import worker_process_init, worker_process_shutdown
    from kombu.transport.redis import Channel

    from tests.contract.test_asset_faults import identity_barrier
    from tests.support import asset_faults as faults
    from tests.support import asset_job_handlers as handlers

    control = identity_barrier(tmp_path, monkeypatch)
    lookup_state = {}
    monkeypatch.setattr(
        faults, "process_identity", lambda pid, owner: lookup_state["read"](pid, owner)
    )
    monkeypatch.setattr(Channel, "QoS", Channel.QoS)
    monkeypatch.setattr(handlers, "_CONTROL", handlers._CONTROL)
    monkeypatch.setattr(handlers, "_READER", handlers._READER)
    before_init = {receiver for _, receiver in worker_process_init.receivers}
    before_shutdown = {receiver for _, receiver in worker_process_shutdown.receivers}
    app = handlers.create_worker_app(
        {
            "WSO_ASSET_FIXTURE_BROKER_URL": "redis://127.0.0.1:6379/0",
            "WSO_TEST_JOB_DATABASE_URL": (
                "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:5432/fixture_db"
            ),
            "WSO_ASSET_FIXTURE_WORKER_ID": "synthetic-worker",
        },
        control,
    )
    (child_init,) = [
        receiver
        for _, receiver in worker_process_init.receivers
        if receiver not in before_init
    ]
    (child_shutdown,) = [
        receiver
        for _, receiver in worker_process_shutdown.receivers
        if receiver not in before_shutdown
    ]
    try:
        yield control, child_init, child_shutdown, lookup_state
    finally:
        worker_process_init.disconnect(child_init)
        worker_process_shutdown.disconnect(child_shutdown)
        app.close()


def test_child_init_native_publication_roundtrips_through_owned_parent_reader(
    tmp_path, monkeypatch, identity_worker
):
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from tests.support import asset_broker as broker
    from tests.support import asset_faults as faults
    from tests.support.asset_process import ProcessMode

    control, child_init, child_shutdown, lookup_state = identity_worker
    command = ("synthetic-python", "synthetic-worker")
    child = faults.ProcessIdentity(control.owner, os.getpid(), 7, 11, 11, 37, command)
    parent_identity = faults.ProcessIdentity(control.owner, 11, 7, 1, 11, 31, command)

    def lookup(pid, owner):
        assert owner == control.owner
        return child if pid == child.pid else parent_identity

    lookup_state["read"] = lookup
    monkeypatch.setattr(broker, "process_identity", lookup)
    descriptor = os.open(tmp_path / "synthetic-pidfd", os.O_CREAT | os.O_RDWR, 0o600)

    def pin(pid, flags):
        assert (pid, flags) == (child.pid, 0)
        return descriptor

    monkeypatch.setattr(os, "pidfd_open", pin, raising=False)
    parent = SimpleNamespace(
        mode=ProcessMode.JOB_WORKER,
        spec=SimpleNamespace(control_path=tmp_path),
        identity=parent_identity,
        process=SimpleNamespace(pid=11),
        command=command,
    )
    jobs = object.__new__(broker.AssetJobs)
    jobs.h = SimpleNamespace(owner=control.owner)
    jobs.processes, jobs.children = [parent], {}
    jobs.child_stop, jobs.child_lock = threading.Event(), threading.Lock()
    jobs.child_failure, jobs.seen_children = None, set()
    child_path = tmp_path / f"child-{child.pid}.json"
    release_path = tmp_path / f"child-{child.pid}.release"
    shutdown_needed = False
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            caller = executor.submit(child_init)
            try:
                cutoff = time.monotonic() + 1.0
                while not child_path.exists():
                    if caller.done():
                        caller.result()
                    assert time.monotonic() < cutoff
                    time.sleep(0.005)
                shutdown_needed = True
                value = json.loads(child_path.read_bytes())
                assert value == {
                    "owner": control.owner,
                    "pid": child.pid,
                    "uid": 7,
                    "ppid": 11,
                    "pgid": 11,
                    "start_ticks": 37,
                    "command": ["synthetic-python", "synthetic-worker"],
                }
                stopper = threading.Timer(0.05, jobs.child_stop.set)
                stopper.start()
                try:
                    jobs.observe_children()
                finally:
                    stopper.cancel()
                    stopper.join()
                assert jobs.child_failure is None
                assert jobs.children == {child.pid: (child, descriptor, parent)}
                assert jobs.seen_children == {child_path}
                observed = jobs.children[child.pid][0]
                assert type(observed.command) is tuple
                faults.validate_process_identity(child, observed)
                assert not caller.done()
            finally:
                faults.snapshot_json(
                    release_path,
                    {"owner": control.owner, "pid": child.pid, "start_ticks": 37},
                )
            caller.result(timeout=1)
    finally:
        if shutdown_needed:
            child_shutdown()
        os.close(descriptor)
    assert json.loads((tmp_path / "helpers.json").read_bytes()) == {
        "owner": control.owner,
        "pids": [],
        "complete": True,
    }
    assert json.loads((tmp_path / f"child-{child.pid}-settled.json").read_bytes()) == {
        "owner": control.owner,
        "settled": True,
    }
    assert (
        json.loads((tmp_path / "last-event.json").read_bytes())["event"]
        == "WORKER_READY"
    )


@pytest.mark.parametrize("identity", [None, {"command": ["synthetic-python"]}])
def test_child_init_malformed_identity_never_publishes_or_starts_helpers(
    tmp_path, monkeypatch, identity_worker, identity
):
    import os

    from tests.support import asset_faults as faults

    _control, child_init, _child_shutdown, lookup_state = identity_worker
    lookup_state["read"] = lambda pid, owner: identity
    with pytest.raises(faults.FixtureContractError, match="^invalid fixture contract$"):
        child_init()
    assert not (tmp_path / f"child-{os.getpid()}.json").exists()
    assert not (tmp_path / "helpers.json").exists()
    assert not (tmp_path / "last-event.json").exists()
