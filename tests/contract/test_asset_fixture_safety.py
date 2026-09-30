"""Offline fixture safety tests are not S3/HTTP lifecycle acceptance."""

import json

import pytest

from tests.support.asset_harness import AssetHarness
from tests.support.asset_provider import LABEL, AssetProvider


def test_unowned_provider_resource_refuses_cleanup(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.created.append(("volume", provider.volume))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps([{"Name": provider.volume, "Labels": {LABEL: "foreign"}}])

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert not any("rm" in arguments for arguments in calls)


def test_selected_asset_fixture_refuses_windows_without_skip(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.support.asset_harness.sys.platform", "win32")
    with pytest.raises(pytest.fail.Exception, match="actual owned Linux"):
        AssetHarness(tmp_path).__enter__()


def test_foreign_process_identity_refuses_signal(tmp_path, monkeypatch):
    harness = AssetHarness(tmp_path)

    class Process:
        pid = 123

        def poll(self):
            return None

    harness.process = Process()
    harness.start_time = 5
    monkeypatch.setattr(
        "tests.support.asset_harness.os.pidfd_open", lambda *_: 999, raising=False
    )
    monkeypatch.setattr("tests.support.asset_harness.os.close", lambda *_: None)
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: None,
        raising=False,
    )
    monkeypatch.setattr(harness, "process_identity", lambda _: ("S", 456, 5))
    monkeypatch.setattr(
        "pathlib.Path.read_bytes", lambda _: b"WSO_ASSET_FIXTURE_OWNER=foreign"
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()


def process_fixture(tmp_path, monkeypatch):
    """Emulate a pinned subprocess handle; never call an operating-system signal."""
    harness = AssetHarness(tmp_path)
    events = []
    pinned = {"value": False}

    class Process:
        pid = 123

        def poll(self):
            return None

        def wait(self, timeout):
            events.append("wait")

    class Log:
        def close(self):
            events.append("log-close")

    harness.process = Process()
    harness.log = Log()
    harness.start_time = 5
    harness.command = [
        "fixture-python",
        "-m",
        "tests.support.asset_process",
        "api",
        "1234",
    ]

    def pin(*_):
        pinned["value"] = True
        events.append("pin")
        return 999

    def identity(_):
        events.append("identity")
        return "S", 123, 5

    def read(path):
        if path.name == "cmdline":
            return b"\0".join(part.encode() for part in harness.command) + b"\0"
        return f"WSO_ASSET_FIXTURE_OWNER={harness.owner}".encode()

    monkeypatch.setattr(harness, "process_identity", identity)
    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    monkeypatch.setattr("tests.support.asset_harness.os.pidfd_open", pin, raising=False)
    monkeypatch.setattr(
        "tests.support.asset_harness.os.close", lambda *_: events.append("close")
    )
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: events.append("signal"),
        raising=False,
    )
    monkeypatch.setattr("tests.support.asset_harness.signal.SIGKILL", 9, raising=False)
    return harness, events, pinned


def test_owned_process_pinned_before_signal_with_descriptor_closed(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    harness.stop_api()
    assert events.index("pin") < events.index("identity") < events.index("signal")
    assert events.index("signal") < events.index("close") < events.index("wait")
    assert harness.process is None


def test_identity_change_during_pidfd_open_denies_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, pinned = process_fixture(tmp_path, monkeypatch)

    def changed(_):
        events.append("identity")
        return "S", 123, 999 if pinned["value"] else 5

    monkeypatch.setattr(harness, "process_identity", changed)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_command_change_refuses_signal_and_closes_handle(tmp_path, monkeypatch):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    original = __import__("pathlib").Path.read_bytes

    def read(path):
        return b"unrelated-process\0" if path.name == "cmdline" else original(path)

    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_process_disappearing_after_pin_refuses_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)

    def vanished(_):
        raise FileNotFoundError("process exited")

    monkeypatch.setattr(harness, "process_identity", vanished)
    with pytest.raises(ValueError, match="identity unavailable"):
        harness.stop_api()
    assert "signal" not in events and "close" in events
