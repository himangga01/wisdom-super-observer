"""Exercise the real error callback without PostgreSQL or integration imports."""

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

SOURCE = (
    Path(__file__).resolve().parents[2] / "tests/integration/test_tvt_operations.py"
)


class VendorError(Exception):
    sqlstate = "42501"
    diag = SimpleNamespace(message_primary="private-server-message")


@pytest.fixture
def callback(tmp_path):
    # Compile only the real callback, following the source-extraction contract
    # pattern. Integration collection would import unrelated fixture runtimes.
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "diagnostic"
    ]
    assert len(nodes) == 1
    namespace = {"EVIDENCE": tmp_path / "fresh" / "evidence", "re": re}
    exec(  # noqa: S102 - execute the real isolated callback, no integration imports
        compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"),
        namespace,
    )
    return namespace["diagnostic"], namespace["EVIDENCE"]


@pytest.mark.parametrize("sqlstate", ["42702", "42703", "42601", "42501"])
def test_known_sqlstate_creates_missing_parent_and_records_safe_metadata(
    callback, sqlstate
):
    diagnostic, evidence = callback
    error = VendorError("private-connection-url")
    error.sqlstate = sqlstate
    context = SimpleNamespace(
        original_exception=error,
        statement="private-sql-statement",
        parameters={"password": "private-parameter"},
    )

    assert diagnostic(context) is None
    record = (evidence / "sql-diagnostics.txt").read_text(encoding="utf-8")
    assert record == f"{sqlstate}: VendorError\n"
    assert context.original_exception is error


def test_records_append_without_overwriting_previous_denial(callback):
    diagnostic, evidence = callback
    context = SimpleNamespace(original_exception=VendorError())
    diagnostic(context)
    diagnostic(context)
    assert (evidence / "sql-diagnostics.txt").read_text(encoding="utf-8") == (
        "42501: VendorError\n42501: VendorError\n"
    )


@pytest.mark.parametrize("sqlstate", [None, "23505", "42501\nprivate-message"])
def test_unknown_sqlstate_has_no_artifact_side_effect(callback, sqlstate):
    diagnostic, evidence = callback
    error = VendorError()
    error.sqlstate = sqlstate
    assert diagnostic(SimpleNamespace(original_exception=error)) is None
    assert not evidence.parent.exists()


def test_file_as_parent_cannot_replace_original_error(callback):
    diagnostic, evidence = callback
    evidence.parent.write_text("owned sentinel", encoding="utf-8")
    error = VendorError()
    assert diagnostic(SimpleNamespace(original_exception=error)) is None
    assert evidence.parent.read_text(encoding="utf-8") == "owned sentinel"


def test_nonwritable_output_cannot_replace_original_error(callback, monkeypatch):
    diagnostic, evidence = callback
    evidence.mkdir(parents=True)
    output = evidence / "sql-diagnostics.txt"
    output.write_text("owned sentinel", encoding="utf-8")
    original_open = Path.open

    def deny_output(path, *args, **kwargs):
        if path == output and args and args[0] == "a":
            raise PermissionError("synthetic nonwritable artifact")
        return original_open(path, *args, **kwargs)

    # Portable Windows/Linux permission injection at the I/O boundary; the
    # callback and its remaining filesystem behavior are real.
    monkeypatch.setattr(Path, "open", deny_output)
    assert diagnostic(SimpleNamespace(original_exception=VendorError())) is None
    assert output.read_text(encoding="utf-8") == "owned sentinel"


def test_malformed_vendor_message_is_never_read(callback):
    diagnostic, evidence = callback

    class BrokenDiagnostic(VendorError):
        @property
        def diag(self):
            raise ValueError("private malformed vendor metadata")

        def __str__(self):
            raise ValueError("private malformed vendor message")

    assert diagnostic(SimpleNamespace(original_exception=BrokenDiagnostic())) is None
    assert (evidence / "sql-diagnostics.txt").read_text(encoding="utf-8") == (
        "42501: BrokenDiagnostic\n"
    )


def test_malformed_sqlstate_cannot_replace_original_error(callback):
    diagnostic, evidence = callback

    class BrokenState(VendorError):
        @property
        def sqlstate(self):
            raise ValueError("private malformed state")

    assert diagnostic(SimpleNamespace(original_exception=BrokenState())) is None
    assert not evidence.exists()


def test_sqlstate_formatting_cannot_write_arbitrary_vendor_metadata(callback):
    diagnostic, evidence = callback

    class VendorState(str):
        def __format__(self, specification):
            return "private arbitrary vendor message"

    error = VendorError()
    error.sqlstate = VendorState("42501")
    assert diagnostic(SimpleNamespace(original_exception=error)) is None
    assert not evidence.exists()


def test_malformed_error_class_is_bounded(callback):
    diagnostic, evidence = callback
    error_type = type("private\n" + "x" * 100, (VendorError,), {})
    assert diagnostic(SimpleNamespace(original_exception=error_type())) is None
    assert (evidence / "sql-diagnostics.txt").read_text(encoding="utf-8") == (
        "42501: DBAPIError\n"
    )


@pytest.mark.parametrize("blocked", [False, True], ids=["fresh-parent", "file-parent"])
def test_sqlalchemy_keeps_original_dbapi_error_propagation(callback, blocked):
    diagnostic, evidence = callback
    if blocked:
        evidence.parent.write_text("owned sentinel", encoding="utf-8")
    original = []
    engine = create_engine("sqlite://", hide_parameters=True)

    def on_error(context):
        original.append(context.original_exception)
        context.original_exception.sqlstate = "42501"
        return diagnostic(context)

    event.listen(engine, "handle_error", on_error)
    try:
        with engine.connect() as connection, pytest.raises(DBAPIError) as raised:
            connection.execute(text("SELECT * FROM private_missing_table"))
        assert len(original) == 1
        assert raised.value.orig is original[0]
        assert raised.value.orig.sqlstate == "42501"
        if not blocked:
            assert (evidence / "sql-diagnostics.txt").read_text(encoding="utf-8") == (
                "42501: OperationalError\n"
            )
    finally:
        engine.dispose()
