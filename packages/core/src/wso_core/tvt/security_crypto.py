"""Private native AES math and scoped consistency; no authority or persistence.

The trusted server supplies temporary MD5/provider-code/previous-key text through
the config port. Nothing is derived from a USER token. Removing references is not
a claim of Python memory zeroing. An admission failure is terminal for this state.
"""

from __future__ import annotations

import base64
import hashlib
import threading
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef

from .account_client import _scope
from .account_protocol import (
    AccountProtocolError,
    AccountResponse,
    _integer,
    _text,
    parse_response,
    private_json,
)
from .ports import PrivateToken


def _fail() -> AccountProtocolError:
    return AccountProtocolError("Security key unavailable.")


def _bytes(value: bytes) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= 4096:
        raise _fail()
    return value


def _decode(value: bytes) -> bytes:
    result: bytes | None = None
    try:
        decoded = base64.b64decode(_bytes(value), validate=True)
        if base64.b64encode(decoded) == value:
            result = decoded
    except Exception:  # noqa: BLE001 -- discard private decoder context
        result = None
    if result is None:
        raise _fail() from None
    return result


def _material(text: bytes) -> bytes:
    value = _bytes(text)
    material = _decode(value) if value.endswith(b"=") else value
    if len(material) not in (16, 24, 32):
        raise _fail()
    return material


def _sid(value: bytes) -> bytes:
    value = _bytes(value)
    return _decode(value) if value.endswith(b"=") else value


def derive_key_text(sid: bytes, temporary_text: bytes) -> bytes:
    """Source math: trailing '=' heuristic, zero extension, ECB, whole Base64.

    This private math helper retains native incomplete-block behavior. Admission
    below rejects incomplete ciphertext, malformed representation and final keys.
    """
    ciphertext = _sid(sid)
    ciphertext += bytes((-len(ciphertext)) % 16)
    decryptor = Cipher(
        algorithms.AES(_material(temporary_text)), modes.ECB()
    ).decryptor()
    return base64.b64encode(decryptor.update(ciphertext) + decryptor.finalize())


def encrypt_password(raw_password: str, key_text: bytes) -> str:
    password = _text(raw_password, nonempty=True)
    digest = (
        hashlib.md5(password.encode("utf-8"), usedforsecurity=False)
        .hexdigest()
        .encode("ascii")
    )
    encryptor = Cipher(algorithms.AES(_material(key_text)), modes.ECB()).encryptor()
    # Exactly two blocks; standard Base64 length 4*ceil(32/3) == 44.
    return base64.b64encode(encryptor.update(digest) + encryptor.finalize()).decode(
        "ascii"
    )


@dataclass(frozen=True, slots=True, repr=False)
class KeyBinding:
    scope: AccountScope
    identity: TvtIdentityRef
    generation: int
    token_id: str


class SecurityKeyConfig(Protocol):
    """Server-only admitted secret supply; never browser configuration/defaults.

    Return exact temporary lowercase MD5 text or previously admitted key text,
    encoded as bytes, scoped to this identity/region/brand/generation/token-ID.
    No unscoped native persistent-key fallback is permitted.
    """

    def temporary_key(self, binding: KeyBinding) -> bytes: ...


def _checked(binding: KeyBinding, token: PrivateToken) -> bytes:
    if type(binding) is not KeyBinding or type(token) is not PrivateToken:
        raise _fail()
    scope = _scope(binding.scope, AccountScope)
    identity = _scope(binding.identity, TvtIdentityRef)
    if (
        scope.tenant_id != identity.tenant_id
        or scope.actor_user_id != identity.actor_user_id
        or scope.identity_id != identity.identity_id
        or token.kind is not TokenKind.USER
        or _scope(token.identity, TvtIdentityRef) != identity
    ):
        raise _fail()
    _integer(binding.generation, 1, 2**63 - 1)
    _text(binding.token_id, nonempty=True)
    return hashlib.sha256(_text(token.value, nonempty=True).encode("utf-8")).digest()


class SecurityKeyState:
    def __init__(
        self, binding: KeyBinding, token: PrivateToken, config: SecurityKeyConfig
    ) -> None:
        checked: bytes | None = None
        temporary: bytes | None = None
        try:
            checked = _checked(binding, token)
            temporary = _bytes(config.temporary_key(binding))
            _material(temporary)
        except Exception:  # noqa: BLE001 -- no config exceptions or secrets escape
            checked = None
        if checked is None or temporary is None:
            raise _fail() from None
        self._binding = KeyBinding(
            _scope(binding.scope, AccountScope),
            _scope(binding.identity, TvtIdentityRef),
            binding.generation,
            binding.token_id,
        )
        self._token_digest = checked
        self._temporary: bytes | None = temporary
        self._key: bytes | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _clear(self) -> None:
        self._key = self._temporary = None
        self._closed = True

    def close(self) -> None:
        with self._lock:
            self._clear()

    def _match(self, binding: KeyBinding, token: PrivateToken) -> None:
        if (
            self._closed
            or _checked(binding, token) != self._token_digest
            or binding != self._binding
        ):
            raise _fail()

    def admit(
        self, binding: KeyBinding, token: PrivateToken, response: AccountResponse
    ) -> None:
        failed = False
        with self._lock:
            try:
                self._match(binding, token)
                if type(response) is not AccountResponse:
                    raise _fail()
                parsed = parse_response(response.http_status, response.private_body)
                if parsed.native_msgcode != response.native_msgcode:
                    raise _fail()
                response.require_success()
                data = private_json(response.private_body).get("data")
                if type(data) is not dict:
                    raise _fail()
                sid = _text(data.get("sid"), nonempty=True).encode("utf-8")
                token_id = _text(data.get("tokenId"), nonempty=True)
                ciphertext = _sid(sid)
                if (
                    token_id != binding.token_id
                    or not ciphertext
                    or len(ciphertext) % 16
                ):
                    raise _fail()
                if self._key is None:
                    if self._temporary is None:
                        raise _fail()
                    derived = derive_key_text(sid, self._temporary)
                    _material(derived)
                    self._key, self._temporary = derived, None
                # Same nonempty token-ID ignores changed SID after shape checks.
            except Exception:  # noqa: BLE001 -- fail closed without native stale fallback
                self._clear()
                failed = True
        if failed:
            raise _fail() from None

    def encrypt(
        self, binding: KeyBinding, token: PrivateToken, raw_password: str
    ) -> str:
        result: str | None = None
        with self._lock:
            try:
                self._match(binding, token)
                if self._key is None:
                    raise _fail()
                result = encrypt_password(raw_password, self._key)
            except Exception:  # noqa: BLE001 -- discard all private failure context
                self._clear()
        if result is None:
            raise _fail() from None
        return result
