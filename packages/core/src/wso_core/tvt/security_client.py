"""Private security methods composed through the sole AccountClient boundary.

Future protected admission must commit write intent before invoking these methods.
A possible dispatch with no conclusive reply returns UNKNOWN_OUTCOME, never replay.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from wso_contracts.tvt.identity import TvtIdentityRef

from .account_client import AccountClient
from .account_protocol import AccountProtocolError, AccountRequest, AccountResponse
from .ports import AccountClientError, AccountDc, AccountErrorCode, PrivateToken
from .security_crypto import KeyBinding, SecurityKeyState
from .security_projection import (
    Acknowledgement,
    CodeChallenge,
    LoginTypes,
    SecurityState,
    parse_acknowledgement,
    parse_code,
    parse_login_types,
)
from .security_protocol import (
    EmailBind,
    EmailChange,
    PasswordUpdate,
    PhoneBind,
    PhoneChange,
    ProfileUpdate,
    SecurityCode,
    SecurityProtocol,
)


@dataclass(frozen=True, slots=True)
class SecurityResult[T]:
    state: SecurityState
    correlation_id: str
    http_status: int | None = None
    native_msgcode: int | None = None
    value: T | None = field(default=None, repr=False)
    error_code: AccountErrorCode | None = None
    dc: AccountDc | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return (
            self.state
            in (SecurityState.ACKNOWLEDGED, SecurityState.READ, SecurityState.CODE_SENT)
            and self.http_status is not None
            and 200 <= self.http_status <= 299
            and self.native_msgcode == 200
            and self.error_code is None
        )


class SecurityClient:
    def __init__(
        self, account: AccountClient, *, protocol: SecurityProtocol | None = None
    ) -> None:
        if (
            type(account) is not AccountClient
            or protocol is not None
            and (
                type(protocol) is not SecurityProtocol
                or protocol._account is not account._protocol
            )
        ):
            raise AccountProtocolError("Invalid security input.")
        self._account = account
        self._security = protocol or SecurityProtocol(account._protocol)

    def close(self) -> None:
        self._account.close()

    def _execute[T](
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        request: Callable[[], AccountRequest],
        decode: Callable[[AccountResponse], T],
        *,
        write: bool = True,
        challenge: bool = False,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[T]:
        attempted = False

        def outgoing() -> AccountRequest:
            nonlocal attempted
            result = request()
            # Conservative boundary: a built write could be dispatched next.
            attempted = write
            return result

        failure: AccountClientError | None = None
        try:
            result = self._account._run(
                lambda: self._account._postlogin(scope, token),
                outgoing,
                decode,
                deadline_ms=deadline_ms,
                correlation_id=correlation_id,
                decode_codes=frozenset({200, 1007, 1005})
                if challenge
                else frozenset({200}),
            )
            state = SecurityState.ACKNOWLEDGED if write else SecurityState.READ
            if result.error_code is not None:
                state = SecurityState.REJECTED
            elif isinstance(result.value, CodeChallenge):
                state = result.value.state
            return SecurityResult(
                state,
                result.correlation_id,
                result.http_status,
                result.native_msgcode,
                result.value,
                result.error_code,
                result.dc,
            )
        except AccountClientError as error:
            failure = AccountClientError(
                error.code,
                error.correlation_id,
                http_status=error.http_status,
                native_msgcode=error.native_msgcode,
            )
        if attempted:
            return SecurityResult(
                SecurityState.UNKNOWN_OUTCOME,
                correlation_id,
                failure.http_status,
                failure.native_msgcode,
                error_code=failure.code,
            )
        raise failure from None

    def update_profile(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: ProfileUpdate,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        return self._execute(
            scope,
            token,
            lambda: self._security.update_profile(token.value, value),
            parse_acknowledgement,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def bind_phone(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: PhoneBind,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        return self._execute(
            scope,
            token,
            lambda: self._security.bind_phone(token.value, value),
            parse_acknowledgement,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def bind_email(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: EmailBind,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        return self._execute(
            scope,
            token,
            lambda: self._security.bind_email(token.value, value),
            parse_acknowledgement,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def change_phone(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: PhoneChange,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        return self._execute(
            scope,
            token,
            lambda: self._security.change_phone(token.value, value),
            parse_acknowledgement,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def change_email(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: EmailChange,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        return self._execute(
            scope,
            token,
            lambda: self._security.change_email(token.value, value),
            parse_acknowledgement,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def login_types(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[LoginTypes]:
        return self._execute(
            scope,
            token,
            lambda: self._security.login_types(token.value),
            parse_login_types,
            write=False,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def issue_code(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: SecurityCode,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[CodeChallenge]:
        return self._execute(
            scope,
            token,
            lambda: self._security.issue_code(token.value, value),
            parse_code,
            challenge=True,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def update_password(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        value: PasswordUpdate,
        key_state: SecurityKeyState,
        binding: KeyBinding,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> SecurityResult[Acknowledgement]:
        def request() -> AccountRequest:
            if (
                type(value) is not PasswordUpdate
                or type(key_state) is not SecurityKeyState
                or type(binding) is not KeyBinding
                or binding.scope != self._account._scope
                or binding.identity != scope
            ):
                if type(key_state) is SecurityKeyState:
                    key_state.close()
                raise AccountProtocolError("Security key unavailable.")
            encrypted = key_state.encrypt(binding, token, value.raw_password)
            return self._security._password(token.value, value, encrypted)

        try:
            return self._execute(
                scope,
                token,
                request,
                parse_acknowledgement,
                deadline_ms=deadline_ms,
                correlation_id=correlation_id,
            )
        finally:
            if type(key_state) is SecurityKeyState:
                key_state.close()
