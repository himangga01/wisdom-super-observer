"""APK-derived private account composition; server acceptance is unverified.

Trusted server code supplies scope/endpoint policy and admitted bytes. No URL
argument exists on the account operations. Scope matching is consistency, not
authorization. W02 supplies protected actor/credential admission; W05 owns the
vault and token rotation. Each call uses the reviewed ProcessAccountTransport
for a real TLS child, never a second containment implementation. One inflight
operation per client; unproved child settlement permanently closes admission.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import cast

from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef

from .account_process import AccountProcessError, ProcessAccountTransport
from .account_protocol import (
    MAX_BODY_BYTES,
    AccountProtocol,
    AccountProtocolError,
    AccountRequest,
    AccountResponse,
    JsonValue,
    LoginInput,
    SessionTaskIds,
    SmsChallengeInput,
    parse_login,
    parse_response,
    private_json,
)
from .account_transport import AccountTransportError, OriginPolicy, PendingDcRedirect
from .ports import (
    AccountChallenge,
    AccountClientError,
    AccountDc,
    AccountErrorCode,
    AccountProfile,
    AccountRenewal,
    AccountResult,
    AccountTokens,
    ChallengeInput,
    ImageChallenge,
    ImageCheck,
    PrivateToken,
)

_PROCESS_ERRORS = {
    "Account process request cancelled.": AccountErrorCode.CANCELLED,
    "Account process admission is closed or busy.": AccountErrorCode.UNAVAILABLE,
    "Account process deadline exceeded.": AccountErrorCode.DEADLINE_EXCEEDED,
    "Account process settlement could not be proved.": AccountErrorCode.QUARANTINED,
}


def _scope[T: AccountScope | TvtIdentityRef](value: T, kind: type[T]) -> T:
    valid: T | None = None
    if type(value) is kind:
        try:
            # Constructors/model_copy can bypass Pydantic validation. Revalidate
            # a dump, not the existing instance (which Pydantic may trust).
            valid = cast(T, kind.model_validate(value.model_dump(warnings=False)))
        except Exception:  # noqa: BLE001 -- discard private validation contexts
            valid = None
    if valid is None:
        raise AccountClientError(AccountErrorCode.SCOPE_INVALID) from None
    return valid


def _correlation(value: str) -> str:
    if type(value) is not str or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value
    ):
        raise AccountClientError(AccountErrorCode.INPUT_INVALID) from None
    return value


def _data(response: AccountResponse) -> dict[str, JsonValue]:
    data = private_json(response.private_body).get("data")
    if data is None:
        return {}
    if type(data) is not dict:
        raise AccountProtocolError("Invalid account response.")
    return data


def _optional_text(data: dict[str, JsonValue], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if (
        type(value) is not str
        or "\x00" in value
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise AccountProtocolError("Invalid account response.")
    return value


def _login(response: AccountResponse) -> AccountTokens:
    parsed = parse_login(response)
    return AccountTokens(parsed.token, parsed.p2p_token)


def _challenge(response: AccountResponse) -> AccountChallenge:
    data = _data(response)
    return AccountChallenge(
        _optional_text(data, "idCode"),
        _optional_text(data, "imgCodeImgData"),
        response.private_body,
    )


def _profile(response: AccountResponse) -> AccountProfile:
    return AccountProfile(
        _optional_text(_data(response), "userId"), response.private_body
    )


def _renew(response: AccountResponse) -> AccountRenewal:
    data = _data(response)
    # createCallbackJson's object branch invokes getTokenFromJson, including
    # renewal. Apply only its token/p2pId/tid extraction, not guessed timing.
    token = _optional_text(data, "token") or None
    if token is not None:
        parsed = parse_login(response)
        return AccountRenewal(
            parsed.token, parsed.p2p_token or None, response.private_body
        )
    return AccountRenewal(private_body=response.private_body)


class AccountClient:
    def __init__(
        self,
        scope: AccountScope,
        policy: OriginPolicy,
        *,
        origin: str,
        identity: TvtIdentityRef | None = None,
        protocol: AccountProtocol | None = None,
        max_body_bytes: int = 65_536,
    ) -> None:
        checked = _scope(scope, AccountScope)
        linked = _scope(identity, TvtIdentityRef) if identity is not None else None
        if (
            linked is not None
            and (
                linked.tenant_id != checked.tenant_id
                or linked.actor_user_id != checked.actor_user_id
                or checked.identity_id not in (None, linked.identity_id)
            )
            or checked.identity_id is not None
            and linked is None
            or type(max_body_bytes) is not int
            or not 1 <= max_body_bytes <= MAX_BODY_BYTES
        ):
            raise AccountClientError(AccountErrorCode.SCOPE_INVALID) from None
        resolved: str | None = None
        if type(policy) is OriginPolicy:
            try:
                resolved = policy.resolve(checked.region, origin).url
            except Exception:  # noqa: BLE001 -- no endpoint value in exceptions
                resolved = None
        if resolved is None:
            raise AccountClientError(AccountErrorCode.INPUT_INVALID) from None
        self._scope = checked
        self._identity = linked
        self._policy = policy
        self._origin = resolved
        self._protocol = (
            protocol
            if protocol is not None
            else AccountProtocol(task_ids=SessionTaskIds())
        )
        self._max_body = max_body_bytes
        self._redirect = PendingDcRedirect()
        self._lock = threading.Lock()
        self._active: ProcessAccountTransport | None = None
        self._busy = False
        self._closed = False
        self._quarantined = False

    def close(self) -> None:
        """Cancel the active owned boundary; no future call is admitted."""
        with self._lock:
            self._closed = True
            if self._active is not None:
                self._active.close()

    def _prelogin(self, scope: AccountScope) -> None:
        if _scope(scope, AccountScope) != self._scope:
            raise AccountClientError(AccountErrorCode.SCOPE_INVALID)

    def _postlogin(self, scope: TvtIdentityRef, token: PrivateToken) -> None:
        checked = _scope(scope, TvtIdentityRef)
        if (
            self._identity is None
            or checked != self._identity
            or type(token) is not PrivateToken
            or type(token.kind) is not TokenKind
            or token.kind is not TokenKind.USER
            or _scope(token.identity, TvtIdentityRef) != checked
            or type(token.value) is not str
            or not token.value
        ):
            raise AccountClientError(AccountErrorCode.SCOPE_INVALID)

    def _run[T](
        self,
        validate: Callable[[], None],
        request: Callable[[], AccountRequest],
        decode: Callable[[AccountResponse], T],
        *,
        deadline_ms: int,
        correlation_id: str,
        decode_codes: frozenset[int] = frozenset({200}),
        response_evidence: Callable[[AccountResponse], None] | None = None,
    ) -> AccountResult[T]:
        correlation = _correlation(correlation_id)
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 60_000:
            raise AccountClientError(AccountErrorCode.INPUT_INVALID, correlation)
        deadline = time.monotonic() + deadline_ms / 1000
        validation_error: AccountErrorCode | None = None
        try:
            validate()
        except AccountClientError as error:
            validation_error = error.code
        if validation_error is not None:
            raise AccountClientError(validation_error, correlation) from None
        with self._lock:
            if self._quarantined:
                raise AccountClientError(AccountErrorCode.QUARANTINED, correlation)
            if self._closed or self._busy:
                raise AccountClientError(AccountErrorCode.UNAVAILABLE, correlation)
            self._busy = True
        boundary: ProcessAccountTransport | None = None
        result: AccountResult[T] | None = None
        response: AccountResponse | None = None
        failure: AccountErrorCode | None = None
        try:
            outgoing = request()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = AccountErrorCode.DEADLINE_EXCEEDED
            else:
                with self._lock:
                    if self._closed:
                        failure = AccountErrorCode.CANCELLED
                    else:
                        boundary = ProcessAccountTransport(
                            self._policy,
                            region=self._scope.region,
                            origin=self._origin,
                            timeout_seconds=remaining,
                            settlement_seconds=min(0.5, remaining / 4),
                            max_body_bytes=self._max_body,
                        )
                        self._active = boundary
                if boundary is not None:
                    received = boundary.send(outgoing)
                    response = parse_response(
                        received.http_status,
                        received.private_body,
                        max_body_bytes=self._max_body,
                    )
                    if response_evidence is not None:
                        # Private bounded evidence only; this does not select
                        # success, decode operation data or admit credentials.
                        response_evidence(response)
                    if response.native_msgcode == 404:
                        dc_hint: AccountDc | None = None
                        try:
                            dc = self._redirect.offer(
                                response, self._policy, region=self._scope.region
                            )
                            dc_hint = AccountDc(dc.origin)
                        except AccountTransportError:
                            # A rejected or second DC hint does not erase the
                            # business status and cannot cause a follow-up request.
                            dc_hint = None
                        result = AccountResult(
                            response.http_status,
                            response.native_msgcode,
                            correlation,
                            error_code=(
                                AccountErrorCode.DC_PENDING
                                if dc_hint is not None
                                else AccountErrorCode.UPSTREAM_REJECTED
                            ),
                            dc=dc_hint,
                        )
                    elif (
                        not 200 <= response.http_status <= 299
                        or response.native_msgcode not in decode_codes
                    ):
                        result = AccountResult(
                            response.http_status,
                            response.native_msgcode,
                            correlation,
                            error_code=AccountErrorCode.UPSTREAM_REJECTED,
                        )
                    else:
                        result = AccountResult(
                            response.http_status,
                            response.native_msgcode,
                            correlation,
                            value=decode(response),
                        )
        except AccountProtocolError:
            failure = AccountErrorCode.PROTOCOL_INVALID
        except AccountProcessError as error:
            failure = _PROCESS_ERRORS.get(str(error), AccountErrorCode.TRANSPORT_FAILED)
        except Exception:  # noqa: BLE001 -- discard private dependency failures
            failure = AccountErrorCode.TRANSPORT_FAILED
        finally:
            if boundary is not None:
                boundary.close()
            with self._lock:
                if failure is AccountErrorCode.QUARANTINED:
                    self._quarantined = True
                    self._closed = True
                elif self._closed:
                    failure = AccountErrorCode.CANCELLED
                elif time.monotonic() >= deadline:
                    failure = AccountErrorCode.DEADLINE_EXCEEDED
                # A quarantined boundary owns exact unsettled resources; retain
                # it even after this request finishes and admission is closed.
                self._active = boundary if self._quarantined else None
                self._busy = False
        # Raise outside the handler: no credential-containing __context__ retained.
        if failure is not None:
            raise AccountClientError(
                failure,
                correlation,
                http_status=response.http_status if response is not None else None,
                native_msgcode=response.native_msgcode
                if response is not None
                else None,
            ) from None
        assert result is not None
        return result

    def login(
        self,
        scope: AccountScope,
        credentials: LoginInput,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountTokens]:
        def request() -> AccountRequest:
            if type(credentials) is not LoginInput:
                raise AccountProtocolError("Invalid account protocol input.")
            return self._protocol.login(credentials)

        return self._run(
            lambda: self._prelogin(scope),
            request,
            _login,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def challenge(
        self,
        scope: AccountScope,
        challenge: ChallengeInput,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountChallenge]:
        def request() -> AccountRequest:
            if type(challenge) is ImageChallenge:
                return self._protocol.image_challenge(
                    customer_app_id=challenge.customer_app_id
                )
            if type(challenge) is ImageCheck:
                return self._protocol.check_image(
                    challenge.image_id,
                    challenge.image_code,
                    customer_app_id=challenge.customer_app_id,
                )
            if type(challenge) is SmsChallengeInput:
                return self._protocol.sms_challenge(challenge)
            raise AccountProtocolError("Invalid account protocol input.")

        return self._run(
            lambda: self._prelogin(scope),
            request,
            _challenge,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def profile(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountProfile]:
        return self._run(
            lambda: self._postlogin(scope, token),
            lambda: self._protocol.profile(token.value),
            _profile,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def renew(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountRenewal]:
        return self._run(
            lambda: self._postlogin(scope, token),
            lambda: self._protocol.renew(token.value),
            _renew,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def logout(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[None]:
        return self._run(
            lambda: self._postlogin(scope, token),
            lambda: self._protocol.logout(token.value),
            lambda _: None,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )
