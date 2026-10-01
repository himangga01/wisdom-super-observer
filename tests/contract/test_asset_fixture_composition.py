"""Bounded fixture compositions; no external provider or PostgreSQL acceptance."""

import hashlib
import io
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from wso_core.asset_images import ImageValidator
from wso_core.storage import PART_BYTES

from tests.support.asset_faults import FixtureContractError
from tests.support.asset_harness import AssetHarness, FixtureDeadlines, FixturePhase
from tests.support.asset_minio import LoopbackRelay
from tests.support.asset_process import (
    adapter_probe,
    delete_adapter_probes,
    read_adapter_failure,
)
from tests.support.asset_provider import AssetProvider


class ProbeObjects:
    """Only the prohibited remote store is substituted; caller is real."""

    def __init__(self, ciphertext):
        self.ciphertext = ciphertext
        self.objects = {}
        self.uploads = {}
        self.puts = []
        self.part_sizes = []

    def get(self, locator, **kwargs):
        return io.BytesIO(self.objects.get(locator, self.ciphertext))

    def head(self, locator, **kwargs):
        return SimpleNamespace(
            byte_size=len(self.objects.get(locator, self.ciphertext))
        )

    def put(self, locator, body, **kwargs):
        assert 0 < len(body) <= PART_BYTES + 36, "direct PUT exceeds existing cap"
        self.puts.append((locator, body))
        self.objects[locator] = body

    def create_multipart(self, locator, **kwargs):
        identifier = str(uuid4())
        self.uploads[identifier] = []
        return identifier

    def upload_part(self, locator, upload, number, body, **kwargs):
        assert 0 < len(body) <= PART_BYTES
        self.part_sizes.append(len(body))
        self.uploads[upload].append(body)
        return SimpleNamespace(part_number=number)

    def complete_multipart(self, locator, upload, parts, **kwargs):
        assert [part.part_number for part in parts] == list(range(1, len(parts) + 1))
        self.objects[locator] = b"".join(self.uploads.pop(upload))

    def abort_multipart(self, locator, upload, **kwargs):
        self.uploads.pop(upload)

    def list_multipart(self, **kwargs):
        return SimpleNamespace(
            items=[SimpleNamespace(upload_id=u) for u in self.uploads]
        )

    def list_objects(self, **kwargs):
        return SimpleNamespace(items=list(self.objects))

    def local_cleanup_complete(self):
        return True


def test_actual_adapter_caller_bounds_direct_body_and_partitions_full_ciphertext(
    tmp_path, monkeypatch
):
    from wso_api.assets import bootstrap

    data = {
        name: str(uuid4())
        for name in (
            "installation_id",
            "tenant_id",
            "asset_id",
            "attempt_id",
            "probe_asset",
            "probe_attempt",
            "direct_probe_asset",
            "direct_probe_attempt",
        )
    }
    data.update(owner="fixture", cutoff=time.monotonic() + 20)
    (tmp_path / "adapter.json").write_text(json.dumps(data))
    from uuid import UUID

    ciphertext = b"a" * (PART_BYTES * 3) + b"ending-ciphertext"
    objects = ProbeObjects(ciphertext)
    runtime = SimpleNamespace(
        objects=objects,
        configuration=SimpleNamespace(
            namespace=SimpleNamespace(installation_id=UUID(data["installation_id"]))
        ),
        admission=SimpleNamespace(retire_if_idle=lambda: True),
        authorization=SimpleNamespace(
            **{
                name: SimpleNamespace(dispose=lambda: None)
                for name in ("web_session", "identity", "tenant", "redemption")
            }
        ),
    )
    monkeypatch.setattr(bootstrap, "load_asset_settings", lambda env: None)
    monkeypatch.setattr(bootstrap, "start_asset_runtime", lambda **kwargs: runtime)
    adapter_probe({}, SimpleNamespace(directory=tmp_path, owner="fixture"), "adapter")
    assert len(objects.objects) == 2
    assert objects.part_sizes == [5242880, 5242880, 5242880, 17]
    assert len(objects.puts) == 1 and objects.puts[0][1] != ciphertext
    assert ciphertext in objects.objects.values()
    assert not objects.uploads
    assert (
        json.loads((tmp_path / "adapter-result.json").read_text())["accepted"] is True
    )


