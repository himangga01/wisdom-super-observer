"""Offline boundary validators; never actual MinIO acceptance."""

import json
from collections import Counter
from io import BytesIO, StringIO, TextIOWrapper
from itertools import product
from unittest.mock import Mock
from xml.etree import ElementTree

import httpx
import pytest
from botocore.exceptions import ClientError

from tests.support.asset_minio import EXCEPTION_TYPES, unavailable_relay_snapshot
from tests.support.asset_provider import AssetProvider, policy_config


@pytest.mark.parametrize(
    "error_type,kind",
    [
        *EXCEPTION_TYPES.items(),
        (TimeoutError, "OS_TIMEOUT"),
        (OSError, "OS_OTHER"),
        (httpx.HTTPError, "HTTPX_OTHER"),
        (Exception, "UNKNOWN"),
    ],
)
def test_http_request_kind_whitelist(tmp_path, monkeypatch, error_type, kind):
    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    del provider.raw_http
    request = Mock(side_effect=error_type("secret-url-body-cookie"))
    monkeypatch.setattr(httpx, "request", request)
    message = acl_diagnostic_run(provider, actor)
    assert f'"exception_kind": "{kind}"' in message
    assert '"call_phase": "HTTP_REQUEST"' in message
    assert '"observed_status": null' in message
    assert "secret-url-body-cookie" not in message
    request.assert_called_once()


@pytest.mark.parametrize("status", [403, True, 503.0, 99, 600, None])
def test_http_response_access_preserves_only_obtained_status(
    tmp_path, monkeypatch, status
):
    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    del provider.raw_http
    order = []

    class Response:
        @property
        def status_code(self):
            order.append("status")
            return status

        @property
        def content(self):
            order.append("content")
            raise httpx.DecodingError("secret-response-body")

    monkeypatch.setattr(httpx, "request", Mock(return_value=Response()))
    message = acl_diagnostic_run(provider, actor)
    assert '"call_phase": "HTTP_RESPONSE_ACCESS"' in message
    assert '"exception_kind": "HTTPX_DECODING_ERROR"' in message
    assert (
        f'"observed_status": {403 if type(status) is int and status == 403 else "null"}'
        in message
    )
    assert order == ["status", "content"]
    assert "secret-response-body" not in message


def test_http_success_keeps_single_request_and_response_access_order(monkeypatch):
    order = []

    class Response:
        @property
        def status_code(self):
            order.append("status")
            return 403

        @property
        def content(self):
            order.append("content")
            return b"private-result"

    request = Mock(return_value=Response())
    monkeypatch.setattr(httpx, "request", request)
    assert AssetProvider.raw_http("GET", "http://unused.invalid") == (
        403,
        b"private-result",
    )
    request.assert_called_once_with(
        "GET",
        "http://unused.invalid",
        timeout=5,
        trust_env=False,
        follow_redirects=False,
    )
    assert order == ["status", "content"]


def test_http_status_access_failure_has_no_invented_status(tmp_path, monkeypatch):
    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    del provider.raw_http

    class Response:
        @property
        def status_code(self):
            raise TypeError("secret-status-property")

        @property
        def content(self):
            pytest.fail("content must not be accessed after failed status access")

    monkeypatch.setattr(httpx, "request", Mock(return_value=Response()))
    message = acl_diagnostic_run(provider, actor)
    assert '"call_phase": "HTTP_RESPONSE_ACCESS"' in message
    assert '"exception_kind": "BUILTIN_TYPE"' in message
    assert '"observed_status": null' in message
    assert "secret-status-property" not in message


def test_operation_kind_survives_required_second_close_failure(tmp_path):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    stream = Mock(
        read=Mock(side_effect=httpx.ReadError("secret-read")),
        close=Mock(side_effect=httpx.ConnectError("secret-close")),
    )
    admin.get_object.side_effect = None
    admin.get_object.return_value = {"Body": stream}
    message = acl_diagnostic_run(provider, actor)
    assert '"exception_kind": "HTTPX_READ_ERROR"' in message
    assert '"call_phase": "OPERATION"' in message
    assert '"close_failed": true' in message
    assert "secret-" not in message
    stream.close.assert_called_once_with()


@pytest.mark.parametrize(
    "category",
    [
        "relay-unsettled",
        "relay-transport",
        "client",
        "container",
        "image",
        "network",
        "volume",
        "private-files",
        "unknown-kind",
    ],
)
def test_provider_close_reports_each_existing_refusal_branch(
    tmp_path, capsys, category
):
    provider = AssetProvider(tmp_path)
    provider.receipt = {"previous": "private-proof"}
    if category.startswith("relay"):
        provider.relay = Mock(
            failed=True,
            diagnostic_snapshot=Mock(return_value=unavailable_relay_snapshot()),
        )
        if category == "relay-unsettled":
            provider.relay.close.side_effect = RuntimeError("secret-relay")
            provider.created = [("container", "retained")]
            provider.inspect = Mock()
    elif category == "client":
        provider.clients = {
            "one": Mock(close=Mock(side_effect=RuntimeError("secret-client")))
        }
    elif category == "private-files":
        provider.work = tmp_path / "unowned"
    else:
        provider.created = [(category, "private-name")]
        provider.inspect = Mock(side_effect=RuntimeError("secret-cli"))
    with pytest.raises(RuntimeError):
        provider.close()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    prefix = "WSO_ASSET_PROVIDER_CLOSE_DIAGNOSTIC="
    assert lines[0].startswith(prefix)
    diagnostic = json.loads(lines[0][len(prefix) :])
    mapped = {
        "relay-unsettled": "RELAY_UNSETTLED",
        "relay-transport": "RELAY_TRANSPORT",
        "private-files": "PRIVATE_FILES",
        "unknown-kind": "UNKNOWN",
    }.get(category, category.upper())
    assert diagnostic == {
        "schema": 1,
        "categories": [mapped],
        "relay": unavailable_relay_snapshot(),
    }
    assert provider.receipt is None
    assert "private-" not in lines[0] and "secret-" not in lines[0]
    if category == "relay-unsettled":
        provider.inspect.assert_not_called()


def test_provider_close_success_emits_nothing_and_preserves_receipt(tmp_path, capsys):
    provider = AssetProvider(tmp_path)
    provider.receipt = {"same": "proof"}
    provider.clients = {"one": Mock()}
    provider.close()
    assert capsys.readouterr().out == ""
    assert provider.receipt == {"same": "proof"}
    provider.clients["one"].close.assert_called_once_with()


