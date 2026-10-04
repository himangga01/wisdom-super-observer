"""Offline owned directory composition checks: never starts DB, TLS or Chrome."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    spec = importlib.util.spec_from_file_location(
        "directory_browser_fixture", ROOT / "scripts/test-tvt-account/runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_directory_mode_is_explicit_and_default_is_account(runtime, monkeypatch):
    monkeypatch.delenv("WSO_TEST_DIRECTORY_BROWSER", raising=False)
    assert hasattr(runtime, "directory_enabled"), "explicit directory mode required"
    assert runtime.directory_enabled() is False
    monkeypatch.setenv("WSO_TEST_DIRECTORY_BROWSER", "1")
    assert runtime.directory_enabled() is True
    monkeypatch.setenv("WSO_TEST_DIRECTORY_BROWSER", "true")
    with pytest.raises(ValueError, match="directory mode"):
        runtime.directory_enabled()


def test_directory_profile_only_opts_into_reviewed_route(runtime):
    assert hasattr(runtime, "directory_enabled"), "explicit directory mode required"
    account = json.loads(runtime.profile("https://localhost:3543"))
    directory = json.loads(runtime.profile("https://localhost:3543", directory=True))
    assert account["local_routes"] == ["/tvt/settings", "/tvt/account"]
    assert directory.pop("local_routes") == [
        "/tvt/settings",
        "/tvt/account",
        "/tvt/devices",
    ]
    account.pop("local_routes")
    assert directory == account


def test_all_six_source_envelopes_use_actual_private_projection(runtime):
    from wso_core.tvt import directory_projection as projection
    from wso_core.tvt.account_protocol import parse_response

    assert hasattr(runtime, "directory_payload"), "decoded source fixture required"
    decoders = {
        "/resource/device/list": projection.parse_device_list,
        "/resource/channel/list": projection.parse_channel_list,
        "/resource/device/detail": projection.parse_device_detail,
        "/resource/channel/detail": projection.parse_channel_detail,
        "/resource/channel/share/to-other/list": projection.parse_sent_shares,
        "/resource/channel/share/from-other/list": projection.parse_received_shares,
    }
    for path, decode in decoders.items():
        value = runtime.directory_payload(path)
        encoded = json.dumps(value).encode()
        result = decode(parse_response(200, encoded))
        safe = json.dumps(result.project())
        assert "synthetic:opaque:SN-7" in safe
        assert "DIRECTORY-SENSITIVE-MARKER" not in safe
    assert (
        runtime.directory_payload("/resource/channel/detail")["data"]["chlIndex"] == 7
    )
    assert (
        runtime.directory_payload("/resource/channel/detail", chl_index=42)["data"][
            "chlIndex"
        ]
        == 42
    )
    with pytest.raises(ValueError, match="directory path"):
        runtime.directory_payload("/resource/channel/share/add")


def test_directory_worker_configuration_is_private_exact_and_optional(
    runtime, tmp_path
):
    assert hasattr(runtime, "directory_worker_environment"), (
        "owned worker configuration required"
    )
    incoming = {"WSO_WORKER_DATABASE_URL": "private-worker", "OTHER": "retained"}
    assert (
        runtime.directory_worker_environment(tmp_path, incoming, enabled=False)
        == incoming
    )
    assert list(tmp_path.iterdir()) == []
    configured = runtime.directory_worker_environment(tmp_path, incoming, enabled=True)
    assert configured.keys() == incoming.keys() | {
        "WSO_TEST_DIRECTORY_BROWSER",
        "WSO_TVT_DIRECTORY_PROFILE_FILE",
    }
    assert configured["WSO_WORKER_DATABASE_URL"] == "private-worker"
    assert json.loads(
        Path(configured["WSO_TVT_DIRECTORY_PROFILE_FILE"]).read_text()
    ) == [
        {
            "region": "test",
            "brand": "SuperLivePlus",
            "profile_id": "browser-fixture",
            "consent_version": "fixture-v1",
        }
    ]


def test_directory_source_gate_runs_before_owned_database_import(runtime, monkeypatch):
    assert hasattr(runtime, "directory_database"), "owned directory generator required"
    from tests.support import directory_source_gate

    def reject():
        raise ValueError("source guard rejected before database")

    monkeypatch.setattr(directory_source_gate, "verify_directory_source_gate", reject)
    with (
        pytest.raises(ValueError, match="source guard rejected before database"),
        runtime.directory_database(None),
    ):
        pytest.fail("unreviewed source reached database")


def test_oidc_codes_are_one_use_pkce_bound_and_expire(runtime):
    import base64
    import hashlib

    assert hasattr(runtime, "DirectoryIssuerState"), "real signed issuer state required"
    state = runtime.DirectoryIssuerState(
        "https://localhost:1234", "synthetic-staff", "s" * 48
    )
    verifier = "v" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    code = state.authorize(
        {
            "client_id": "fixture-web",
            "redirect_uri": "https://localhost:3543/api/auth/callback",
            "response_type": "code",
            "scope": "openid",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "nonce": "nonce",
            "state": "state",
        }
    )
    body = {
        "code": code,
        "client_id": "fixture-web",
        "client_secret": "s" * 48,
        "redirect_uri": "https://localhost:3543/api/auth/callback",
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }
    tokens = state.exchange(body)
    import jwt

    claims = jwt.decode(
        tokens["id_token"],
        state.key.public_key(),
        algorithms=["RS256"],
        audience="fixture-web",
        issuer="https://localhost:1234",
    )
    assert claims["sub"] == "synthetic-staff" and claims["nonce"] == "nonce"
    with pytest.raises(ValueError):
        state.exchange(body)
    code = state.authorize(
        {
            "client_id": "fixture-web",
            "redirect_uri": body["redirect_uri"],
            "response_type": "code",
            "scope": "openid",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "nonce": "nonce2",
            "state": "state2",
        }
    )
    with pytest.raises(ValueError):
        state.exchange(body | {"code": code, "code_verifier": "wrong"})
    query = {
        "client_id": "fixture-web",
        "redirect_uri": body["redirect_uri"],
        "response_type": "code",
        "scope": "openid",
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "nonce": "nonce3",
        "state": "state3",
    }
    code = state.authorize(query)
    state.codes[code] = (0, query)
    with pytest.raises(ValueError):
        state.exchange(body | {"code": code})
    with pytest.raises(ValueError):
        state.authorize(query | {"redirect_uri": "https://evil.test/callback"})


def test_source_failure_control_is_bounded_and_has_no_authority_selection(runtime):
    assert hasattr(runtime, "parse_directory_control"), (
        "private upstream control required"
    )
    assert runtime.parse_directory_control(b'{"op":"upstream","deny":true}') is True
    for raw in (
        b'{"op":"upstream","deny":1}',
        b'{"op":"upstream","deny":false,"actor":"owner"}',
        b"x" * 257,
    ):
        with pytest.raises(ValueError):
            runtime.parse_directory_control(raw)


def test_node_mode_handoff_is_exact_and_default_has_no_directory_auth(tmp_path):
    import subprocess

    server = (ROOT / "scripts/test-tvt-account/server.mjs").as_uri()
    script = f"""import {{ directoryAuthEnvironment }} from {json.dumps(server)};
import assert from "node:assert/strict";
const config = {{ WSO_OIDC_ISSUER: "https://localhost:4321", WSO_OIDC_CLIENT_ID: "fixture-web",
 WSO_OIDC_CLIENT_SECRET: "a".repeat(64), WSO_AUTH_EXCHANGE_KEY: "b".repeat(64), WSO_FLOW_ENCRYPTION_KEY: "c".repeat(43) }};
assert.deepEqual(directoryAuthEnvironment({{}}, {{}}), {{}});
assert.deepEqual(directoryAuthEnvironment({{directoryMode:true,nextAuth:config}}, {{WSO_TEST_DIRECTORY_BROWSER:"1"}}), config);
for (const context of [{{}}, {{directoryMode:true,nextAuth:{{...config,WSO_WORKER_DATABASE_URL:"secret"}}}},
 {{directoryMode:true,nextAuth:{{...config,WSO_OIDC_ISSUER:"https://evil.test"}}}},
 {{directoryMode:true,nextAuth:{{...config,WSO_OIDC_ISSUER:"https://localhost:4321/path"}}}},
 {{directoryMode:true,nextAuth:{{...config,WSO_AUTH_EXCHANGE_KEY:"short"}}}}])
 assert.throws(()=>directoryAuthEnvironment(context, {{WSO_TEST_DIRECTORY_BROWSER:"1"}}));