def test_maintenance_cleans_both_distinct_probe_objects_with_original_cutoff():
    data = {
        name: str(uuid4())
        for name in (
            "installation_id",
            "tenant_id",
            "probe_asset",
            "probe_attempt",
            "direct_probe_asset",
            "direct_probe_attempt",
        )
    }
    data["cutoff"] = time.monotonic() + 2
    deleted = []

    def delete(locator, *, budget):
        assert budget.deadline_monotonic <= data["cutoff"]
        deleted.append(str(locator.asset_id))

    objects = SimpleNamespace(
        delete=delete,
        list_objects=lambda **kwargs: SimpleNamespace(items=[]),
        list_multipart=lambda **kwargs: SimpleNamespace(items=[]),
    )
    assert delete_adapter_probes(objects, data) == {
        "deleted": True,
        "identity": "wso_asset_maintenance",
    }
    assert deleted == [data["probe_asset"], data["direct_probe_asset"]]


def test_adapter_bootstrap_failure_records_safe_stage_without_raw_exception(
    tmp_path, monkeypatch, capsys
):
    from wso_api.assets import bootstrap

    failure = RuntimeError("secret-body-key-url")

    def refuse(env):
        raise failure

    monkeypatch.setattr(bootstrap, "load_asset_settings", refuse)
    with pytest.raises(RuntimeError) as caught:
        adapter_probe(
            {}, SimpleNamespace(directory=tmp_path, owner="fixture"), "adapter"
        )
    assert caught.value is failure
    assert read_adapter_failure(tmp_path) == {
        "schema": 1,
        "action": "adapter",
        "stage": "BOOTSTRAP",
        "body": "UNKNOWN",
        "error_code": "UNKNOWN",
    }
    assert "secret" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"action": "secret", "stage": "secret", "body": [1], "error_code": [2]},
        "oversized",
    ],
)
def test_adapter_parent_refuses_unsafe_diagnostic_fields(tmp_path, value):
    (tmp_path / "adapter-diagnostic.json").write_text(
        "x" * 8193 if value == "oversized" else json.dumps(value)
    )
    assert read_adapter_failure(tmp_path) == {
        "schema": 1,
        "action": "UNKNOWN",
        "stage": "UNKNOWN",
        "body": "UNKNOWN",
        "error_code": "UNKNOWN",
    }


def error_response(status, code):
    return httpx.Response(
        status,
        json={
            "error": {"code": code, "message": "Asset request failed"},
            "request_id": None,
        },
        headers={"cache-control": "no-store", "vary": "Cookie"},
    )


def test_rejected_parent_stimulus_preserves_signature_and_integrity_branch():
    h = AssetHarness.__new__(AssetHarness)
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 64
    h.image = lambda: data
    h.actors = [None, None]
    h.asset_count = lambda: 2
    sessions = iter([{"asset_id": "pending"}, {"asset_id": "failed"}])
    h.require_begin = lambda *args, **kwargs: next(sessions)
    h.begin = lambda *args, **kwargs: SimpleNamespace(status_code=422)
    recovered = []
    h.recover_rejected = lambda session: recovered.append(session["asset_id"])
    h.row = lambda identifier: {"state": "REJECTED"}

    def put(session, body):
        from wso_core.asset_crypto import AssetCryptoFailure, _EncryptingUpload
        from wso_core.assets import _failure

        from tests.contract.test_asset_storage_primitives import make_aad

        assert len(body) == len(data)
        assert body[:8] == data[:8], "integrity stimulus destroyed PNG signature"
        assert ImageValidator(policy=None).sniff(body) == "image/png"
        assert hashlib.sha256(body).digest() != hashlib.sha256(data).digest()
        encryptor = _EncryptingUpload(
            SimpleNamespace(
                aad=make_aad(data),
                data_key=b"k" * 32,
                envelope=SimpleNamespace(object_nonce=b"n" * 12),
            )
        )
        encryptor.header()
        encryptor.update(body)
        with pytest.raises(AssetCryptoFailure) as caught:
            encryptor.finish()
        assert caught.value.code == "INTEGRITY"
        public = _failure(caught.value)
        return error_response(public.status, public.code)

    h.put = put
    h.prove_invalid_parents(
        {"id": "parent", "store_id": "store"}, {"id": "child"}, other_store="other"
    )
    assert recovered == ["pending", "failed"]


