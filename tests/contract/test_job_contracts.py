"""Boundary contracts shared by durable job producers and consumers."""

from importlib import import_module
from types import ModuleType
from uuid import uuid4

import pytest
from pydantic import ValidationError


@pytest.fixture
def contracts() -> ModuleType:
    return import_module("wso_contracts.jobs")


def reference() -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_id": str(uuid4()),
        "outbox_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "kind": "IMPORT",
        "lease_generation": 1,
    }


def test_import_payload_without_store_or_connection(contracts: ModuleType) -> None:
    payload = contracts.ImportJobPayload(import_id=uuid4())
    assert payload.connection_id is None
    assert "store_id" not in payload.model_dump()


@pytest.mark.parametrize("key", ["password", "token", "url", "store_id"])
def test_import_payload_rejects_unowned_fields(contracts: ModuleType, key: str) -> None:
    with pytest.raises(ValidationError):
        contracts.ImportJobPayload.model_validate(
            {"import_id": str(uuid4()), key: "must-not-enter-a-job"}
        )


def test_registration_payload_requires_connection(contracts: ModuleType) -> None:
    with pytest.raises(ValidationError):
        contracts.RegistrationJobPayload(registration_id=uuid4())


@pytest.mark.parametrize("version", [True, "1", 0, 2])
def test_payload_and_reference_reject_invalid_versions(
    contracts: ModuleType, version: object
) -> None:
    with pytest.raises(ValidationError):
        contracts.ImportJobPayload.model_validate(
            {"schema_version": version, "import_id": str(uuid4())}
        )
    with pytest.raises(ValidationError):
        contracts.DispatchReference.model_validate(
            {**reference(), "schema_version": version}
        )


@pytest.mark.parametrize("generation", [True, "1", 0, -1, 2**63])
def test_dispatch_generation_is_a_strict_positive_bigint(
    contracts: ModuleType, generation: object
) -> None:
    with pytest.raises(ValidationError):
        contracts.DispatchReference.model_validate(
            {**reference(), "lease_generation": generation}
        )


def test_dispatch_reference_contains_metadata_only(contracts: ModuleType) -> None:
    value = reference()
    assert (
        contracts.DispatchReference.model_validate(value).model_dump(mode="json")
        == value
    )
    with pytest.raises(ValidationError):
        contracts.DispatchReference.model_validate({**value, "payload": {}})


def job_view() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "scope": {"scope_kind": "TENANT", "tenant_id": str(uuid4())},
        "kind": "IMPORT",
        "state": "QUEUED",
        "attempts": 0,
        "created_at": "2026-09-30T12:00:00Z",
        "updated_at": "2026-09-30T12:00:00Z",
    }


def test_job_view_uses_discriminated_scope_and_no_payload(
    contracts: ModuleType,
) -> None:
    view = contracts.JobView.model_validate(job_view()).model_dump(mode="json")
    assert view["scope"]["scope_kind"] == "TENANT"
    assert view["state"] == "QUEUED"
    assert "payload" not in view
    with pytest.raises(ValidationError):
        contracts.JobView.model_validate({**job_view(), "payload": {"secret": "x"}})


def test_store_scope_requires_real_store_id(contracts: ModuleType) -> None:
    with pytest.raises(ValidationError):
        contracts.JobView.model_validate(
            {
                **job_view(),
                "scope": {"scope_kind": "STORE", "tenant_id": str(uuid4())},
            }
        )


@pytest.mark.parametrize("state", ["ONLINE", "UNKNOWN_REMOTE_STATE", "ready"])
def test_job_view_rejects_noncanonical_job_state(
    contracts: ModuleType, state: str
) -> None:
    with pytest.raises(ValidationError):
        contracts.JobView.model_validate({**job_view(), "state": state})


def test_job_view_requires_aware_timestamp(contracts: ModuleType) -> None:
    with pytest.raises(ValidationError):
        contracts.JobView.model_validate(
            {**job_view(), "created_at": "2026-09-30T12:00:00"}
        )


def test_job_timestamps_are_normalized_to_utc(contracts: ModuleType) -> None:
    value = contracts.JobView.model_validate(
        {
            **job_view(),
            "created_at": "2026-09-30T12:00:00+09:00",
            "updated_at": "2026-09-30T12:01:00+09:00",
            "heartbeat_at": "2026-09-30T12:00:30+09:00",
        }
    ).model_dump(mode="json")
    assert value["created_at"] == "2026-09-30T03:00:00Z"
    assert value["updated_at"] == "2026-09-30T03:01:00Z"
    assert value["heartbeat_at"] == "2026-09-30T03:00:30Z"
    assert value["cancel_requested_at"] is None


@pytest.mark.parametrize("result", [{"number": float("nan")}, {"text": "한" * 22000}])
def test_job_result_rejects_nonfinite_or_oversized_json(
    contracts: ModuleType, result: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        contracts.JobView.model_validate({**job_view(), "result": result})
    with pytest.raises(ValidationError):
        contracts.JobItemView(item_key="item-1", state="FAILED", result=result)


def test_job_item_keeps_actual_outcome(contracts: ModuleType) -> None:
    item = contracts.JobItemView(
        item_key="item-1", state="FAILED", failure_code="HANDLER_UNAVAILABLE"
    )
    assert item.failure_code == "HANDLER_UNAVAILABLE"
    with pytest.raises(ValidationError):
        contracts.JobItemView(item_key="", state="SUCCEEDED")
