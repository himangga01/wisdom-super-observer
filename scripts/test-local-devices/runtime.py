"""Explicit root-owned local device browser runtime; import is inert."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import ModuleType
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://localhost:3543"
EVIDENCE_ROOT = ROOT / ".superpowers/verification/local-device-browser-runtime"
NATIVE_KEYS = tuple(
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_" + key
    for key in ("ENABLED", "BUNDLE", "STAGING", "SOURCE_REVIEW", "RUNTIME_REVIEW")
)
OWN = {
    "scripts/test-local-devices/runtime.py",
    "scripts/test-local-devices/server.mjs",
    "tests/contract/test_local_device_browser_fixture.py",
    "docs/integrations/tvt-local-device-browser-runtime.md",
}
ANCHORS = {
    ".superpowers/verification/local-device-api/root-receipt.json": "f780f9d52c4f05df1c9071623dba7f93b4cfb7be1d5f8585ec19b4ce2d066351",
    ".superpowers/verification/local-device-web/root-receipt.json": "7ea5c0675d857edd7487f79eaca086dfbae2df442df2ea67ac67e0ec71dad5f5",
    ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W08-local-service-integration-Fix2-reviewed-root-receipt.json": "d58b026a2f991ad98960ed5f3d3f54b0851b307890cfb317f2426bf8b403e66f",
}
NATIVE_SOURCE_ANCHOR = ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/M1-native-inventory-postpublication-source-root-receipt.json"
NATIVE_SOURCE_SHA = "06aea3adedc19e179aac515e9c962baf6a525ee36dad9b480ad18dde32410483"
BORROWED = {
    "scripts/test-tvt-account/runtime.py",
    "scripts/test-tvt-account/server.mjs",
    "tests/integration/test_tvt_directory_admission.py",
    "tests/integration/test_tvt_account_flow_admission.py",
    "tests/integration/test_tvt_sessions.py",
    "tests/tvt_parity/test_bridge_mtls.py",
    "packages/core/src/wso_core/connections.py",
    "packages/core/src/wso_core/secrets.py",
    "packages/core/src/wso_core/tvt/local_credentials.py",
    "services/api/src/wso_api/auth.py",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_provider.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_config.py",
    "tests/contract/test_windows_socket.py",
    "tests/contract/test_local_inventory_provider.py",
    "docs/integrations/tvt-windows-socket-provider.md",
}
PRIVATE_MEDIA_KEYS = (
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_SOURCE_REVIEW",
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_RUNTIME_REVIEW",
    "WSO_TVT_WINDOWS_DECODER_PYTHON",
)
MEDIA_SOURCES = {
    "services/api/src/wso_api/tvt/local_media_diagnostics.py",
    "tests/tvt_parity/test_local_media_diagnostics.py",
    "tests/contract/test_local_media_debug_runtime.py",
    "scripts/test-local-devices/observation.py",
    "tests/contract/test_local_media_observation.py",
    "packages/contracts/src/wso_contracts/tvt/local_device.py",
    "infra/migrations/versions/0012_tvt_local_devices.py",
    "packages/core/src/wso_core/tvt/local_admission.py",
    "packages/core/src/wso_core/tvt/local_service.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_rpc.py",
    "services/api/src/wso_api/tvt/local_devices.py",
    "services/api/src/wso_api/tvt/local_device_service.py",
    "apps/web/src/features/connections/connections-view.tsx",
    "apps/web/src/lib/tvt/local-device-api.ts",
    "apps/web/src/lib/tvt/local-device-proxy.ts",
    "apps/web/src/app/api/local-devices/[[...segments]]/route.ts",
    "infra/migrations/versions/0013_tvt_local_media_leases.py",
    "infra/migrations/versions/0014_tvt_local_media_hot_authority.py",
    "infra/migrations/versions/0015_tvt_local_media_capacity.py",
    "packages/contracts/src/wso_contracts/tvt/local_media.py",
    "packages/contracts/src/wso_contracts/tvt/media.py",
    "packages/core/src/wso_core/tvt/local_media_admission.py",
    "packages/core/src/wso_core/tvt/local_media_service.py",
    "packages/core/src/wso_core/tvt/windows_decode.py",
    "packages/core/src/wso_core/tvt/windows_decode_worker.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_media_rpc.py",
    "services/tvt-bridge/src/wso_tvt_bridge/server.py",
    "services/tvt-bridge/src/wso_tvt_bridge/client.py",
    "services/api/src/wso_api/main.py",
    "services/api/src/wso_api/tvt/local_media.py",
    "packages/contracts/proto/tvt_bridge.proto",
    "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2.py",
    "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2_grpc.py",
    "services/tvt-media/pyproject.toml",
    "services/tvt-media/src/wso_tvt_media/__init__.py",
    "services/tvt-media/src/wso_tvt_media/codec.py",
    "services/tvt-media/src/wso_tvt_media/live.py",
    "services/tvt-media/src/wso_tvt_media/signaling.py",
    "services/tvt-media/src/wso_tvt_media/native_source.py",
    "services/tvt-media/src/wso_tvt_media/worker.py",
    "apps/web/src/features/connections/local-live-panel.tsx",
    "apps/web/src/features/connections/local-device-inventory.tsx",
    "apps/web/src/lib/tvt/local-live-api.ts",
    "apps/web/src/lib/tvt/local-live-proxy.ts",
    "apps/web/src/lib/tvt/local-live-player.ts",
    "apps/web/src/app/api/live-sessions/[[...segments]]/route.ts",
    "tests/tvt_parity/test_windows_decode.py",
    "tests/contract/test_local_live_provider.py",
    "tests/tvt_parity/test_local_media_rpc_api.py",
    "tests/tvt_parity/test_local_media_worker.py",
    "tests/tvt_parity/test_local_media_source.py",
    "tests/tvt_parity/test_local_webrtc.py",
    "docs/integrations/tvt-local-media-service.md",
    "docs/integrations/tvt-local-webrtc.md",
    "docs/integrations/tvt-windows-decode.md",
    "uv.lock",
    "pyproject.toml",
}

SHARED_PROFILE = {
    "base_originals": 2,
    "main_originals": 1,
    "viewers": 12,
    "physical_slots": 16,
    "worker_process_bytes": 2 << 30,
    "native_process_bytes": 512 << 20,
    "decoder_process_bytes": 512 << 20,
    "retained_host_bytes": 1 << 30,
}
SHARED_SOURCES = {
    "scripts/test-local-devices/core_state_debug.py",
    "tests/contract/test_local_media_core_state_debug.py",
    "tests/contract/test_local_media_core_state_runtime.py",
    "scripts/test-local-devices/core_debug.py",
    "tests/contract/test_local_media_core_debug.py",
    "scripts/test-local-devices/worker_job.py",
    "scripts/test-local-devices/mux-probe.py",
    "tests/contract/test_local_media_worker_job.py",
    "tests/contract/test_local_mux_probe.py",
    "infra/migrations/versions/0016_tvt_device_media_epochs.py",
    "infra/migrations/versions/0017_tvt_main_return_retention.py",
    "packages/core/src/wso_core/tvt/local_live_mux.py",
    "packages/core/src/wso_core/tvt/local_media_mux_types.py",
    "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
    "packages/core/src/wso_core/tvt/local_media_mux_service.py",
    "packages/contracts/src/wso_contracts/tvt/local_media_mux.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ownership.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py",
    "tests/contract/test_native_first_key_debug.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_media_mux_rpc.py",
    "services/tvt-media/src/wso_tvt_media/mux_budget.py",
    "services/tvt-media/src/wso_tvt_media/mux_source.py",
    "services/api/src/wso_api/tvt/local_media_mux.py",
    "apps/web/src/app/monitoring/page.tsx",
    "apps/web/src/features/monitoring/live-wall.tsx",
    "apps/web/src/features/monitoring/live-tile.tsx",
    "apps/web/src/lib/tvt/live-wall-scheduler.ts",
    "apps/web/src/lib/tvt/live-wall-group.ts",
    "apps/web/src/lib/tvt/local-live-wall-api.ts",
    "apps/web/src/lib/tvt/local-live-wall-proxy.ts",
    "apps/web/src/app/api/live-walls/[[...segments]]/route.ts",
    "packages/contracts/generated/openapi.json",
    "packages/contracts/generated/tvt.ts",
    "tests/tvt_parity/test_local_live_mux.py",
    "tests/tvt_parity/test_local_media_mux_migrations.py",
    "tests/tvt_parity/test_local_media_mux_service.py",
    "tests/tvt_parity/test_local_media_mux_source.py",
    "tests/tvt_parity/test_local_media_mux_budget.py",
    "tests/tvt_parity/test_local_media_mux_rpc_api.py",
    "tests/tvt_parity/test_local_media_worker_construction.py",
    "tests/integration/test_local_media_mux_admission.py",
    "tests/contract/test_local_mux_callback.py",
    "tests/contract/test_local_live_mux_ipc.py",
    "tests/contract/test_local_mux_ownership.py",
    "tests/contract/test_local_live_mux_provider.py",
    "tests/contract/test_local_live_mux_pressure.py",
    "apps/web/tests/local-live-wall-api.test.ts",
    "apps/web/tests/local-live-wall-proxy.test.ts",
    "apps/web/tests/live-wall-group.test.ts",
    "docs/integrations/tvt-local-live-mux-codec.md",
    "docs/integrations/tvt-local-live-mux-provider.md",
    "docs/integrations/tvt-local-media-mux-admission.md",
    "docs/integrations/tvt-local-live-mux-acceptance.md",
}


def media_enabled():
    value = os.environ.get("WSO_TEST_LOCAL_MEDIA_BROWSER")
    if value not in (None, "1"):
        raise ValueError("invalid explicit media mode")
    return value == "1"


def shared_enabled():
    value = os.environ.get("WSO_TEST_LOCAL_MEDIA_SHARED")
    if value not in (None, "1") or (value == "1" and not media_enabled()):
        raise ValueError("invalid explicit shared media mode")
    return value == "1"


def shared_context(shared):
    if type(shared) is not bool:
        raise ValueError("invalid shared context")
    return (
        {
            "sharedMedia": {
                "schemaVersion": 1,
                "enabled": True,
                "profile": dict(SHARED_PROFILE),
            }
        }
        if shared
        else {}
    )


def media_revision(*, shared):
    return "0017_tvt_main_return_retention" if shared else "0015_tvt_local_media_capacity"


def worker_job_helper():
    spec = importlib.util.spec_from_file_location(
        "owned_local_worker_job", ROOT / "scripts/test-local-devices/worker_job.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation_enabled() -> bool:
    return (
        os.environ.get("WSO_TEST_LOCAL_MEDIA_BROWSER") == "1"
        and os.environ.get("WSO_TEST_LOCAL_MEDIA_OBSERVE") == "1"
    )


def api_debug_enabled() -> bool:
    flag = os.environ.get("WSO_TEST_LOCAL_MEDIA_API_DEBUG")
    if flag is not None and (flag != "1" or not media_enabled()):
        raise ValueError("invalid explicit API debug mode")
    return flag == "1" or observation_enabled()


def _private_debug_writer(folder, name):
    if name not in {
        "media-api-debug.jsonl",
        "media-core-debug.jsonl",
        "media-core-state-debug.jsonl",
        "media-native-startup-debug.jsonl",
    }:
        raise ValueError("invalid diagnostic target")
    folder = Path(folder)
    evidence = EVIDENCE_ROOT / folder.name
    path = evidence / name
    if (
        not folder.is_absolute()
        or not re.fullmatch(r"local-devices-[0-9a-f]{32}", folder.name)
        or folder.parent.resolve() != (ROOT / "auth-state").resolve()
        or not folder.is_dir()
        or not evidence.is_dir()
        or any(
            p.is_symlink() or p.is_junction()
            for p in (folder, folder.parent, evidence, evidence.parent)
        )
    ):
        raise ValueError("unowned diagnostic path")
    borrowed_helpers().private_directory(evidence, existing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        original = os.fstat(fd)
    finally:
        os.close(fd)

    def write(raw):
        if any(
            p.is_symlink() or p.is_junction() for p in (path, evidence, evidence.parent)
        ):
            raise ValueError("unowned diagnostic path")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        try:
            current = os.fstat(fd)
            if (
                not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino)
                != (original.st_dev, original.st_ino)
                or current.st_size + len(raw) > 65536
            ):
                raise ValueError("diagnostic file custody or bound")
            remaining = memoryview(raw)
            while remaining:
                count = os.write(fd, remaining)
                if count <= 0:
                    raise OSError("diagnostic write failed")
                remaining = remaining[count:]
        finally:
            os.close(fd)

    return write


def configure_api_debug(app, folder):
    """Optional current-run JSONL sink; no paths or values come from requests."""
    if not api_debug_enabled():
        return
    try:
        from wso_api.tvt.local_media_diagnostics import BoundedMediaDiagnostics

        app.state.tvt_local_media_diagnostics_sink = BoundedMediaDiagnostics(
            _private_debug_writer(folder, "media-api-debug.jsonl")
        )
    except Exception:  # noqa: BLE001 - optional writer must not prevent API startup
        return


def core_debug_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "local_fixture_core_debug", ROOT / "scripts/test-local-devices/core_debug.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_core_debug(executor, folder):
    """Decorate only this retained executor's bound start; preserve all owners."""
    if not api_debug_enabled():
        return
    try:
        helper = core_debug_helper()
        writer = _private_debug_writer(folder, "media-core-debug.jsonl")
        original = executor.start
        executor.start = helper.wrap_start(
            original, helper.BoundedCoreDiagnostics(writer), root=ROOT
        )
    except BaseException:  # noqa: BLE001 - optional setup cannot change original owner
        return


