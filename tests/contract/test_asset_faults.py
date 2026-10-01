"""Independent offline contracts for the full14 fixture request matcher."""

from uuid import UUID

import pytest

OBJECT_PATH = (
    b"/fixture-bucket/wso-assets/v1/00000000000000000000000000000001/objects/"
    b"00000000000000000000000000000002/00000000000000000000000000000003/"
    b"00000000000000000000000000000004.wso"
)


def test_create_multipart_selector_dispatches_complete_owned_request() -> None:
    from wso_core.storage import InstallationNamespace, ObjectLocator

    from tests.support.asset_faults import (
        MatchResult,
        S3FaultSelector,
        S3Operation,
        match_s3_request,
    )

    selector = S3FaultSelector(
        S3Operation.CREATE_MULTIPART,
        InstallationNamespace(UUID(int=1), "fixture-bucket"),
        ObjectLocator(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)),
    )
    header = (
        b"POST " + OBJECT_PATH + b"?uploads HTTP/1.1\r\nHost: 127.0.0.1:9000\r\n\r\n"
    )
    assert match_s3_request(header, selector) is MatchResult.MATCH
    assert (
        match_s3_request(header.replace(b"POST ", b"PUT ", 1), selector)
        is MatchResult.UNMATCHED
    )
    assert (
        match_s3_request(header.replace(b"?uploads ", b"?uploads&uploads "), selector)
        is MatchResult.INVALID
    )


def selector(operation, **fields):
    from wso_core.storage import InstallationNamespace, ObjectLocator

    from tests.support.asset_faults import S3FaultSelector, S3Operation

    if operation not in {"LIST_OBJECTS", "LIST_MULTIPART"}:
        fields.setdefault(
            "locator",
            ObjectLocator(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)),
        )
    return S3FaultSelector(
        S3Operation(operation),
        InstallationNamespace(UUID(int=1), "fixture-bucket"),
        **fields,
    )


def request(method, target, headers=b"Host: 127.0.0.1:9000\r\n"):
    return method + b" " + target + b" HTTP/1.1\r\n" + headers + b"\r\n"


@pytest.mark.parametrize(
    "operation,fields,method,target",
    [
        ("CREATE_MULTIPART", {}, b"POST", OBJECT_PATH + b"?uploads="),
        (
            "UPLOAD_PART",
            {"upload_id": "u+/=", "part_number": 10000},
            b"PUT",
            OBJECT_PATH + b"?partNumber=10000&uploadId=u%2B%2F%3D",
        ),
        (
            "COMPLETE_MULTIPART",
            {"upload_id": "u+/="},
            b"POST",
            OBJECT_PATH + b"?uploadId=u%2B%2F%3D",
        ),
        ("DELETE_OBJECT", {}, b"DELETE", OBJECT_PATH),
        (
            "LIST_OBJECTS",
            {"limit": 1},
            b"GET",
            (
                b"/fixture-bucket?list-type=2&prefix=wso-assets%2Fv1%2F"
                b"00000000000000000000000000000001%2F&max-keys=1"
            ),
        ),
        (
            "LIST_MULTIPART",
            {"limit": 100},
            b"GET",
            (
                b"/fixture-bucket?uploads&prefix=wso-assets%2Fv1%2F"
                b"00000000000000000000000000000001%2F&max-uploads=100"
            ),
        ),
    ],
)
def test_six_operations_match_literal_native_requests(
    operation, fields, method, target
) -> None:
    from tests.support.asset_faults import MatchResult, match_s3_request

    assert (
        match_s3_request(request(method, target), selector(operation, **fields))
        is MatchResult.MATCH
    )


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize(
    "suffix,want",
    [
        (b"", "MATCH"),
        (b"&encoding-type=url", "MATCH"),
        (b"&encoding-type=URL", "INVALID"),
        (b"&encoding-type=", "INVALID"),
        (b"&encoding-type=url&encoding-type=url", "INVALID"),
    ],
)
def test_native_list_encoding_is_optional_exact_and_unique(operation, suffix, want):
    from tests.support.asset_faults import MatchResult, match_s3_request

    start = (
        b"/fixture-bucket?list-type=2&max-keys=1"
        if operation == "LIST_OBJECTS"
        else b"/fixture-bucket?uploads&max-uploads=1"
    )
    target = (
        start
        + b"&prefix=wso-assets%2Fv1%2F00000000000000000000000000000001%2F"
        + suffix
    )
    assert match_s3_request(
        request(b"GET", target), selector(operation, limit=1)
    ) is MatchResult(want)


def test_object_operations_reject_list_encoding_field():
    from tests.support.asset_faults import MatchResult, match_s3_request

    assert (
        match_s3_request(
            request(b"POST", OBJECT_PATH + b"?uploads&encoding-type=url"),
            selector("CREATE_MULTIPART"),
        )
        is MatchResult.INVALID
    )


@pytest.mark.parametrize("stream", ["objects", "multipart"])
def test_retained_cursor_requires_exact_native_marker_and_decodes_once(stream):
    from tests.support.asset_faults import (
        MatchResult,
        MultipartPageCursor,
        ObjectPageCursor,
        match_s3_request,
    )

    if stream == "objects":
        selected = selector("LIST_OBJECTS", limit=1, cursor=ObjectPageCursor("c+/=%2F"))
        target = (
            b"/fixture-bucket?list-type=2&max-keys=1&continuation-token=c%2B%2F%3D%252F"
        )
        missing = b"/fixture-bucket?list-type=2&max-keys=1"
    else:
        selected = selector(
            "LIST_MULTIPART",
            limit=1,
            cursor=MultipartPageCursor("tail/key", "u+/="),
        )
        target = b"/fixture-bucket?uploads&max-uploads=1&key-marker=tail%2Fkey&upload-id-marker=u%2B%2F%3D"
        missing = b"/fixture-bucket?uploads&max-uploads=1"
    prefix = b"&prefix=wso-assets%2Fv1%2F00000000000000000000000000000001%2F"
    assert (
        match_s3_request(request(b"GET", target + prefix), selected)
        is MatchResult.MATCH
    )
    assert (
        match_s3_request(request(b"GET", missing + prefix), selected)
        is MatchResult.UNMATCHED
    )
    assert (
        match_s3_request(
            request(b"GET", target.replace(b"%2B", b"%2D") + prefix), selected
        )
        is MatchResult.UNMATCHED
    )


@pytest.mark.parametrize(
    "method,target,want",
    [
        (b"PUT", OBJECT_PATH + b"?uploadId=other&partNumber=1", "UNMATCHED"),
        (b"PUT", OBJECT_PATH + b"?uploadId=u&partNumber=2", "UNMATCHED"),
        (
            b"PUT",
            OBJECT_PATH.replace(b"fixture-bucket", b"other-bucket")
            + b"?uploadId=u&partNumber=1",
            "UNMATCHED",
        ),
        (
            b"PUT",
            OBJECT_PATH + b"?uploadId=u&partNumber=1&backend=127.0.0.1",
            "INVALID",
        ),
        (b"PUT", OBJECT_PATH + b"?uploadId=u&partNumber=1&partNumber=1", "INVALID"),
        (b"PUT", OBJECT_PATH + b"?uploadId=u&partNumber=%GG", "INVALID"),
        (b"PUT", OBJECT_PATH + b"?uploadId=u%00&partNumber=1", "INVALID"),
        (b"PUT", OBJECT_PATH + b"?uploadId=u&partNumber=1&%75ploadId=u", "INVALID"),
    ],
)
def test_known_mismatch_and_ambiguous_query_are_distinct(method, target, want):
    from tests.support.asset_faults import MatchResult, match_s3_request

    assert match_s3_request(
        request(method, target),
        selector("UPLOAD_PART", upload_id="u", part_number=1),
    ) is MatchResult(want)


