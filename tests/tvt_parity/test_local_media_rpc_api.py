import json
from uuid import uuid4

import pytest
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_tvt_bridge.local_media_rpc import checked_media_json


def public_view():
    ids = [str(uuid4()) for _ in range(7)]
    owner = {
        "tenant_id": ids[0],
        "actor_user_id": ids[1],
        "connection_id": ids[2],
        "store_id": ids[3],
    }
    return {
        "lease": {
            "id": ids[4],
            "owner": owner,
            "device": owner | {"device_id": ids[5], "channel_id": ids[6]},
            "channel": ids[6],
            "kind": "live",
            "state": "NEGOTIATING",
            "expires_at": "2026-10-04T01:00:30Z",
            "heartbeat_at": "2026-10-04T01:00:00Z",
            "connection_generation": 1,
            "inventory_revision": 2,
            "grant_revision": 1,
        },
        "request_id": "test-request",
    }


def test_transport_accepts_only_local_safe_views():
    view = public_view()
    result = checked_media_json(json.dumps(view).encode(), "start", "test-request")
    assert result.lease.device.channel_id == result.lease.channel
    for change in (
        {"serial": "private-marker"},
        {"grant_revision": True},
        {"channel": str(uuid4())},
    ):
        bad = public_view()
        bad["lease"].update(change)
        with pytest.raises(LocalDeviceFailure):
            checked_media_json(json.dumps(bad).encode(), "start", "test-request")


def test_transport_offer_is_bounded_correlated_and_closed():
    payload = {"type": "answer", "sdp": "v=0\r\n", "request_id": "test-request"}
    assert (
        checked_media_json(json.dumps(payload).encode(), "offer", "test-request").type
        == "answer"
    )
    for bad in [
        payload | {"request_id": "foreign"},
        payload | {"secret": "private-marker"},
        payload | {"sdp": "x" * 131073},
    ]:
        with pytest.raises(LocalDeviceFailure):
            checked_media_json(json.dumps(bad).encode(), "offer", "test-request")


def test_live_routes_authenticate_before_body_or_worker_dispatch():
    from fastapi.testclient import TestClient
    from wso_api.main import create_app

    app = create_app()
    client = TestClient(app)
    tenant, connection, lease = (str(uuid4()) for _ in range(3))
    for path in [
        f"/api/v1/tvt/live-sessions?tenant_id={tenant}&connection_id={connection}",
        f"/api/v1/tvt/live-sessions/{lease}/webrtc-offer?tenant_id={tenant}",
        f"/api/v1/tvt/live-sessions/{lease}/stop?tenant_id={tenant}",
        f"/api/v1/tvt/live-sessions/{lease}/heartbeat?tenant_id={tenant}",
    ]:
        response = client.post(
            path,
            content=b"private-marker",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401 and "private-marker" not in response.text


def test_real_mtls_media_start_offer_stop_transport(tmp_path):
    from wso_contracts.tvt.local_media import (
        LocalLiveOfferRequest,
        LocalLiveOfferResponse,
        LocalLiveResponse,
    )
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    from tests.tvt_parity.test_bridge_mtls import StrictExecutor, certs

    class Media:
        def __init__(self):
            self.calls = []

        def start(self, ticket, *, deadline_ms, correlation_id, cancel):
            assert 0 < deadline_ms <= 20000 and not cancel.is_set()
            self.calls.append(("start", ticket))
            data = public_view()
            data["request_id"] = correlation_id
            return LocalLiveResponse.model_validate(data)

        def offer(self, ticket, *, offer, deadline_ms, correlation_id, cancel):
            self.calls.append(("offer", ticket))
            return LocalLiveOfferResponse(sdp="v=0\r\n", request_id=correlation_id)

        def stop(self, ticket, *, deadline_ms, correlation_id, cancel):
            self.calls.append(("stop", ticket))
            data = public_view()
            data["request_id"] = correlation_id
            data["lease"]["state"] = "CLOSED"
            return LocalLiveResponse.model_validate(data)

    certs(tmp_path)
    worker = Media()
    server = AccountRpcServer(
        ServerConfig(
            "localhost:0",
            (tmp_path / "ca.pem").read_bytes(),
            (tmp_path / "server.pem").read_bytes(),
            (tmp_path / "server.key").read_bytes(),
            frozenset({"api.test"}),
            2,
        ),
        StrictExecutor(tmp_path),
        local_media_worker=worker,
    )
    port = server.start()
    client = AccountRpcClient(
        ClientConfig(
            f"localhost:{port}",
            (tmp_path / "ca.pem").read_bytes(),
            (tmp_path / "client.pem").read_bytes(),
            (tmp_path / "client.key").read_bytes(),
        )
    )
    try:
        assert (
            client.live_start(
                "a" * 64, deadline_ms=5000, correlation_id="media-start"
            ).lease.state
            == "NEGOTIATING"
        )
        assert (
            client.live_offer(
                "b" * 64,
                offer=LocalLiveOfferRequest(sdp="v=0\r\n", offer_id=uuid4()),
                deadline_ms=5000,
                correlation_id="media-offer",
            ).type
            == "answer"
        )
        assert (
            client.live_stop(
                "c" * 64, deadline_ms=5000, correlation_id="media-stop"
            ).lease.state
            == "CLOSED"
        )
        assert [name for name, _ in worker.calls] == ["start", "offer", "stop"]
    finally:
        client.close()
        server.close()