def core_state_debug_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "local_fixture_core_state_debug",
        ROOT / "scripts/test-local-devices/core_state_debug.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_core_state_debug(admission, coordinator, folder, *, native_debug=None):
    """Install exact instance hooks before the executor can start its monitor."""
    if not api_debug_enabled():
        return None
    try:
        helper = core_state_debug_helper()
        sink = helper.BoundedCoreStateDiagnostics(
            _private_debug_writer(folder, "media-core-state-debug.jsonl")
        )
        if native_debug is not None:
            sink.add_native_sink(*native_debug)
        helper.install_hooks(admission, coordinator, sink, root=ROOT)
        return sink
    except BaseException:  # noqa: BLE001 - optional setup preserves original calls
        return None


def configure_native_startup_debug(folder):
    """One typed bounded native callback; runtime publisher owns its fixed file."""
    if not api_debug_enabled():
        return None
    try:
        from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

        writer = _private_debug_writer(folder, "media-native-startup-debug.jsonl")
        return NativeFirstKeySink(), writer
    except BaseException:  # noqa: BLE001 - optional callback cannot prevent startup
        return None


def observation_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "local_fixture_observation", ROOT / "scripts/test-local-devices/observation.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measurement_identity(role: str) -> dict[str, object]:
    if not observation_enabled():
        return {}
    result: dict[str, object] = observation_helper().identity_fields(
        enabled=True, role=role
    )
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def bounded_file(path, limit=65536):
    path = Path(path)
    if (
        not path.is_absolute()
        or not path.is_file()
        or path.is_symlink()
        or path.is_junction()
    ):
        raise ValueError("bounded private file required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("bounded private file required")
    return raw


def anchored_sources(root=ROOT):
    trusted = {}
    for relative, digest in ANCHORS.items():
        raw = bounded_file(root / relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or hashlib.sha256(raw).hexdigest() != digest
        ):
            raise ValueError("new local browser source approval refused")
        data = json.loads(raw, object_pairs_hook=unique_object)
        if data["status"] != "SOURCE_ACCEPTED_UNPUBLISHED":
            raise ValueError("new local browser source approval refused")
        trusted.update(
            {name: value["sha256"] for name, value in data["sources"].items()}
        )
    return trusted


def verify_source_approval(path, expected_digest, *, required_paths=None, root=ROOT):
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise ValueError()
        raw = bounded_file(path)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError()
        receipt = json.loads(raw, object_pairs_hook=unique_object)
        media, shared = media_enabled(), shared_enabled()
        expected_keys = {
            "schema_version",
            "root_explicitly_accepted",
            "scope",
            "sources",
        }
        if media:
            expected_keys.add("private_sources")
        if shared:
            expected_keys.add("shared_profile")
        if (
            set(receipt) != expected_keys
            or type(receipt["schema_version"]) is not int
            or receipt["schema_version"] != (3 if shared else 2 if media else 1)
            or receipt["root_explicitly_accepted"] is not True
            or receipt["scope"]
            != (
                "owned-local-device-shared-media-browser-only"
                if shared
                else "owned-local-device-media-browser-only"
                if media
                else "owned-local-device-browser-only"
            )
        ):
            raise ValueError()
        if shared and (
            type(receipt["shared_profile"]) is not dict
            or receipt["shared_profile"] != SHARED_PROFILE
            or any(
                type(value) is not int for value in receipt["shared_profile"].values()
            )
        ):
            raise ValueError()
        required = set(required_paths) if required_paths is not None else OWN | BORROWED
        trusted = {}
        if media:
            private = receipt["private_sources"]
            if type(private) is not dict or set(private) != set(PRIVATE_MEDIA_KEYS):
                raise ValueError()
            for key, value in private.items():
                if (
                    type(value) is not dict
                    or set(value) != {"path", "sha256"}
                    or value["path"] != os.environ.get(key)
                    or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
                ):
                    raise ValueError()
                payload = bounded_file(Path(value["path"]), 16 * 1024 * 1024)
                if hashlib.sha256(payload).hexdigest() != value["sha256"]:
                    raise ValueError()
            if required_paths is None:
                required |= MEDIA_SOURCES
                if shared:
                    required |= SHARED_SOURCES
        elif required_paths is None:
            trusted = anchored_sources(root)
            native_raw = bounded_file(root / NATIVE_SOURCE_ANCHOR)
            if hashlib.sha256(native_raw).hexdigest() != NATIVE_SOURCE_SHA:
                raise ValueError()
            native = json.loads(native_raw, object_pairs_hook=unique_object)
            if (
                set(native)
                != {"status", "files", "dependencies", "critical", "important", "minor"}
                or native["status"] != "ACCEPTED_WINDOWS_NATIVE_PROVIDER_ROOT_REVIEW"
                or any(native[key] != 0 for key in ("critical", "important", "minor"))
            ):
                raise ValueError()
            for mapping in (native["files"], native["dependencies"]):
                for relative, value in mapping.items():
                    if relative in trusted and trusted[relative] != value["sha256"]:
                        raise ValueError()
                    trusted[relative] = value["sha256"]
            required |= set(trusted)
        sources = receipt["sources"]
        if (
            type(sources) is not dict
            or not required.issubset(sources)
            or len(sources) > 1024
        ):
            raise ValueError()
        for relative, digest in sources.items():
            if (
                type(relative) is not str
                or "\\" in relative
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError()
            target = root / relative
            if (
                target.is_symlink()
                or target.is_junction()
                or not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != digest
                or (relative in trusted and trusted[relative] != digest)
            ):
                raise ValueError()
        return sources
    except (ValueError, TypeError, KeyError, OSError):
        raise ValueError("new local browser source approval refused") from None


class PrivateInput:
    __slots__ = ("alias", "credentials", "store_label")

    def __init__(self, alias, label, credentials):
        self.alias, self.store_label, self.credentials = alias, label, credentials

    def __repr__(self):
        return "<LocalBrowserInput: private>"


def parse_input(raw):
    from wso_core.tvt.local_credentials import parse_local_device_credentials

    try:
        if type(raw) is not bytes or len(raw) > 16384:
            raise ValueError()
        body = json.loads(raw, object_pairs_hook=unique_object)
        if (
            type(body) is not dict
            or set(body) != {"schema_version", "devices"}
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1
            or type(body["devices"]) is not list
            or len(body["devices"]) != 2
        ):
            raise ValueError()
        items = []
        for device in body["devices"]:
            if type(device) is not dict or set(device) != {
                "alias",
                "store_label",
                "credentials",
            }:
                raise ValueError()
            credentials = parse_local_device_credentials(
                json.dumps(device["credentials"], separators=(",", ":")).encode()
            )
            for key in ("alias", "store_label"):
                value = device[key]
                if (
                    type(value) is not str
                    or not 1 <= len(value) <= 200
                    or value != value.strip()
                    or any(ord(c) < 32 for c in value)
                    or any(
                        secret.casefold() in value.casefold()
                        for secret in (
                            credentials.serial,
                            credentials.username,
                            credentials.password,
                        )
                    )
                ):
                    raise ValueError()
            items.append(
                PrivateInput(device["alias"], device["store_label"], credentials)
            )
        if (
            len({item.credentials.serial for item in items}) != 2
            or len({item.alias for item in items}) != 2
            or len({item.store_label for item in items}) != 2
        ):
            raise ValueError()
        return tuple(items)
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid private local input") from None


def borrowed_helpers():
    path = ROOT / "scripts/test-tvt-account/runtime.py"
    raw = bounded_file(path)
    if (
        hashlib.sha256(raw).hexdigest()
        != "1d961908c917d66f2da4e111c4dd1eddf46d1c130d8a542957c92b3944a0ba97"
    ):
        raise ValueError("borrowed browser helper source refused")
    spec = importlib.util.spec_from_file_location("reviewed_browser_helpers", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), "exec"), module.__dict__)  # noqa: S102 - execute exact admitted bytes
    return module


