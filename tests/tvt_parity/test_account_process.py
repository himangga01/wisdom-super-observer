"""Host process-boundary proofs only; no APK/server interoperability claim."""

import importlib
import ssl
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def modules():
    return (
        importlib.import_module("wso_core.tvt.account_protocol"),
        importlib.import_module("wso_core.tvt.account_transport"),
        importlib.import_module("wso_core.tvt.account_process"),
    )


@pytest.fixture
def child_processes(monkeypatch):
    _, _, boundary = modules()
    original = subprocess.Popen
    children = []
    launches = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        launches.append((args, kwargs))
        return process

    monkeypatch.setattr(boundary.subprocess, "Popen", spawn)
    yield children, launches
    # Emergency test cleanup is separate from assertions on production settlement.
    for child in children:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)


def inject_worker(monkeypatch, boundary, code, *, replace=False):
    original = boundary._worker_command

    def command():
        argv = original()
        prefix = argv[-1].rsplit("_child_main()", 1)[0]
        argv[-1] = prefix + code + ("" if replace else "\n_child_main()")
        return argv

    monkeypatch.setattr(boundary, "_worker_command", command)


def client(boundary, transport, *, origin="https://127.0.0.1:1", **kwargs):
    return boundary.ProcessAccountTransport(
        transport.OriginPolicy({"host-test": frozenset({origin})}),
        region="host-test",
        origin=origin,
        **kwargs,
    )


def assert_settled(children):
    assert children
    assert all(child.poll() is not None for child in children)
    assert all(child.stdin.closed and child.stdout.closed for child in children)
    assert not [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("account-process-")
    ]


def test_dns_block_is_killed_within_total_deadline_and_io_is_settled(
    monkeypatch, tmp_path, child_processes
):
    p, t, boundary = modules()
    marker = tmp_path / "entered-dns"
    inject_worker(
        monkeypatch,
        boundary,
        "import socket,time\n"
        "def blocked(*args,**kwargs):\n"
        f"    open({str(marker)!r},'w').write('entered')\n"
        "    time.sleep(3600)\n"
        "socket.getaddrinfo=blocked\n",
    )
    transport = client(boundary, t, timeout_seconds=1.2, settlement_seconds=0.3)
    started = time.monotonic()
    with pytest.raises(boundary.AccountProcessError) as error:
        transport.send(p.AccountRequest("/user/info/get", b"{}"))
    assert time.monotonic() - started < 1.5
    assert marker.read_text() == "entered"
    assert "deadline" in str(error.value).lower()
    assert error.value.__context__ is None
    assert_settled(child_processes[0])


def test_startup_and_blocked_large_pipe_write_share_deadline(
    monkeypatch, child_processes
):
    p, t, boundary = modules()
    inject_worker(monkeypatch, boundary, "import time;time.sleep(3600)", replace=True)
    transport = client(boundary, t, timeout_seconds=0.8, settlement_seconds=0.25)
    started = time.monotonic()
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/login", b"x" * p.MAX_BODY_BYTES))
    assert time.monotonic() - started < 1.1
    assert_settled(child_processes[0])


@pytest.fixture
def tls_peer(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "host-cert.pem", tmp_path / "host-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    received = []
    reached = threading.Event()
    release = threading.Event()
    mode = {"value": "success"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers["Content-Type"], body))
            reached.set()
            if mode["value"] == "header-block":
                release.wait(3)
                return
            if mode["value"] == "body-block":
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b'{"basic":')
                self.wfile.flush()
                release.wait(3)
                return
            reply = (
                b'{"basic":{"msgcode":200},"data":{"token":"host-private-token"}}'
                if mode["value"] == "success"
                else b'{"token":"host-private-token",'
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://localhost:{server.server_port}", cert_path, received, mode, reached
    release.set()
    server.shutdown()
    server.server_close()
    thread.join(2)


def trust_host_peer(monkeypatch, boundary, certificate):
    # Test-only trust injection: the actual child still verifies TLS and hostname.
    inject_worker(
        monkeypatch,
        boundary,
        "import ssl\noriginal_context=ssl.create_default_context\n"
        f"ssl.create_default_context=lambda:original_context(cafile={str(certificate)!r})\n",
    )


def test_real_child_https_success_private_bytes_and_clean_environment(
    monkeypatch, tls_peer, child_processes
):
    p, t, boundary = modules()
    origin, certificate, received, _, _ = tls_peer
    monkeypatch.setenv("WSO_ACCOUNT_SECRET", "host-private-secret")
    monkeypatch.setenv("HTTPS_PROXY", "https://host-private-proxy")
    monkeypatch.setenv("SSL_CERT_FILE", "host-private-override")
    trust_host_peer(monkeypatch, boundary, certificate)
    transport = client(boundary, t, origin=origin, timeout_seconds=3)
    request = p.AccountRequest(
        "/user/info/get", b'{"basic":{"token":"request-private"}}'
    )
    response = transport.send(request)
    assert response.http_status == 200 and response.native_msgcode == 200
    assert p.parse_login(response).token == "host-private-token"
    assert received == [
        (
            "/user/info/get",
            "application/json;charset=UTF-8",
            request.body,
        )
    ]
    assert "private" not in repr(response) + repr(request) + repr(transport)
    children, launches = child_processes
    assert_settled(children)
    argv, options = launches[0]
    assert "request-private" not in repr(argv)
    assert options["close_fds"] and options["stderr"] == subprocess.DEVNULL
    assert not {
        "WSO_ACCOUNT_SECRET",
        "HTTPS_PROXY",
        "SSL_CERT_FILE",
        "PYTHONPATH",
    } & set(options["env"])


@pytest.mark.parametrize("mode", ["malformed", "header-block", "body-block"])
def test_real_child_https_failure_and_header_block_are_sanitized_and_settled(
    monkeypatch, tls_peer, child_processes, mode
):
    p, t, boundary = modules()
    origin, certificate, _, state, reached = tls_peer
    state["value"] = mode
    trust_host_peer(monkeypatch, boundary, certificate)
    transport = client(
        boundary, t, origin=origin, timeout_seconds=3, settlement_seconds=0.5
    )
    started = time.monotonic()
    with pytest.raises(boundary.AccountProcessError) as error:
        transport.send(p.AccountRequest("/user/info/get", b"{}"))
    assert reached.is_set(), str(error.value)
    assert time.monotonic() - started < 3.3
    assert "private" not in repr(error.value)
    assert error.value.__context__ is None
    assert_settled(child_processes[0])


@pytest.mark.parametrize(
    "script",
    [
        "import os;os.write(1,b'x'*200000);import time;time.sleep(3600)",
        "import os;os.write(1,b'{')",
        "import os;os._exit(7)",
    ],
)
def test_child_reply_overflow_malformed_and_exit_fail_closed(
    monkeypatch, child_processes, script
):
    p, t, boundary = modules()
    inject_worker(monkeypatch, boundary, script, replace=True)
    transport = client(
        boundary, t, timeout_seconds=1.2, settlement_seconds=0.3, max_body_bytes=32
    )
    started = time.monotonic()
    with pytest.raises(boundary.AccountProcessError) as error:
        transport.send(p.AccountRequest("/user/login", b"{}"))
    assert time.monotonic() - started < 1.5
    assert error.value.__context__ is None
    assert_settled(child_processes[0])


def test_busy_admission_and_close_cancel_an_owned_child(
    monkeypatch, tmp_path, child_processes
):
    p, t, boundary = modules()
    marker = tmp_path / "child-ready"
    inject_worker(
        monkeypatch,
        boundary,
        f"open({str(marker)!r},'w').write('ready')\nimport time;time.sleep(3600)",
        replace=True,
    )
    transport = client(boundary, t, timeout_seconds=3)
    errors = []

    def send():
        try:
            transport.send(p.AccountRequest("/user/login", b"{}"))
        except boundary.AccountProcessError as error:
            errors.append(error)

    thread = threading.Thread(target=send)
    thread.start()
    end = time.monotonic() + 2
    while not marker.exists() and time.monotonic() < end:
        time.sleep(0.01)
    assert marker.exists()
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/login", b"{}"))
    assert len(child_processes[0]) == 1
    transport.close()
    thread.join(1)
    assert not thread.is_alive() and errors
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/login", b"{}"))
    assert_settled(child_processes[0])


@pytest.mark.parametrize("kind", ["duck", "subclass", "path", "body", "oversized"])
def test_closed_request_types_and_bounds_reject_before_spawn(monkeypatch, kind):
    p, t, boundary = modules()
    calls = []
    monkeypatch.setattr(boundary.subprocess, "Popen", lambda *a, **k: calls.append(a))

    class Subclass(p.AccountRequest):
        pass

    values = {
        "duck": object(),
        "subclass": Subclass("/user/login", b"{}"),
        "path": p.AccountRequest("/user/login?request-private", b"{}"),
        "body": p.AccountRequest("/user/login", bytearray(b"{}")),
        "oversized": p.AccountRequest("/user/login", b"x" * (p.MAX_BODY_BYTES + 1)),
    }
    with pytest.raises(boundary.AccountProcessError) as error:
        client(boundary, t).send(values[kind])
    assert not calls and "private" not in repr(error.value)


@pytest.mark.parametrize(
    "options",
    [
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 61},
        {"timeout_seconds": 0},
        {"settlement_seconds": 0},
        {"settlement_seconds": 4},
        {"timeout_seconds": 0.5, "settlement_seconds": 0.5},
        {"max_body_bytes": True},
        {"max_body_bytes": 0},
    ],
)
def test_configuration_limits_fail_safely(options):
    _, t, boundary = modules()
    with pytest.raises(boundary.AccountProcessError) as error:
        client(boundary, t, **options)
    assert error.value.__context__ is None