@pytest.mark.parametrize(
    "header",
    [
        b"POST / HTTP/1.1\r\nHost: local\r\n",
        request(b"POST", b"http://127.0.0.1:9000" + OBJECT_PATH + b"?uploads"),
        request(b"POST", OBJECT_PATH + b"?uploads", b""),
        request(b"POST", OBJECT_PATH + b"?uploads", b"Host: local\r\nhost: other\r\n"),
        request(
            b"POST", OBJECT_PATH + b"?uploads", b"Host: local\r\nX-Field: a\x01b\r\n"
        ),
        request(
            b"POST", OBJECT_PATH + b"?uploads", b"Host: local\r\n continuation\r\n"
        ),
        request(
            b"POST",
            OBJECT_PATH + b"?uploads",
            b"Host: local\r\nAuthorization: a\r\nauthorization: b\r\n",
        ),
        request(
            b"POST",
            OBJECT_PATH + b"?uploads",
            b"Host: local\r\nX-Pad: " + b"x" * 65536 + b"\r\n",
        ),
        request(
            b"POST",
            OBJECT_PATH + b"?uploads",
            b"Host: local\r\nX-Field: bad\nvalue\r\n",
        ),
    ],
    ids=[
        "incomplete",
        "absolute-target",
        "missing-host",
        "duplicate-host",
        "control-header",
        "folded-header",
        "duplicate-authorization",
        "over-65536-bytes",
        "bare-lf-header",
    ],
)
def test_malformed_headers_never_match(header):
    from tests.support.asset_faults import MatchResult, match_s3_request

    assert match_s3_request(header, selector("CREATE_MULTIPART")) is MatchResult.INVALID


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("CREATE_MULTIPART", {"locator": None}),
        ("CREATE_MULTIPART", {"upload_id": "u"}),
        ("DELETE_OBJECT", {"limit": 1}),
        ("COMPLETE_MULTIPART", {"upload_id": "u", "part_number": 1}),
        ("COMPLETE_MULTIPART", {"upload_id": ""}),
        ("UPLOAD_PART", {"upload_id": "u", "part_number": True}),
        ("UPLOAD_PART", {"upload_id": "u", "part_number": "1"}),
        ("UPLOAD_PART", {"upload_id": "u", "part_number": 0}),
        ("UPLOAD_PART", {"upload_id": "u", "part_number": 10001}),
        ("UPLOAD_PART", {"upload_id": "u\n", "part_number": 1}),
        ("LIST_OBJECTS", {"limit": True}),
        ("LIST_OBJECTS", {"limit": 0}),
        ("LIST_MULTIPART", {"limit": 101}),
        ("LIST_MULTIPART", {"limit": 1, "upload_id": "u"}),
        ("LIST_OBJECTS", {"limit": 1, "cursor": "opaque"}),
    ],
)
def test_invalid_selector_fails_before_request_matching(operation, fields):
    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        selector(operation, **fields)


def test_namespace_and_locator_cannot_select_foreign_installation():
    from wso_core.storage import InstallationNamespace, ObjectLocator

    from tests.support.asset_faults import (
        FixtureContractError,
        S3FaultSelector,
        S3Operation,
    )

    for namespace, locator in (
        (
            InstallationNamespace(UUID(int=1), "fixture-bucket"),
            ObjectLocator(UUID(int=8), UUID(int=2), UUID(int=3), UUID(int=4)),
        ),
        (
            InstallationNamespace(UUID(int=0), "fixture-bucket"),
            ObjectLocator(UUID(int=0), UUID(int=2), UUID(int=3), UUID(int=4)),
        ),
    ):
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            S3FaultSelector(S3Operation.DELETE_OBJECT, namespace, locator)


@pytest.mark.parametrize("value", ["", "a\r", "a\x7f", "x" * 8193, "é" * 4097, 1])
def test_cursor_rejects_empty_control_and_utf8_overflow(value):
    from tests.support.asset_faults import FixtureContractError, ObjectPageCursor

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        ObjectPageCursor(value)


def test_wrong_cursor_kind_and_nonbyte_header_fail_strictly():
    from tests.support.asset_faults import (
        FixtureContractError,
        MultipartPageCursor,
        match_s3_request,
    )

    with pytest.raises(FixtureContractError):
        selector("LIST_OBJECTS", limit=1, cursor=MultipartPageCursor("key", "upload"))
    with pytest.raises(FixtureContractError):
        match_s3_request("POST / HTTP/1.1\r\n\r\n", selector("CREATE_MULTIPART"))


OWNED_LIST_PREFIX = (
    b"wso-assets%2Fv1%2F00000000000000000000000000000001%2Fobjects%2F"
    b"00000000000000000000000000000002%2F00000000000000000000000000000003%2F"
    b"00000000000000000000000000000004.wso"
)


def owned_list_locator():
    from wso_core.storage import ObjectLocator

    return ObjectLocator(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4))


def test_owned_list_objects_locator_matches_exact_object_prefix():
    from tests.support.asset_faults import MatchResult, match_s3_request

    selected = selector("LIST_OBJECTS", locator=owned_list_locator(), limit=100)
    header = request(
        b"GET",
        b"/fixture-bucket?list-type=2&max-keys=100&prefix="
        + OWNED_LIST_PREFIX
        + b"&encoding-type=url",
    )
    assert match_s3_request(header, selected) is MatchResult.MATCH