def api_environment(roles, auth, bridge, key, ca, *, media=False, shared=False):
    if type(shared) is not bool or (shared and media is not True):
        raise ValueError("invalid shared environment")
    env = (
        borrowed_helpers().child_environment()
        | {
            "WSO_TEST_LOCAL_DEVICE_BROWSER": "1",
            "WSO_CONNECTION_KEY_FILE": str(key),
            "SSL_CERT_FILE": str(ca),
        }
        | auth
    )
    env.update(
        {
            f"WSO_{role}_DATABASE_URL": roles[role]
            for role in ("APP", "IDENTITY", "SESSION")
        }
    )
    env.update(
        {
            "WSO_TVT_BRIDGE_" + name: bridge[name]
            for name in ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE")
        }
    )
    if media:
        env["WSO_TEST_LOCAL_MEDIA_BROWSER"] = "1"
        if observation_enabled():
            env["WSO_TEST_LOCAL_MEDIA_OBSERVE"] = "1"
        if api_debug_enabled():
            env["WSO_TEST_LOCAL_MEDIA_API_DEBUG"] = "1"
    if shared:
        env["WSO_TEST_LOCAL_MEDIA_SHARED"] = "1"
    return env


def worker_environment(
    roles, native, key, *, media=False, decoder=None, shared=False, source_approval=None
):
    if type(shared) is not bool or (shared and media is not True):
        raise ValueError("invalid shared environment")
    if (
        set(native) != set(NATIVE_KEYS)
        or native[NATIVE_KEYS[0]] != "1"
        or not all(native.values())
    ):
        raise ValueError("explicit reviewed native configuration required")
    env = (
        borrowed_helpers().child_environment()
        | native
        | {
            "WSO_TEST_LOCAL_DEVICE_BROWSER": "1",
            "WSO_TEST_LOCAL_DEVICE_NATIVE": "real",
            "WSO_WORKER_DATABASE_URL": roles["WORKER"],
            "WSO_CONNECTION_KEY_FILE": str(key),
        }
    )
    if media:
        if (
            type(decoder) is not type(Path())
            or not decoder.is_absolute()
            or not decoder.is_file()
            or decoder.is_symlink()
            or decoder.is_junction()
        ):
            raise ValueError("explicit owned decoder executable required")
        env.update(
            WSO_TEST_LOCAL_MEDIA_BROWSER="1",
            WSO_TVT_WINDOWS_DECODER_PYTHON=str(decoder),
        )
        if os.environ.get("WSO_TEST_LOCAL_MEDIA_TRACE") == "1":
            env["WSO_TEST_LOCAL_MEDIA_TRACE"] = "1"
        if observation_enabled():
            env["WSO_TEST_LOCAL_MEDIA_OBSERVE"] = "1"
        if api_debug_enabled():
            env["WSO_TEST_LOCAL_MEDIA_API_DEBUG"] = "1"
    if shared:
        if (
            type(source_approval) is not tuple
            or len(source_approval) != 2
            or type(source_approval[0]) is not type(Path())
            or not source_approval[0].is_absolute()
            or type(source_approval[1]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", source_approval[1])
        ):
            raise ValueError("explicit shared source approval required")
        env["WSO_TEST_LOCAL_MEDIA_SHARED"] = "1"
        env["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE"] = str(source_approval[0])
        env["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"] = source_approval[1]
    return env


def required_provider(loader):
    from wso_tvt_bridge.local_inventory_provider import NativeLocalInventoryProvider

    provider = loader()
    if type(provider) is not NativeLocalInventoryProvider:
        raise ValueError("reviewed native provider unavailable")
    return provider


def settle_child(child, folder, label, *, budget=30, receipt=None, pause=time.sleep):
    if child is None:
        return
    record = receipt or (
        lambda value: borrowed_helpers().write_private(
            folder / (label + "-settled.json"), value
        )
    )
    if child.poll() is None:
        try:
            child.stdin.write(b"close\n")
            child.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    deadline = time.monotonic() + budget
    reported = False
    while child.poll() is None:
        if not reported and time.monotonic() >= deadline:
            record({"exit": None, "custody_retained": True, "incomplete": True})
            reported = True
        pause(0.05)
    record({"exit": child.poll(), "custody_retained": False, "incomplete": False})
    if child.poll() != 0 or reported:
        raise RuntimeError("owned local child failed after settlement")


def spawn_python(arguments, env):
    import sysconfig

    launch = f"import site,runpy,sys;sys.prefix={sys.prefix!r};site.addsitedir({sysconfig.get_paths()['purelib']!r});sys.path.insert(0,{str(ROOT)!r});sys.argv={([str(Path(__file__).resolve())] + arguments)!r};runpy.run_path(sys.argv[0],run_name='__main__')"
    return subprocess.Popen(
        [sys._base_executable if os.name == "nt" else sys.executable, "-c", launch],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def spawn_shared_worker(folder, env, owner):
    import sysconfig

    helper = worker_job_helper()
    command = [
        sys._base_executable,
        "-I",
        "-S",
        "-c",
        helper.WORKER_BOOTSTRAP,
        str(ROOT),
        sys.prefix,
        sysconfig.get_paths()["purelib"],
        str(Path(__file__).resolve()),
        str(folder),
    ]
    return owner.launch(command, env=env, cwd=ROOT)


def settle_shared_worker(owner, folder, *, budget=40, receipt=None, pause=time.sleep):
    write = receipt or (
        lambda value: borrowed_helpers().write_private(
            folder / "worker-settled.json", value
        )
    )
    deadline, overrun = time.monotonic() + budget, False
    while not owner.close_step():
        if not overrun and time.monotonic() >= deadline:
            overrun = True
            write(owner.receipt())
        pause(0.05)
    value = owner.receipt()
    write(value)
    if overrun or value["failed"]:
        raise RuntimeError("owned shared worker failed after settlement")


@contextmanager
def owned_database(evidence, *, media=False, shared=False):
    if type(shared) is not bool or (shared and media is not True):
        raise ValueError("invalid shared database mode")
    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from tests.integration import test_tvt_directory_admission as accepted

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accepted, "EVIDENCE", evidence)
        with contextmanager(accepted.directory_database.__wrapped__)() as engines:
            owned = engines["ADMIN"].url.database
            if not re.fullmatch(r"w07_directory_[0-9a-f]{32}", owned):
                raise ValueError("fresh owned local database required")
            with engines["ADMIN"].connect() as db:
                actual, marker = db.execute(
                    text(
                        "SELECT current_database(),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
                    )
                ).one()
                if actual != owned or not marker.startswith("owned-w07-directory-"):
                    raise ValueError("fresh owned local database required")
            cfg = Config(str(ROOT / "infra/alembic.ini"))
            cfg.set_main_option(
                "sqlalchemy.url",
                engines["ADMIN"]
                .url.render_as_string(hide_password=False)
                .replace("%", "%%"),
            )
            command.upgrade(cfg, "0012_tvt_local_devices")
            try:
                if media:
                    command.upgrade(cfg, media_revision(shared=shared))
                try:
                    yield engines
                finally:
                    if media:
                        command.downgrade(cfg, "0012_tvt_local_devices")
            finally:
                command.downgrade(cfg, "0011_tvt_directory_read_tickets")


def seed_owner(engines, issuer, owner, key, inputs):
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from wso_core.connections import ConnectionService
    from wso_core.db import tenant_session
    from wso_core.secrets import FileKeyProvider
    from wso_core.tenancy import identity_session

    tenant, stores = uuid4(), (uuid4(), uuid4())
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.tenants(id,name) VALUES(:id,'Local Device Browser Demo')"
            ),
            {"id": tenant},
        )
        db.execute(
            text(
                "INSERT INTO public.users(id,oidc_issuer,oidc_subject) VALUES(:id,:issuer,:subject)"
            ),
            {"id": owner, "issuer": issuer, "subject": str(owner)},
        )
        db.execute(
            text(
                "INSERT INTO public.memberships(tenant_id,user_id,role) VALUES(:tenant,:owner,'OWNER')"
            ),
            {"tenant": tenant, "owner": owner},
        )
        for item, store in zip(inputs, stores, strict=True):
            db.execute(
                text(
                    "INSERT INTO public.stores(id,tenant_id,name,timezone) VALUES(:id,:tenant,:name,'Asia/Seoul')"
                ),
                {"id": store, "tenant": tenant, "name": item.store_label},
            )
    with identity_session(
        issuer, str(owner), session_factory=sessionmaker(engines["IDENTITY"])
    ) as lookup:
        choice = lookup.authorize_tenant(tenant)
    links = []
    with tenant_session(
        tenant, authorization=choice, session_factory=sessionmaker(engines["APP"])
    ) as db:
        for item, store in zip(inputs, stores, strict=True):
            view = ConnectionService(db, FileKeyProvider(key)).mutate(
                "create",
                {
                    "kind": "TVT_DEVICE",
                    "alias": item.alias,
                    "site": item.store_label,
                    "store_ids": [str(store)],
                },
                credentials=item.credentials.to_encrypt_bytes(),
            )
            links.append(
                {
                    "connectionId": str(view.id),
                    "storeId": str(store),
                    "alias": item.alias,
                    "storeLabel": item.store_label,
                    "generation": view.generation,
                }
            )
    return tenant, links