def test_provider_close_diagnostic_output_failure_preserves_refusal(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    provider.clients = {"one": Mock(close=Mock(side_effect=OSError("private-client")))}
    monkeypatch.setattr(
        "builtins.print", Mock(side_effect=BrokenPipeError("private-output"))
    )
    with pytest.raises(
        RuntimeError, match="owned asset resource cleanup failed: client"
    ):
        provider.close()


@pytest.mark.parametrize("stream_type", [StringIO, TextIOWrapper])
@pytest.mark.parametrize("unsettled", [True, False])
def test_closed_text_output_preserves_original_close_refusal(
    tmp_path, monkeypatch, stream_type, unsettled
):
    provider = AssetProvider(tmp_path)
    provider.receipt = {"previous": "proof"}
    client = Mock(close=Mock(side_effect=OSError("private-client")))
    provider.clients = {"one": client}
    provider.created = [("network", "owned-network")]
    provider.inspect = Mock(return_value={})
    provider.docker = Mock(side_effect=OSError("private-network"))
    if unsettled:
        provider.relay = Mock(
            close=Mock(side_effect=RuntimeError("private-relay")),
            diagnostic_snapshot=Mock(return_value=unavailable_relay_snapshot()),
        )
    output = stream_type() if stream_type is StringIO else stream_type(BytesIO())
    output.close()
    monkeypatch.setattr("sys.stdout", output)
    expected = (
        "owned relay cleanup unsettled; target retained"
        if unsettled
        else "owned asset resource cleanup failed: client, network"
    )
    with pytest.raises(RuntimeError, match=expected):
        provider.close()
    assert provider.receipt is None
    if unsettled:
        client.close.assert_not_called()
        provider.inspect.assert_not_called()
        provider.docker.assert_not_called()
        assert provider.created == [("network", "owned-network")]
    else:
        client.close.assert_called_once_with()
        provider.inspect.assert_called_once_with("network", "owned-network")
        provider.docker.assert_called_once_with("network", "rm", "owned-network")


def test_http_unsafe_class_request_context_and_labels_are_not_serialized(
    tmp_path, monkeypatch
):
    from tests.support.asset_provider import acl_fields

    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    del provider.raw_http
    unsafe_type = type("PrivateKeyURLClass", (Exception,), {})
    error = unsafe_type("secret-body")
    error.request = httpx.Request(
        "GET", "http://private.invalid/secret-key", headers={"Cookie": "secret-cookie"}
    )
    error.__cause__ = OSError("secret-cause")
    monkeypatch.setattr(httpx, "request", Mock(side_effect=error))
    message = acl_diagnostic_run(provider, actor)
    assert '"exception_kind": "UNKNOWN"' in message
    assert "secret-" not in message and "PrivateKeyURLClass" not in message
    fields = {
        "target": "new",
        "component": "anonymous_get",
        "exception_kind": ["secret-class"],
        "call_phase": "secret-phase",
    }
    normalized = acl_fields(fields)
    assert normalized["exception_kind"] == normalized["call_phase"] == "UNKNOWN"


def test_close_snapshot_categories_are_deduplicated_and_closed(tmp_path, capsys):
    provider = AssetProvider(tmp_path)
    unsafe = {
        **unavailable_relay_snapshot(),
        "available": True,
        "state": "secret-state",
        "failed": 1,
        "connections": True,
        "sockets": 2.0,
        "workers": 4097,
        "first_stage": "secret-stage",
        "first_kind": "secret-kind",
    }
    provider.relay = Mock(diagnostic_snapshot=Mock(return_value=unsafe))
    provider.emit_close_diagnostic(
        ["client", "client", "secret-category", "private-files"]
    )
    message = capsys.readouterr().out
    output = json.loads(message.split("=", 1)[1])
    assert output["categories"] == ["CLIENT", "PRIVATE_FILES", "UNKNOWN"]
    assert output["relay"] == {**unavailable_relay_snapshot(), "available": True}
    assert "secret-" not in message


def test_http_failure_retains_fixed_kind_and_phase(tmp_path, monkeypatch):
    import httpx

    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    del provider.raw_http
    monkeypatch.setattr(
        httpx, "request", Mock(side_effect=httpx.ReadTimeout("secret-url-body"))
    )
    message = acl_diagnostic_run(provider, actor)
    assert '"exception_kind": "HTTPX_READ_TIMEOUT"' in message
    assert '"call_phase": "HTTP_REQUEST"' in message
    assert "secret-url-body" not in message


def test_close_failure_emits_bounded_category(tmp_path, capsys):
    provider = AssetProvider(tmp_path)
    provider.clients = {
        "bootstrap": Mock(close=Mock(side_effect=OSError("secret-path")))
    }
    with pytest.raises(RuntimeError, match="resource cleanup failed"):
        provider.close()
    output = capsys.readouterr().out
    assert output.startswith("WSO_ASSET_PROVIDER_CLOSE_DIAGNOSTIC=")
    assert '"categories": ["CLIENT"]' in output
    assert "secret-path" not in output


def acl_diagnostic_fixture(tmp_path):
    provider = AssetProvider(tmp_path)
    provider.endpoint = "http://unused.invalid"
    admin, actor = Mock(), Mock()
    provider.clients = {"bootstrap": admin}
    private_acl = {
        "Owner": {},
        "Grants": [
            {"Grantee": {"Type": "CanonicalUser"}, "Permission": "FULL_CONTROL"}
        ],
    }
    admin.head_object.side_effect = lambda **kw: (
        {"ContentLength": 10, "ResponseMetadata": {"HTTPStatusCode": 200}}
        if admin.delete_object.call_count == 0
        else (_ for _ in ()).throw(error(404, "NoSuchKey"))
    )
    admin.get_object.side_effect = lambda **kw: {
        "Body": BytesIO(b"ciphertext"),
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }
    admin.get_object_acl.return_value = private_acl
    admin.get_bucket_acl.return_value = private_acl
    admin.get_bucket_policy.side_effect = error(404, "NoSuchBucketPolicy")
    admin.list_multipart_uploads.return_value = {"IsTruncated": False}
    actor.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    actor.create_multipart_upload.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "UploadId": "private-upload",
    }
    actor.upload_part.return_value = {"ETag": "private-etag"}
    provider.raw_http = Mock(return_value=(403, b""))
    return provider, admin, actor


def acl_diagnostic_run(
    provider, actor, operation="put_object", name="gateway", variant=1
):
    with pytest.raises(RuntimeError) as caught:
        provider.verify_public_attempt(
            actor,
            name,
            variant,
            operation,
            {
                "Key": "private-original"
                if operation == "put_object_acl"
                else "private-new"
            },
            "private-original",
            b"ciphertext",
        )
    assert provider.receipt is None
    assert all(not item["effects_verified"] for item in provider.outcomes)
    return str(caught.value)


@pytest.mark.parametrize("target", ["new", "original"])
def test_acl_failure_attributes_signed_head_target(tmp_path, target):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)

    def head(**kw):
        if kw["Key"] == "private-" + target:
            raise error(503, "SlowDown")
        return {"ContentLength": 10}

    admin.head_object.side_effect = head
    message = acl_diagnostic_run(provider, actor)
    assert f'"target": "{target}"' in message
    assert '"component": "signed_head"' in message
    assert '"observed_status": 503' in message
    assert '"observed_code": "SlowDown"' in message
    assert "private-" not in message


@pytest.mark.parametrize("target", ["new", "original"])
@pytest.mark.parametrize(
    "component",
    [
        "signed_get_open",
        "signed_get_read",
        "signed_get_close",
        "object_acl",
        "anonymous_get",
        "anonymous_head",
    ],
)
def test_acl_failure_attributes_each_private_effect(tmp_path, target, component):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    sequence = 0 if target == "new" else 1
    sentinel = "secret-url-key-cookie-credential"
    streams = [Mock(), Mock()]
    for stream in streams:
        stream.read.return_value = b"ciphertext"
    if component in {"signed_get_read", "signed_get_close"}:
        getattr(
            streams[sequence], component.removeprefix("signed_get_")
        ).side_effect = OSError(sentinel)
    responses = [{"Body": stream} for stream in streams]
    if component == "signed_get_open":
        responses[sequence] = error(503, "SlowDown")
    admin.get_object.side_effect = responses
    if component == "object_acl":
        acl_responses = [admin.get_object_acl.return_value] * 2
        acl_responses[sequence] = {"Grants": []}
        admin.get_object_acl.side_effect = acl_responses
    if component.startswith("anonymous"):
        responses = [(403, b"")] * 4
        responses[sequence * 2 + (component == "anonymous_head")] = (
            200,
            b"private-body",
        )
        provider.raw_http.side_effect = responses
    message = acl_diagnostic_run(provider, actor)
    assert f'"target": "{target}"' in message
    assert f'"component": "{component}"' in message
    assert sentinel not in message and "private-body" not in message
    if component != "signed_get_open":
        streams[sequence].close.assert_called_once_with()


