"""Worker-only T04 encrypted tokens with SQL authority and renewal fencing.

The API only issues opaque tickets. This module is constructed in a separate
worker process with the existing wso_connection_worker role and key provider.
No caller-selected IDs can decrypt a value; every use is a checked callback.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from wso_contracts.tvt.identity import TokenKind

from wso_core.secrets import Envelope, KeyProvider, SecretCipher
from wso_core.tvt.account_projection import AccountFailure

_REMAINING: ContextVar[Callable[[], int] | None] = ContextVar(
    "tvt_account_remaining", default=None
)


@contextmanager
def token_budget(remaining: Callable[[], int] | None) -> Iterator[None]:
    # Capture the parent before setting the child. Looking up the ContextVar
    # inside the combined callback would recurse and lose transport authority.
    parent = _REMAINING.get()
    combined = remaining
    if parent is not None and remaining is not None:

        def both() -> int:
            return min(parent(), remaining())

        combined = both
    # None is an explicit detach for separately bounded local logout cleanup.
    marker = _REMAINING.set(combined)
    try:
        yield
    finally:
        _REMAINING.reset(marker)


def remaining_budget() -> int | None:
    remaining = _REMAINING.get()
    return remaining() if remaining else None


def _apply_budget(db: Connection) -> None:
    milliseconds = remaining_budget()
    if milliseconds is not None:
        db.execute(
            text(
                "SELECT set_config('statement_timeout',:statement,true),set_config('lock_timeout',:lock,true)"
            ),
            {
                "statement": str(min(milliseconds, 10000)),
                "lock": str(min(milliseconds, 3000)),
            },
        )


def require_user_kind(kind: object) -> None:
    if type(kind) is not TokenKind or kind is not TokenKind.USER:
        raise AccountFailure("CAPABILITY_UNSUPPORTED", 409)


def private_text(value: bytes) -> str:
    result = None
    try:
        result = value.decode("utf-8")
    except UnicodeError:
        pass
    if not result or len(result.encode("utf-8")) > 4096:
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502) from None
    return result


@dataclass(frozen=True, slots=True)
class AccountLease:
    value: str = field(repr=False)
    tenant_id: UUID
    actor_id: UUID
    identity_id: UUID | None
    region: str
    brand: str
    generation: int
    purpose: str


class TokenVault:
    def __init__(self, worker_url: str, provider: KeyProvider) -> None:
        if not worker_url.startswith("postgresql+psycopg://"):
            raise AccountFailure()
        self._engine = create_engine(
            worker_url,
            hide_parameters=True,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 5,
                "options": "-c statement_timeout=10000 -c lock_timeout=3000",
            },
        )
        self._cipher = SecretCipher(provider)

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        failed = False
        try:
            remaining_budget()
            with self._engine.begin() as db:
                _apply_budget(db)
                if (
                    db.execute(text("SELECT current_user")).scalar_one()
                    != "wso_connection_worker"
                ):
                    raise AccountFailure()
                yield db
                remaining_budget()
        except SQLAlchemyError:
            failed = True
        if failed:
            raise AccountFailure() from None

    def redeem(self, ticket: str, purpose: str) -> AccountLease:
        lease = secrets.token_hex(32)
        with self.transaction() as db:
            accepted: bool = db.execute(
                text("SELECT public.wso_tvt_account_redeem(:ticket,:lease)"),
                {"ticket": ticket, "lease": lease},
            ).scalar_one()
        if not accepted:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        with self.transaction() as db:
            row = (
                db.execute(
                    text(
                        "SELECT * FROM public.wso_tvt_account_context(:lease,:purpose)"
                    ),
                    {"lease": lease, "purpose": purpose},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            return AccountLease(lease, **dict(row), purpose=purpose)

    def recheck(self, db: Connection, lease: AccountLease) -> None:
        row = (
            db.execute(
                text("SELECT * FROM public.wso_tvt_account_context(:lease,:purpose)"),
                {"lease": lease.value, "purpose": lease.purpose},
            )
            .mappings()
            .one_or_none()
        )
        if row is None or any(row[key] != getattr(lease, key) for key in row):
            raise AccountFailure("ACCOUNT_DENIED", 404)

    def use[T](self, lease: AccountLease, callback: Callable[[bytes], T]) -> T:
        with self.transaction() as db:
            self.recheck(db, lease)
            row = (
                db.execute(
                    text(
                        "SELECT * FROM public.wso_tvt_account_secret(:lease,:purpose)"
                    ),
                    {"lease": lease.value, "purpose": lease.purpose},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            value = self._cipher.open(
                row["tenant_id"],
                row["connection_id"],
                row["version_id"],
                Envelope(row["nonce"], row["ciphertext"]),
            )
            try:
                result = callback(value)
                self.recheck(db, lease)
                return result
            finally:
                del value

    def publish(self, lease: AccountLease, user: str, p2p: str) -> UUID:
        identity, connection, version = uuid4(), uuid4(), uuid4()
        envelope = self._cipher.seal(
            lease.tenant_id, connection, version, user.encode()
        )
        other_connection, other_version = (uuid4(), uuid4()) if p2p else (None, None)
        other = (
            self._cipher.seal(
                lease.tenant_id, other_connection, other_version, p2p.encode()
            )
            if other_connection and other_version
            else None
        )
        with self.transaction() as db:
            result: UUID | None = db.execute(
                text(
                    "SELECT public.wso_tvt_account_publish(:lease,:identity,:connection,:version,:nonce,:cipher,:other_connection,:other_version,:other_nonce,:other_cipher)"
                ),
                {
                    "lease": lease.value,
                    "identity": identity,
                    "connection": connection,
                    "version": version,
                    "nonce": envelope.nonce,
                    "cipher": envelope.ciphertext,
                    "other_connection": other_connection,
                    "other_version": other_version,
                    "other_nonce": other.nonce if other else None,
                    "other_cipher": other.ciphertext if other else None,
                },
            ).scalar_one()
        if result != identity:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return identity

    def save_challenge(self, lease: AccountLease, image_id: str) -> UUID:
        challenge, connection, version = uuid4(), uuid4(), uuid4()
        envelope = self._cipher.seal(
            lease.tenant_id, connection, version, image_id.encode()
        )
        with self.transaction() as db:
            result: UUID | None = db.execute(
                text(
                    "SELECT public.wso_tvt_challenge_publish(:lease,:id,:connection,:version,:nonce,:cipher)"
                ),
                {
                    "lease": lease.value,
                    "id": challenge,
                    "connection": connection,
                    "version": version,
                    "nonce": envelope.nonce,
                    "cipher": envelope.ciphertext,
                },
            ).scalar_one()
        if result != challenge:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return challenge

    def consume_challenge(self, lease: AccountLease, challenge_id: UUID) -> str:
        # Commit consumption before decrypt/transport: failures cannot replay it.
        with self.transaction() as db:
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_tvt_challenge_consume(:lease,:id)"),
                    {"lease": lease.value, "id": challenge_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise AccountFailure("CHALLENGE_EXPIRED", 409)
        return private_text(
            self._cipher.open(
                row["tenant_id"],
                row["connection_id"],
                row["version_id"],
                Envelope(row["nonce"], row["ciphertext"]),
            )
        )

    def renew(
        self, lease: AccountLease, callback: Callable[[bytes], str | None]
    ) -> int:
        # One physical connection owns the session advisory lock across claim
        # commit and bounded callback. A process crash releases that lock but
        # retains INFLIGHT, so a successor reports UNKNOWN and does not retry.
        attempt = uuid4()
        failed = False
        try:
            remaining_budget()
            with self._engine.connect() as db:
                _apply_budget(db)
                if (
                    db.execute(text("SELECT current_user")).scalar_one()
                    != "wso_connection_worker"
                ):
                    raise AccountFailure()
                key = f"wso-account:{lease.tenant_id}:{lease.identity_id}:USER"
                db.execute(
                    text("SELECT pg_advisory_lock(hashtextextended(:key,0))"),
                    {"key": key},
                )
                db.commit()
                try:
                    with db.begin():
                        _apply_budget(db)
                        claim: str = db.execute(
                            text(
                                "SELECT public.wso_tvt_account_renew_claim(:lease,:attempt)"
                            ),
                            {"lease": lease.value, "attempt": attempt},
                        ).scalar_one()
                    if claim.startswith("CURRENT:"):
                        return int(claim.split(":")[1])
                    if claim != "CLAIMED":
                        raise AccountFailure(
                            "RENEWAL_OUTCOME_UNKNOWN"
                            if claim == "UNKNOWN"
                            else "ACCOUNT_DENIED",
                            409,
                        )
                    with db.begin():
                        _apply_budget(db)
                        self.recheck(db, lease)
                        row = (
                            db.execute(
                                text(
                                    "SELECT * FROM public.wso_tvt_account_secret(:lease,'renew')"
                                ),
                                {"lease": lease.value},
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if row is None:
                            raise AccountFailure("ACCOUNT_DENIED", 404)
                        value = self._cipher.open(
                            row["tenant_id"],
                            row["connection_id"],
                            row["version_id"],
                            Envelope(row["nonce"], row["ciphertext"]),
                        )
                        try:
                            replacement = callback(value)
                        finally:
                            del value
                        version = uuid4() if replacement else None
                        envelope = (
                            self._cipher.seal(
                                row["tenant_id"],
                                row["connection_id"],
                                version,
                                replacement.encode(),
                            )
                            if version and replacement
                            else None
                        )
                        _apply_budget(db)
                        generation: int | None = db.execute(
                            text(
                                "SELECT public.wso_tvt_account_renew_publish(:lease,:attempt,:version,:nonce,:cipher)"
                            ),
                            {
                                "lease": lease.value,
                                "attempt": attempt,
                                "version": version,
                                "nonce": envelope.nonce if envelope else None,
                                "cipher": envelope.ciphertext if envelope else None,
                            },
                        ).scalar_one()
                        if generation is None:
                            raise AccountFailure("ACCOUNT_DENIED", 404)
                        remaining_budget()
                        return int(generation)
                finally:
                    db.rollback()
                    db.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                        {"key": key},
                    )
                    db.commit()
        except SQLAlchemyError:
            failed = True
        if failed:
            raise AccountFailure() from None
        raise AccountFailure()

    def revoke(self, lease: AccountLease) -> None:
        with self.transaction() as db:
            if (
                db.execute(
                    text("SELECT public.wso_tvt_account_revoke(:lease)"),
                    {"lease": lease.value},
                ).scalar_one()
                is not True
            ):
                raise AccountFailure("ACCOUNT_DENIED", 404)
