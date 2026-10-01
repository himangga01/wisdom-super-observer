"""Real loopback TLS process tests. The strict seam is NOT SQL/APK acceptance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pydantic import SecretStr
from wso_contracts.tvt.account import (
    AccountIdentity,
    AccountLogin,
    AccountLogoutView,
    AccountProfileFields,
    AccountProfileView,
    AccountRefresh,
    ImageChallengeView,
    ImageCheckRequest,
    ImageCheckView,
)
from wso_core.tvt.account_projection import AccountFailure

IDENTITY = UUID("00000000-0000-4000-8000-000000000001")


class StrictExecutor:
    def __init__(self, folder: Path):
        from threading import Lock

        self.folder, self.used, self.lock = folder, set(), Lock()

    def enter(self, ticket, correlation_id, deadline_ms):
        assert 0 < deadline_ms <= 20000
        with self.lock:
            if ticket in self.used:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            self.used.add(ticket)
            with (self.folder / "calls").open("a", encoding="utf-8") as stream:
                stream.write(correlation_id + "\n")
            with (self.folder / "budgets").open("a", encoding="utf-8") as stream:
                stream.write(str(deadline_ms) + "\n")
        if ticket.startswith("ab"):
            from wso_api.tvt.session_service import AccountWorkerExecutor
            from wso_core.tvt.ports import AccountErrorCode, AccountResult

            # Execute the real public result projection; this path uses no vault.
            AccountWorkerExecutor(None, ())._result(
                AccountResult(
                    http_status=200,
                    native_msgcode=404,
                    correlation_id=correlation_id,
                    error_code=AccountErrorCode.DC_PENDING,
                )
            )
        if ticket.startswith("cc"):
            raise AccountFailure("CHALLENGE_EXPIRED", 409)
        if ticket.startswith("bb"):
            raise AccountFailure("RENEWAL_OUTCOME_UNKNOWN", 409)
        if ticket.startswith("aa"):
            raise AccountFailure("PRIVATE-UNKNOWN-WORKER-DETAIL", 418)
        if ticket.startswith("ee"):
            raise ValueError("PRIVATE-UPSTREAM-SECRET")
        if ticket.startswith("dd"):
            time.sleep(0.65)
            (self.folder / "settled").write_text("yes", encoding="utf-8")

    def identity(self, correlation_id, generation=1):
        return AccountIdentity(
            identity_id=IDENTITY,
            region="eu",
            brand="tvt",
            state="READY",
            generation=generation,
            request_id=correlation_id,
        )

    def login(self, ticket, body, *, deadline_ms, correlation_id):
        assert (
            type(body) is AccountLogin
            and body.secret.get_secret_value() == "private-password"
        )
        self.enter(ticket, correlation_id, deadline_ms)
        return self.identity(correlation_id)

    def image_challenge(self, ticket, *, deadline_ms, correlation_id):
        self.enter(ticket, correlation_id, deadline_ms)
        return ImageChallengeView(
            challenge_id=IDENTITY,
            media_type="image/png",
            image_base64="A" * 90000,
            request_id=correlation_id,
        )

    def check_image(self, ticket, body, *, deadline_ms, correlation_id):
        assert (
            type(body) is ImageCheckRequest
            and body.image_code.get_secret_value() == "1234"
        )
        self.enter(ticket, correlation_id, deadline_ms)
        return ImageCheckView(request_id=correlation_id)

    def profile(self, ticket, *, deadline_ms, correlation_id):
        self.enter(ticket, correlation_id, deadline_ms)
        return AccountProfileView(
            **self.identity(correlation_id).model_dump(),
            profile=AccountProfileFields(nickname="test"),
        )

    def renew(self, ticket, body, *, deadline_ms, correlation_id):
        assert type(body) is AccountRefresh and body.expected_generation == 1
        self.enter(ticket, correlation_id, deadline_ms)
        return self.identity(correlation_id, 2)

    def logout(self, ticket, *, deadline_ms, correlation_id):
        self.enter(ticket, correlation_id, deadline_ms)
        return AccountLogoutView(
            identity_id=IDENTITY,
            upstream_outcome="confirmed",
            request_id=correlation_id,
        )


def serve(folder: Path):
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    worker = StrictExecutor(folder)
    config = ServerConfig(
        bind="localhost:0",
        ca=(folder / "ca.pem").read_bytes(),
        certificate=(folder / "server.pem").read_bytes(),
        key=(folder / "server.key").read_bytes(),
        client_sans=frozenset(json.loads((folder / "allow.json").read_text())),
        capacity=1,
    )
    server = AccountRpcServer(config, worker)
    (folder / "port").write_text(str(server.start()), encoding="utf-8")
    sys.stdin.readline()
    drained = server.close(grace=0.02)
    (folder / "closed").write_text(str(drained), encoding="utf-8")


def certs(folder):
    folder.chmod(0o700)
    if os.name == "nt":
        principal = os.environ["USERDOMAIN"] + "\\" + os.environ["USERNAME"]
        subprocess.run(
            [
                "icacls",
                str(folder),
                "/inheritance:r",
                "/grant:r",
                principal + ":(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
        )
    now = datetime.now(UTC)

    def key():
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def name(value):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, value)])

    ca_key = key()
    ca = (
        x509.CertificateBuilder()
        .subject_name(name("test-ca"))
        .issuer_name(name("test-ca"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    (folder / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for label, san, server in (
        ("server", "localhost", True),
        ("client", "api.test", False),
        ("other", "other.test", False),
    ):
        private = key()
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name(label))
            .issuer_name(ca.subject)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [
                        ExtendedKeyUsageOID.SERVER_AUTH
                        if server
                        else ExtendedKeyUsageOID.CLIENT_AUTH
                    ]
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        (folder / (label + ".pem")).write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM)
        )
        path = folder / (label + ".key")
        path.write_bytes(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)
    (folder / "allow.json").write_text(json.dumps(["api.test"]), encoding="utf-8")


class Process:
    def __init__(self, folder):
        self.folder = folder
        self.stdout = (folder / "stdout").open("wb")
        self.stderr = (folder / "stderr").open("wb")
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", str(folder)],
            stdin=subprocess.PIPE,
            stdout=self.stdout,
            stderr=self.stderr,
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
                "PYTHONIOENCODING": "utf-8",
            },
        )
        end = time.monotonic() + 10
        while (
            not (folder / "port").exists()
            and time.monotonic() < end
            and self.process.poll() is None
        ):
            time.sleep(0.02)
        if not (folder / "port").exists():
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=5)
            self.stdout.close()
            self.stderr.close()
            raise AssertionError("worker did not start")
        self.target = "localhost:" + (folder / "port").read_text()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.communicate(b"close\n", timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
                raise AssertionError("owned worker failed bounded shutdown") from None
        self.stdout.close()
        self.stderr.close()
        assert self.process.returncode == 0

    def client(self, label="client", host=None):
        from wso_tvt_bridge.client import AccountRpcClient, ClientConfig

        return AccountRpcClient(
            ClientConfig(
                endpoint=host or self.target,
                ca=(self.folder / "ca.pem").read_bytes(),
                certificate=(self.folder / (label + ".pem")).read_bytes(),
                key=(self.folder / (label + ".key")).read_bytes(),
            )
        )

    def calls(self):
        path = self.folder / "calls"
        return path.read_text().splitlines() if path.exists() else []


@pytest.fixture(autouse=True)
def remove_ephemeral_credentials(tmp_path):
    yield
    root = tmp_path.resolve()
    for directory in (root, root / "other-ca"):
        for name in (
            "ca.pem",
            "server.pem",
            "server.key",
            "client.pem",
            "client.key",
            "other.pem",
            "other.key",
        ):
            target = (directory / name).resolve()
            assert target.is_relative_to(root)
            target.unlink(missing_ok=True)


@pytest.fixture
def worker(tmp_path):
    certs(tmp_path)
    value = Process(tmp_path)
    try:
        yield value
    finally:
        value.close()


def test_six_typed_methods_and_ticket_replay_through_separate_process(worker):
    assert worker.process.pid != os.getpid()
    with worker.client() as client:
        body = AccountLogin(
            region="eu",
            brand="tvt",
            mode="email",
            account=SecretStr("a@example.invalid"),
            secret=SecretStr("private-password"),
        )
        assert (
            client.login(
                "01" * 32, body, deadline_ms=3000, correlation_id="login"
            ).identity_id
            == IDENTITY
        )
        assert (
            len(
                client.image_challenge(
                    "02" * 32, deadline_ms=3000, correlation_id="image"
                ).image_base64
            )
            == 90000
        )
        check = ImageCheckRequest(
            region="eu",
            brand="tvt",
            challenge_id=IDENTITY,
            image_code=SecretStr("1234"),
        )
        assert client.check_image(
            "03" * 32, check, deadline_ms=3000, correlation_id="check"
        ).checked
        assert (
            client.profile(
                "04" * 32, deadline_ms=3000, correlation_id="profile"
            ).profile.nickname
            == "test"
        )
        assert (
            client.renew(
                "05" * 32,
                AccountRefresh(expected_generation=1),
                deadline_ms=3000,
                correlation_id="renew",
            ).generation
            == 2
        )
        assert (
            client.logout("06" * 32, deadline_ms=3000, correlation_id="logout").state
            == "CLOSED"
        )
        with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
            client.profile("04" * 32, deadline_ms=3000, correlation_id="replay")
    assert len(worker.calls()) == 6


@pytest.mark.parametrize(
    "case", ["missing", "wrong-ca", "wrong-host", "unauthorized-san"]
)
def test_mtls_negative_never_reaches_executor(worker, case, tmp_path):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.generated import tvt_bridge_pb2_grpc as rpc

    ca = (tmp_path / "ca.pem").read_bytes()
    if case == "wrong-ca":
        other = tmp_path / "other-ca"
        other.mkdir()
        certs(other)
        ca = (other / "ca.pem").read_bytes()
    label = "other" if case == "unauthorized-san" else "client"
    credentials = grpc.ssl_channel_credentials(
        ca,
        None if case == "missing" else (tmp_path / (label + ".key")).read_bytes(),
        None if case == "missing" else (tmp_path / (label + ".pem")).read_bytes(),
    )
    target = (
        worker.target.replace("localhost", "127.0.0.1")
        if case == "wrong-host"
        else worker.target
    )
    with grpc.secure_channel(target, credentials) as channel:
        stub = rpc.AccountBridgeV1Stub(channel)
        with pytest.raises(grpc.RpcError):
            stub.Profile(
                pb.ProfileRequest(
                    context=pb.RpcContext(
                        protocol_version=1,
                        ticket="01" * 32,
                        deadline_ms=1000,
                        correlation_id="denied",
                    )
                ),
                timeout=1,
            )
    assert worker.calls() == []


def test_invalid_version_unknown_fields_unknown_method_and_large_frame(worker):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    creds = grpc.ssl_channel_credentials(
        (worker.folder / "ca.pem").read_bytes(),
        (worker.folder / "client.key").read_bytes(),
        (worker.folder / "client.pem").read_bytes(),
    )
    with grpc.secure_channel(worker.target, creds) as channel:
        call = channel.unary_unary(
            "/wso.tvt.account.v1.AccountBridgeV1/Profile",
            response_deserializer=pb.AccountReply.FromString,
        )
        request = pb.ProfileRequest(
            context=pb.RpcContext(
                protocol_version=0,
                ticket="01" * 32,
                deadline_ms=1000,
                correlation_id="old",
            )
        )
        assert (
            call(request.SerializeToString(), timeout=1).failure_code
            == "ACCOUNT_PROTOCOL_INVALID"
        )
        request.context.protocol_version = 1
        assert (
            call(request.SerializeToString() + b"\x18\x01", timeout=1).failure_code
            == "ACCOUNT_INPUT_INVALID"
        )
        for payload in (b"\xff", b"x" * 524289):
            with pytest.raises(grpc.RpcError):
                call(payload, timeout=1)
        with pytest.raises(grpc.RpcError) as caught:
            channel.unary_unary("/wso.tvt.account.v1.AccountBridgeV1/Execute")(
                b"", timeout=1
            )
        assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert worker.calls() == []


def test_executor_exception_is_redacted(worker):
    with worker.client() as client:
        with pytest.raises(AccountFailure) as caught:
            client.profile("ee" * 32, deadline_ms=1000, correlation_id="failure")
        assert str(caught.value) == "ACCOUNT_UNAVAILABLE"
    assert "PRIVATE-UPSTREAM-SECRET" not in (worker.folder / "stderr").read_text()


def test_deadline_quarantines_slot_until_actual_settlement(worker):
    with worker.client() as client:
        start = time.monotonic()
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            client.profile("dd" * 32, deadline_ms=150, correlation_id="slow")
        assert time.monotonic() - start < 0.55
        with pytest.raises(AccountFailure, match="SESSION_BUSY"):
            client.profile("02" * 32, deadline_ms=1000, correlation_id="busy")
        end = time.monotonic() + 2
        while not (worker.folder / "settled").exists() and time.monotonic() < end:
            time.sleep(0.02)
        assert (
            client.profile(
                "03" * 32, deadline_ms=1000, correlation_id="after"
            ).request_id
            == "after"
        )
    assert worker.calls() == ["slow", "after"]


def test_client_close_cancels_waiter_and_reconnect_has_fresh_epoch(worker):
    from concurrent.futures import ThreadPoolExecutor

    client = worker.client()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.profile, "dd" * 32, deadline_ms=3000, correlation_id="cancelled"
        )
        end = time.monotonic() + 2
        while not worker.calls() and time.monotonic() < end:
            time.sleep(0.01)
        client.close()
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(timeout=1)
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        client.profile("02" * 32, deadline_ms=1000, correlation_id="closed")
    end = time.monotonic() + 2
    while not (worker.folder / "settled").exists() and time.monotonic() < end:
        time.sleep(0.02)
    with worker.client() as fresh:
        assert (
            fresh.profile(
                "03" * 32, deadline_ms=1000, correlation_id="fresh"
            ).request_id
            == "fresh"
        )


def test_certificate_rotation_removes_old_san_with_fresh_process(tmp_path):
    certs(tmp_path)
    old = Process(tmp_path)
    with old.client() as client:
        assert (
            client.profile("01" * 32, deadline_ms=1000, correlation_id="old").request_id
            == "old"
        )
    old.close()
    (tmp_path / "port").unlink()
    (tmp_path / "allow.json").write_text(json.dumps(["other.test"]), encoding="utf-8")
    fresh = Process(tmp_path)
    try:
        with (
            fresh.client() as rejected,
            pytest.raises(AccountFailure, match="ACCOUNT_DENIED"),
        ):
            rejected.profile("02" * 32, deadline_ms=1000, correlation_id="removed")
        with fresh.client("other") as accepted:
            assert (
                accepted.profile(
                    "03" * 32, deadline_ms=1000, correlation_id="rotated"
                ).request_id
                == "rotated"
            )
        assert fresh.calls() == ["old", "rotated"]
    finally:
        fresh.close()


def test_server_close_retires_active_call_without_forged_completion(worker):
    from concurrent.futures import ThreadPoolExecutor

    with worker.client() as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.profile, "dd" * 32, deadline_ms=3000, correlation_id="shutdown"
        )
        end = time.monotonic() + 2
        while not worker.calls() and time.monotonic() < end:
            time.sleep(0.01)
        assert worker.calls() == ["shutdown"]
        worker.close()
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(timeout=1)
    assert (worker.folder / "closed").read_text() == "False"
    assert (worker.folder / "settled").exists()


def test_new_ca_and_credentials_require_fresh_configured_client(tmp_path):
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig

    certs(tmp_path)
    old_ca = (tmp_path / "ca.pem").read_bytes()
    old_cert = (tmp_path / "client.pem").read_bytes()
    old_key = (tmp_path / "client.key").read_bytes()
    old = Process(tmp_path)
    with old.client() as client:
        assert (
            client.profile(
                "01" * 32, deadline_ms=1000, correlation_id="before-rotate"
            ).request_id
            == "before-rotate"
        )
    old.close()
    (tmp_path / "port").unlink()
    certs(tmp_path)
    fresh = Process(tmp_path)
    try:
        with (
            AccountRpcClient(
                ClientConfig(
                    endpoint=fresh.target, ca=old_ca, certificate=old_cert, key=old_key
                )
            ) as stale,
            pytest.raises(AccountFailure),
        ):
            stale.profile("02" * 32, deadline_ms=1000, correlation_id="stale-ca")
        with fresh.client() as client:
            assert (
                client.profile(
                    "03" * 32, deadline_ms=1000, correlation_id="fresh-ca"
                ).request_id
                == "fresh-ca"
            )
        assert fresh.calls() == ["before-rotate", "fresh-ca"]
    finally:
        fresh.close()


def test_malformed_dto_and_spoofed_metadata_are_not_authority(worker):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.generated import tvt_bridge_pb2_grpc as rpc

    creds = grpc.ssl_channel_credentials(
        (worker.folder / "ca.pem").read_bytes(),
        (worker.folder / "client.key").read_bytes(),
        (worker.folder / "client.pem").read_bytes(),
    )
    with grpc.secure_channel(worker.target, creds) as channel:
        stub = rpc.AccountBridgeV1Stub(channel)
        for payload in (
            b'{"worker_url":"secret"}',
            b'{"mode":"email","mode":"phone"}',
            b"{}",
        ):
            reply = stub.Login(
                pb.LoginRequest(
                    context=pb.RpcContext(
                        protocol_version=1,
                        ticket="01" * 32,
                        deadline_ms=1000,
                        correlation_id="bad-dto",
                    ),
                    account_login_json=payload,
                ),
                timeout=1,
            )
            assert reply.failure_code == "ACCOUNT_INPUT_INVALID"
    other = grpc.ssl_channel_credentials(
        (worker.folder / "ca.pem").read_bytes(),
        (worker.folder / "other.key").read_bytes(),
        (worker.folder / "other.pem").read_bytes(),
    )
    with (
        grpc.secure_channel(worker.target, other) as channel,
        pytest.raises(grpc.RpcError) as caught,
    ):
        rpc.AccountBridgeV1Stub(channel).Profile(
            pb.ProfileRequest(
                context=pb.RpcContext(
                    protocol_version=1,
                    ticket="02" * 32,
                    deadline_ms=1000,
                    correlation_id="spoof",
                )
            ),
            timeout=1,
            metadata=(("x509_subject_alternative_name", "api.test"),),
        )
    assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
    assert worker.calls() == []


def test_original_deadline_includes_serialization_before_tls(worker, monkeypatch):
    import wso_tvt_bridge.client as module

    original = module.encode_input

    def delayed(body):
        time.sleep(0.18)
        return original(body)

    monkeypatch.setattr(module, "encode_input", delayed)
    body = AccountLogin(
        region="eu",
        brand="tvt",
        mode="email",
        account=SecretStr("a@example.invalid"),
        secret=SecretStr("private-password"),
    )
    with (
        worker.client() as client,
        pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"),
    ):
        client.login("dd" * 32, body, deadline_ms=350, correlation_id="one-deadline")
    assert 0 < int((worker.folder / "budgets").read_text().strip()) < 180
    assert worker.calls() == ["one-deadline"]


def test_client_rejects_misbound_public_response(worker):
    from concurrent.futures import Future

    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    class MisboundPeer:
        def future(self, request, **kwargs):
            pending = Future()
            answer = AccountProfileView(
                identity_id=IDENTITY,
                region="eu",
                brand="tvt",
                state="READY",
                generation=1,
                request_id="wrong-correlation",
                profile=AccountProfileFields(),
            )
            pending.set_result(
                pb.AccountReply(public_json=answer.model_dump_json().encode())
            )
            return pending

    with (
        worker.client() as client,
        pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"),
    ):
        client._call(
            MisboundPeer(),
            pb.ProfileRequest,
            "01" * 32,
            1000,
            "correct-correlation",
            AccountProfileView,
        )
    assert worker.calls() == []


@pytest.mark.parametrize(
    "ticket,operation,expected,status",
    [
        ("cc", "check_image", "CHALLENGE_EXPIRED", 409),
        ("bb", "renew", "RENEWAL_OUTCOME_UNKNOWN", 409),
        ("aa", "profile", "ACCOUNT_UNAVAILABLE", 503),
        ("ab", "profile", "ACCOUNT_DC_PENDING", 502),
    ],
)
def test_worker_failure_vocabulary_crosses_real_rpc(
    worker, ticket, operation, expected, status
):
    with worker.client() as client:
        with pytest.raises(AccountFailure) as caught:
            if operation == "check_image":
                client.check_image(
                    ticket * 32,
                    ImageCheckRequest(
                        region="eu",
                        brand="tvt",
                        challenge_id=IDENTITY,
                        image_code=SecretStr("1234"),
                    ),
                    deadline_ms=3000,
                    correlation_id="failure-check",
                )
            elif operation == "renew":
                client.renew(
                    ticket * 32,
                    AccountRefresh(expected_generation=1),
                    deadline_ms=3000,
                    correlation_id="failure-renew",
                )
            else:
                client.profile(
                    ticket * 32, deadline_ms=3000, correlation_id="failure-profile"
                )
        assert (caught.value.code, caught.value.status, str(caught.value)) == (
            expected,
            status,
            expected,
        )
    assert len(worker.calls()) == 1


@pytest.mark.parametrize("via_factory", [False, True], ids=["direct", "factory"])
@pytest.mark.parametrize(
    "case",
    [
        "ca",
        "certificate",
        "key",
        "mismatch",
        "encrypted-key",
        "ca-tail",
        "chain-tail",
        "key-tail",
        "empty",
        "oversized",
    ],
)
def test_invalid_tls_is_sanitized_before_channel_creation(
    tmp_path, monkeypatch, via_factory, case
):
    from wso_tvt_bridge.client import (
        AccountRpcClient,
        ClientConfig,
        create_account_worker_client,
    )

    certs(tmp_path)
    data = {
        name: (tmp_path / file).read_bytes()
        for name, file in (
            ("ca", "ca.pem"),
            ("certificate", "client.pem"),
            ("key", "client.key"),
        )
    }
    if case in ("ca", "certificate", "key"):
        data[case] = b"PRIVATE-MALFORMED-PEM"
    elif case == "mismatch":
        data["key"] = (tmp_path / "other.key").read_bytes()
    elif case == "encrypted-key":
        private = serialization.load_pem_private_key(data["key"], password=None)
        data["key"] = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"fixture-password"),
        )
    elif case in ("ca-tail", "chain-tail", "key-tail"):
        data[
            {"ca-tail": "ca", "chain-tail": "certificate", "key-tail": "key"}[case]
        ] += b"PRIVATE-TRAILING-DATA"
    elif case == "empty":
        data["ca"] = b""
    else:
        data["ca"] = b"x" * 65537

    def forbid_channel(*args, **kwargs):
        pytest.fail("invalid TLS configuration reached channel creation")

    monkeypatch.setattr(grpc, "secure_channel", forbid_channel)
    with pytest.raises(AccountFailure) as caught:
        if via_factory:
            for name, file in (
                ("ca", "ca.pem"),
                ("certificate", "client.pem"),
                ("key", "client.key"),
            ):
                (tmp_path / file).write_bytes(data[name])
            create_account_worker_client(
                {
                    "WSO_TVT_BRIDGE_ENDPOINT": "localhost:12345",
                    "WSO_TVT_BRIDGE_CA_FILE": str(tmp_path / "ca.pem"),
                    "WSO_TVT_BRIDGE_CLIENT_CERT_FILE": str(tmp_path / "client.pem"),
                    "WSO_TVT_BRIDGE_CLIENT_KEY_FILE": str(tmp_path / "client.key"),
                }
            )
        else:
            AccountRpcClient(ClientConfig(endpoint="localhost:12345", **data))
    assert (caught.value.code, caught.value.status, str(caught.value)) == (
        "ACCOUNT_UNAVAILABLE",
        503,
        "ACCOUNT_UNAVAILABLE",
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_valid_ca_bundle_and_leaf_chain_connect_normally(worker):
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig

    ca = (worker.folder / "ca.pem").read_bytes()
    with AccountRpcClient(
        ClientConfig(
            endpoint=worker.target,
            ca=ca + ca,
            certificate=(worker.folder / "client.pem").read_bytes() + ca,
            key=(worker.folder / "client.key").read_bytes(),
        )
    ) as client:
        result = client.profile("09" * 32, deadline_ms=3000, correlation_id="bundled")
        assert result.identity_id == IDENTITY
    assert worker.calls() == ["bundled"]


if __name__ == "__main__":
    assert sys.argv[1] == "--serve"
    serve(Path(sys.argv[2]))