def test_owned_list_multipart_locator_matches_exact_object_prefix():
    from tests.support.asset_faults import MatchResult, match_s3_request

    selected = selector("LIST_MULTIPART", locator=owned_list_locator(), limit=100)
    header = request(
        b"GET",
        b"/fixture-bucket?uploads&max-uploads=100&prefix="
        + OWNED_LIST_PREFIX
        + b"&encoding-type=url",
    )
    assert match_s3_request(header, selected) is MatchResult.MATCH


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize(
    "prefix",
    [
        b"wso-assets%2Fv1%2F00000000000000000000000000000001%2F",
        (
            b"wso-assets%2Fv1%2F00000000000000000000000000000001%2Fobjects%2F"
            b"00000000000000000000000000000002%2F00000000000000000000000000000009%2F"
            b"00000000000000000000000000000004.wso"
        ),
        (
            b"wso-assets%2Fv1%2F00000000000000000000000000000001%2Fobjects%2F"
            b"00000000000000000000000000000002%2F00000000000000000000000000000003%2F"
            b"00000000000000000000000000000009.wso"
        ),
        (
            b"wso-assets%2Fv1%2F00000000000000000000000000000001%2Fobjects%2F"
            b"00000000000000000000000000000002%2F00000000000000000000000000000003%2F"
        ),
        (
            b"wso-assets%2Fv1%2F00000000000000000000000000000001%2Fobjects%2F"
            b"00000000000000000000000000000002%2F00000000000000000000000000000003%2F"
            b"00000000000000000000000000000004.wso-sibling"
        ),
    ],
)
def test_owned_list_locator_never_matches_installation_ancestor_or_sibling(
    operation, prefix
):
    from tests.support.asset_faults import MatchResult, match_s3_request

    grammar = (
        b"/fixture-bucket?list-type=2&max-keys=100&prefix="
        if operation == "LIST_OBJECTS"
        else b"/fixture-bucket?uploads&max-uploads=100&prefix="
    )
    selected = selector(operation, locator=owned_list_locator(), limit=100)
    assert (
        match_s3_request(request(b"GET", grammar + prefix), selected)
        is MatchResult.UNMATCHED
    )


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize(
    "suffix,want",
    [
        (b"", "MATCH"),
        (b"&encoding-type=url", "MATCH"),
        (b"&encoding-type=URL", "INVALID"),
        (b"&encoding-type=url&encoding-type=url", "INVALID"),
        (b"&prefix=other", "INVALID"),
        (b"&raw-prefix=other", "INVALID"),
    ],
)
def test_owned_list_locator_retains_r20_and_unique_known_query_fields(
    operation, suffix, want
):
    from tests.support.asset_faults import MatchResult, match_s3_request

    grammar = (
        b"/fixture-bucket?list-type=2&max-keys=100&prefix="
        if operation == "LIST_OBJECTS"
        else b"/fixture-bucket?uploads&max-uploads=100&prefix="
    )
    selected = selector(operation, locator=owned_list_locator(), limit=100)
    assert match_s3_request(
        request(b"GET", grammar + OWNED_LIST_PREFIX + suffix), selected
    ) is MatchResult(want)


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
def test_owned_list_locator_retains_exact_limit_and_native_cursor(operation):
    from tests.support.asset_faults import (
        MatchResult,
        MultipartPageCursor,
        ObjectPageCursor,
        match_s3_request,
    )

    if operation == "LIST_OBJECTS":
        cursor = ObjectPageCursor("c+/=%2F")
        grammar = b"/fixture-bucket?list-type=2&max-keys=100&prefix="
        markers = b"&continuation-token=c%2B%2F%3D%252F"
        missing = b""
    else:
        cursor = MultipartPageCursor(
            "wso-assets/v1/00000000000000000000000000000001/objects/"
            "00000000000000000000000000000002/00000000000000000000000000000003/"
            "00000000000000000000000000000004.wso",
            "u+/=",
        )
        grammar = b"/fixture-bucket?uploads&max-uploads=100&prefix="
        markers = b"&key-marker=" + OWNED_LIST_PREFIX + b"&upload-id-marker=u%2B%2F%3D"
        missing = b""
    selected = selector(
        operation, locator=owned_list_locator(), limit=100, cursor=cursor
    )
    exact = grammar + OWNED_LIST_PREFIX + markers
    assert match_s3_request(request(b"GET", exact), selected) is MatchResult.MATCH
    for other in (
        exact.replace(b"=100", b"=99", 1),
        grammar + OWNED_LIST_PREFIX + missing,
        exact.replace(b"%2B", b"%2D"),
    ):
        assert (
            match_s3_request(request(b"GET", other), selected) is MatchResult.UNMATCHED
        )


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize(
    "parts",
    [(8, 2, 3, 4), (0, 2, 3, 4), (1, 0, 3, 4), (1, 2, 0, 4), (1, 2, 3, 0)],
)
def test_owned_list_locator_refuses_foreign_or_nil_uuid_fields(operation, parts):
    from wso_core.storage import ObjectLocator

    from tests.support.asset_faults import FixtureContractError

    locator = ObjectLocator(*(UUID(int=value) for value in parts))
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        selector(operation, locator=locator, limit=100)


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize("locator", ["arbitrary/raw/prefix", {"object_key": "raw"}, 1])
def test_owned_list_locator_refuses_raw_prefix_and_malformed_locator(
    operation, locator
):
    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        selector(operation, locator=locator, limit=100)


@pytest.mark.parametrize("operation", ["LIST_OBJECTS", "LIST_MULTIPART"])
@pytest.mark.parametrize("limit", [True, "100", 0, 101])
def test_owned_list_locator_does_not_bypass_native_limit_bounds(operation, limit):
    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        selector(operation, locator=owned_list_locator(), limit=limit)


def test_normal_upload_part_under_create_selector_is_unmatched():
    from tests.support.asset_faults import MatchResult, match_s3_request

    selected = selector("CREATE_MULTIPART")
    normal_part = request(b"PUT", OBJECT_PATH + b"?uploadId=real-upload&partNumber=1")
    assert match_s3_request(normal_part, selected) is MatchResult.UNMATCHED


@pytest.mark.parametrize(
    "selected,fields,method,target",
    [
        (
            "CREATE_MULTIPART",
            {},
            b"GET",
            OBJECT_PATH + b"?uploadId=real-upload",
        ),
        (
            "COMPLETE_MULTIPART",
            {"upload_id": "real-upload"},
            b"PUT",
            OBJECT_PATH + b"?uploadId=real-upload&partNumber=2",
        ),
        (
            "COMPLETE_MULTIPART",
            {"upload_id": "real-upload"},
            b"GET",
            OBJECT_PATH + b"?uploadId=real-upload",
        ),
        (
            "DELETE_OBJECT",
            {},
            b"GET",
            (
                b"/fixture-bucket?list-type=2&max-keys=100&encoding-type=url&prefix="
                b"wso-assets%2Fv1%2F00000000000000000000000000000001%2F"
            ),
        ),
        (
            "UPLOAD_PART",
            {"upload_id": "real-upload", "part_number": 1},
            b"POST",
            OBJECT_PATH + b"?uploads",
        ),
        (
            "LIST_OBJECTS",
            {"limit": 100},
            b"POST",
            OBJECT_PATH + b"?uploadId=real-upload",
        ),
        ("LIST_MULTIPART", {"limit": 100}, b"DELETE", OBJECT_PATH),
        ("CREATE_MULTIPART", {}, b"GET", OBJECT_PATH),
        ("CREATE_MULTIPART", {}, b"HEAD", OBJECT_PATH),
    ],
    ids=[
        "parts-before-create",
        "part-before-complete",
        "parts-before-complete",
        "list-before-delete",
        "create-before-part",
        "complete-before-list",
        "delete-before-multipart-list",
        "get-before-create",
        "head-before-create",
    ],
)
def test_valid_nonselected_s3_grammar_is_forwardable_not_invalid(
    selected, fields, method, target
):
    from tests.support.asset_faults import MatchResult, match_s3_request

    assert (
        match_s3_request(request(method, target), selector(selected, **fields))
        is MatchResult.UNMATCHED
    )


def test_owned_snapshots_publish_repeated_complete_json(tmp_path):
    import json

    from tests.support.asset_faults import OwnedSnapshots

    with OwnedSnapshots(tmp_path, "synthetic-owner") as snapshots:
        snapshots.write("send.json", {"phase": "begin", "count": 0})
        assert json.loads((tmp_path / "send.json").read_text()) == {
            "phase": "begin",
            "count": 0,
        }
        snapshots.write("send.json", {"phase": "end", "count": 11})
        assert json.loads((tmp_path / "send.json").read_text()) == {
            "phase": "end",
            "count": 11,
        }


def test_fault_admission_consumes_one_match_and_attributes_its_counters():
    from tests.support.asset_faults import FaultAdmission, FaultMode, MatchResult

    admission = FaultAdmission()
    admission.arm(FaultMode.RESET_BEFORE_FORWARD)
    before = admission.admit(MatchResult.UNMATCHED)
    assert (before.generation, before.request, before.matched, before.mode) == (
        1,
        1,
        False,
        FaultMode.PASS,
    )
    admission.record(before, forwarded=11, returned=7, dispatches=1)
    admission.finish(before)
    selected = admission.admit(MatchResult.MATCH)
    assert (selected.generation, selected.request, selected.matched, selected.mode) == (
        1,
        2,
        True,
        FaultMode.RESET_BEFORE_FORWARD,
    )
    admission.finish(selected)
    after = admission.admit(MatchResult.MATCH)
    assert (after.generation, after.request, after.matched, after.mode) == (
        1,
        3,
        False,
        FaultMode.PASS,
    )
    admission.record(after, forwarded=5, returned=3, dispatches=1)
    admission.finish(after)
    facts = admission.snapshot()
    assert facts["armed"] is False
    assert (
        facts["consumed"],
        facts["matched"],
        facts["forwarded"],
        facts["returned"],
        facts["dispatches"],
        facts["total_forwarded"],
        facts["total_returned"],
        facts["total_dispatches"],
    ) == (True, True, 0, 0, 0, 16, 10, 2)