def test_settlement_failure_quarantines_instance(monkeypatch, child_processes):
    p, t, boundary = modules()
    original = boundary._settle

    def unproven(*args, **kwargs):
        assert original(*args, **kwargs)
        return False

    monkeypatch.setattr(boundary, "_settle", unproven)
    transport = client(boundary, t, timeout_seconds=2)
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/login", b"{}"))
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/login", b"{}"))
    assert len(child_processes[0]) == 1
    assert_settled(child_processes[0])


def test_deadline_never_terminates_an_unrelated_process(monkeypatch, child_processes):
    p, t, boundary = modules()
    sentinel = subprocess.Popen(
        [boundary._worker_command()[0], "-I", "-S", "-c", "import time;time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    inject_worker(monkeypatch, boundary, "import time;time.sleep(3600)", replace=True)
    with pytest.raises(boundary.AccountProcessError):
        client(boundary, t, timeout_seconds=0.8, settlement_seconds=0.25).send(
            p.AccountRequest("/user/info/get", b"{}")
        )
    assert sentinel.poll() is None
    assert child_processes[0][1].poll() is not None


def test_result_decoding_cannot_return_success_after_total_budget(
    monkeypatch, tls_peer, child_processes
):
    p, t, boundary = modules()
    origin, certificate, _, _, _ = tls_peer
    trust_host_peer(monkeypatch, boundary, certificate)
    original = boundary._decode_reply
    real_clock = time.monotonic
    offset = [0]
    monkeypatch.setattr(
        boundary, "time", SimpleNamespace(monotonic=lambda: real_clock() + offset[0])
    )

    def delayed(*args):
        # Advance the parent clock beyond the whole 3-second budget at decode
        # entry, regardless of child startup speed. The actual child clock is
        # unchanged. This proves late-success rejection, not parser interruption.
        offset[0] = 4
        return original(*args)

    monkeypatch.setattr(boundary, "_decode_reply", delayed)
    transport = client(boundary, t, origin=origin, timeout_seconds=3)
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/info/get", b"{}"))
    assert_settled(child_processes[0])


@pytest.mark.parametrize("phase", ["decode", "settlement"])
def test_close_during_completion_rejects_collected_success_and_settles_child(
    monkeypatch, tls_peer, child_processes, phase
):
    p, t, boundary = modules()
    origin, certificate, received, _, _ = tls_peer
    trust_host_peer(monkeypatch, boundary, certificate)
    entered = threading.Event()
    release = threading.Event()
    name = "_decode_reply" if phase == "decode" else "_settle"
    original = getattr(boundary, name)

    def gated(*args):
        # Each hook is reached only after the supervisor collects the real
        # child's HTTPS reply. Keep completion active until close has returned.
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(boundary, name, gated)
    transport = client(boundary, t, origin=origin, timeout_seconds=6)
    replies, errors = [], []

    def send():
        try:
            replies.append(transport.send(p.AccountRequest("/user/info/get", b"{}")))
        except boundary.AccountProcessError as error:
            errors.append(error)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert entered.wait(4)
        assert received
        transport.close()
    finally:
        release.set()
        thread.join(6)
    assert not thread.is_alive()
    assert not replies and len(errors) == 1
    assert "cancel" in str(errors[0]).lower()
    assert errors[0].__context__ is None
    assert_settled(child_processes[0])
    with pytest.raises(boundary.AccountProcessError):
        transport.send(p.AccountRequest("/user/info/get", b"{}"))
    assert len(child_processes[0]) == 1


def test_owned_pid_is_actual_worker_interpreter_not_a_windows_venv_launcher(
    monkeypatch, child_processes
):
    p, t, boundary = modules()
    inject_worker(
        monkeypatch,
        boundary,
        "import os,json,base64\n"
        "sys.stdin.buffer.read()\n"
        "body=json.dumps({'basic':{'msgcode':200},'data':{'pid':os.getpid()}}).encode()\n"
        "sys.stdout.buffer.write(json.dumps({'status':200,'body':base64.b64encode(body).decode()}).encode())\n",
        replace=True,
    )
    response = client(boundary, t, timeout_seconds=3).send(
        p.AccountRequest("/user/info/get", b"{}")
    )
    assert (
        p.private_json(response.private_body)["data"]["pid"]
        == child_processes[0][0].pid
    )
    assert_settled(child_processes[0])
