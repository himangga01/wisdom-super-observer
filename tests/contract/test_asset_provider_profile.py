"""Offline boundary validators; never actual MinIO acceptance."""

import json
from collections import Counter
from io import BytesIO
from itertools import product
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest
from botocore.exceptions import ClientError

from tests.support.asset_provider import AssetProvider, policy_config


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


def test_source_characterized_controls_require_effects_without_bootstrap_mutations(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    provider.clients = {name: Mock() for name in ("bootstrap", "gateway", "cleanup")}
    effects = []
    monkeypatch.setattr(
        provider, "private_effect", lambda *_: effects.append("verified")
    )
    monkeypatch.setattr(provider, "inspect_no_bucket_policy", lambda: None)
    provider.clients["bootstrap"].get_bucket_acl.return_value = {
        "Owner": {"ID": ""},
        "Grants": [
            {
                "Grantee": {"Type": "CanonicalUser", "ID": ""},
                "Permission": "FULL_CONTROL",
            }
        ],
    }
    mutations = (
        "put_bucket_policy",
        "delete_bucket_policy",
        "put_bucket_acl",
        "put_object_acl",
        "put_bucket_ownership_controls",
        "delete_bucket_ownership_controls",
        "put_public_access_block",
        "delete_public_access_block",
    )
    for name, actor in provider.clients.items():
        actor.get_bucket_ownership_controls.side_effect = error(501, "NotImplemented")
        actor.get_public_access_block.side_effect = error(501, "NotImplemented")
        for mutation in mutations:
            getattr(actor, mutation).side_effect = (
                AssertionError("bootstrap mutations prohibited")
                if name == "bootstrap"
                else error(403, "AccessDenied")
            )
    provider.control_profile("owned-private", b"ciphertext")
    assert len(effects) == 22
    for mutation in mutations:
        assert not getattr(provider.clients["bootstrap"], mutation).called


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