@pytest.mark.parametrize(
    "name",
    [
        "../outside.json",
        "nested/send.json",
        "nested\\send.json",
        ".snapshot-owner",
        ".",
        "..",
        "",
        "é.json",
        "x" * 129,
    ],
    ids=[
        "parent",
        "slash",
        "backslash",
        "reserved",
        "dot",
        "double-dot",
        "empty",
        "non-ascii",
        "long",
    ],
)
def test_snapshot_invalid_basename_preserves_published_value(tmp_path, name):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    with OwnedSnapshots(tmp_path, "synthetic-owner") as snapshots:
        snapshots.write("send.json", {"version": 1})
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            snapshots.write(name, {"version": 2})
        assert json.loads((tmp_path / "send.json").read_text()) == {"version": 1}


@pytest.mark.parametrize(
    "kind",
    [
        "bytes",
        "non-string-key",
        "nan",
        "inf",
        "int-subclass",
        "dict-subclass",
        "depth",
        "size",
    ],
)
def test_snapshot_native_json_type_depth_and_size_refusal_preserves_old_json(
    tmp_path, kind
):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    class IntSubclass(int):
        pass

    class DictSubclass(dict):
        pass

    values = {
        "bytes": b"unsupported",
        "non-string-key": {1: "unsupported"},
        "nan": float("nan"),
        "inf": float("inf"),
        "int-subclass": IntSubclass(1),
        "dict-subclass": DictSubclass(value=1),
        "size": "x" * 1048576,
    }
    deep = None
    for _ in range(33):
        deep = [deep]
    value = deep if kind == "depth" else values[kind]
    with OwnedSnapshots(tmp_path, "synthetic-owner") as snapshots:
        snapshots.write("send.json", {"version": 1})
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            snapshots.write("send.json", value)
        assert json.loads((tmp_path / "send.json").read_text()) == {"version": 1}


def test_snapshot_native_tree_roundtrip_close_and_same_owner_registration(tmp_path):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    first = OwnedSnapshots(tmp_path, "synthetic-owner")
    first.write("state.json", {"items": [None, True, False, 7, 1.25, "é"]})
    second = OwnedSnapshots(tmp_path, "synthetic-owner")
    try:
        second.write("state.json", {"items": [None, False, 8, 2.5, "complete"]})
        assert json.loads((tmp_path / "state.json").read_text()) == {
            "items": [None, False, 8, 2.5, "complete"]
        }
    finally:
        second.close()
        first.close()
    first.close()
    with pytest.raises(FixtureContractError):
        first.write("state.json", {"items": []})


@pytest.mark.parametrize("owner", ["", True, "owner\n", "é", "x" * 129])
def test_snapshot_owner_native_validation_and_mismatch_never_overwrite(tmp_path, owner):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    with OwnedSnapshots(tmp_path, "synthetic-owner") as snapshots:
        snapshots.write("state.json", {"owner": "original"})
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            OwnedSnapshots(tmp_path, owner)
        with pytest.raises(FixtureContractError):
            OwnedSnapshots(tmp_path, "other-owner")
        assert json.loads((tmp_path / "state.json").read_text()) == {
            "owner": "original"
        }


def test_snapshot_invalid_directory_type_parent_and_marker_refuse(tmp_path):
    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    for directory in (str(tmp_path), tmp_path / ".." / tmp_path.name):
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            OwnedSnapshots(directory, "synthetic-owner")
    snapshots = OwnedSnapshots(tmp_path, "synthetic-owner")
    snapshots.close()
    (tmp_path / ".snapshot-owner").write_bytes(b"invalid owner marker")
    with pytest.raises(FixtureContractError):
        OwnedSnapshots(tmp_path, "synthetic-owner")


def test_snapshot_link_or_nonregular_target_never_modifies_outside_value(tmp_path):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    outside.write_text('{"value":"outside-original"}')
    target = root / "link.json"
    try:
        target.symlink_to(outside)
    except OSError:
        # Native Windows symlinks may require privilege. This fallback exercises
        # the exact regular-destination contract, not POSIX no-follow security.
        target.mkdir()
    with (
        OwnedSnapshots(root, "synthetic-owner") as snapshots,
        pytest.raises(FixtureContractError),
    ):
        snapshots.write("link.json", {"value": "changed"})
    assert json.loads(outside.read_text()) == {"value": "outside-original"}


def test_snapshot_replaced_directory_refusal_or_os_pin_preserves_original(tmp_path):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    snapshots = OwnedSnapshots(root, "synthetic-owner")
    snapshots.write("state.json", {"version": 1})
    moved = tmp_path / "retained-owned"
    try:
        try:
            root.rename(moved)
        except PermissionError:
            # Windows may prevent the rename while a retained handle is open.
            assert json.loads((root / "state.json").read_text()) == {"version": 1}
            return
        root.mkdir(mode=0o700)
        with pytest.raises(FixtureContractError):
            snapshots.write("state.json", {"version": 2})
        assert json.loads((moved / "state.json").read_text()) == {"version": 1}
        assert list(root.iterdir()) == []
    finally:
        snapshots.close()


def test_snapshot_replace_failure_preserves_first_error_cleans_temp_and_poisons(
    tmp_path, monkeypatch
):
    import json

    import tests.support.asset_faults as faults

    snapshots = faults.OwnedSnapshots(tmp_path, "synthetic-owner")
    snapshots.write("state.json", {"version": 1})

    def denied(*args, **kwargs):
        raise PermissionError("synthetic-private-poison")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(faults.os, "replace", denied)
            with pytest.raises(faults.FixtureContractError) as failure:
                snapshots.write("state.json", {"version": 2})
        assert str(failure.value) == "invalid fixture contract"
        assert "synthetic-private-poison" not in repr(failure.value)
        assert json.loads((tmp_path / "state.json").read_text()) == {"version": 1}
        assert {path.name for path in tmp_path.iterdir()} == {
            ".snapshot-owner",
            "state.json",
        }
        with pytest.raises(faults.FixtureContractError):
            snapshots.write("state.json", {"version": 3})
    finally:
        snapshots.close()


