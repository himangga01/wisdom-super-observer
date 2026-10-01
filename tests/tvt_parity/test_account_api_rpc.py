"""API lifespan and trusted profile writer tests; no real upstream acceptance."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wso_api import main
from wso_core.tvt.account_projection import AccountFailure
from wso_tvt_bridge import client as bridge

ROOT = Path(__file__).resolve().parents[2]


class Client:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_lifespan_creates_injects_and_closes_one_client(monkeypatch):
    owned = Client()
    calls = []
    monkeypatch.setattr(
        bridge,
        "create_account_worker_client",
        lambda env=None: calls.append(env) or owned,
    )
    app = main.create_app()
    assert calls == []
    with TestClient(app) as http:
        assert app.state.tvt_account_worker is owned
        assert len(calls) == 1
        assert http.get("/health/live").status_code == 200
        assert owned.closed == 0
    assert owned.closed == 1
    assert app.state.tvt_account_worker is None


def test_startup_failure_closes_client_and_asset_resources(monkeypatch):
    owned = Client()
    monkeypatch.setattr(bridge, "create_account_worker_client", lambda env=None: owned)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic startup failure")

    from types import SimpleNamespace

    asset_closed = []
    asset = SimpleNamespace(
        admission=SimpleNamespace(close_admission=lambda: asset_closed.append(True)),
        authorization=SimpleNamespace(
            web_session=None, identity=None, tenant=None, redemption=None
        ),
    )
    monkeypatch.setattr(main, "load_asset_settings", lambda env: None)
    monkeypatch.setattr(main, "start_asset_runtime", lambda **kwargs: asset)
    app = main.create_app()
    monkeypatch.setattr(main, "configure_assets", fail)
    with (
        pytest.raises(RuntimeError, match="synthetic startup failure"),
        TestClient(app),
    ):
        pass
    assert owned.closed == 1
    assert asset_closed == [True]


def test_failed_close_does_not_mask_lifespan(monkeypatch):
    owned = Client()

    def fail():
        owned.closed += 1
        raise RuntimeError("private close error")

    owned.close = fail
    monkeypatch.setattr(bridge, "create_account_worker_client", lambda env=None: owned)
    with TestClient(main.create_app()) as http:
        assert http.app.state.tvt_account_worker is owned
    assert owned.closed == 1


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"WSO_TVT_BRIDGE_ENDPOINT": "localhost:9443"},
        {"WSO_TVT_BRIDGE_ENDPOINT": "http://invalid"},
    ],
)
def test_missing_partial_bad_config_fail_closed_and_auth_precedes_parse(
    monkeypatch, settings
):
    for name in tuple(os.environ):
        if name.startswith("WSO_TVT_BRIDGE_"):
            monkeypatch.delenv(name)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    from wso_api.tvt import account

    with TestClient(main.create_app()) as http:
        assert http.app.state.tvt_account_worker is None
        response = http.post("/api/v1/tvt/identities/login", content="{bad")
        assert response.status_code == 401
        # Route authentication remains the first operation. This seam lets the
        # missing-worker response be tested without inventing SQL authorization.
        monkeypatch.setattr(account, "_authenticate", lambda request: (None, None))
        response = http.post(
            "/api/v1/tvt/identities/login",
            params={"tenant_id": str(uuid4())},
            json={
                "region": "test",
                "brand": "SuperLivePlus",
                "mode": "email",
                "account": "person@example.test",
                "secret": "synthetic-password",
            },
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"


def test_client_import_has_no_worker_capabilities_and_app_creation_loads_no_key():
    code = """
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname in ('wso_tvt_bridge.server', 'wso_core.tvt.token_vault', 'wso_api.tvt.session_service'):
   raise AssertionError('worker import')