def settle_media(worker, admission, *, pause=time.sleep):
    while worker.shutdown() is not True:
        pause(0.1)
    while admission.shutdown() is not True:
        pause(0.1)


def compose_shared_media(
    worker_url,
    keys,
    config,
    decoder,
    *,
    observation_factory=None,
    factories=None,
    observer=None,
    core_debug_folder=None,
    retain_core_state_debug=None,
):
    """One owned profile; every factory shares the same authority and budget."""
    if factories is None:
        from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
        from wso_core.tvt.local_media_mux_service import (
            DeviceEpochCoordinator,
            MuxMediaExecutor,
        )
        from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget
        from wso_tvt_bridge.local_live_mux_provider import NativeLocalMuxProvider
        from wso_tvt_bridge.windows_socket import WindowsSocketProvider
        from wso_tvt_media.mux_budget import MediaCreditLedger
        from wso_tvt_media.mux_source import MuxSourceFactory
        from wso_tvt_media.worker import LocalMediaWorker

        factories = {
            "SqlMuxAdmission": SqlMuxAdmission,
            "DeviceEpochCoordinator": DeviceEpochCoordinator,
            "MuxMediaExecutor": MuxMediaExecutor,
            "MuxOriginalBudget": MuxOriginalBudget,
            "NativeLocalMuxProvider": NativeLocalMuxProvider,
            "WindowsSocketProvider": WindowsSocketProvider,
            "MediaCreditLedger": MediaCreditLedger,
            "MuxSourceFactory": MuxSourceFactory,
            "LocalMediaWorker": LocalMediaWorker,
        }
    admission = factories["SqlMuxAdmission"](worker_url, keys)
    coordinator = executor = retained_worker = None

    def retain_owner(owner):
        nonlocal retained_worker
        if owner is None or (
            retained_worker is not None and retained_worker is not owner
        ):
            raise ValueError("original media construction owner changed")
        retained_worker = owner

    try:
        native_debug = (
            configure_native_startup_debug(core_debug_folder)
            if core_debug_folder is not None
            else None
        )
        budget = factories["MuxOriginalBudget"](worker_epoch=admission.worker_epoch)
        native = factories["WindowsSocketProvider"](mux_config=config)
        provider = factories["NativeLocalMuxProvider"](
            native,
            budget=budget,
            admission=admission,
            **(
                {"first_key_debug": native_debug[0]} if native_debug is not None else {}
            ),
        )
        if observer is not None:
            # R182: wrap the factory boundary before Core captures any prepared
            # original or binding/receipt supplier. Exact originals stay owned.
            provider = observer.wrap_mux_provider(provider)
            observation_factory = observer.begin_source
        coordinator = factories["DeviceEpochCoordinator"](admission, provider, budget)
        if core_debug_folder is not None:
            state_debug = configure_core_state_debug(
                admission, coordinator, core_debug_folder, native_debug=native_debug
            )
            if state_debug is not None and retain_core_state_debug is not None:
                retain_core_state_debug(state_debug)
        executor = factories["MuxMediaExecutor"](admission, coordinator)
        if core_debug_folder is not None:
            configure_core_debug(executor, core_debug_folder)
        credit = factories["MediaCreditLedger"]()
        source = factories["MuxSourceFactory"](executor, credit)
        worker = factories["LocalMediaWorker"](
            executor,
            decoder_executable=decoder,
            observation_factory=observation_factory,
            source_factory=source,
            retain_owner=retain_owner,
        )
        if retained_worker is not worker:
            raise ValueError("original media construction owner unavailable")
        return worker, admission
    except BaseException:
        if retained_worker is not None:
            # R187 supplies this exact owner before Thread.start/ready wait.
            # An exception or pending constructor is not executor retirement.
            while True:
                try:
                    if retained_worker.shutdown() is True:
                        break
                except BaseException:  # noqa: BLE001, S110 - retain, never log private errors
                    pass
                try:
                    time.sleep(0.1)
                except BaseException:  # noqa: BLE001, S110 - reporting cannot drop custody
                    pass
        if executor is not None:
            settle_media(executor, admission)
        elif coordinator is not None:
            settle_media(coordinator, admission)
        else:
            while admission.shutdown() is not True:
                time.sleep(0.1)
        raise


