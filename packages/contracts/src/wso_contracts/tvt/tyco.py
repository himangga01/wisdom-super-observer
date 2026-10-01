"""Tyco selectors stay distinct from TVT identity and credential contracts."""

from uuid import UUID

from wso_contracts.models import TenantScope, WireModel


class TycoIdentityRef(TenantScope):
    actor_user_id: UUID
    tyco_identity_id: UUID


class TycoPanelRef(WireModel):
    identity: TycoIdentityRef
    panel_id: UUID
