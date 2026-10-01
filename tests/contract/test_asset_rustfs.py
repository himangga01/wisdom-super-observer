"""Offline RustFS fixture contracts; no installed provider acceptance."""

import io
import json
import zipfile
from copy import deepcopy

import pytest

from tests.support.asset_provider import SECURITY_PROFILE, AssetProvider
from tests.support.asset_rustfs import NativeIamFailure, NativeSnapshotFailure


def archive(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, body in members:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100755 << 16
            bundle.writestr(entry, body)
    return output.getvalue()


def test_strict_native_json_refuses_duplicate_members_and_depth():
    from tests.support.asset_rustfs import strict_json

    assert strict_json(b'{"ok":[1,true]}') == {"ok": [1, True]}
    for payload in (
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"\xef\xbb\xbf{}",
        b"[" * 17 + b"0" + b"]" * 17,
    ):
        with pytest.raises(RuntimeError, match="native JSON"):
            strict_json(payload)


def test_import_response_requires_exact_two_bindings_not_counts():
    from tests.support.asset_rustfs import import_payload, validate_import_result

    identities = {
        "bootstrap": ("a" * 20, "b" * 40),
        "gateway": ("c" * 20, "d" * 40),
        "cleanup": ("e" * 20, "f" * 40),
    }
    policies = {
        "wso-gateway": {"Version": "2012-10-17", "Statement": []},
        "wso-maintenance": {"Version": "2012-10-17", "Statement": []},
    }
    payload = import_payload(identities, policies)
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        assert set(bundle.namelist()) == {
            "iam-assets/policies.json",
            "iam-assets/users.json",
            "iam-assets/user_mappings.json",
        }
        assert set(json.loads(bundle.read("iam-assets/users.json"))) == {
            "c" * 20,
            "e" * 20,
        }
    entities = (
        "policies",
        "users",
        "groups",
        "serviceAccounts",
        "userPolicies",
        "groupPolicies",
        "stsPolicies",
    )
    result = {
        section: {entity: [] for entity in entities}
        for section in ("skipped", "removed", "added", "failed")
    }
    result["added"].update(
        policies=list(policies),
        users=["c" * 20, "e" * 20],
        userPolicies=[{"c" * 20: ["wso-gateway"]}, {"e" * 20: ["wso-maintenance"]}],
    )
    validate_import_result(result, identities)
    result["added"]["userPolicies"][0] = {"c" * 20: ["wso-maintenance"]}
    with pytest.raises(RuntimeError, match="native IAM import"):
        validate_import_result(result, identities)


def test_phase_budget_never_renews_old_cutoff_after_return():
    from tests.support.asset_rustfs import PhaseBudget

    now = [0.0]
    budget = PhaseBudget(clock=lambda: now[0])
    budget.enter("A")
    assert budget.allowance(180) == 180
    now[0] = 359.5
    assert budget.allowance(20) == 0.5
    now[0] = 360
    with pytest.raises(RuntimeError, match="phase cutoff"):
        budget.check()
    with pytest.raises(RuntimeError, match="phase cutoff"):
        budget.enter("B")


def iam_fixture():
    from tests.support.asset_rustfs import (
        NativeIam,
        PhaseBudget,
        zip_maps,
    )

    identities = {
        "bootstrap": ("a" * 20, "b" * 40),
        "gateway": ("c" * 20, "d" * 40),
        "cleanup": ("e" * 20, "f" * 40),
    }
    policies = {
        "wso-gateway": {"Version": "2012-10-17", "Statement": []},
        "wso-maintenance": {"Version": "2012-10-17", "Statement": []},
    }
    maps = {
        name: {}
        for name in (
            "policies",
            "users",
            "groups",
            "svcaccts",
            "user_mappings",
            "group_mappings",
            "stsuser_mappings",
        )
    }
    maps["policies"] = {**native_defaults(), **policies}
    stamp = "2026-10-01T00:00:00Z"
    maps["users"] = {
        identities[actor][0]: {"secretKey": identities[actor][1], "status": "enabled"}
        for actor in ("gateway", "cleanup")
    }
    maps["user_mappings"] = {
        identities[actor][0]: {
            "version": 1,
            "policy": "wso-" + ("gateway" if actor == "gateway" else "maintenance"),
            "updatedAt": stamp,
        }
        for actor in ("gateway", "cleanup")
    }
    calls = []
    controls = {"changed": False, "fail_get": None, "failure": False}

    def request(actor, method, path, query, body, headers, timeout):
        calls.append((actor, method, path))
        assert "Authorization" in headers and timeout <= 20
        if method == "PUT":
            controls["changed"] = True
            return 403, "application/xml", b"<Error><Code>AccessDenied</Code></Error>"
        if controls["fail_get"] == len(calls):
            raise ValueError("unsafe private body")
        if path == "export-iam":
            return 200, "application/zip", zip_maps(maps)
        if path == "user-info":
            mapping = maps["user_mappings"][query["accessKey"]]
            result = {
                "status": "enabled",
                "policyName": mapping["policy"],
                "updatedAt": stamp,
            }
        else:
            date = [
                2026,
                274,
                0,
                0,
                0,
                int(controls["failure"] and controls["changed"]),
                0,
                0,
                0,
            ]
            result = {
                "policy_name": query["name"],
                "policy": policies[query["name"]],
                "create_date": [2026, 274, 0, 0, 0, 0, 0, 0, 0],
                "update_date": date,
            }
        return 200, "application/json", json.dumps(result).encode()

    budget = PhaseBudget()
    budget.enter("A")
    budget.enter("B")
    budget.enter("C")
    return (
        NativeIam("http://127.0.0.1:1", identities, policies, budget, request=request),
        calls,
        controls,
        maps,
    )


def test_native_no_effect_uses_twenty_reads_and_two_independent_denials():
    # Independent literal native templates model the complete unchanged IAM state.
    native, calls, _, _ = iam_fixture()
    native.no_effect()
    assert len(calls) == 22
    assert [item[0] for item in calls if item[1] == "PUT"] == ["gateway", "cleanup"]
    assert all(item[0] == "bootstrap" for item in calls if item[1] == "GET")


def test_native_no_effect_rejects_nominal_denial_with_metadata_only_change():
    native, calls, controls, _ = iam_fixture()
    controls["failure"] = True
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
        caught.value.status,
    ) == ("GATEWAY", "IAM_AFTER", "POLICY_GATEWAY", "METADATA", None)
    assert len(calls) == 11


@pytest.mark.parametrize("failed_read, expected_calls", [(1, 5), (7, 11)])
def test_native_no_effect_finishes_safe_observations_and_never_repairs(
    failed_read, expected_calls
):
    native, calls, controls, _ = iam_fixture()
    controls["fail_get"] = failed_read
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
    ) == (
        "GATEWAY",
        "IAM_BEFORE" if failed_read == 1 else "IAM_AFTER",
        "EXPORT",
        "SHAPE",
    )
    assert len(calls) == expected_calls
    assert len([item for item in calls if item[1] == "PUT"]) == (
        0 if failed_read == 1 else 1
    )


def test_native_snapshot_does_not_alias_mutable_export_state():
    native, _, _, maps = iam_fixture()
    before = native.snapshot()
    maps["users"]["c" * 20]["secretKey"] = "bad"
    assert b'"secretKey":"' + b"d" * 40 + b'"' in before
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "EXPORT",
        "EXPECTED_STATE",
    )


def test_native_multipart_cursor_must_be_received_row_identity():
    from tests.support.asset_rustfs import NativeListingFailure, native_pages

    class Client:
        def list_multipart_uploads(self, **kwargs):
            return {
                "Uploads": [{"Key": "prefix/a", "UploadId": "received"}],
                "IsTruncated": True,
                "NextKeyMarker": "prefix/a",
                "NextUploadIdMarker": "invented",
            }

    with pytest.raises(NativeListingFailure) as caught:
        native_pages(
            Client(), "bucket", "prefix/", "multipart", {("prefix/a", "received")}
        )
    assert caught.value.summary["pages"] == 1
    assert "received" not in str(caught.value) and "invented" not in str(caught.value)


def test_native_pages_retains_actual_same_key_upload_boundary_and_resume_marker():
    from tests.support.asset_rustfs import native_pages

    identities = [("prefix/a", "u1"), ("prefix/a", "u2"), ("prefix/b", "u3")]
    calls = []

    class Client:
        def list_multipart_uploads(self, **kwargs):
            calls.append(kwargs)
            marker = (kwargs.get("KeyMarker"), kwargs.get("UploadIdMarker"))
            index = identities.index(marker) + 1 if marker in identities else 0
            key, upload = identities[index]
            return {
                "Uploads": [{"Key": key, "UploadId": upload}],
                "IsTruncated": index < 2,
                "NextKeyMarker": key,
                "NextUploadIdMarker": upload,
            }

    client = Client()
    rows, cursors, summary = native_pages(
        client, "bucket", "prefix/", "multipart", set(identities)
    )
    assert summary["same_key_boundary"] is True
    assert cursors[0] == {"KeyMarker": "prefix/a", "UploadIdMarker": "u1"}
    resumed, _, _ = native_pages(
        client, "bucket", "prefix/", "multipart", set(identities[1:]), start=cursors[0]
    )
    assert resumed == rows[1:]
    assert all(item["MaxUploads"] == 1 for item in calls)


def version_output():
    from tests.support.asset_rustfs import SERVER_COMMIT

    return (
        "\n".join(
            [
                "rustfs 1.0.0",
                "build time   : public",
                "build profile: release",
                "build os     : linux",
                "rust version : public",
                "rust channel : stable",
                "git branch   : release",
                "git commit   : " + SERVER_COMMIT,
                "git tag      : 1.0.0",
                "git status   : clean",
            ]
        )
        + "\n"
    )


