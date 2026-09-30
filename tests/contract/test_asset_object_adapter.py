from __future__ import annotations

import time
from dataclasses import replace
from uuid import UUID

import pytest
from wso_core.storage import (
    InstallationNamespace,
    IOBudget,
    ObjectLocator,
    S3Command,
    S3ObjectStore,
    StorageFailure,
    UploadedPart,
    validate_command,
)


def owned():
    ns = InstallationNamespace(UUID(int=1), "private-assets")
    loc = ObjectLocator(ns.installation_id, UUID(int=2), UUID(int=3), UUID(int=4))
    return ns, loc


@pytest.mark.parametrize(
    "operation,args",
    [
        ("GET", {"max_bytes": True}),
        ("GET", {"max_bytes": 20971557}),
        ("PUT", {"body": b"x" * 5242917}),
        ("UPLOAD_PART", {"body": b"x" * 5242881, "upload_id": "a", "part_number": 1}),
        ("COMPLETE_MULTIPART", {"upload_id": "a"}),
        ("COMPLETE_MULTIPART", {"upload_id": "a", "parts": (UploadedPart(2, "etag"),)}),
        ("LIST_OBJECTS", {"limit": 101}),
        ("LIST_OBJECTS", {"limit": 1, "cursor": "x" * 4097}),
        ("PRESIGN_GET", {"expires_seconds": 31}),
        ("DELETE", {"cursor": "injected"}),
    ],
)
def test_command_allowlists_and_hard_bounds(operation, args) -> None:
    ns, loc = owned()
    with pytest.raises(StorageFailure):
        validate_command(operation, S3Command(locator=loc, **args), ns)


def test_foreign_installation_rejected() -> None:
    ns, loc = owned()
    with pytest.raises(StorageFailure):
        validate_command(
            "HEAD", S3Command(locator=replace(loc, installation_id=UUID(int=9))), ns
        )


class WrongResultExecutor:
    def local_cleanup_complete(self):
        return True

    def execute(self, operation, args, *, budget):
        return b"unexpected"


def test_wrong_mutating_result_preserves_remote_uncertainty() -> None:
    ns, loc = owned()
    store = S3ObjectStore(client=WrongResultExecutor(), namespace=ns)
    with pytest.raises(StorageFailure) as failure:
        store.delete(loc, budget=IOBudget(time.monotonic() + 5))
    assert failure.value.code == "INTEGRITY"
    assert failure.value.outcome_unknown


class BoundedExecutor:
    def local_cleanup_complete(self):
        return True

    def execute(self, operation, args, *, budget):
        return b"encrypted"


def test_ciphertext_reader_retains_original_budget_and_bounds() -> None:
    ns, loc = owned()
    store = S3ObjectStore(client=BoundedExecutor(), namespace=ns)
    reader = store.get(loc, max_bytes=9, budget=IOBudget(time.monotonic() + 0.03))
    assert reader.read(3) == b"enc"
    with pytest.raises(ValueError):
        reader.read(262145)
    time.sleep(0.05)
    with pytest.raises(StorageFailure) as failure:
        reader.read(3)
    assert failure.value.code == "DEADLINE"
    reader.close()


def test_reader_transport_overflow_rejected_before_reader_exists() -> None:
    ns, loc = owned()
    store = S3ObjectStore(client=BoundedExecutor(), namespace=ns)
    with pytest.raises(StorageFailure) as failure:
        store.get(loc, max_bytes=8, budget=IOBudget(time.monotonic() + 5))
    assert failure.value.code == "LIMIT"


class LateAcknowledgmentExecutor:
    def local_cleanup_complete(self):
        return True

    def execute(self, operation, args, *, budget):
        time.sleep(0.05)


def test_budget_expires_after_mutation_still_preserves_unknown_outcome() -> None:
    ns, loc = owned()
    store = S3ObjectStore(client=LateAcknowledgmentExecutor(), namespace=ns)
    with pytest.raises(StorageFailure) as failure:
        store.delete(loc, budget=IOBudget(time.monotonic() + 0.03))
    assert failure.value.code == "DEADLINE"
    assert failure.value.outcome_unknown


class CleanupStatusExecutor(BoundedExecutor):
    healthy = False

    def local_cleanup_complete(self):
        return self.healthy


def test_object_store_cleanup_query_delegates_explicit_executor_status() -> None:
    ns, _ = owned()
    client = CleanupStatusExecutor()
    store = S3ObjectStore(client=client, namespace=ns)
    assert not store.local_cleanup_complete()
    client.healthy = True
    assert store.local_cleanup_complete()


