"""Offline local OWNER runtime contracts; never opens DB, SDK or a listener."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "scripts/test-local-devices/runtime.py"


@pytest.fixture
def runtime():
    assert RUNTIME.is_file(), "new owned local-device runtime is not implemented"
    spec = importlib.util.spec_from_file_location("local_browser_runtime", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inert_input():
    return {
        "schema_version": 1,
        "devices": [
            {
                "alias": "Recorder one",
                "store_label": "Store one",
                "credentials": {
                    "schema_version": 1,
                    "kind": "TVT_DEVICE",
                    "serial": "TEST123",
                    "country": "KR",
                    "username": "private-user",
                    "password": "private-password",
                },
            },
            {
                "alias": "Recorder two",
                "store_label": "Store two",
                "credentials": {
                    "schema_version": 1,
                    "kind": "TVT_DEVICE",
                    "serial": "TEST456",
                    "country": "KR",
                    "username": "private-user",
                    "password": "private-password",
                },
            },
        ],
    }


def test_cli_without_activation_cannot_read_inputs_or_start_children(tmp_path):
    assert RUNTIME.is_file(), "new explicit local-device activation boundary missing"
    result = subprocess.run(
        [sys.executable, str(RUNTIME)],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert (
        result.stderr.strip()
        == b"Local device browser fixture requires explicit activation."
    )
    assert list(tmp_path.iterdir()) == []


def test_private_input_is_closed_two_devices_and_never_represented(runtime):
    items = runtime.parse_input(json.dumps(inert_input()).encode())
    assert len(items) == 2
    assert [item.alias for item in items] == ["Recorder one", "Recorder two"]
    assert "private-password" not in repr(items) and "TEST123" not in repr(items)
    assert items[0].credentials.to_encrypt_bytes().startswith(b'{"schema_version":1,')


@pytest.mark.parametrize(
    "change",
    ["actor", "endpoint", "one", "duplicate", "secret-label", "duplicate-json"],
)
def test_private_input_rejects_scope_or_transport_selection(runtime, change):
    body = inert_input()
    if change == "actor":
        body["actor"] = "owner"
    elif change == "endpoint":
        body["devices"][0]["endpoint"] = "https://evil.test"
    elif change == "one":
        body["devices"] = body["devices"][:1]
    elif change == "duplicate":
        body["devices"][1]["credentials"] = body["devices"][0]["credentials"]
    elif change == "secret-label":
        body["devices"][0]["alias"] = "private-password"
    raw = (
        b'{"schema_version":1,"schema_version":1,"devices":[]}'
        if change == "duplicate-json"
        else json.dumps(body).encode()
    )
    with pytest.raises(ValueError, match="private local input"):
        runtime.parse_input(raw)


def test_api_and_worker_environment_keep_capabilities_separate(runtime):
    roles = {
        key: "private-" + key
        for key in ["ADMIN", "APP", "IDENTITY", "SESSION", "WORKER"]
    }
    auth = {
        "WSO_OIDC_ISSUER": "https://localhost:1234",
        "WSO_OIDC_CLIENT_ID": "fixture-web",
        "WSO_OIDC_JWKS_URL": "https://localhost:1234/jwks",
        "WSO_AUTH_EXCHANGE_KEY": "exchange",
        "WSO_PUBLIC_ORIGIN": "https://localhost:3543",
    }
    bridge = {
        "ENDPOINT": "localhost:12345",
        "CA_FILE": "ca",
        "CLIENT_CERT_FILE": "client",
        "CLIENT_KEY_FILE": "key",
    }
    api = runtime.api_environment(
        roles, auth, bridge, Path("owned/key"), Path("owned/ca.pem")
    )
    assert {k for k in api if k.endswith("DATABASE_URL")} == {
        "WSO_APP_DATABASE_URL",
        "WSO_IDENTITY_DATABASE_URL",
        "WSO_SESSION_DATABASE_URL",
    }
    assert api["WSO_CONNECTION_KEY_FILE"] == str(Path("owned/key"))
    assert not any(k.startswith("WSO_TVT_WINDOWS_") for k in api)
    native = {k: "approved" for k in runtime.NATIVE_KEYS}
    native[runtime.NATIVE_KEYS[0]] = "1"
    worker = runtime.worker_environment(roles, native, Path("owned/key"))
    assert {k for k in worker if k.endswith("DATABASE_URL")} == {
        "WSO_WORKER_DATABASE_URL"
    }
    assert all(worker[k] == native[k] for k in runtime.NATIVE_KEYS)
    assert "WSO_APP_DATABASE_URL" not in worker and "WSO_OIDC_ISSUER" not in worker


def test_real_mode_refuses_missing_native_loader_before_admission(runtime):
    with pytest.raises(ValueError, match="reviewed native provider unavailable"):
        runtime.required_provider(lambda: None)


def test_real_mode_refuses_inert_provider_substitution(runtime):
    with pytest.raises(ValueError, match="reviewed native provider unavailable"):
        runtime.required_provider(lambda: object())


def test_source_anchors_match_independently_reviewed_current_receipts(runtime):
    assert all(len(value) == 64 for value in runtime.ANCHORS.values()), (
        "malformed approval pin"
    )
    sources = runtime.anchored_sources()
    assert len(sources) == 24
    assert (
        sources["infra/migrations/versions/0012_tvt_local_devices.py"]
        == "883b4e09532dad7f9df62621a160b45a9561757599281737f98d1cfa54271ab3"
    )
    assert (
        sources["services/api/src/wso_api/main.py"]
        == "8c4770bef1c943814832198040423e98f2abbf66b025375d190e675a56d122b1"
    )
    assert (
        sources["apps/web/src/lib/tvt/local-device-api.ts"]
        == "50cb1e4288494834dd072595016c2b189316beb39e1c5852abfb2694164d328a"
    )


def test_node_stop_is_durable_and_cli_without_activation_is_inert(tmp_path):
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const {{installDurableStop}}=await import({json.dumps(module)});
let present=false,calls=0;const check=installDurableStop('owned-shutdown',async()=>{{calls++}},{{exists:()=>present}});
await check();if(calls)throw Error('implicit stop');present=true;await check();if(calls!==1)throw Error('durable stop ignored');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=tmp_path,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        ["node", str(ROOT / "scripts/test-local-devices/server.mjs")],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert list(tmp_path.iterdir()) == []


def test_approval_is_exact_root_receipt_and_source_identity(runtime, tmp_path):
    import hashlib

    root = tmp_path / "root"
    root.mkdir()
    (root / "file.py").write_bytes(b"approved\n")
    body = {
        "schema_version": 1,
        "root_explicitly_accepted": True,
        "scope": "owned-local-device-browser-only",
        "sources": {
            "file.py": "f7d9e9c2b3c9b23f73ba33e5fa8e1d99e5f2ebd9a8e9e8c9d0611b4a9e2fccef"
        },
    }
    # Independently fixed exact bytes for this inert single-file fixture.
    body["sources"]["file.py"] = hashlib.sha256(b"approved\n").hexdigest()
    raw = json.dumps(body).encode()
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(raw)
    approved = hashlib.sha256(raw).hexdigest()
    runtime.verify_source_approval(
        receipt, approved, required_paths={"file.py"}, root=root
    )
    (root / "file.py").write_bytes(b"unapproved\n")
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            receipt, approved, required_paths={"file.py"}, root=root
        )
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            receipt, "0" * 64, required_paths={"file.py"}, root=root
        )


def test_resource_owner_outlives_reporting_deadline_without_termination(runtime):
    class Child:
        def __init__(self):
            self.polls, self.stdin = 0, self

        def write(self, value):
            assert value == b"close\n"

        def flush(self):
            pass

        def poll(self):
            self.polls += 1
            return None if self.polls < 5 else 0

        def terminate(self):
            pytest.fail("resource owner was terminated")

    receipts = []
    with pytest.raises(RuntimeError, match="after settlement"):
        runtime.settle_child(
            Child(),
            Path("unused"),
            "worker",
            budget=0,
            receipt=lambda value: receipts.append(value),
            pause=lambda _: None,
        )
    assert any(value["custody_retained"] for value in receipts)
    assert receipts[-1]["exit"] == 0


def test_owned_migration_unwinds_before_original_database_owner(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from alembic import command

    from tests.integration import test_tvt_directory_admission as accepted

    events = []
    name = "w07_directory_" + "a" * 32

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            assert "current_database" in str(statement)
            return SimpleNamespace(
                one=lambda: (name, "owned-w07-directory-" + "b" * 32)
            )

    engine = SimpleNamespace(
        url=SimpleNamespace(
            database=name,
            render_as_string=lambda **kwargs: (
                "postgresql+psycopg://inert@localhost/" + name
            ),
        ),
        connect=Db,
    )

    def generator():
        events.append("original-owner-enter")
        try:
            yield {"ADMIN": engine}
        finally:
            events.append("original-owner-exit")

    monkeypatch.setattr(
        accepted, "directory_database", SimpleNamespace(__wrapped__=generator)
    )
    monkeypatch.setattr(
        command, "upgrade", lambda cfg, revision: events.append(("upgrade", revision))
    )
    monkeypatch.setattr(
        command,
        "downgrade",
        lambda cfg, revision: events.append(("downgrade", revision)),
    )
    with (
        pytest.raises(ValueError, match="body failed"),
        runtime.owned_database(tmp_path),
    ):
        raise ValueError("body failed")
    assert events == [
        "original-owner-enter",
        ("upgrade", "0012_tvt_local_devices"),
        ("downgrade", "0011_tvt_directory_read_tickets"),
        "original-owner-exit",
    ]


def test_denied_source_approval_never_executes_borrowed_python(
    runtime, monkeypatch, tmp_path
):
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv("WSO_TEST_BROWSER_TLS_DIR", str(tmp_path))
    path = ROOT / "auth-state" / ("local-devices-" + "0" * 32) / "context.json"
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE", str(path))
    monkeypatch.setenv(
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE", str(tmp_path / "denied.json")
    )
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "0" * 64)
    imported = []

    def loader():
        imported.append(True)
        raise AssertionError("unadmitted borrowed code executed")

    def deny(*args, **kwargs):
        raise ValueError("source approval test denial")

    monkeypatch.setattr(runtime, "borrowed_helpers", loader)
    monkeypatch.setattr(runtime, "verify_source_approval", deny)
    with pytest.raises(ValueError, match="source approval test denial"):
        runtime.coordinate()
    assert imported == []


def test_node_queues_stop_until_original_runtime_folder_exists():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});let present=false,marker=false,pauses=0,overrun=0;
const child={{exitCode:null,signalCode:null,kill(){{throw Error('resource owner killed')}}}};
if(typeof m.deliverRuntimeStop!=='function')throw Error('queued marker delivery missing');
await m.deliverRuntimeStop(child,'owned',{{deadline:0,now:()=>1,exists:()=>present,write:()=>{{marker=true;child.exitCode=0}},pause:async()=>{{if(++pauses===3)present=true}},onOverrun:()=>{{overrun++}}}});
if(!marker||pauses!==3||overrun!==1)throw Error('early stop lost or reporting custody reset');
let writes=0;await m.deliverRuntimeStop({{exitCode:1,signalCode:null}},'absent',{{write:()=>{{writes++}}}});if(writes)throw Error('retired owner received marker');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_node_checks_borrowed_hash_before_dynamic_execution():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});let imported=0;
if(typeof m.admittedHelpers!=='function')throw Error('borrowed source admission missing');
let refused=false;try{{await m.admittedHelpers({{read:()=>Buffer.from('unadmitted source'),importer:async()=>{{imported++;return {{}}}}}})}}catch{{refused=true}}
if(!refused||imported!==0)throw Error('unadmitted borrowed module executed');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows direct interpreter admission")
def test_direct_base_child_restores_venv_prefix_before_native_admission(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    probe = tmp_path / "probe.py"
    probe.write_text(
        """import json,os,sys