assert.throws(()=>directoryAuthEnvironment({{}}, {{WSO_TEST_DIRECTORY_BROWSER:"true"}}));
assert.throws(()=>directoryAuthEnvironment({{directoryMode:true,nextAuth:config}}, {{}}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_owned_database_generator_keeps_exit_custody(runtime, monkeypatch):
    from types import SimpleNamespace

    from tests.integration import test_tvt_directory_admission as accepted
    from tests.integration import test_tvt_domain_scope as foundation
    from tests.support import directory_source_gate

    events = []
    monkeypatch.setattr(
        directory_source_gate,
        "verify_directory_source_gate",
        lambda: events.append("guard"),
    )

    def generator():
        events.append("database-enter")
        try:
            yield {"ADMIN": "owned-admin"}
        finally:
            events.append("database-exit")

    monkeypatch.setattr(
        accepted, "directory_database", SimpleNamespace(__wrapped__=generator)
    )
    monkeypatch.setattr(foundation, "seed_foundation", lambda admin: {"owner": admin})
    with (
        pytest.raises(ValueError, match="simulated body failure"),
        runtime.directory_database(monkeypatch) as database,
    ):
        assert database == ({"ADMIN": "owned-admin"}, {"owner": "owned-admin"})
        raise ValueError("simulated body failure")
    assert events == ["guard", "database-enter", "database-exit"]


def test_all_six_handlers_accept_real_serializers_and_real_http_denial(
    runtime, monkeypatch, tmp_path
):
    import io
    from types import SimpleNamespace

    from wso_core.tvt.account_protocol import AccountProtocol, SessionTaskIds
    from wso_core.tvt.directory_protocol import DirectoryProtocol

    captured = {}

    def no_network(self, folder, handler):
        self.origin = "https://localhost:1234"
        captured["handler"] = handler

    monkeypatch.setattr(runtime.OwnedHttps, "__init__", no_network)
    upstream = runtime.DirectoryUpstream(tmp_path)
    protocol = DirectoryProtocol(AccountProtocol(task_ids=SessionTaskIds()))
    calls = [
        protocol.device_list("synthetic-user-token", 0, 1000),
        protocol.channel_list("synthetic-user-token", [runtime.DIRECTORY_SN]),
        protocol.device_detail("synthetic-user-token", runtime.DIRECTORY_SN, False),
        protocol.channel_detail("synthetic-user-token", runtime.DIRECTORY_SN, 42),
        protocol.sent_shares("synthetic-user-token", 0, 1000, []),
        protocol.received_shares("synthetic-user-token", 0, 1000, []),
    ]
    statuses = []
    for request in calls:
        handler = captured["handler"].__new__(captured["handler"])
        handler.connection = SimpleNamespace(settimeout=lambda _: None)
        handler.path = "/mobile_v1.0" + request.path
        handler.headers = {"Content-Length": str(len(request.body))}
        handler.rfile, handler.wfile = io.BytesIO(request.body), io.BytesIO()
        handler.send_response = statuses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.send_error = statuses.append
        handler.do_POST()
        assert statuses[-1] == 200, request.path
    upstream.deny = True
    handler.rfile = io.BytesIO(calls[-1].body)
    handler.do_POST()
    assert statuses == [200] * 6 + [503]
    assert upstream.errors == [] and len(upstream.paths) == 7


def test_owned_https_close_retains_original_objects_when_join_is_uncertain(runtime):
    from types import SimpleNamespace

    events = []
    owner = runtime.OwnedHttps.__new__(runtime.OwnedHttps)
    server = SimpleNamespace(
        shutdown=lambda: events.append("shutdown"),
        server_close=lambda: events.append("server-close"),
    )
    thread = SimpleNamespace(
        join=lambda deadline: events.append(("join", deadline)), is_alive=lambda: True
    )
    owner.server, owner.thread = server, thread
    with pytest.raises(AssertionError):
        owner.close()
    assert owner.server is server and owner.thread is thread
    assert events == ["shutdown", "server-close", ("join", 5)]


def test_owned_https_request_threads_are_joined_and_handshake_is_bounded(runtime):
    import ast

    tree = ast.parse((ROOT / "scripts/test-tvt-account/runtime.py").read_text())
    owner = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OwnedHttps"
    )
    source = ast.unparse(owner)
    assert "daemon_threads = False" in source
    assert "do_handshake_on_connect=False" in source
    assert "settimeout(5)" in source


def signed_exchange(state):
    """A real bounded PKCE code for the fixed synthetic browser client."""
    import base64
    import hashlib

    verifier = "v" * 43
    code = state.authorize(
        {
            "client_id": "fixture-web",
            "redirect_uri": "https://localhost:3543/api/auth/callback",
            "response_type": "code",
            "scope": "openid",
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
            "nonce": "fresh-normal-login",
            "state": "fresh-state",
        }
    )
    return {
        "code": code,
        "client_id": "fixture-web",
        "client_secret": "s" * 48,
        "redirect_uri": "https://localhost:3543/api/auth/callback",
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }


def test_valid_signed_exchange_publishes_after_elapsed_startup_lifetime(runtime):
    state = runtime.DirectoryIssuerState(
        "https://localhost:1234", "fixed-staff", "s" * 48
    )
    # Offline timing model at the publication seam; this does not execute SQL.
    clock, grant = [1000], {"expires_at": 300}
    publications = []

    def publish():
        publications.append(clock[0])
        grant["expires_at"] = clock[0] + 300

    state.on_authenticated = publish
    assert grant["expires_at"] <= clock[0]
    body = signed_exchange(state)
    tokens = state.exchange(body)
    assert publications == [1000], (
        "valid normal login did not refresh fixture publication"
    )
    assert grant["expires_at"] == 1300
    assert tokens["token_type"] == "Bearer"
    with pytest.raises(ValueError, match="invalid issuer grant"):
        state.exchange(body)
    assert publications == [1000], "replayed code republished fixture authority"


@pytest.mark.parametrize(
    "change",
    [
        {"client_id": "foreign"},
        {"client_secret": "wrong"},
        {"code_verifier": "wrong"},
        {"redirect_uri": "https://evil.test/callback"},
        {"grant_type": "refresh_token"},
    ],
)
def test_invalid_signed_exchange_never_publishes_fixture_identity(runtime, change):
    state = runtime.DirectoryIssuerState(
        "https://localhost:1234", "fixed-staff", "s" * 48
    )
    publications = []
    state.on_authenticated = lambda: publications.append(True)
    with pytest.raises(ValueError, match="invalid issuer grant"):
        state.exchange(signed_exchange(state) | change)
    assert publications == []


def test_expired_signed_code_never_publishes_fixture_identity(runtime):
    state = runtime.DirectoryIssuerState(
        "https://localhost:1234", "fixed-staff", "s" * 48
    )
    publications = []
    state.on_authenticated = lambda: publications.append(True)
    body = signed_exchange(state)
    _, query = state.codes[body["code"]]
    state.codes[body["code"]] = (0, query)
    with pytest.raises(ValueError, match="invalid issuer grant"):
        state.exchange(body)
    assert publications == []


def test_failed_fixture_publication_cannot_issue_signed_tokens_or_replay(runtime):
    state = runtime.DirectoryIssuerState(
        "https://localhost:1234", "fixed-staff", "s" * 48
    )

    def refuse():
        raise ValueError("fixture publication refused")

    state.on_authenticated = refuse
    body = signed_exchange(state)
    with pytest.raises(ValueError, match="fixture publication refused"):
        state.exchange(body)
    with pytest.raises(ValueError, match="invalid issuer grant"):
        state.exchange(body)


@pytest.fixture
def tls_material(tmp_path):
    import ipaddress
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(issuer)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def material(
        *, host=True, ip=True, expired=False, other_signer=False, leaf_ca=False
    ):
        sans = [x509.DNSName("localhost" if host else "evil.test")]
        if ip:
            sans += [
                x509.IPAddress(ipaddress.ip_address(value))
                for value in ["127.0.0.1", "::1"]
            ]
        leaf = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            )
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(
                now - timedelta(hours=1) if expired else now + timedelta(days=1)
            )
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
        )
        if leaf_ca is not None:
            leaf = leaf.add_extension(
                x509.BasicConstraints(ca=leaf_ca, path_length=None), critical=True
            )
        leaf = leaf.sign(key if other_signer else ca_key, hashes.SHA256())
        return {
            "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
            "server.pem": leaf.public_bytes(serialization.Encoding.PEM),
            "server.key": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        }

    def write(raw):
        source = tmp_path / "tls-source"
        source.mkdir(exist_ok=True)
        for name, value in raw.items():
            (source / name).write_bytes(value)
        return source

    return material, write