@pytest.mark.parametrize(
    "component",
    [
        "bucket_acl",
        "policy_absence",
        "delete_new",
        "absence_head",
        "absence_multipart_page",
    ],
)
def test_acl_failure_attributes_bucket_and_cleanup(tmp_path, component):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    target = (
        "bucket" if component in {"bucket_acl", "policy_absence"} else "new_cleanup"
    )
    if component == "bucket_acl":
        admin.get_bucket_acl.return_value = {"Grants": []}
    elif component == "policy_absence":
        admin.get_bucket_policy.side_effect = None
        admin.get_bucket_policy.return_value = {"Policy": "private-policy"}
    elif component == "delete_new":
        admin.delete_object.side_effect = error(403, "AccessDenied")
    elif component == "absence_head":
        admin.head_object.side_effect = None
        admin.head_object.return_value = {"ContentLength": 10}
    else:
        admin.list_multipart_uploads.side_effect = error(503, "SlowDown")
    message = acl_diagnostic_run(provider, actor)
    assert f'"target": "{target}"' in message
    assert f'"component": "{component}"' in message
    assert "private-policy" not in message


@pytest.mark.parametrize(
    "component", ["multipart_identity", "upload_part", "complete_multipart"]
)
def test_acl_failure_attributes_materialization(tmp_path, component):
    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    if component == "multipart_identity":
        actor.create_multipart_upload.return_value.pop("UploadId")
    else:
        getattr(
            actor,
            component.removesuffix("_multipart") + "_multipart_upload"
            if component == "complete_multipart"
            else component,
        ).side_effect = error(503, "SlowDown")
    message = acl_diagnostic_run(provider, actor, "create_multipart_upload")
    assert '"target": "new"' in message
    assert f'"component": "{component}"' in message


@pytest.mark.parametrize("read_failure", ["exception", "bytes", "comparison"])
def test_acl_first_failure_survives_required_close(tmp_path, read_failure):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    stream = Mock()
    stream.read.side_effect = (
        OSError("secret-read") if read_failure == "exception" else None
    )
    stream.read.return_value = b"wrong-private-bytes"
    if read_failure == "comparison":

        class UnsafeComparison:
            def __ne__(self, other):
                raise RuntimeError("secret-comparison")

        stream.read.return_value = UnsafeComparison()
    stream.close.side_effect = OSError("secret-close")
    admin.get_object.side_effect = None
    admin.get_object.return_value = {"Body": stream}
    message = acl_diagnostic_run(provider, actor)
    assert '"component": "signed_get_read"' in message
    assert '"close_failed": true' in message
    condition = {
        "exception": "TRANSPORT_ERROR",
        "bytes": "BYTES_MISMATCH",
        "comparison": "UNKNOWN",
    }[read_failure]
    assert f'"condition": "{condition}"' in message
    assert "secret-" not in message and "wrong-private" not in message
    stream.close.assert_called_once_with()
    admin.get_object_acl.assert_not_called()


@pytest.mark.parametrize(
    "status", [True, False, 503.0, 99, 600, "private-status", None]
)
def test_acl_diagnostic_status_is_exact_bounded_integer(tmp_path, status):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    admin.head_object.side_effect = error(status, "PrivateCredentialCode")
    message = acl_diagnostic_run(provider, actor)
    assert '"observed_status": null' in message
    assert '"observed_code": "UNKNOWN"' in message
    assert "private-status" not in message and "PrivateCredentialCode" not in message


@pytest.mark.parametrize("mutation_error", ["sdk", "transport"])
@pytest.mark.parametrize("operation", ["put_object", "put_object_acl"])
def test_acl_mutation_response_is_separate_and_sanitized(
    tmp_path, mutation_error, operation
):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    getattr(actor, operation).side_effect = (
        error(418, "PrivateCredentialCode")
        if mutation_error == "sdk"
        else OSError("secret-url-body")
    )
    message = acl_diagnostic_run(provider, actor, operation)
    assert '"component": "mutation_response"' in message
    target = "original" if operation == "put_object_acl" else "new"
    assert f'"target": "{target}"' in message
    assert "code=UNKNOWN" in message
    assert "PrivateCredentialCode" not in message and "secret-url-body" not in message
    admin.head_object.assert_not_called()
    assert provider.outcomes == [
        {
            "actor": "gateway",
            "operation": operation,
            "variant": 1,
            "status": None,
            "code": "UNKNOWN",
            "effects_verified": False,
        }
    ]


@pytest.mark.parametrize(
    "part",
    [{}, {"ETag": None}, {"ETag": ""}, {"ETag": False}, {"ETag": 128}, {"ETag": []}],
)
def test_acl_upload_part_identity_failure_precedes_completion(tmp_path, part):
    provider, _, actor = acl_diagnostic_fixture(tmp_path)
    actor.upload_part.return_value = {
        **part,
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }
    message = acl_diagnostic_run(provider, actor, "create_multipart_upload")
    assert '"target": "new"' in message
    assert '"component": "upload_part"' in message
    assert '"observed_status": 200' in message
    assert '"observed_code": "SUCCESS"' in message
    assert '"condition": "UNKNOWN"' in message
    actor.upload_part.assert_called_once()
    actor.complete_multipart_upload.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "secret-actor"),
        ("operation", "secret-operation"),
        ("variant", True),
        ("variant", 7),
        ("name", []),
        ("operation", {}),
    ],
)
def test_acl_attempt_rejects_unsafe_identity_before_io(tmp_path, field, value):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    arguments = {"name": "gateway", "operation": "put_object", "variant": 1}
    arguments[field] = value
    message = acl_diagnostic_run(provider, actor, **arguments)
    assert message == "invalid fixed ACL attempt identity"
    actor.put_object.assert_not_called()
    admin.head_object.assert_not_called()


@pytest.mark.parametrize(
    "component,condition",
    [
        ("signed_head", "LENGTH_MISMATCH"),
        ("absence_multipart_page", "PAGINATION_INVALID"),
        ("absence_multipart_page", "UPLOAD_SURVIVED"),
    ],
)
def test_acl_semantic_failure_reports_fixed_condition(tmp_path, component, condition):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    if condition == "LENGTH_MISMATCH":
        admin.head_object.side_effect = None
        admin.head_object.return_value = {"ContentLength": 11}
    elif condition == "PAGINATION_INVALID":
        admin.list_multipart_uploads.return_value = {
            "IsTruncated": True,
            "NextKeyMarker": "private-key",
            "NextUploadIdMarker": "",
        }
    else:
        admin.list_multipart_uploads.return_value = {
            "IsTruncated": False,
            "Uploads": [{"Key": "private-new", "UploadId": "private-upload"}],
        }
    message = acl_diagnostic_run(provider, actor)
    assert f'"component": "{component}"' in message
    assert f'"condition": "{condition}"' in message
    assert "private-key" not in message and "private-upload" not in message


