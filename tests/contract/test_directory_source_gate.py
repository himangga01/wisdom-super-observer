"""Offline W07 activation contracts; no database, Docker or network execution."""

import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SDD = ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan"
FIXTURE = "tests/tvt_parity/fixtures/directory-approved-sources.json"
LOCAL = SDD + "/W07-directory-api-evidence/composition-gate.json"
PIN = "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958"
FLAGS = {
    "WSO_TEST_W07_DIRECTORY_ACCEPTANCE": "1",
    "WSO_TEST_W07_API_ACCEPTANCE": "1",
    "WSO_TEST_W07_PARENT_SHA256": PIN,
}
CI = {
    "CI": "true",
    "WSO_CI_DISPOSABLE_POSTGRES": "1",
    "WSO_TEST_RECOVERY_DATABASE_NAME": "wso_ci_test",
    "WSO_TEST_RECOVERY_DATABASE_OWNER": "postgres",
    "WSO_CI_RUNTIME_OWNER": "a" * 32,
}


def test_strict_activation_helper_is_committed():
    assert (ROOT / "tests/support/directory_source_gate.py").is_file(), (
        "Missing committed strict W07 source activation helper"
    )


@pytest.fixture
def gate(monkeypatch, tmp_path):
    helper = ROOT / "tests/support/directory_source_gate.py"
    assert helper.is_file(), "Missing committed strict W07 source activation helper"
    runtime = importlib.import_module("tests.support.directory_source_gate")
    accepted = (ROOT / FIXTURE).read_bytes()
    data = json.loads(accepted)
    for relative in (*data["sources"], FIXTURE, LOCAL):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative == LOCAL:
            target.write_bytes(LOCAL_RECEIPT_BYTES)
        elif relative == FIXTURE:
            target.write_bytes(accepted)
        else:
            target.write_bytes(recorded_raw_source(relative, data["sources"][relative]))
    parent = tmp_path / "infra/migrations/versions/0010_tvt_account_flows.py"
    parent.write_bytes((ROOT / parent.relative_to(tmp_path)).read_bytes())
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    for name, value in (FLAGS | CI).items():
        monkeypatch.setenv(name, value)
    return runtime, tmp_path, data


def recorded_raw_source(relative, identities):
    """Reconstruct test snapshots only, checked against the fixed reviewed raw pin."""
    live = (ROOT / relative).read_bytes()
    assert hashlib.sha256(live).hexdigest() in identities.values()
    lf = live.replace(b"\r\n", b"\n")
    candidates = [live, lf, lf.replace(b"\n", b"\r\n")]
    if relative == "docs/integrations/tvt-directory-rpc.md":
        boundary = lf.index(b"\n## W07 RPC Fix1 review correction (2026-10-03)")
        candidates.append(lf[:boundary] + lf[boundary:].replace(b"\n", b"\r\n"))
    return next(
        raw
        for raw in candidates
        if hashlib.sha256(raw).hexdigest() == identities["raw_sha256"]
    )


def test_fixed_committed_ci_gate_accepts_reviewed_current19(gate):
    runtime, root, _ = gate
    (root / LOCAL).unlink()
    runtime.verify_directory_source_gate()


def test_fixture_is_verbatim_fixed_root_input():
    assert (ROOT / FIXTURE).is_file(), "Missing committed reviewed W07 CI fixture"
    raw = (ROOT / FIXTURE).read_bytes()
    assert hashlib.sha256(raw).hexdigest() in {
        "03064a0906958dc2b318fa819bac3aa93c7c35834eb49b1034e45c2dbb4f1c44",
        "194562c6ea78099c8f5900320a1a2cf41d3d36c1461a601c1b11b73d4ea023d9",
    }
    assert len(json.loads(raw)["sources"]) == 19


@pytest.mark.parametrize("key", list(FLAGS))
@pytest.mark.parametrize("value", [None, "", "0", "true", "1 "])
def test_partial_or_invalid_activation_fails_closed(gate, monkeypatch, key, value):
    runtime, _, _ = gate
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def test_all_settings_absent_preserves_optional_opt_in(gate, monkeypatch):
    runtime, _, _ = gate
    for key in FLAGS:
        monkeypatch.delenv(key)
    with pytest.raises(pytest.skip.Exception):
        runtime.verify_directory_source_gate()


@pytest.mark.parametrize("key", list(CI))
@pytest.mark.parametrize("value", [None, "", "wrong"])
def test_linux_requires_every_managed_ci_opt_in(gate, monkeypatch, key, value):
    runtime, _, _ = gate
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


