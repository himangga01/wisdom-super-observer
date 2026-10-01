"""API account ticket issuance, using the existing consumed tenant context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from wso_contracts.tvt.account import AccountSelection
from wso_contracts.tvt.identity import TokenKind
from wso_core.secrets import SecretRejected
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.authorization import AuthorizationDenied, DomainTarget, authorize
from wso_core.tvt.credentials import CredentialProvider


@dataclass(frozen=True, slots=True)
class LocalIdentity:
    identity_id: UUID
    region: str
    brand: str
    generation: int


class IdentityService:
    def __init__(
        self, session: Session, remaining: Callable[[], int] | None = None
    ) -> None:
        self.session, self.remaining = session, remaining

    def _bound(self) -> None:
        milliseconds = min(10000, self.remaining()) if self.remaining else 10000
        self.session.execute(
            text("SELECT set_config('statement_timeout',:deadline,true)"),
            {"deadline": str(milliseconds)},
        )

    def describe(self, identity_id: UUID) -> LocalIdentity:
        self._bound()
        row = (
            self.session.execute(
                text("SELECT * FROM public.wso_tvt_account_describe(:identity)"),
                {"identity": identity_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return LocalIdentity(**dict(row))

    def issue(
        self,
        purpose: str,
        selection: AccountSelection,
        *,
        identity_id: UUID | None = None,
        kind: TokenKind = TokenKind.USER,
        generation: int = 0,
    ) -> str:
        # Structural scopes alone confer no authority. SQL reads PID/XID plus
        # current membership and, after login, exact account grants/generation.
        action = "account.read" if purpose in {"profile", "renew"} else "account.login"
        self._bound()
        try:
            scope = authorize(
                self.session,
                DomainTarget(
                    "TVT", identity_id=identity_id if action == "account.read" else None
                ),
                action,
            )
            return CredentialProvider(self.session).with_account_ticket(
                scope,
                purpose,
                selection.region,
                selection.brand,
                identity_id=identity_id,
                kind=kind,
                generation=generation,
            )
        except (SecretRejected, AuthorizationDenied):
            pass
        raise AccountFailure("ACCOUNT_DENIED", 404) from None

    def close(self, identity_id: UUID) -> None:
        self._bound()
        if (
            self.session.execute(
                text("SELECT public.wso_tvt_account_close(:identity)"),
                {"identity": identity_id},
            ).scalar_one()
            is not True
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