@pytest.mark.parametrize("operation", ["put_object", "create_multipart_upload"])
def test_acl_refused_new_mutation_retains_absence_target(tmp_path, operation):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    getattr(actor, operation).side_effect = error(403, "AccessDenied")
    admin.head_object.side_effect = error(503, "SlowDown")
    message = acl_diagnostic_run(provider, actor, operation)
    assert "status=403 code=AccessDenied" in message
    assert '"target": "new"' in message
    assert '"component": "absence_head"' in message
    assert '"observed_status": 503' in message


def test_acl_success_keeps_exact_operation_order_and_outcome(tmp_path):
    provider, admin, actor = acl_diagnostic_fixture(tmp_path)
    trace = Mock()
    trace.attach_mock(actor, "actor")
    trace.attach_mock(admin, "admin")
    trace.attach_mock(provider.raw_http, "http")
    provider.verify_public_attempt(
        actor,
        "gateway",
        1,
        "put_object",
        {"Key": "private-new"},
        "private-original",
        b"ciphertext",
    )
    assert [call[0] for call in trace.mock_calls] == [
        "actor.put_object",
        "admin.head_object",
        "admin.get_object",
        "admin.get_object_acl",
        "http",
        "http",
        "admin.head_object",
        "admin.get_object",
        "admin.get_object_acl",
        "http",
        "http",
        "admin.get_bucket_acl",
        "admin.get_bucket_policy",
        "admin.delete_object",
        "admin.head_object",
        "admin.list_multipart_uploads",
    ]
    assert provider.outcomes == [
        {
            "actor": "gateway",
            "operation": "put_object",
            "variant": 1,
            "status": 200,
            "code": "accepted-inert-candidate",
            "effects_verified": True,
        }
    ]


def test_acl_diagnostic_output_normalizes_unapproved_fields():
    from tests.support.asset_provider import acl_fields

    fields = {
        "target": "new",
        "component": "signed_head",
        "observed_status": True,
        "observed_code": "private-code",
        "condition": "private-condition",
        "close_failed": "private-bool",
        "private-field": "private-value",
    }
    assert acl_fields(fields) == {
        "target": "new",
        "component": "signed_head",
        "observed_status": None,
        "observed_code": "UNKNOWN",
        "condition": "UNKNOWN",
        "exception_kind": "UNKNOWN",
        "call_phase": "UNKNOWN",
    }
    for field in ("target", "component"):
        with pytest.raises(RuntimeError, match="invalid fixed ACL diagnostic metadata"):
            acl_fields({**fields, field: "private-label"})


def relay_identity_fixture(tmp_path):
    provider = AssetProvider(tmp_path)
    provider.container_id = "a" * 64
    provider.network_id = "b" * 64
    provider.relay_pin = (
        provider.container_id,
        provider.network_id,
        "c" * 64,
        "172.28.0.2",
    )
    state = {
        "Id": provider.container_id,
        "Name": "/" + provider.container,
        "Config": {"Labels": {"wso.assets.owner": provider.owner}},
        "State": {"Running": True},
        "HostConfig": {"PortBindings": None},
        "NetworkSettings": {
            "Ports": {"9000/tcp": None},
            "Networks": {
                provider.network: {
                    "NetworkID": provider.network_id,
                    "EndpointID": "c" * 64,
                    "IPAddress": "172.28.0.2",
                    "Gateway": "",
                    "IPv6Gateway": "",
                    "GlobalIPv6Address": "",
                }
            },
        },
    }
    network = {
        "Id": provider.network_id,
        "Name": provider.network,
        "Labels": {"wso.assets.owner": provider.owner},
        "Driver": "bridge",
        "Internal": True,
        "EnableIPv6": False,
        "IPAM": {"Config": [{"Subnet": "172.28.0.0/16", "Gateway": "172.28.0.1"}]},
        "Containers": {
            provider.container_id: {
                "Name": provider.container,
                "EndpointID": "c" * 64,
                "IPv4Address": "172.28.0.2/16",
                "IPv6Address": "",
            }
        },
    }
    return provider, state, network


@pytest.mark.parametrize(
    "mutation",
    [
        "replacement",
        "network",
        "endpoint",
        "address",
        "foreign",
        "subnet",
        "gateway",
        "loopback",
        "stopped",
        "external",
        "ipv6",
        "public-binding",
    ],
)
def test_relay_target_refuses_replacement_or_changed_authority(tmp_path, mutation):
    provider, state, network = relay_identity_fixture(tmp_path)
    endpoint = state["NetworkSettings"]["Networks"][provider.network]
    if mutation == "replacement":
        state["Id"] = "d" * 64
    elif mutation == "network":
        endpoint["NetworkID"] = "d" * 64
    elif mutation == "endpoint":
        endpoint["EndpointID"] = "d" * 64
    elif mutation == "address":
        endpoint["IPAddress"] = "172.28.0.3"
    elif mutation == "foreign":
        network["Containers"]["d" * 64] = dict(
            network["Containers"][provider.container_id]
        )
    elif mutation == "subnet":
        network["IPAM"]["Config"][0]["Subnet"] = "192.168.0.0/24"
    elif mutation == "gateway":
        endpoint["Gateway"] = "172.28.0.1"
    elif mutation == "loopback":
        endpoint["IPAddress"] = "127.0.0.1"
    elif mutation == "stopped":
        state["State"]["Running"] = False
    elif mutation == "external":
        network["Internal"] = False
    elif mutation == "ipv6":
        network["EnableIPv6"] = True
    else:
        state["NetworkSettings"]["Ports"]["9000/tcp"] = [
            {"HostIp": "0.0.0.0", "HostPort": "1234"}
        ]
    with pytest.raises(RuntimeError, match="relay target identity"):
        provider.verify_relay_identity(state, network)
    assert provider.relay_pin == ("a" * 64, "b" * 64, "c" * 64, "172.28.0.2")
    assert provider.receipt is None


def test_relay_target_accepts_exact_pinned_private_endpoint(tmp_path):
    provider, state, network = relay_identity_fixture(tmp_path)
    assert provider.verify_relay_identity(state, network) == provider.relay_pin


def test_any_host_publication_is_refused_even_if_loopback(tmp_path):
    provider, state, network = relay_identity_fixture(tmp_path)
    state["HostConfig"]["PortBindings"] = {
        "9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "1234"}]
    }
    with pytest.raises(RuntimeError, match="relay target identity"):
        provider.verify_relay_identity(state, network)


def test_initial_relay_pin_refuses_reserved_ipv4(tmp_path):
    provider, state, network = relay_identity_fixture(tmp_path)
    provider.relay_pin = None
    state["NetworkSettings"]["Networks"][provider.network]["IPAddress"] = "240.28.0.2"
    network["IPAM"]["Config"] = [{"Subnet": "240.28.0.0/16", "Gateway": "240.28.0.1"}]
    network["Containers"][provider.container_id]["IPv4Address"] = "240.28.0.2/16"
    with pytest.raises(RuntimeError, match="relay target identity"):
        provider.verify_relay_identity(state, network)


@pytest.mark.parametrize("field", ["host", "ports"])
def test_relay_unknown_publication_shape_is_refused(tmp_path, field):
    provider, state, network = relay_identity_fixture(tmp_path)
    if field == "host":
        del state["HostConfig"]["PortBindings"]
    else:
        del state["NetworkSettings"]["Ports"]
    with pytest.raises(RuntimeError, match="relay target identity"):
        provider.verify_relay_identity(state, network)