def test_version_source_model_empty_branch_one_terminal_lf_is_valid(capsys):
    from tests.support.asset_rustfs import verify_version

    # Independent synthetic long-version fields; this is not recovered stdout.
    output = (
        "rustfs 1.0.0\n"
        "build time   : SYNTHETIC-time\n"
        "build profile: SYNTHETIC-profile\n"
        "build os     : SYNTHETIC-os\n"
        "rust version : SYNTHETIC-compiler\n"
        "rust channel : SYNTHETIC-channel\n"
        "git branch   : \n"
        "git commit   : d47f54bfb2f39f48bd1adda334bd27e151fe85b8\n"
        "git tag      : 1.0.0\n"
        "git status   :\nSYNTHETIC-private-status\n"
    )
    assert verify_version(output) is None
    assert capsys.readouterr() == ("", "")


def test_version_source_model_nonempty_branch_two_terminal_lfs_is_valid(capsys):
    from tests.support.asset_rustfs import verify_version

    # Empty source status plus Clap's one added LF gives two terminal LFs.
    output = (
        "rustfs 1.0.0\n"
        "build time   : SYNTHETIC-time\n"
        "build profile: SYNTHETIC-profile\n"
        "build os     : SYNTHETIC-os\n"
        "rust version : SYNTHETIC-compiler\n"
        "rust channel : SYNTHETIC-channel\n"
        "git branch   : SYNTHETIC-branch\n"
        "git commit   : d47f54bfb2f39f48bd1adda334bd27e151fe85b8\n"
        "git tag      : 1.0.0\n"
        "git status   :\n\n"
    )
    assert verify_version(output) is None
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.replace("build time   :", "build time:"),
        lambda value: value + "\n\n",
        lambda value: value.replace("git tag      : 1.0.0", "git tag      : unknown"),
        lambda value: value + "git commit   : secret\n",
        lambda value: value.replace("public", "\x1bsecret", 1),
    ],
)
def test_version_grammar_refuses_spacing_fallback_duplicates_and_unsafe_output(change):
    from tests.support.asset_rustfs import verify_version

    verify_version(version_output())
    with pytest.raises(RuntimeError, match="version grammar") as caught:
        verify_version(change(version_output()))
    assert "secret" not in str(caught.value)


def test_pinned_server_extraction_does_not_extract_cli_and_is_exclusive(
    tmp_path, monkeypatch
):
    import hashlib

    from tests.support import asset_rustfs

    body = b"fixture-not-an-executable"
    monkeypatch.setattr(asset_rustfs, "SERVER_SIZE", len(body))
    monkeypatch.setattr(asset_rustfs, "SERVER_SHA", hashlib.sha256(body).hexdigest())
    bundle = tmp_path / "release.zip"
    bundle.write_bytes(archive([("rustfs", body), ("rustfs-cli", b"unused")]))
    budget = asset_rustfs.PhaseBudget()
    budget.enter("A")
    target = tmp_path / "rustfs"
    asset_rustfs.extract_server(bundle, target, budget)
    assert target.read_bytes() == body and not (tmp_path / "rustfs-cli").exists()
    with pytest.raises(RuntimeError, match="server identity"):
        asset_rustfs.extract_server(bundle, target, budget)


@pytest.mark.parametrize(
    "members",
    [
        [("rustfs", b"body")],
        [("../rustfs", b"body"), ("rustfs-cli", b"unused")],
        [("rustfs", b"body"), ("rustfs", b"body"), ("rustfs-cli", b"unused")],
    ],
)
def test_server_archive_refuses_missing_traversal_duplicate_members(tmp_path, members):
    from tests.support.asset_rustfs import PhaseBudget, extract_server

    bundle = tmp_path / "release.zip"
    with (
        pytest.warns(UserWarning)
        if len(members) == 3
        else __import__("contextlib").nullcontext()
    ):
        bundle.write_bytes(archive(members))
    budget = PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError):
        extract_server(bundle, tmp_path / "rustfs", budget)
    assert not (tmp_path / "rustfs").exists()


def test_native_admin_read_failure_survives_required_close_failure(monkeypatch):
    import httpx

    from tests.support.asset_rustfs import NativeAdminFailure

    native, _, _, _ = iam_fixture()
    native.request_hook = None
    closed = []

    class Response:
        status_code = 200

        def __init__(self):
            self.headers = {"content-type": "application/json"}

        def iter_bytes(self, size):
            raise httpx.ReadError("private-read-message")

    class Context:
        def __enter__(self):
            return Response()

        def __exit__(self, *args):
            closed.append(True)
            raise OSError("private-close-message")

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Context())
    with pytest.raises(NativeAdminFailure) as caught:
        native.request("bootstrap", "GET", "user-info")
    assert caught.value.phase == "READ"
    assert caught.value.close_failed is True and closed == [True]
    assert "private-" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.invalid/x",
        "https://github.com:444/x",
        "https://user:secret@github.com/x",
        "https://github.com/x#private",
        "file:///private",
        "https://github.com.invalid/x",
    ],
)
def test_artifact_redirects_refuse_other_authority_without_revealing_urls(url):
    from tests.support.asset_rustfs import validate_download_url

    with pytest.raises(RuntimeError) as caught:
        validate_download_url(url)
    assert url not in str(caught.value)


def test_active_fixture_is_rustfs_with_independent_native_credential_shape(tmp_path):
    provider = AssetProvider(tmp_path)
    assert SECURITY_PROFILE == "rustfs-inert-acl-dedicated-bucket-v1"
    assert provider.image_tag.startswith("wso-assets-rustfs:")
    assert set(provider.credentials) == {"bootstrap", "gateway", "cleanup"}
    assert len({access for access, _ in provider.credentials.values()}) == 3
    assert all(
        len(access) == 20 and len(secret) == 40
        for access, secret in provider.credentials.values()
    )


def test_active_control_table_characterizes_native_ownership_and_persisted_pab():
    from tests.support.asset_provider import CONTROL_RESULTS

    assert CONTROL_RESULTS["put_bucket_ownership_controls"] == (501, "NotImplemented")
    assert CONTROL_RESULTS["delete_bucket_ownership_controls"] == (
        501,
        "NotImplemented",
    )
    assert CONTROL_RESULTS["put_public_access_block"] == (403, "AccessDenied")
    assert CONTROL_RESULTS["get_public_access_block"] == (403, "AccessDenied")


def test_native_import_hook_receives_explicit_signed_payload_identity():
    import hashlib
    import hmac

    native, _, _, _ = iam_fixture()
    observed = []

    def request(actor, method, path, query, body, headers, timeout):
        observed.append((actor, method, path, query, body, headers, timeout))
        return 403, "application/xml", b"<Error><Code>AccessDenied</Code></Error>"

    native.request_hook = request
    native.request("gateway", "PUT", "import-iam", body=native.payload)
    actor, method, path, query, body, raw_headers, timeout = observed[0]
    headers = {key.lower(): value for key, value in raw_headers.items()}
    assert (actor, method, path, query, body) == (
        "gateway",
        "PUT",
        "import-iam",
        None,
        native.payload,
    )
    assert headers["content-type"] == "application/zip"
    assert headers["content-length"] == str(len(body))
    assert headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
    assert "Credential=" + "c" * 20 + "/" in headers["authorization"]
    assert "/us-east-1/s3/aws4_request" in headers["authorization"]
    assert "content-length" in headers["authorization"]
    assert "x-amz-content-sha256" in headers["authorization"]
    assert 0 < timeout <= 20
    signed_headers = "content-length;content-type;host;x-amz-content-sha256;x-amz-date"
    assert "SignedHeaders=" + signed_headers + "," in headers["authorization"]
    timestamp = headers["x-amz-date"]
    date = timestamp[:8]
    scope = date + "/us-east-1/s3/aws4_request"
    canonical_headers = (
        f"content-length:{len(body)}\n"
        "content-type:application/zip\n"
        "host:127.0.0.1:1\n"
        f"x-amz-content-sha256:{hashlib.sha256(body).hexdigest()}\n"
        f"x-amz-date:{timestamp}\n"
    )
    canonical_request = "\n".join(
        (
            "PUT",
            "/rustfs/admin/v3/import-iam",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(body).hexdigest(),
        )
    )
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            timestamp,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        )
    )
    key = ("AWS4" + "d" * 40).encode()
    for part in (date, "us-east-1", "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    assert headers["authorization"].endswith("Signature=" + signature)


def pinned_test_archive(tmp_path, monkeypatch, body=b"data-only-server"):
    """Small independent pin data; nothing in this archive is executed."""
    import hashlib

    from tests.support import asset_rustfs

    payload = archive([("rustfs", body), ("rustfs-cli", b"never-extract")])
    monkeypatch.setattr(asset_rustfs, "SERVER_SIZE", len(body))
    monkeypatch.setattr(asset_rustfs, "SERVER_SHA", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(asset_rustfs, "ARCHIVE_SIZE", len(payload))
    monkeypatch.setattr(
        asset_rustfs, "ARCHIVE_SHA", hashlib.sha256(payload).hexdigest()
    )
    path = tmp_path / "input.zip"
    path.write_bytes(payload)
    return asset_rustfs, path, payload, body


def controlled_download(monkeypatch, responses):
    import httpx

    original_client = httpx.Client
    received = []

    def handle(request):
        received.append(str(request.url))
        status, headers, body = responses[len(received) - 1]
        return httpx.Response(status, headers=headers, content=body)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handle), **kwargs
        ),
    )
    return received