sys.meta_path.insert(0, Guard())
import wso_tvt_bridge.client
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, check=False
    )
    assert result.returncode == 0
    code = """
import grpc
from wso_core.secrets import FileKeyProvider
from wso_core.tvt.token_vault import TokenVault
def fail(*args, **kwargs): raise AssertionError('worker capability or import connection')
FileKeyProvider.encryption_key = fail
TokenVault.__init__ = fail
grpc.secure_channel = fail
from wso_api.main import create_app
create_app()
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, check=False
    )
    assert result.returncode == 0


def writer():
    path = ROOT / "scripts/dev/write_tvt_account_profile.py"
    assert path.is_file(), "trusted worker profile writer must exist"
    spec = importlib.util.spec_from_file_location("profile_writer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry(**patch):
    return dict(
        region="test",
        brand="SuperLivePlus",
        origin="https://example.test/mobile_v1.0",
        language="en",
        country="US",
        app_version="1.18.1",
        **patch,
    )


def test_profile_writer_validates_with_actual_loader_and_deterministic_bytes(tmp_path):
    from wso_api.tvt.session_service import load_account_endpoints

    module = writer()
    target = module.write_profile(
        tmp_path, "account-profile.json", [entry(customer_app_id="", customer_mark="")]
    )
    raw = target.read_bytes()
    assert len(load_account_endpoints(target)) == 1
    assert "customer_app_id" not in json.loads(raw)[0]
    with pytest.raises(ValueError):
        module.write_profile(tmp_path, "account-profile.json", [entry()])
    module.write_profile(tmp_path, "account-profile.json", [entry()], overwrite=True)
    assert target.read_bytes() == raw


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "control", "origin", "oversize", "escape", "env", "key", "directory"],
)
def test_profile_writer_rejects_unsafe_inputs(tmp_path, kind):
    module = writer()
    values = [entry()]
    name = "profile.json"
    if kind == "duplicate":
        values *= 2
    if kind == "control":
        values[0]["country"] = "U\\nS".replace("\\n", "\n")
    if kind == "origin":
        values[0]["origin"] = "http://example.test"
    if kind == "oversize":
        values = [
            dict(entry(), region=f"test{i}", customer_mark="x" * 4096)
            for i in range(64)
        ]
    if kind == "escape":
        name = "../profile.json"
    if kind == "env":
        name = ".env"
    if kind == "key":
        name = "vault.key"
    if kind == "directory":
        (tmp_path / name).mkdir()
    with pytest.raises((ValueError, AccountFailure)):
        module.write_profile(tmp_path, name, values, overwrite=True)


def test_shutdown_is_bounded_and_preserves_asset_cleanup(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace

    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    owned = Client()

    def wait():
        owned.closed += 1
        entered.set()
        release.wait(5)
        settled.set()

    owned.close = wait
    monkeypatch.setattr(bridge, "create_account_worker_client", lambda env=None: owned)
    disposed = []

    class Provider(main.SqlAlchemyBudgetedSessionProvider):
        def __init__(self):
            pass

        def dispose(self):
            disposed.append(True)

    admission = []
    asset = SimpleNamespace(
        admission=SimpleNamespace(close_admission=lambda: admission.append(True)),
        authorization=SimpleNamespace(
            web_session=Provider(),
            identity=Provider(),
            tenant=Provider(),
            redemption=Provider(),
        ),
    )
    monkeypatch.setattr(main, "load_asset_settings", lambda env: None)
    monkeypatch.setattr(main, "start_asset_runtime", lambda **kwargs: asset)
    # configure_assets binds many asset collaborators. Its unrelated setup is a
    # seam here; lifespan still owns and disposes the real provider base types.
    monkeypatch.setattr(main, "configure_assets", lambda *args, **kwargs: None)
    started = time.monotonic()
    try:
        with TestClient(main.create_app()):
            pass
        assert entered.is_set() and owned.closed == 1
        assert time.monotonic() - started < 2.5
        assert len(disposed) == 4 and admission == [True]
    finally:
        release.set()
        assert settled.wait(2)


def test_profile_cli_is_deterministic_and_rejects_arbitrary_json_overwrite(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "scripts/dev/write_tvt_account_profile.py"),
        "--root",
        str(tmp_path),
        "--output-name",
        "profile.json",
        "--endpoint",
        "test",
        "SuperLivePlus",
        "https://example.test",
        "en",
        "US",
        "1.18.1",
    ]
    first = subprocess.run(command, capture_output=True, check=False)
    assert first.returncode == 0
    raw = (tmp_path / "profile.json").read_bytes()
    assert subprocess.run(command, capture_output=True, check=False).returncode == 2
    assert (
        subprocess.run(
            command + ["--overwrite"], capture_output=True, check=False
        ).returncode
        == 0
    )
    assert (tmp_path / "profile.json").read_bytes() == raw
    (tmp_path / "profile.json").write_text('{"private":"synthetic"}')
    assert (
        subprocess.run(
            command + ["--overwrite"], capture_output=True, check=False
        ).returncode
        == 2
    )
    assert (tmp_path / "profile.json").read_text() == '{"private":"synthetic"}'


def test_profile_writer_rejects_hardlink_target(tmp_path):
    module = writer()
    target = module.write_profile(tmp_path, "profile.json", [entry()])
    os.link(target, tmp_path / "other.json")
    with pytest.raises(ValueError):
        module.write_profile(tmp_path, "profile.json", [entry()], overwrite=True)


def test_malformed_present_tls_configuration_is_unavailable(monkeypatch, tmp_path):
    for name in ("CA", "CLIENT_CERT", "CLIENT_KEY"):
        path = tmp_path / (name.lower() + ".pem")
        path.write_text("not a valid PEM credential")
        monkeypatch.setenv("WSO_TVT_BRIDGE_" + name + "_FILE", str(path))
    monkeypatch.setenv("WSO_TVT_BRIDGE_ENDPOINT", "localhost:9443")
    with TestClient(main.create_app()) as http:
        assert http.app.state.tvt_account_worker is None


def test_profile_writer_rejects_unicode_controls(tmp_path):
    values = entry()
    values["language"] = "en\u0085"
    with pytest.raises(ValueError):
        writer().write_profile(tmp_path, "profile.json", [values])
