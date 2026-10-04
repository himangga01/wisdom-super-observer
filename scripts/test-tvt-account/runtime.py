"""Explicit, private browser fixture. Never imported by production applications."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W05-account-browser-fixture-fix1-evidence"
)


def directory_enabled():
    value = os.environ.get("WSO_TEST_DIRECTORY_BROWSER")
    if value not in (None, "1"):
        raise ValueError("invalid explicit directory mode")
    return value == "1"


DIRECTORY_POLICY = {
    "region": "test",
    "brand": "SuperLivePlus",
    "profile_id": "browser-fixture",
    "consent_version": "fixture-v1",
}
DIRECTORY_SN = "synthetic:opaque:SN-7"


def directory_payload(path, *, chl_index=7):
    """Synthetic decoded upstream envelopes, never public DirectoryView objects."""
    if type(chl_index) is not int or chl_index not in (7, 42):
        raise ValueError("unrecognized synthetic channel")
    channel = {
        "sn": DIRECTORY_SN,
        "chlIndex": chl_index,
        "chlName": "Synthetic loading bay" if chl_index == 7 else None,
        "status": 1,
        "model": None,
        "password": "DIRECTORY-SENSITIVE-MARKER",
    }
    device = {
        "sn": DIRECTORY_SN,
        "name": "Synthetic directory recorder",
        "maxShareNum": None,
        "type": 1,
        "password": "DIRECTORY-SENSITIVE-MARKER",
    }
    payloads = {
        "/resource/device/list": {"total": "1", "records": [device]},
        "/resource/channel/list": [
            {
                "sn": DIRECTORY_SN,
                "chls": [
                    {"chlIndex": 7, "chlName": "Synthetic loading bay"},
                    {"chlIndex": 42, "chlName": None},
                ],
            }
        ],
        "/resource/device/detail": {
            "devInfo": {
                "sn": DIRECTORY_SN,
                "name": device["name"],
                "model": None,
                "onlineStatus": 1,
                "userId": {"secret": "DIRECTORY-SENSITIVE-MARKER"},
            },
            "chlInfos": [channel],
        },
        "/resource/channel/detail": channel,
        "/resource/channel/share/to-other/list": {
            "total": 1,
            "records": [
                {
                    "id": "synthetic-sent",
                    "sn": DIRECTORY_SN,
                    "chlIndex": 7,
                    "recipientId": "synthetic-recipient",
                    "validData": 0,
                    "auth": ["preview"],
                    "password": "DIRECTORY-SENSITIVE-MARKER",
                }
            ],
        },
        "/resource/channel/share/from-other/list": {
            "total": 1,
            "records": [
                {
                    "id": "synthetic-received",
                    "sn": DIRECTORY_SN,
                    "chlIndex": 42,
                    "ownerId": "synthetic-owner",
                    "devRemark": None,
                    "auth": ["preview"],
                    "password": "DIRECTORY-SENSITIVE-MARKER",
                }
            ],
        },
    }
    if path not in payloads:
        raise ValueError("unrecognized readonly directory path")
    return {"basic": {"msgcode": 200}, "data": payloads[path]}


def directory_worker_environment(folder, incoming, *, enabled):
    if not enabled:
        return incoming
    path = folder / "directory-profile.json"
    write_private(path, [DIRECTORY_POLICY])
    return incoming | {
        "WSO_TEST_DIRECTORY_BROWSER": "1",
        "WSO_TVT_DIRECTORY_PROFILE_FILE": str(path),
    }


def seed_directory(database):
    from sqlalchemy import text

    engines, ids = database
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_flow_policies(region,brand,profile_id,consent_version,key_commitment,enabled) VALUES(:region,:brand,:profile_id,:consent_version,decode(:key,'hex'),true)"
            ),
            DIRECTORY_POLICY | {"key": "0" * 64},
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_user_consents(tenant_id,user_id,profile_id,version,status) VALUES(:tenant,:actor,:profile_id,:consent_version,'accepted')"
            ),
            DIRECTORY_POLICY | {"tenant": ids["tenant"], "actor": ids["staff"]},
        )
        db.execute(
            text("UPDATE public.tenants SET name=:name WHERE id=:id"),
            {"name": "Synthetic Directory Demo", "id": ids["tenant"]},
        )
        db.execute(
            text("UPDATE public.tenants SET name=:name WHERE id=:id"),
            {"name": "Synthetic Other Tenant", "id": ids["other_tenant"]},
        )


def publish_directory_identity(database, key_path, issuer):
    from sqlalchemy.orm import sessionmaker
    from wso_api.tvt.identity_service import IdentityService
    from wso_contracts.tvt.account import AccountSelection
    from wso_core.db import tenant_session
    from wso_core.secrets import FileKeyProvider
    from wso_core.tenancy import identity_session
    from wso_core.tvt.token_vault import TokenVault

    engines, ids = database
    # The fixed actor's provisioned issuer has changed to the signed local issuer.
    # Commit its actual protected ticket before using the unchanged worker vault.
    with identity_session(
        issuer,
        str(ids["staff"]),
        session_factory=sessionmaker(engines["IDENTITY"]),
    ) as lookup:
        choice = lookup.authorize_tenant(ids["tenant"])
    with tenant_session(
        ids["tenant"],
        authorization=choice,
        session_factory=sessionmaker(engines["APP"]),
    ) as db:
        ticket = IdentityService(db).issue(
            "login", AccountSelection(region="test", brand="SuperLivePlus")
        )
    vault = TokenVault(
        engines["WORKER"].url.render_as_string(hide_password=False),
        FileKeyProvider(key_path),
    )
    try:
        lease = vault.redeem(ticket, "login")
        return vault.publish(lease, "synthetic-user-token", "synthetic-p2p-token")
    finally:
        vault.close()


def bind_directory_login(issuer, database, key_path, gate, path, state):
    _, ids = database
    if (
        issuer.state.subject != str(ids["staff"])
        or state["userId"] != str(ids["staff"])
        or state["tenantId"] != str(ids["tenant"])
        or issuer.state.origin != issuer.origin
    ):
        raise ValueError("fixed directory login scope required")

    def publish():
        # This issuer request is the sole counted API entry. Fence any concurrent
        # API/worker entry; retain the existing admission and settlement contract.
        with gate.frozen() as (api, worker):
            if api != 1 or worker:
                raise ValueError("directory publication requires settled calls")
            identity = publish_directory_identity(database, key_path, issuer.origin)
            ids["identity"] = identity
            state["identityId"] = str(identity)
            write_private(path, state)

    issuer.state.on_authenticated = publish


def browser_certificates(folder, default):
    source = os.environ.get("WSO_TEST_BROWSER_TLS_DIR")
    if source is None:
        return default(folder)
    from ipaddress import ip_address

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID

    try:
        source = Path(source)
        if (
            os.environ.get("WSO_TEST_ACCOUNT_BROWSER") != "1"
            or not source.is_absolute()
            or not source.is_dir()
            or source.is_symlink()
            or source.is_junction()
            or not folder.is_dir()
            or folder.is_symlink()
            or folder.is_junction()
        ):
            raise ValueError()
        raw = {}
        for name in ("ca.pem", "server.pem", "server.key"):
            path = source / name
            if not path.is_file() or path.is_symlink() or path.is_junction():
                raise ValueError()
            with path.open("rb") as stream:
                raw[name] = stream.read(65537)
            if not 0 < len(raw[name]) <= 65536:
                raise ValueError()
        ca = x509.load_pem_x509_certificate(raw["ca.pem"])
        leaf = x509.load_pem_x509_certificate(raw["server.pem"])
        key = serialization.load_pem_private_key(raw["server.key"], password=None)
        now = datetime.now(UTC)
        for cert in (ca, leaf):
            if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
                raise ValueError()
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError()
        try:
            leaf_is_ca = leaf.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value.ca
        except x509.ExtensionNotFound:
            leaf_is_ca = False
        if leaf_is_ca:
            raise ValueError()
        ca.verify_directly_issued_by(ca)
        leaf.verify_directly_issued_by(ca)
        spki = (
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if leaf.public_key().public_bytes(*spki) != key.public_key().public_bytes(
            *spki
        ):
            raise ValueError()
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if "localhost" not in san.get_values_for_type(x509.DNSName) or not {
            ip_address("127.0.0.1"),
            ip_address("::1"),
        }.issubset(san.get_values_for_type(x509.IPAddress)):
            raise ValueError()
        if (
            ExtendedKeyUsageOID.SERVER_AUTH
            not in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        ):
            raise ValueError()
    except Exception:  # noqa: BLE001 - no certificate/key values disclosed
        raise ValueError("invalid explicit development TLS") from None
    # All input validation finishes before copying anything into owned custody.
    for name, value in raw.items():
        target = folder / name
        target.write_bytes(value)
        target.chmod(0o600)


@contextmanager
def directory_database(patch):
    from tests.support.directory_source_gate import verify_directory_source_gate

    verify_directory_source_gate()
    from tests.integration import test_tvt_directory_admission as accepted_directory
    from tests.integration.test_tvt_domain_scope import seed_foundation

    patch.setattr(accepted_directory, "EVIDENCE", EVIDENCE)
    with contextmanager(accepted_directory.directory_database.__wrapped__)() as engines:
        yield engines, seed_foundation(engines["ADMIN"])


def parse_directory_control(raw):
    if len(raw) > 256:
        raise ValueError("invalid upstream control")
    value = json.loads(raw)
    if (
        type(value) is not dict
        or set(value) != {"op", "deny"}
        or value["op"] != "upstream"
        or type(value["deny"]) is not bool
    ):
        raise ValueError("invalid upstream control")
    return value["deny"]


class OwnedHttps:
    """Loopback HTTPS source, with no request logging and joined ownership."""

    def __init__(self, folder, handler):
        from http.server import ThreadingHTTPServer

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(folder / "server.pem", folder / "server.key")

        class Server(ThreadingHTTPServer):
            daemon_threads = False

            def get_request(self):
                connection, address = super().get_request()
                wrapped = None
                try:
                    connection.settimeout(5)
                    wrapped = context.wrap_socket(
                        connection, server_side=True, do_handshake_on_connect=False
                    )
                    wrapped.do_handshake()
                    return wrapped, address
                except BaseException:
                    (wrapped or connection).close()
                    raise

        self.server = Server(("127.0.0.1", 0), handler)
        self.origin = f"https://localhost:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()


class DirectoryUpstream(OwnedHttps):
    def __init__(self, folder):
        from http.server import BaseHTTPRequestHandler

        self.paths, self.errors, self.deny = [], [], False
        self.release = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.connection.settimeout(5)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 < length <= 65536
                    value = json.loads(self.rfile.read(length))
                    basic, data = value["basic"], value["data"]
                    assert set(value) == {"basic", "data"}
                    assert set(basic) == {"ver", "id", "time", "nonce", "token"}
                    assert (
                        basic["token"] == "synthetic-user-token"
                        and basic["ver"] == "1.0"
                    )
                    assert basic["id"].isdigit() and int(basic["id"]) >= 1
                    assert 100_000_000 <= basic["nonce"] <= 999_999_999
                    assert abs(time.time() - basic["time"]) < 30
                    assert self.path.startswith("/mobile_v1.0/resource/")
                    path = self.path.removeprefix("/mobile_v1.0")
                    payload = directory_payload(path, chl_index=data.get("chlIndex", 7))
                    if path == "/resource/channel/list":
                        assert data == {"snList": [DIRECTORY_SN]}
                    elif path == "/resource/channel/detail":
                        assert data in (
                            {"sn": DIRECTORY_SN, "chlIndex": 7},
                            {"sn": DIRECTORY_SN, "chlIndex": 42},
                        )
                    elif path == "/resource/device/detail":
                        assert data in (
                            {"sn": DIRECTORY_SN, "returnChl": False},
                            {"sn": DIRECTORY_SN, "returnChl": True},
                        )
                    else:
                        assert set(data) <= {"pageNum", "pageSize", "resourceTypes"}
                        assert type(data["pageNum"]) is int and data["pageNum"] >= 0
                        assert (
                            type(data["pageSize"]) is int
                            and 0 <= data["pageSize"] <= 1000
                        )
                    outer.paths.append(path)
                    raw = json.dumps(payload).encode()
                    self.send_response(503 if outer.deny else 200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                    pass
                except Exception:  # noqa: BLE001 - never retain credentials
                    outer.errors.append("decoded directory request rejected")
                    self.send_error(400)

        super().__init__(folder, Handler)
        self.origin += "/mobile_v1.0"

    def close(self):
        super().close()
        assert not self.errors


class DirectoryIssuerState:
    """Synthetic signed issuer: one actor, one-use PKCE codes, bounded lifetime."""

    def __init__(self, origin, subject, secret):
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.origin, self.subject, self.secret = origin, subject, secret
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes, self.lock = {}, threading.Lock()
        self.on_authenticated = None

    def validate_authorization(self, query):
        import re

        expected = {
            "client_id": "fixture-web",
            "redirect_uri": "https://localhost:3543/api/auth/callback",
            "response_type": "code",
            "scope": "openid",
            "code_challenge_method": "S256",
        }
        if (
            any(query.get(k) != v for k, v in expected.items())
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", query.get("code_challenge", ""))
            or any(not 1 <= len(query.get(k, "")) <= 256 for k in ("nonce", "state"))
            or set(query)
            - (set(expected) | {"code_challenge", "nonce", "state", "profile"})
        ):
            raise ValueError("invalid issuer authorization")

    def authorize(self, query):
        self.validate_authorization(query)
        with self.lock:
            now = time.monotonic()
            self.codes = {k: v for k, v in self.codes.items() if v[0] > now}
            if len(self.codes) >= 16:
                raise ValueError("issuer capacity")
            code = secrets.token_urlsafe(32)
            self.codes[code] = (now + 60, dict(query))
            return code

    def exchange(self, body):
        import hmac

        import jwt

        with self.lock:
            entry = self.codes.pop(body.get("code", ""), None)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(body.get("code_verifier", "").encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        if (
            entry is None
            or entry[0] <= time.monotonic()
            or body.get("client_id") != "fixture-web"
            or not hmac.compare_digest(body.get("client_secret", ""), self.secret)
            or body.get("grant_type") != "authorization_code"
            or body.get("redirect_uri") != entry[1]["redirect_uri"]
            or not hmac.compare_digest(challenge, entry[1]["code_challenge"])
        ):
            raise ValueError("invalid issuer grant")
        if self.on_authenticated is not None:
            self.on_authenticated()
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": self.origin,
                "aud": "fixture-web",
                "sub": self.subject,
                "nonce": entry[1]["nonce"],
                "iat": now,
                "exp": now + 1800,
            },
            self.key,
            algorithm="RS256",
            headers={"kid": "synthetic-directory"},
        )
        return {
            "access_token": secrets.token_urlsafe(32),
            "token_type": "Bearer",
            "expires_in": 1800,
            "id_token": token,
        }


class DirectoryIssuer(OwnedHttps):
    def __init__(self, folder, subject, secret, gate):
        from html import escape
        from http.server import BaseHTTPRequestHandler
        from urllib.parse import parse_qs, urlencode, urlsplit

        import jwt

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(
                self, status, value, content_type="application/json", **headers
            ):
                raw = (
                    value.encode() if type(value) is str else json.dumps(value).encode()
                )
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                for name, header_value in headers.items():
                    self.send_header(name, header_value)
                self.end_headers()
                self.wfile.write(raw)

            def dispatch(self):
                self.connection.settimeout(5)
                url = urlsplit(self.path)
                state = outer.state
                if (
                    self.command == "GET"
                    and url.path == "/.well-known/openid-configuration"
                ):
                    return self.respond(
                        200,
                        {
                            "issuer": state.origin,
                            "authorization_endpoint": state.origin + "/authorize",
                            "token_endpoint": state.origin + "/token",
                            "jwks_uri": state.origin + "/jwks",
                            "response_types_supported": ["code"],
                            "subject_types_supported": ["public"],
                            "id_token_signing_alg_values_supported": ["RS256"],
                            "token_endpoint_auth_methods_supported": [
                                "client_secret_post"
                            ],
                            "code_challenge_methods_supported": ["S256"],
                        },
                    )
                if self.command == "GET" and url.path == "/jwks":
                    key = json.loads(
                        jwt.algorithms.RSAAlgorithm.to_jwk(state.key.public_key())
                    )
                    return self.respond(
                        200,
                        {
                            "keys": [
                                key
                                | {
                                    "kid": "synthetic-directory",
                                    "use": "sig",
                                    "alg": "RS256",
                                }
                            ]
                        },
                    )
                if self.command == "GET" and url.path == "/authorize":
                    query = self.parameters(url.query)
                    state.validate_authorization(query)
                    if query.get("profile") != "synthetic-staff":
                        inputs = "".join(
                            f'<input type="hidden" name="{escape(k, quote=True)}" value="{escape(v, quote=True)}">'
                            for k, v in query.items()
                            if k != "profile"
                        )
                        return self.respond(
                            200,
                            '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width"><title>Synthetic directory sign in</title><body><h1>Synthetic directory fixture</h1><p>Invented account and devices. No vendor connection.</p><form method="get">'
                            + inputs
                            + '<button name="profile" value="synthetic-staff">Sign in as synthetic directory staff</button></form></body></html>',
                            "text/html; charset=utf-8",
                        )
                    code = state.authorize(query)
                    return self.respond(
                        302,
                        {},
                        Location=query["redirect_uri"]
                        + "?"
                        + urlencode(
                            {"code": code, "state": query["state"], "iss": state.origin}
                        ),
                    )
                if self.command == "POST" and url.path == "/token":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError("invalid issuer request")
                    return self.respond(
                        200,
                        state.exchange(
                            self.parameters(self.rfile.read(length).decode())
                        ),
                    )
                self.respond(404, {})

            @staticmethod
            def parameters(value):
                if len(value) > 8192:
                    raise ValueError("invalid issuer request")
                pairs = parse_qs(value, strict_parsing=True)
                if any(len(v) != 1 for v in pairs.values()):
                    raise ValueError("duplicate issuer parameter")
                return {k: v[0] for k, v in pairs.items()}

            def do_GET(self):
                if not gate.enter("api"):
                    return self.respond(503, {})
                try:
                    self.dispatch()
                except Exception:  # noqa: BLE001 - signed issuer errors are private
                    self.respond(400, {"error": "invalid_request"})
                finally:
                    gate.leave("api")

            do_POST = do_GET

        # State is assigned before serving any announced URL.
        super().__init__(folder, Handler)
        self.state = DirectoryIssuerState(self.origin, subject, secret)


def canonical_digest(raw):
    canonical = raw.replace(b"\r\n", b"\n")
    if b"\r" in canonical:
        raise ValueError("unapproved source line ending")
    return hashlib.sha256(canonical).hexdigest()


def approved_migration_digest(raw):
    approved = {
        "86f154d10c7cd14ca51aae9327982c80f60945f59820ccda1769ca777f510f6d",
        "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608",
    }
    digest = hashlib.sha256(raw).hexdigest()
    if (
        digest not in approved
        or canonical_digest(raw)
        != "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608"
    ):
        raise ValueError("unapproved migration source")
    return digest


def fixture_png():
    """A valid synthetic 1234 challenge, replacing the protocol-only magic bytes."""
    import struct
    import zlib

    glyphs = [
        "010110010010111",
        "110001010100111",
        "110001010001110",
        "101101111001001",
    ]
    width, height = 100, 40
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            digit, column = divmod(x - 10, 22)
            gy = (y - 5) // 6
            gx = column // 6
            ink = (
                0 <= digit < 4
                and 0 <= gx < 3
                and 0 <= gy < 5
                and glyphs[digit][gy * 3 + gx] == "1"
            )
            row.extend((32, 32, 32) if ink else (245, 245, 245))
        rows.append(bytes(row))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def source_snapshot():
    paths = []
    for prefix in (
        "apps/web/src",
        "packages/core/src",
        "packages/contracts/src",
        "packages/contracts/generated",
        "services/api/src",
        "services/tvt-bridge/src",
        "infra/migrations",
    ):
        paths += [
            p
            for p in (ROOT / prefix).rglob("*")
            if p.suffix in {".py", ".ts", ".tsx", ".css", ".json"}
            and "__pycache__" not in p.parts
            and not p.name.startswith("0008")
        ]
    paths += [
        ROOT / p
        for p in (
            "uv.lock",
            "pnpm-lock.yaml",
            "package.json",
            "apps/web/package.json",
            "packages/core/pyproject.toml",
            "tests/contract/test_account_web_fixture.py",
            "tests/contract/test_directory_web_fixture.py",
            "docs/integrations/tvt-directory-browser-runtime.md",
            "tests/integration/test_tvt_directory_admission.py",
            "tests/integration/test_tvt_account_flow_admission.py",
            "tests/support/directory_source_gate.py",
            "tests/tvt_parity/fixtures/directory-approved-sources.json",
            "docs/integrations/tvt-account-browser-fixture.md",
            ".github/workflows/account-browser.yml",
            "scripts/dev/provision-ci-postgres.py",
            "tests/integration/test_tvt_account_rpc.py",
            "tests/integration/test_tvt_sessions.py",
            "tests/integration/test_tvt_domain_scope.py",
            "tests/support/job_handlers.py",
            "tests/tvt_parity/test_bridge_mtls.py",
            "tests/tvt_parity/e2e/login.spec.ts",
            "scripts/test-tvt-account/runtime.py",
            "scripts/test-tvt-account/server.mjs",
            "playwright.tvt-account.config.ts",
        )
    ]
    return {
        p.relative_to(ROOT).as_posix(): {
            "raw_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "canonical_lf_sha256": canonical_digest(p.read_bytes()),
        }
        for p in sorted(paths)
        if p.is_file()
    }


def private_directory(path, *, existing=False):
    if existing:
        if not path.is_dir() or path.is_symlink() or path.is_junction():
            raise ValueError("private directory ownership")
        path.chmod(0o700)
    else:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        import re

        sid = re.search(rb"S-1-[0-9-]+", result.stdout).group().decode("ascii")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
            timeout=5,
        )


def write_private(path, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    if len(raw) > 65536:
        raise ValueError("private context must be bounded")
    if (
        path.is_symlink()
        or path.is_junction()
        or path.parent.is_symlink()
        or path.parent.is_junction()
    ):
        raise ValueError("private path ownership")
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_owned(folder, owner):
    if folder.is_symlink() or json.loads((folder / "owner.json").read_text()) != {
        "owner": owner
    }:
        raise ValueError("private folder ownership mismatch")
    resolved = folder.resolve(strict=True)
    if resolved.parent != folder.parent.resolve() or resolved == ROOT:
        raise ValueError("private folder ownership mismatch")
    shutil.rmtree(resolved)


def parse_control(raw):
    if len(raw) > 256:
        raise ValueError("invalid control")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"op", "sequence"}
        or value["op"] != "session"
        or type(value["sequence"]) is not int
        or not 1 <= value["sequence"] <= 100
    ):
        raise ValueError("invalid control")
    return value["sequence"]


class AdmissionGate:
    """Private cross-process gate; transactions never span application work."""

    def __init__(self, path, *, create=False):
        self.path = path
        if create:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            with self.transaction() as db:
                db.execute(
                    "CREATE TABLE gate (closed INTEGER, api INTEGER, worker INTEGER)"
                )
                db.execute("INSERT INTO gate VALUES (0,0,0)")
        elif not path.is_file() or path.is_symlink():
            raise ValueError("private gate missing")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()

    def enter(self, kind):
        if kind not in {"api", "worker"}:
            raise ValueError("invalid admission kind")
        with self.transaction() as db:
            if db.execute("SELECT closed FROM gate").fetchone()[0]:
                return False
            db.execute(f"UPDATE gate SET {kind}={kind}+1")
            return True

    def leave(self, kind):
        if kind not in {"api", "worker"}:
            raise ValueError("invalid admission kind")
        with self.transaction() as db:
            assert db.execute(f"SELECT {kind} FROM gate").fetchone()[0] > 0
            db.execute(f"UPDATE gate SET {kind}={kind}-1")

    @contextmanager
    def frozen(self):
        with self.transaction() as db:
            closed, api, worker = db.execute("SELECT * FROM gate").fetchone()
            if closed:
                raise ValueError("admission already frozen")
            db.execute("UPDATE gate SET closed=1")
        try:
            yield api, worker
        finally:
            with self.transaction() as db:
                db.execute("UPDATE gate SET closed=0")


def rotate_when_settled(gate, authority, rotate):
    # Freeze BOTH admissions before checking any counts, keep the freeze through
    # revoke/create. Existing calls may still leave: no lock is held over work.
    with gate.frozen() as (api, worker):
        if api or worker or any(authority()):
            raise ValueError("control requires settled logged-out scenario")
        rotate()


class GuardedApplication:
    def __init__(self, app, gate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not self.gate.enter("api"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"cache-control", b"no-store")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self.gate.leave("api")


def guard_worker_execute(original, gate):
    def guarded(service, request, context, *args, **kwargs):
        if not gate.enter("worker"):
            import grpc

            return context.abort(
                grpc.StatusCode.UNAVAILABLE, "fixture admission closed"
            )
        try:
            return original(service, request, context, *args, **kwargs)
        finally:
            gate.leave("worker")

    return guarded


def worker_process(folder, gate_path):
    # Instrument admission/settlement only. Accepted serve still creates the
    # concrete server/executor/vault/client, R53 trust hook and drain receipt.
    from wso_tvt_bridge.server import _Service

    from tests.integration import test_tvt_account_rpc as accepted

    gate = AdmissionGate(gate_path)
    original = _Service._execute
    _Service._execute = guard_worker_execute(original, gate)
    try:
        accepted.serve(folder)
    finally:
        _Service._execute = original


def wait_file(path, process, deadline):
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("owned child exited before readiness")
        if path.is_file():
            return
        time.sleep(0.025)
    raise TimeoutError("owned child readiness deadline")


def child_environment():
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("WSO_", "PG", "DATABASE", "NODE_"))
        and k not in {"SSL_CERT_FILE", "SSL_CERT_DIR"}
    }


def spawn_python(arguments, environment):
    executable = sys._base_executable if os.name == "nt" else sys.executable
    import sysconfig

    site_directory = sysconfig.get_paths()["purelib"]
    launch = f"import site,runpy,sys;site.addsitedir({site_directory!r});sys.path.insert(0,{str(ROOT)!r});sys.argv={([str(Path(__file__).resolve())] + arguments)!r};runpy.run_path(sys.argv[0],run_name='__main__')"
    return subprocess.Popen(
        [executable, "-c", launch],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def stop_child(process):
    if process.poll() is None:
        try:
            process.communicate(b"close\n", timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    return process.returncode


def api_process(folder):
    import uvicorn
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from wso_api.auth import (
        AuthService,
        AuthSettings,
        OIDCVerifier,
        PostgresSessionStore,
    )
    from wso_api.main import create_app
    from wso_api.tvt.device_service import DirectoryWorkerExecutor
    from wso_api.tvt.session_service import AccountWorkerExecutor
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.directory_admission import DirectoryAdmission
    from wso_core.tvt.token_vault import TokenVault

    def forbidden(*args, **kwargs):
        raise RuntimeError("API worker capability forbidden")

    FileKeyProvider.encryption_key = forbidden
    TokenVault.__init__ = forbidden
    AccountWorkerExecutor.__init__ = forbidden
    DirectoryWorkerExecutor.__init__ = forbidden
    DirectoryAdmission.__init__ = forbidden
    assert not any(
        os.getenv(k)
        for k in (
            "WSO_WORKER_DATABASE_URL",
            "WSO_CONNECTION_KEY_FILE",
            "WSO_TVT_ACCOUNT_PROFILE_FILE",
            "WSO_TVT_DIRECTORY_PROFILE_FILE",
        )
    )
    settings = AuthSettings.from_environment()
    app = create_app()
    engines = {
        role: create_engine(
            os.environ[f"WSO_{role}_DATABASE_URL"], hide_parameters=True
        )
        for role in ("APP", "IDENTITY", "SESSION")
    }
    app.state.auth_service = AuthService(
        settings,
        OIDCVerifier(settings),
        PostgresSessionStore(
            settings.session_database_url,
            session_factory=sessionmaker(engines["SESSION"]),
        ),
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(
            GuardedApplication(app, AdmissionGate(folder / "admission.sqlite")),
            log_config=None,
            log_level="critical",
            access_log=False,
            ssl_certfile=str(folder / "api.pem"),
            ssl_keyfile=str(folder / "api.key"),
            timeout_graceful_shutdown=5,
        )
    )

    def shutdown():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=shutdown, daemon=True).start()
    write_private(
        folder / "api-port.json",
        {"port": listener.getsockname()[1], "pid": os.getpid()},
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        for engine in engines.values():
            engine.dispose()


def profile(origin, *, directory=False):
    from wso_core.tvt.startup import APK_SHA256, StartupProfile

    return StartupProfile.model_validate(
        {
            "profile_id": "browser-fixture",
            "source_apk_sha256": APK_SHA256,
            "brand": "SuperLivePlus",
            "region": "test",
            "consent_version": "fixture-v1",
            "default_locale": "en",
            "default_timezone": "UTC",
            "supported_locales": ["en", "zh"],
            "terms": {
                "source_reference": "agreement/ServiceTerms_en.html",
                "url": origin + "/tvt/policies/en/terms",
            },
            "privacy": {
                "source_reference": "agreement/PrivacyStatement_en.html",
                "url": origin + "/tvt/policies/en/privacy",
            },
            "local_routes": ["/tvt/settings", "/tvt/account"]
            + (["/tvt/devices"] if directory else []),
        }
    ).model_dump_json()


def coordinate():
    import pytest
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from wso_api.auth import PostgresSessionStore, WebSession, token_digest

    from tests.integration import test_tvt_account_rpc as accepted
    from tests.tvt_parity.test_bridge_mtls import certs

    directory = directory_enabled()
    if directory:
        # Keep the original W05 historical packet untouched by this mode.
        global EVIDENCE
        EVIDENCE = (
            ROOT
            / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-browser-runtime-evidence"
        )

    path = Path(os.environ["WSO_TVT_ACCOUNT_BROWSER_STATE_FILE"])
    if (
        not path.is_absolute()
        or path.name != "context.json"
        or not path.parent.name.startswith("tvt-account-")
        or path.parent.parent.resolve() != (ROOT / "auth-state").resolve()
    ):
        raise ValueError("explicit owned private context path required")
    folder = path.parent
    owner = secrets.token_hex(16)
    output = os.environ.get("WSO_TVT_ACCOUNT_BROWSER_OUTPUT")
    if output:
        captures = Path(output)
        if (
            not captures.is_absolute()
            or captures.parent.resolve() != (ROOT / "auth-state").resolve()
            or not captures.name.startswith("tvt-account-captures-")
        ):
            raise ValueError("explicit private capture directory required")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    sources = source_snapshot()
    for source, expected in {
        "tests/integration/test_tvt_account_rpc.py": "e6acb9b4bf862b722a60ee96e1ca93cbf5e6f08e0e6e779bbeacb8acca34b0df",
        "tests/tvt_parity/test_bridge_mtls.py": "c28624e5dcbc871a0fc76126cd5bd1d9dfeb04087c9281c05fd3e95ddeb8aeb5",
        "services/api/src/wso_api/main.py": "3a4f030701e8a032718ae85b029b38bec2e4c13a805ce84d11a49ba8a10c76c3",
        "infra/migrations/versions/0007_tvt_account_sessions.py": "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608",
    }.items():
        if sources.get(source, {}).get("canonical_lf_sha256") != expected:
            raise ValueError("accepted runtime source guard mismatch")
    private_directory(folder)
    write_private(folder / "owner.json", {"owner": owner})
    gate = AdmissionGate(folder / "admission.sqlite", create=True)
    (EVIDENCE / ("browser-source-" + owner + ".json")).write_text(
        json.dumps(sources, indent=2) + "\n"
    )
    # The accepted test-only generators retain every database ownership guard.
    # Only receipt destination and mkdtemp directory privacy are adapted here.
    process = None
    result = {"context_removed": False, "api_settled": False}
    stopped = threading.Event()
    threading.Thread(
        target=lambda: (sys.stdin.readline(), stopped.set()), daemon=True
    ).start()
    try:
        if output:
            private_directory(captures)
        with ExitStack() as stack:
            patch = stack.enter_context(pytest.MonkeyPatch.context())
            patch.setattr(accepted, "EVIDENCE", EVIDENCE)
            patch.setenv("WSO_TEST_ACCOUNT_RPC_RUNTIME", "1")
            # R58: two controller-approved raw EOL representations only. The
            # accepted generator's raw-byte assertion and all DB guards remain.
            migration = ROOT / "infra/migrations/versions/0007_tvt_account_sessions.py"
            patch.setattr(
                accepted,
                "MIGRATION_SHA",
                approved_migration_digest(migration.read_bytes()),
            )
            protocol_image = b"\x89PNG\r\n\x1a\nfixtureIEND\xaeB`\x82"
            patch.setattr(
                accepted,
                "base64",
                SimpleNamespace(
                    b64encode=lambda value: base64.b64encode(
                        fixture_png() if value == protocol_image else value
                    )
                ),
            )
            original_mkdtemp = accepted.tempfile.mkdtemp

            def secured_mkdtemp(*args, **kwargs):
                created = Path(original_mkdtemp(*args, **kwargs))
                # Secure before the accepted generator writes certificates/keys.
                private_directory(created, existing=True)
                return str(created)

            patch.setattr(accepted.tempfile, "mkdtemp", secured_mkdtemp)
            database = stack.enter_context(
                directory_database(patch)
                if directory
                else contextmanager(accepted.runtime_db.__wrapped__)()
            )
            if directory:
                patch.setattr(accepted, "Upstream", DirectoryUpstream)
            directory_key_path = None

            def guarded_worker_popen(arguments, **kwargs):
                nonlocal directory_key_path
                # Narrowly adapt this reviewed helper's one owned worker launch.
                expected = "from pathlib import Path;from tests.integration.test_tvt_account_rpc import serve;import sys;serve(Path(sys.argv[1]))"
                if (
                    len(arguments) != 4
                    or arguments[1] != "-c"
                    or expected not in arguments[2]
                ):
                    raise ValueError("unexpected accepted worker launch")
                launch = arguments[2].split(expected)[0] + (
                    f"import runpy,sys;sys.path.insert(0,{str(ROOT)!r});"
                    f"sys.argv={[str(Path(__file__).resolve()), '--worker', arguments[3], str(folder / 'admission.sqlite')]!r};"
                    "runpy.run_path(sys.argv[0],run_name='__main__')"
                )
                worker_folder = Path(arguments[3])
                kwargs["env"] = directory_worker_environment(
                    worker_folder, kwargs["env"], enabled=directory
                ) | {"WSO_TEST_ACCOUNT_BROWSER": "1"}
                if directory:
                    directory_key_path = worker_folder / "vault.key"
                    seed_directory(database)
                return subprocess.Popen([arguments[0], "-c", launch], **kwargs)

            patch.setattr(
                accepted,
                "subprocess",
                SimpleNamespace(
                    Popen=guarded_worker_popen,
                    PIPE=subprocess.PIPE,
                    DEVNULL=subprocess.DEVNULL,
                    TimeoutExpired=subprocess.TimeoutExpired,
                    CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ),
            )
            upstream = stack.enter_context(
                contextmanager(accepted.runtime.__wrapped__)(
                    database, patch, SimpleNamespace(param=None)
                )
            )
            engines, ids = database
            browser_certificates(folder, certs)
            shutil.copyfile(folder / "server.pem", folder / "api.pem")
            shutil.copyfile(folder / "server.key", folder / "api.key")
            origin = os.environ.get(
                "WSO_TVT_ACCOUNT_BROWSER_ORIGIN", "https://localhost:3543"
            )
            if origin != "https://localhost:3543":
                raise ValueError("fixture origin is fixed")
            env = child_environment() | {
                "WSO_TEST_ACCOUNT_BROWSER": "1",
                "WSO_OIDC_ISSUER": "https://w02.test",
                "WSO_OIDC_CLIENT_ID": "fixture-web",
                "WSO_OIDC_JWKS_URL": "https://w02.test/keys",
                "WSO_AUTH_EXCHANGE_KEY": secrets.token_urlsafe(48),
                "WSO_PUBLIC_ORIGIN": origin,
                "WSO_TVT_STARTUP_PROFILE": profile(origin, directory=directory),
            }
            if directory:
                issuer_secret = secrets.token_urlsafe(48)
                issuer = DirectoryIssuer(folder, str(ids["staff"]), issuer_secret, gate)
                stack.callback(issuer.close)
                with engines["ADMIN"].begin() as db:
                    db.execute(
                        text(
                            "UPDATE public.users SET oidc_issuer=:issuer WHERE id=:actor"
                        ),
                        {"issuer": issuer.origin, "actor": ids["staff"]},
                    )
                env.update(
                    WSO_TEST_DIRECTORY_BROWSER="1",
                    WSO_OIDC_ISSUER=issuer.origin,
                    WSO_OIDC_JWKS_URL=issuer.origin + "/jwks",
                    SSL_CERT_FILE=str(folder / "ca.pem"),
                )
            for role in ("APP", "IDENTITY", "SESSION"):
                env[f"WSO_{role}_DATABASE_URL"] = engines[role].url.render_as_string(
                    hide_password=False
                )
            for key in ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE"):
                env["WSO_TVT_BRIDGE_" + key] = os.environ["WSO_TVT_BRIDGE_" + key]
            process = spawn_python(["--api", str(folder)], env)
            result["api_pid"] = process.pid
            wait_file(folder / "api-port.json", process, time.monotonic() + 15)
            announcement = json.loads((folder / "api-port.json").read_text())
            assert announcement["pid"] == process.pid
            api_origin = f"https://localhost:{announcement['port']}"
            tls = ssl.create_default_context(cafile=str(folder / "ca.pem"))
            end = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("owned API child exited")
                try:
                    with urlopen(
                        api_origin + "/health/live", context=tls, timeout=1
                    ) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise TimeoutError("owned API readiness deadline") from None
                    time.sleep(0.05)
            sessions = PostgresSessionStore(
                env["WSO_SESSION_DATABASE_URL"],
                session_factory=sessionmaker(engines["SESSION"]),
            )
            state = {
                "schemaVersion": 1,
                "proofKind": "actual-pg-rpc-https",
                "baseURL": origin,
                "apiOrigin": api_origin,
                "caFile": str(folder / "ca.pem"),
                "certificateFile": str(folder / "server.pem"),
                "keyFile": str(folder / "server.key"),
                "tenantId": str(ids["tenant"]),
                "otherTenantId": str(ids["other_tenant"]),
                "userId": str(ids["staff"]),
                "account": {
                    "email": "person@example.test",
                    "phone": "+12345678",
                    "password": "synthetic-password",
                    "imageCode": "1234",
                    "secondCode": "5678",
                },
                "expectedProfile": {
                    "userName": None,
                    "nickname": "Fixture",
                    "accountType": 4,
                },
                "controlFile": str(folder / "control.json"),
                "sequence": 0,
            }
            if directory:
                state.update(
                    directoryMode=True,
                    directoryControlFile=str(folder / "directory-control.json"),
                    browserEntrance=origin + "/api/auth/login",
                    nextAuth={
                        "WSO_OIDC_ISSUER": issuer.origin,
                        "WSO_OIDC_CLIENT_ID": "fixture-web",
                        "WSO_OIDC_CLIENT_SECRET": issuer_secret,
                        "WSO_AUTH_EXCHANGE_KEY": env["WSO_AUTH_EXCHANGE_KEY"],
                        "WSO_FLOW_ENCRYPTION_KEY": secrets.token_urlsafe(32),
                    },
                )
            current = None

            def fresh_session(sequence):
                nonlocal current
                if current:
                    assert sessions.revoke(
                        token_digest(current[0]), token_digest(current[1])
                    )
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                expires = datetime.now(UTC) + timedelta(seconds=600)
                assert sessions.create(
                    token_digest(token),
                    WebSession(
                        "https://w02.test",
                        str(ids["staff"]),
                        ids["staff"],
                        token_digest(csrf),
                        expires,
                    ),
                    token_digest(secrets.token_urlsafe(32)),
                )
                current = (token, csrf)
                state.update(
                    sequence=sequence,
                    expiresAt=expires.isoformat(),
                    csrfToken=csrf,
                    cookies=[
                        {
                            "name": "__Host-wso-session",
                            "value": token,
                            "url": origin,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "Lax",
                            "expires": expires.timestamp(),
                        },
                        {
                            "name": "__Host-wso-csrf",
                            "value": csrf,
                            "url": origin,
                            "httpOnly": False,
                            "secure": True,
                            "sameSite": "Strict",
                            "expires": expires.timestamp(),
                        },
                    ],
                )
                write_private(path, state)

            if directory:
                # The real signed callback and restricted AuthService create it.
                if directory_key_path is None:
                    raise ValueError("owned directory worker key unavailable")
                bind_directory_login(
                    issuer, database, directory_key_path, gate, path, state
                )
                write_private(path, state)
            else:
                fresh_session(0)
            try:
                while not stopped.wait(0.05):
                    if process.poll() is not None:
                        raise RuntimeError("owned API child exited")
                    directory_control = folder / "directory-control.json"
                    if directory and directory_control.exists():
                        with directory_control.open("rb") as stream:
                            deny = parse_directory_control(stream.read(257))
                        directory_control.unlink()
                        with gate.frozen() as (active_api, active_worker):
                            if active_api or active_worker:
                                raise ValueError(
                                    "upstream control requires settled calls"
                                )
                            upstream.deny = deny
                        write_private(
                            folder / "directory-control-applied.json", {"deny": deny}
                        )
                    control = folder / "control.json"
                    if control.exists():
                        if directory:
                            raise ValueError(
                                "directory sessions require normal signed login"
                            )
                        with control.open("rb") as stream:
                            sequence = parse_control(stream.read(257))
                        control.unlink()
                        if sequence != state["sequence"] + 1:
                            raise ValueError("control sequence mismatch")

                        def authority():
                            with engines["ADMIN"].connect() as db:
                                return db.execute(
                                    text(
                                        "SELECT (SELECT count(*) FROM wso_private.tvt_account_sessions WHERE state NOT IN ('CLOSED','FAILED')), "
                                        "(SELECT count(*) FROM wso_private.tvt_account_tickets WHERE expires_at>clock_timestamp())"
                                    )
                                ).one()

                        rotate_when_settled(
                            gate,
                            authority,
                            lambda sequence=sequence: fresh_session(sequence),
                        )
            finally:
                if current:
                    sessions.revoke(token_digest(current[0]), token_digest(current[1]))
                result["api_exit_code"] = stop_child(process)
                result["api_settled"] = process.poll() is not None
                result["decoded_paths"] = sorted(set(upstream.paths))
                result["decoded_requests"] = len(upstream.paths)
                result["upstream_errors"] = len(upstream.errors)
                with engines["ADMIN"].connect() as db:
                    result["account_session_states"] = dict(
                        db.execute(
                            text(
                                "SELECT state,count(*) FROM wso_private.tvt_account_sessions GROUP BY state"
                            )
                        ).all()
                    )
                    result["encrypted_account_secret_rows"] = db.execute(
                        text(
                            "SELECT count(*) FROM wso_private.connection_secrets s JOIN wso_private.tvt_account_tokens t USING(connection_id)"
                        )
                    ).scalar_one()
                    result["token_generations"] = list(
                        db.execute(
                            text(
                                "SELECT DISTINCT generation FROM wso_private.tvt_account_tokens ORDER BY generation"
                            )
                        ).scalars()
                    )
                    result["target_revision"] = db.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
    finally:
        if process is not None and process.poll() is None:
            stop_child(process)
        remove_owned(folder, owner)
        result["context_removed"] = not folder.exists()
        final_sources = source_snapshot()
        dependency_paths = {"uv.lock", "packages/core/pyproject.toml"}
        result["dependency_changes"] = sorted(
            p for p in dependency_paths if sources.get(p) != final_sources.get(p)
        )
        result["source_unchanged"] = final_sources == sources
        result["implementation_unchanged"] = {
            p: v for p, v in final_sources.items() if p not in dependency_paths
        } == {p: v for p, v in sources.items() if p not in dependency_paths}
        (EVIDENCE / ("browser-source-final-" + owner + ".json")).write_text(
            json.dumps(final_sources, indent=2) + "\n"
        )
        (EVIDENCE / ("browser-resources-" + owner + ".json")).write_text(
            json.dumps(result, indent=2) + "\n"
        )
        if not result["implementation_unchanged"]:
            raise RuntimeError("browser source changed during proof")


def main():
    if os.environ.get("WSO_TEST_ACCOUNT_BROWSER") != "1":
        print("Account browser fixture requires explicit activation.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        worker_process(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--api":
        api_process(Path(sys.argv[2]))
    else:
        coordinate()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never disclose private failure values
        # Never emit exception values, connection strings, payloads or tracebacks.
        import traceback

        frames = traceback.extract_tb(error.__traceback__)
        print(
            "Account browser fixture failed ("
            + type(error).__name__
            + "; "
            + ",".join(
                Path(frame.filename).name + ":" + str(frame.lineno) for frame in frames
            )
            + ").",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