def test_official_download_verifies_streamed_redirected_archive_before_server_use(
    tmp_path, monkeypatch
):
    helper, _, payload, body = pinned_test_archive(
        tmp_path, monkeypatch, b"data-only" * 16000
    )
    redirect = "https://release-assets.githubusercontent.com/owned.zip?token=private"
    received = controlled_download(
        monkeypatch, [(302, {"location": redirect}, b""), (200, {}, payload)]
    )
    budget = helper.PhaseBudget()
    budget.enter("A")
    result = helper.download_server(tmp_path, budget)
    assert received == [helper.ARCHIVE_URL, redirect]
    assert result == tmp_path / "rustfs" and result.read_bytes() == body
    assert (tmp_path / "release.zip").read_bytes() == payload
    assert not (tmp_path / "rustfs-cli").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value[:-1],
        lambda value: value + b"x",
        lambda value: b"x" + value[1:],
    ],
)
def test_official_download_refuses_size_or_digest_mismatch_before_extraction(
    tmp_path, monkeypatch, change
):
    helper, _, payload, _ = pinned_test_archive(tmp_path, monkeypatch)
    controlled_download(monkeypatch, [(200, {}, change(payload))])
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="owned official RustFS acquisition"):
        helper.download_server(tmp_path, budget)
    assert not (tmp_path / "rustfs").exists()


def test_official_download_refuses_unapproved_redirect_without_requesting_it(
    tmp_path, monkeypatch
):
    helper, _, _, _ = pinned_test_archive(tmp_path, monkeypatch)
    received = controlled_download(
        monkeypatch, [(302, {"location": "https://private.invalid/secret"}, b"")]
    )
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError) as caught:
        helper.download_server(tmp_path, budget)
    assert received == [helper.ARCHIVE_URL]
    assert "private" not in str(caught.value) and "secret" not in str(caught.value)
    assert not (tmp_path / "release.zip").exists()


def test_official_download_allows_six_redirects_but_never_a_seventh_target(
    tmp_path, monkeypatch
):
    helper, _, _, _ = pinned_test_archive(tmp_path, monkeypatch)
    received = controlled_download(
        monkeypatch,
        [
            (302, {"location": f"https://github.com/release/{index}"}, b"")
            for index in range(7)
        ],
    )
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="owned official RustFS acquisition"):
        helper.download_server(tmp_path, budget)
    assert len(received) == 7 and "https://github.com/release/6" not in received
    assert not (tmp_path / "release.zip").exists()


def test_official_download_exclusive_archive_never_overwrites_existing_bytes(
    tmp_path, monkeypatch
):
    helper, _, payload, _ = pinned_test_archive(tmp_path, monkeypatch)
    (tmp_path / "release.zip").write_bytes(b"owned-existing")
    controlled_download(monkeypatch, [(200, {}, payload)])
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError):
        helper.download_server(tmp_path, budget)
    assert (tmp_path / "release.zip").read_bytes() == b"owned-existing"
    assert not (tmp_path / "rustfs").exists()


@pytest.mark.parametrize("defect", ["size", "hash", "crc"])
def test_server_extraction_checks_independent_size_hash_and_crc(
    tmp_path, monkeypatch, defect
):
    import struct

    helper, source, payload, _ = pinned_test_archive(tmp_path, monkeypatch)
    if defect == "size":
        monkeypatch.setattr(helper, "SERVER_SIZE", 1)
    elif defect == "hash":
        monkeypatch.setattr(helper, "SERVER_SHA", "0" * 64)
    else:
        # ZIP_STORED bytes are changed while the directory's original CRC remains.
        damaged = bytearray(payload)
        name_length, extra_length = struct.unpack_from("<HH", damaged, 26)
        damaged[30 + name_length + extra_length] ^= 1
        source.write_bytes(damaged)
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="server identity") as caught:
        helper.extract_server(source, tmp_path / "rustfs", budget)
    assert "data-only-server" not in str(caught.value)


@pytest.mark.parametrize(
    "mode, system, encrypted",
    [
        (0o120755, 3, False),
        (0o040755, 3, False),
        (0o020755, 3, False),
        (0o100644, 3, False),
        (0o100755, 0, False),
        (0o100755, 3, True),
    ],
)
def test_server_archive_rejects_nonregular_wrong_mode_or_encrypted_members(
    tmp_path, monkeypatch, mode, system, encrypted
):
    import struct

    helper, source, _, _ = pinned_test_archive(tmp_path, monkeypatch)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        for name in ("rustfs", "rustfs-cli"):
            entry = zipfile.ZipInfo(name)
            entry.create_system = system
            entry.external_attr = mode << 16
            bundle.writestr(entry, b"data-only-server")
    payload = bytearray(data.getvalue())
    if encrypted:
        # Mark both local and central-directory records; no encryption is executed.
        struct.pack_into("<H", payload, 6, 1)
        central = payload.index(b"PK\x01\x02")
        struct.pack_into("<H", payload, central + 8, 1)
    source.write_bytes(payload)
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="server identity"):
        helper.extract_server(source, tmp_path / "rustfs", budget)
    assert not (tmp_path / "rustfs").exists()


def test_server_extraction_refuses_existing_link_without_touching_referent(
    tmp_path, monkeypatch
):
    helper, source, _, _ = pinned_test_archive(tmp_path, monkeypatch)
    referent = tmp_path / "kept"
    referent.write_bytes(b"keep")
    target = tmp_path / "rustfs"
    try:
        target.symlink_to(referent)
    except OSError:
        pytest.skip("local OS does not permit creating this test symlink")
    budget = helper.PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="server identity"):
        helper.extract_server(source, target, budget)
    assert target.is_symlink() and referent.read_bytes() == b"keep"


@pytest.mark.parametrize(
    "value",
    [
        lambda text: text.replace("rustfs 1.0.0", "rustfs @d47f54b"),
        lambda text: text.replace(
            "d47f54bfb2f39f48bd1adda334bd27e151fe85b8", "d47f54b"
        ),
        lambda text: text.replace(
            "build time   : public", "build time   : " + "x" * 257
        ),
        lambda text: text.replace("build time   : public", "build time   : "),
        lambda text: text.replace("public", "métadata", 1),
        lambda text: text.replace("\n", "\r\n"),
        lambda text: text.replace("rust channel : stable", "git branch   : stable"),
        lambda text: text + "x" * 16384,
    ],
)
def test_version_refuses_source_fallback_metadata_bounds_and_changed_order(value):
    from tests.support.asset_rustfs import verify_version

    with pytest.raises(RuntimeError, match="version grammar"):
        verify_version(value(version_output()))


def test_version_accepts_optional_lf_and_discards_private_printable_status_tail(capsys):
    from tests.support.asset_rustfs import verify_version

    public = (
        version_output()
        .replace("build time   : public", "build time   : " + "x" * 256)
        .rstrip("\n")
    )
    assert verify_version(public) is None
    assert verify_version(public.encode() + b"\n") is None
    assert (
        verify_version(public + "\n M private/worktree/path\n?? private-file\n") is None
    )
    assert capsys.readouterr() == ("", "")


def test_version_status_tail_uses_whole_output_bound_not_build_metadata_bound(capsys):
    from tests.support.asset_rustfs import verify_version

    output = version_output().replace(
        "git status   : clean", "git status   : " + "private-path/" * 30
    )
    assert verify_version(output) is None
    assert capsys.readouterr() == ("", "")


def literal_version_header(branch="SYNTHETIC-branch"):
    """Independent public pins and synthetic metadata; never actual cold stdout."""
    return (
        "rustfs 1.0.0\n"
        "build time   : SYNTHETIC-time\n"
        "build profile: SYNTHETIC-profile\n"
        "build os     : SYNTHETIC-os\n"
        "rust version : SYNTHETIC-compiler\n"
        "rust channel : SYNTHETIC-channel\n"
        f"git branch   : {branch}\n"
        "git commit   : d47f54bfb2f39f48bd1adda334bd27e151fe85b8\n"
        "git tag      : 1.0.0\n"
        "git status   :"
    )


@pytest.mark.parametrize("branch", ["", "SYNTHETIC-branch"], ids=["empty", "named"])
@pytest.mark.parametrize("terminal_lfs", [0, 1, 2])
@pytest.mark.parametrize(
    "status",
    ["", " SYNTHETIC-inline-status", "\nSYNTHETIC-private-status"],
    ids=["empty-status", "inline-status", "separate-status"],
)
def test_version_literal_field_combinations_accept_only_supported_terminal_lfs(
    branch, terminal_lfs, status, capsys
):
    from tests.support.asset_rustfs import verify_version

    output = literal_version_header(branch) + status + "\n" * terminal_lfs
    assert verify_version(output) is None
    assert verify_version(output.encode("ascii")) is None
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("terminal_lfs", [0, 1, 2])
def test_version_branch_exact_256_byte_boundary_is_valid(terminal_lfs):
    from tests.support.asset_rustfs import verify_version

    output = literal_version_header("x" * 256) + "\n" * terminal_lfs
    assert verify_version(output) is None


