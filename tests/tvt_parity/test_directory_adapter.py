"""Source contracts and synthetic host TLS only; no vendor runtime equivalence."""

import importlib
import json
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef
from wso_core.tvt.account_protocol import (
    AccountProtocol,
    SessionTaskIds,
    parse_response,
)
from wso_core.tvt.account_transport import OriginPolicy
from wso_core.tvt.ports import AccountClientError, PrivateToken


def subject(name):
    module = f"wso_core.tvt.directory_{name}"
    assert importlib.util.find_spec(module) is not None, (
        "The six source-approved directory operations need their private adapter"
    )
    return importlib.import_module(module)


def protocol(**bounds):
    p = subject("protocol")
    return p.DirectoryProtocol(
        AccountProtocol(
            task_ids=SessionTaskIds(),
            clock=lambda: 1700000000,
            nonce=lambda: 123456789,
        ),
        bounds=p.DirectoryBounds(**bounds),
    )


CASES = [
    (
        "device_list",
        (0, 1000),
        "/resource/device/list",
        {"pageNum": 0, "pageSize": 1000},
    ),
    (
        "channel_list",
        (["opaque:SN-A", "SN-B"],),
        "/resource/channel/list",
        {"snList": ["opaque:SN-A", "SN-B"]},
    ),
    (
        "device_detail",
        ("opaque:SN-A", True),
        "/resource/device/detail",
        {"sn": "opaque:SN-A", "returnChl": True},
    ),
    (
        "channel_detail",
        ("SN-A", 7),
        "/resource/channel/detail",
        {"sn": "SN-A", "chlIndex": 7},
    ),
    (
        "sent_shares",
        (0, 0, []),
        "/resource/channel/share/to-other/list",
        {"pageNum": 0, "pageSize": 0},
    ),
    (
        "received_shares",
        (0, 5, [1, 99]),
        "/resource/channel/share/from-other/list",
        {"pageNum": 0, "pageSize": 5, "resourceTypes": [1, 99]},
    ),
]


@pytest.mark.parametrize("name,args,path,data", CASES)
def test_six_serializers_emit_source_paths_numbers_and_ordinary_user_basic(
    name,
    args,
    path,
    data,
):
    request = getattr(protocol(), name)("synthetic-user", *args)
    assert request.path == path
    assert json.loads(request.body) == {
        "basic": {
            "ver": "1.0",
            "id": "1",
            "time": 1700000000,
            "nonce": 123456789,
            "token": "synthetic-user",
        },
        "data": data,
    }


@pytest.mark.parametrize(
    "name,args",
    [
        ("device_list", (True, 1)),
        ("device_list", (-1, 1)),
        ("device_list", (0, 1001)),
        ("device_list", (2**31, 1)),
        ("channel_list", ([],)),
        ("channel_list", (["A", "A"],)),
        ("channel_list", ([""],)),
        ("channel_list", ([True],)),
        ("channel_list", (["A"] * 101,)),
        ("channel_list", ("A",)),
        ("device_detail", ("", True)),
        ("device_detail", ("A", 1)),
        ("device_detail", ("\x00", False)),
        ("device_detail", ("\U0001f600", False)),
        ("device_detail", ("a" * 4097, False)),
        ("channel_detail", ("A", True)),
        ("channel_detail", ("A", -1)),
        ("received_shares", (0, 1, [True])),
        ("received_shares", (0, 1, [1, 1])),
        ("sent_shares", (0, 1, list(range(17)))),
    ],
)
def test_input_guards_reject_ambiguous_or_overbound_selectors(name, args):
    from wso_core.tvt.account_protocol import AccountProtocolError

    with pytest.raises(AccountProtocolError):
        getattr(protocol(), name)("synthetic-user", *args)


def response(data, *, key="data", status=200, code=200):
    return parse_response(
        status, json.dumps({"basic": {"msgcode": code}, key: data}).encode()
    )


