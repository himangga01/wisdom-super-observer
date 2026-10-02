"""Host-only safety contracts; no database activation or provider requests."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "scripts/test-tvt-account/runtime.py"


@pytest.fixture
def runtime():
    assert RUNTIME.is_file(), "owned browser runtime is not implemented"
    spec = importlib.util.spec_from_file_location("account_browser_fixture", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_without_activation_does_not_read_private_configuration(tmp_path):
    result = subprocess.run(
        [sys.executable, str(RUNTIME)],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=5,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        result.stderr.strip() == "Account browser fixture requires explicit activation."
    )
    assert list(tmp_path.iterdir()) == []


def test_private_context_is_bounded_and_replacement_cannot_escape(runtime, tmp_path):
    folder = tmp_path / "owned"
    runtime.private_directory(folder)
    runtime.write_private(folder / "context.json", {"secret": "private-test-value"})
    assert json.loads((folder / "context.json").read_text()) == {
        "secret": "private-test-value"
    }
    if os.name != "nt":
        assert folder.stat().st_mode & 0o077 == 0
        assert (folder / "context.json").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="bounded"):
        runtime.write_private(folder / "context.json", {"secret": "a" * 65536})
    assert (
        json.loads((folder / "context.json").read_text())["secret"]
        == "private-test-value"
    )


@pytest.mark.parametrize(
    "command",
    [
        {},
        {"op": "reset"},
        {"op": "session", "actor": "owner"},
        {"op": "session", "sequence": 1, "extra": "secret"},
        {"op": "session", "sequence": True},
    ],
)
def test_control_rejects_unbounded_or_authority_selecting_requests(runtime, command):
    with pytest.raises(ValueError, match="control"):
        runtime.parse_control(json.dumps(command).encode())


def test_control_accepts_only_fresh_session_with_monotonic_sequence(runtime):
    assert runtime.parse_control(b'{"op":"session","sequence":1}') == 1


def test_wait_aborts_on_owned_child_exit_without_disclosing_output(runtime, tmp_path):
    process = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(7)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="owned child exited"):
            runtime.wait_file(tmp_path / "missing", process, time.monotonic() + 5)
        assert time.monotonic() - started < 3
    finally:
        process.wait(timeout=5)


def test_cleanup_refuses_changed_ownership_and_preserves_unrelated_files(
    runtime, tmp_path
):
    folder = tmp_path / "owned"
    runtime.private_directory(folder)
    runtime.write_private(folder / "owner.json", {"owner": "original"})
    (folder / "precious").write_text("keep")
    with pytest.raises(ValueError, match="ownership"):
        runtime.remove_owned(folder, "different")
    assert (folder / "precious").read_text() == "keep"
    runtime.remove_owned(folder, "original")
    assert not folder.exists()


def test_node_import_has_no_service_start_and_cli_requires_opt_in(tmp_path):
    node = shutil.which("node")
    assert node
    module = (ROOT / "scripts/test-tvt-account/server.mjs").as_uri()
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            f"const m=await import({json.dumps(module)});console.log(typeof m.default)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=5,
    )
    assert result.returncode == 0 and result.stdout.strip() == "function"
    result = subprocess.run(
        [node, str(ROOT / "scripts/test-tvt-account/server.mjs")],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=5,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.strip() == "Account browser coordinator failed."
    assert list(tmp_path.iterdir()) == []


def test_challenge_image_is_decodable_complete_png(runtime):
    import struct
    import zlib

    image = runtime.fixture_png()
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    decoded = b""
    chunks = []
    while offset < len(image):
        length = struct.unpack(">I", image[offset : offset + 4])[0]
        kind = image[offset + 4 : offset + 8]
        payload = image[offset + 8 : offset + 8 + length]
        assert struct.unpack(">I", image[offset + 8 + length : offset + 12 + length])[
            0
        ] == zlib.crc32(kind + payload)
        chunks.append(kind)
        if kind == b"IDAT":
            decoded += payload
        offset += 12 + length
    assert chunks == [b"IHDR", b"IDAT", b"IEND"]
    assert len(zlib.decompress(decoded)) == 12040


def test_reviewed_migration_allows_only_two_exact_eol_variants(runtime):
    path = ROOT / "infra/migrations/versions/0007_tvt_account_sessions.py"
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    assert (
        runtime.approved_migration_digest(canonical)
        == "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608"
    )
    assert (
        runtime.approved_migration_digest(canonical.replace(b"\n", b"\r\n"))
        == "86f154d10c7cd14ca51aae9327982c80f60945f59820ccda1769ca777f510f6d"
    )
    for changed in (
        canonical + b"\n",
        canonical.replace(b"CREATE TABLE", b"CREATE VIEW", 1),
        canonical + b"\r",
    ):
        with pytest.raises(ValueError, match="migration source"):
            runtime.approved_migration_digest(changed)


def test_setup_refuses_existing_private_context_before_spawning(tmp_path):
    state = tmp_path / "context.json"
    state.write_text('{"owner":"foreign"}')
    module = (ROOT / "scripts/test-tvt-account/server.mjs").as_uri()
    code = f"const m=await import({json.dumps(module)});try{{await m.default();process.exitCode=9}}catch(e){{console.log(e.message)}}"
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", code],
        env={**os.environ, "WSO_TVT_ACCOUNT_BROWSER_STATE_FILE": str(state)},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Private fixture directory must be new"
    assert state.read_text() == '{"owner":"foreign"}'


def test_parent_cleanup_budget_preserves_nested_resource_custody(tmp_path):
    module = (ROOT / "scripts/test-tvt-account/server.mjs").as_uri()
    code = """
