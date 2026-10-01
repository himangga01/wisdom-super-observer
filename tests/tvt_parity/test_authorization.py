"""Local decisions are independent of database authority; PG tests prove that gate."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

NOW = datetime(2026, 10, 2, tzinfo=UTC)
IDS = [UUID(int=i) for i in range(1, 12)]


def facts():
    from wso_core.tvt.authorization import AuthorizationFacts, DomainTarget

    return AuthorizationFacts(
        tenant_id=IDS[0],
        actor_id=IDS[1],
        role="STAFF",
        target=DomainTarget("TVT", IDS[2], IDS[3], IDS[4], IDS[5]),
        action="media.live",
        member=True,
        store_assigned=True,
        identity_granted=True,
        linked=True,
        upstream_allowed=True,
        capability_verified=True,
        grant_id=IDS[6],
        grant_revision=1,
        capability_revision=2,
        upstream_revision=3,
        link_revision=4,
        connection_generation=5,
        valid_until=NOW + timedelta(minutes=1),
    )


def test_restricted_channel_intersection_allows():
    from wso_core.tvt.authorization import decide

    assert decide(facts(), now=NOW)


@pytest.mark.parametrize(
    "field",
    [
        "member",
        "store_assigned",
        "identity_granted",
        "linked",
        "upstream_allowed",
        "capability_verified",
    ],
)
@pytest.mark.parametrize("role", ["STAFF", "MANAGER", "OWNER"])
def test_no_role_bypasses_missing_intersection(field, role):
    from wso_core.tvt.authorization import decide

    assert not decide(replace(facts(), role=role, **{field: False}), now=NOW)


@pytest.mark.parametrize(
    "action", ["unknown", "panel.read", "account.read", "account.login", "MEDIA.LIVE"]
)
def test_unknown_or_wrong_target_action_denies(action):
    from wso_core.tvt.authorization import decide

    assert not decide(replace(facts(), action=action), now=NOW)


def test_null_channel_cannot_authorize_media():
    from wso_core.tvt.authorization import decide

    f = facts()
    assert not decide(replace(f, target=replace(f.target, channel_id=None)), now=NOW)


def test_expired_and_naive_observations_deny():
    from wso_core.tvt.authorization import decide

    for value in (NOW, NOW - timedelta(seconds=1), NOW.replace(tzinfo=None)):
        assert not decide(replace(facts(), valid_until=value), now=NOW)


def test_native_types_do_not_coerce_authority():
    from wso_core.tvt.authorization import DomainTarget, decide

    for change in (
        {"member": 1},
        {"grant_revision": True},
        {"grant_revision": 0},
        {"actor_id": str(IDS[1])},
        {"role": "ADMIN"},
    ):
        assert not decide(replace(facts(), **change), now=NOW)
    with pytest.raises(ValueError, match="invalid domain target"):
        DomainTarget("TVT", str(IDS[2]))


def test_prelogin_has_no_invented_identity_or_store():
    from wso_core.tvt.authorization import DomainTarget, decide

    f = replace(
        facts(),
        target=DomainTarget("TVT"),
        action="account.login",
        store_assigned=False,
        identity_granted=False,
        linked=False,
        upstream_allowed=False,
        capability_verified=False,
        grant_id=None,
        grant_revision=0,
        capability_revision=0,
        upstream_revision=0,
        link_revision=0,
        connection_generation=0,
        valid_until=None,
    )
    assert decide(f, now=NOW)
    assert not decide(replace(f, member=False), now=NOW)
    assert not decide(replace(f, target=DomainTarget("TVT", IDS[2])), now=NOW)


def test_tyco_panel_is_separate_and_still_requires_grants():
    from wso_core.tvt.authorization import DomainTarget, decide

    f = replace(
        facts(),
        target=DomainTarget("TYCO", IDS[2], panel_id=IDS[7]),
        action="panel.read",
        store_assigned=False,
        linked=False,
        link_revision=0,
    )
    assert decide(f, now=NOW)
    assert not decide(replace(f, identity_granted=False, role="OWNER"), now=NOW)
    with pytest.raises(ValueError, match="invalid domain target"):
        DomainTarget("TYCO", IDS[2], device_id=IDS[3], store_id=IDS[5])


class Rows:
    def __init__(self, rows):
        self.rows = iter(rows)

    def execute(self, statement, parameters):
        self.current = next(self.rows)
        return self

    def mappings(self):
        return self

    def one_or_none(self):
        return self.current


def row(f):
    from dataclasses import asdict

    data = asdict(f)
    target = data.pop("target")
    data.update(target)
    return data


def test_authorizer_seals_response_and_rechecks_revocation():
    from wso_core.tvt.authorization import AuthorizationDenied, authorize, recheck

    f = facts()
    session = Rows([row(f), row(f), None])
    scope = authorize(session, f.target, f.action, now=NOW)
    assert (scope.tenant_id, scope.actor_id, scope.target) == (IDS[0], IDS[1], f.target)
    assert "capability_revision" not in repr(scope)
    assert recheck(session, scope, now=NOW) == scope
    with pytest.raises(AuthorizationDenied, match="domain authorization denied"):
        recheck(session, scope, now=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": IDS[8]},
        {"tenant_id": IDS[8]},
        {"grant_revision": 2},
        {"capability_revision": 8},
        {"upstream_revision": 8},
        {"link_revision": 8},
        {"connection_generation": 8},
    ],
)
def test_recheck_rejects_scope_or_revision_replacement(change):
    from wso_core.tvt.authorization import AuthorizationDenied, authorize, recheck

    f = facts()
    session = Rows([row(f), row(replace(f, **change))])
    scope = authorize(session, f.target, f.action, now=NOW)
    with pytest.raises(AuthorizationDenied):
        recheck(session, scope, now=NOW)


def test_caller_object_cannot_skip_database_and_wrong_row_denies():
    from wso_core.tvt.authorization import AuthorizationDenied, authorize, recheck

    with pytest.raises(AuthorizationDenied):
        recheck(Rows([]), object(), now=NOW)
    f = facts()
    with pytest.raises(AuthorizationDenied):
        authorize(
            Rows([row(f)]), replace(f.target, channel_id=IDS[8]), f.action, now=NOW
        )