def error(status, code):
    return ClientError(
        {"ResponseMetadata": {"HTTPStatusCode": status}, "Error": {"Code": code}},
        "Probe",
    )


def test_multipart_bucket_authority_has_no_fabricated_prefix_condition():
    policies = policy_config("dedicated", "installed/", {})
    for name in ("wso-gateway", "wso-maintenance"):
        rows = policies[name]["Statement"]
        assert [
            row for row in rows if row["Action"] == ["s3:ListBucketMultipartUploads"]
        ] == [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucketMultipartUploads"],
                "Resource": "arn:aws:s3:::dedicated",
            }
        ]
        assert next(row for row in rows if row["Action"] == ["s3:ListBucket"])[
            "Condition"
        ] == {"StringLike": {"s3:prefix": ["installed/", "installed/*"]}}
        assert all(row["Resource"] != "*" for row in rows)
    assert "s3:GetObject" not in policies["wso-maintenance"]["Statement"][0]["Action"]


def test_private_synthetic_acl_is_not_a_canonical_owner_identity():
    AssetProvider.require_private_acl(
        {
            "Owner": {"ID": "", "DisplayName": ""},
            "Grants": [
                {
                    "Grantee": {"Type": "CanonicalUser", "ID": "", "DisplayName": ""},
                    "Permission": "FULL_CONTROL",
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "grants",
    [
        [],
        [
            {
                "Grantee": {
                    "Type": "Group",
                    "URI": "http://acs.amazonaws.com/groups/global/AllUsers",
                },
                "Permission": "READ",
            }
        ],
        [
            {
                "Grantee": {"Type": "CanonicalUser", "ID": "foreign"},
                "Permission": "FULL_CONTROL",
            }
        ],
    ],
)
def test_unexpected_synthetic_acl_fails_closed(grants):
    with pytest.raises(RuntimeError):
        AssetProvider.require_private_acl({"Owner": {"ID": ""}, "Grants": grants})


@pytest.mark.parametrize(
    "status,code",
    [(501, "NotImplemented"), (403, "UnknownError"), (400, "InvalidRequest")],
)
def test_unsupported_is_not_supported_iam_denial(status, code):
    with pytest.raises(RuntimeError):
        AssetProvider.denied(Mock(side_effect=error(status, code)), "policy mutation")


def result():
    return {
        "added": {
            "policies": ["wso-gateway", "wso-maintenance"],
            "users": ["gateway-key", "maintenance-key"],
            "userPolicies": [
                {"gateway-key": ["wso-gateway"]},
                {"maintenance-key": ["wso-maintenance"]},
            ],
        },
        "skipped": {},
        "removed": {},
        "failed": {},
    }


@pytest.mark.parametrize(
    "corruption",
    [
        "failed",
        "skipped",
        "removed",
        "unknown",
        "extra-user",
        "duplicate-user",
        "wrong-policy",
        "legacy",
    ],
)
def test_partial_or_unknown_mc_import_rejected(corruption):
    from tests.support.asset_minio import validate_import_result

    value = result()
    if corruption in {"failed", "skipped", "removed"}:
        value[corruption] = {"users": ["gateway-key"]}
    elif corruption == "unknown":
        value["status"] = "success"
    elif corruption == "extra-user":
        value["added"]["users"].append("unrelated")
    elif corruption == "duplicate-user":
        value["added"]["users"].append("gateway-key")
    elif corruption == "wrong-policy":
        value["added"]["userPolicies"][0] = {"gateway-key": ["consoleAdmin"]}
    else:
        value = "legacy success"
    with pytest.raises(RuntimeError, match="IAM import"):
        validate_import_result(
            json.dumps(value),
            {"gateway": ("gateway-key", "a"), "cleanup": ("maintenance-key", "b")},
        )


def test_exact_mc_import_added_entities():
    from tests.support.asset_minio import validate_import_result

    validate_import_result(
        json.dumps(result()),
        {"gateway": ("gateway-key", "a"), "cleanup": ("maintenance-key", "b")},
    )


@pytest.mark.parametrize("field", ["users", "policies"])
def test_mc_added_entity_dictionary_cannot_substitute_for_a_list(field):
    from tests.support.asset_minio import validate_import_result

    value = result()
    value["added"][field] = dict.fromkeys(value["added"][field], "unexpected")
    with pytest.raises(RuntimeError, match="IAM import"):
        validate_import_result(
            json.dumps(value),
            {"gateway": ("gateway-key", "a"), "cleanup": ("maintenance-key", "b")},
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/file",
        "https://evil.invalid/file",
        "https://github.com.evil.invalid/file",
        "https://user:secret@github.com/file",
    ],
)
def test_nonofficial_or_credentialed_redirect_rejected(url):
    from tests.support.asset_minio import validate_download_url

    with pytest.raises(RuntimeError):
        validate_download_url(url)


@pytest.mark.parametrize("length,digest", [(3, "good"), (4, "bad")])
def test_fixed_artifact_length_and_hash_required(length, digest):
    from tests.support.asset_minio import validate_artifact

    with pytest.raises(RuntimeError):
        validate_artifact(length, digest, 4, "good")


def effect_provider(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.endpoint = "http://unused.invalid"
    admin = Mock()
    provider.clients = {"bootstrap": admin}
    admin.get_object.return_value = {"Body": BytesIO(b"ciphertext")}
    admin.head_object.return_value = {"ContentLength": 10}
    admin.get_object_acl.return_value = {
        "Owner": {"ID": ""},
        "Grants": [
            {
                "Grantee": {"Type": "CanonicalUser", "ID": ""},
                "Permission": "FULL_CONTROL",
            }
        ],
    }
    monkeypatch.setattr(provider, "raw_http", Mock(return_value=(403, b"")))
    return provider


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_inert_request_still_requires_anonymous_denial(tmp_path, monkeypatch, method):
    provider = effect_provider(tmp_path, monkeypatch)
    provider.raw_http.side_effect = lambda actual, *_: (
        200 if actual == method else 403,
        b"",
    )
    with pytest.raises(RuntimeError, match="anonymous"):
        provider.private_effect(provider.prefix + "private", b"ciphertext")


def test_inert_request_requires_original_signed_bytes(tmp_path, monkeypatch):
    provider = effect_provider(tmp_path, monkeypatch)
    provider.clients["bootstrap"].get_object.return_value = {
        "Body": BytesIO(b"changed")
    }
    with pytest.raises(RuntimeError, match="bytes"):
        provider.private_effect(provider.prefix + "private", b"ciphertext")


def test_accepted_multipart_completes_before_private_effect(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    actor = Mock()
    actor.upload_part.return_value = {"ETag": "part"}
    effects = []
    actor.complete_multipart_upload.side_effect = lambda **_: effects.append("complete")
    monkeypatch.setattr(
        provider, "private_effect", lambda *_: effects.append("effect"), raising=False
    )
    provider.materialize_public_upload(actor, "owned", "upload", b"ciphertext")
    assert effects == ["complete", "effect"]


def test_multipart_pages_refuse_foreign_rows_and_repeated_markers(tmp_path):
    provider = AssetProvider(tmp_path)
    client = Mock()
    client.list_multipart_uploads.return_value = {
        "Uploads": [{"Key": "foreign", "UploadId": "id"}],
        "IsTruncated": False,
    }
    with pytest.raises(RuntimeError, match="foreign"):
        provider.multipart_pages(client, provider.prefix)
    client.list_multipart_uploads.return_value = {
        "Uploads": [],
        "IsTruncated": True,
        "NextKeyMarker": "marker",
        "NextUploadIdMarker": "id",
    }
    with pytest.raises(RuntimeError, match="pagination"):
        provider.multipart_pages(client, provider.prefix)


def test_iam_archive_contains_only_pinned_regular_users_and_fixed_mappings():
    import zipfile

    from tests.support.asset_minio import iam_archive_bytes

    credentials = {
        "bootstrap": ("root-key", "root-secret"),
        "gateway": ("gateway-key", "gateway-secret"),
        "cleanup": ("maintenance-key", "maintenance-secret"),
    }
    policies = policy_config("dedicated", "installed/", credentials)
    with zipfile.ZipFile(BytesIO(iam_archive_bytes(credentials, policies))) as archive:
        assert set(archive.namelist()) == {
            "iam-assets/policies.json",
            "iam-assets/users.json",
            "iam-assets/user_mappings.json",
        }
        assert json.loads(archive.read("iam-assets/users.json")) == {
            "gateway-key": {"secretKey": "gateway-secret", "status": "enabled"},
            "maintenance-key": {"secretKey": "maintenance-secret", "status": "enabled"},
        }
        assert json.loads(archive.read("iam-assets/user_mappings.json")) == {
            "gateway-key": {"version": 1, "policy": "wso-gateway"},
            "maintenance-key": {"version": 1, "policy": "wso-maintenance"},
        }
        assert json.loads(archive.read("iam-assets/policies.json")) == policies


CONTROL_MUTATIONS = (
    "put_bucket_policy",
    "delete_bucket_policy",
    "put_bucket_acl",
    "put_object_acl",
    "put_bucket_ownership_controls",
    "delete_bucket_ownership_controls",
    "put_public_access_block",
    "delete_public_access_block",
    "create_bucket",
)
CONTROL_GETS = ("get_bucket_ownership_controls", "get_public_access_block")
PARSER_PUTS = {"put_bucket_ownership_controls", "put_public_access_block"}
CONTROL_EFFECTS = (
    "signed_head",
    "signed_bytes",
    "object_acl",
    "bucket_acl",
    "policy_absence",
    "anonymous_get",
    "anonymous_head",
)


def control_fixture(tmp_path, monkeypatch, *, fault=None, effect_fault=None):
    provider = AssetProvider(tmp_path)
    provider.endpoint = "http://unused.invalid"
    provider.clients = {name: Mock() for name in ("bootstrap", "gateway", "cleanup")}
    events = []
    acl = {
        "Owner": {"ID": ""},
        "Grants": [
            {
                "Grantee": {"Type": "CanonicalUser", "ID": ""},
                "Permission": "FULL_CONTROL",
            }
        ],
    }

    def effect(name, result):
        def perform(**_):
            events.append(("effect", name))
            if effect_fault == name and any(e[0] == "attempt" for e in events):
                raise RuntimeError("SECRET https://private.invalid/credentials")
            if name == "policy_absence":
                raise error(404, "NoSuchBucketPolicy")
            return result() if callable(result) else result

        return perform

    admin = provider.clients["bootstrap"]
    admin.head_object.side_effect = effect("signed_head", {"ContentLength": 10})
    admin.get_object.side_effect = effect(
        "signed_bytes", lambda: {"Body": BytesIO(b"ciphertext")}
    )
    admin.get_object_acl.side_effect = effect("object_acl", acl)
    admin.get_bucket_acl.side_effect = effect("bucket_acl", acl)
    admin.get_bucket_policy.side_effect = effect("policy_absence", None)

    def anonymous(method, *_):
        return effect("anonymous_" + method.lower(), (403, b""))()

    monkeypatch.setattr(provider, "raw_http", anonymous)

    def attempt(name, operation):
        def perform(**arguments):
            events.append(("attempt", name, operation, arguments))
            if fault and (name, operation) == fault[:2]:
                value = fault[2]
                if isinstance(value, Exception):
                    raise value
                return value
            if name == "bootstrap" and operation in CONTROL_MUTATIONS:
                raise AssertionError("bootstrap mutations prohibited")
            expected = (
                (400, "MalformedXML")
                if operation in PARSER_PUTS
                else (501, "NotImplemented")
                if operation in CONTROL_GETS
                else (403, "AccessDenied")
            )
            raise error(*expected)

        return perform

    for name, actor in provider.clients.items():
        for operation in (*CONTROL_MUTATIONS, *CONTROL_GETS):
            getattr(actor, operation).side_effect = attempt(name, operation)
    return provider, events


def assert_control_effects(events):
    starts = [i for i, event in enumerate(events) if event[0] == "attempt"]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(events)
        assert events[start + 1 : end] == [
            ("effect", component) for component in CONTROL_EFFECTS
        ]


def test_v2_exact_controls_payloads_queries_order_and_complete_effects(
    tmp_path, monkeypatch
):
    from botocore.serialize import create_serializer
    from botocore.session import get_session

    provider, events = control_fixture(tmp_path, monkeypatch)
    key = provider.prefix + "private"
    provider.control_profile(key, b"ciphertext")
    attempts = [event for event in events if event[0] == "attempt"]
    assert [(e[1], e[2]) for e in attempts] == [
        (actor, operation)
        for actor in ("gateway", "cleanup")
        for operation in CONTROL_MUTATIONS
    ] + [
        (actor, operation)
        for actor in ("bootstrap", "gateway", "cleanup")
        for operation in CONTROL_GETS
    ]
    assert len(attempts) == 24
    assert_control_effects(events)
    assert len(provider.control_outcomes) == 24
    assert all(
        outcome["response_verified"] and outcome["effects_verified"]
        for outcome in provider.control_outcomes
    )
    assert Counter(
        (row["status"], row["code"]) for row in provider.control_outcomes
    ) == {
        (400, "MalformedXML"): 4,
        (403, "AccessDenied"): 14,
        (501, "NotImplemented"): 6,
    }
    model = get_session().get_service_model("s3")
    serializer = create_serializer("rest-xml")
    for _, actor, operation, arguments in attempts:
        assert arguments["Bucket"] == provider.bucket
        if operation == "create_bucket":
            assert actor != "bootstrap"
            assert arguments == {"Bucket": provider.bucket}
            request = serializer.serialize_to_request(
                arguments, model.operation_model("CreateBucket")
            )
            assert request["method"] == "PUT"
            assert request["url_path"] == "/" + provider.bucket
            assert request["query_string"] == {}
            assert request["body"] == b""
        elif operation in PARSER_PUTS:
            ownership = operation == "put_bucket_ownership_controls"
            api = "PutBucketOwnershipControls" if ownership else "PutPublicAccessBlock"
            field = (
                "OwnershipControls" if ownership else "PublicAccessBlockConfiguration"
            )
            expected = (
                {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
                if ownership
                else dict.fromkeys(
                    (
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    ),
                    True,
                )
            )
            assert arguments == {"Bucket": provider.bucket, field: expected}
            request = serializer.serialize_to_request(
                arguments, model.operation_model(api)
            )
            assert request["method"] == "PUT"
            assert request["url_path"] == (
                "/"
                + provider.bucket
                + ("?ownershipControls" if ownership else "?publicAccessBlock")
            )
            xml = ElementTree.fromstring(request["body"])
            assert xml.tag == "{http://s3.amazonaws.com/doc/2006-03-01/}" + field
            if ownership:
                assert (
                    xml.find("{*}Rule/{*}ObjectOwnership").text == "BucketOwnerEnforced"
                )
            else:
                assert {
                    node.tag.rsplit("}", 1)[1]: node.text for node in xml
                } == dict.fromkeys(expected, "true")
        elif operation == "put_object_acl":
            assert arguments == {
                "Bucket": provider.bucket,
                "Key": key,
                "ACL": "private",
            }
        elif operation == "put_bucket_acl":
            assert arguments == {"Bucket": provider.bucket, "ACL": "private"}
        elif operation == "put_bucket_policy":
            policy = json.loads(arguments["Policy"])
            assert policy["Statement"][0]["Principal"] == "*"
            assert (
                policy["Statement"][0]["Resource"]
                == f"arn:aws:s3:::{provider.bucket}/*"
            )
        else:
            assert arguments == {"Bucket": provider.bucket}
        if operation in (
            *CONTROL_GETS,
            "delete_bucket_ownership_controls",
            "delete_public_access_block",
        ):
            api = "".join(part.capitalize() for part in operation.split("_"))
            request = serializer.serialize_to_request(
                arguments, model.operation_model(api)
            )
            ownership = "ownership" in operation
            assert request["method"] == (
                "GET" if operation in CONTROL_GETS else "DELETE"
            )
            assert request["url_path"] == "/" + provider.bucket + (
                "?ownershipControls" if ownership else "?publicAccessBlock"
            )
            assert request["query_string"] == {}
            assert request["body"] == b""
    for operation in CONTROL_MUTATIONS:
        assert not getattr(provider.clients["bootstrap"], operation).called


def malformed_metadata_error():
    value = error(403, "AccessDenied")
    value.response["ResponseMetadata"] = "SECRET"
    return value


@pytest.mark.parametrize("operation", sorted(PARSER_PUTS))
@pytest.mark.parametrize(
    "response",
    [
        {"ResponseMetadata": {"HTTPStatusCode": 200}},
        error(403, "AccessDenied"),
        error(501, "NotImplemented"),
        error(400, "InvalidRequest"),
        error(403, "MalformedXML"),
        error(400, "SECRETprivatekey"),
        RuntimeError("SECRET https://private.invalid/credentials"),
    ],
)
def test_parser_refusal_retains_operation_and_attempts_all_effects(
    tmp_path, monkeypatch, operation, response
):
    provider, events = control_fixture(
        tmp_path, monkeypatch, fault=("gateway", operation, response)
    )
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    message = str(raised.value)
    assert "actor=gateway operation=" + operation in message
    assert "effects_verified=True" in message
    assert "SECRET" not in message
    assert "private.invalid" not in message
    assert raised.value.__suppress_context__
    assert [e for e in events if e[0] == "attempt"][-1][2] == operation
    assert_control_effects(events)
    assert provider.receipt is None


@pytest.mark.parametrize("component", CONTROL_EFFECTS)
def test_control_readback_failure_is_unverified_and_preserves_original_label(
    tmp_path, monkeypatch, component
):
    provider, events = control_fixture(tmp_path, monkeypatch, effect_fault=component)
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    message = str(raised.value)
    assert "actor=gateway operation=put_bucket_policy" in message
    assert "effects_verified=False" in message
    assert component in message
    assert "SECRET" not in message
    assert_control_effects(events)
    assert len([e for e in events if e[0] == "attempt"]) == 1
    assert provider.receipt is None


def test_v2_producer_profile_is_exact():
    from tests.support.asset_provider import SECURITY_PROFILE

    assert SECURITY_PROFILE == "minio-inert-acl-dedicated-bucket-v2"


@pytest.mark.parametrize(
    "response",
    [
        error(403.0, "AccessDenied"),
        {"ResponseMetadata": "SECRET https://private.invalid/credentials"},
        malformed_metadata_error(),
    ],
)
def test_unknown_control_metadata_is_refused_with_complete_sanitized_effects(
    tmp_path, monkeypatch, response
):
    provider, events = control_fixture(
        tmp_path, monkeypatch, fault=("gateway", "put_bucket_policy", response)
    )
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    message = str(raised.value)
    assert "actor=gateway operation=put_bucket_policy" in message
    assert "effects_verified=True" in message
    assert "SECRET" not in message
    assert "private.invalid" not in message
    assert_control_effects(events)
    assert len([e for e in events if e[0] == "attempt"]) == 1
    assert provider.receipt is None


@pytest.mark.parametrize(
    "actor,operation",
    [
        (actor, operation)
        for actor in ("gateway", "cleanup")
        for operation in CONTROL_MUTATIONS
    ]
    + [
        (actor, operation)
        for actor in ("bootstrap", "gateway", "cleanup")
        for operation in CONTROL_GETS
    ],
)
@pytest.mark.parametrize("refusal", ["success", "status", "code", "transport"])
def test_each_control_attempt_enforces_exact_pair_and_preserves_full_effects(
    tmp_path, monkeypatch, actor, operation, refusal
):
    status, code = (
        (400, "MalformedXML")
        if operation in PARSER_PUTS
        else (501, "NotImplemented")
        if operation in CONTROL_GETS
        else (403, "AccessDenied")
    )
    responses = {
        "success": {"ResponseMetadata": {"HTTPStatusCode": 204}},
        "status": error(401, code),
        "code": error(status, "403"),
        "transport": RuntimeError("SECRET https://private.invalid/credentials"),
    }
    provider, events = control_fixture(
        tmp_path, monkeypatch, fault=(actor, operation, responses[refusal])
    )
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    message = str(raised.value)
    assert f"actor={actor} operation={operation}" in message
    assert "effects_verified=True" in message
    assert "SECRET" not in message
    assert_control_effects(events)
    assert [e for e in events if e[0] == "attempt"][-1][1:3] == (actor, operation)
    assert not provider.control_outcomes[-1]["response_verified"]
    assert provider.control_outcomes[-1]["effects_verified"]
    assert provider.receipt is None


def test_response_refusal_and_readback_failure_both_remain_visible(
    tmp_path, monkeypatch
):
    provider, events = control_fixture(
        tmp_path,
        monkeypatch,
        fault=(
            "gateway",
            "put_bucket_ownership_controls",
            error(501, "NotImplemented"),
        ),
        effect_fault=None,
    )
    admin = provider.clients["bootstrap"]
    original = admin.get_bucket_acl.side_effect

    def changed_acl(**arguments):
        value = original(**arguments)
        if any(
            e[:3] == ("attempt", "gateway", "put_bucket_ownership_controls")
            for e in events
        ):
            return {"Owner": {}, "Grants": []}
        return value

    admin.get_bucket_acl.side_effect = changed_acl
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    message = str(raised.value)
    assert "actor=gateway operation=put_bucket_ownership_controls" in message
    assert "actual_status=501 actual_code=NotImplemented" in message
    assert "effects_verified=False failed_components=bucket_acl" in message
    assert_control_effects(events)
    assert provider.receipt is None


@pytest.mark.parametrize("component", ["policy_absence", "bucket_acl"])
def test_control_baseline_readback_transport_is_sanitized(
    tmp_path, monkeypatch, component
):
    provider, events = control_fixture(tmp_path, monkeypatch)
    operation = (
        "get_bucket_policy" if component == "policy_absence" else "get_bucket_acl"
    )
    getattr(provider.clients["bootstrap"], operation).side_effect = RuntimeError(
        "SECRET https://private.invalid/credentials"
    )
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    assert str(raised.value) == "provider control baseline privacy unverified"
    assert raised.value.__suppress_context__
    assert not any(e[0] == "attempt" for e in events)
    assert provider.receipt is None


@pytest.mark.parametrize("component", CONTROL_EFFECTS)
def test_each_control_effect_rejects_changed_state(tmp_path, monkeypatch, component):
    provider, events = control_fixture(tmp_path, monkeypatch)
    admin = provider.clients["bootstrap"]
    operations = {
        "signed_head": ("head_object", {"ContentLength": 11}),
        "signed_bytes": ("get_object", {"Body": BytesIO(b"changed")}),
        "object_acl": ("get_object_acl", {"Owner": {}, "Grants": []}),
        "bucket_acl": ("get_bucket_acl", {"Owner": {}, "Grants": []}),
        "policy_absence": ("get_bucket_policy", {"Policy": "public"}),
    }
    if component in operations:
        operation, changed = operations[component]
        original = getattr(admin, operation).side_effect

        def altered(**arguments):
            if any(e[0] == "attempt" for e in events):
                events.append(("effect", component))
                return changed
            return original(**arguments)

        getattr(admin, operation).side_effect = altered
    else:
        original = provider.raw_http

        def altered_http(method, *arguments):
            value = original(method, *arguments)
            return (200, b"") if "anonymous_" + method.lower() == component else value

        monkeypatch.setattr(provider, "raw_http", altered_http)
    with pytest.raises(RuntimeError) as raised:
        provider.control_profile(provider.prefix + "private", b"ciphertext")
    assert f"effects_verified=False failed_components={component}" in str(raised.value)
    assert_control_effects(events)
    assert provider.receipt is None


@pytest.mark.parametrize(
    "status,code",
    [(403, "AccessDenied"), (400, "InvalidRequest"), (501, "UnknownError")],
)
def test_unsupported_get_requires_exact_pinned_501(status, code):
    with pytest.raises(RuntimeError, match="unsupported-control"):
        AssetProvider.unsupported(Mock(side_effect=error(status, code)))


def test_failed_public_effect_keeps_sanitized_typed_outcome(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    actor = Mock()
    actor.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    monkeypatch.setattr(
        provider,
        "private_effect",
        Mock(side_effect=RuntimeError("private bytes changed")),
    )
    with pytest.raises(
        RuntimeError, match="actor=bootstrap operation=put_object variant=0 status=200"
    ):
        provider.verify_public_attempt(
            actor,
            "bootstrap",
            0,
            "put_object",
            {
                "Bucket": provider.bucket,
                "Key": provider.prefix + "new",
                "Body": b"ciphertext",
            },
            provider.prefix + "original",
            b"ciphertext",
        )
    assert provider.outcomes == [
        {
            "actor": "bootstrap",
            "operation": "put_object",
            "variant": 0,
            "status": 200,
            "code": "accepted-inert-candidate",
            "effects_verified": False,
        }
    ]
    assert provider.receipt is None


@pytest.mark.parametrize("unexpected", ["success", "unsupported"])
def test_failed_admin_denial_reports_actual_typed_result(unexpected):
    operation = (
        Mock(return_value={"ResponseMetadata": {"HTTPStatusCode": 200}})
        if unexpected == "success"
        else Mock(side_effect=error(501, "NotImplemented"))
    )
    expected = (
        "actual_status=200 actual_code=SUCCESS"
        if unexpected == "success"
        else "actual_status=501 actual_code=NotImplemented"
    )
    with pytest.raises(RuntimeError, match=expected):
        AssetProvider.denied(operation, "runtime public policy")


def test_numeric_403_is_not_an_administrative_access_denied():
    with pytest.raises(RuntimeError, match="actual_code=403"):
        AssetProvider.denied(Mock(side_effect=error(403, "403")), "public policy")


def test_numeric_403_allowed_only_for_explicit_head_probe():
    AssetProvider.denied(
        Mock(side_effect=error(403, "403")), "maintenance HEAD", head=True
    )


def test_exact_actor_operation_public_grant_matrix_and_valid_xml(tmp_path, monkeypatch):
    from botocore.serialize import create_serializer
    from botocore.session import get_session

    provider = AssetProvider(tmp_path)
    provider.work = tmp_path
    provider.clients = {name: Mock() for name in ("bootstrap", "gateway", "cleanup")}
    monkeypatch.setattr(provider, "control_profile", lambda *_: None)
    monkeypatch.setattr(provider, "private_effect", lambda *_: None)
    monkeypatch.setattr(provider, "raw_http", Mock(return_value=(403, b"")))
    provider.endpoint = "http://unused.invalid"
    seen = []
    model = get_session().get_service_model("s3")
    serializer = create_serializer("rest-xml")

    def record(actor, name, _index, operation, arguments, original, body):
        assert actor is provider.clients[name]
        assert arguments["Bucket"] == provider.bucket
        assert arguments["Key"].startswith(provider.prefix)
        if "ACL" in arguments:
            grant = ("canned", arguments["ACL"])
        elif operation == "put_object_acl":
            policy = arguments["AccessControlPolicy"]
            owner = "0" * 64
            assert policy["Owner"] == {"ID": owner}
            assert policy["Grants"][0] == {
                "Grantee": {"Type": "CanonicalUser", "ID": owner},
                "Permission": "FULL_CONTROL",
            }
            assert len(policy["Grants"]) == 2
            public = policy["Grants"][1]
            group = public["Grantee"]
            assert group["Type"] == "Group"
            uri = group["URI"]
            assert uri in {
                "http://acs.amazonaws.com/groups/global/AllUsers",
                "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
            }
            grant = ("group", uri.rsplit("/", 1)[1], public["Permission"])
            encoded = serializer.serialize_to_request(
                arguments, model.operation_model("PutObjectAcl")
            )["body"]
            xml = ElementTree.fromstring(encoded)
            assert xml.find("{*}Owner/{*}ID").text == owner
            xml_grants = xml.findall("{*}AccessControlList/{*}Grant")
            assert len(xml_grants) == 2
            assert xml_grants[1].find("{*}Grantee/{*}URI").text == uri
            assert xml_grants[1].find("{*}Permission").text == public["Permission"]
        else:
            field = "GrantRead" if "GrantRead" in arguments else "GrantFullControl"
            header = arguments[field]
            assert header.startswith('uri="http://acs.amazonaws.com/groups/global/')
            assert header.endswith('"')
            grant = (
                "group",
                header[:-1].rsplit("/", 1)[1],
                "READ" if field == "GrantRead" else "FULL_CONTROL",
            )
        if operation == "put_object_acl":
            assert arguments["Key"] == original
        elif operation == "put_object":
            assert arguments["Body"] == body
        seen.append((name, operation, grant))
        provider.outcomes.append({"effects_verified": True})

    monkeypatch.setattr(provider, "verify_public_attempt", record)
    provider.privacy_profile(provider.prefix + "private", b"ciphertext")
    expected_grants = {
        ("canned", "public-read"),
        ("canned", "public-read-write"),
        ("canned", "authenticated-read"),
        ("group", "AllUsers", "READ"),
        ("group", "AllUsers", "FULL_CONTROL"),
        ("group", "AuthenticatedUsers", "READ"),
        ("group", "AuthenticatedUsers", "FULL_CONTROL"),
    }
    expected = product(
        ("bootstrap", "gateway", "cleanup"),
        ("put_object_acl", "put_object", "create_multipart_upload"),
        expected_grants,
    )
    assert Counter(seen) == Counter(expected)