@pytest.mark.parametrize(
    "upload",
    ["a" * 1024, '"' * 1024, "\\" * 1024, "\U0010ffff" * 1024, "\ud800" * 1024],
    ids=["ascii", "quotes", "backslashes", "astral", "surrogates"],
)
def test_multipart_cursor_preserves_maximum_opaque_unicode_and_unknown_keys(
    upload,
) -> None:
    from wso_core.asset_s3_worker import _cursor_encode, _cursor_read
    from wso_core.storage import installation_prefix

    ns, _ = owned()
    key = installation_prefix(ns) + "\n" * (1024 - len(installation_prefix(ns)))
    marker = {"key": key, "upload": upload}
    cursor = _cursor_encode(marker)
    assert len(cursor) <= 4096
    assert _cursor_read(cursor, {"key", "upload"}) == marker


def test_maximum_multipart_wire_page_fits_control_cap_with_cursor() -> None:
    from datetime import UTC, datetime

    from wso_core.asset_process import CONTROL_CAP, encode_control
    from wso_core.asset_s3_worker import (
        _cursor_encode,
        _multipart_page_limit,
        _result_wire,
    )
    from wso_core.storage import MultipartEntry, MultipartPage, installation_prefix

    ns, loc = owned()
    cursor = _cursor_encode(
        {
            "key": installation_prefix(ns)
            + "\n" * (1024 - len(installation_prefix(ns))),
            "upload": "\U0010ffff" * 1024,
        }
    )
    limit = _multipart_page_limit()
    assert 1 <= limit < 100
    entry = MultipartEntry(
        loc, "\U0010ffff" * 1024, datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    )
    page = MultipartPage((entry,) * limit, cursor)
    control, body = _result_wire(page)
    assert body == b""
    assert len(encode_control({"ok": True, "result": control})) <= CONTROL_CAP


@pytest.mark.parametrize(
    "corruption",
    ["version", "truncated", "alphabet", "padding", "extra-zero-word"],
)
def test_multipart_cursor_rejects_noncanonical_wire(corruption) -> None:
    from wso_core.asset_s3_worker import _cursor_encode, _cursor_read

    cursor = _cursor_encode({"key": "a", "upload": "b"})
    damaged = {
        "version": "M2" + cursor[2:],
        "truncated": cursor[:-1],
        "alphabet": cursor[:-1] + "\u9000",
        "padding": cursor[:-1] + chr(ord(cursor[-1]) + 1),
        "extra-zero-word": cursor + "\u1000",
    }[corruption]
    with pytest.raises(StorageFailure) as failure:
        _cursor_read(damaged, {"key", "upload"})
    assert failure.value.code == "INTEGRITY"


@pytest.mark.parametrize(
    "raw",
    [
        b"\x00\x00\x00\x01b",  # Empty key.
        b"\x00\x01\x00\x00a",  # Empty upload ID.
        b"\x04\x01\x00\x01ab",  # Oversized key header.
        b"\x00\x01\x10\x01ab",  # Oversized upload header.
        b"\x00\x01\x00\x01\xffb",  # Invalid key UTF-8.
        b"\x00\x01\x00\x01a\n",  # Forbidden upload control character.
    ],
    ids=["empty-key", "empty-id", "key-bound", "id-bound", "utf8", "id-control"],
)
def test_multipart_cursor_rejects_invalid_marker_payload(raw) -> None:
    from wso_core.asset_s3_worker import _cursor_read

    # Independent whole-integer packing constructs malformed wire payloads.
    words = (len(raw) * 8 + 14) // 15
    packed = int.from_bytes(raw, "big") << (words * 15 - len(raw) * 8)
    cursor = "M1" + "".join(
        chr(0x1000 + ((packed >> (15 * index)) & 32767))
        for index in reversed(range(words))
    )
    with pytest.raises(StorageFailure) as failure:
        _cursor_read(cursor, {"key", "upload"})
    assert failure.value.code == "INTEGRITY"


def test_maximum_multipart_cursor_request_fits_with_explicit_credentials() -> None:
    from wso_core.asset_process import CONTROL_CAP, encode_control
    from wso_core.asset_s3_worker import _command_wire, _configuration, _cursor_encode
    from wso_core.storage import S3Credentials, S3RuntimeConfig, installation_prefix

    ns, loc = owned()
    config = S3RuntimeConfig(
        "https://s3.example.test", "us-east-1", S3Credentials("key", "secret"), ns
    )
    cursor = _cursor_encode(
        {
            "key": installation_prefix(ns)
            + "\n" * (1024 - len(installation_prefix(ns))),
            "upload": "\U0010ffff" * 1024,
        }
    )
    command = S3Command(locator=loc, cursor=cursor, limit=100)
    frame = encode_control(
        {
            "version": 1,
            "config": _configuration(config),
            "operation": "LIST_MULTIPART",
            "command": _command_wire(command),
        }
    )
    assert len(frame) <= CONTROL_CAP