SHAPES = [
    ("device_list", {"total": "1001", "records": [{"sn": "A", "type": None}]}),
    ("channel_list", [{"sn": "A", "chls": [{"chlIndex": 7, "chlName": "Rear"}]}]),
    (
        "device_detail",
        {
            "devInfo": {
                "sn": "A",
                "model": "reported-model",
                "version": "v",
                "onlineStatus": 987,
                "capability": {"talk": True, "chlNum": 2},
            },
            "chlInfos": [{"sn": "A", "chlIndex": 7}],
        },
    ),
    (
        "channel_detail",
        {
            "sn": "A",
            "chlIndex": 7,
            "status": 987,
            "capability": {
                "stream": [
                    {
                        "name": "main",
                        "res": [{"fps": 25, "value": "1920x1080"}],
                        "supEnct": ["H264"],
                    }
                ]
            },
        },
    ),
    (
        "sent_shares",
        {
            "total": 1,
            "records": [
                {
                    "id": "share:A",
                    "sn": "A",
                    "recipientId": "recipient-A",
                    "chlIndex": 7,
                    "auth": ["live.video"],
                    "validData": 3,
                    "shardIds": ["opaque:A"],
                }
            ],
        },
    ),
    (
        "received_shares",
        {
            "total": 2,
            "records": [
                {
                    "id": "share:A",
                    "sn": "A",
                    "ownerId": "owner-A",
                    "devRemark": "device",
                    "ownerRemark": "owner",
                    "devType": 13,
                    "chlIndex": 7,
                    "auth": ["live.video"],
                },
                {"id": "share:B", "sn": "A", "chlIndex": 8, "auth": ["unknown"]},
            ],
        },
    ),
]


@pytest.mark.parametrize("name,data", SHAPES)
def test_six_response_shapes_preserve_only_observed_source_fields(name, data):
    value = getattr(subject("projection"), f"parse_{name}")(response(data))
    assert value.project() == data
    assert value.complete is None


def test_source_presence_and_initializer_do_not_manufacture_share_authority():
    p = subject("projection")
    page = p.parse_device_list(
        response(
            {
                "total": "3",
                "records": [
                    {"sn": "A"},
                    {"sn": "B", "maxShareNum": None},
                    {"sn": "C", "maxShareNum": ""},
                ],
            }
        )
    )
    missing, null, empty = [record.field("maxShareNum") for record in page.records]
    assert missing.state == "missing" and missing.source_default == "0"
    assert null.state == "null" and null.value is None
    assert empty.state == "value" and empty.value == ""
    assert page.records[0].field("type").state == "missing"
    assert page.project()["records"] == [
        {"sn": "A"},
        {"sn": "B", "maxShareNum": None},
        {"sn": "C", "maxShareNum": ""},
    ]


def test_received_fields_are_independent_and_auth_never_unions_siblings():
    data = {
        "total": 2,
        "records": [
            {
                "id": "S1",
                "sn": "A",
                "chlIndex": 7,
                "ownerId": "O",
                "devRemark": "D",
                "ownerRemark": "R",
                "devType": 13,
                "auth": ["ptz"],
                "recipientId": "sent-only",
                "validData": 5,
                "shardIds": ["sent-only"],
                "childList": [{"auth": ["talk"]}],
                "selectState": True,
                "supportPtzList": [7],
                "token": "synthetic-secret",
            },
            {"id": "S2", "sn": "A", "chlIndex": 8, "auth": None},
        ],
    }
    page = subject("projection").parse_received_shares(response(data))
    projected = page.project()
    assert projected == {
        "total": 2,
        "records": [
            {
                "id": "S1",
                "sn": "A",
                "chlIndex": 7,
                "ownerId": "O",
                "devRemark": "D",
                "ownerRemark": "R",
                "devType": 13,
                "auth": ["ptz"],
            },
            {"id": "S2", "sn": "A", "chlIndex": 8, "auth": None},
        ],
    }
    assert "synthetic-secret" not in repr(page) + repr(projected)
    assert page.records[0].unknown_members == 7