def test_explicit_valid_dev_tls_copies_only_validated_material(
    runtime,
    monkeypatch,
    tmp_path,
    tls_material,
):
    assert hasattr(runtime, "browser_certificates"), (
        "validated optional development TLS required"
    )
    material, write = tls_material
    raw = material()
    source = write(raw)
    (source / "CA-PRIVATE-KEY-DO-NOT-COPY").write_text("private")
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setenv("WSO_TEST_ACCOUNT_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_BROWSER_TLS_DIR", str(source))
    runtime.browser_certificates(
        owned, lambda _: pytest.fail("default certificates selected")
    )
    assert {p.name: p.read_bytes() for p in owned.iterdir()} == raw


@pytest.mark.parametrize(
    "mutation",
    [
        "key",
        "signature",
        "expired",
        "host",
        "loopback",
        "truncated",
        "relative",
        "no-activation",
    ],
)
def test_invalid_dev_tls_fails_before_any_owned_file_is_written(
    runtime,
    monkeypatch,
    tmp_path,
    tls_material,
    mutation,
):
    assert hasattr(runtime, "browser_certificates"), (
        "validated optional development TLS required"
    )
    material, write = tls_material
    raw = material(
        host=mutation != "host",
        ip=mutation != "loopback",
        expired=mutation == "expired",
        other_signer=mutation == "signature",
    )
    if mutation == "key":
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        raw["server.key"] = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        ).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    if mutation == "truncated":
        raw["server.pem"] = b"invalid PEM"
    source = write(raw)
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setenv("WSO_TEST_ACCOUNT_BROWSER", "1")
    monkeypatch.setenv(
        "WSO_TEST_BROWSER_TLS_DIR",
        "relative" if mutation == "relative" else str(source),
    )
    if mutation == "no-activation":
        monkeypatch.delenv("WSO_TEST_ACCOUNT_BROWSER")
    with pytest.raises(ValueError, match="development TLS"):
        runtime.browser_certificates(owned, lambda _: pytest.fail("unsafe fallback"))
    assert list(owned.iterdir()) == []