@pytest.mark.parametrize("terminal_lfs", [0, 1, 2])
def test_version_whole_exact_16k_byte_boundary_is_valid(terminal_lfs, capsys):
    from tests.support.asset_rustfs import verify_version

    header = literal_version_header("")
    output = header + "S" * (16384 - len(header) - terminal_lfs) + "\n" * terminal_lfs
    assert len(output.encode("ascii")) == 16384
    assert verify_version(output) is None
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("branch", ["", "SYNTHETIC-branch"], ids=["empty", "named"])
@pytest.mark.parametrize("terminal_lfs", [3, 4, 16])
def test_version_three_or_more_terminal_lfs_are_refused(branch, terminal_lfs, capsys):
    from tests.support.asset_rustfs import verify_version

    with pytest.raises(RuntimeError, match="version grammar") as caught:
        verify_version(
            literal_version_header(branch)
            + "\nSYNTHETIC-private-status"
            + "\n" * terminal_lfs
        )
    assert str(caught.value) == "official RustFS version grammar differs"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "required_line",
    [
        "build time   : SYNTHETIC-time",
        "build profile: SYNTHETIC-profile",
        "build os     : SYNTHETIC-os",
        "rust version : SYNTHETIC-compiler",
        "rust channel : SYNTHETIC-channel",
        "git commit   : d47f54bfb2f39f48bd1adda334bd27e151fe85b8",
        "git tag      : 1.0.0",
    ],
    ids=["time", "profile", "os", "compiler", "channel", "commit", "tag"],
)
def test_version_empty_branch_does_not_permit_other_empty_required_fields(
    required_line, capsys
):
    from tests.support.asset_rustfs import verify_version

    prefix = required_line[: required_line.index(":") + 2]
    output = literal_version_header("").replace(required_line, prefix) + "\n\n"
    with pytest.raises(RuntimeError, match="version grammar") as caught:
        verify_version(output)
    assert str(caught.value) == "official RustFS version grammar differs"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "defect",
    [
        "missing-branch",
        "wrong-branch-prefix",
        "short-branch-spacing",
        "branch-order",
        "duplicate-branch",
        "duplicate-time",
        "overlong-branch",
        "wrong-display",
        "wrong-commit",
        "wrong-tag",
        "missing-status",
        "whole-overflow",
        "control",
        "carriage-return",
        "nonascii",
        "invalid-utf8",
        "short-only",
    ],
)
def test_version_branch_exception_preserves_closed_grammar_and_identity(defect, capsys):
    from tests.support.asset_rustfs import verify_version

    output = literal_version_header("") + "\nSYNTHETIC-private-status\n\n"
    if defect == "missing-branch":
        output = output.replace("git branch   : \n", "")
    elif defect == "wrong-branch-prefix":
        output = output.replace("git branch   : ", "git branches : ")
    elif defect == "short-branch-spacing":
        output = output.replace("git branch   : ", "git branch: ")
    elif defect == "branch-order":
        output = output.replace(
            "rust channel : SYNTHETIC-channel\ngit branch   : \n",
            "git branch   : \nrust channel : SYNTHETIC-channel\n",
        )
    elif defect == "duplicate-branch":
        output = output[:-2] + "\ngit branch   : SYNTHETIC-duplicate\n\n"
    elif defect == "duplicate-time":
        output = output[:-2] + "\nbuild time   : SYNTHETIC-duplicate\n\n"
    elif defect == "overlong-branch":
        output = output.replace(
            "git branch   : \n", "git branch   : " + "x" * 257 + "\n"
        )
    elif defect == "wrong-display":
        output = output.replace("rustfs 1.0.0", "rustfs 1.0.1")
    elif defect == "wrong-commit":
        output = output.replace("d47f54bfb2f39f48bd1adda334bd27e151fe85b8", "0" * 40)
    elif defect == "wrong-tag":
        output = output.replace("git tag      : 1.0.0", "git tag      : 1.0.1")
    elif defect == "missing-status":
        output = output.replace("git status   :\n", "")
    elif defect == "whole-overflow":
        header = literal_version_header("")
        output = header + "S" * (16385 - len(header) - 2) + "\n\n"
    elif defect == "control":
        output = output.replace("SYNTHETIC-private-status", "SYNTHETIC-\x00-status")
    elif defect == "carriage-return":
        output = output.replace("\n", "\r\n")
    elif defect == "nonascii":
        output = output.replace("SYNTHETIC-private-status", "SYNTHETIC-é-status")
    elif defect == "invalid-utf8":
        output = output.encode("ascii").replace(
            b"SYNTHETIC-private-status", b"SYNTHETIC-\xff-status"
        )
    else:
        output = "rustfs 1.0.0\n"
    with pytest.raises(RuntimeError, match="version grammar") as caught:
        verify_version(output)
    assert str(caught.value) == "official RustFS version grammar differs"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "shape", ["bytearray", "memoryview", "none", "number", "list", "dict"]
)
def test_version_only_native_string_or_bytes_shapes_are_accepted(shape, capsys):
    from tests.support.asset_rustfs import verify_version

    encoded = (literal_version_header("") + "\n\n").encode("ascii")
    output = {
        "bytearray": bytearray(encoded),
        "memoryview": memoryview(encoded),
        "none": None,
        "number": 123,
        "list": [encoded],
        "dict": {"version": encoded},
    }[shape]
    with pytest.raises(RuntimeError, match="version grammar") as caught:
        verify_version(output)
    assert str(caught.value) == "official RustFS version grammar differs"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "payload",
    [
        b'"\xff"',
        b'{"x":{"x":1,"x":2}}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b" " * 65536 + b"0",
    ],
    ids=[
        "nonutf8",
        "nested-duplicate",
        "infinity",
        "negative-infinity",
        "wire-overflow",
    ],
)
def test_native_json_refuses_nested_duplicate_nonutf8_nonfinite_and_wire_overflow(
    payload,
):
    from tests.support.asset_rustfs import strict_json

    with pytest.raises(RuntimeError, match="native JSON") as caught:
        strict_json(payload)
    assert str(caught.value) == "invalid bounded native JSON"


def test_native_json_accepts_exact_wire_and_depth_boundaries():
    from tests.support.asset_rustfs import strict_json

    assert strict_json(b" " * 65535 + b"0") == 0
    assert strict_json(b"[" * 16 + b"0" + b"]" * 16) == [
        [[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]
    ]


def native_defaults():
    """Literal pinned templates, independent of the production defaults factory."""
    return {
        "readwrite": {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:*"], "Resource": ["arn:aws:s3:::*"]},
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "readonly": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetBucketLocation",
                        "s3:GetObject",
                        "s3:GetBucketQuota",
                    ],
                    "Resource": ["arn:aws:s3:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "writeonly": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:PutObject"],
                    "Resource": ["arn:aws:s3:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "diagnostics": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "admin:Profiling",
                        "admin:ServerTrace",
                        "admin:ConsoleLog",
                        "admin:ServerInfo",
                        "admin:TopLocksInfo",
                        "admin:OBDInfo",
                        "admin:Prometheus",
                        "admin:BandwidthMonitor",
                    ],
                    "Resource": ["arn:aws:s3:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "consoleAdmin": {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["admin:*"]},
                {"Effect": "Allow", "Action": ["kms:*"]},
                {"Effect": "Allow", "Action": ["s3:*"], "Resource": ["arn:aws:s3:::*"]},
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "KMSKeyAdministrator": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "kms:DescribeKey",
                        "kms:ListKeys",
                        "kms:EnableKey",
                        "kms:DisableKey",
                        "kms:RotateKey",
                        "kms:DeleteKey",
                    ],
                    "Resource": ["arn:aws:kms:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "KMSKeyUser": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"],
                    "Resource": ["arn:aws:kms:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
        "KMSAuditor": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["kms:DescribeKey", "kms:ListKeys"],
                    "Resource": ["arn:aws:kms:::*"],
                },
                {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
            ],
        },
    }


def literal_policy_sets(policy):
    """Compare ordered native sets without changing or deduplicating wire strings."""
    result = deepcopy(policy)
    for statement in result["Statement"]:
        for name in ("Action", "Resource"):
            if name in statement:
                value = statement[name]
                statement[name] = sorted([value] if type(value) is str else value)
    result["Statement"].sort(
        key=lambda statement: json.dumps(statement, sort_keys=True)
    )
    return result


def test_pinned_native_diagnostics_matches_full_literal_wire_policy():
    from tests.support.asset_rustfs import builtin_policies

    expected = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "admin:Profiling",
                    "admin:ServerTrace",
                    "admin:ConsoleLog",
                    "admin:ServerInfo",
                    "admin:TopLocksInfo",
                    "admin:OBDInfo",
                    "admin:Prometheus",
                    "admin:BandwidthMonitor",
                ],
                "Resource": ["arn:aws:s3:::*"],
            },
            {"Effect": "Allow", "Action": ["sts:AssumeRole"]},
        ],
    }
    assert literal_policy_sets(
        builtin_policies()["diagnostics"]
    ) == literal_policy_sets(expected)


def test_source_modeled_complete_native_export_snapshot_is_accepted(capsys):
    from tests.support.asset_rustfs import export_maps

    native, calls, _, maps = iam_fixture()
    # All eight source-defined defaults and seven maps are synthetic test inputs.
    decoded = export_maps(export_archive(maps))
    assert set(decoded) == {
        "policies",
        "users",
        "groups",
        "svcaccts",
        "user_mappings",
        "group_mappings",
        "stsuser_mappings",
    }
    assert set(decoded["policies"]) == {
        "readwrite",
        "readonly",
        "writeonly",
        "diagnostics",
        "consoleAdmin",
        "KMSKeyAdministrator",
        "KMSKeyUser",
        "KMSAuditor",
        "wso-gateway",
        "wso-maintenance",
    }
    snapshot = json.loads(native.snapshot())
    assert set(snapshot) == {
        "export",
        "gateway",
        "cleanup",
        "wso-gateway",
        "wso-maintenance",
    }
    assert snapshot["export"]["users"] == {
        "c" * 20: {"secretKey": "d" * 40, "status": "enabled"},
        "e" * 20: {"secretKey": "f" * 40, "status": "enabled"},
    }
    assert calls == [
        ("bootstrap", "GET", "export-iam"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "info-canned-policy"),
        ("bootstrap", "GET", "info-canned-policy"),
    ]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "default",
    [
        "readwrite",
        "readonly",
        "writeonly",
        "diagnostics",
        "consoleAdmin",
        "KMSKeyAdministrator",
        "KMSKeyUser",
        "KMSAuditor",
    ],
)
def test_pinned_native_default_templates_have_independent_complete_semantics(default):
    from tests.support.asset_rustfs import builtin_policies

    actual = builtin_policies()
    assert set(actual) == {
        "readwrite",
        "readonly",
        "writeonly",
        "diagnostics",
        "consoleAdmin",
        "KMSKeyAdministrator",
        "KMSKeyUser",
        "KMSAuditor",
    }
    assert literal_policy_sets(actual[default]) == literal_policy_sets(
        native_defaults()[default]
    )