def test_snapshot_concurrent_reads_are_whole_correlated_publications(
    tmp_path, monkeypatch
):
    import errno
    import json
    import os
    import threading

    import tests.support.asset_faults as faults

    snapshots = faults.OwnedSnapshots(tmp_path, "synthetic-owner")
    snapshots.write("state.json", {"serial": 0, "mirror": [0] * 64})
    ready, done = threading.Event(), threading.Event()
    observed, errors, denied, denied_reads = [], [], [], []
    last_successful_publication = 0
    real_replace = faults.os.replace

    def tracked_replace(*args, **kwargs):
        try:
            return real_replace(*args, **kwargs)
        except PermissionError:
            denied.append(True)
            raise

    def read():
        try:
            while not done.is_set():
                try:
                    raw = (tmp_path / "state.json").read_text()
                except PermissionError as error:
                    if os.name != "nt" or error.errno != errno.EACCES:
                        raise
                    denied_reads.append(
                        {
                            "errno": error.errno,
                            "winerror": getattr(error, "winerror", None),
                        }
                    )
                    ready.set()
                    break
                value = json.loads(raw)
                if (
                    set(value) != {"serial", "mirror"}
                    or value["mirror"] != [value["serial"]] * 64
                ):
                    raise AssertionError("partial or uncorrelated snapshot")
                observed.append(value["serial"])
                ready.set()
        except BaseException as error:  # noqa: BLE001 -- surface owned reader failures in main-thread assertions.
            errors.append(error)
            ready.set()

    reader = threading.Thread(target=read, name="owned-snapshot-unit-reader")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(faults.os, "replace", tracked_replace)
            reader.start()
            assert ready.wait(2)
            publication_failure = None
            for serial in range(1, 17):
                try:
                    snapshots.write(
                        "state.json", {"serial": serial, "mirror": [serial] * 64}
                    )
                    last_successful_publication = serial
                except faults.FixtureContractError as error:
                    publication_failure = error
                    break
            if publication_failure is not None:
                assert os.name == "nt" and denied
                assert str(publication_failure) == "invalid fixture contract"
                with pytest.raises(faults.FixtureContractError):
                    snapshots.write("state.json", {"serial": 99, "mirror": [99] * 64})
            else:
                assert last_successful_publication == 16
    finally:
        done.set()
        if reader.ident is not None:
            reader.join(3)
        snapshots.close()
    assert not reader.is_alive()
    assert observed and not errors
    assert len(denied_reads) <= 1
    assert not denied_reads or (
        os.name == "nt" and denied_reads[0]["errno"] == errno.EACCES
    )
    assert json.loads((tmp_path / "state.json").read_text()) == {
        "serial": last_successful_publication,
        "mirror": [last_successful_publication] * 64,
    }


def test_admission_initial_unarmed_pass_and_rearm_preserve_only_totals():
    from tests.support.asset_faults import FaultAdmission, FaultMode, MatchResult

    admission = FaultAdmission()
    assert admission.snapshot() == {
        "armed": False,
        "consumed": False,
        "matched": False,
        "forwarded": 0,
        "returned": 0,
        "dispatches": 0,
        "total_forwarded": 0,
        "total_returned": 0,
        "total_dispatches": 0,
    }
    unarmed = admission.admit(MatchResult.MATCH)
    assert (unarmed.generation, unarmed.request, unarmed.matched, unarmed.mode) == (
        0,
        1,
        False,
        FaultMode.PASS,
    )
    admission.record(unarmed, forwarded=3, returned=2, dispatches=1)
    admission.finish(unarmed)
    admission.arm(FaultMode.PASS)
    assert admission.snapshot() == {
        "armed": True,
        "consumed": False,
        "matched": False,
        "forwarded": 0,
        "returned": 0,
        "dispatches": 0,
        "total_forwarded": 3,
        "total_returned": 2,
        "total_dispatches": 1,
    }
    selected = admission.admit(MatchResult.MATCH)
    assert (selected.generation, selected.request, selected.matched, selected.mode) == (
        1,
        2,
        True,
        FaultMode.PASS,
    )
    admission.record(selected, forwarded=11, returned=7, dispatches=1)
    admission.finish(selected)
    retained = {
        "armed": False,
        "consumed": True,
        "matched": True,
        "forwarded": 11,
        "returned": 7,
        "dispatches": 1,
        "total_forwarded": 14,
        "total_returned": 9,
        "total_dispatches": 2,
    }
    assert admission.snapshot() == retained
    later = admission.admit(MatchResult.MATCH)
    assert not later.matched and later.mode is FaultMode.PASS
    admission.record(later, forwarded=5, returned=3, dispatches=1)
    admission.finish(later)
    assert admission.snapshot() == {
        **retained,
        "total_forwarded": 19,
        "total_returned": 12,
        "total_dispatches": 3,
    }
    admission.arm(FaultMode.HOLD_REQUEST)
    assert admission.snapshot() == {
        "armed": True,
        "consumed": False,
        "matched": False,
        "forwarded": 0,
        "returned": 0,
        "dispatches": 0,
        "total_forwarded": 19,
        "total_returned": 12,
        "total_dispatches": 3,
    }
    next_selected = admission.admit(MatchResult.MATCH)
    assert next_selected.generation == 2 and next_selected.request == 4
    assert next_selected.mode is FaultMode.HOLD_REQUEST and next_selected.matched
    admission.finish(next_selected)


def test_admission_forged_unknown_finished_and_stale_tokens_refuse_mutation():
    from dataclasses import replace

    from tests.support.asset_faults import (
        FaultAdmission,
        FaultMode,
        FaultRequestToken,
        FixtureContractError,
        MatchResult,
    )

    admission = FaultAdmission()
    admission.arm(FaultMode.PASS)
    token = admission.admit(MatchResult.MATCH)
    baseline = admission.snapshot()
    for invalid in (
        replace(token),
        FaultRequestToken(1, 999, True, FaultMode.PASS),
        None,
    ):
        for method in (admission.record, admission.finish):
            with pytest.raises(
                FixtureContractError, match="^invalid fixture contract$"
            ):
                method(invalid)
            assert admission.snapshot() == baseline
    with pytest.raises(FixtureContractError):
        admission.arm(FaultMode.HOLD_RESPONSE)
    assert admission.snapshot() == baseline
    admission.record(token, forwarded=4, returned=2, dispatches=1)
    admission.finish(token)
    finished = admission.snapshot()
    for method in (admission.record, admission.finish):
        with pytest.raises(FixtureContractError):
            method(token)
        assert admission.snapshot() == finished
    admission.arm(FaultMode.RESET_BEFORE_FORWARD)
    rearmed = admission.snapshot()
    for method in (admission.record, admission.finish):
        with pytest.raises(FixtureContractError):
            method(token)
        assert admission.snapshot() == rearmed


@pytest.mark.parametrize(
    "field,value",
    [
        ("forwarded", True),
        ("returned", -1),
        ("forwarded", 1.0),
        ("returned", "2"),
        ("dispatches", True),
        ("dispatches", 2),
    ],
)
def test_admission_native_increment_validation_does_not_poison_token(field, value):
    from tests.support.asset_faults import (
        FaultAdmission,
        FaultMode,
        FixtureContractError,
        MatchResult,
    )

    admission = FaultAdmission()
    admission.arm(FaultMode.PASS)
    token = admission.admit(MatchResult.MATCH)
    baseline = admission.snapshot()
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        admission.record(token, **{field: value})
    assert admission.snapshot() == baseline
    admission.record(token, forwarded=2, returned=1, dispatches=1)
    admission.finish(token)
    assert admission.snapshot()["forwarded"] == 2
    assert admission.snapshot()["total_returned"] == 1


def test_admission_invalid_enum_or_result_cannot_consume_available_arm():
    from tests.support.asset_faults import (
        FaultAdmission,
        FaultMode,
        FixtureContractError,
        MatchResult,
    )

    admission = FaultAdmission()
    for mode in ("PASS", True, None):
        with pytest.raises(FixtureContractError):
            admission.arm(mode)
    admission.arm(FaultMode.RESET_BEFORE_FORWARD)
    baseline = admission.snapshot()
    for result in (MatchResult.INVALID, "MATCH", True, None):
        with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
            admission.admit(result)
        assert admission.snapshot() == baseline
    token = admission.admit(MatchResult.MATCH)
    assert token.mode is FaultMode.RESET_BEFORE_FORWARD and token.matched
    assert admission.snapshot()["armed"] is False
    admission.finish(token)


