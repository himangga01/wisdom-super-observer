"""Post-login domain credential admission into the existing T04 worker store."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from wso_contracts.tvt.identity import TokenKind

from wso_core.secrets import SecretRejected
from wso_core.tvt.authorization import AuthorizationDenied, AuthorizedScope, recheck

_PURPOSES = frozenset({"account.read", "device.read", "media.live", "panel.read"})


class CredentialProvider:
    """Internal only. SQL derives authority; Python objects cannot mint it.

    Commit the caller transaction before handing the opaque string to
    WorkerSecretStore. Never return handles or callback secrets to a browser.
    Pre-login and job execution require separately owned admission paths.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def with_handle(
        self, scope: AuthorizedScope, purpose: str, deadline: datetime
    ) -> str:
        from wso_core.worker import JOB_STEP_ACTIVE

        if (
            JOB_STEP_ACTIVE.get()
            or type(scope) is not AuthorizedScope
            or type(purpose) is not str
            or purpose not in _PURPOSES
            or purpose != scope.action
            or scope.target.identity_id is None
            or type(deadline) is not datetime
            or deadline.tzinfo is None
            or deadline.utcoffset() is None
            or deadline <= datetime.now(UTC)
        ):
            raise SecretRejected()
        try:
            current = recheck(self._session, scope)
            expected = asdict(current._facts)
            expected.update(expected.pop("target"))
            handle: str | None = self._session.execute(
                text(
                    "SELECT public.wso_issue_domain_connection_handle(CAST(:expected AS jsonb),:purpose,:deadline)"
                ),
                {
                    "expected": json.dumps(
                        expected,
                        default=lambda value: (
                            value.isoformat()
                            if isinstance(value, datetime)
                            else str(value)
                        ),
                    ),
                    "purpose": purpose,
                    "deadline": deadline,
                },
            ).scalar_one()
        except (AuthorizationDenied, DBAPIError):
            raise SecretRejected() from None
        if type(handle) is not str or len(handle) != 64:
            raise SecretRejected()
        return handle

    def with_account_ticket(
        self,
        scope: AuthorizedScope,
        purpose: str,
        region: str,
        brand: str,
        *,
        identity_id: UUID | None = None,
        kind: TokenKind = TokenKind.USER,
        generation: int = 0,
    ) -> str:
        """W05 typed admission; no untyped handle fallback for managed tokens."""
        from wso_core.worker import JOB_STEP_ACTIVE

        prelogin = purpose in {"login", "image", "check"}
        action = "account.login" if prelogin or purpose == "logout" else "account.read"
        if (
            JOB_STEP_ACTIVE.get()
            or type(scope) is not AuthorizedScope
            or purpose not in {"login", "image", "check", "profile", "renew", "logout"}
            or scope.action != action
            or type(kind) is not TokenKind
            or kind is not TokenKind.USER
            or type(generation) is not int
            or generation < 0
            or (prelogin and (identity_id is not None or generation != 0))
            or (not prelogin and (type(identity_id) is not UUID or generation < 1))
            or (action == "account.read" and scope.target.identity_id != identity_id)
        ):
            raise SecretRejected()
        try:
            recheck(self._session, scope)
            ticket: str | None = self._session.execute(
                text(
                    "SELECT public.wso_tvt_account_issue(:purpose,:region,:brand,:identity,:kind,:generation)"
                ),
                {
                    "purpose": purpose,
                    "region": region,
                    "brand": brand,
                    "identity": identity_id,
                    "kind": kind.value,
                    "generation": generation,
                },
            ).scalar_one()
        except (AuthorizationDenied, DBAPIError):
            raise SecretRejected() from None
        if type(ticket) is not str or len(ticket) != 64:
            raise SecretRejected()
        return ticket