@pytest.mark.parametrize(
    "native_action, old_alias",
    [
        ("admin:ServerTrace", "admin:Trace"),
        ("admin:TopLocksInfo", "admin:TopLocks"),
        ("admin:OBDInfo", "admin:HealthInfo"),
    ],
    ids=["trace-alias", "locks-alias", "health-alias"],
)
def test_native_diagnostics_each_old_alias_alone_is_refused(
    native_action, old_alias, capsys
):
    native, calls, _, maps = iam_fixture()
    actions = maps["policies"]["diagnostics"]["Statement"][0]["Action"]
    actions[actions.index(native_action)] = old_alias
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition, caught.value.status) == (
        "EXPORT",
        "EXPECTED_STATE",
        None,
    )
    assert calls == [
        ("bootstrap", "GET", "export-iam"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "info-canned-policy"),
        ("bootstrap", "GET", "info-canned-policy"),
    ]
    assert "admin:" not in str(caught.value)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "defect",
    [
        "missing-action",
        "extra-action",
        "duplicate-action",
        "resource",
        "condition",
        "sts-resource",
        "sts-action",
        "extra-statement",
        "version",
        "other-default",
        "unknown-ID",
        "unknown-NotAction",
        "unknown-NotResource",
        "unknown-Principal",
    ],
)
def test_native_diagnostics_complete_tree_changes_are_refused(defect, capsys):
    native, calls, _, maps = iam_fixture()
    policy = maps["policies"]["diagnostics"]
    statement = policy["Statement"][0]
    if defect == "missing-action":
        statement["Action"].remove("admin:Profiling")
    elif defect == "extra-action":
        statement["Action"].append("admin:*")
    elif defect == "duplicate-action":
        statement["Action"].append("admin:ServerTrace")
    elif defect == "resource":
        statement["Resource"] = ["arn:aws:s3:::unexpected/*"]
    elif defect == "condition":
        statement["Condition"] = {"StringLike": {"s3:prefix": ["unexpected/*"]}}
    elif defect == "sts-resource":
        policy["Statement"][1]["Resource"] = ["arn:aws:s3:::*"]
    elif defect == "sts-action":
        policy["Statement"][1]["Action"] = ["sts:*"]
    elif defect == "extra-statement":
        policy["Statement"].append({"Effect": "Allow", "Action": ["kms:*"]})
    elif defect == "version":
        policy["Version"] = "2008-10-17"
    elif defect == "other-default":
        maps["policies"]["diagnostics"] = native_defaults()["readonly"]
    elif defect == "unknown-ID":
        policy["ID"] = "SYNTHETIC-id"
    else:
        statement[defect.removeprefix("unknown-")] = (
            [] if defect != "unknown-Principal" else {}
        )
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition, caught.value.status) == (
        "EXPORT",
        "EXPECTED_STATE",
        None,
    )
    assert len(calls) == 5 and all(method == "GET" for _, method, _ in calls)
    assert "unexpected" not in str(caught.value) and "SYNTHETIC" not in str(
        caught.value
    )
    assert capsys.readouterr() == ("", "")


def test_source_modeled_native_defaults_ignore_only_valid_ordering():
    native, _, _, maps = iam_fixture()
    before = native.snapshot()
    for name in (
        "readwrite",
        "readonly",
        "writeonly",
        "diagnostics",
        "consoleAdmin",
        "KMSKeyAdministrator",
        "KMSKeyUser",
        "KMSAuditor",
    ):
        policy = maps["policies"][name]
        for statement in policy["Statement"]:
            for field in ("Action", "Resource"):
                if field in statement:
                    statement[field].reverse()
        policy["Statement"].reverse()
    maps["policies"] = dict(reversed(list(maps["policies"].items())))
    assert native.snapshot() == before


def export_archive(maps):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, value in maps.items():
            entry = zipfile.ZipInfo(f"iam-assets/{name}.json")
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            bundle.writestr(entry, json.dumps(value, separators=(",", ":")).encode())
    return output.getvalue()


def test_native_import_zip_has_exact_owned_documents_users_bindings_and_no_root():
    native, _, _, _ = iam_fixture()
    with zipfile.ZipFile(io.BytesIO(native.payload)) as bundle:
        assert len(bundle.infolist()) == 3
        assert all(entry.external_attr >> 16 == 0o100600 for entry in bundle.infolist())
        assert json.loads(bundle.read("iam-assets/policies.json")) == {
            "wso-gateway": {"Version": "2012-10-17", "Statement": []},
            "wso-maintenance": {"Version": "2012-10-17", "Statement": []},
        }
        assert json.loads(bundle.read("iam-assets/users.json")) == {
            "c" * 20: {"secretKey": "d" * 40, "status": "enabled"},
            "e" * 20: {"secretKey": "f" * 40, "status": "enabled"},
        }
        assert json.loads(bundle.read("iam-assets/user_mappings.json")) == {
            "c" * 20: {
                "version": 1,
                "policy": "wso-gateway",
                "updatedAt": "2026-10-01T00:00:00Z",
            },
            "e" * 20: {
                "version": 1,
                "policy": "wso-maintenance",
                "updatedAt": "2026-10-01T00:00:00Z",
            },
        }


@pytest.mark.parametrize(
    "access, secret",
    [
        ("a" * 19, "b" * 40),
        ("a" * 21, "b" * 40),
        ("a" * 20, "b" * 39),
        ("a" * 20, "b" * 41),
        ("A" * 20, "b" * 40),
        ("a" * 20, "G" * 40),
        ("a" * 19 + "\n", "b" * 40),
        ("a" * 19 + "=", "b" * 40),
        ("a" * 20, "b" * 39 + " "),
    ],
    ids=[
        "short-access",
        "long-access",
        "short-secret",
        "long-secret",
        "uppercase-access",
        "nonhex-secret",
        "newline",
        "reserved",
        "space",
    ],
)
def test_native_import_refuses_invalid_fixture_credentials_before_zip_write(
    access, secret
):
    from tests.support.asset_rustfs import import_payload

    native, _, _, _ = iam_fixture()
    identities = {**native.identities, "gateway": (access, secret)}
    with pytest.raises(RuntimeError, match="credentials") as caught:
        import_payload(identities, native.policies)
    assert secret not in str(caught.value)


def test_native_import_refuses_access_identity_collision():
    from tests.support.asset_rustfs import import_payload

    native, _, _, _ = iam_fixture()
    identities = {**native.identities, "gateway": ("a" * 20, "d" * 40)}
    with pytest.raises(RuntimeError, match="credentials"):
        import_payload(identities, native.policies)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "extra",
        "duplicate",
        "encrypted",
        "symlink",
        "malformed-json",
        "expanded-overflow",
        "wire-overflow",
    ],
)
def test_native_export_refuses_archive_topology_and_bounded_member_violations(defect):
    import struct
    from contextlib import nullcontext

    from tests.support.asset_rustfs import export_maps

    _, _, _, maps = iam_fixture()
    if defect == "missing":
        del maps["groups"]
    elif defect == "extra":
        maps["extra"] = {}
    elif defect == "expanded-overflow":
        maps["groups"] = {"large": "x" * 65536}
    payload = export_archive(maps)
    if defect == "wire-overflow":
        payload += b"x" * 65536
    elif defect in {
        "duplicate",
        "encrypted",
        "symlink",
        "malformed-json",
        "expanded-overflow",
    }:
        if defect in {"encrypted", "symlink"}:
            changed = bytearray(payload)
            central = changed.index(b"PK\x01\x02")
            struct.pack_into(
                "<H" if defect == "encrypted" else "<I",
                changed,
                central + (8 if defect == "encrypted" else 38),
                1 if defect == "encrypted" else 0o120600 << 16,
            )
            payload = bytes(changed)
        else:
            output = io.BytesIO()
            with (
                pytest.warns(UserWarning) if defect == "duplicate" else nullcontext(),
                zipfile.ZipFile(
                    output, "w", compression=zipfile.ZIP_DEFLATED
                ) as bundle,
                zipfile.ZipFile(io.BytesIO(payload)) as original,
            ):
                for entry in original.infolist():
                    body = original.read(entry)
                    if (
                        defect == "malformed-json"
                        and entry.filename == "iam-assets/users.json"
                    ):
                        body = b'{"secretKey":"private","secretKey":"private"}'
                    bundle.writestr(entry, body)
                if defect == "duplicate":
                    bundle.writestr(original.infolist()[0], b"{}")
            payload = output.getvalue()
    with pytest.raises(RuntimeError, match="native IAM export shape") as caught:
        export_maps(payload)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "default",
    [
        "readwrite",
        "readonly",
        "writeonly",
        "diagnostics",
        "consoleAdmin",
        "KMSKeyAdministrator",
        "KMSKeyUser",
        "KMSAuditor",
    ],
)
def test_native_snapshot_requires_full_semantics_of_each_unbound_default(default):
    native, calls, _, maps = iam_fixture()
    maps["policies"] = {**native_defaults(), **native.policies}
    native.snapshot()
    maps["policies"][default]["Statement"][0]["Action"] = "s3:*"
    if default == "readwrite":
        maps["policies"][default]["Statement"][0]["Resource"] = "arn:aws:s3:::different"
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "EXPORT",
        "EXPECTED_STATE",
    )
    assert len(calls) == 10