def test_concurrent_matching_admissions_consume_exactly_once():
    import threading

    from tests.support.asset_faults import FaultAdmission, FaultMode, MatchResult

    admission = FaultAdmission()
    admission.arm(FaultMode.HOLD_RESPONSE)
    barrier = threading.Barrier(9, timeout=3)
    tokens, errors = [], []

    def admit():
        try:
            barrier.wait()
            token = admission.admit(MatchResult.MATCH)
            tokens.append(token)
            admission.record(token, forwarded=2, returned=1, dispatches=1)
            admission.finish(token)
        except BaseException as error:  # noqa: BLE001 -- surface owned admission worker failures in main-thread assertions.
            errors.append(error)

    threads = [
        threading.Thread(target=admit, name=f"unit-admission-{index}")
        for index in range(8)
    ]
    try:
        for thread in threads:
            thread.start()
        barrier.wait()
    finally:
        for thread in threads:
            if thread.ident is not None:
                thread.join(4)
    assert not errors and all(not thread.is_alive() for thread in threads)
    assert len(tokens) == 8 and len({token.request for token in tokens}) == 8
    assert sorted(token.request for token in tokens) == list(range(1, 9))
    assert sum(token.matched for token in tokens) == 1
    assert sum(token.mode is FaultMode.HOLD_RESPONSE for token in tokens) == 1
    assert sum(token.mode is FaultMode.PASS for token in tokens) == 7
    assert admission.snapshot() == {
        "armed": False,
        "consumed": True,
        "matched": True,
        "forwarded": 2,
        "returned": 1,
        "dispatches": 1,
        "total_forwarded": 16,
        "total_returned": 8,
        "total_dispatches": 8,
    }


@pytest.mark.parametrize(
    "flow",
    ["complete", "delete"],
    ids=["multipart-before-complete", "list-before-delete"],
)
def test_real_loopback_relay_preserves_unmatched_bytes_and_consumes_reset_once(flow):
    import errno
    import os
    import socket
    import sys
    import threading
    import time
    from urllib.parse import urlsplit

    from tests.support.asset_faults import FaultMode, FaultRelay

    response = (
        b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nopaque"
    )
    body = b"\x00\xffopaque\r\n\x80"
    headers = b"Host: 127.0.0.1:9000\r\nAuthorization: Synthetic exact-opaque\r\n"
    if flow == "complete":
        initial = [
            request(
                b"POST", OBJECT_PATH + b"?uploads", headers + b"Content-Length: 0\r\n"
            ),
            request(
                b"PUT",
                OBJECT_PATH + b"?uploadId=real-upload&partNumber=1",
                headers + b"Content-Length: 11\r\n",
            )
            + body,
            request(b"GET", OBJECT_PATH + b"?uploadId=real-upload", headers),
        ]
        selected = selector("COMPLETE_MULTIPART", upload_id="real-upload")
        selected_bytes = request(
            b"POST",
            OBJECT_PATH + b"?uploadId=real-upload",
            headers + b"Content-Length: 0\r\n",
        )
    else:
        initial = [
            request(
                b"GET",
                b"/fixture-bucket?list-type=2&max-keys=100&prefix=wso-assets%2Fv1%2F00000000000000000000000000000001%2F&encoding-type=url",
                headers,
            )
        ]
        selected = selector("DELETE_OBJECT")
        selected_bytes = request(b"DELETE", OBJECT_PATH, headers)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.1)
    target = listener.getsockname()
    cutoff = time.monotonic() + 15.0
    stop = threading.Event()
    received, errors, verified, shutdown_resets = [], [], [], []

    def serve():
        try:
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if stop.is_set():
                        return
                    raise
                with connection:
                    connection.settimeout(3)
                    chunks = []
                    while True:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    received.append(b"".join(chunks))
                    connection.sendall(response)
                    connection.shutdown(socket.SHUT_WR)
        except BaseException as error:  # noqa: BLE001 -- surface owned backend failures in main-thread assertions.
            errors.append(error)

    def verify(deadline):
        assert listener.fileno() >= 0 and listener.getsockname() == target
        assert type(deadline) is float and time.monotonic() < deadline <= cutoff
        verified.append(deadline)

    backend_thread = threading.Thread(target=serve, name="unit-owned-loopback-backend")
    relay = FaultRelay(
        f"http://127.0.0.1:{target[1]}", "synthetic-owner", verify, cutoff
    )

    def exchange(value, *, reset=False):
        endpoint = urlsplit(relay.endpoint)
        with socket.create_connection(
            ("127.0.0.1", endpoint.port), timeout=3
        ) as client:
            client.sendall(value)
            chunks = []
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError as error:
                if not (
                    reset
                    and (
                        (
                            os.name == "nt"
                            and isinstance(error, ConnectionResetError)
                            and getattr(error, "winerror", None) == 10054
                        )
                        or (
                            sys.platform.startswith("linux")
                            and error.errno == errno.ENOTCONN
                        )
                    )
                ):
                    raise
                shutdown_resets.append(
                    {
                        "boundary": "shutdown(SHUT_WR)",
                        "platform": sys.platform,
                        "errno": error.errno,
                        "winerror": getattr(error, "winerror", None),
                    }
                )
                client.close()
            else:
                while True:
                    try:
                        chunk = client.recv(4096)
                    except ConnectionResetError:
                        assert reset
                        break
                    if not chunk:
                        break
                    chunks.append(chunk)
        assert b"".join(chunks) == (b"" if reset else response)
        end = min(cutoff, time.monotonic() + 3)
        while relay.snapshot()["active"] and time.monotonic() < end:
            stop.wait(0.005)
        assert not relay.snapshot()["active"] and not relay.snapshot()["failed"]

    try:
        backend_thread.start()
        with relay:
            relay.arm(selected, FaultMode.RESET_BEFORE_FORWARD)
            for value in initial:
                exchange(value)
            assert received == initial
            exchange(selected_bytes, reset=True)
            relay.wait_match(cutoff)
            facts = relay.snapshot()
            assert (
                facts["matched"],
                facts["forwarded"],
                facts["returned"],
                facts["dispatches"],
            ) == (True, 0, 0, 0)
            assert (
                facts["total_forwarded"],
                facts["total_returned"],
                facts["total_dispatches"],
            ) == (sum(map(len, initial)), len(response) * len(initial), len(initial))
            assert received == initial
            exchange(selected_bytes)
            assert received == initial + [selected_bytes]
            final = relay.snapshot()
            assert (final["forwarded"], final["returned"], final["dispatches"]) == (
                0,
                0,
                0,
            )
            assert (
                final["total_forwarded"],
                final["total_returned"],
                final["total_dispatches"],
            ) == (
                sum(map(len, initial)) + len(selected_bytes),
                len(response) * (len(initial) + 1),
                len(initial) + 1,
            )
            assert len(verified) == len(initial) + 2
    finally:
        stop.set()
        listener.close()
        if backend_thread.ident is not None:
            backend_thread.join(4)
    assert not backend_thread.is_alive() and not errors
    assert len(shutdown_resets) <= 1
    settled = relay.snapshot()
    assert settled["sockets"] == 0 and settled["threads"] == 0


