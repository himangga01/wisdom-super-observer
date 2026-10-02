"""Phone binding regressions; synthetic boundaries do not establish SQL authority."""

import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from wso_api.tvt.session_service import AccountEndpoint, AccountWorkerExecutor
from wso_contracts.tvt.account import AccountLogin
from wso_core.tvt.account_protocol import AccountProtocol, LoginInput, SessionTaskIds
from wso_core.tvt.ports import AccountResult, AccountTokens
from wso_core.tvt.token_vault import AccountLease, TokenVault
from wso_tvt_bridge.selected import decode_input, encode_input

ID = UUID("30000000-0000-4000-8000-000000000001")
BASE: dict[str, Any] = {
    "region": "KR",
    "brand": "SuperLivePlus",
    "secret": "synthetic-password",
}


@pytest.mark.parametrize(
    "code,local,native",
    [
        ("82", "00101234", "82+00101234"),
        ("0001", "0", "0001+0"),
        ("1", "9" * 32, "1+" + "9" * 32),
    ],
)
def test_phone_keeps_local_zeros_and_private_composite(
    code: str, local: str, native: str
) -> None:
    body = AccountLogin(
        **BASE, mode="phone", account=SecretStr(local), country_code=code
    )
    assert body._native_account() == native
    assert body.account.get_secret_value() == local
    assert native not in body.model_dump_json()
    assert native not in repr(body)
    assert "_native_account" not in body.model_dump()
    restored = decode_input(encode_input(body), AccountLogin)
    assert restored._native_account() == native


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"country_code": None},
        {"country_code": ""},
        {"country_code": "+82"},
        {"country_code": "12345"},
        {"country_code": 82},
        {"country_code": "８２"},
        {"country_code": "8 2"},
        {"country_code": "82\n"},
        {"country_code": "82", "account": "0012\n"},
        {"country_code": "82", "account": "+001"},
        {"country_code": "82", "account": "82+001"},
        {"country_code": "82", "account": "１２３４"},
        {"country_code": "82", "account": "1" * 33},
        {"country_code": "82", "account": ""},
        {"country_code": "82", "country_name": "Korea"},
    ],
)
def test_phone_rejects_missing_malformed_or_extra_country(
    changes: dict[str, Any],
) -> None:
    values = dict(BASE, mode="phone", account="00101234") | changes
    with pytest.raises(ValidationError):
        AccountLogin.model_validate(values)


@pytest.mark.parametrize("country", [{}, {"country_code": None}])
def test_email_omission_and_null_survive_protected_codec(
    country: dict[str, Any],
) -> None:
    body = AccountLogin(
        **BASE, mode="email", account=SecretStr("synthetic@example.test"), **country
    )
    restored = decode_input(encode_input(body), AccountLogin)
    assert restored._native_account() == "synthetic@example.test"
    assert restored.country_code is None
    assert "synthetic@example.test" not in restored.model_dump_json()


def test_email_rejects_country_code() -> None:
    with pytest.raises(ValidationError):
        AccountLogin(
            **BASE,
            mode="email",
            account=SecretStr("synthetic@example.test"),
            country_code="82",
        )


def test_worker_binds_composite_before_actual_serializer_and_proofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire: dict[str, Any] = {}
    lease = AccountLease(
        "synthetic-ticket", ID, ID, None, "KR", "SuperLivePlus", 0, "login"
    )
    vault = SimpleNamespace(
        redeem=lambda *_: lease,
        consume_challenge=lambda *_: "synthetic-image-id",
        publish=lambda *_: ID,
    )
    protocol = AccountProtocol(
        task_ids=SessionTaskIds(), clock=lambda: 1700000000, nonce=lambda: 123456789
    )

    class PrivateClient:
        def login(
            self, scope: object, credentials: LoginInput, **kwargs: Any
        ) -> AccountResult[AccountTokens]:
            wire.update(json.loads(protocol.login(credentials).body))
            return AccountResult(
                200,
                200,
                "synthetic-request",
                AccountTokens("synthetic-user", "synthetic-p2p"),
            )

        def close(self) -> None:
            pass

    worker = AccountWorkerExecutor(
        cast(TokenVault, vault),
        (
            AccountEndpoint(
                "KR",
                "SuperLivePlus",
                "https://synthetic.test",
                "en",
                "deployment-country",
                "1.18.1",
            ),
        ),
    )
    monkeypatch.setattr(worker, "_client", lambda _: PrivateClient())
    monkeypatch.setattr("wso_api.tvt.session_service.uuid4", lambda: ID)
    body = AccountLogin(
        **BASE,
        mode="phone",
        account=SecretStr("00101234"),
        country_code="82",
        challenge_id=ID,
        image_code=SecretStr("synthetic-image"),
        second_code=SecretStr("synthetic-second"),
    )
    result = worker.login(
        "synthetic-ticket", body, deadline_ms=1000, correlation_id="synthetic-request"
    )
    assert result.identity_id == ID
    assert wire["data"]["userName"] == "82+00101234"
    assert wire["data"]["type"] == 1
    assert wire["data"]["country"] == "deployment-country"
    assert wire["data"]["lang"] == "en"
    assert wire["data"]["idCode"] == "synthetic-image-id"
    assert wire["data"]["imgCode"] == "synthetic-image"
    assert wire["data"]["doubleCheckCode"] == "synthetic-second"
    for field, value in [("password", "synthetic-password"), ("uuid", str(ID))]:
        md5 = hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
        expected = hashlib.sha512(
            f"123456789#1700000000#82+00101234#{md5}".encode()
        ).hexdigest()
        assert wire["data"][field] == expected
