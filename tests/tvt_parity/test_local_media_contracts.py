"""Local media scopes cannot widen existing cloud lease authority."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import TvtIdentityRef
from wso_contracts.tvt.local_device import LocalDeviceRef
from wso_contracts.tvt.media import MediaLease


def test_existing_cloud_lease_json_roundtrips_unchanged():
    owner = TvtIdentityRef(
        tenant_id=uuid4(), actor_user_id=uuid4(), identity_id=uuid4()
    )
    now = datetime.now(UTC)
    lease = MediaLease(
        id=uuid4(),
        owner=owner,
        device=DeviceRef(identity=owner, store_id=uuid4(), device_id=uuid4()),
        kind="live",
        state="REQUESTED",
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    wire = lease.model_dump_json()
    assert MediaLease.model_validate_json(wire) == lease
    assert "inventory_revision" not in lease.model_dump(exclude_none=True)


def local_values():
    from wso_contracts.tvt.local_media import LocalMediaOwnerRef

    owner = LocalMediaOwnerRef(
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        connection_id=uuid4(),
        store_id=uuid4(),
    )
    device = LocalDeviceRef(**owner.model_dump(), device_id=uuid4(), channel_id=uuid4())
    now = datetime.now(UTC)
    return {
        "id": uuid4(),
        "owner": owner,
        "device": device,
        "channel": device.channel_id,
        "kind": "live",
        "state": "NEGOTIATING",
        "heartbeat_at": now,
        "expires_at": now + timedelta(seconds=30),
        "connection_generation": 1,
        "inventory_revision": 2,
        "grant_revision": 1,
    }


def test_local_media_requires_exact_scope_and_revision_fences():
    values = local_values()
    assert (
        MediaLease.model_validate_json(MediaLease(**values).model_dump_json()).device
        == values["device"]
    )
    for field in ("tenant_id", "actor_user_id", "connection_id", "store_id"):
        bad = {**values, "device": values["device"].model_copy(update={field: uuid4()})}
        with pytest.raises(ValidationError):
            MediaLease(**bad)
    for field in (
        "connection_generation",
        "inventory_revision",
        "grant_revision",
        "channel",
    ):
        with pytest.raises(ValidationError):
            MediaLease(**{**values, field: None})
    with pytest.raises(ValidationError):
        MediaLease(**{**values, "kind": "talk"})
    with pytest.raises(ValidationError):
        MediaLease(
            **{
                **values,
                "device": values["device"].model_copy(update={"channel_id": None}),
            }
        )


def test_local_request_rejects_boolean_and_unsafe_revision_counters():
    from wso_contracts.tvt.local_media import LocalLiveRequest

    args = {
        "store_id": uuid4(),
        "device_id": uuid4(),
        "channel_id": uuid4(),
        "expected_generation": 1,
        "inventory_revision": 2,
    }
    assert LocalLiveRequest(**args).stream == "main"
    for value in (True, 0, 2**53, "1"):
        with pytest.raises(ValidationError):
            LocalLiveRequest(**{**args, "inventory_revision": value})


def test_browser_started_report_is_strict_bounded_observation_only():
    from wso_contracts.tvt.local_media import LocalLiveStartedRequest

    assert LocalLiveStartedRequest(decoded_frames=1).decoded_frames == 1
    for value in (True, 0, -1, 2**53, "1"):
        with pytest.raises(ValidationError):
            LocalLiveStartedRequest(decoded_frames=value)
    with pytest.raises(ValidationError):
        LocalLiveStartedRequest(decoded_frames=1, live_permission=True)