@pytest.mark.parametrize(
    "defect",
    [
        "root-user",
        "secret",
        "disabled",
        "extra-user-field",
        "missing-user",
        "extra-policy",
        "missing-default",
        "binding-policy",
        "binding-bool",
        "binding-null-time",
        "binding-extra",
        "extra-binding",
        "groups",
        "svcaccts",
        "group_mappings",
        "stsuser_mappings",
    ],
)
def test_native_snapshot_rejects_incomplete_or_excess_expected_state(defect):
    native, calls, _, maps = iam_fixture()
    maps["policies"] = {**native_defaults(), **native.policies}
    if defect == "root-user":
        maps["users"]["a" * 20] = {"secretKey": "b" * 40, "status": "enabled"}
    elif defect == "secret":
        maps["users"]["c" * 20]["secretKey"] = "wrong-private-secret"
    elif defect == "disabled":
        maps["users"]["c" * 20]["status"] = "disabled"
    elif defect == "extra-user-field":
        maps["users"]["c" * 20]["updatedAt"] = "2026-10-01T00:00:00Z"
    elif defect == "missing-user":
        del maps["users"]["c" * 20]
    elif defect == "extra-policy":
        maps["policies"]["foreign"] = {"Version": "2012-10-17", "Statement": []}
    elif defect == "missing-default":
        del maps["policies"]["readonly"]
    elif defect == "binding-policy":
        maps["user_mappings"]["c" * 20]["policy"] = "wso-gateway,consoleAdmin"
    elif defect == "binding-bool":
        maps["user_mappings"]["c" * 20]["version"] = True
    elif defect == "binding-null-time":
        maps["user_mappings"]["c" * 20]["updatedAt"] = None
    elif defect == "binding-extra":
        maps["user_mappings"]["c" * 20]["extra"] = "private"
    elif defect == "extra-binding":
        maps["user_mappings"]["a" * 20] = deepcopy(maps["user_mappings"]["c" * 20])
    else:
        maps[defect]["unexpected"] = {}
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "EXPORT",
        "EXPECTED_STATE",
    )
    assert len(calls) == 5 and all(method == "GET" for _, method, _ in calls)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "date",
    [
        [2024, 366, 23, 59, 59, 999999999, 0, 0, 0],
        "2026-10-01 00:00:00.123456789 +00:00:00",
    ],
)
def test_native_policy_date_accepts_closed_native_utc_encodings_without_coercion(date):
    from tests.support.asset_rustfs import utc_date

    assert utc_date(date) == date
    assert type(utc_date(date)) is type(date)


@pytest.mark.parametrize(
    "date",
    [
        None,
        "2026-10-01T00:00:00Z",
        [2026, 366, 0, 0, 0, 0, 0, 0, 0],
        [2026, 274, True, 0, 0, 0, 0, 0, 0],
        [2026, 274, 0.0, 0, 0, 0, 0, 0, 0],
        [2026, 274, 0, 0, 0, 1000000000, 0, 0, 0],
        [2026, 274, 24, 0, 0, 0, 0, 0, 0],
        [2026, 274, 0, 0, 60, 0, 0, 0, 0],
        [2026, 274, 0, 0, 0, 0, 1, 0, 0],
        [2026, 274, 0, 0, 0, 0, 0, 0],
        "2026-02-30 00:00:00.0 +00:00:00",
        "2026-10-01 00:00:00.1234567890 +00:00:00",
        "2026-10-01 00:00:00.0 +01:00:00",
        "2026-10-01 00:00:00.0 +00:00:00\n",
    ],
    ids=[
        "null",
        "rfc3339",
        "nonleap-ordinal",
        "bool",
        "float",
        "nanosecond",
        "hour",
        "second",
        "offset",
        "length",
        "calendar",
        "precision",
        "text-offset",
        "newline",
    ],
)
def test_native_policy_date_refuses_wrong_types_calendar_precision_and_offset(date):
    from tests.support.asset_rustfs import utc_date

    with pytest.raises(RuntimeError, match="policy mutation date"):
        utc_date(date)


