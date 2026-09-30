"""Authenticated credential encryption and restricted worker capabilities.

Key providers are deployment dependencies. The file provider is for local use;
production must inject its secret-manager/KMS integration.
"""

from __future__ import annotations

import os
import secrets as random_secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class SecretRejected(Exception):
    def __init__(self) -> None:
        super().__init__("credential access unavailable")


class KeyProvider(Protocol):
    def encryption_key(self) -> bytes: ...


class FileKeyProvider:
    def __init__(self, path: Path) -> None:
        self._path = path

    def encryption_key(self) -> bytes:
        try:
            key = self._path.read_bytes()
            if len(key) != 32:
                raise SecretRejected()
            return key
        except OSError:
            raise SecretRejected() from None


@dataclass(frozen=True)
class Envelope:
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)


class SecretCipher:
    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider

    def _aes(self) -> AESGCM:
        key = self._provider.encryption_key()
        if len(key) != 32:
            raise SecretRejected()
        return AESGCM(key)

    @staticmethod
    def _aad(tenant_id: UUID, connection_id: UUID, version_id: UUID) -> bytes:
        return (
            b"wso-connection-v1\x00"
            + tenant_id.bytes
            + connection_id.bytes
            + version_id.bytes
        )

    def seal(
        self, tenant_id: UUID, connection_id: UUID, version_id: UUID, plaintext: bytes
    ) -> Envelope:
        nonce = os.urandom(12)
        encrypted = self._aes().encrypt(
            nonce, plaintext, self._aad(tenant_id, connection_id, version_id)
        )
        return Envelope(nonce, encrypted)

    def open(
        self, tenant_id: UUID, connection_id: UUID, version_id: UUID, envelope: Envelope
    ) -> bytes:
        try:
            return self._aes().decrypt(
                envelope.nonce,
                envelope.ciphertext,
                self._aad(tenant_id, connection_id, version_id),
            )
        except (InvalidTag, ValueError):
            raise SecretRejected() from None


T = TypeVar("T")


class WorkerSecretStore:
    """Worker role alone redeems scoped capabilities; no arbitrary-ID decrypt."""

    def __init__(self, url: str, provider: KeyProvider) -> None:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("explicit worker PostgreSQL URL required")
        self._factory = sessionmaker(
            create_engine(url, hide_parameters=True, pool_pre_ping=True)
        )
        self._cipher = SecretCipher(provider)

    @staticmethod
    def _check_role(db: Session) -> None:
        if (
            db.execute(text("SELECT current_user")).scalar_one()
            != "wso_connection_worker"
        ):
            raise SecretRejected()

    def with_secret(self, handle: str) -> WorkerLease:
        token = random_secrets.token_hex(32)
        # Redemption commits before any caller work: caller rollback cannot replay.
        with self._factory.begin() as db:
            self._check_role(db)
            accepted: bool = db.execute(
                text("SELECT public.wso_redeem_connection_handle(:handle,:lease)"),
                {"handle": handle, "lease": token},
            ).scalar_one()
        if not accepted:
            raise SecretRejected()
        return WorkerLease(self, token)


class WorkerLease:
    def __init__(self, store: WorkerSecretStore, token: str) -> None:
        self._store, self._token = store, token

    def use(self, callback: Callable[[bytes], T]) -> T:
        """Keep owner/connection shared locks until bounded credential use ends.

        Trusted callbacks must not retain credentials. Every use revalidates;
        lifecycle mutations wait for an already-authorized use to finish.
        """
        with self._store._factory.begin() as db:
            self._store._check_role(db)
            row = db.execute(
                text("SELECT * FROM public.wso_use_connection_lease(:lease)"),
                {"lease": self._token},
            ).first()
            if row is None:
                raise SecretRejected()
            value = self._store._cipher.open(
                row.tenant_id,
                row.connection_id,
                row.version_id,
                Envelope(row.nonce, row.ciphertext),
            )
            try:
                return callback(value)
            finally:
                del value
