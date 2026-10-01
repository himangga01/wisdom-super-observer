"""Canonical business intent must resist actor/key/browser variations."""

from uuid import UUID

import pytest
from pydantic import ValidationError
from wso_contracts.tvt import operation

BASE = {
    "kind": "firmware",
    "domain": "TVT",
    "identity_id": "00000000-0000-0000-0000-000000000001",
    "device_id": "00000000-0000-0000-0000-000000000002",
    "store_id": "00000000-0000-0000-0000-000000000003",
    "target_version": "v1.2",
}


def parse(value):
    parser = getattr(operation, "parse_intent", None)
    assert parser is not None, "typed intent validation is required"
    return parser(value)


def test_firmware_hold_ignores_store_but_not_target_version():
    first = parse(BASE)
    alternate = parse({**BASE, "store_id": str(UUID(int=4))})
    changed = parse({**BASE, "target_version": "v1.3"})
    assert first.business_key() == alternate.business_key()
    assert first.business_key() != changed.business_key()
    assert first.payload_hash() != alternate.payload_hash()


@pytest.mark.parametrize(
    "extra", ["actor_id", "idempotency_key", "discriminator", "payload", "tenant_id"]
)
def test_browser_fields_cannot_supply_business_identity(extra):
    with pytest.raises(ValidationError):
        parse({**BASE, extra: "invented"})


def test_payment_quote_and_term_are_part_of_business_identity():
    value = {
        "kind": "payment",
        "domain": "TVT",
        "identity_id": str(UUID(int=1)),
        "product": "cloud",
        "term": "P1Y",
        "quoted_price_version": "quote-5",
    }
    first = parse(value)
    for field, changed in (
        ("term", "P1M"),
        ("quoted_price_version", "quote-6"),
        ("product", "vas"),
    ):
        assert first.business_key() != parse({**value, field: changed}).business_key()


def test_delete_requires_exact_target_and_tyco_has_no_tvt_reference():
    with pytest.raises(ValidationError):
        parse(
            {
                "kind": "delete",
                "domain": "TVT",
                "identity_id": str(UUID(int=1)),
                "target_kind": "account",
                "target_id": str(UUID(int=2)),
            }
        )
    value = parse(
        {
            "kind": "tyco",
            "domain": "TYCO",
            "identity_id": str(UUID(int=1)),
            "panel_id": str(UUID(int=2)),
            "action": "relay",
            "target": "relay-1",
            "requested_state": "open",
        }
    )
    assert value.job_kind() == "TYCO_OPERATION"
    with pytest.raises(ValidationError):
        parse({**value.model_dump(), "device_id": str(UUID(int=3))})


def test_registry_composition_preserves_supplied_retention_and_rejects_override():
    import wso_core.tvt.domain_jobs as domain
    from wso_contracts.jobs import ImportJobPayload
    from wso_core.jobs import DEFAULT_REGISTRY, JobKind, JobRegistry

    retained = JobKind("ASSET_RETENTION", ImportJobPayload, "TENANT")
    registry = domain.compose_registry(
        JobRegistry((*DEFAULT_REGISTRY.kinds.values(), retained))
    )
    assert registry.get("ASSET_RETENTION") is retained
    assert registry.get("IMPORT") is DEFAULT_REGISTRY.get("IMPORT")
    assert registry.get("TVT_DEVICE_OPERATION").scope_kind == "STORE"
    with pytest.raises(ValueError):
        domain.compose_registry(registry)