def _owned_payload_failure_boundary(
    directory, monkeypatch, *, write_mode="error", deny_close=False, deny_unlink=False
):
    """Observe only real newly opened payload resources, never private custody."""
    import errno
    import os
    from contextlib import contextmanager
    from pathlib import Path

    import tests.support.asset_faults as faults

    @contextmanager
    def track():
        real_open, real_write, real_close = (
            faults.os.open,
            faults.os.write,
            faults.os.close,
        )
        real_unlink = Path.unlink
        root_identity = (directory.stat().st_dev, directory.stat().st_ino)
        resources, closes, unlinks = [], [], []
        write_calls = 0

        def belongs(path, flags, kwargs):
            candidate = Path(os.fsdecode(path))
            if not candidate.name.startswith(".snapshot-") or not flags & os.O_EXCL:
                return False
            if candidate.is_absolute():
                return candidate.parent == directory
            if len(candidate.parts) != 1 or kwargs.get("dir_fd") is None:
                return False
            row = os.fstat(kwargs["dir_fd"])
            return (row.st_dev, row.st_ino) == root_identity

        def opened(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if belongs(path, flags, kwargs):
                row = os.fstat(descriptor)
                resources.append(
                    {
                        "fd": descriptor,
                        "path": directory / Path(os.fsdecode(path)).name,
                        "identity": (row.st_dev, row.st_ino),
                    }
                )
            return descriptor

        def owned_descriptor(descriptor):
            for resource in resources:
                if descriptor != resource["fd"]:
                    continue
                row = os.fstat(descriptor)
                if (row.st_dev, row.st_ino) == resource["identity"]:
                    return True
            return False

        def written(descriptor, data):
            nonlocal write_calls
            if not owned_descriptor(descriptor):
                return real_write(descriptor, data)
            write_calls += 1
            if write_mode == "zero":
                return 0
            if write_mode == "partial" and write_calls == 1:
                return real_write(descriptor, data[:1])
            if write_mode in {"error", "partial"}:
                raise OSError(errno.EIO, "synthetic-private-write-failure")
            return real_write(descriptor, data)

        def closed(descriptor):
            if owned_descriptor(descriptor):
                closes.append(descriptor)
                if deny_close:
                    raise OSError(errno.EBUSY, "synthetic-private-close-failure")
            return real_close(descriptor)

        def unlinked(path, *args, **kwargs):
            for resource in resources:
                if path != resource["path"] or not path.exists():
                    continue
                row = path.lstat()
                if (row.st_dev, row.st_ino) == resource["identity"]:
                    unlinks.append(resource["identity"])
                    if deny_unlink:
                        raise PermissionError(
                            errno.EACCES, "synthetic-private-unlink-failure"
                        )
            return real_unlink(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(faults.os, "open", opened)
            patch.setattr(faults.os, "write", written)
            patch.setattr(faults.os, "close", closed)
            patch.setattr(Path, "unlink", unlinked)
            yield {"resources": resources, "closes": closes, "unlinks": unlinks}

    return track()


def _assert_real_payload_resources_settled(probe):
    import errno
    import os

    assert len(probe["resources"]) == 1
    for resource in probe["resources"]:
        with pytest.raises(OSError) as closed:
            os.fstat(resource["fd"])
        assert closed.value.errno == errno.EBADF
        assert not resource["path"].exists()


def _best_effort_owned_snapshot_settlement(writer, probe):
    """Callbacks are already restored; settle only observed exact owned identities."""
    import os

    from tests.support.asset_faults import FixtureContractError

    try:
        writer.close()
    except FixtureContractError:
        # Failed implementation custody must not leave test-owned resources open.
        pass
    if probe is None:
        return
    for resource in probe["resources"]:
        try:
            row = os.fstat(resource["fd"])
        except OSError:
            pass
        else:
            if (row.st_dev, row.st_ino) == resource["identity"]:
                os.close(resource["fd"])
        path = resource["path"]
        if path.exists():
            row = path.lstat()
            assert (row.st_dev, row.st_ino) == resource["identity"]
            path.unlink()


@pytest.mark.parametrize(
    "write_mode", ["error", "zero", "partial"], ids=["error", "zero", "partial"]
)
def test_snapshot_failed_write_immediately_settles_owned_temp(
    tmp_path, monkeypatch, write_mode
):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    writer = OwnedSnapshots(tmp_path, "synthetic-owner")
    writer.write("state.json", {"version": 1})
    probe = None
    try:
        with _owned_payload_failure_boundary(
            tmp_path, monkeypatch, write_mode=write_mode
        ) as probe:
            with pytest.raises(FixtureContractError) as failure:
                writer.write("state.json", {"version": 2})
            assert str(failure.value) == "invalid fixture contract"
            assert "synthetic-private" not in repr(failure.value)
            assert json.loads((tmp_path / "state.json").read_text()) == {"version": 1}
            _assert_real_payload_resources_settled(probe)
            with pytest.raises(FixtureContractError):
                writer.write("state.json", {"version": 3})
        writer.close()
        writer.close()
        _assert_real_payload_resources_settled(probe)
    finally:
        _best_effort_owned_snapshot_settlement(writer, probe)


def test_snapshot_close_refuses_unremoved_owned_temp(tmp_path, monkeypatch):
    import json

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    writer = OwnedSnapshots(tmp_path, "synthetic-owner")
    writer.write("state.json", {"version": 1})
    probe = None
    try:
        with _owned_payload_failure_boundary(
            tmp_path, monkeypatch, deny_unlink=True
        ) as probe:
            with pytest.raises(
                FixtureContractError, match="^invalid fixture contract$"
            ):
                writer.write("state.json", {"version": 2})
            assert len(probe["resources"]) == 1
            retained = probe["resources"][0]
            row = retained["path"].lstat()
            assert (row.st_dev, row.st_ino) == retained["identity"]
            assert json.loads((tmp_path / "state.json").read_text()) == {"version": 1}
            with pytest.raises(
                FixtureContractError, match="^invalid fixture contract$"
            ):
                writer.close()
            with pytest.raises(FixtureContractError):
                writer.write("state.json", {"version": 3})
            with pytest.raises(FixtureContractError):
                writer.close()
            row = retained["path"].lstat()
            assert (row.st_dev, row.st_ino) == retained["identity"]
            assert len(probe["resources"]) == 1
        writer.close()
        _assert_real_payload_resources_settled(probe)
        writer.close()
        assert json.loads((tmp_path / "state.json").read_text()) == {"version": 1}
        with pytest.raises(FixtureContractError):
            writer.write("state.json", {"version": 4})
    finally:
        _best_effort_owned_snapshot_settlement(writer, probe)


@pytest.mark.parametrize(
    "write_mode", ["error", "normal"], ids=["write-and-close", "close-only"]
)
def test_snapshot_refused_payload_close_retains_real_descriptor_and_poison(
    tmp_path, monkeypatch, write_mode
):
    import json
    import os

    from tests.support.asset_faults import FixtureContractError, OwnedSnapshots

    writer = OwnedSnapshots(tmp_path, "synthetic-owner")
    writer.write("state.json", {"version": 1})
    probe = None
    try:
        with _owned_payload_failure_boundary(
            tmp_path, monkeypatch, write_mode=write_mode, deny_close=True
        ) as probe:
            with pytest.raises(FixtureContractError) as failure:
                writer.write("state.json", {"version": 2})
            assert str(failure.value) == "invalid fixture contract"
            assert "synthetic-private" not in repr(failure.value)
            assert len(probe["resources"]) == 1
            retained = probe["resources"][0]
            row = os.fstat(retained["fd"])
            assert (row.st_dev, row.st_ino) == retained["identity"]
            with pytest.raises(FixtureContractError):
                writer.close()
            row = os.fstat(retained["fd"])
            assert (row.st_dev, row.st_ino) == retained["identity"]
            with pytest.raises(FixtureContractError):
                writer.write("state.json", {"version": 3})
            assert json.loads((tmp_path / "state.json").read_text()) == {"version": 1}
        writer.close()
        _assert_real_payload_resources_settled(probe)
        writer.close()
    finally:
        _best_effort_owned_snapshot_settlement(writer, probe)


def identity_barrier(tmp_path, monkeypatch):
    """Keep real control/publications; supply only Linux directory metadata on Windows."""
    import os
    from pathlib import Path

    from tests.support import asset_faults as faults

    tmp_path.chmod(0o700)
    original_stat = Path.stat
    if os.name != "posix":

        def directory_stat(path, *args, **kwargs):
            row = original_stat(path, *args, **kwargs)
            if path == tmp_path:
                fields = list(row)
                fields[0] = (row.st_mode & ~0o777) | 0o700
                return os.stat_result(fields)
            return row

        monkeypatch.setattr(Path, "stat", directory_stat)
        monkeypatch.setattr(
            os, "getuid", lambda: original_stat(tmp_path).st_uid, raising=False
        )
    return faults.BarrierControl(tmp_path, "00000000000000000000000000000001")


def test_armed_callback_publishes_native_identity_and_waits_for_exact_release(
    tmp_path, monkeypatch
):
    import json
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor

    from wso_core.assets import AssetEvent

    from tests.support import asset_faults as faults

    control = identity_barrier(tmp_path, monkeypatch)
    identity = faults.ProcessIdentity(
        control.owner,
        os.getpid(),
        7,
        11,
        11,
        37,
        ("synthetic-python", "synthetic-worker"),
    )
    monkeypatch.setattr(faults, "process_identity", lambda pid, owner: identity)
    cutoff = time.monotonic() + 1.0
    control.arm("VALIDATED_BEFORE_FINALIZE", asset_id=UUID(int=3), cutoff=cutoff)
    with ThreadPoolExecutor(max_workers=1) as executor:
        caller = executor.submit(
            control.callback, AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3))
        )
        try:
            # Surface a producer refusal rather than conceal it behind a wait timeout.
            while not (tmp_path / "reached.json").exists():
                if caller.done():
                    caller.result()
                assert time.monotonic() < cutoff
                time.sleep(0.005)
            record = control.wait(cutoff)
            assert not caller.done()
            assert (record["owner"], record["event"], record["id"]) == (
                control.owner,
                "VALIDATED_BEFORE_FINALIZE",
                str(UUID(int=3)),
            )
            assert record["identity"] == {
                "owner": control.owner,
                "pid": os.getpid(),
                "uid": 7,
                "ppid": 11,
                "pgid": 11,
                "start_ticks": 37,
                "command": ["synthetic-python", "synthetic-worker"],
            }
            assert (
                json.loads((tmp_path / "armed.json").read_bytes())["cutoff"] == cutoff
            )
        finally:
            control.release(
                {
                    "owner": control.owner,
                    "event": "VALIDATED_BEFORE_FINALIZE",
                    "id": str(UUID(int=3)),
                }
            )
        caller.result(timeout=1)
    assert type(identity.command) is tuple