@pytest.mark.parametrize("platform", ["darwin", "linux2", ""])
def test_other_platforms_cannot_select_ci_fixture(gate, monkeypatch, platform):
    runtime, _, _ = gate
    monkeypatch.setattr(runtime.sys, "platform", platform)
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def test_windows_still_requires_explicit_root_current_flat19(gate, monkeypatch):
    runtime, root, data = gate
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    runtime.verify_directory_source_gate()
    path = next(iter(data["sources"]))
    (root / path).write_bytes((root / path).read_bytes() + b"\n")
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def test_windows_never_falls_back_to_ci_fixture(gate, monkeypatch):
    runtime, root, _ = gate
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    (root / LOCAL).unlink()
    with pytest.raises(FileNotFoundError):
        runtime.verify_directory_source_gate()


@pytest.mark.parametrize("receipt", ["fixture", "local"])
@pytest.mark.parametrize(
    "change",
    [
        "missing-approval",
        "false-approval",
        "wrong-family",
        "wrong-parent",
        "missing-source",
        "extra-source",
        "duplicate-source",
        "duplicate-key",
        "extra-field",
        "invalid-digest",
        "computed-approval",
        "empty-sources",
        "bom",
        "bare-cr",
        "mixed-eol",
    ],
)
def test_closed_fixed_receipts_reject_tampering(gate, monkeypatch, receipt, change):
    runtime, root, _ = gate
    if receipt == "local":
        monkeypatch.setattr(runtime.sys, "platform", "win32")
    target = root / (FIXTURE if receipt == "fixture" else LOCAL)
    raw = target.read_bytes()
    data = json.loads(raw)
    approval = (
        "root_source_approval" if receipt == "fixture" else "root_explicitly_accepted"
    )
    if change == "missing-approval":
        del data[approval]
    elif change == "false-approval":
        data[approval] = False
    elif change == "wrong-family":
        data["source_family"] = "unknown"
    elif change == "wrong-parent":
        data["parent_sha256"] = "0" * 64
    elif change == "missing-source":
        data["sources"].pop(next(iter(data["sources"])))
    elif change == "extra-source":
        data["sources"]["unreviewed.py"] = "0" * 64
    elif change == "extra-field":
        data["allow_unknown_sources"] = True
    elif change == "invalid-digest":
        data["sources"][next(iter(data["sources"]))] = "invalid"
    elif change == "computed-approval":
        source = next(iter(data["sources"]))
        changed = (root / source).read_bytes() + b"# unreviewed\n"
        (root / source).write_bytes(changed)
        digest = hashlib.sha256(changed).hexdigest()
        data["sources"][source] = (
            {"raw_sha256": digest, "canonical_lf_sha256": digest}
            if receipt == "fixture"
            else digest
        )
    elif change == "empty-sources":
        data["sources"] = {}
    if change == "duplicate-source":
        name, value = next(iter(data["sources"].items()))
        text = json.dumps(data).replace(
            '"sources": {',
            '"sources": {' + json.dumps(name) + ": " + json.dumps(value) + ",",
        )
        raw = text.encode()
    elif change == "duplicate-key":
        raw = (
            '{"parent_sha256": ' + json.dumps(PIN) + "," + json.dumps(data)[1:]
        ).encode()
    elif change == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif change == "bare-cr":
        raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r")
    elif change == "mixed-eol":
        raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n", 1)
    else:
        raw = json.dumps(data).encode()
    target.write_bytes(raw)
    with pytest.raises((AssertionError, ValueError)):
        runtime.verify_directory_source_gate()


@pytest.mark.parametrize("variant", ["raw", "lf"])
def test_exact_recorded_raw_or_lf_sources_are_accepted(gate, variant):
    runtime, root, data = gate
    for name, identities in data["sources"].items():
        raw = (root / name).read_bytes()
        selected = raw if variant == "raw" else raw.replace(b"\r\n", b"\n")
        assert (
            hashlib.sha256(selected).hexdigest()
            == identities["raw_sha256" if variant == "raw" else "canonical_lf_sha256"]
        )
        (root / name).write_bytes(selected)
    runtime.verify_directory_source_gate()


