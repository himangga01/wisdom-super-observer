"""Metadata authorization only: scopes cannot issue or redeem T04 credentials.

Every use must call ``recheck`` in a fresh protected transaction. The private
Python seal prevents accidental construction; PostgreSQL is the authority.
This module does not fence a later external side effect against revocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_SEAL = object()
_ACTIONS = frozenset(
    {"account.login", "account.read", "device.read", "media.live", "panel.read"}
)


class AuthorizationDenied(PermissionError):
    def __init__(self) -> None:
        super().__init__("domain authorization denied")


@dataclass(frozen=True, slots=True)
class DomainTarget:
    domain: str
    identity_id: UUID | None = None
    device_id: UUID | None = None
    channel_id: UUID | None = None
    store_id: UUID | None = None
    panel_id: UUID | None = None

    def __post_init__(self) -> None:
        ids = (
            self.identity_id,
            self.device_id,
            self.channel_id,
            self.store_id,
            self.panel_id,
        )
        valid = (
            type(self.domain) is str
            and self.domain in {"TVT", "TYCO"}
            and all(value is None or type(value) is UUID for value in ids)
        )
        valid = valid and (self.identity_id is not None or not any(ids[1:]))
        if self.domain == "TVT":
            valid = valid and self.panel_id is None
            valid = valid and ((self.device_id is None) == (self.store_id is None))
            valid = valid and (self.channel_id is None or self.device_id is not None)
        else:
            valid = valid and not any((self.device_id, self.channel_id, self.store_id))
        if not valid:
            raise ValueError("invalid domain target")


@dataclass(frozen=True, slots=True)
class AuthorizationFacts:
    """Internal decision inputs, never a permit or a public request DTO."""

    tenant_id: UUID
    actor_id: UUID
    role: str
    target: DomainTarget
    action: str
    member: bool
    store_assigned: bool
    identity_granted: bool
    linked: bool
    upstream_allowed: bool
    capability_verified: bool
    grant_id: UUID | None = field(repr=False)
    grant_revision: int = field(repr=False)
    capability_revision: int = field(repr=False)
    upstream_revision: int = field(repr=False)
    link_revision: int = field(repr=False)
    connection_generation: int = field(repr=False)
    valid_until: datetime | None = field(repr=False)


def decide(facts: AuthorizationFacts, *, now: datetime) -> bool:
    """Intersect supplied facts; only the checked SQL reader supplies live facts."""
    if type(facts) is not AuthorizationFacts or type(facts.target) is not DomainTarget:
        return False
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        return False
    if any(type(value) is not UUID for value in (facts.tenant_id, facts.actor_id)):
        return False
    checks = (
        facts.member,
        facts.store_assigned,
        facts.identity_granted,
        facts.linked,
        facts.upstream_allowed,
        facts.capability_verified,
    )
    revisions = (
        facts.grant_revision,
        facts.capability_revision,
        facts.upstream_revision,
        facts.link_revision,
        facts.connection_generation,
    )
    if any(type(value) is not bool for value in checks) or any(
        type(value) is not int or value < 0 or value > 9223372036854775807
        for value in revisions
    ):
        return False
    if (
        not facts.member
        or type(facts.role) is not str
        or facts.role not in {"OWNER", "MANAGER", "STAFF"}
    ):
        return False
    if type(facts.action) is not str or facts.action not in _ACTIONS:
        return False
    target = facts.target
    if facts.action == "account.login":
        return (
            target.identity_id is None and facts.grant_id is None and not any(revisions)
        )
    if target.identity_id is None or type(facts.grant_id) is not UUID:
        return False
    if not all(
        (facts.identity_granted, facts.upstream_allowed, facts.capability_verified)
    ):
        return False
    if any(
        value <= 0
        for value in (
            facts.grant_revision,
            facts.capability_revision,
            facts.upstream_revision,
            facts.connection_generation,
        )
    ):
        return False
    if (
        type(facts.valid_until) is not datetime
        or facts.valid_until.tzinfo is None
        or facts.valid_until.utcoffset() is None
        or facts.valid_until <= now
    ):
        return False
    if facts.action == "account.read":
        return target.device_id is None and target.panel_id is None
    if target.domain == "TYCO":
        return facts.action == "panel.read" and target.panel_id is not None
    return (
        facts.action in {"device.read", "media.live"}
        and target.device_id is not None
        and facts.store_assigned
        and facts.linked
        and facts.link_revision > 0
        and (facts.action != "media.live" or target.channel_id is not None)
    )


@dataclass(frozen=True, slots=True)
class AuthorizedScope:
    tenant_id: UUID
    actor_id: UUID
    target: DomainTarget
    action: str
    _facts: AuthorizationFacts = field(repr=False)
    _seal: object = field(repr=False, compare=False)


def authorize(
    session: Session, target: DomainTarget, action: str, *, now: datetime | None = None
) -> AuthorizedScope:
    """Read checked metadata using the consumed PID/XID context, never caller IDs."""
    if (
        type(target) is not DomainTarget
        or type(action) is not str
        or action not in _ACTIONS
    ):
        raise AuthorizationDenied()
    row = (
        session.execute(
            text(
                "SELECT * FROM public.wso_authorize_domain(:domain,:identity_id,"
                ":device_id,:channel_id,:store_id,:panel_id,:action)"
            ),
            {
                "domain": target.domain,
                "identity_id": target.identity_id,
                "device_id": target.device_id,
                "channel_id": target.channel_id,
                "store_id": target.store_id,
                "panel_id": target.panel_id,
                "action": action,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise AuthorizationDenied()
    try:
        data = dict(row)
        selected = DomainTarget(
            **{
                key: data.pop(key)
                for key in (
                    "domain",
                    "identity_id",
                    "device_id",
                    "channel_id",
                    "store_id",
                    "panel_id",
                )
            }
        )
        facts = AuthorizationFacts(target=selected, **data)
    except (TypeError, ValueError, KeyError):
        raise AuthorizationDenied() from None
    if (
        selected != target
        or facts.action != action
        or not decide(facts, now=now or datetime.now(UTC))
    ):
        raise AuthorizationDenied()
    return AuthorizedScope(
        facts.tenant_id, facts.actor_id, selected, action, facts, _SEAL
    )


def recheck(
    session: Session, scope: AuthorizedScope, *, now: datetime | None = None
) -> AuthorizedScope:
    """Fail closed on revoked/replaced authority; never reuse a cached decision."""
    if type(scope) is not AuthorizedScope or scope._seal is not _SEAL:
        raise AuthorizationDenied()
    current = authorize(session, scope.target, scope.action, now=now)
    if current != scope:
        raise AuthorizationDenied()
    return current