@pytest.mark.parametrize("name,data", SHAPES)
def test_only_object_consumers_allow_array_fallback(name, data):
    from wso_core.tvt.account_protocol import AccountProtocolError

    parse = getattr(subject("projection"), f"parse_{name}")
    if name == "channel_list":
        with pytest.raises(AccountProtocolError):
            parse(response(data, key="array"))
    else:
        assert parse(response(data, key="array")).project() == data


@pytest.mark.parametrize(
    "name,data",
    [
        ("device_list", None),
        ("device_list", {"total": 0, "records": []}),
        ("device_list", {"total": "0", "records": None}),
        ("device_list", {"total": "0"}),
        ("device_list", {"total": "0", "records": [False]}),
        ("device_list", {"total": "1", "records": [{"type": False}]}),
        ("channel_list", {}),
        ("channel_list", [False]),
        ("channel_list", [{"sn": "A", "chls": [False]}]),
        ("channel_list", [{"sn": "A", "chls": [{"chlIndex": True}]}]),
        ("device_detail", False),
        ("device_detail", {"devInfo": []}),
        ("device_detail", {"devInfo": {"capability": {"talk": 1}}}),
        ("channel_detail", []),
        ("channel_detail", {"capability": {"stream": [False]}}),
        ("sent_shares", {"total": "0", "records": []}),
        ("received_shares", {"total": False, "records": []}),
        ("received_shares", {"total": 1, "records": [{"auth": [True]}]}),
    ],
)
def test_malformed_null_and_false_primitives_never_become_empty_success(name, data):
    from wso_core.tvt.account_protocol import AccountProtocolError

    with pytest.raises(AccountProtocolError):
        getattr(subject("projection"), f"parse_{name}")(response(data))


@pytest.mark.parametrize(
    "name,data",
    [
        ("device_list", {"total": "0", "records": []}),
        ("channel_list", []),
        ("sent_shares", {"total": 0, "records": []}),
        ("received_shares", {"total": 0, "records": []}),
    ],
)
def test_valid_empty_records_are_readonly_observations(name, data):
    assert (
        getattr(subject("projection"), f"parse_{name}")(response(data)).project()
        == data
    )


def identity(**changes):
    return TvtIdentityRef(
        tenant_id=UUID(int=1), actor_user_id=UUID(int=2), identity_id=UUID(int=3)
    ).model_copy(update=changes)


def build(monkeypatch, reply, *, protocol_value=None):
    account = importlib.import_module("wso_core.tvt.account_client")
    requests = []
    launches = []

    class Boundary:
        def send(self, request):
            requests.append(request)
            return reply() if callable(reply) else reply

        def close(self):
            pass

    def launch(*args, **kwargs):
        launches.append(kwargs)
        return Boundary()

    monkeypatch.setattr(account, "ProcessAccountTransport", launch)
    client = subject("client").DirectoryClient(
        AccountScope(
            tenant_id=UUID(int=1),
            actor_user_id=UUID(int=2),
            identity_id=UUID(int=3),
            region="host-test",
            brand="demo",
        ),
        OriginPolicy(
            {
                "host-test": frozenset(
                    {"https://localhost:1", "https://localhost:1/mobile_v1.0"}
                )
            }
        ),
        origin="https://localhost:1",
        identity=identity(),
        protocol=protocol_value,
    )
    return client, requests, launches


