"""Account worker port and concrete executor, for a separate worker process.

Runtime RPC/mTLS is owned by W04. The API never constructs this executor,
receives its database URL, or obtains a SecretCipher capable of opening saved
credentials. A deployment injects an AccountWorker client into the API.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

from wso_contracts.tvt.account import (
    AccountIdentity,
    AccountLogin,
    AccountLogoutView,
    AccountProfileFields,
    AccountProfileView,
    AccountRefresh,
    AccountSelection,
    ImageChallengeView,
    ImageCheckRequest,
    ImageCheckView,
)
from wso_contracts.tvt.identity import (
    AccountScope,
    SessionState,
    TokenKind,
    TvtIdentityRef,
)
from wso_core.tvt.account_client import AccountClient
from wso_core.tvt.account_projection import (
    AccountFailure,
    project_image,
    project_profile,
)
from wso_core.tvt.account_protocol import LoginInput
from wso_core.tvt.account_transport import OriginPolicy
from wso_core.tvt.ports import (
    AccountClientError,
    AccountResult,
    ImageChallenge,
    ImageCheck,
    PrivateToken,
)
from wso_core.tvt.token_vault import (
    AccountLease,
    TokenVault,
    private_text,
    remaining_budget,
    require_user_kind,
    token_budget,
)


class AccountWorker(Protocol):
    def login(
        self, ticket: str, body: AccountLogin, *, deadline_ms: int, correlation_id: str
    ) -> AccountIdentity: ...
    def image_challenge(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> ImageChallengeView: ...
    def check_image(
        self,
        ticket: str,
        body: ImageCheckRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> ImageCheckView: ...
    def profile(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountProfileView: ...
    def renew(
        self,
        ticket: str,
        body: AccountRefresh,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountIdentity: ...
    def logout(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountLogoutView: ...


@dataclass(frozen=True, slots=True, repr=False)
class AccountEndpoint:
    region: str
    brand: str
    origin: str
    language: str
    country: str
    app_version: str
    customer_app_id: str = ""
    customer_mark: str = ""


def load_account_endpoints(path: Path | None = None) -> tuple[AccountEndpoint, ...]:
    """Worker-only trusted deployment input; no request/body URL selection."""
    result = None
    try:
        selected = path or Path(os.environ["WSO_TVT_ACCOUNT_PROFILE_FILE"])
        raw = selected.read_bytes()
        if len(raw) > 65536:
            raise ValueError
        value = json.loads(raw)
        if type(value) is not list or not 1 <= len(value) <= 64:
            raise ValueError
        entries = []
        for item in value:
            if type(item) is not dict or any(
                type(v) is not str or not v or len(v) > 4096 for v in item.values()
            ):
                raise ValueError
            entry = AccountEndpoint(**item)
            AccountSelection(region=entry.region, brand=entry.brand)
            OriginPolicy({entry.region: frozenset({entry.origin})})
            if any(
                len(v) > 64
                or any(
                    ord(c) == 0 or ord(c) > 0xFFFF or 0xD800 <= ord(c) <= 0xDFFF
                    for c in v
                )
                for v in (entry.language, entry.country, entry.app_version)
            ):
                raise ValueError
            entries.append(entry)
        if len({(e.region, e.brand) for e in entries}) != len(entries):
            raise ValueError
        result = tuple(entries)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if result is None:
        raise AccountFailure() from None
    return result


@dataclass(frozen=True, slots=True)
class RestrictedStatus:
    # Numeric status only. No upstream strings or exception/response objects.
    http_status: int
    native_msgcode: int
    correlation_id: str


class StatusSink(Protocol):
    def __call__(self, status: RestrictedStatus) -> None: ...


class Budget:
    def __init__(self, deadline_ms: int) -> None:
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 60000:
            raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
        self._end = time.monotonic() + deadline_ms / 1000

    def remaining(self) -> int:
        value = int((self._end - time.monotonic()) * 1000)
        shared = remaining_budget()
        if shared is not None:
            value = min(value, shared)
        if value < 1:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        return value


def worker_budget[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def execute(*args: P.args, **kwargs: P.kwargs) -> R:
        deadline = kwargs.get("deadline_ms")
        if type(deadline) is not int or not 1 <= deadline <= 20000:
            raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
        end = time.monotonic() + deadline / 1000

        def remaining() -> int:
            left = int((end - time.monotonic()) * 1000)
            if left < 1:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
            return left

        with token_budget(remaining):
            return operation(*args, **kwargs)

    return execute


class AccountWorkerExecutor:
    def __init__(
        self,
        vault: TokenVault,
        endpoints: tuple[AccountEndpoint, ...],
        status_sink: StatusSink | None = None,
    ) -> None:
        self.vault, self.endpoints, self.status_sink = vault, endpoints, status_sink

    def _client(self, lease: AccountLease) -> AccountClient:
        endpoint = self._endpoint(lease)
        scope = AccountScope(
            tenant_id=lease.tenant_id,
            actor_user_id=lease.actor_id,
            region=lease.region,
            brand=lease.brand,
            identity_id=lease.identity_id,
        )
        return AccountClient(
            scope,
            OriginPolicy({lease.region: frozenset({endpoint.origin})}),
            origin=endpoint.origin,
            identity=self._identity(lease) if lease.identity_id else None,
        )

    def _endpoint(self, lease: AccountLease) -> AccountEndpoint:
        found = [
            entry
            for entry in self.endpoints
            if entry.region == lease.region and entry.brand == lease.brand
        ]
        if len(found) != 1:
            raise AccountFailure()
        return found[0]

    @staticmethod
    def _identity(lease: AccountLease) -> TvtIdentityRef:
        if lease.identity_id is None:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return TvtIdentityRef(
            tenant_id=lease.tenant_id,
            actor_user_id=lease.actor_id,
            identity_id=lease.identity_id,
        )

    @staticmethod
    def _scope(lease: AccountLease) -> AccountScope:
        return AccountScope(
            tenant_id=lease.tenant_id,
            actor_user_id=lease.actor_id,
            region=lease.region,
            brand=lease.brand,
        )

    def _result[T](self, result: AccountResult[T]) -> T:
        if self.status_sink is not None:
            self.status_sink(
                RestrictedStatus(
                    result.http_status, result.native_msgcode, result.correlation_id
                )
            )
        if not result.ok:
            raise AccountFailure(
                result.error_code.value
                if result.error_code
                else "ACCOUNT_UPSTREAM_REJECTED",
                502,
            )
        return cast(T, result.value)

    @worker_budget
    def login(
        self, ticket: str, body: AccountLogin, *, deadline_ms: int, correlation_id: str
    ) -> AccountIdentity:
        budget = Budget(deadline_ms)
        lease = self.vault.redeem(ticket, "login")
        if body.region != lease.region or body.brand != lease.brand:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        endpoint = self._endpoint(lease)
        image_id = (
            self.vault.consume_challenge(lease, body.challenge_id)
            if body.challenge_id
            else ""
        )
        credentials = LoginInput(
            1,
            body.account.get_secret_value(),
            body.secret.get_secret_value(),
            str(uuid4()),
            endpoint.language,
            endpoint.app_version,
            endpoint.country,
            image_id=image_id,
            image_code=body.image_code.get_secret_value() if body.image_code else "",
            double_check_code=body.second_code.get_secret_value()
            if body.second_code
            else "",
            customer_app_id=endpoint.customer_app_id,
            customer_mark=endpoint.customer_mark,
        )
        client = self._client(lease)
        try:
            tokens = self._result(
                client.login(
                    self._scope(lease),
                    credentials,
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation_id,
                )
            )
            budget.remaining()
            identity = self.vault.publish(lease, tokens.account_token, tokens.p2p_token)
            return AccountIdentity(
                identity_id=identity,
                region=lease.region,
                brand=lease.brand,
                state=SessionState.READY,
                generation=1,
                request_id=correlation_id,
            )
        finally:
            client.close()

    @worker_budget
    def image_challenge(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> ImageChallengeView:
        budget = Budget(deadline_ms)
        lease = self.vault.redeem(ticket, "image")
        client = self._client(lease)
        try:
            challenge = self._result(
                client.challenge(
                    self._scope(lease),
                    ImageChallenge(self._endpoint(lease).customer_app_id),
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation_id,
                )
            )
            media_type, encoded = project_image(challenge.private_image_data)
            if (
                type(challenge.image_id) is not str
                or not 1 <= len(challenge.image_id) <= 4096
            ):
                raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
            budget.remaining()
            reference = self.vault.save_challenge(lease, challenge.image_id)
            return ImageChallengeView(
                challenge_id=reference,
                media_type=cast("Literal['image/jpeg', 'image/png']", media_type),
                image_base64=encoded,
                request_id=correlation_id,
            )
        finally:
            client.close()

    @worker_budget
    def check_image(
        self,
        ticket: str,
        body: ImageCheckRequest,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> ImageCheckView:
        budget = Budget(deadline_ms)
        lease = self.vault.redeem(ticket, "check")
        if body.region != lease.region or body.brand != lease.brand:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        image_id = self.vault.consume_challenge(lease, body.challenge_id)
        client = self._client(lease)
        try:
            self._result(
                client.challenge(
                    self._scope(lease),
                    ImageCheck(
                        image_id,
                        body.image_code.get_secret_value(),
                        self._endpoint(lease).customer_app_id,
                    ),
                    deadline_ms=budget.remaining(),
                    correlation_id=correlation_id,
                )
            )
            with self.vault.transaction() as db:
                self.vault.recheck(db, lease)
            return ImageCheckView(request_id=correlation_id)
        finally:
            client.close()

    @worker_budget
    def profile(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountProfileView:
        budget = Budget(deadline_ms)
        lease = self.vault.redeem(ticket, "profile")
        client = self._client(lease)
        try:

            def callback(value: bytes) -> AccountProfileFields:
                result = self._result(
                    client.profile(
                        self._identity(lease),
                        PrivateToken(
                            self._identity(lease), TokenKind.USER, private_text(value)
                        ),
                        deadline_ms=budget.remaining(),
                        correlation_id=correlation_id,
                    )
                )
                return project_profile(result.private_body)

            profile = self.vault.use(lease, callback)
            return AccountProfileView(
                identity_id=self._identity(lease).identity_id,
                region=lease.region,
                brand=lease.brand,
                state=SessionState.READY,
                generation=lease.generation,
                profile=profile,
                request_id=correlation_id,
            )
        finally:
            client.close()

    @worker_budget
    def renew(
        self,
        ticket: str,
        body: AccountRefresh,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountIdentity:
        budget = Budget(deadline_ms)
        require_user_kind(body.kind)
        lease = self.vault.redeem(ticket, "renew")
        if body.expected_generation != lease.generation:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        client = self._client(lease)
        try:

            def callback(value: bytes) -> str | None:
                result = self._result(
                    client.renew(
                        self._identity(lease),
                        PrivateToken(
                            self._identity(lease), TokenKind.USER, private_text(value)
                        ),
                        deadline_ms=budget.remaining(),
                        correlation_id=correlation_id,
                    )
                )
                # A P2P field in a USER renewal is not authority to run/rotate a
                # native P2P session. A missing USER token retains the version.
                return result.account_token

            generation = self.vault.renew(lease, callback)
            return AccountIdentity(
                identity_id=self._identity(lease).identity_id,
                region=lease.region,
                brand=lease.brand,
                state=SessionState.READY,
                generation=generation,
                request_id=correlation_id,
            )
        finally:
            client.close()

    @worker_budget
    def logout(
        self, ticket: str, *, deadline_ms: int, correlation_id: str
    ) -> AccountLogoutView:
        budget = Budget(deadline_ms)
        lease = self.vault.redeem(ticket, "logout")
        outcome = "not_attempted"
        client = None
        try:
            client = self._client(lease)

            def callback(value: bytes) -> None:
                self._result(
                    client.logout(
                        self._identity(lease),
                        PrivateToken(
                            self._identity(lease), TokenKind.USER, private_text(value)
                        ),
                        deadline_ms=budget.remaining(),
                        correlation_id=correlation_id,
                    )
                )

            self.vault.use(lease, callback)
            outcome = "confirmed"
        except (AccountFailure, AccountClientError):
            outcome = "unknown"
        finally:
            if client is not None:
                client.close()
            # Local revocation commits independently of an uncertain upstream.
            with token_budget(None):
                self.vault.revoke(lease)
        return AccountLogoutView(
            identity_id=self._identity(lease).identity_id,
            upstream_outcome=cast(
                "Literal['confirmed', 'unknown', 'not_attempted']", outcome
            ),
            request_id=correlation_id,
        )
