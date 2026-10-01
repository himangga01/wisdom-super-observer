"""NEW1 domain contracts: structural scope checks, never authorization grants."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

TENANT = UUID("10000000-0000-4000-8000-000000000001")
ACTOR = UUID("20000000-0000-4000-8000-000000000001")
IDENTITY = UUID("30000000-0000-4000-8000-000000000001")
STORE = UUID("40000000-0000-4000-8000-000000000001")
DEVICE = UUID("50000000-0000-4000-8000-000000000001")
CHANNEL = UUID("60000000-0000-4000-8000-000000000001")
OTHER = UUID("90000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
OFFSET = timezone(timedelta(hours=9))


def identity_data():
    return {"tenant_id": TENANT, "actor_user_id": ACTOR, "identity_id": IDENTITY}


def device_data():
    return {
        "identity": identity_data(),
        "store_id": STORE,
        "device_id": DEVICE,
        "channel_id": CHANNEL,
    }


def lease_data():
    return {
        "id": OTHER,
        "owner": identity_data(),
        "device": device_data(),
        "channel": CHANNEL,
        "kind": "live",
        "state": "PLAYING",
        "expires_at": NOW + timedelta(minutes=1),
        "heartbeat_at": NOW,
    }


def tyco_identity_data():
    return {
        "tenant_id": TENANT,
        "actor_user_id": ACTOR,
        "tyco_identity_id": OTHER,
    }


def operation_data(domain="TVT", target_kind="device"):
    if domain == "TVT":
        target = (
            {"target_kind": "account", "identity": identity_data()}
            if target_kind == "account"
            else {"target_kind": "device", "device": device_data()}
        )
    else:
        target = (
            {"target_kind": "account", "identity": tyco_identity_data()}
            if target_kind == "account"
            else {
                "target_kind": "panel",
                "panel": {"identity": tyco_identity_data(), "panel_id": DEVICE},
            }
        )
    return {
        "intent_id": OTHER,
        "idempotency_key": "client-intent-001",
        "actor_user_id": ACTOR,
        "target": {"target_domain": domain, "target": target},
        "kind": "account.logout" if target_kind == "account" else "device.configure",
        "payload_hash": "0123456789abcdef" * 4,
        "state": "UNKNOWN_OUTCOME",
        "upstream_ref": "opaque/vendor:007",
        "readback_ref": None,
    }


def event_data():
    return {
        "event_id": OTHER,
        "source_id": "opaque-source:007",
        "device": device_data(),
        "channel": CHANNEL,
        "subtype": "unknown.vendor:77",
        "occurred_at": NOW.astimezone(OFFSET),
        "payload_ref": OTHER,
    }


def cloud_data():
    return {
        "identity": identity_data(),
        "device": device_data(),
        "channel": CHANNEL,
        "upstream_record_id": "opaque-record:007",
        "starts_at": NOW.astimezone(OFFSET),
        "ends_at": (NOW + timedelta(minutes=1)).astimezone(OFFSET),
    }


def test_prelogin_account_scope_without_store_or_connected_identity():
    from wso_contracts.tvt.identity import AccountScope

    account = AccountScope.model_validate(
        {"tenant_id": TENANT, "actor_user_id": ACTOR, "region": "EU", "brand": "TVT"}
    )
    wire = json.loads(account.model_dump_json())
    assert wire["tenant_id"] == "10000000-0000-4000-8000-000000000001"
    assert wire["actor_user_id"] == "20000000-0000-4000-8000-000000000001"
    assert wire["scope_kind"] == "TENANT"
    assert wire["identity_id"] is None
    assert "store_id" not in wire
    assert "device_id" not in wire
    assert AccountScope.model_validate_json(account.model_dump_json()) == account


def test_scoped_device_media_roundtrip_normalizes_utc():
    from wso_contracts.tvt.media import MediaLease

    data = lease_data()
    data["heartbeat_at"] = NOW.astimezone(OFFSET)
    lease = MediaLease.model_validate(data)
    wire = json.loads(lease.model_dump_json())
    assert wire["heartbeat_at"] == "2026-10-02T00:00:00Z"
    assert wire["device"]["store_id"] == "40000000-0000-4000-8000-000000000001"
    assert wire["channel"] == "60000000-0000-4000-8000-000000000001"
    assert lease.heartbeat_at.tzinfo == UTC
    assert MediaLease.model_validate_json(lease.model_dump_json()) == lease


def test_tyco_operation_target_has_separate_identity_roundtrip():
    from wso_contracts.tvt.operation import OperationView

    operation = OperationView.model_validate(operation_data("TYCO", "panel"))
    wire = json.loads(operation.model_dump_json())
    panel = wire["target"]["target"]["panel"]
    assert wire["target"]["target_domain"] == "TYCO"
    assert panel["identity"]["tyco_identity_id"] == str(OTHER)
    assert "identity_id" not in panel["identity"]
    assert OperationView.model_validate_json(operation.model_dump_json()) == operation


@pytest.mark.parametrize("field", ["store_id", "device_id", "token", "password"])
def test_prelogin_rejects_device_scope_and_credentials(field):
    from wso_contracts.tvt.identity import AccountScope

    with pytest.raises(ValidationError):
        AccountScope.model_validate(
            {
                "tenant_id": TENANT,
                "actor_user_id": ACTOR,
                "region": "EU",
                "brand": "TVT",
                field: "unexpected",
            }
        )


@pytest.mark.parametrize("field", ["region", "brand"])
@pytest.mark.parametrize("value", ["", " " * 2, "A" * 65, "name\nother", 123])
def test_prelogin_names_are_explicit_bounded_labels(field, value):
    from wso_contracts.tvt.identity import AccountScope

    data = {"tenant_id": TENANT, "actor_user_id": ACTOR, "region": "EU", "brand": "TVT"}
    data[field] = value
    with pytest.raises(ValidationError):
        AccountScope.model_validate(data)


def test_connected_account_scope_retains_uuid_identity_without_store():
    from wso_contracts.tvt.identity import AccountScope

    account = AccountScope.model_validate(
        {**identity_data(), "region": "EU", "brand": "TVT"}
    )
    assert json.loads(account.model_dump_json())["identity_id"] == str(IDENTITY)


@pytest.mark.parametrize("field", ["store_id", "device_id"])
def test_device_requires_local_uuid_store_and_device(field):
    from wso_contracts.tvt.device import DeviceRef

    data = device_data()
    del data[field]
    with pytest.raises(ValidationError):
        DeviceRef.model_validate(data)
    data[field] = "serial-number-is-not-a-local-id"
    with pytest.raises(ValidationError):
        DeviceRef.model_validate(data)


@pytest.mark.parametrize("source_kind", ["local", "cloud"])
def test_record_opaque_identifier_survives_uuid_json_roundtrip(source_kind):
    from wso_contracts.tvt.device import RecordRef

    record = RecordRef.model_validate(
        {
            "device": device_data(),
            "upstream_record_id": "0007/device:opaque",
            "source_kind": source_kind,
        }
    )
    wire = json.loads(record.model_dump_json())
    assert wire["upstream_record_id"] == "0007/device:opaque"
    assert wire["device"]["device_id"] == str(DEVICE)
    assert RecordRef.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("value", ["", "x" * 257, "opaque\nsecond", " ", 123])
def test_upstream_record_identifier_is_bounded_strict_and_opaque(value):
    from wso_contracts.tvt.device import RecordRef

    with pytest.raises(ValidationError):
        RecordRef.model_validate(
            {
                "device": device_data(),
                "upstream_record_id": value,
                "source_kind": "local",
            }
        )


def test_capabilities_retain_only_explicit_observations_with_utc_provenance():
    from wso_contracts.tvt.device import CapabilitySet

    capability = CapabilitySet.model_validate(
        {
            "model": "observed-model",
            "firmware": "1.2.3",
            "flags": [],
            "source_time": NOW,
        }
    )
    assert json.loads(capability.model_dump_json())["flags"] == []
    observed = CapabilitySet.model_validate(
        {
            "model": "observed-model",
            "firmware": "1.2.3",
            "flags": ["vendor.observed_flag", "live"],
            "source_time": NOW.astimezone(OFFSET),
        }
    )
    wire = json.loads(observed.model_dump_json())
    assert wire["flags"] == ["vendor.observed_flag", "live"]
    assert wire["source_time"] == "2026-10-02T00:00:00Z"
    assert CapabilitySet.model_validate_json(observed.model_dump_json()) == observed


@pytest.mark.parametrize(
    "patch",
    [
        {"flags": ["x" * 65]},
        {"flags": ["unsafe\nflag"]},
        {"flags": ["same"] * 65},
        {"flags": {"live": True}},
        {"model": "x" * 129},
        {"firmware": ""},
        {"command": {"arbitrary": "payload"}},
    ],
)
def test_capability_observations_reject_unbounded_or_command_data(patch):
    from wso_contracts.tvt.device import CapabilitySet

    with pytest.raises(ValidationError):
        CapabilitySet.model_validate(
            {
                "model": "observed",
                "firmware": "1",
                "flags": [],
                "source_time": NOW,
                **patch,
            }
        )


@pytest.mark.parametrize("field", ["tenant_id", "actor_user_id", "identity_id"])
def test_media_owner_must_match_device_identity(field):
    from wso_contracts.tvt.media import MediaLease

    data = lease_data()
    data["owner"][field] = OTHER
    with pytest.raises(ValidationError):
        MediaLease.model_validate(data)


@pytest.mark.parametrize("kind", ["live", "playback", "talk"])
def test_media_kinds_preserve_scope_without_inferring_transports(kind):
    from wso_contracts.tvt.media import MediaLease

    lease = MediaLease.model_validate({**lease_data(), "kind": kind})
    wire = json.loads(lease.model_dump_json())
    assert wire["kind"] == kind
    assert set(wire) == {
        "id",
        "owner",
        "device",
        "channel",
        "kind",
        "state",
        "expires_at",
        "heartbeat_at",
    }


@pytest.mark.parametrize("channel", [OTHER, None])
def test_media_explicit_device_channel_cannot_be_overridden_or_dropped(channel):
    from wso_contracts.tvt.media import MediaLease

    with pytest.raises(ValidationError):
        MediaLease.model_validate({**lease_data(), "channel": channel})


def test_media_accepts_device_level_lease_and_new_explicit_channel():
    from wso_contracts.tvt.media import MediaLease

    data = lease_data()
    data["device"]["channel_id"] = None
    data["channel"] = None
    assert MediaLease.model_validate(data).channel is None
    data["channel"] = CHANNEL
    assert MediaLease.model_validate(data).channel == CHANNEL


def test_media_rejects_heartbeat_after_expiry_but_allows_historical_closed_lease():
    from wso_contracts.tvt.media import MediaLease

    data = lease_data()
    data["heartbeat_at"] = NOW + timedelta(minutes=2)
    with pytest.raises(ValidationError):
        MediaLease.model_validate(data)
    data["heartbeat_at"] = NOW + timedelta(minutes=1)
    data["state"] = "CLOSED"
    assert MediaLease.model_validate(data).heartbeat_at == data["expires_at"]


@pytest.mark.parametrize("field", ["native_handle", "frames", "signed_url", "token"])
def test_media_wire_rejects_native_and_secret_fields(field):
    from wso_contracts.tvt.media import MediaLease

    with pytest.raises(ValidationError):
        MediaLease.model_validate({**lease_data(), field: "unexpected"})


def test_unknown_event_subtype_is_preserved_with_asset_uuid_and_utc():
    from wso_contracts.tvt.event import TvtEvent

    event = TvtEvent.model_validate(event_data())
    wire = json.loads(event.model_dump_json())
    assert wire["subtype"] == "unknown.vendor:77"
    assert wire["source_id"] == "opaque-source:007"
    assert wire["occurred_at"] == "2026-10-02T00:00:00Z"
    assert wire["payload_ref"] == str(OTHER)
    assert TvtEvent.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize("field", ["subtype", "source_id"])
@pytest.mark.parametrize("value", ["", "x" * 257, "unsafe\rvalue", 123])
def test_event_internal_names_are_bounded_and_strict(field, value):
    from wso_contracts.tvt.event import TvtEvent

    with pytest.raises(ValidationError):
        TvtEvent.model_validate({**event_data(), field: value})


@pytest.mark.parametrize("patch", [{"channel": OTHER}, {"payload_ref": "unsafe-image"}])
def test_event_rejects_channel_conflict_and_non_asset_payload_reference(patch):
    from wso_contracts.tvt.event import TvtEvent

    with pytest.raises(ValidationError):
        TvtEvent.model_validate({**event_data(), **patch})


@pytest.mark.parametrize("field", ["payload", "image", "token", "upstream_json"])
def test_event_rejects_raw_upstream_and_secret_fields(field):
    from wso_contracts.tvt.event import TvtEvent

    with pytest.raises(ValidationError):
        TvtEvent.model_validate({**event_data(), field: {"arbitrary": "data"}})


@pytest.mark.parametrize(
    "domain,target_kind", [("TVT", "account"), ("TVT", "device"), ("TYCO", "account")]
)
def test_operation_targets_roundtrip_typed_domains(domain, target_kind):
    from wso_contracts.tvt.operation import OperationView

    operation = OperationView.model_validate(operation_data(domain, target_kind))
    wire = json.loads(operation.model_dump_json())
    assert wire["target"]["target_domain"] == domain
    assert wire["target"]["target"]["target_kind"] == target_kind
    assert wire["state"] == "UNKNOWN_OUTCOME"
    assert wire["upstream_ref"] == "opaque/vendor:007"
    assert OperationView.model_validate_json(operation.model_dump_json()) == operation


@pytest.mark.parametrize(
    "domain,target_kind",
    [("TVT", "account"), ("TVT", "device"), ("TYCO", "account"), ("TYCO", "panel")],
)
def test_operation_actor_must_match_its_scoped_identity(domain, target_kind):
    from wso_contracts.tvt.operation import OperationView

    data = operation_data(domain, target_kind)
    data["actor_user_id"] = OTHER
    with pytest.raises(ValidationError):
        OperationView.model_validate(data)


@pytest.mark.parametrize("domain", ["TVT", "TYCO"])
def test_operation_target_rejects_other_domain_identity(domain):
    from wso_contracts.tvt.operation import OperationView

    data = operation_data(domain, "account")
    data["target"]["target"]["identity"] = (
        tyco_identity_data() if domain == "TVT" else identity_data()
    )
    with pytest.raises(ValidationError):
        OperationView.model_validate(data)


@pytest.mark.parametrize(
    "target",
    [
        {"target_domain": "UNKNOWN", "target": {"target_kind": "account"}},
        {"target_domain": "TVT", "target": {"target_kind": "panel"}},
        {"target_domain": "TYCO", "target": {"target_kind": "device"}},
        {"target_domain": "TVT", "target": {"target_kind": "account"}},
        {"target": {"target_kind": "account", "identity": identity_data()}},
        {
            "target_domain": "TYCO",
            "identity": identity_data(),
            "target": {"target_kind": "account", "identity": tyco_identity_data()},
        },
        {
            "target_domain": "TVT",
            "target": {
                "target_kind": "account",
                "identity": identity_data(),
                "tyco_identity": tyco_identity_data(),
            },
        },
    ],
)
def test_operation_rejects_malformed_and_multiple_identity_targets(target):
    from wso_contracts.tvt.operation import OperationView

    with pytest.raises(ValidationError):
        OperationView.model_validate({**operation_data(), "target": target})


@pytest.mark.parametrize(
    "patch",
    [
        {"payload_hash": "A" * 64},
        {"payload_hash": "0" * 63},
        {"payload_hash": "0" * 65},
        {"payload_hash": "g" * 64},
        {"idempotency_key": ""},
        {"idempotency_key": "x" * 129},
        {"kind": ""},
        {"kind": "x" * 129},
        {"kind": "unsafe\ncommand"},
        {"upstream_ref": "x" * 257},
        {"readback_ref": "unsafe\nref"},
        {"payload": {"arbitrary": "command"}},
        {"token": "unexpected"},
        {"confirmation_token": "unexpected"},
    ],
)
def test_operation_rejects_bad_hash_unbounded_refs_and_raw_payload(patch):
    from wso_contracts.tvt.operation import OperationView

    with pytest.raises(ValidationError):
        OperationView.model_validate({**operation_data(), **patch})


def test_cloud_record_roundtrip_preserves_ownership_and_utc_interval():
    from wso_contracts.tvt.cloud import CloudRecordRef

    record = CloudRecordRef.model_validate(cloud_data())
    wire = json.loads(record.model_dump_json())
    assert wire["starts_at"] == "2026-10-02T00:00:00Z"
    assert wire["ends_at"] == "2026-10-02T00:01:00Z"
    assert wire["upstream_record_id"] == "opaque-record:007"
    assert wire["device"]["channel_id"] == wire["channel"] == str(CHANNEL)
    assert CloudRecordRef.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("field", ["tenant_id", "actor_user_id", "identity_id"])
def test_cloud_record_identity_must_match_device(field):
    from wso_contracts.tvt.cloud import CloudRecordRef

    data = cloud_data()
    data["identity"][field] = OTHER
    with pytest.raises(ValidationError):
        CloudRecordRef.model_validate(data)


@pytest.mark.parametrize("channel", [OTHER, None])
def test_cloud_record_cannot_override_or_drop_device_channel(channel):
    from wso_contracts.tvt.cloud import CloudRecordRef

    with pytest.raises(ValidationError):
        CloudRecordRef.model_validate({**cloud_data(), "channel": channel})


def test_cloud_record_rejects_reversed_interval_and_allows_equal_endpoints():
    from wso_contracts.tvt.cloud import CloudRecordRef

    with pytest.raises(ValidationError):
        CloudRecordRef.model_validate(
            {**cloud_data(), "ends_at": NOW - timedelta(seconds=1)}
        )
    assert (
        CloudRecordRef.model_validate({**cloud_data(), "ends_at": NOW}).ends_at == NOW
    )


@pytest.mark.parametrize("field", ["url", "signed_url", "media_bytes", "cookie"])
def test_cloud_record_rejects_media_and_credentials(field):
    from wso_contracts.tvt.cloud import CloudRecordRef

    with pytest.raises(ValidationError):
        CloudRecordRef.model_validate({**cloud_data(), field: "unexpected"})


@pytest.mark.parametrize("field", ["identity_id", "cookie", "password"])
def test_tyco_identity_rejects_tvt_identity_and_credentials(field):
    from wso_contracts.tvt.tyco import TycoIdentityRef

    with pytest.raises(ValidationError):
        TycoIdentityRef.model_validate({**tyco_identity_data(), field: "unexpected"})


def test_tyco_panel_requires_its_own_identity_and_local_uuid():
    from wso_contracts.tvt.tyco import TycoPanelRef

    for patch in ({"identity": identity_data()}, {"panel_id": "upstream-serial"}):
        with pytest.raises(ValidationError):
            TycoPanelRef.model_validate(
                {"identity": tyco_identity_data(), "panel_id": DEVICE, **patch}
            )


@pytest.mark.parametrize(
    "module,name,data,field",
    [
        (
            "device",
            "CapabilitySet",
            {"model": "m", "firmware": "1", "flags": []},
            "source_time",
        ),
        ("media", "MediaLease", lease_data(), "expires_at"),
        ("media", "MediaLease", lease_data(), "heartbeat_at"),
        ("event", "TvtEvent", event_data(), "occurred_at"),
        ("cloud", "CloudRecordRef", cloud_data(), "starts_at"),
        ("cloud", "CloudRecordRef", cloud_data(), "ends_at"),
    ],
)
def test_every_timestamp_boundary_rejects_naive_datetimes(module, name, data, field):
    from importlib import import_module

    model = getattr(import_module(f"wso_contracts.tvt.{module}"), name)
    with pytest.raises(ValidationError):
        model.model_validate({**data, field: NOW.replace(tzinfo=None)})


def test_protocol_states_and_token_kinds_remain_distinct_without_secret_values():
    from wso_contracts.tvt.device import DeviceState
    from wso_contracts.tvt.event import PublicEventKind
    from wso_contracts.tvt.identity import SessionState, TokenKind
    from wso_contracts.tvt.media import MediaState, TalkState
    from wso_contracts.tvt.operation import OperationState

    assert (
        json.dumps([TokenKind.USER, TokenKind.P2P, TokenKind.DEVICE])
        == '["USER", "P2P", "DEVICE"]'
    )
    for enum, value in (
        (SessionState, "EXPIRED"),
        (DeviceState, "UNAUTHORIZED"),
        (MediaState, "RECONNECTING"),
        (TalkState, "BUSY"),
        (OperationState, "UNKNOWN_OUTCOME"),
        (PublicEventKind, "LEASE_STATE"),
    ):
        assert enum(value).value == value
        with pytest.raises(ValueError):
            enum("INVENTED_SUCCESS")