def test_authority_revocation_retains_audit_and_live_session_with_guarded_denials():
    h = AssetHarness.__new__(AssetHarness)
    actor = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    state = {"role": "OWNER", "audit": [{"id": uuid4(), "action": "asset:delete"}]}

    class DB:
        def execute(self, statement, values):
            sql = str(statement)
            assert "DELETE" not in sql, (
                "physical membership deletion violates retained audit"
            )
            assert "UPDATE public.memberships SET role='STAFF'" in sql
            state["role"] = "STAFF"
            return SimpleNamespace(rowcount=1)

    @contextmanager
    def transaction():
        yield DB()

    h.admin = SimpleNamespace(begin=transaction)

    def query(statement, values=None):
        if "audit_events" in statement:
            return list(state["audit"])
        if "memberships" in statement:
            return [{"role": state["role"]}]
        raise AssertionError("unexpected query")

    h.query = query
    calls = []

    def request(method, path, **kwargs):
        from fastapi import HTTPException
        from wso_api.stores.router import require_tenant

        calls.append(path.split("?")[0])
        if path == "/api/v1/me":
            return SimpleNamespace(status_code=200)

        @contextmanager
        def identity(principal):
            yield SimpleNamespace(
                user_id=lambda: actor.user_id,
                authorize_tenant=lambda tenant: SimpleNamespace(role=state["role"]),
            )

        action = "connections:read" if "/connections" in path else "assets:write"
        with (
            pytest.raises(HTTPException) as denied,
            require_tenant(
                action,
                actor.tenant_id,
                service=SimpleNamespace(identity=identity),
                principal=actor,
            ),
        ):
            pytest.fail("revoked owner reached tenant data")
        return SimpleNamespace(status_code=denied.value.status_code)

    h.request = request
    h.image = lambda: b"fixture-png"
    h.revoke_membership(actor)
    assert state["role"] == "STAFF" and len(state["audit"]) == 1
    assert "/api/v1/me" in calls and "/api/v1/connections" in calls
    assert "/api/v1/assets" in calls


def minimal_harness(directory):
    h = AssetHarness.__new__(AssetHarness)
    h.directory = directory
    h.provider_evidence = directory / "receipt.json"
    h.provider = AssetProvider(directory)
    h.deadlines = FixtureDeadlines(time.monotonic())
    h.deadlines.cutoffs[FixturePhase.TEARDOWN] = time.monotonic() + 3
    h.callers, h.launches, h.modes, h.faults = set(), [], {}, set()
    h.access = h.admin = None

    def refuse(*args):
        raise RuntimeError("owned job refusal")

    h.jobs_context = SimpleNamespace(__exit__=refuse)
    return h


def test_exceptional_harness_quiesces_real_relay_retains_targets_and_keys(tmp_path):
    h = minimal_harness(tmp_path)
    h.provider.created = [("container", "owned-retained")]
    (tmp_path / "K1").write_bytes(b"test-key")
    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    h.provider.relay = relay
    relay.start(deadline=time.monotonic() + 2)
    try:
        with pytest.raises(RuntimeError, match="JOB"):
            h.__exit__(None, None, None)
        assert not relay.live_threads, "earlier JOB refusal left non-daemon relay alive"
        assert not relay.active_sockets
        assert h.provider.created == [("container", "owned-retained")]
        assert (tmp_path / "K1").exists() and not h.provider_evidence.exists()
    finally:
        relay.close()


