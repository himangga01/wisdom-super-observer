"""Unbound private successful SID evidence, never protected current authority.

Only the existing AccountClient owns transport and status parsing. A worker must
publish actual USER credentials and check current actor/identity/generation before
binding this evidence. Constructors and structural checks cannot grant access.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import cast
from uuid import UUID

from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef

from .account_client import _renew, _scope
from .account_protocol import (
    AccountProtocolError,
    AccountResponse,
    _integer,
    _text,
    parse_login,
    parse_response,
    private_json,
)
from .ports import AccountRenewal, AccountResult, AccountTokens, PrivateToken
from .security_crypto import KeyBinding, SecurityKeyState, _checked

type ScopeSnapshot = tuple[UUID, UUID, str, str, UUID | None]
type IdentitySnapshot = tuple[UUID, UUID, UUID]


def _fail() -> AccountProtocolError:
    return AccountProtocolError("Private SID capture unavailable.")


def _private[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Discard validation/decoder contexts, including private JSON and inputs."""

    @wraps(function)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        failed = False
        result: R | None = None
        try:
            result = function(*args, **kwargs)
        except Exception:  # noqa: BLE001 -- fixed private failure only
            failed = True
        if failed:
            raise _fail() from None
        return cast(R, result)

    return checked


def _scope_snapshot(scope: AccountScope) -> ScopeSnapshot:
    checked = _scope(scope, AccountScope)
    return (
        checked.tenant_id,
        checked.actor_user_id,
        checked.region,
        checked.brand,
        checked.identity_id,
    )


def _identity_snapshot(identity: TvtIdentityRef) -> IdentitySnapshot:
    checked = _scope(identity, TvtIdentityRef)
    return checked.tenant_id, checked.actor_user_id, checked.identity_id


def _token_digest(token: PrivateToken, identity: IdentitySnapshot) -> bytes:
    if (
        type(token) is not PrivateToken
        or token.kind is not TokenKind.USER
        or _identity_snapshot(token.identity) != identity
    ):
        raise _fail()
    return _digest(_text(token.value, nonempty=True))


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _known(
    scope: ScopeSnapshot, identity: TvtIdentityRef | None
) -> IdentitySnapshot | None:
    known = _identity_snapshot(identity) if identity is not None else None
    if (
        known is not None
        and (known[:2] != scope[:2] or scope[4] not in (None, known[2]))
        or scope[4] is not None
        and known is None
    ):
        raise _fail()
    return known


def _response[T: AccountTokens | AccountRenewal](
    result: AccountResult[T], kind: type[T]
) -> AccountResponse:
    if (
        type(result) is not AccountResult
        or not result.ok
        or type(result.value) is not kind
        or type(result.native_msgcode) is not int
        or type(result.value.private_body) is not bytes
    ):
        raise _fail()
    parsed = parse_response(result.http_status, result.value.private_body)
    if parsed.native_msgcode != result.native_msgcode:
        raise _fail()
    parsed.require_success()
    return parsed


def _capture(
    scope: ScopeSnapshot,
    known: IdentitySnapshot | None,
    digest: bytes,
    response: AccountResponse,
) -> UnboundSidCapture | None:
    # Native createCallbackJson only invokes SID extraction in object-data branch.
    # A JSON-text string is not that branch, and no second parse is performed.
    data = private_json(response.private_body).get("data")
    if data is None:
        return None
    if type(data) is not dict:
        raise _fail()
    sid = _text(data["sid"]) if "sid" in data else ""
    token_id = _text(data["tokenId"]) if "tokenId" in data else ""
    if not sid or not token_id:
        return None
    return UnboundSidCapture(scope, known, digest, response, token_id)


