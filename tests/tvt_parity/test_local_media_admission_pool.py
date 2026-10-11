"""Inert pool configuration checks for local media admission; no database."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import QueuePool
from wso_core.tvt import local_media_admission as module
from wso_core.tvt.local_media_admission import LocalMediaAdmission, LocalMediaLease
from wso_core.tvt.local_service import LocalDeviceFailure

URL = "postgresql+psycopg://worker:unused@127.0.0.1:1/unused"


class Key:
    def encryption_key(self):
        return bytes(range(32))


@pytest.fixture
def admission():
    value = LocalMediaAdmission(URL, Key())
    yield value
    value._engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://worker:unused@127.0.0.1:1/unused",
        "postgresql+psycopg2://worker:unused@127.0.0.1:1/unused",
        "sqlite://",
    ],
)
def test_rejects_non_psycopg_worker_url_before_building_engine(url, monkeypatch):
    built = []
    monkeypatch.setattr(module, "create_engine", lambda *a, **k: built.append(a))
    with pytest.raises(LocalDeviceFailure) as caught:
        LocalMediaAdmission(url, Key())
    assert caught.value.code == "LOCAL_DEVICE_UNAVAILABLE"
    assert caught.value.status == 503
    assert built == []


def test_engine_uses_bounded_queue_pool(admission):
    pool = admission._engine.pool
    assert type(pool) is QueuePool
    assert pool.size() == 4
    assert pool._max_overflow == 4
    assert pool._timeout == 1
    assert pool._pre_ping is True
    assert pool._recycle == 300
    assert admission._engine.hide_parameters is True


def test_checkout_timeout_maps_to_unavailable(admission, monkeypatch):
    def timeout(*args, **kwargs):
        raise PoolTimeout("QueuePool limit reached", None, None)

    monkeypatch.setattr(admission._engine, "begin", timeout)
    lease = LocalMediaLease("a" * 64, uuid4(), uuid4(), None, module._SEAL)
    with pytest.raises(LocalDeviceFailure) as caught:
        admission.current(lease)
    assert caught.value.code == "LOCAL_DEVICE_UNAVAILABLE"
    assert caught.value.status == 503


def test_connect_args_keep_server_side_timeouts(admission, monkeypatch):
    import psycopg

    captured = {}

    def fake(*args, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(psycopg, "connect", fake)
    with pytest.raises(Exception, match="stop"):
        admission._engine.connect()
    assert captured["connect_timeout"] == 3
    assert captured["options"] == "-c statement_timeout=20000 -c lock_timeout=3000"
