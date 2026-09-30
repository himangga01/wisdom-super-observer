"""Offline probe-validator contracts; never actual SeaweedFS acceptance."""

from io import BytesIO
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from tests.support.asset_provider import AssetProvider


def provider_error(status, code):
    return ClientError(
        {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code, "Message": "sanitized"},
        },
        "Probe",
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (501, "NotImplemented"),
        (403, "NotImplemented"),
        (400, "InvalidRequest"),
        (403, "UnknownError"),
    ],
)
@pytest.mark.parametrize("ownership", [False, True])
def test_generic_unsupported_is_not_privacy_enforcement(status, code, ownership):
    operation = Mock(side_effect=provider_error(status, code))
    with pytest.raises(RuntimeError, match="security capability failed"):
        AssetProvider.denied(operation, "public grant", ownership=ownership)


def test_explicit_ownership_acl_denial_is_valid_only_in_acl_probe():
    operation = Mock(side_effect=provider_error(400, "AccessControlListNotSupported"))
    AssetProvider.denied(operation, "ownership enforcement", ownership=True)
    with pytest.raises(RuntimeError, match="security capability failed"):
        AssetProvider.denied(operation, "runtime IAM permission")


@pytest.mark.parametrize(
    "readback",
    [
        None,
        {},
        {"Rules": []},
        {"Rules": [{"ObjectOwnership": "ObjectWriter"}]},
        {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}], "unexpected": True},
    ],
)
def test_ownership_readback_must_exactly_match_enforced_mode(tmp_path, readback):
    provider = AssetProvider(tmp_path)
    admin = Mock()
    admin.get_bucket_ownership_controls.return_value = {"OwnershipControls": readback}
    provider.clients["bootstrap"] = admin
    with pytest.raises(RuntimeError, match="ownership"):
        provider.configure_ownership()


def test_ownership_api_failure_is_not_optional(tmp_path):
    provider = AssetProvider(tmp_path)
    admin = Mock()
    admin.put_bucket_ownership_controls.side_effect = provider_error(
        501, "NotImplemented"
    )
    provider.clients["bootstrap"] = admin
    with pytest.raises(RuntimeError, match="ownership"):
        provider.configure_ownership()
    assert provider.receipt is None