@dataclass(frozen=True, slots=True, repr=False)
class UnboundSidCapture:
    """Private source evidence only; neither a key nor an operation grant."""

    _scope: ScopeSnapshot
    _identity: IdentitySnapshot | None
    _token_digest: bytes
    _response: AccountResponse
    _token_id: str

    def _match(self, binding: KeyBinding, token: PrivateToken) -> None:
        digest = _checked(binding, token)
        scope = _scope_snapshot(binding.scope)
        identity = _identity_snapshot(binding.identity)
        if (
            scope[:4] != self._scope[:4]
            or scope[4] != identity[2]
            or self._scope[4] not in (None, identity[2])
            or self._identity not in (None, identity)
            or digest != self._token_digest
            or binding.token_id != self._token_id
        ):
            raise _fail()

    @_private
    def binding(
        self,
        scope: AccountScope,
        identity: TvtIdentityRef,
        generation: int,
        token: PrivateToken,
    ) -> KeyBinding:
        """Build structural binding after worker publishes/checks actual generation."""
        checked = _scope(scope, AccountScope)
        ref = _scope(identity, TvtIdentityRef)
        checked.identity_id = ref.identity_id
        # Check the caller's scope before completing the prelogin identity slot.
        original = _scope_snapshot(scope)
        if original[:4] != self._scope[:4] or original[4] not in (
            None,
            ref.identity_id,
        ):
            raise _fail()
        binding = KeyBinding(
            checked, ref, _integer(generation, 1, 2**63 - 1), self._token_id
        )
        self._match(binding, token)
        return binding

    @_private
    def password_temporary_config(
        self, binding: KeyBinding, token: PrivateToken, raw_password: str
    ) -> _PasswordTemporaryConfig:
        """Explicit worker password input only, exact raw UTF-8 lowercase MD5."""
        self._match(binding, token)
        password = _text(raw_password, nonempty=True)
        temporary = (
            hashlib.md5(password.encode("utf-8"), usedforsecurity=False)
            .hexdigest()
            .encode("ascii")
        )
        return _PasswordTemporaryConfig(
            _scope_snapshot(binding.scope),
            _identity_snapshot(binding.identity),
            binding.generation,
            binding.token_id,
            temporary,
        )

    def admit(
        self, state: SecurityKeyState, binding: KeyBinding, token: PrivateToken
    ) -> None:
        """Feed existing state; worker still owns current admission and publication."""
        failed = False
        try:
            if type(state) is not SecurityKeyState:
                raise _fail()
            self._match(binding, token)
            state.admit(binding, token, self._response)
        except Exception:  # noqa: BLE001 -- never preserve private failure contexts
            if type(state) is SecurityKeyState:
                state.close()
            failed = True
        if failed:
            raise _fail() from None


@dataclass(frozen=True, slots=True, repr=False)
class _PasswordTemporaryConfig:
    _scope: ScopeSnapshot
    _identity: IdentitySnapshot
    _generation: int
    _token_id: str
    _temporary: bytes

    @_private
    def temporary_key(self, binding: KeyBinding) -> bytes:
        if (
            type(binding) is not KeyBinding
            or _scope_snapshot(binding.scope) != self._scope
            or _identity_snapshot(binding.identity) != self._identity
            or type(binding.generation) is not int
            or binding.generation != self._generation
            or binding.token_id != self._token_id
        ):
            raise _fail()
        return self._temporary


@_private
def capture_login(
    scope: AccountScope,
    result: AccountResult[AccountTokens],
    *,
    known_identity: TvtIdentityRef | None = None,
) -> UnboundSidCapture | None:
    snapshot = _scope_snapshot(scope)
    known = _known(snapshot, known_identity)
    response = _response(result, AccountTokens)
    parsed = parse_login(response)
    assert result.value is not None
    if (
        parsed.token != result.value.account_token
        or parsed.p2p_token != result.value.p2p_token
    ):
        raise _fail()
    return _capture(snapshot, known, _digest(parsed.token), response)


@_private
def capture_renewal(
    scope: AccountScope, token: PrivateToken, result: AccountResult[AccountRenewal]
) -> UnboundSidCapture | None:
    snapshot = _scope_snapshot(scope)
    if type(token) is not PrivateToken:
        raise _fail()
    known = _known(snapshot, token.identity)
    assert known is not None
    current = _token_digest(token, known)
    response = _response(result, AccountRenewal)
    parsed = _renew(response)
    assert result.value is not None
    if (
        parsed.account_token != result.value.account_token
        or parsed.p2p_token != result.value.p2p_token
    ):
        raise _fail()
    digest = (
        _digest(parsed.account_token) if parsed.account_token is not None else current
    )
    return _capture(snapshot, known, digest, response)