@pytest.mark.parametrize(
    "change", ["bom", "bare-cr", "mixed-eol", "content", "new-crlf"]
)
def test_unrecorded_source_bytes_cannot_be_normalized_into_approval(gate, change):
    runtime, root, data = gate
    name = (
        "services/tvt-bridge/src/wso_tvt_bridge/directory_config.py"
        if change == "new-crlf"
        else next(iter(data["sources"]))
    )
    target = root / name
    raw = target.read_bytes()
    variants = {
        "bom": b"\xef\xbb\xbf" + raw,
        "bare-cr": raw.replace(b"\r\n", b"\r"),
        "mixed-eol": raw.replace(b"\r\n", b"\n", 1),
        "content": raw + b"# unreviewed\n",
        "new-crlf": raw.replace(b"\n", b"\r\n"),
    }
    target.write_bytes(variants[change])
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def test_parent_live_bytes_are_pinned_before_authority(gate):
    runtime, root, _ = gate
    (root / "infra/migrations/versions/0010_tvt_account_flows.py").write_bytes(
        b"unknown\n"
    )
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def test_exact_lf_fixture_is_portable_without_local_evidence(gate):
    runtime, root, _ = gate
    target = root / FIXTURE
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
    (root / LOCAL).unlink()
    runtime.verify_directory_source_gate()


def test_linux_missing_committed_fixture_never_falls_back_to_local(gate):
    runtime, root, _ = gate
    (root / FIXTURE).unlink()
    with pytest.raises(FileNotFoundError):
        runtime.verify_directory_source_gate()


@pytest.mark.parametrize(
    "relative", list(json.loads((ROOT / FIXTURE).read_bytes())["sources"])
)
def test_each_reviewed_source_is_required_and_verified(gate, relative):
    runtime, root, _ = gate
    target = root / relative
    original = target.read_bytes()
    target.write_bytes(original + b"# unreviewed\n")
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()
    target.unlink()
    with pytest.raises(FileNotFoundError):
        runtime.verify_directory_source_gate()


def test_local_root_requires_exact_raw_not_ci_lf_alias(gate, monkeypatch):
    runtime, root, data = gate
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    name = next(iter(data["sources"]))
    target = root / name
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(AssertionError):
        runtime.verify_directory_source_gate()


def consumed_owned_fixture():
    tree = ast.parse((ROOT / "tests/tvt_parity/test_directory_api.py").read_bytes())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "owned_directory_database"
    )
    node.decorator_list = []
    namespace = {
        "pytest": pytest,
        "json": json,
        "__file__": str(ROOT / "tests/tvt_parity/test_directory_api.py"),
    }
    exec(  # noqa: S102 - Execute only the extracted offline fixture, never SQL imports.
        compile(
            ast.Module(body=[node], type_ignores=[]),
            "consumed-owned-directory-fixture",
            "exec",
        ),
        namespace,
    )
    return namespace["owned_directory_database"]


def test_consumed_api_fixture_rejects_partial_flags_before_owned_database(monkeypatch):
    for key, value in FLAGS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WSO_TEST_W07_DIRECTORY_ACCEPTANCE")

    def refused_boundary():
        raise RuntimeError("owned boundary reached before complete source activation")
        yield  # This double is a generator, matching the real fixture protocol.

    authority = SimpleNamespace(
        EVIDENCE="original",
        directory_database=SimpleNamespace(__wrapped__=refused_boundary),
    )
    monkeypatch.setitem(
        sys.modules, "tests.integration.test_tvt_directory_admission", authority
    )
    with pytest.raises(AssertionError):
        next(consumed_owned_fixture()())


def test_consumed_api_fixture_validates_source_before_owned_database(gate, monkeypatch):
    _, root, data = gate
    events = []

    def owned():
        events.append("owned-database-boundary")
        yield "offline-engine-marker"
        events.append("owned-cleanup-boundary")

    authority = SimpleNamespace(
        EVIDENCE="original", directory_database=SimpleNamespace(__wrapped__=owned)
    )
    monkeypatch.setitem(
        sys.modules, "tests.integration.test_tvt_directory_admission", authority
    )
    generator = consumed_owned_fixture()()
    assert next(generator) == "offline-engine-marker"
    assert events == ["owned-database-boundary"]
    assert next(generator, None) is None
    assert events == ["owned-database-boundary", "owned-cleanup-boundary"]
    assert authority.EVIDENCE == "original"
    target = root / next(iter(data["sources"]))
    target.write_bytes(target.read_bytes() + b"# drift\n")
    with pytest.raises(AssertionError):
        next(consumed_owned_fixture()())
    assert events == ["owned-database-boundary", "owned-cleanup-boundary"]