def compose_shared_controls(media_worker, observer=None):
    """Register one original control adapter; observer only decorates the entrance."""
    from wso_tvt_bridge.local_media_mux_rpc import LocalMuxWorkerAdapter

    adapter = LocalMuxWorkerAdapter(media_worker)
    return observer.wrap_mux_controls(adapter) if observer is not None else adapter


def install_media_observer(folder):
    """Root-only bounded structural observations; no payloads or exception text."""
    if os.environ.get("WSO_TEST_LOCAL_MEDIA_TRACE") != "1":
        return
    from wso_core.tvt.local_service import LOCAL_DEVICE_FAILURES
    from wso_tvt_bridge import windows_socket as native_module
    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority
    from wso_tvt_bridge.windows_socket import WindowsSocketProvider

    child_observer = """
import json as _trace_json, time as _trace_time
from pathlib import Path as _TracePath
from wso_tvt_bridge.windows_socket import protect_created_acl as _trace_acl
_trace_rows = []
def _child_trace(frame, event, arg):
    name = frame.f_code.co_name
    filename = frame.f_code.co_filename
    if not ((name == 'serve_live' and filename.endswith('windows_socket_worker.py')) or (name == 'exchange' and filename.endswith('local_live_ipc.py'))):
        return None
    if event == 'exception' and len(_trace_rows) < 6:
        try:
            kind = type(arg[1]).__name__
            row = {'function': name, 'line': frame.f_lineno, 'kind': kind if kind in ('AuthorityError','LiveDenied','BrokenPipeError','EOFError','OSError','ValueError') else 'other'}
            if name == 'serve_live':
                callback = frame.f_locals.get('callback')
                row.update(callback_failed=callback.failed, callback_closed=callback.closed, callback_bytes=callback.used, callback_chunks=callback.chunks.qsize(), context_matches=callback.context.value==callback.generation, authorized=frame.f_locals.get('authorized') is True)
                authority = frame.f_locals.get('authority')
            else:
                authority = frame.f_locals.get('self')
            if authority is not None:
                row.update(remote_closed=authority.closed, remote_sequence=authority.sequence, remote_expired=_trace_time.monotonic()>=authority.deadline)
            _trace_rows.append(row)
            output = _TracePath('native-boundary.json')
            output.write_text(_trace_json.dumps(_trace_rows, indent=2), encoding='utf-8')
            _trace_acl(output)
        except Exception:
            pass
    return _child_trace
sys.settrace(_child_trace)
"""
    marker = "from wso_tvt_bridge.windows_socket_worker import main"
    if native_module.BOOTSTRAP.count(marker) != 1:
        raise ValueError("owned diagnostic bootstrap refused")
    native_module.BOOTSTRAP = native_module.BOOTSTRAP.replace(
        marker, child_observer + "\n" + marker
    )

    records = []
    lock = threading.Lock()
    path = EVIDENCE_ROOT / folder.parent.name / "media-boundary.json"

    def record(value):
        with lock:
            if len(records) >= 64:
                return
            records.append(value)
            try:
                path.write_text(json.dumps(records, indent=2), encoding="utf-8")
            except OSError:
                pass

    original_run, original_deny = WindowsSocketProvider.run, LiveParentAuthority.deny

    def deny(self, reason):
        if not self.failure:
            record(
                {
                    "event": "first-denial",
                    "reason": reason
                    if reason
                    in {
                        "denied",
                        "protocol",
                        "deadline",
                        "cancelled",
                        "closed",
                        "overflow",
                    }
                    else "other",
                    "ready": self.ready,
                    "handoff": self.handed_off,
                    "setup": self.setup_data is not None,
                    "open_ack": self.open_ack,
                    "frames": len(self.frames),
                    "cancel": self.cancel.is_set(),
                    "expired": time.monotonic() >= self.deadline,
                }
            )
        return original_deny(self, reason)

    def run(self, config, request, **kwargs):
        authority = kwargs.get("service")
        if type(authority) is not LiveParentAuthority:
            return original_run(self, config, request, **kwargs)
        started = time.monotonic()
        current = kwargs["current"]
        counts = [0]

        def checked():
            counts[0] += 1
            try:
                result = current()
                if result is not True:
                    record({"event": "current-false", "checks": counts[0]})
                return result
            except Exception as error:
                code = getattr(error, "code", None)
                record(
                    {
                        "event": "current-error",
                        "code": code if code in LOCAL_DEVICE_FAILURES else "other",
                    }
                )
                raise

        kwargs["current"] = checked
        try:
            return original_run(self, config, request, **kwargs)
        finally:
            record(
                {
                    "event": "native-return",
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "checks": counts[0],
                    "ready": authority.ready,
                    "handoff": authority.handed_off,
                    "failure": authority.failure
                    if authority.failure
                    in {
                        "denied",
                        "protocol",
                        "deadline",
                        "cancelled",
                        "closed",
                        "overflow",
                        "",
                    }
                    else "other",
                }
            )

    def trace(frame, event, arg):
        filename = frame.f_code.co_filename.replace("\\", "/")
        name = frame.f_code.co_name
        allowed = (name == "pump" and filename.endswith("/local_live_ipc.py")) or (
            any(
                filename.endswith(suffix)
                for suffix in (
                    "/wso_tvt_media/worker.py",
                    "/wso_tvt_media/native_source.py",
                    "/wso_core/tvt/windows_decode.py",
                    "/wso_tvt_media/live.py",
                    "/wso_tvt_media/signaling.py",
                )
            )
            and name
            in {
                "start",
                "_prepare",
                "packet",
                "_run",
                "decode",
                "_admit",
                "answer",
                "offer",
                "recv",
                "binding",
                "validate_offer",
            }
        )
        if not allowed:
            return None
        if event == "exception":
            kind = type(arg[1]).__name__
            if kind in {"StopIteration", "GeneratorExit"}:
                return trace
            row = {
                "event": "media-exception",
                "module": filename.rsplit("/", 1)[-1],
                "function": name,
                "line": frame.f_lineno,
                "kind": kind
                if kind
                in {
                    "AuthorityError",
                    "LiveError",
                    "LiveDenied",
                    "UnsupportedLive",
                    "BrokenPipeError",
                    "EOFError",
                    "ValueError",
                    "UnboundLocalError",
                    "MediaDenied",
                    "DecodeError",
                    "DecodeDenied",
                    "LocalDeviceFailure",
                    "TypeError",
                    "AttributeError",
                    "RuntimeError",
                    "TimeoutError",
                    "CancelledError",
                }
                else "other",
            }
            if name == "validate_offer":
                lines = frame.f_locals.get("lines", [])
                row.update(
                    lines=len(lines),
                    max_line=max((len(line) for line in lines), default=0),
                    candidates=sum(line.startswith("a=candidate:") for line in lines),
                )
                parsed = frame.f_locals.get("parsed")
                if parsed is not None:
                    row["media_count"] = len(parsed.media)
                    if parsed.media:
                        m = parsed.media[0]
                        row.update(
                            video=m.kind == "video",
                            receive_only=m.direction == "recvonly",
                            rtcp_mux=m.rtcp_mux,
                            active_port=m.port != 0,
                            codecs=len(m.rtp.codecs),
                            vp8=any(
                                c.mimeType.lower() == "video/vp8" for c in m.rtp.codecs
                            ),
                        )
            if name == "packet":
                value = frame.f_locals.get("frame")
                if type(value).__name__ == "PrivateLiveFrame":
                    summary = value.summary()
                    row.update(
                        width=summary.width,
                        height=summary.height,
                        codec=summary.codec
                        if summary.codec in {"h264", "h265"}
                        else "other",
                        payload_bytes=len(value.private_bytes()),
                        key=value.key_frame,
                        timestamp_present=type(value.device_timestamp.unix_microseconds)
                        is int,
                        frame_type=value.source_context[3],
                    )
                    kinds = frame.f_locals.get("kinds")
                    if type(kinds) is list:
                        row["nal_types"] = [
                            n for n in kinds[:16] if type(n) is int and 0 <= n <= 63
                        ]
            record(row)
        return trace

    WindowsSocketProvider.run = run
    LiveParentAuthority.deny = deny
    threading.settrace(trace)