def test_enforced_ownership_has_exact_put_and_readback(tmp_path):
    provider = AssetProvider(tmp_path)
    admin = Mock()
    ownership = {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    admin.get_bucket_ownership_controls.return_value = {"OwnershipControls": ownership}
    provider.clients["bootstrap"] = admin
    provider.configure_ownership()
    admin.put_bucket_ownership_controls.assert_called_once_with(
        Bucket=provider.bucket, OwnershipControls=ownership
    )
    admin.get_bucket_ownership_controls.assert_called_once_with(Bucket=provider.bucket)


@pytest.mark.parametrize(
    "grantee",
    [
        {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
        {
            "Type": "Group",
            "URI": "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
        },
        {"Type": "CanonicalUser", "ID": "foreign-owner"},
    ],
)
def test_public_or_foreign_acl_is_rejected(grantee):
    with pytest.raises(RuntimeError, match="private owner"):
        AssetProvider.require_private_acl(
            {
                "Owner": {"ID": "owner"},
                "Grants": [{"Grantee": grantee, "Permission": "READ"}],
            }
        )


def test_missing_bucket_policy_requires_real_not_found(tmp_path):
    provider = AssetProvider(tmp_path)
    admin = Mock()
    provider.clients["bootstrap"] = admin
    admin.get_bucket_policy.side_effect = provider_error(404, "NoSuchBucketPolicy")
    provider.inspect_no_bucket_policy()
    admin.get_bucket_policy.side_effect = provider_error(501, "NotImplemented")
    with pytest.raises(RuntimeError, match="bucket policy"):
        provider.inspect_no_bucket_policy()


def offline_profile_probe(tmp_path, monkeypatch):
    """Replace only external SDK/HTTP boundaries; execute the real probe validators."""
    provider = AssetProvider(tmp_path)
    provider.endpoint = "http://unused.invalid"
    provider.clients = {name: Mock() for name in ("bootstrap", "gateway", "cleanup")}
    for client in provider.clients.values():
        for operation in (
            "put_bucket_acl",
            "put_object_acl",
            "put_bucket_ownership_controls",
            "delete_bucket_ownership_controls",
            "put_bucket_policy",
            "delete_bucket_policy",
            "put_object",
            "create_multipart_upload",
        ):
            getattr(client, operation).side_effect = provider_error(403, "AccessDenied")
    admin = provider.clients["bootstrap"]
    private_acl = {
        "Owner": {"ID": "owner"},
        "Grants": [
            {
                "Grantee": {"Type": "CanonicalUser", "ID": "owner"},
                "Permission": "FULL_CONTROL",
            }
        ],
    }
    admin.get_bucket_acl.return_value = private_acl
    admin.get_object_acl.return_value = private_acl
    admin.get_bucket_policy.side_effect = provider_error(404, "NoSuchBucketPolicy")
    admin.get_bucket_ownership_controls.return_value = {
        "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    }
    admin.list_objects_v2.return_value = {}
    admin.list_multipart_uploads.return_value = {}
    admin.get_object.return_value = {"Body": BytesIO(b"ciphertext")}
    monkeypatch.setattr(provider, "raw_http", Mock(return_value=(403, b"")))
    return provider


def test_required_public_grant_matrix_reaches_every_sdk_boundary(tmp_path, monkeypatch):
    provider = offline_profile_probe(tmp_path, monkeypatch)
    key = provider.prefix + "capability/private"
    provider.privacy_profile(key, b"ciphertext")
    # Independently derived from the ruling: three canned ACLs plus both groups
    # in read and full-control forms, on existing object, PUT and multipart.
    required = {
        ("ACL", "public-read"),
        ("ACL", "public-read-write"),
        ("ACL", "authenticated-read"),
        ("GrantRead", 'uri="http://acs.amazonaws.com/groups/global/AllUsers"'),
        ("GrantFullControl", 'uri="http://acs.amazonaws.com/groups/global/AllUsers"'),
        (
            "GrantRead",
            'uri="http://acs.amazonaws.com/groups/global/AuthenticatedUsers"',
        ),
        (
            "GrantFullControl",
            'uri="http://acs.amazonaws.com/groups/global/AuthenticatedUsers"',
        ),
    }
    for client in provider.clients.values():
        for operation in ("put_object_acl", "put_object", "create_multipart_upload"):
            attempts = []
            for call in getattr(client, operation).call_args_list:
                grant = {
                    name: value
                    for name, value in call.kwargs.items()
                    if name in {"ACL", "GrantRead", "GrantFullControl"}
                }
                if "AccessControlPolicy" in call.kwargs:
                    public = call.kwargs["AccessControlPolicy"]["Grants"][1]
                    grant = {
                        {"READ": "GrantRead", "FULL_CONTROL": "GrantFullControl"}[
                            public["Permission"]
                        ]: 'uri="' + public["Grantee"]["URI"] + '"'
                    }
                if grant == {"ACL": "private"}:
                    continue  # The separate runtime administrative IAM probe.
                assert call.kwargs["Bucket"] == provider.bucket
                assert call.kwargs["Key"].startswith(provider.prefix)
                attempts.append(next(iter(grant.items())))
            assert len(attempts) == 7
            assert set(attempts) == required
    assert provider.receipt is None  # A subprobe alone cannot mint acceptance.


def test_existing_object_explicit_group_grants_use_valid_policy_body(
    tmp_path, monkeypatch
):
    provider = offline_profile_probe(tmp_path, monkeypatch)
    provider.privacy_profile(provider.prefix + "capability/private", b"ciphertext")
    for client in provider.clients.values():
        policies = [
            call.kwargs["AccessControlPolicy"]
            for call in client.put_object_acl.call_args_list
            if "AccessControlPolicy" in call.kwargs
        ]
        assert len(policies) == 4
        assert {
            (policy["Grants"][1]["Permission"], policy["Grants"][1]["Grantee"]["URI"])
            for policy in policies
        } == {
            ("READ", "http://acs.amazonaws.com/groups/global/AllUsers"),
            ("FULL_CONTROL", "http://acs.amazonaws.com/groups/global/AllUsers"),
            ("READ", "http://acs.amazonaws.com/groups/global/AuthenticatedUsers"),
            (
                "FULL_CONTROL",
                "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
            ),
        }
        for policy in policies:
            assert policy["Owner"] == {"ID": "owner"}
            assert policy["Grants"][0] == {
                "Grantee": {"Type": "CanonicalUser", "ID": "owner"},
                "Permission": "FULL_CONTROL",
            }
            assert policy["Grants"][1]["Grantee"]["Type"] == "Group"


@pytest.mark.parametrize("identity", ["bootstrap", "gateway", "cleanup"])
@pytest.mark.parametrize(
    "operation", ["put_object_acl", "put_object", "create_multipart_upload"]
)
def test_any_public_grant_success_fails_closed(
    tmp_path, monkeypatch, identity, operation
):
    provider = offline_profile_probe(tmp_path, monkeypatch)

    def public_success(**arguments):
        if arguments.get("ACL") == "private":
            raise provider_error(403, "AccessDenied")
        return {}

    getattr(provider.clients[identity], operation).side_effect = public_success
    with pytest.raises(RuntimeError, match="public ACL/grant refusal"):
        provider.privacy_profile(provider.prefix + "capability/private", b"ciphertext")
    assert provider.receipt is None


@pytest.mark.parametrize("anonymous_probe", range(4))
def test_any_anonymous_access_success_fails_closed(
    tmp_path, monkeypatch, anonymous_probe
):
    provider = offline_profile_probe(tmp_path, monkeypatch)
    statuses = [(403, b"")] * 4
    statuses[anonymous_probe] = (200, b"")
    provider.raw_http.side_effect = statuses
    with pytest.raises(RuntimeError, match="anonymous"):
        provider.privacy_profile(provider.prefix + "capability/private", b"ciphertext")
    assert provider.receipt is None


@pytest.mark.parametrize(
    "listing,field",
    [("list_objects_v2", "Contents"), ("list_multipart_uploads", "Uploads")],
)
def test_denied_public_attempt_must_not_leave_resources(
    tmp_path, monkeypatch, listing, field
):
    provider = offline_profile_probe(tmp_path, monkeypatch)
    getattr(provider.clients["bootstrap"], listing).return_value = {field: [{}]}
    with pytest.raises(RuntimeError, match="left an"):
        provider.privacy_profile(provider.prefix + "capability/private", b"ciphertext")
    assert provider.receipt is None