from pathlib import Path
from wso_tvt_bridge.windows_socket import direct_interpreter
try:
 direct,site=direct_interpreter(); admitted=True
except Exception:
 admitted=False
print(json.dumps({'pid':os.getpid(),'prefix_ok':Path(sys.prefix).name=='.venv','admitted':admitted}))
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "__file__", str(probe))
    actual = subprocess.Popen
    commands = []

    def spawn(argv, **kwargs):
        commands.append(argv)
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return actual(argv, **kwargs)

    monkeypatch.setattr(
        runtime,
        "subprocess",
        SimpleNamespace(
            Popen=spawn,
            PIPE=subprocess.PIPE,
            DEVNULL=subprocess.DEVNULL,
            CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ),
    )
    child = runtime.spawn_python([], runtime.borrowed_helpers().child_environment())
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    result = json.loads(stdout)
    assert commands[0][0] == sys._base_executable
    assert result["pid"] == child.pid, "venv redirector hid the original child"
    assert result["prefix_ok"] and result["admitted"], (
        "direct base launcher lost admitted venv context"
    )


def test_next_subordinate_exits_after_close_even_with_retained_dev_handles():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});setInterval(()=>{{}},60000);
if(typeof m.closeNextOwned!=='function')throw Error('deliberate Next exit missing');
await m.closeNextOwned({{close:async()=>{{await new Promise(r=>setTimeout(r,5));process.stdout.write('app-closed\\n')}}}},{{close(){{}},closeAllConnections(){{}}}});
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"app-closed\n"


def test_owner_banner_distinguishes_synthetic_owner_from_real_devices(runtime):
    html = "Sign in as synthetic directory staff; Synthetic directory fixture; Invented account and devices. No vendor connection."
    text = runtime.owner_page_text(html)
    assert "synthetic owner" in text
    assert "real registered devices" in text
    assert "read-only verification" in text
    assert "No vendor connection" not in text