def worker_process(folder):
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_NATIVE") != "real":
        raise ValueError("explicit real native worker mode required")
    shared = shared_enabled()
    if shared:
        verify_source_approval(
            Path(os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE"]),
            os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"],
        )
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.local_admission import LocalDeviceAdmission
    from wso_core.tvt.local_service import LocalVerificationExecutor
    from wso_tvt_bridge.local_inventory_config import load_local_inventory_provider
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig
    from wso_tvt_bridge.windows_socket import pending_owner_snapshot

    helper = borrowed_helpers()
    media_worker = media_admission = observation = core_state_debug = None

    def retain_state_debug(owner):
        nonlocal core_state_debug
        if core_state_debug is not None and core_state_debug is not owner:
            raise ValueError("original diagnostic publisher changed")
        core_state_debug = owner
        # The exact publisher owner is retained before Thread.start.
        owner.start()

    def close_state_debug():
        if core_state_debug is not None:
            while core_state_debug.close() is not True:
                time.sleep(0.1)

    if shared and observation_enabled():
        # No provider/DB constructor before the exact schema3 source port exists.
        sys.path.insert(0, str(ROOT / "services/tvt-media/src"))
        from wso_tvt_media import worker as media_worker_module

        observation_module = observation_helper()
        observation = observation_module.MediaObservation(
            lambda value: observation_module.write_snapshot(
                EVIDENCE_ROOT / folder.parent.name / "media-observation.json", value
            ),
            shared=True,
        )
        if observation.snapshot().get("schema_version") != 3 or any(
            not callable(getattr(observation, name, None))
            for name in ("wrap_mux_provider", "wrap_mux_controls")
        ):
            raise ValueError("reviewed shared observation integration required")
        observation.install_peer_observer(media_worker_module)
    provider = required_provider(load_local_inventory_provider)
    admission = LocalDeviceAdmission(
        os.environ["WSO_WORKER_DATABASE_URL"],
        FileKeyProvider(Path(os.environ["WSO_CONNECTION_KEY_FILE"])),
    )
    if shared:
        sys.path.insert(0, str(ROOT / "services/tvt-media/src"))
        try:
            media_worker, media_admission = compose_shared_media(
                os.environ["WSO_WORKER_DATABASE_URL"],
                FileKeyProvider(Path(os.environ["WSO_CONNECTION_KEY_FILE"])),
                provider._config,
                Path(os.environ["WSO_TVT_WINDOWS_DECODER_PYTHON"]),
                **(
                    {
                        "core_debug_folder": folder.parent,
                        "retain_core_state_debug": retain_state_debug,
                    }
                    if api_debug_enabled()
                    else {}
                ),
                **({"observer": observation} if observation is not None else {}),
            )
        except BaseException:
            try:
                admission.shutdown()
            finally:
                close_state_debug()
            raise
    elif media_enabled():
        install_media_observer(folder)
        from wso_core.tvt.local_media_admission import LocalMediaAdmission
        from wso_core.tvt.local_media_service import LocalMediaExecutor
        from wso_tvt_bridge.local_live_provider import NativeLocalLiveProvider

        sys.path.insert(0, str(ROOT / "services/tvt-media/src"))
        from wso_tvt_media.worker import LocalMediaWorker

        media_admission = LocalMediaAdmission(
            os.environ["WSO_WORKER_DATABASE_URL"],
            FileKeyProvider(Path(os.environ["WSO_CONNECTION_KEY_FILE"])),
        )
        live_provider = NativeLocalLiveProvider(provider._config)
        if observation_enabled():
            media_worker_module = sys.modules["wso_tvt_media.worker"]

            observation_module = observation_helper()
            observation = observation_module.MediaObservation(
                lambda value: observation_module.write_snapshot(
                    EVIDENCE_ROOT / folder.parent.name / "media-observation.json", value
                )
            )
            observation.install_peer_observer(media_worker_module)
            live_provider = observation.wrap_provider(live_provider)
        media_executor = LocalMediaExecutor(media_admission, live_provider)
        try:
            media_worker = LocalMediaWorker(
                media_executor,
                decoder_executable=Path(os.environ["WSO_TVT_WINDOWS_DECODER_PYTHON"]),
                observation_factory=observation.begin_source
                if observation is not None
                else None,
            )
        except BaseException:
            settle_media(media_executor, media_admission)
            admission.shutdown()
            raise

    def dispose():
        if media_worker is not None:
            settle_media(media_worker, media_admission)
        for owner in pending_owner_snapshot():
            owner.passive_wait()
        if any(not owner.confirmed for owner in pending_owner_snapshot()):
            raise RuntimeError("native custody remains")
        admission.shutdown()

    class NoCloudWorker:
        def __getattr__(self, name):
            from wso_core.tvt.account_projection import AccountFailure

            def unavailable(*args, **kwargs):
                raise AccountFailure()

            return unavailable

    try:
        mux_worker = (
            compose_shared_controls(media_worker, observation) if shared else None
        )
        server = AccountRpcServer(
            ServerConfig(
                bind="localhost:0",
                ca=(folder / "ca.pem").read_bytes(),
                certificate=(folder / "server.pem").read_bytes(),
                key=(folder / "server.key").read_bytes(),
                client_sans=frozenset({"api.test"}),
                capacity=32,
            ),
            NoCloudWorker(),
            local_device_worker=LocalVerificationExecutor(admission, provider),
            **(
                {"local_media_worker": media_worker} if media_worker is not None else {}
            ),
            shared_media_enabled=shared,
            **({"local_media_mux_worker": mux_worker} if shared else {}),
            dispose=dispose,
        )
    except BaseException:
        if shared:
            try:
                dispose()
            finally:
                try:
                    if observation is not None:
                        observation.close()
                finally:
                    close_state_debug()
        raise
    try:
        port = server.start()
        if observation is not None:
            observation.start()
        helper.write_private(
            folder / "worker-ready.json",
            {
                "pid": os.getpid(),
                "port": port,
                "providerLoaded": True,
                "sharedMediaEnabled": shared,
            }
            | measurement_identity("worker"),
        )
        sys.stdin.readline()
    finally:
        try:
            drained = server.close(grace=20)
            if not drained:
                helper.write_private(
                    folder / "worker-close.json",
                    {"drained": False, "custodyRetained": True},
                )
                while not server.close(grace=1):
                    time.sleep(0.1)
        finally:
            try:
                terminal = observation.close() if observation is not None else None
            finally:
                close_state_debug()
        helper.write_private(
            folder / "worker-close.json",
            {
                "drained": True,
                "custodyRetained": False,
                "nativeOwnersConfirmed": all(
                    owner.confirmed for owner in pending_owner_snapshot()
                ),
            }
            | ({"mediaObservation": terminal} if terminal is not None else {})
            | (
                {"mediaCoreStateDebug": core_state_debug.status()}
                if core_state_debug is not None
                else {}
            ),
        )


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
    from wso_core.secrets import SecretCipher
    from wso_core.tvt.local_admission import LocalDeviceAdmission
    from wso_core.tvt.local_service import LocalVerificationExecutor
    from wso_core.tvt.token_vault import TokenVault

    def forbidden(*args, **kwargs):
        raise RuntimeError("API local worker capability forbidden")

    if (
        any(key in os.environ for key in NATIVE_KEYS)
        or os.environ.get("WSO_WORKER_DATABASE_URL")
        or os.environ.get("WSO_TVT_WINDOWS_DECODER_PYTHON")
    ):
        raise ValueError("API worker environment refused")
    SecretCipher.open = forbidden
    LocalDeviceAdmission.__init__ = forbidden
    LocalVerificationExecutor.__init__ = forbidden
    TokenVault.__init__ = forbidden
    if media_enabled():
        from wso_core.tvt.local_media_admission import LocalMediaAdmission
        from wso_core.tvt.local_media_service import LocalMediaExecutor

        LocalMediaAdmission.__init__ = forbidden
        LocalMediaExecutor.__init__ = forbidden
        from wso_tvt_bridge.local_live_provider import NativeLocalLiveProvider

        NativeLocalLiveProvider.__init__ = forbidden
    shared = shared_enabled()
    if shared:
        from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
        from wso_core.tvt.local_media_mux_service import (
            DeviceEpochCoordinator,
            MuxMediaExecutor,
        )
        from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget
        from wso_tvt_bridge.local_live_mux_provider import NativeLocalMuxProvider
        from wso_tvt_bridge.windows_socket import WindowsSocketProvider

        for factory in (
            SqlMuxAdmission,
            DeviceEpochCoordinator,
            MuxMediaExecutor,
            NativeLocalMuxProvider,
            MuxOriginalBudget,
            WindowsSocketProvider,
        ):
            factory.__init__ = forbidden
    from wso_api.main import create_app

    helper = borrowed_helpers()
    settings = AuthSettings.from_environment()
    engines = {
        role: create_engine(
            os.environ[f"WSO_{role}_DATABASE_URL"], hide_parameters=True
        )
        for role in ("APP", "IDENTITY", "SESSION")
    }
    app = create_app(shared_media_enabled=shared)
    configure_api_debug(app, folder)
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
            helper.GuardedApplication(
                app, helper.AdmissionGate(folder / "admission.sqlite")
            ),
            log_config=None,
            log_level="critical",
            access_log=False,
            ssl_certfile=str(folder / "server.pem"),
            ssl_keyfile=str(folder / "server.key"),
            timeout_graceful_shutdown=5,
        )
    )

    def shutdown():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=shutdown, daemon=True).start()
    helper.write_private(
        folder / "api-ready.json",
        {
            "pid": os.getpid(),
            "port": listener.getsockname()[1],
            "sharedMediaEnabled": shared,
        }
        | measurement_identity("api"),
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        for engine in engines.values():
            engine.dispose()


def owner_page_text(value):
    return (
        value.replace(
            "Sign in as synthetic directory staff", "Sign in as local device demo owner"
        )
        .replace("Synthetic directory fixture", "Local device browser verification")
        .replace(
            "Invented account and devices. No vendor connection.",
            "This synthetic owner uses real registered devices for read-only verification. Live playback and device control are separate.",
        )
    )


def coordinate():
    media, shared = media_enabled(), shared_enabled()
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_NATIVE") != "real" or not os.environ.get(
        "WSO_TEST_BROWSER_TLS_DIR"
    ):
        raise ValueError("explicit real mode and trusted TLS required")
    path = Path(os.environ["WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE"])
    if (
        not path.is_absolute()
        or path.name != "context.json"
        or not re.fullmatch(r"local-devices-[0-9a-f]{32}", path.parent.name)
        or path.parent.parent.resolve() != (ROOT / "auth-state").resolve()
    ):
        raise ValueError("explicit owned local context required")
    approved = verify_source_approval(
        Path(os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE"]),
        os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"],
    )
    helper = borrowed_helpers()
    folder, owner = path.parent, secrets.token_hex(16)
    evidence = EVIDENCE_ROOT / folder.name
    evidence.mkdir(parents=True, exist_ok=False)
    helper.private_directory(folder)
    helper.write_private(folder / "owner.json", {"owner": owner})
    initial = helper.source_snapshot() | {
        name: {"raw_sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in OWN
    }
    (evidence / "source-before.json").write_text(json.dumps(initial, indent=2))
    worker = api = worker_owner = None
    result = {"apiSettled": False, "workerSettled": False, "contextRemoved": False}
    try:
        if observation_enabled():
            helper.write_private(
                folder / "runtime-owner.json", measurement_identity("runtime")
            )
        inputs = parse_input(
            bounded_file(Path(os.environ["WSO_TEST_LOCAL_BROWSER_INPUT_FILE"]), 16384)
        )
        from tests.tvt_parity.test_bridge_mtls import certs

        os.environ["WSO_TEST_ACCOUNT_BROWSER"] = (
            "1"  # Pure reviewed TLS helper opt-in only.
        )
        helper.browser_certificates(folder, certs)
        key = folder / "connection.key"
        key.write_bytes(secrets.token_bytes(32))
        key.chmod(0o600)
        bridge_folder = folder / "bridge"
        helper.private_directory(bridge_folder)
        certs(bridge_folder)
        gate = helper.AdmissionGate(folder / "admission.sqlite", create=True)
        fixed_owner = uuid4()
        with ExitStack() as stack:
            engines = stack.enter_context(
                owned_database(evidence, media=media, shared=shared)
            )
            issuer_secret = secrets.token_urlsafe(48)
            issuer = helper.DirectoryIssuer(
                folder, str(fixed_owner), issuer_secret, gate
            )
            stack.callback(issuer.close)
            original = issuer.server.RequestHandlerClass

            class OwnerHandler(original):
                def respond(
                    self, status, value, content_type="application/json", **headers
                ):
                    if type(value) is str:
                        value = owner_page_text(value)
                    return super().respond(status, value, content_type, **headers)

            issuer.server.RequestHandlerClass = OwnerHandler
            tenant, links = seed_owner(engines, issuer.origin, fixed_owner, key, inputs)
            del inputs
            roles = {
                role: engines[role].url.render_as_string(hide_password=False)
                for role in ("APP", "IDENTITY", "SESSION", "WORKER")
            }
            native = {key: os.environ.get(key, "") for key in NATIVE_KEYS}
            worker_env = worker_environment(
                roles,
                native,
                key,
                media=media,
                shared=shared,
                source_approval=(
                    Path(os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE"]),
                    os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"],
                )
                if shared
                else None,
                decoder=Path(os.environ["WSO_TVT_WINDOWS_DECODER_PYTHON"])
                if media
                else None,
            )
            observation = observation_helper() if observation_enabled() else None

            def close_worker():
                if worker_owner is not None:
                    settle_shared_worker(worker_owner, folder)
                else:
                    settle_child(worker, folder, "worker", budget=40)
                result["workerSettled"] = True
                if observation is not None:
                    result["mediaObservation"] = observation.read_terminal(
                        bridge_folder / "worker-close.json"
                    )

            if shared:
                # Retain the owner and cleanup callback BEFORE launch can fail.
                worker_owner = worker_job_helper().WorkerSupervisor()
                stack.callback(close_worker)
                worker = spawn_shared_worker(bridge_folder, worker_env, worker_owner)
            else:
                worker = spawn_python(["--worker", str(bridge_folder)], worker_env)
                stack.callback(close_worker)
            helper.wait_file(
                bridge_folder / "worker-ready.json", worker, time.monotonic() + 20
            )
            ready = json.loads((bridge_folder / "worker-ready.json").read_text())
            if (
                ready["pid"] != worker.pid
                or ready["providerLoaded"] is not True
                or ready.get("sharedMediaEnabled", False) is not shared
            ):
                raise ValueError("owned native worker readiness refused")
            bridge = {
                "ENDPOINT": "localhost:" + str(ready["port"]),
                "CA_FILE": str(bridge_folder / "ca.pem"),
                "CLIENT_CERT_FILE": str(bridge_folder / "client.pem"),
                "CLIENT_KEY_FILE": str(bridge_folder / "client.key"),
            }
            auth = {
                "WSO_OIDC_ISSUER": issuer.origin,
                "WSO_OIDC_CLIENT_ID": "fixture-web",
                "WSO_OIDC_JWKS_URL": issuer.origin + "/jwks",
                "WSO_AUTH_EXCHANGE_KEY": secrets.token_urlsafe(48),
                "WSO_PUBLIC_ORIGIN": BASE_URL,
            }
            api = spawn_python(
                ["--api", str(folder)],
                api_environment(
                    roles,
                    auth,
                    bridge,
                    key,
                    folder / "ca.pem",
                    media=media,
                    shared=shared,
                ),
            )

            def close_api():
                settle_child(api, folder, "api", budget=20)
                result["apiSettled"] = True

            stack.callback(close_api)
            helper.wait_file(folder / "api-ready.json", api, time.monotonic() + 15)
            announcement = json.loads((folder / "api-ready.json").read_text())
            if (
                announcement["pid"] != api.pid
                or announcement.get("sharedMediaEnabled", False) is not shared
            ):
                raise ValueError("owned API readiness refused")
            api_origin = "https://localhost:" + str(announcement["port"])
            tls = ssl.create_default_context(cafile=str(folder / "ca.pem"))
            deadline = time.monotonic() + 10
            while True:
                if api.poll() is not None:
                    raise RuntimeError("owned API exited before HTTPS readiness")
                try:
                    with urlopen(
                        api_origin + "/health/live", context=tls, timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("owned API HTTPS readiness deadline")
                time.sleep(0.05)
            helper.write_private(
                path,
                {
                    "schemaVersion": 1,
                    "proofKind": "owned-local-device-native-pipeline",
                    "baseURL": BASE_URL,
                    "apiOrigin": api_origin,
                    "caFile": str(folder / "ca.pem"),
                    "certificateFile": str(folder / "server.pem"),
                    "keyFile": str(folder / "server.key"),
                    "tenantId": str(tenant),
                    "userId": str(fixed_owner),
                    "role": "OWNER",
                    "connections": links,
                    "nextAuth": {
                        key: auth[key]
                        for key in (
                            "WSO_OIDC_ISSUER",
                            "WSO_OIDC_CLIENT_ID",
                            "WSO_AUTH_EXCHANGE_KEY",
                        )
                    }
                    | {
                        "WSO_OIDC_CLIENT_SECRET": issuer_secret,
                        "WSO_FLOW_ENCRYPTION_KEY": secrets.token_urlsafe(32),
                    },
                }
                | shared_context(shared),
            )
            while not (folder / "runtime-shutdown.json").exists():
                if api.poll() is not None or worker.poll() is not None:
                    raise RuntimeError("owned local service exited")
                time.sleep(0.1)
    finally:
        if api is not None and api.poll() is None:
            settle_child(api, folder, "api")
        if worker_owner is not None and not worker_owner.confirmed:
            settle_shared_worker(worker_owner, folder)
        elif worker is not None and worker.poll() is None:
            settle_child(worker, folder, "worker")
        final = helper.source_snapshot() | {
            name: {"raw_sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
            for name in OWN
        }
        (evidence / "source-after.json").write_text(json.dumps(final, indent=2))
        result["sourceUnchanged"] = initial == final
        helper.remove_owned(folder, owner)
        result["contextRemoved"] = not folder.exists()
        (evidence / "resources.json").write_text(json.dumps(result, indent=2))
        if initial != final or any(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
            for name, digest in approved.items()
        ):
            raise RuntimeError("local browser source changed during proof")


def main():
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_BROWSER") != "1":
        print(
            "Local device browser fixture requires explicit activation.",
            file=sys.stderr,
        )
        return 2
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker_process(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--api":
        api_process(Path(sys.argv[2]))
    else:
        coordinate()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - private inputs/config never printed
        print("Local device browser fixture failed.", file=sys.stderr)
        raise SystemExit(1) from None