# Hermetic historical root receipt for offline tests; the helper never creates one.
LOCAL_RECEIPT_BYTES = (
    b"{\r\n"
    b'  "root_explicitly_accepted": true,\r\n'
    b'  "scope": "sole contained synthetic six-read API/PG/mTLS/HTTPS case",\r\n'
    b'  "sources": {\r\n'
    b'    "packages/contracts/src/wso_contracts/tvt/directory.py": "8f762a0993d7296bc6c6a0684bef0a9f3c31b9083bacf82cee8f39333cbb81c4",\r\n'
    b'    "infra/migrations/versions/0011_tvt_directory_read_tickets.py": "d9a7b30e8bf286602ef059a66c24f916ddf31fcb8075430c0c64dee12ac258e0",\r\n'
    b'    "packages/core/src/wso_core/tvt/directory_admission.py": "08d10ba590d57fb71f35c790ae03fc24553ace65a623369434d295c911118abc",\r\n'
    b'    "services/api/src/wso_api/tvt/device_service.py": "56d029bfc0f99468ea4ce51a2fb8abf3fda99dcac045ecce0ae99a417175fcc1",\r\n'
    b'    "tests/tvt_parity/test_directory_service.py": "15792a2ba91860578f7db75a9348c13495b415067dc38160e4a4d0834804f75b",\r\n'
    b'    "tests/integration/test_tvt_directory_admission.py": "fd378890d0ef7a68da9f0e8904fa515b7d8a34655bab6524a5004471e8cbb47c",\r\n'
    b'    "tests/integration/test_tenant_isolation.py": "eeec39dfdb91596e5b6f1b1acccfd09dd570e4788801d8c052c82ae5832b9173",\r\n'
    b'    "tests/integration/test_tvt_account_flow_admission.py": "2631dd3040cbb0ff87c7af162ac0d6737c1feec08d951a9b5623ea3822bff6fd",\r\n'
    b'    "tests/contract/test_flow_fixture_portability.py": "1c3911ca4e62290d3b20c039f7c0b6f6e54367c0b53b6e98cf08756803d57333",\r\n'
    b'    "docs/integrations/tvt-directory-service.md": "ea6c6999a4c25b7b9765df5c145341a9b28eb13ce8707c5fa20695328dc9907f",\r\n'
    b'    "packages/contracts/proto/tvt_bridge.proto": "79912d203e1eebe40fba93ed64c941a34ba42227542f271fafdcdd8506695d38",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2.py": "a696751a4a34fe2eddd5708f750f87042fa3b5ee17c53cf38b58c643262059ca",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2_grpc.py": "d0819b81384e840b9c6889e78ddf682433d2518ba8dea024ec3ef8c52f4f25e4",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/client.py": "50b5d1ab230faede8f83bc3b6c9ab0b46cbc31d7811db3b3abc88e0511c01647",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/server.py": "f32548f60a2ae0fd0354ae2d7123851d4251ad2c3dc6567a99d02faa8a956f9c",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/selected.py": "0377a282f8099d0d0584df49b7b3974b6d30946943236c9959adb8c78ac5ca63",\r\n'
    b'    "services/tvt-bridge/src/wso_tvt_bridge/directory_config.py": "14936bb3b1037c6f756897438b5707273669e7364393e60371b70b8a3d14e4de",\r\n'
    b'    "tests/tvt_parity/test_directory_rpc.py": "d61439f293adfa059dad98e8b9150d2f4fa6df4a4a00d77de24a068519985ecc",\r\n'
    b'    "docs/integrations/tvt-directory-rpc.md": "0723ace7df49cade8fa1b2dfafb9fbefa734838c6de6d55b402c5c4c4864e56d"\r\n'
    b"  },\r\n"
    b'  "parent_sha256": "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958",\r\n'
    b'  "worker_review": {\r\n'
    b'    "path": ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-protected-directory-service-Fix1-review.md",\r\n'
    b'    "sha256": "dc5b4462e26dab1a08d154387ffc3c6e92f431f3f92894cb9418d11d224f7c08",\r\n'
    b'    "critical": 0,\r\n'
    b'    "important": 0,\r\n'
    b'    "minor": 0\r\n'
    b"  },\r\n"
    b'  "rpc_review": {\r\n'
    b'    "path": ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-rpc-Fix1-review.md",\r\n'
    b'    "sha256": "813b7d502ea30d589982585487f0ce80497b0c797ff5ad8f1f129845543d4383",\r\n'
    b'    "critical": 0,\r\n'
    b'    "important": 0,\r\n'
    b'    "minor": 0\r\n'
    b"  },\r\n"
    b'  "vendor_or_APK_acceptance": false\r\n'
    b"}\r\n"
)