const {stopOwned,retainCustody,CLEANUP}=await import(MODULE);
let now=0, killed=0, close=0, dropped=false, removed=false;
const runtime={get exitCode(){if(now>=70000){dropped=true;removed=true;return 0}return null},stdin:{end(){close++}},kill(){killed++}};
await stopOwned(runtime,{deadline:CLEANUP.runtimeMs,resourceOwner:true,now:()=>now,pause:async ms=>{now+=ms}});
if(killed||close!==1||!dropped||!removed||now<70000)throw Error('premature custody loss');
const stalled={exitCode:null,stdin:{end(){}},kill(){killed++}};
let retained=false;
try {await stopOwned(stalled,{deadline:now+100,resourceOwner:true,now:()=>now,pause:async ms=>{now+=ms}})}catch(e){retained=e.custodyRetained===true}
if(!retained||killed)throw Error('resource owner was killed');
let later=0;
await retainCustody(stalled,{pause:async()=>{later++;stalled.exitCode=0}});
if(later!==1)throw Error('custody was not retained to actual exit');
const signalled={exitCode:null,signalCode:'SIGTERM',stdin:{end(){throw Error('already reaped')}},kill(){throw Error('already reaped')}};
let abnormal=false; try {await stopOwned(signalled,{deadline:100,resourceOwner:true})}catch(e){abnormal=!e.custodyRetained}
if(!abnormal)throw Error('signal exit mistaken for live custodian');
let webKilled=0; now=0;
const web={exitCode:null,stdin:{end(){}},kill(){webKilled++;this.exitCode=0}};
await stopOwned(web,{deadline:CLEANUP.nextMs,now:()=>now,pause:async ms=>{now+=ms}});
if(webKilled!==1||now!==15000)throw Error('Next subordinate budget changed');

