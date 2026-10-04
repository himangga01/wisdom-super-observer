"""Portable API credential contract: no PostgreSQL acceptance claim."""

import json

import pytest
from pydantic import ValidationError
from wso_api.connections.router import (
    ConnectionCreate,
    ConnectionPatch,
    credential_bytes,
)


def create(**changes):
    data = {
        "kind": "TVT_DEVICE",
        "alias": "Office",
        "site": "Seoul",
        "username": "fixture-user",
        "password": "fixture-password",
        "device": {"serial": "inert123"},
    }
    data.update(changes)
    if changes.get("device", False) is None:
        data.pop("device")
    return ConnectionCreate.model_validate(data)


def test_device_create_canonical_private_serialization():
    body = create()
    assert json.loads(credential_bytes(body)) == {
        "schema_version": 1,
        "kind": "TVT_DEVICE",
        "serial": "INERT123",
        "country": "KR",
        "username": "fixture-user",
        "password": "fixture-password",
    }
    assert "inert123" not in repr(body)


def test_account_shape_is_unchanged_and_selector_forbidden():
    for kind in ("TVT_ACCOUNT", "TYCO_ACCOUNT"):
        body = create(kind=kind, device=None)
        assert json.loads(credential_bytes(body)) == {
            "username": "fixture-user",
            "password": "fixture-password",
        }
        with pytest.raises(ValidationError):
            create(kind=kind)


@pytest.mark.parametrize(
    "changes",
    [
        {"device": None},
        {"device": {"serial": "inert123", "sourceType": "TVT_ACCOUNT"}},
        {"device": {"serial": "inert123", "country": "ZZ"}},
        {"password": "한" * 22},
        {
            "device": {
                "serial": "inert123",
                "qr_payload": "<sn>OTHER</sn><user>fixture-user</user>",
            }
        },
    ],
)
def test_device_contract_rejects_missing_selector_types_and_contradiction(changes):
    with pytest.raises(ValidationError) as caught:
        create(**changes)
    assert "fixture-password" not in str(caught.value)
    assert "inert123" not in str(caught.value)


def test_patch_metadata_legacy_and_complete_pair():
    assert (
        credential_bytes(
            ConnectionPatch(expected_generation=1, alias="renamed"), kind="TVT_DEVICE"
        )
        is None
    )
    body = ConnectionPatch(
        expected_generation=1,
        username="fixture-user",
        password="fixture-password",
        device={"serial": "inert123"},
    )
    assert json.loads(credential_bytes(body, kind="TVT_DEVICE"))["serial"] == "INERT123"
    from wso_core.connections import ConnectionFailure

    for kind, data in [
        ("TVT_DEVICE", {"username": "u", "password": "p"}),
        (
            "TVT_ACCOUNT",
            {"username": "u", "password": "p", "device": {"serial": "inert123"}},
        ),
        ("TVT_DEVICE", {"device": {"serial": "inert123"}}),
    ]:
        with pytest.raises(ConnectionFailure) as caught:
            credential_bytes(ConnectionPatch(expected_generation=1, **data), kind=kind)
        assert caught.value.status == 422