def test_exceptional_context_subprocess_exits_nonzero_with_real_nondaemon_relay(
    tmp_path,
):
    # The exact child handle is the sole timeout cancellation authority. This
    # tests interpreter exit, which an exception-only teardown test cannot prove.
    script = """
import sys, time
from pathlib import Path
from tests.contract.test_asset_fixture_composition import minimal_harness
from tests.support.asset_minio import LoopbackRelay
h = minimal_harness(Path(sys.argv[1]))
h.provider.created = [('container', 'owned-retained')]
(h.directory / 'K1').write_bytes(b'test-key')
h.provider.relay = LoopbackRelay(lambda *_: '172.28.0.2', h.directory)
h.provider.relay.start(deadline=time.monotonic() + 2)
assert all(not t.daemon for t in h.provider.relay.live_threads)
try:
    h.__exit__(RuntimeError, RuntimeError('original-body'), None)
finally:
    assert h.provider.created == [('container', 'owned-retained')]
    assert (h.directory / 'K1').exists()
    assert not h.provider_evidence.exists()
    print('RETAINED_NO_RECEIPT', flush=True)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[2],
    )
    try:
        stdout, stderr = child.communicate(timeout=7)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=3)
        pytest.fail("exceptional context left interpreter waiting for relay")
    assert child.returncode != 0
    assert b"RETAINED_NO_RECEIPT" in stdout and b"JOB" in stderr
    assert b"original-body" in stderr


def test_failed_begin_diagnostic_is_bounded_allowlisted_and_keeps_exact_status(capsys):
    h = AssetHarness.__new__(AssetHarness)
    h.actors = [SimpleNamespace(expires_at=datetime.now(UTC) - timedelta(seconds=1))]
    h.upload_sizes = {}
    h.begin = lambda *args, **kwargs: httpx.Response(
        401,
        json={
            "error": {"code": "secret-cookie-url", "message": "secret-body"},
            "request_id": "secret-id",
        },
    )
    with pytest.raises(FixtureContractError):
        h.require_begin(b"private-content")
    output = capsys.readouterr().out
    assert "WSO_ASSET_UPLOAD_DIAGNOSTIC=" in output
    diagnostic = json.loads(output.split("=", 1)[1])
    assert diagnostic["stage"] == "BEGIN"
    assert diagnostic["expected"] == 201 and diagnostic["actual"] == 401
    assert diagnostic["error_code"] == "UNKNOWN"
    assert diagnostic["session_remaining"] == "EXPIRED"
    assert diagnostic["caller"] == "FINISHED" and diagnostic["event_wait"] is False
    assert "secret" not in output and "private-content" not in output


def test_error_diagnostic_preserves_absent_disconnected_response_and_trial(capsys):
    h = AssetHarness.__new__(AssetHarness)
    h._upload_trial = 3
    h._upload_stage = "PUT"
    h._upload_started = time.monotonic()
    h._upload_actor = SimpleNamespace(
        expires_at=datetime.now(UTC) + timedelta(seconds=20)
    )
    response = SimpleNamespace(status_code=None, disconnected=True, content=b"secret")
    with pytest.raises(FixtureContractError):
        h.assert_error(response, 422, "ASSET_LENGTH")
    diagnostic = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert diagnostic["trial"] == "UPLOAD_03" and diagnostic["actual"] == "ABSENT"
    assert diagnostic["disconnected"] is True and diagnostic["expected"] == 422
    assert diagnostic["session_remaining"] == "LE_30S"


def test_original_cutoff_refuses_unsettled_local_worker_and_preserves_body(tmp_path):
    import socket
    import threading

    h = minimal_harness(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        release.wait(2)
        return "172.28.0.2"

    relay = LoopbackRelay(blocked, tmp_path)
    h.provider.relay = relay
    relay.start(deadline=time.monotonic() + 2)
    client = socket.create_connection(relay.address, timeout=1)
    try:
        assert entered.wait(1)
        cutoff = time.monotonic() + 0.03
        h.provider.cleanup_cutoff = cutoff
        original = RuntimeError("body-failure")
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="JOB.*LOCAL_UNSETTLED") as caught:
            h.__exit__(RuntimeError, original, None)
        assert time.monotonic() - started < 0.5
        assert caught.value.__cause__ is original
        assert relay.live_threads and relay.stop.is_set()
        assert h.provider.cleanup_cutoff == cutoff and h.provider.receipt is None
        assert not h.provider_evidence.exists()
    finally:
        release.set()
        client.close()
        relay.close()


def test_local_quiescence_cancels_exact_relay_command_and_joins_worker(tmp_path):
    import os
    import socket

    h = minimal_harness(tmp_path)

    def validate(deadline, stop, commands):
        commands.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            os.environ.copy(),
            deadline,
        )
        raise AssertionError("cancelled command must not authorize forwarding")

    relay = LoopbackRelay(validate, tmp_path)
    h.provider.relay = relay
    relay.start(deadline=time.monotonic() + 3)
    client = socket.create_connection(relay.address, timeout=1)
    process = None
    try:
        cutoff = time.monotonic() + 2
        while process is None and time.monotonic() < cutoff:
            with relay.commands.lock:
                process = next(
                    (
                        r["process"]
                        for r in relay.commands.records.values()
                        if r["process"] is not None
                    ),
                    None,
                )
            time.sleep(0.005)
        assert process is not None and process.poll() is None
        with pytest.raises(RuntimeError, match="JOB.*LOCAL_QUIESCED_TARGET_RETAINED"):
            h.__exit__(None, None, None)
        assert process.poll() is not None
        assert not relay.live_threads and not relay.commands.records
        assert not relay.active_sockets
    finally:
        client.close()
        relay.close()


@pytest.mark.parametrize(
    "finished,error,want",
    [
        (False, None, "RUNNING"),
        (True, None, "FINISHED"),
        (True, RuntimeError("secret-error"), "ERROR"),
    ],
)
def test_event_wait_diagnostic_distinguishes_finished_caller(
    capsys, finished, error, want
):
    import threading

    h = AssetHarness.__new__(AssetHarness)
    done = threading.Event()
    if finished:
        done.set()
    call = SimpleNamespace(done=done, error=error)

    def wait(cutoff):
        raise FixtureContractError()

    with pytest.raises(FixtureContractError):
        h.wait_event(SimpleNamespace(wait=wait), time.monotonic() - 1, call)
    output = capsys.readouterr().out
    assert json.loads(output.split("=", 1)[1]) == {
        "schema": 1,
        "event_wait": True,
        "caller": want,
        "cutoff_expired": True,
    }
    assert "secret" not in output


@pytest.mark.parametrize("failure", ["receipt", "poll", "wait", "log"])
@pytest.mark.parametrize("with_body", [False, True])
def test_early_teardown_failure_still_quiesces_real_relay_and_keeps_cause(
    tmp_path, monkeypatch, failure, with_body
):
    h = minimal_harness(tmp_path)
    h.jobs_context = None
    h.provider.created = [("container", "retained")]
    (tmp_path / "K1").write_bytes(b"retained-key")
    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    h.provider.relay = relay
    relay.start(deadline=time.monotonic() + 2)
    recycled = []
    h.provider.close = lambda: recycled.append(True)
    original = RuntimeError("original-body")
    injected = OSError("private-early-cleanup")

    def refuse(*args, **kwargs):
        raise injected

    if failure == "receipt":
        h.provider_evidence.mkdir()
    else:
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=3)
        log = io.StringIO()
        if failure in {"poll", "wait"}:
            monkeypatch.setattr(process, failure, refuse)
        else:
            log = SimpleNamespace(close=refuse)
        h.launches.append((process, log))
    try:
        try:
            h.__exit__(
                RuntimeError if with_body else None,
                original if with_body else None,
                None,
            )
        except (RuntimeError, OSError) as error:
            caught = error
        else:
            pytest.fail("early cleanup failure was swallowed")
        assert relay.stop.is_set() and not relay.live_threads
        assert caught.__cause__ is (original if with_body else caught.cleanup_causes[0])
        assert isinstance(caught, RuntimeError)
        assert (
            "RECEIPT" in str(caught)
            if failure == "receipt"
            else "LAUNCH" in str(caught)
        )
        assert not recycled
        assert h.provider.created == [("container", "retained")]
        assert (tmp_path / "K1").exists() and not h.provider_evidence.is_file()
        assert h.provider.receipt is None
        assert h.provider.cleanup_cutoff <= h.deadlines.cutoffs[FixturePhase.TEARDOWN]
        if failure != "receipt":
            assert injected in caught.cleanup_causes and h.launches
    finally:
        relay.close()


def test_deadline_setup_failure_reaches_local_quiescence_without_new_budget(
    tmp_path, monkeypatch
):
    h = minimal_harness(tmp_path)
    h.jobs_context = None
    del h.deadlines.cutoffs[FixturePhase.TEARDOWN]
    deadline = time.monotonic() + 1
    h.provider.cleanup_cutoff = deadline
    failure = RuntimeError("deadline-setup")

    def refuse():
        raise failure

    monkeypatch.setattr(h.deadlines, "begin_teardown", refuse)
    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    h.provider.relay = relay
    relay.start(deadline=deadline)
    try:
        with pytest.raises(RuntimeError, match="CUTOFF") as caught:
            h.__exit__(None, None, None)
        assert caught.value.__cause__ is failure
        assert h.provider.cleanup_cutoff == deadline
        assert relay.stop.is_set() and not relay.live_threads
        assert not h.provider_evidence.exists()
    finally:
        relay.close()


@pytest.mark.parametrize("pending", [False, True])
def test_contended_command_registry_refuses_within_original_cutoff(tmp_path, pending):
    import threading

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    entered, release = threading.Event(), threading.Event()
    retained = {"process": None}
    if pending:
        relay.commands.records[17] = retained

    def holder():
        with relay.commands.lock:
            entered.set()
            release.wait(0.25)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        cutoff = started + 0.03
        try:
            relay.close(deadline=cutoff)
        except RuntimeError:
            refused = True
        else:
            refused = False
        assert time.monotonic() - started < 0.15, (
            "registry lock outlived original cutoff"
        )
        assert refused and relay.state != "CLOSED"
        assert relay.stop.is_set() and not relay.live_threads
        if pending:
            assert relay.commands.records[17] is retained
    finally:
        release.set()
        thread.join(1)
        assert not thread.is_alive()
        relay.commands.records.clear()
        relay.close()


def test_post_admission_cutoff_leaves_no_child_custody_retireable(monkeypatch):
    import threading
    from unittest.mock import Mock

    from tests.support.asset_minio import RelayCommands

    commands = RelayCommands(threading.Event())
    clock = Mock(side_effect=[0.0, 0.0, 0.0, 2.0])
    popen = Mock(side_effect=AssertionError("no process may be launched"))
    with monkeypatch.context() as patch:
        patch.setattr("tests.support.asset_minio.time.monotonic", clock)
        patch.setattr("tests.support.asset_minio.subprocess.Popen", popen)
        with pytest.raises(RuntimeError):
            commands.run(["unreached"], {}, 1.0)
    assert popen.call_count == 0
    assert all(record["process"] is None for record in commands.records.values())
    # This is a later cleanup allowance, never a renewed command budget.
    commands.cancel(time.monotonic() + 0.05)
    assert not commands.records


@pytest.mark.parametrize("creates_child", [False, True])
def test_genuine_pending_creator_stays_fenced_until_producer_finishes(
    monkeypatch, creates_child
):
    import threading

    from tests.support.asset_minio import RelayCommands

    commands = RelayCommands(threading.Event())
    entered, release = threading.Event(), threading.Event()
    errors, children = [], []
    popen = subprocess.Popen

    def pending_creation(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        if creates_child:
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        raise OSError("controlled-no-child")

    def producer():
        try:
            commands.run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                {},
                time.monotonic() + 1,
            )
        except RuntimeError as error:
            errors.append(error)

    monkeypatch.setattr("tests.support.asset_minio.subprocess.Popen", pending_creation)
    thread = threading.Thread(target=producer)
    thread.start()
    try:
        assert entered.wait(1)
        identity, record = next(iter(commands.records.items()))
        assert record["process"] is None
        commands.stop.set()
        with pytest.raises(RuntimeError):
            commands.cancel(time.monotonic() + 0.03)
        assert commands.records[identity] is record and thread.is_alive()
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and len(errors) == 1
    commands.cancel(time.monotonic() + 0.05)
    assert not commands.records
    assert len(children) == int(creates_child)
    assert all(child.poll() is not None for child in children)