def call(client, **changes):
    kwargs = {
        "scope": identity(),
        "token": PrivateToken(identity(), TokenKind.USER, "synthetic-user"),
        "page_num": 0,
        "page_size": 1,
        "deadline_ms": 3000,
        "correlation_id": "directory-test",
    }
    kwargs.update(changes)
    return client.device_list(**kwargs)


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": identity(identity_id=UUID(int=4))},
        {"scope": identity(tenant_id=UUID(int=4))},
        {"scope": identity(actor_user_id=UUID(int=4))},
        {"token": PrivateToken(identity(), TokenKind.P2P, "synthetic-user")},
        {"token": PrivateToken(identity(), TokenKind.DEVICE, "synthetic-user")},
        {
            "token": PrivateToken(
                identity(identity_id=UUID(int=4)), TokenKind.USER, "synthetic-user"
            )
        },
        {"token": PrivateToken(identity(), TokenKind.USER, "")},
        {"page_num": True},
        {"page_size": 1001},
    ],
)
def test_scope_token_and_input_guards_fail_before_process_io(monkeypatch, changes):
    client, requests, launches = build(
        monkeypatch, response({"total": "0", "records": []})
    )
    with pytest.raises(AccountClientError) as error:
        call(client, **changes)
    assert error.value.code in {"ACCOUNT_SCOPE_INVALID", "ACCOUNT_PROTOCOL_INVALID"}
    assert error.value.__context__ is None
    assert requests == [] and launches == []


@pytest.mark.parametrize(
    "status,code",
    [
        (500, 200),
        (200, 7000),
        (200, 7003),
        (200, 10002),
        (200, 11101),
        (200, 7004),
        (200, 7009),
        (200, 7088),
        (200, 7089),
        (200, 7090),
    ],
)
def test_http_business_and_invalid_token_codes_are_failures_without_retry(
    monkeypatch, status, code
):
    client, requests, launches = build(
        monkeypatch, response(None, status=status, code=code)
    )
    result = call(client)
    assert not result.ok and result.value is None
    assert result.error_code == "ACCOUNT_UPSTREAM_REJECTED"
    assert (result.http_status, result.native_msgcode) == (status, code)
    assert len(requests) == len(launches) == 1


def test_directory_reuses_inflight_and_close_discard_of_late_results(monkeypatch):
    reached, release = threading.Event(), threading.Event()

    def delayed():
        reached.set()
        assert release.wait(2)
        return response({"total": "0", "records": []})

    client, requests, launches = build(monkeypatch, delayed)
    outcomes = []

    def run():
        try:
            call(client)
        except AccountClientError as error:
            outcomes.append(error.code)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert reached.wait(1)
        with pytest.raises(AccountClientError) as busy:
            call(client)
        assert busy.value.code == "ACCOUNT_UNAVAILABLE"
        client.close()
    finally:
        release.set()
        thread.join(2)
    assert outcomes == ["ACCOUNT_CANCELLED"]
    assert len(requests) == len(launches) == 1
    with pytest.raises(AccountClientError) as closed:
        call(client)
    assert closed.value.code == "ACCOUNT_UNAVAILABLE"


def test_parse_bounds_cover_unknown_members_and_nested_reported_support():
    from wso_core.tvt.account_protocol import AccountProtocolError

    p, b = subject("projection"), subject("protocol")
    for data, bounds in [
        (
            {"total": "2", "records": [{"sn": "A"}, {"sn": "B"}]},
            b.DirectoryBounds(max_records=1),
        ),
        (
            {"total": "0", "records": [], "extra": "x" * 9},
            b.DirectoryBounds(max_string_bytes=8),
        ),
        (
            {"total": "0", "records": [], "extra": [[[[1]]]]},
            b.DirectoryBounds(max_depth=3),
        ),
        (
            {"total": "0", "records": [], "extra": [1, 2, 3]},
            b.DirectoryBounds(max_list_items=2),
        ),
    ]:
        with pytest.raises(AccountProtocolError):
            p.parse_device_list(response(data), bounds=bounds)


