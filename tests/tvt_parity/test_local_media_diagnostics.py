"""Offline diagnostics boundaries; no SDK, service process or database."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from wso_api.main import create_app
from wso_api.tvt import local_media
from wso_core.tvt.local_service import LocalDeviceFailure


def selector(**changes):
    return {
        "store_id": str(uuid4()),
        "device_id": str(uuid4()),
        "channel_id": str(uuid4()),
        "expected_generation": 1,
        "inventory_revision": 2,
    } | changes


def client(monkeypatch, sink, *, shared=True):
    app = create_app(shared_media_enabled=shared)
    app.state.tvt_local_media_diagnostics_sink = sink
    monkeypatch.setattr(
        local_media,
        "_authenticate",
        lambda request: (object(), SimpleNamespace(user_id=uuid4())),
    )
    return TestClient(app), app


def start(http, body):
    http.cookies.set("__Host-wso-session", "private-cookie-marker")
    return http.post(
        f"/api/v1/tvt/live-sessions?tenant_id={uuid4()}&connection_id={uuid4()}",
        json=body,
    )


def test_mode_422_logs_phase_without_request_identifiers(monkeypatch):
    records = []
    http, _ = client(monkeypatch, records.append)
    body = selector()
    response = start(http, body)
    assert response.status_code == 422
    assert records, "API rejected shared mode without diagnostic evidence"
    record = records[-1]
    assert record["phase"] == "mode"
    assert record["code"] == "LOCAL_DEVICE_INPUT_INVALID"
    assert record["status"] == 422
    assert record["stream"] == "main"
    assert record["wall_present"] is False and record["focus_present"] is False
    encoded = json.dumps(records)
    assert "private-cookie-marker" not in encoded
    assert all(value not in encoded for value in body.values() if type(value) is str)


def test_later_rpc_failure_has_ticket_progress_and_no_exception_text(monkeypatch):
    records = []
    http, app = client(monkeypatch, records.append, shared=False)

    @contextmanager
    def tenant(*args, **kwargs):
        yield SimpleNamespace(session=object())

    monkeypatch.setattr(local_media, "require_tenant", tenant)
    monkeypatch.setattr(local_media, "token_digest", lambda token: "a" * 64)
    monkeypatch.setattr(
        local_media,
        "LocalMediaTicketIssuer",
        lambda *args: SimpleNamespace(issue=lambda *args: "b" * 64),
    )

    def failed(*args, **kwargs):
        raise LocalDeviceFailure("LOCAL_DEVICE_UPSTREAM_REJECTED", 502)

    app.state.tvt_local_media_worker = SimpleNamespace(live_start=failed)
    response = start(http, selector())
    assert response.status_code == 502
    assert records, "RPC failure has no phase evidence"
    record = records[-1]
    assert record["phase"] == "rpc" and "ticket" in record["completed"]
    assert record["exception"] == "LocalDeviceFailure"
    assert record["code"] == "LOCAL_DEVICE_UPSTREAM_REJECTED"


def test_writer_failure_preserves_auth_and_mode_http_results(monkeypatch):
    def failed(record):
        raise RuntimeError("private-writer-secret")

    app = create_app(shared_media_enabled=True)
    app.state.tvt_local_media_diagnostics_sink = failed
    response = TestClient(app).post("/api/v1/tvt/live-sessions", content="private")
    assert response.status_code == 401
    http, _ = client(monkeypatch, failed)
    assert start(http, selector()).status_code == 422


def test_body_and_query_failures_are_separate(monkeypatch):
    records = []
    http, _ = client(monkeypatch, records.append)
    assert http.post("/api/v1/tvt/live-sessions", json={}).status_code == 422
    assert records, "query rejection missing diagnostic"
    assert records[-1]["phase"] == "query"
    url = f"/api/v1/tvt/live-sessions?tenant_id={uuid4()}&connection_id={uuid4()}"
    assert (
        http.post(
            url, content="private", headers={"content-type": "text/plain"}
        ).status_code
        == 422
    )
    assert records[-1]["phase"] == "body"


def safe_record():
    return {
        "schema_version": 1,
        "route": "start",
        "phase": "rpc",
        "completed": ["auth", "query", "body", "mode", "ticket"],
        "shared": True,
        "stream": "sub",
        "wall_present": True,
        "focus_present": False,
        "status": 502,
        "code": "LOCAL_DEVICE_UPSTREAM_REJECTED",
        "exception": "LocalDeviceFailure",
        "elapsed_ms": 50,
    }


def test_sink_rejects_private_fields_and_strings():
    from wso_api.tvt.local_media_diagnostics import BoundedMediaDiagnostics

    written = []
    sink = BoundedMediaDiagnostics(written.append)
    for field in (
        "route",
        "phase",
        "stream",
        "code",
        "exception",
        "completed",
        "status",
    ):
        sink(safe_record() | {field: "private-secret-marker"})
    sink(safe_record() | {"cookie": "private-secret-marker"})
    sink(safe_record() | {"elapsed_ms": True})
    assert written == []
    sink(safe_record())
    assert len(written) == 1 and json.loads(written[0])["phase"] == "rpc"


def test_sink_concurrent_writes_and_failure_attempts_are_bounded():
    from concurrent.futures import ThreadPoolExecutor

    from wso_api.tvt.local_media_diagnostics import BoundedMediaDiagnostics

    written = []
    sink = BoundedMediaDiagnostics(written.append)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(sink, [safe_record() for _ in range(500)]))
    assert 0 < len(written) <= 128
    assert sum(map(len, written)) <= 65536
    assert all(json.loads(raw)["status"] == 502 for raw in written)
    failed = []

    def writer(raw):
        failed.append(1)
        raise RuntimeError("private-secret-marker")

    sink = BoundedMediaDiagnostics(writer)
    for _ in range(500):
        sink(safe_record())
    assert 0 < len(failed) <= 128


def test_success_logs_response_and_elapsed_time(monkeypatch):
    records = []
    http, _ = client(monkeypatch, records.append)

    async def accepted(request, **kwargs):
        from tests.tvt_parity.test_local_media_rpc_api import public_view

        return public_view()

    monkeypatch.setattr(local_media, "call_owned", accepted)
    assert start(http, selector()).status_code == 200
    assert records[-1]["phase"] == "response"
    assert records[-1]["status"] == 200 and records[-1]["code"] == "OK"
    assert records[-1]["exception"] == "none"
    assert 0 <= records[-1]["elapsed_ms"] <= 60000


def test_unknown_exception_class_and_text_never_logged(monkeypatch):
    records = []
    http, _ = client(monkeypatch, records.append)
    secret_class = type("private-secret-marker", (Exception,), {})

    def failed(request):
        raise secret_class("private-secret-message")

    monkeypatch.setattr(local_media, "_authenticate", failed)
    assert start(http, selector()).status_code == 500
    assert records[-1]["phase"] == "auth"
    assert records[-1]["exception"] == "unexpected"
    assert "private-secret" not in json.dumps(records)


def test_wall_route_uses_constant_template_without_wall_identifier():
    app = create_app(shared_media_enabled=True)
    records = []
    app.state.tvt_local_media_diagnostics_sink = records.append
    wall = uuid4()
    response = TestClient(app).get(f"/api/v1/tvt/live-walls/{wall}?tenant_id={uuid4()}")
    assert response.status_code == 401
    assert records[-1]["route"] == "wall"
    assert str(wall) not in json.dumps(records)


def test_exact_wall_action_templates_get_closed_operation_names_without_values():
    from wso_api.tvt.local_media_diagnostics import MediaDiagnostic

    templates = {
        "/api/v1/tvt/live-walls/{wall_id}/focus-reservations/{reference_id}/settle": "focus_settle",
        "/api/v1/tvt/live-walls/{wall_id}/heartbeat": "wall_heartbeat",
        "/api/v1/tvt/live-walls/{wall_id}/stop": "wall_stop",
    }
    for template, expected in templates.items():
        rows = []
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    tvt_local_media_diagnostics_sink=rows.append,
                    tvt_local_media_shared_enabled=True,
                )
            )
        )
        diagnostic = MediaDiagnostic(request, template)
        diagnostic.finish(error=LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404))
        assert rows[0]["route"] == expected
        assert template not in json.dumps(rows) and "{wall_id}" not in json.dumps(rows)
        # Actual URL/identifier substitutions never select a new trusted action.
        rows.clear()
        raw = template.replace("{wall_id}", str(uuid4())).replace(
            "{reference_id}", str(uuid4())
        )
        MediaDiagnostic(request, raw).finish()
        assert rows[0]["route"] not in templates.values()
        assert raw not in json.dumps(rows)


def test_sink_baseexception_does_not_replace_original_http_failure(monkeypatch):
    def failed(value):
        raise KeyboardInterrupt("private-marker")

    http, _ = client(monkeypatch, failed)
    assert start(http, selector()).status_code == 422
