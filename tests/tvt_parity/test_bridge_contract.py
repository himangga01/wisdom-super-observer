"""The RPC is a transport, not proof of APK or SQL authority."""

import importlib.util
import json

import pytest
from pydantic import SecretStr
from wso_contracts.tvt.account import AccountLogin
from wso_core.tvt.account_projection import AccountFailure


def test_account_rpc_package_exists():
    assert importlib.util.find_spec("wso_tvt_bridge") is not None


def test_login_secrets_cross_only_explicit_typed_serialization():
    from wso_tvt_bridge.selected import decode_input, encode_input

    body = AccountLogin(
        region="eu",
        brand="tvt",
        mode="email",
        account=SecretStr("test@example.invalid"),
        secret=SecretStr("private-password"),
    )
    payload = encode_input(body)
    assert json.loads(payload)["secret"] == "private-password"
    assert (
        decode_input(payload, AccountLogin).secret.get_secret_value()
        == "private-password"
    )
    assert "private-password" not in repr(body)
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        decode_input(payload[:-1] + b',"worker_url":"private"}', AccountLogin)
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        decode_input(payload[:-1] + b',"secret":"duplicate"}', AccountLogin)


def test_fixed_context_rejects_authority_unknown_and_old_version():
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import validate_request

    good = pb.ProfileRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="a" * 64,
            deadline_ms=1000,
            correlation_id="call-01",
        )
    )
    validate_request(good)
    good.context.protocol_version = 0
    with pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"):
        validate_request(good)
    good.context.protocol_version = 1
    unknown = pb.ProfileRequest.FromString(good.SerializeToString() + b"\x18\x01")
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        validate_request(unknown)
    good.context.ticket = "SECRET"
    with pytest.raises(AccountFailure) as caught:
        validate_request(good)
    assert "SECRET" not in str(caught.value)


def test_client_module_does_not_load_worker_capabilities():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import wso_tvt_bridge.client; assert 'wso_core.tvt.token_vault' not in sys.modules; assert 'wso_core.secrets' not in sys.modules; assert 'wso_api.tvt.session_service' not in sys.modules",
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_missing_configuration_fails_without_secret_output():
    import os
    import subprocess
    import sys

    from wso_tvt_bridge.client import create_account_worker_client

    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        create_account_worker_client({})
    env = {
        name: value for name, value in os.environ.items() if not name.startswith("WSO_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "wso_tvt_bridge"],
        capture_output=True,
        check=False,
        env=env,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout.strip() == b"ACCOUNT_WORKER_UNAVAILABLE"
    assert result.stderr == b""


def test_generated_messages_have_installable_package_identity():
    import pickle

    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    value = pb.RpcContext(
        protocol_version=1, ticket="01" * 32, deadline_ms=1000, correlation_id="package"
    )
    assert pickle.loads(pickle.dumps(value)) == value


@pytest.mark.parametrize("code", ["CHALLENGE_EXPIRED", "RENEWAL_OUTCOME_UNKNOWN"])
def test_durable_account_conflicts_keep_exact_public_code_and_status(code):
    from wso_tvt_bridge.selected import failure

    error = failure(code)
    assert (error.code, error.status) == (code, 409)


def test_unrecognized_worker_failure_stays_closed_and_sanitized():
    from wso_tvt_bridge.selected import failure

    error = failure("PRIVATE-UNKNOWN-WORKER-DETAIL")
    assert (error.code, error.status, str(error)) == (
        "ACCOUNT_UNAVAILABLE",
        503,
        "ACCOUNT_UNAVAILABLE",
    )


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-path"])
def test_unreadable_tls_file_is_sanitized(tmp_path, monkeypatch, kind):
    import grpc
    from wso_tvt_bridge.client import create_account_worker_client

    def forbid_channel(*args, **kwargs):
        pytest.fail("unreadable TLS configuration reached channel creation")

    monkeypatch.setattr(grpc, "secure_channel", forbid_channel)
    path = str(tmp_path / "missing") if kind == "missing" else str(tmp_path)
    if kind == "invalid-path":
        path += "\x00PRIVATE-PATH"
    with pytest.raises(AccountFailure) as caught:
        create_account_worker_client(
            {
                "WSO_TVT_BRIDGE_ENDPOINT": "localhost:12345",
                "WSO_TVT_BRIDGE_CA_FILE": path,
                "WSO_TVT_BRIDGE_CLIENT_CERT_FILE": path,
                "WSO_TVT_BRIDGE_CLIENT_KEY_FILE": path,
            }
        )
    assert (caught.value.code, caught.value.status, str(caught.value)) == (
        "ACCOUNT_UNAVAILABLE",
        503,
        "ACCOUNT_UNAVAILABLE",
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