def test_default_certificates_are_retained_without_explicit_dev_tls(
    runtime, monkeypatch, tmp_path
):
    assert hasattr(runtime, "browser_certificates"), (
        "validated optional development TLS required"
    )
    monkeypatch.delenv("WSO_TEST_BROWSER_TLS_DIR", raising=False)

    def default(folder):
        (folder / "default-selected").write_text("CI fixture")

    runtime.browser_certificates(tmp_path, default)
    assert (tmp_path / "default-selected").read_text() == "CI fixture"


def test_dev_tls_accepts_leaf_without_optional_basic_constraints(
    runtime,
    monkeypatch,
    tmp_path,
    tls_material,
):
    material, write = tls_material
    raw = material(leaf_ca=None)
    source = write(raw)
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setenv("WSO_TEST_ACCOUNT_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_BROWSER_TLS_DIR", str(source))
    runtime.browser_certificates(owned, lambda _: pytest.fail("unsafe fallback"))
    assert {p.name: p.read_bytes() for p in owned.iterdir()} == raw


def test_dev_tls_rejects_explicit_ca_leaf_before_copy(
    runtime,
    monkeypatch,
    tmp_path,
    tls_material,
):
    material, write = tls_material
    source = write(material(leaf_ca=True))
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setenv("WSO_TEST_ACCOUNT_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_BROWSER_TLS_DIR", str(source))
    with pytest.raises(ValueError, match="development TLS"):
        runtime.browser_certificates(owned, lambda _: pytest.fail("unsafe fallback"))
    assert list(owned.iterdir()) == []