@pytest.mark.parametrize(
    "name,data",
    [
        ("channel_list", [{"sn": "A", "chls": [None]}]),
        ("sent_shares", {"total": 1, "records": [{"auth": [None]}]}),
        ("channel_detail", {"capability": {"stream": [None]}}),
    ],
)
def test_null_list_elements_are_invalid_shapes(name, data):
    from wso_core.tvt.account_protocol import AccountProtocolError

    with pytest.raises(AccountProtocolError):
        getattr(subject("projection"), f"parse_{name}")(response(data))


def test_java_object_metadata_retains_presence_without_credential_passthrough():
    detail = subject("projection").parse_device_detail(
        response(
            {
                "devInfo": {
                    "userId": {"token": "synthetic-secret"},
                    "checkTime": [1, 2],
                }
            }
        )
    )
    info = detail.field("devInfo").value
    assert info.field("userId").state == "value"
    assert info.field("userId").value.kind == "object"
    assert info.field("checkTime").value.kind == "array"
    assert detail.project() == {"devInfo": {}}
    assert "synthetic-secret" not in repr(detail) + repr(info)


@pytest.mark.parametrize(
    "operation,args,data",
    [
        ("channel_list", (["A"],), [{"sn": "B", "chls": []}]),
        ("channel_list", (["A"],), [{"sn": "A", "chls": []}, {"sn": "A", "chls": []}]),
        (
            "channel_list",
            (["A"],),
            [{"sn": "A", "chls": [{"chlIndex": 7}, {"chlIndex": 7}]}],
        ),
        ("device_detail", ("A", True), {"devInfo": {"sn": "B"}}),
        ("channel_detail", ("A", 7), {"sn": "A", "chlIndex": 8}),
        ("channel_detail", ("A", 7), {"sn": "B", "chlIndex": 7}),
    ],
)
def test_returned_selectors_do_not_escape_or_ambiguously_replace_requested_scope(
    monkeypatch,
    operation,
    args,
    data,
):
    client, requests, _ = build(monkeypatch, response(data))
    with pytest.raises(AccountClientError) as error:
        getattr(client, operation)(
            identity(),
            PrivateToken(identity(), TokenKind.USER, "synthetic-user"),
            *args,
            deadline_ms=3000,
            correlation_id="directory-test",
        )
    assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert len(requests) == 1


def test_dc_hint_is_pending_once_and_cannot_retry_or_move_origin(monkeypatch):
    client, requests, launches = build(
        monkeypatch,
        response(
            {
                "domain": "localhost",
                "dcPort": 1,
                "httpPrefix": "https://",
            },
            code=404,
        ),
    )
    first = call(client)
    second = call(client)
    assert first.error_code == "ACCOUNT_DC_PENDING" and not first.ok
    assert second.error_code == "ACCOUNT_UPSTREAM_REJECTED" and not second.ok
    assert first.dc.origin == "https://localhost:1/mobile_v1.0"
    assert len(requests) == len(launches) == 2
    assert all(launch["origin"] == "https://localhost:1" for launch in launches)


@pytest.mark.parametrize(
    "message,code",
    [
        ("Account process deadline exceeded.", "ACCOUNT_DEADLINE_EXCEEDED"),
        ("Account process settlement could not be proved.", "ACCOUNT_QUARANTINED"),
        ("Account process request cancelled.", "ACCOUNT_CANCELLED"),
    ],
)
def test_contained_process_failures_stay_safe_and_unproved_settlement_is_quarantined(
    monkeypatch,
    message,
    code,
):
    from wso_core.tvt.account_process import AccountProcessError

    def fail():
        raise AccountProcessError(message)

    client, requests, launches = build(monkeypatch, fail)
    with pytest.raises(AccountClientError) as error:
        call(client)
    assert error.value.code == code and error.value.__context__ is None
    if code == "ACCOUNT_QUARANTINED":
        with pytest.raises(AccountClientError) as next_error:
            call(client)
        assert next_error.value.code == "ACCOUNT_QUARANTINED"
    assert len(requests) == len(launches) == 1