@pytest.mark.parametrize("armed", [None, "other-event", "other-asset"])
def test_callback_unarmed_or_nonmatching_never_looks_up_identity(
    tmp_path, monkeypatch, armed
):
    import json
    import time

    from wso_core.assets import AssetEvent

    from tests.support import asset_faults as faults

    control = identity_barrier(tmp_path, monkeypatch)

    def forbidden_lookup(*args):
        raise AssertionError("nonmatching callback performed process lookup")

    monkeypatch.setattr(faults, "process_identity", forbidden_lookup)
    if armed is not None:
        control.arm(
            "UPLOAD_INTENT_COMMITTED"
            if armed == "other-event"
            else "VALIDATED_BEFORE_FINALIZE",
            asset_id=UUID(int=4) if armed == "other-asset" else UUID(int=3),
            cutoff=time.monotonic() + 1.0,
        )
    control.callback(AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3)))
    assert not (tmp_path / "reached.json").exists()
    assert json.loads((tmp_path / "last-event.json").read_bytes())["id"] == str(
        UUID(int=3)
    )


@pytest.mark.parametrize("identity", [None, {"command": ["synthetic-python"]}])
def test_callback_malformed_identity_refuses_without_reached_record(
    tmp_path, monkeypatch, identity
):
    import time

    from wso_core.assets import AssetEvent

    from tests.support import asset_faults as faults

    control = identity_barrier(tmp_path, monkeypatch)
    monkeypatch.setattr(faults, "process_identity", lambda pid, owner: identity)
    control.arm(
        "VALIDATED_BEFORE_FINALIZE", asset_id=UUID(int=3), cutoff=time.monotonic() + 1.0
    )
    with pytest.raises(faults.FixtureContractError, match="^invalid fixture contract$"):
        control.callback(AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3)))
    assert not (tmp_path / "reached.json").exists()


@pytest.mark.parametrize("release", [None, "owner", "event", "id"])
def test_callback_native_identity_preserves_cutoff_and_release_validation(
    tmp_path, monkeypatch, release
):
    import os
    import time

    from wso_core.assets import AssetEvent

    from tests.support import asset_faults as faults

    control = identity_barrier(tmp_path, monkeypatch)
    identity = faults.ProcessIdentity(
        control.owner, os.getpid(), 7, 11, 11, 37, ("synthetic-python",)
    )
    monkeypatch.setattr(faults, "process_identity", lambda pid, owner: identity)
    control.arm(
        "VALIDATED_BEFORE_FINALIZE",
        asset_id=UUID(int=3),
        cutoff=time.monotonic() - 0.1 if release is None else time.monotonic() + 1.0,
    )
    if release is None:
        with pytest.raises(RuntimeError, match="^owned fixture barrier expired$"):
            control.callback(AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3)))
    else:
        value = {
            "owner": control.owner,
            "event": "VALIDATED_BEFORE_FINALIZE",
            "id": str(UUID(int=3)),
        }
        value[release] = "foreign-value"
        faults.snapshot_json(tmp_path / "release.json", value, owner=control.owner)
        with pytest.raises(
            faults.FixtureContractError, match="^invalid fixture contract$"
        ):
            control.callback(AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3)))
    assert (tmp_path / "reached.json").exists()


def test_snapshot_writer_still_refuses_process_command_tuple(tmp_path):
    from tests.support import asset_faults as faults

    with (
        faults.OwnedSnapshots(tmp_path, "synthetic-owner") as writer,
        pytest.raises(faults.FixtureContractError),
    ):
        writer.write("identity.json", {"command": ("synthetic-python",)})
    assert not (tmp_path / "identity.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", True),
        ("pid", True),
        ("uid", -1),
        ("ppid", -1),
        ("pgid", 0),
        ("start_ticks", 0),
        ("command", ["synthetic-python"]),
        ("command", ()),
        ("command", ("synthetic-python\n",)),
        ("command", (object(),)),
    ],
    ids=[
        "owner-type",
        "pid-type",
        "uid-negative",
        "ppid-negative",
        "pgid-zero",
        "ticks-zero",
        "command-list",
        "command-empty",
        "command-control",
        "command-object",
    ],
)
def test_callback_corrupted_identity_refuses_before_reached_publication(
    tmp_path, monkeypatch, field, value
):
    import os
    import time

    from wso_core.assets import AssetEvent

    from tests.support import asset_faults as faults

    control = identity_barrier(tmp_path, monkeypatch)
    identity = faults.ProcessIdentity(
        control.owner, os.getpid(), 7, 11, 11, 37, ("synthetic-python",)
    )
    # Simulate a compromised process lookup; ordinary identities remain frozen.
    object.__setattr__(identity, field, value)
    monkeypatch.setattr(faults, "process_identity", lambda pid, owner: identity)
    control.arm(
        "VALIDATED_BEFORE_FINALIZE", asset_id=UUID(int=3), cutoff=time.monotonic() + 1.0
    )
    with pytest.raises(faults.FixtureContractError, match="^invalid fixture contract$"):
        control.callback(AssetEvent("VALIDATED_BEFORE_FINALIZE", UUID(int=3)))
    assert not (tmp_path / "reached.json").exists()
