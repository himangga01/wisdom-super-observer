"""Public prelogin boundaries; source-shaped fixtures are entirely invented."""

import importlib
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wso_core.tvt.account_projection import project_image

FLOW = "2d620c23-576a-4c3b-9291-7f3925dc9e4f"
CHALLENGE = "d3df5708-9500-4d06-b0aa-4e6b8a5a56af"
SELECTION = {"region": "global", "brand": "SuperLivePlus"}
REFERENCE = {**SELECTION, "flow_id": FLOW, "purpose": "register"}
VIEW = {**REFERENCE, "request_id": "w06.public:1"}


def contracts() -> ModuleType:
    try:
        return importlib.import_module("wso_contracts.tvt.account_flows")
    except ModuleNotFoundError:
        pytest.fail("public account-flow contracts are not implemented")


def test_phone_start_preserves_separate_dialing_code_and_local_number() -> None:
    start = contracts().AccountFlowStart.model_validate(
        {
            **SELECTION,
            "purpose": "recover",
            "mode": "phone",
            "country_code": "82",
            "account": "01012345678",
        }
    )
    assert start.account.get_secret_value() == "01012345678"
    assert start.country_code == "82"
    assert start.purpose == "recover"
    assert "01012345678" not in start.model_dump_json()


@pytest.mark.parametrize(
    "patch",
    [
        {"country_code": None},
        {"country_code": ""},
        {"country_code": "+82"},
        {"country_code": 82},
        {"country_code": "12345"},
        {"account": "82+01012345678"},
        {"account": "１２３４"},
        {"account": "1" * 33},
        {"account": "1 234"},
        {"mode": 1},
        {"purpose": 12},
    ],
)
def test_phone_start_rejects_combined_and_ambiguous_inputs(
    patch: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        contracts().AccountFlowStart.model_validate(
            {
                **SELECTION,
                "purpose": "register",
                "mode": "phone",
                "country_code": "82",
                "account": "01012345678",
                **patch,
            }
        )


@pytest.mark.parametrize(
    "email", ["user_name-1@example.test", "a.b@example-domain.test"]
)
def test_email_start_accepts_source_restricted_ascii_shape(email: str) -> None:
    result = contracts().AccountFlowStart.model_validate(
        {**SELECTION, "purpose": "register", "mode": "email", "account": email}
    )
    assert result.account.get_secret_value() == email
    assert result.country_code is None


@pytest.mark.parametrize(
    "patch",
    [
        {"country_code": "82"},
        {"country_code": None},
        {"account": "a+b@example.test"},
        {"account": "이메일@example.test"},
        {"account": "a@localhost"},
        {"account": " a@example.test"},
        {"account": "a@example.test\n"},
        {"account": "x" * 500 + "@example.test"},
        {"account": None},
        {"account": ""},
    ],
)
def test_email_start_rejects_non_source_shape_and_country_field(
    patch: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        contracts().AccountFlowStart.model_validate(
            {
                **SELECTION,
                "purpose": "recover",
                "mode": "email",
                "account": "user@example.test",
                **patch,
            }
        )


@pytest.mark.parametrize(
    "model,purpose,password_field",
    [
        ("AccountRegistrationSubmit", "register", "password"),
        ("AccountRecoverySubmit", "recover", "new_password"),
    ],
)
def test_final_submit_is_purpose_specific_and_masks_secrets(
    model: str, purpose: str, password_field: str
) -> None:
    cls = getattr(contracts(), model)
    body = {
        **REFERENCE,
        "purpose": purpose,
        password_field: "비밀P@ss1",
        "dynamic_code": "246810",
    }
    result = cls.model_validate(body)
    assert getattr(result, password_field).get_secret_value() == "비밀P@ss1"
    assert result.dynamic_code.get_secret_value() == "246810"
    assert "비밀P@ss1" not in repr(result) + result.model_dump_json() + str(
        result.model_dump()
    )
    assert "246810" not in repr(result) + result.model_dump_json() + str(
        result.model_dump()
    )
    wrong = {**body, "purpose": "recover" if purpose == "register" else "register"}
    with pytest.raises(ValidationError):
        cls.model_validate(wrong)
    with pytest.raises(ValidationError):
        cls.model_validate(
            {
                **body,
                "new_password" if password_field == "password" else "password": "other",
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("password", None),
        ("password", ""),
        ("password", "x\x00y"),
        ("password", "\ud800"),
        ("password", "😀"),
        ("password", "x" * 4097),
        ("password", "한" * 1366),
        ("dynamic_code", "12345"),
        ("dynamic_code", "1234567"),
        ("dynamic_code", "12345\x00"),
        ("dynamic_code", "12345😀"),
        ("dynamic_code", 246810),
        ("dynamic_code", None),
    ],
)
def test_final_native_inputs_are_bounded_bmp_and_code_is_six_characters(
    field: str, value: object
) -> None:
    body = {
        **REFERENCE,
        "password": "Demo_Pass9!",
        "dynamic_code": "246810",
        field: value,
    }
    with pytest.raises(ValidationError) as error:
        contracts().AccountRegistrationSubmit.model_validate(body)
    assert "Demo_Pass9!" not in str(error.value)
    assert "246810" not in str(error.value)
    assert "input_value=" not in str(error.value)
    assert all("input" not in item for item in error.value.errors(include_input=False))


def test_password_bounds_do_not_invent_unresolved_apk_strength_validator() -> None:
    cls = contracts().AccountRecoverySubmit
    for password in ("x", "x" * 4096, "한" * 1365):
        result = cls.model_validate(
            {
                **REFERENCE,
                "purpose": "recover",
                "new_password": password,
                "dynamic_code": "가나다라마바",
            }
        )
        assert result.new_password.get_secret_value() == password


def test_dynamic_image_input_requires_local_reference_and_generation_pair() -> None:
    cls = contracts().AccountDynamicCodeRequest
    assert cls.model_validate(REFERENCE).image_code is None
    result = cls.model_validate(
        {
            **REFERENCE,
            "challenge_id": CHALLENGE,
            "challenge_generation": 2,
            "image_code": "ab12",
        }
    )
    assert result.image_code.get_secret_value() == "ab12"
    assert "ab12" not in repr(result) + result.model_dump_json()
    for patch in (
        {"image_code": "ab12"},
        {"challenge_id": CHALLENGE},
        {"challenge_id": CHALLENGE, "challenge_generation": True, "image_code": "ab12"},
        {"challenge_id": CHALLENGE, "challenge_generation": 1, "image_code": ""},
        {"challenge_id": CHALLENGE, "challenge_generation": 1, "image_code": "😀"},
    ):
        with pytest.raises(ValidationError):
            cls.model_validate({**REFERENCE, **patch})


@pytest.mark.parametrize("value", [None, "false", 0, 1, "", {}, []])
def test_existence_never_coerces_missing_or_wrong_type_to_false(value: object) -> None:
    cls = contracts().AccountExistenceView
    with pytest.raises(ValidationError):
        cls.model_validate({**VIEW, "exists": value})
    with pytest.raises(ValidationError):
        cls.model_validate(VIEW)


@pytest.mark.parametrize("exists", [False, True])
def test_existence_projects_exact_boolean(exists: bool) -> None:
    result = contracts().AccountExistenceView.model_validate({**VIEW, "exists": exists})
    assert result.model_dump(mode="json")["exists"] is exists
    assert result.state == "EXISTENCE"
    assert result.return_to_login is False


def test_complete_and_unknown_outcome_cannot_claim_same_result() -> None:
    complete = contracts().AccountCompletionView.model_validate(VIEW)
    assert complete.state == "COMPLETE"
    assert complete.return_to_login is True
    assert complete.automatic_retry_permitted is False
    unknown = contracts().AccountFlowView.model_validate(
        {**VIEW, "state": "UNKNOWN_OUTCOME"}
    )
    assert unknown.return_to_login is False
    assert unknown.automatic_retry_permitted is False
    for patch in (
        {"state": "UNKNOWN_OUTCOME", "return_to_login": True},
        {"state": "COMPLETE"},
        {"state": "COMPLETE", "return_to_login": 1},
        {"state": "UNKNOWN_OUTCOME", "automatic_retry_permitted": True},
    ):
        with pytest.raises(ValidationError):
            contracts().AccountFlowView.model_validate({**VIEW, **patch})


def test_projected_image_is_inert_bounded_and_not_a_completion() -> None:
    kind, payload = project_image("/9j/AAH/2Q==")
    image = {
        "challenge_id": CHALLENGE,
        "generation": 1,
        "media_type": kind,
        "image_base64": payload,
    }
    cls = contracts().AccountImageView
    for state in ("IMAGE_AVAILABLE", "IMAGE_REQUIRED", "IMAGE_REJECTED"):
        result = cls.model_validate({**VIEW, "state": state, "image": image})
        assert result.return_to_login is False
        assert result.image.media_type == "image/jpeg"
        assert result.image.image_base64 == "/9j/AAH/2Q=="
    with pytest.raises(ValidationError):
        cls.model_validate(
            {**VIEW, "state": "IMAGE_REJECTED", "purpose": "recover", "image": image}
        )
    for patch in (
        {"media_type": "image/svg+xml"},
        {"image_base64": "data:image/png;base64,AA=="},
        {"image_base64": ""},
        {"image_base64": "AA==\n"},
        {"image_base64": "A" * 90004},
        {"generation": 0},
        {"generation": True},
    ):
        with pytest.raises(ValidationError):
            cls.model_validate(
                {**VIEW, "state": "IMAGE_REQUIRED", "image": {**image, **patch}}
            )


def test_code_sent_needs_no_image_and_countdown_is_only_ui_behavior() -> None:
    result = contracts().AccountDynamicCodeView.model_validate(
        {**VIEW, "state": "CODE_SENT"}
    )
    assert result.image is None
    assert result.ui_resend_countdown_seconds == 120
    assert result.expires_in_seconds is None
    assert result.resend_wait_seconds is None
    for patch in (
        {"expires_in_seconds": 0},
        {"expires_in_seconds": True},
        {"resend_wait_seconds": -1},
        {"resend_wait_seconds": 3601},
        {"ui_resend_countdown_seconds": True},
    ):
        with pytest.raises(ValidationError):
            contracts().AccountDynamicCodeView.model_validate(
                {**VIEW, "state": "CODE_SENT", **patch}
            )


@pytest.mark.parametrize(
    "field",
    [
        "token",
        "p2p_token",
        "identity_id",
        "actor_user_id",
        "tenant_id",
        "endpoint",
        "publicKey",
        "idCode",
        "private_body",
        "businessType",
        "loginType",
        "callback",
        "operation",
    ],
)
def test_extra_private_fields_cannot_cross_public_boundaries(field: str) -> None:
    with pytest.raises(ValidationError):
        contracts().AccountFlowCancel.model_validate(
            {**REFERENCE, field: "private-marker"}
        )
    with pytest.raises(ValidationError) as error:
        contracts().AccountCompletionView.model_validate(
            {**VIEW, field: "private-marker"}
        )
    assert "private-marker" not in str(error.value)
    assert set(contracts().AccountCompletionView.model_validate(VIEW).model_dump()) == {
        "region",
        "brand",
        "purpose",
        "flow_id",
        "request_id",
        "state",
        "exists",
        "image",
        "error_code",
        "expires_in_seconds",
        "resend_wait_seconds",
        "return_to_login",
        "automatic_retry_permitted",
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"flow_id": "native-id"},
        {"flow_id": 1},
        {"flow_id": UUID(FLOW).bytes},
        {"request_id": "https://upstream.invalid"},
        {"request_id": "x" * 129},
        {"request_id": "x\n"},
        {"request_id": ""},
        {"request_id": 1},
        {"region": "https://upstream.invalid"},
        {"purpose": "provider"},
    ],
)
def test_view_rejects_unsafe_correlation_authority_and_invalid_uuid(
    patch: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        contracts().AccountCompletionView.model_validate({**VIEW, **patch})


@pytest.mark.parametrize(
    "state", ["CREATED", "FAILED", "UNKNOWN_OUTCOME", "CLOSED", "EXPIRED"]
)
def test_non_completion_states_project_without_credentials(state: str) -> None:
    result = contracts().AccountFlowView.model_validate({**VIEW, "state": state})
    assert result.return_to_login is False
    assert result.image is None
    assert result.exists is None
    assert contracts().AccountFlowCancelView.model_validate(VIEW).state == "CLOSED"


@pytest.mark.parametrize(
    "patch",
    [
        {"state": "EXISTENCE"},
        {"state": "CREATED", "exists": False},
        {"state": "IMAGE_REQUIRED"},
        {"state": "CODE_SENT", "exists": True},
        {
            "state": "COMPLETE",
            "return_to_login": True,
            "error_code": "ACCOUNT_UPSTREAM_REJECTED",
        },
        {"state": "FAILED", "error_code": "arbitrary upstream body"},
    ],
)
def test_state_fields_do_not_describe_a_different_operation(
    patch: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        contracts().AccountFlowView.model_validate({**VIEW, **patch})


@pytest.mark.parametrize(
    "model,body",
    [
        (
            "AccountFlowStart",
            {
                **SELECTION,
                "purpose": "register",
                "mode": "email",
                "account": b"user@example.test",
            },
        ),
        (
            "AccountRegistrationSubmit",
            {**REFERENCE, "password": b"Demo_Pass9!", "dynamic_code": "246810"},
        ),
        (
            "AccountRecoverySubmit",
            {
                **REFERENCE,
                "purpose": "recover",
                "new_password": b"Demo_Pass9!",
                "dynamic_code": "246810",
            },
        ),
        (
            "AccountRegistrationSubmit",
            {**REFERENCE, "password": "Demo_Pass9!", "dynamic_code": b"246810"},
        ),
        (
            "AccountDynamicCodeRequest",
            {
                **REFERENCE,
                "challenge_id": CHALLENGE,
                "challenge_generation": 1,
                "image_code": b"ab12",
            },
        ),
    ],
)
def test_secrets_require_text_without_coercing_private_bytes(
    model: str, body: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        getattr(contracts(), model).model_validate(body)
