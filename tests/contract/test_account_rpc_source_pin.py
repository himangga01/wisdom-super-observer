"""Pure source custody checks; no account RPC runtime or service imports."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/integration/test_tvt_account_rpc.py"
MIGRATION = ROOT / "infra/migrations/versions/0007_tvt_account_sessions.py"
WINDOWS_SHA = "86f154d10c7cd14ca51aae9327982c80f60945f59820ccda1769ca777f510f6d"
LF_SHA = "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608"


@pytest.fixture(scope="module")
def validator():
    # Execute the real pure helper and its pinned constants without importing
    # this integration module's database, server, or transport dependencies.
    tree = ast.parse(FIXTURE.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef) and node.name == "verify_migration_source"
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id in {"MIGRATION_SHA", "MIGRATION_LF_SHA"}
                for target in node.targets
            )
        )
    ]
    namespace = {"hashlib": hashlib}
    exec(  # noqa: S102 - execute the reviewed pure helper, no module imports
        compile(ast.Module(body=nodes, type_ignores=[]), str(FIXTURE), "exec"),
        namespace,
    )
    return namespace["verify_migration_source"]


@pytest.fixture(scope="module")
def reviewed_sources():
    # Both forms are derived from the reviewed migration, independently checked
    # against fixed identities. No Git command or ignored evidence is needed.
    canonical = MIGRATION.read_bytes().replace(b"\r\n", b"\n")
    assert b"\r" not in canonical
    assert hashlib.sha256(canonical).hexdigest() == LF_SHA
    windows = canonical.replace(b"\n", b"\r\n")
    assert hashlib.sha256(windows).hexdigest() == WINDOWS_SHA
    return windows, canonical


@pytest.mark.parametrize("index", [0, 1], ids=["reviewed-windows", "reviewed-git-lf"])
def test_accepts_exact_reviewed_source(validator, reviewed_sources, index):
    validator(reviewed_sources[index])


@pytest.mark.parametrize("index", [0, 1], ids=["windows-mutation", "lf-mutation"])
def test_rejects_single_byte_mutation(validator, reviewed_sources, index):
    source = reviewed_sources[index]
    with pytest.raises(AssertionError):
        validator(bytes([source[0] ^ 1]) + source[1:])


def test_rejects_stray_carriage_return(validator, reviewed_sources):
    with pytest.raises(AssertionError):
        validator(reviewed_sources[1] + b"\r")


@pytest.mark.parametrize("index", [0, 1], ids=["windows-with-lf", "lf-with-crlf"])
def test_rejects_mixed_newlines(validator, reviewed_sources, index):
    source = reviewed_sources[index]
    mixed = (
        source.replace(b"\r\n", b"\n", 1)
        if index == 0
        else source.replace(b"\n", b"\r\n", 1)
    )
    # These bytes have the same canonical identity but an unreviewed raw hash.
    assert mixed.replace(b"\r\n", b"\n") == reviewed_sources[1]
    with pytest.raises(AssertionError):
        validator(mixed)


@pytest.mark.parametrize("source", [b"", b"unrelated source\n", b"\r\n"])
def test_rejects_wrong_source(validator, source):
    with pytest.raises(AssertionError):
        validator(source)


def test_runtime_preflight_checks_exact_migration_before_database_work():
    tree = ast.parse(FIXTURE.read_text(encoding="utf-8"))
    runtime = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "runtime_db"
    )
    activation, preflight = runtime.body[:2]
    assert isinstance(activation, ast.If)
    assert ast.unparse(activation.test) == (
        "os.getenv('WSO_TEST_ACCOUNT_RPC_RUNTIME') != '1'"
    )
    assert ast.unparse(preflight) == (
        "verify_migration_source((ROOT / "
        "'infra/migrations/versions/0007_tvt_account_sessions.py').read_bytes())"
    )