def test_native_snapshot_canonicalizes_validated_unordered_policy_sets():
    native, _, _, maps = iam_fixture()
    owned = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": ["arn:aws:s3:::one/*", "arn:aws:s3:::two/*"],
                "Condition": {"StringLike": {"s3:prefix": ["a/*", "b/*"]}},
            },
            {
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": "arn:aws:s3:::one",
            },
        ],
    }
    native.policies["wso-gateway"] = deepcopy(owned)
    maps["policies"]["wso-gateway"] = deepcopy(owned)
    before = native.snapshot()
    statements = maps["policies"]["wso-gateway"]["Statement"]
    statements[0]["Action"].reverse()
    statements[0]["Resource"].reverse()
    statements[0]["Condition"]["StringLike"]["s3:prefix"].reverse()
    statements.reverse()
    assert native.snapshot() == before


@pytest.mark.parametrize("field", ["Statement", "Action", "Resource", "Condition"])
def test_native_snapshot_does_not_normalize_away_duplicate_policy_semantics(field):
    native, _, _, maps = iam_fixture()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": ["arn:aws:s3:::one/*"],
                "Condition": {"StringLike": {"s3:prefix": ["a/*"]}},
            }
        ],
    }
    native.policies["wso-gateway"] = deepcopy(policy)
    maps["policies"]["wso-gateway"] = deepcopy(policy)
    if field == "Statement":
        maps["policies"]["wso-gateway"][field] *= 2
    elif field == "Condition":
        maps["policies"]["wso-gateway"]["Statement"][0][field]["StringLike"][
            "s3:prefix"
        ] *= 2
    else:
        maps["policies"]["wso-gateway"]["Statement"][0][field] *= 2
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "EXPORT",
        "EXPECTED_STATE",
    )


def test_native_policy_date_text_requires_printable_ascii_digits():
    from tests.support.asset_rustfs import utc_date

    with pytest.raises(RuntimeError, match="policy mutation date"):
        utc_date("٢٠٢٦-10-01 00:00:00.0 +00:00:00")


def test_server_extraction_refuses_write_returning_after_immutable_phase_cutoff(
    tmp_path, monkeypatch
):
    helper, source, _, _ = pinned_test_archive(tmp_path, monkeypatch)
    now = [0.0]
    budget = helper.PhaseBudget(clock=lambda: now[0])
    budget.enter("A")
    original_fdopen = helper.os.fdopen

    class Output:
        def __init__(self, descriptor, mode):
            self.file = original_fdopen(descriptor, mode)

        def __enter__(self):
            self.file.__enter__()
            return self

        def write(self, data):
            result = self.file.write(data)
            now[0] = 360.0
            return result

        def __exit__(self, *args):
            return self.file.__exit__(*args)

    monkeypatch.setattr(helper.os, "fdopen", Output)
    with pytest.raises(RuntimeError, match="server identity"):
        helper.extract_server(source, tmp_path / "rustfs", budget)


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "disabled"),
        ("policyName", "consoleAdmin"),
        ("updatedAt", None),
        ("updatedAt", "2026-10-01T00:00:01Z"),
        ("memberOf", ["foreign"]),
        ("memberOf", {}),
        ("secretKey", "private-secret"),
        ("userAuthInfo", {}),
    ],
    ids=[
        "disabled",
        "wrong-policy",
        "null-time",
        "inconsistent-time",
        "membership",
        "membership-type",
        "secret-field",
        "auth-field",
    ],
)
def test_native_snapshot_rejects_user_metadata_shape_and_cross_inconsistency(
    field, value
):
    native, calls, _, _ = iam_fixture()
    original = native.request_hook

    def request(actor, method, path, query, body, headers, timeout):
        status, mime, payload = original(
            actor, method, path, query, body, headers, timeout
        )
        if path == "user-info" and query["accessKey"] == "c" * 20:
            result = json.loads(payload)
            result[field] = value
            payload = json.dumps(result).encode()
        return status, mime, payload

    native.request_hook = request
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "USER_GATEWAY",
        "METADATA" if field == "updatedAt" else "EXPECTED_STATE",
    )
    assert len(calls) == 5 and "private-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("policy_name", "foreign"),
        ("create_date", None),
        ("update_date", None),
        ("create_date", "2026-10-01T00:00:00Z"),
        ("extra", "private-metadata"),
        (
            "policy",
            {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "s3:*"}],
            },
        ),
    ],
    ids=[
        "wrong-name",
        "null-create",
        "null-update",
        "wrong-encoding",
        "extra-field",
        "inconsistent-policy",
    ],
)
def test_native_snapshot_rejects_policy_information_shape_and_cross_inconsistency(
    field, value
):
    native, calls, _, _ = iam_fixture()
    original = native.request_hook

    def request(actor, method, path, query, body, headers, timeout):
        status, mime, payload = original(
            actor, method, path, query, body, headers, timeout
        )
        if path == "info-canned-policy" and query["name"] == "wso-gateway":
            result = json.loads(payload)
            result[field] = value
            payload = json.dumps(result).encode()
        return status, mime, payload

    native.request_hook = request
    with pytest.raises(NativeSnapshotFailure) as caught:
        native.snapshot()
    assert (caught.value.component, caught.value.condition) == (
        "POLICY_GATEWAY",
        "METADATA" if field in {"create_date", "update_date"} else "EXPECTED_STATE",
    )
    assert len(calls) == 5 and "private-metadata" not in str(caught.value)


def test_native_no_effect_refuses_mapping_metadata_only_rewrite():
    native, calls, _, maps = iam_fixture()
    original = native.request_hook

    def request(actor, method, path, query, body, headers, timeout):
        result = original(actor, method, path, query, body, headers, timeout)
        if method == "PUT":
            maps["user_mappings"]["c" * 20]["updatedAt"] = (
                "2026-10-01T00:00:00.000000001Z"
            )
        elif path == "user-info" and query["accessKey"] == "c" * 20:
            status, mime, payload = result
            value = json.loads(payload)
            value["updatedAt"] = maps["user_mappings"]["c" * 20]["updatedAt"]
            result = status, mime, json.dumps(value).encode()
        return result

    native.request_hook = request
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
    ) == ("GATEWAY", "IAM_AFTER", "EXPORT", "METADATA")
    assert len(calls) == 11 and sum(method == "PUT" for _, method, _ in calls) == 1


@pytest.mark.parametrize(
    "defect",
    ["secret", "status", "owned-policy", "binding", "default", "additional-entity"],
)
def test_native_admin_nominal_denial_with_changed_complete_state_fails(defect):
    native, calls, _, maps = iam_fixture()
    maps["policies"] = deepcopy(maps["policies"])
    original = native.request_hook

    def request(actor, method, path, query, body, headers, timeout):
        result = original(actor, method, path, query, body, headers, timeout)
        if method == "PUT":
            if defect == "secret":
                maps["users"]["c" * 20]["secretKey"] = "changed-private"
            elif defect == "status":
                maps["users"]["c" * 20]["status"] = "disabled"
            elif defect == "owned-policy":
                maps["policies"]["wso-gateway"]["Statement"] = [
                    {"Effect": "Allow", "Action": "s3:*"}
                ]
            elif defect == "binding":
                maps["user_mappings"]["c" * 20]["policy"] = "consoleAdmin"
            elif defect == "default":
                maps["policies"]["readonly"]["Statement"][0]["Action"] = "s3:*"
            else:
                maps["groups"]["foreign"] = {}
        return result

    native.request_hook = request
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
    ) == ("GATEWAY", "IAM_AFTER", "EXPORT", "EXPECTED_STATE")
    assert len(calls) == 11 and sum(method == "PUT" for _, method, _ in calls) == 1
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        (200, "application/xml", b"<Error><Code>AccessDenied</Code></Error>"),
        (403, "application/json", b'{"Code":"AccessDenied"}'),
        (403, "application/xml", b"<Error><Code>Other</Code></Error>"),
        (
            403,
            "application/xml",
            b"<!DOCTYPE Error><Error><Code>AccessDenied</Code></Error>",
        ),
        (403, "application/xml", b"private-malformed"),
    ],
    ids=["wrong-status", "wrong-mime", "wrong-code", "doctype", "malformed"],
)
def test_native_admin_invalid_denial_still_finishes_safe_after_snapshot(response):
    native, calls, _, _ = iam_fixture()
    original = native.request_hook

    def request(actor, method, path, query, body, headers, timeout):
        result = original(actor, method, path, query, body, headers, timeout)
        return response if method == "PUT" else result

    native.request_hook = request
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
        caught.value.status,
    ) == (
        "GATEWAY",
        "IAM_IMPORT",
        "IMPORT_STATUS",
        "HTTP_STATUS" if response[0] == 200 else "SHAPE",
        response[0],
    )
    assert len(calls) == 11 and calls[-1] == ("bootstrap", "GET", "info-canned-policy")
    assert "private" not in str(caught.value)


def test_native_snapshot_uses_only_fixed_owned_read_routes_and_queries():
    native, _, _, _ = iam_fixture()
    original = native.request_hook
    observed = []

    def request(actor, method, path, query, body, headers, timeout):
        observed.append((actor, method, path, query, body))
        return original(actor, method, path, query, body, headers, timeout)

    native.request_hook = request
    native.snapshot()
    assert observed == [
        ("bootstrap", "GET", "export-iam", None, b""),
        ("bootstrap", "GET", "user-info", {"accessKey": "c" * 20}, b""),
        ("bootstrap", "GET", "user-info", {"accessKey": "e" * 20}, b""),
        ("bootstrap", "GET", "info-canned-policy", {"name": "wso-gateway"}, b""),
        ("bootstrap", "GET", "info-canned-policy", {"name": "wso-maintenance"}, b""),
    ]


def test_native_signed_http_uses_fixed_url_query_no_redirect_or_ambient_authority(
    monkeypatch, capsys
):
    import httpx

    native, _, _, _ = iam_fixture()
    native.request_hook = None
    observed = []
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-private")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-private-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-private-token")
    monkeypatch.setenv("HTTP_PROXY", "http://ambient.invalid:1")

    class Context:
        def __enter__(self):
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"{}"
            )

        def __exit__(self, *args):
            return False

    def stream(method, url, **kwargs):
        observed.append((method, url, kwargs))
        return Context()

    monkeypatch.setattr(httpx, "stream", stream)
    assert native.request(
        "bootstrap", "GET", "user-info", query={"accessKey": "c" * 20}
    ) == (200, "application/json", b"{}")
    method, url, arguments = observed[0]
    assert (
        method == "GET"
        and url == "http://127.0.0.1:1/rustfs/admin/v3/user-info?accessKey=" + "c" * 20
    )
    assert arguments["trust_env"] is False and arguments["follow_redirects"] is False
    assert arguments["content"] == b"" and 0 < arguments["timeout"] <= 20
    headers = {key.lower(): value for key, value in arguments["headers"].items()}
    assert "Credential=" + "a" * 20 + "/" in headers["authorization"]
    assert "x-amz-security-token" not in headers
    assert headers["content-length"] == "0"
    assert (
        headers["x-amz-content-sha256"]
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("late", [20.0, 20.001])
def test_native_admin_hook_return_at_or_after_per_call_cutoff_is_refused(
    monkeypatch, late
):
    from tests.support import asset_rustfs

    native, _, _, _ = iam_fixture()
    now = [0.0]
    native.budget = asset_rustfs.PhaseBudget(clock=lambda: now[0])
    native.budget.enter("A")
    monkeypatch.setattr(asset_rustfs.time, "monotonic", lambda: now[0])

    def request(*args):
        now[0] = late
        return 200, "application/json", b"{}"

    native.request_hook = request
    with pytest.raises(asset_rustfs.NativeAdminFailure) as caught:
        native.request("bootstrap", "GET", "user-info")
    assert caught.value.phase == "REQUEST"


def test_native_admin_call_cap_is_clipped_to_remaining_phase_without_renewal(
    monkeypatch,
):
    from tests.support import asset_rustfs

    native, _, _, _ = iam_fixture()
    now = [0.0]
    native.budget = asset_rustfs.PhaseBudget(clock=lambda: now[0])
    native.budget.enter("A")
    now[0] = 359.5
    monkeypatch.setattr(asset_rustfs.time, "monotonic", lambda: now[0])
    seen = []

    def request(*args):
        seen.append(args[-1])
        now[0] = 360.0
        return 200, "application/json", b"{}"

    native.request_hook = request
    with pytest.raises(asset_rustfs.NativeAdminFailure):
        native.request("bootstrap", "GET", "user-info")
    assert seen == [0.5]
    with pytest.raises(RuntimeError, match="phase cutoff"):
        native.budget.enter("B")


def test_phase_budget_early_success_keeps_later_phases_within_their_own_caps():
    from tests.support.asset_rustfs import PhaseBudget

    now = [0.0]
    budget = PhaseBudget(clock=lambda: now[0])
    budget.enter("A")
    now[0] = 1.0
    budget.enter("B")
    assert budget.allowance(360) == 180
    now[0] = 2.0
    budget.enter("C")
    assert budget.allowance(360) == 180
    now[0] = 181.5
    assert budget.allowance(20) == 0.5
    now[0] = 182.0
    with pytest.raises(RuntimeError, match="phase cutoff"):
        budget.allowance(20)


def test_phase_budget_late_starts_are_clipped_to_original_outer_cutoff():
    from tests.support.asset_rustfs import PhaseBudget

    now = [0.0]
    budget = PhaseBudget(clock=lambda: now[0])
    now[0] = 200.0
    budget.enter("A")
    now[0] = 559.0
    budget.enter("B")
    assert budget.allowance(180) == 161
    now[0] = 719.0
    budget.enter("C")
    assert budget.allowance(180) == 1
    now[0] = 720.0
    with pytest.raises(RuntimeError, match="phase cutoff"):
        budget.check()


@pytest.mark.parametrize("phase", ["A", "C", "cleanup", None])
def test_phase_budget_refuses_repeated_or_out_of_order_transition(phase):
    from tests.support.asset_rustfs import PhaseBudget

    budget = PhaseBudget()
    budget.enter("A")
    with pytest.raises(RuntimeError, match="phase transition"):
        budget.enter(phase)


def import_result():
    empty = {
        "policies": [],
        "users": [],
        "groups": [],
        "serviceAccounts": [],
        "userPolicies": [],
        "groupPolicies": [],
        "stsPolicies": [],
    }
    result = {
        section: deepcopy(empty)
        for section in ("skipped", "removed", "added", "failed")
    }
    result["added"].update(
        {
            "policies": ["wso-gateway", "wso-maintenance"],
            "users": ["c" * 20, "e" * 20],
            "userPolicies": [
                {"c" * 20: ["wso-gateway"]},
                {"e" * 20: ["wso-maintenance"]},
            ],
        }
    )
    return result


def test_native_import_result_ignores_valid_entity_order():
    from tests.support.asset_rustfs import validate_import_result

    native, _, _, _ = iam_fixture()
    result = import_result()
    for rows in result["added"].values():
        rows.reverse()
    validate_import_result(result, native.identities)


@pytest.mark.parametrize(
    "defect",
    [
        "section",
        "entity",
        "array-type",
        "failed",
        "skipped",
        "removed",
        "duplicate-policy",
        "duplicate-user",
        "duplicate-binding",
        "extra-group",
        "wrong-binding-map",
        "multiple-binding-policy",
    ],
)
def test_native_import_result_refuses_inexact_sections_entities_and_identity_sets(
    defect,
):
    from tests.support.asset_rustfs import validate_import_result

    native, _, _, _ = iam_fixture()
    result = import_result()
    if defect == "section":
        result["unexpected"] = {}
    elif defect == "entity":
        result["added"]["extra"] = []
    elif defect == "array-type":
        result["added"]["groups"] = {}
    elif defect in {"failed", "skipped", "removed"}:
        result[defect]["users"] = ["c" * 20]
    elif defect == "duplicate-policy":
        result["added"]["policies"] = ["wso-gateway", "wso-gateway"]
    elif defect == "duplicate-user":
        result["added"]["users"] = ["c" * 20, "c" * 20]
    elif defect == "duplicate-binding":
        result["added"]["userPolicies"] = [{"c" * 20: ["wso-gateway"]}] * 2
    elif defect == "extra-group":
        result["added"]["groups"] = ["unexpected"]
    elif defect == "wrong-binding-map":
        result["added"]["userPolicies"][0] = {
            "c" * 20: ["wso-gateway"],
            "e" * 20: ["wso-maintenance"],
        }
    else:
        result["added"]["userPolicies"][0] = {"c" * 20: ["wso-gateway", "consoleAdmin"]}
    with pytest.raises(RuntimeError, match="native IAM import"):
        validate_import_result(result, native.identities)


def test_official_download_refuses_return_at_immutable_download_cap(
    tmp_path, monkeypatch
):
    import httpx

    helper, _, payload, _ = pinned_test_archive(tmp_path, monkeypatch)
    now = [0.0]
    budget = helper.PhaseBudget(clock=lambda: now[0])
    budget.enter("A")
    monkeypatch.setattr(helper.time, "monotonic", lambda: now[0])
    original_client = httpx.Client

    def handle(request):
        now[0] = 180.0
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handle), **kwargs
        ),
    )
    with pytest.raises(RuntimeError, match="owned official RustFS acquisition"):
        helper.download_server(tmp_path, budget)
    assert not (tmp_path / "rustfs").exists()
    # The phase still has time; the exhausted download cap was independently binding.
    assert budget.allowance(20) == 20


@pytest.mark.parametrize(
    "change",
    [
        {"content-length": None},
        {"content-length": "1"},
        {"content-length": "+2"},
        {"content-length": "٢"},
        {"content-disposition": None},
        {"content-disposition": "attachment; filename=private.zip"},
        {"content-type": "application/zip; charset=utf-8"},
    ],
    ids=[
        "missing-length",
        "wrong-length",
        "signed-length",
        "nonascii-length",
        "missing-disposition",
        "wrong-disposition",
        "inexact-type",
    ],
)
def test_native_export_http_requires_exact_wire_metadata_and_always_closes(
    monkeypatch, change
):
    import httpx

    from tests.support.asset_rustfs import NativeAdminFailure

    native, _, _, _ = iam_fixture()
    native.request_hook = None
    closed = []
    headers = {
        "content-type": "application/zip",
        "content-length": "2",
        "content-disposition": "attachment; filename=iam-assets.zip",
    }
    for name, value in change.items():
        if value is None:
            del headers[name]
        else:
            headers[name] = value

    class Response:
        status_code = 200

        def __init__(self):
            self.headers = headers

        def iter_bytes(self, size):
            yield b"{}"

    class Context:
        def __enter__(self):
            return Response()

        def __exit__(self, *args):
            closed.append(True)

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Context())
    with pytest.raises(NativeAdminFailure) as caught:
        native.request("bootstrap", "GET", "export-iam")
    assert caught.value.phase == "ACCESS" and closed == [True]
    assert "private" not in str(caught.value)


def test_native_export_http_accepts_exact_bounded_declared_bytes(monkeypatch):
    import httpx

    native, _, _, maps = iam_fixture()
    native.request_hook = None
    payload = export_archive(maps)
    closed = []

    class Context:
        def __enter__(self):
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/zip",
                    "content-length": str(len(payload)),
                    "content-disposition": "attachment; filename=iam-assets.zip",
                },
                content=payload,
            )

        def __exit__(self, *args):
            closed.append(True)

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Context())
    assert native.request("bootstrap", "GET", "export-iam") == (
        200,
        "application/zip",
        payload,
    )
    assert closed == [True]


def test_native_admin_response_wire_overflow_is_refused_before_json_decode_and_closed(
    monkeypatch,
):
    import httpx

    from tests.support.asset_rustfs import NativeAdminFailure

    native, _, _, _ = iam_fixture()
    native.request_hook = None
    closed = []

    class Context:
        def __enter__(self):
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"x" * 65537
            )

        def __exit__(self, *args):
            closed.append(True)

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Context())
    with pytest.raises(NativeAdminFailure) as caught:
        native.request("bootstrap", "GET", "user-info")
    assert caught.value.phase == "READ" and closed == [True]


@pytest.mark.parametrize("defect", ["crc", "duplicate-json"])
def test_native_export_decodes_safe_later_members_after_first_member_failure(
    defect, capsys
):
    import struct

    from tests.support.asset_rustfs import NativeExportFailure, export_maps

    _, _, _, maps = iam_fixture()
    payload = export_archive(maps)
    if defect == "crc":
        changed = bytearray(payload)
        name_length, extra_length = struct.unpack_from("<HH", changed, 26)
        changed[30 + name_length + extra_length] ^= 1
        payload = bytes(changed)
    else:
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(payload)) as original,
            zipfile.ZipFile(output, "w") as bundle,
        ):
            for entry in original.infolist():
                body = (
                    b'{"private":1,"private":2}'
                    if entry.filename == "iam-assets/policies.json"
                    else original.read(entry)
                )
                bundle.writestr(entry, body)
        payload = output.getvalue()
    with pytest.raises(NativeExportFailure) as caught:
        export_maps(payload)
    assert set(caught.value.partial) == {
        "users",
        "groups",
        "svcaccts",
        "user_mappings",
        "group_mappings",
        "stsuser_mappings",
    }
    assert caught.value.partial["users"] == {
        "c" * 20: {"secretKey": "d" * 40, "status": "enabled"},
        "e" * 20: {"secretKey": "f" * 40, "status": "enabled"},
    }
    assert caught.value.partial["stsuser_mappings"] == {}
    assert str(caught.value) == "native IAM export shape differs"
    assert capsys.readouterr() == ("", "")


def test_native_invalid_before_member_finishes_safe_reads_without_mutation():
    native, calls, _, maps = iam_fixture()
    original = native.request_hook
    del maps["groups"]
    payload = export_archive(maps)

    def request(actor, method, path, query, body, headers, timeout):
        result = original(actor, method, path, query, body, headers, timeout)
        return (200, "application/zip", payload) if path == "export-iam" else result

    native.request_hook = request
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
    ) == ("GATEWAY", "IAM_BEFORE", "EXPORT", "SHAPE")
    assert calls == [
        ("bootstrap", "GET", "export-iam"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "info-canned-policy"),
        ("bootstrap", "GET", "info-canned-policy"),
    ]


@pytest.mark.parametrize("timing", ["before", "after", "import"])
@pytest.mark.parametrize("later_failure", ["http", "transport", "close"])
def test_native_mixed_snapshot_failures_preserve_first_observed_origin(
    monkeypatch, timing, later_failure, capsys
):
    from urllib.parse import parse_qs, urlsplit

    import httpx

    native, calls, controls, maps = iam_fixture()
    original_hook = native.request_hook
    native.request_hook = None
    closed = []
    if timing == "before":
        maps["users"]["c" * 20]["secretKey"] = "changed-private-secret"

    def stream(method, url, **arguments):
        parsed = urlsplit(url)
        path = parsed.path.removeprefix("/rustfs/admin/v3/")
        query = {name: values[0] for name, values in parse_qs(parsed.query).items()}
        actor = "gateway" if method == "PUT" else "bootstrap"
        status, mime, payload = original_hook(
            actor,
            method,
            path,
            query or None,
            arguments["content"],
            arguments["headers"],
            arguments["timeout"],
        )
        if path == "export-iam":
            payload = export_archive(maps)
        if method == "PUT":
            maps["users"]["c" * 20]["secretKey"] = "changed-private-secret"
            if timing == "import":
                status = 200
        fail_later = (
            path == "user-info"
            and query["accessKey"] == "e" * 20
            and (timing == "before" or controls["changed"])
        )
        if fail_later and later_failure == "http":
            status, payload = 503, b"{}"
        response_headers = {"content-type": mime}
        if path == "export-iam":
            response_headers.update(
                {
                    "content-length": str(len(payload)),
                    "content-disposition": "attachment; filename=iam-assets.zip",
                }
            )

        class Context:
            def __enter__(self):
                if fail_later and later_failure == "transport":
                    raise httpx.ConnectError("private-later-transport")
                return httpx.Response(status, headers=response_headers, content=payload)

            def __exit__(self, *args):
                closed.append(path)
                if fail_later and later_failure == "close":
                    raise OSError("private-later-close")

        return Context()

    monkeypatch.setattr(httpx, "stream", stream)
    with pytest.raises(NativeIamFailure) as caught:
        native.no_effect()
    if timing == "import":
        expected = ("GATEWAY", "IAM_IMPORT", "IMPORT_STATUS", "HTTP_STATUS", 200)
    else:
        expected = (
            "GATEWAY",
            "IAM_BEFORE" if timing == "before" else "IAM_AFTER",
            "EXPORT",
            "EXPECTED_STATE",
            None,
        )
    assert (
        caught.value.actor,
        caught.value.phase,
        caught.value.component,
        caught.value.condition,
        caught.value.status,
    ) == expected
    snapshot_calls = [
        ("bootstrap", "GET", "export-iam"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "user-info"),
        ("bootstrap", "GET", "info-canned-policy"),
        ("bootstrap", "GET", "info-canned-policy"),
    ]
    expected_calls = (
        snapshot_calls
        if timing == "before"
        else [
            *snapshot_calls,
            ("gateway", "PUT", "import-iam"),
            *snapshot_calls,
        ]
    )
    assert calls == expected_calls
    expected_closes = len(expected_calls) - (later_failure == "transport")
    assert len(closed) == expected_closes
    assert "private" not in str(caught.value)
    assert capsys.readouterr() == ("", "")