if(CLEANUP.nextMs+CLEANUP.runtimeMs>CLEANUP.coordinatorMs||CLEANUP.coordinatorMs>=CLEANUP.setupMs)throw Error('incoherent budget');
console.log('nested cleanup reached database/context; overdue custody retained');
""".replace("MODULE", json.dumps(module))
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("pending", ["api", "worker", "ticket"])
def test_rotation_refuses_pending_prelogin_authority_with_zero_identities(
    runtime, tmp_path, pending
):
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    rotated = []
    if pending != "ticket":
        assert gate.enter(pending)

    def authority():
        return (0, int(pending == "ticket"))

    with pytest.raises(ValueError, match="settled"):
        runtime.rotate_when_settled(gate, authority, lambda: rotated.append(True))
    assert not rotated
    if pending != "ticket":
        gate.leave(pending)
    runtime.rotate_when_settled(gate, lambda: (0, 0), lambda: rotated.append(True))
    assert rotated == [True]


def test_rotation_freezes_both_admission_paths_across_check_and_revoke(
    runtime, tmp_path
):
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    observer = runtime.AdmissionGate(tmp_path / "gate.sqlite")
    seen = []

    def check():
        seen.append((observer.enter("api"), observer.enter("worker")))
        return (0, 0)

    def revoke_and_create():
        seen.append((observer.enter("api"), observer.enter("worker")))

    runtime.rotate_when_settled(gate, check, revoke_and_create)
    assert seen == [(False, False), (False, False)]
    assert observer.enter("api")
    observer.leave("api")


@pytest.mark.parametrize("side", ["api", "worker"])
def test_admission_is_released_on_cancellation_without_changing_result(
    runtime, tmp_path, side
):
    import asyncio

    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)

    class Cancelled(BaseException):
        pass

    if side == "api":

        async def app(scope, receive, send):
            with pytest.raises(ValueError, match="settled"):
                runtime.rotate_when_settled(gate, lambda: (0, 0), lambda: None)
            raise Cancelled()

        with pytest.raises(Cancelled):
            asyncio.run(
                runtime.GuardedApplication(app, gate)({"type": "http"}, None, None)
            )
    else:

        def execute(*args):
            with pytest.raises(ValueError, match="settled"):
                runtime.rotate_when_settled(gate, lambda: (0, 0), lambda: None)
            raise Cancelled()

        with pytest.raises(Cancelled):
            runtime.guard_worker_execute(execute, gate)(None, None, None)
        sentinel = object()
        assert (
            runtime.guard_worker_execute(lambda *args: sentinel, gate)(None, None, None)
            is sentinel
        )
    rotated = []
    runtime.rotate_when_settled(gate, lambda: (0, 0), lambda: rotated.append(True))
    assert rotated == [True]


def test_rotation_refusal_releases_freeze_and_preserves_session_on_check_error(
    runtime, tmp_path
):
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    rotated = []

    def failed_check():
        raise TimeoutError("owned database read timed out")

    with pytest.raises(TimeoutError):
        runtime.rotate_when_settled(gate, failed_check, lambda: rotated.append(True))
    assert not rotated
    assert gate.enter("worker")
    gate.leave("worker")


def test_active_completion_can_leave_while_admission_is_frozen(runtime, tmp_path):
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    assert gate.enter("worker")
    with gate.frozen() as activity:
        assert activity == (0, 1)
        gate.leave("worker")
        assert not gate.enter("api")
    runtime.rotate_when_settled(gate, lambda: (0, 0), lambda: None)


def test_browser_sequence_uses_distinct_owned_lifetimes_and_stops_on_failure():
    module = (ROOT / "scripts/test-tvt-account/server.mjs").as_uri()
    code = """
const {runBrowserSequence}=await import(MODULE);
const calls=[];
const result=await runBrowserSequence(async (args,env)=>{calls.push({args,env});return 0});
if(result!==0||calls.length!==2)throw Error('two lifetimes required');
if(calls[0].env.WSO_TVT_ACCOUNT_BROWSER_STATE_FILE===calls[1].env.WSO_TVT_ACCOUNT_BROWSER_STATE_FILE)throw Error('context reused');
if(calls.map(x=>x.env.WSO_TVT_ACCOUNT_BROWSER_VIEWPORT).join(',')!=='account-desktop,account-mobile')throw Error('viewport selection');
if(calls.some(x=>!x.args.includes('--config')||x.args.at(-1)!==`--project=${x.env.WSO_TVT_ACCOUNT_BROWSER_VIEWPORT}`))throw Error('real selected Playwright required');
let release,completed=false,started=0;
const pending=runBrowserSequence(async()=>{started++;if(started===1){await new Promise(done=>{release=done});completed=true;return 0}if(!completed)throw Error('next lifetime began before settlement');return 8});
await Promise.resolve();
if(started!==1||completed)throw Error('cleanup was not awaited');
release();
if(await pending!==8||started!==2)throw Error('second failure not propagated');
let attempts=0;
if(await runBrowserSequence(async()=>{attempts++;return 7})!==7||attempts!==1)throw Error('continued after failed cleanup');
console.log('isolated lifetimes and failure boundary verified');
""".replace("MODULE", json.dumps(module))
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_config_requires_explicit_single_viewport_without_silent_skips():
    module = (ROOT / "playwright.tvt-account.config.ts").as_uri()
    code = f"try {{const m=await import({json.dumps(module)});console.log(m.default.projects.map(p=>p.name).join(','))}}catch(e){{console.log(e.message);process.exitCode=2}}"
    for viewport in (None, "invalid", "account-desktop", "account-mobile"):
        env = {
            k: v
            for k, v in os.environ.items()
            if k != "WSO_TVT_ACCOUNT_BROWSER_VIEWPORT"
        }
        if viewport is not None:
            env["WSO_TVT_ACCOUNT_BROWSER_VIEWPORT"] = viewport
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        if viewport in {None, "invalid"}:
            assert result.returncode == 2
            assert (
                "Use node scripts/test-tvt-account/server.mjs --browser"
                in result.stdout
            )
        else:
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == viewport