def test_bound_signed_login_persists_new_identity_and_fences_other_entries(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from uuid import UUID

    actor, tenant, identity = (UUID(int=value) for value in (1, 2, 3))
    state = {"userId": str(actor), "tenantId": str(tenant)}
    issuer = SimpleNamespace(
        origin="https://localhost:1234",
        state=runtime.DirectoryIssuerState(
            "https://localhost:1234", str(actor), "s" * 48
        ),
    )
    database = ({}, {"staff": actor, "tenant": tenant})
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    observer = runtime.AdmissionGate(tmp_path / "gate.sqlite")

    def publication(received_database, key, origin):
        assert received_database is database
        assert key == tmp_path / "owned-key"
        assert origin == "https://localhost:1234"
        assert observer.enter("api") is False and observer.enter("worker") is False
        return identity

    monkeypatch.setattr(runtime, "publish_directory_identity", publication)
    path = tmp_path / "context.json"
    runtime.bind_directory_login(
        issuer, database, tmp_path / "owned-key", gate, path, state
    )
    assert not path.exists(), "binding spent the grant lifetime before login"
    assert gate.enter("api")
    try:
        issuer.state.exchange(signed_exchange(issuer.state))
    finally:
        gate.leave("api")
    assert json.loads(path.read_text()) == state | {"identityId": str(identity)}
    assert database[1]["identity"] == identity
    assert observer.enter("worker")
    observer.leave("worker")


@pytest.mark.parametrize("pending", ["no-issuer", "api", "worker"])
def test_bound_login_refuses_unsettled_entries_without_publication(
    runtime, monkeypatch, tmp_path, pending
):
    from types import SimpleNamespace
    from uuid import UUID

    actor, tenant = UUID(int=1), UUID(int=2)
    state = {"userId": str(actor), "tenantId": str(tenant)}
    issuer = SimpleNamespace(
        origin="https://localhost:1234",
        state=runtime.DirectoryIssuerState(
            "https://localhost:1234", str(actor), "s" * 48
        ),
    )
    gate = runtime.AdmissionGate(tmp_path / "gate.sqlite", create=True)
    monkeypatch.setattr(
        runtime,
        "publish_directory_identity",
        lambda *args: pytest.fail("unsettled publication"),
    )
    path = tmp_path / "context.json"
    runtime.bind_directory_login(
        issuer,
        ({}, {"staff": actor, "tenant": tenant}),
        tmp_path / "owned-key",
        gate,
        path,
        state,
    )
    entries = [] if pending == "no-issuer" else ["api", pending]
    for side in entries:
        assert gate.enter(side)
    try:
        with pytest.raises(ValueError, match="settled calls"):
            issuer.state.exchange(signed_exchange(issuer.state))
    finally:
        for side in entries:
            gate.leave(side)
    assert not path.exists() and "identityId" not in state
    assert gate.enter("worker")
    gate.leave("worker")