def test_success_status_with_malformed_payload_stays_protocol_failure(monkeypatch):
    client, requests, _ = build(monkeypatch, response(None))
    with pytest.raises(AccountClientError) as error:
        call(client)
    assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert (error.value.http_status, error.value.native_msgcode) == (200, 200)
    assert len(requests) == 1


@pytest.fixture
def directory_peer(tmp_path):
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
    certificate, key_path = tmp_path / "peer.pem", tmp_path / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    received = []
    replies = {case[2]: shape[1] for case, shape in zip(CASES, SHAPES, strict=True)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(
                (
                    self.path,
                    dict(self.headers),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            body = json.dumps(
                {"basic": {"msgcode": 200}, "data": replies[self.path]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://localhost:{server.server_port}", certificate, received
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_actual_process_verified_loopback_https_runs_six_readonly_source_requests(
    monkeypatch,
    directory_peer,
):
    import subprocess

    from test_account_process import assert_settled, trust_host_peer
    from wso_core.tvt import account_process

    origin, certificate, received = directory_peer
    trust_host_peer(monkeypatch, account_process, certificate)
    children = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(account_process.subprocess, "Popen", launch)
    client = subject("client").DirectoryClient(
        AccountScope(
            tenant_id=UUID(int=1),
            actor_user_id=UUID(int=2),
            identity_id=UUID(int=3),
            region="host-test",
            brand="demo",
        ),
        OriginPolicy({"host-test": frozenset({origin})}),
        origin=origin,
        identity=identity(),
        protocol=protocol(),
    )
    token = PrivateToken(identity(), TokenKind.USER, "synthetic-user")
    # The detail SN matches the source response; list tests above cover opaque selectors.
    calls = [
        ("device_list", (0, 1000)),
        ("channel_list", (["A"],)),
        ("device_detail", ("A", True)),
        ("channel_detail", ("A", 7)),
        ("sent_shares", (0, 0, [])),
        ("received_shares", (0, 5, [1, 99])),
    ]
    try:
        for (operation, args), (_, data) in zip(calls, SHAPES, strict=True):
            result = getattr(client, operation)(
                identity(),
                token,
                *args,
                deadline_ms=4000,
                correlation_id=f"directory-{operation}",
            )
            assert result.ok and result.value.project() == data
            assert result.http_status == result.native_msgcode == 200
        assert [request[0] for request in received] == [case[2] for case in CASES]
        assert len(children) == 6
        for index, (_, headers, body) in enumerate(received, start=1):
            assert headers["Content-Type"] == "application/json;charset=UTF-8"
            assert "Authorization" not in headers
            assert body["basic"] == {
                "ver": "1.0",
                "id": str(index),
                "time": 1700000000,
                "nonce": 123456789,
                "token": "synthetic-user",
            }
        assert [item[2]["data"] for item in received] == [
            {"pageNum": 0, "pageSize": 1000},
            {"snList": ["A"]},
            {"sn": "A", "returnChl": True},
            {"sn": "A", "chlIndex": 7},
            {"pageNum": 0, "pageSize": 0},
            {"pageNum": 0, "pageSize": 5, "resourceTypes": [1, 99]},
        ]
        assert_settled(children)
    finally:
        client.close()
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)


@pytest.mark.parametrize("sn", [" ", " A", "A\n", "A\tB", "A\x7fB"])
def test_web_selector_policy_rejects_blank_whitespace_and_control_characters(sn):
    from wso_core.tvt.account_protocol import AccountProtocolError

    with pytest.raises(AccountProtocolError):
        protocol().device_detail("synthetic-user", sn, False)


def test_object_consumer_fallback_accepts_empty_native_data_with_valid_array():
    value = parse_response(
        200, b'{"basic":{"msgcode":200},"data":"","array":{"total":"0","records":[]}}'
    )
    assert subject("projection").parse_device_list(value).project() == {
        "total": "0",
        "records": [],
    }
