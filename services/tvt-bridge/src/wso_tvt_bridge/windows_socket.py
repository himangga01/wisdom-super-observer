"""Private Windows raw transport supervisor. Import never loads vendor libraries."""

from __future__ import annotations

import ctypes as ct
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, NoReturn, cast

if TYPE_CHECKING:
    from .local_inventory_ipc import ParentAuthority

ROOT = Path(__file__).resolve().parents[4]
SDD = ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/"
OWNED = (
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py",
    "tests/contract/test_windows_socket.py",
    "docs/integrations/tvt-windows-socket-provider.md",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_provider.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_config.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py",
    "tests/contract/test_local_inventory_provider.py",
)
ABI_RECEIPT = SDD + "W04-windows-socket-abi-reviewed-root-receipt.json"
CODEC_RECEIPT = SDD + "W04-local-n9000-login-field-reviewed-root-receipt.json"
INVENTORY_RECEIPT = SDD + "W04-local-inventory-xml-Fix3-Fix1-reviewed-root-receipt.json"
LIVE_RECEIPT = (
    SDD + "W08-local-live-taskless-first-qualified-reviewed-root-receipt.json"
)
RUNTIME_RECEIPT = (
    SDD + "W04-windows-python-crypto-runtime-override-reviewed-root-receipt.json"
)
ACCEPTED_HASHES = {
    LIVE_RECEIPT: "8039ff625abdb21c34214014af129286ee8becc3ed102986920b7289a1ae0b75",
    ABI_RECEIPT: "75fc1cc60907375b7306c484562f22d6944f5ea92f5203201a629fb3f5e6abdf",
    CODEC_RECEIPT: "03f6adbac6499d8a48bc9342c5a29dadc3ec0fd871eb042559f27c1ffb2d971e",
    INVENTORY_RECEIPT: "2b8b158ef441ec374dc237c21157562c4fe02ce8fdcd76dadfe78cf8df686e9e",
    RUNTIME_RECEIPT: "77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d",
}
Mode = Literal["load", "initialize", "connect", "handshake", "inventory", "live"]
CAP = 16384
STAGES = frozenset(
    (
        "validated",
        "load",
        "initialize",
        "connect",
        "greeting",
        "handshake",
        "inventory",
        "live",
        "complete",
        "deadline",
    )
)
FAILURES = frozenset(
    (
        "none",
        "invalid",
        "linkage",
        "runtime",
        "connect",
        "greeting",
        "send",
        "rejected",
        "unsupported",
        "codec",
        "callback",
        "deadline",
        "custody",
        "denied",
    )
)


class ProviderError(ValueError):
    def __init__(self) -> None:
        super().__init__("Private Windows provider validation failed.")


class ProviderBusy(ProviderError):
    pass


def fail() -> NoReturn:
    raise ProviderError()


def json_object(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                fail()
            result[key] = value
        return result

    result: object = None
    if 0 < len(raw) <= CAP:
        try:
            result = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, UnicodeError):
            pass
    if type(result) is not dict:
        fail()
    return cast(dict[str, Any], result)


def identity(path: Path, *, directory: bool = False) -> tuple[int, int]:
    if not path.is_absolute() or any(p in (".", "..") for p in path.parts):
        fail()
    for part in (path, *path.parents):
        info = part.lstat()
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            fail()
    info = path.stat()
    if directory != stat.S_ISDIR(info.st_mode):
        fail()
    return info.st_dev, info.st_ino


def file_hash(path: Path) -> dict[str, str | int]:
    before = identity(path)
    raw = path.read_bytes()
    if identity(path) != before:
        fail()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read_json(path: Path) -> dict[str, Any]:
    before = identity(path)
    if not 0 < path.stat().st_size <= CAP:
        fail()
    raw = path.read_bytes()
    if identity(path) != before:
        fail()
    return json_object(raw)


def read_original(path: Path, expected: tuple[int, int], cap: int) -> bytes:
    if identity(path) != expected:
        fail()
    with path.open("rb") as source:
        info = os.fstat(source.fileno())
        if (info.st_dev, info.st_ino) != expected:
            fail()
        raw = source.read(cap + 1)
    if len(raw) > cap or identity(path) != expected:
        fail()
    return raw


def check_private_acl(path: Path) -> None:
    """Require a protected owner/SYSTEM-only DACL; no ACL mutation."""
    if os.name != "nt":
        fail()
    adv = ct.WinDLL("advapi32", use_last_error=True)
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ct.c_void_p
    kernel.LocalFree.argtypes = [ct.c_void_p]
    kernel.LocalFree.restype = ct.c_void_p
    kernel.CloseHandle.argtypes = [ct.c_void_p]
    kernel.CloseHandle.restype = ct.c_int
    adv.OpenProcessToken.argtypes = [ct.c_void_p, ct.c_uint32, ct.c_void_p]
    adv.OpenProcessToken.restype = ct.c_int
    adv.GetTokenInformation.argtypes = [
        ct.c_void_p,
        ct.c_int,
        ct.c_void_p,
        ct.c_uint32,
        ct.c_void_p,
    ]
    adv.GetTokenInformation.restype = ct.c_int
    adv.ConvertSidToStringSidW.argtypes = [ct.c_void_p, ct.c_void_p]
    adv.ConvertSidToStringSidW.restype = ct.c_int
    adv.GetNamedSecurityInfoW.argtypes = [
        ct.c_wchar_p,
        ct.c_int,
        ct.c_uint32,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
    ]
    adv.GetNamedSecurityInfoW.restype = ct.c_uint32
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ct.c_void_p,
        ct.c_uint32,
        ct.c_uint32,
        ct.c_void_p,
        ct.c_void_p,
    ]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = ct.c_int
    token, sidtext, descriptor, sddl = (ct.c_void_p() for _ in range(4))
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ct.byref(token)):
            fail()
        needed = ct.c_uint32()
        adv.GetTokenInformation(token, 1, None, 0, ct.byref(needed))
        if not 1 <= needed.value <= 4096:
            fail()
        buf = ct.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token, 1, buf, needed, ct.byref(needed)):
            fail()
        sid = ct.cast(buf, ct.POINTER(ct.c_void_p))[0]
        if not adv.ConvertSidToStringSidW(sid, ct.byref(sidtext)):
            fail()
        current = ct.wstring_at(sidtext)
        if adv.GetNamedSecurityInfoW(
            str(path), 1, 5, None, None, None, None, ct.byref(descriptor)
        ):
            fail()
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 5, ct.byref(sddl), None
        ):
            fail()
        validate_sddl(ct.wstring_at(sddl), current)
    finally:
        for ptr in (sidtext, descriptor, sddl):
            if ptr.value:
                kernel.LocalFree(ptr)
        if token.value:
            kernel.CloseHandle(token)


def validate_sddl(sddl: str, current_sid: str) -> None:
    match = re.fullmatch(r"O:([^:]+)D:(P(?:AI|AR)?)(\(.*\))", sddl)
    if match is None or match[1] not in (current_sid, "SY"):
        fail()
    aces = re.findall(r"\(([^()]*)\)", match[3])
    if not aces or "".join(f"({a})" for a in aces) != match[3]:
        fail()
    trustees: set[str] = set()
    for ace in aces:
        fields = ace.split(";")
        if (
            len(fields) != 6
            or fields[0] != "A"
            or fields[2] != "FA"
            or fields[3:5] != ["", ""]
            or fields[5] not in (current_sid, "SY")
            or re.fullmatch(r"(?:OI|CI|ID|IO|NP)*", fields[1]) is None
        ):
            fail()
        trustees.add(fields[5])
    if current_sid not in trustees:
        fail()


def protect_created_acl(path: Path) -> None:
    """Protect inherited restrictive ACL on a newly owned object only."""
    before = identity(path, directory=path.is_dir())
    adv = ct.WinDLL("advapi32", use_last_error=True)
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [
        ct.c_wchar_p,
        ct.c_int,
        ct.c_uint32,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
    ]
    adv.GetNamedSecurityInfoW.restype = ct.c_uint32
    adv.SetNamedSecurityInfoW.argtypes = [
        ct.c_wchar_p,
        ct.c_int,
        ct.c_uint32,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
    ]
    adv.SetNamedSecurityInfoW.restype = ct.c_uint32
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ct.c_void_p], ct.c_void_p
    descriptor, dacl = ct.c_void_p(), ct.c_void_p()
    try:
        if (
            adv.GetNamedSecurityInfoW(
                str(path), 1, 4, None, None, ct.byref(dacl), None, ct.byref(descriptor)
            )
            or not dacl.value
        ):
            fail()
        if adv.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None):
            fail()
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)
    if identity(path, directory=path.is_dir()) != before:
        fail()
    check_private_acl(path)


def select_trusted_nat2(country: str) -> tuple[bytes, int]:
    """Extract only NAT2 from the accepted selector using a synthetic context.

    These dummy Android fields are never passed to Windows NAT or persisted.
    Windows NAT owns its generated identity. This is resource selection only.
    """
    from wso_core.tvt.local_bootstrap import (
        TrustedAndroidRuntime,
        select_local_bootstrap,
    )

    profile = select_local_bootstrap(
        country_code=country,
        runtime=TrustedAndroidRuntime("/resource-selection-only", "unused", 0),
        attempt_branch="initial",
    )
    fields = json_object(profile.private_helper_json().encode())
    host, port = fields["nat2Host"], fields["nat2Port"]
    if (
        type(host) is not str
        or type(port) is not int
        or not 2 <= len(host.encode("ascii")) <= 63
        or not 1 <= port <= 65535
    ):
        fail()
    return host.encode("ascii"), port


@dataclass(frozen=True, slots=True, repr=False)
class PrivateRequest:
    mode: Mode
    country: str = ""
    serial: str = ""
    username: str = ""
    password: str = ""
    metadata_read_opt_in: bool = False
    live_read_opt_in: bool = False
    store_ref: str = ""
    channel_position: int = 0

    def __post_init__(self) -> None:
        if self.mode not in (
            "load",
            "initialize",
            "connect",
            "handshake",
            "inventory",
            "live",
        ):
            fail()
        if type(self.metadata_read_opt_in) is not bool or (
            self.metadata_read_opt_in != (self.mode in ("inventory", "live"))
        ):
            fail()
        if type(self.live_read_opt_in) is not bool or self.live_read_opt_in != (
            self.mode == "live"
        ):
            fail()
        if self.mode == "live":
            if (
                type(self.store_ref) is not str
                or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.store_ref) is None
                or type(self.channel_position) is not int
                or not 1 <= self.channel_position <= 256
            ):
                fail()
        elif (
            self.store_ref
            or type(self.channel_position) is not int
            or self.channel_position != 0
        ):
            fail()
        if self.mode in ("connect", "handshake", "inventory", "live"):
            if (
                type(self.serial) is not str
                or re.fullmatch(r"[a-zA-Z0-9]{1,63}", self.serial) is None
            ):
                fail()
            select_trusted_nat2(self.country)
            object.__setattr__(self, "serial", self.serial.upper())
        elif self.serial or self.country:
            fail()
        if self.mode in ("handshake", "inventory", "live"):
            from wso_core.tvt.local_n9000 import Credentials

            Credentials(self.username, self.password)
        elif self.username or self.password:
            fail()


@dataclass(slots=True)
class SafeResult:
    generation: str
    stage: str = "validated"
    failure: str = "none"
    loaded: bool = False
    initialized: bool = False
    transport: bool = False
    greeting_bytes: int = 0
    connect_status: int = 0
    native_error: int = 0
    send_count: int = 0
    received_bytes: int = 0
    reply_accepted: bool = False
    proof_verified: bool = False
    key_extracted: bool = False
    cleanup_attempted: bool = False
    quiescence_verified: bool = False
    authorized: bool = False
    live: bool = False
    reaped: bool = False
    runtime_substitutions: int = 0
    development_debug_only: bool = True
    production_ready: bool = False
    inventory_queries_sent: int = 0
    inventory_replies: int = 0
    inventory_complete: bool = False
    serial_matched: bool = False
    channel_count: int = 0
    channels_complete: bool = False
    user_observed: bool = False
    permissions_complete: bool = False
    inventory_availability: str = "unavailable"
    metadata_branch_complete: bool = False
    permissions_availability: str = "unavailable"
    capture_status: str = "not_requested"
    live_open_attempts: int = 0
    live_close_attempts: int = 0
    live_open_ack: bool = False
    live_received_bytes: int = 0
    live_payload_received: int = 0
    live_frames_validated: int = 0
    pre_key_frames: int = 0
    live_frames: int = 0
    live_bytes: int = 0
    live_codec: str = "unavailable"
    live_width: int = 0
    live_height: int = 0

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True).encode()


def parse_result(raw: bytes, generation: str) -> SafeResult:
    data = json_object(raw)
    defaults = asdict(SafeResult(generation))
    if set(data) != set(defaults) or data["generation"] != generation:
        fail()
    for key, default in defaults.items():
        if type(data[key]) is not type(default):
            fail()
    if (
        data["stage"] not in STAGES
        or data["failure"] not in FAILURES
        or not 0 <= data["greeting_bytes"] <= 64
        or data["connect_status"] not in (-1, 0, 1)
        or not 0 <= data["native_error"] <= 0xFFFFFFFF
        or not -(2**31) <= data["send_count"] < 2**31
        or not 0 <= data["received_bytes"] <= 65536
        or any(
            data[k]
            for k in ("authorized", "live", "quiescence_verified", "production_ready")
        )
        or not data["development_debug_only"]
        or data["runtime_substitutions"] not in (0, 1, 2)
        or (
            (data["proof_verified"] or data["key_extracted"])
            and not data["reply_accepted"]
        )
        or (data["reply_accepted"] and not data["transport"])
        or (data["transport"] and data["connect_status"] != 1)
        or (data["greeting_bytes"] and not data["transport"])
        or (data["stage"] == "inventory" and not data["reply_accepted"])
        or (
            data["inventory_queries_sent"]
            and (
                data["stage"] not in ("inventory", "live", "complete")
                or not all(data[k] for k in ("loaded", "initialized", "key_extracted"))
                or data["greeting_bytes"] != 64
                or data["send_count"] <= 0
                or (
                    data["stage"] == "complete" and not data["metadata_branch_complete"]
                )
            )
        )
        or not 0 <= data["inventory_replies"] <= data["inventory_queries_sent"] <= 4
        or not 0 <= data["channel_count"] <= 256
        or (data["inventory_queries_sent"] and not data["reply_accepted"])
        or data["inventory_availability"] not in ("unavailable", "identity_available")
        or (
            data["inventory_complete"]
            and (
                data["inventory_replies"] != 4
                or not data["metadata_branch_complete"]
                or not all(
                    data[k]
                    for k in (
                        "serial_matched",
                        "channels_complete",
                        "user_observed",
                        "permissions_complete",
                        "reply_accepted",
                    )
                )
                or data["inventory_availability"] != "identity_available"
            )
        )
        or (
            not data["metadata_branch_complete"]
            and (
                any(
                    data[k]
                    for k in (
                        "serial_matched",
                        "channel_count",
                        "channels_complete",
                        "user_observed",
                        "permissions_complete",
                    )
                )
                or data["inventory_availability"] != "unavailable"
            )
        )
    ):
        fail()
    if data["permissions_availability"] not in (
        "unavailable",
        "observed",
        "not_requested_no_group",
    ):
        fail()
    if data["metadata_branch_complete"]:
        no_group = data["permissions_availability"] == "not_requested_no_group"
        if (
            data["inventory_replies"] != (3 if no_group else 4)
            or data["inventory_queries_sent"] != data["inventory_replies"]
            or data["permissions_complete"] == no_group
            or data["inventory_complete"] == no_group
            or data["permissions_availability"] == "unavailable"
            or not all(
                data[k]
                for k in ("serial_matched", "channels_complete", "user_observed")
            )
            or data["inventory_availability"] != "identity_available"
        ):
            fail()
        if data["capture_status"] == "not_requested" and (
            data["stage"] != "complete" or data["failure"] != "none"
        ):
            fail()
    elif data["permissions_availability"] != "unavailable":
        fail()
    if (
        data["capture_status"] not in ("not_requested", "complete", "failed")
        or not 0 <= data["live_close_attempts"] <= data["live_open_attempts"] <= 1
        or not 0 <= data["live_received_bytes"] <= 8 << 20
        or not 0 <= data["live_bytes"] <= data["live_payload_received"] <= 4 << 20
        or not 0 <= data["live_frames"] <= 4
        or not 0 <= data["pre_key_frames"] <= data["live_frames_validated"] <= 64
        or data["live_frames"] + data["pre_key_frames"] > data["live_frames_validated"]
        or data["live_codec"] not in ("unavailable", "h264", "h265")
        or not 0 <= data["live_width"] <= 32767
        or not 0 <= data["live_height"] <= 32767
        or (data["live_open_attempts"] and not data["metadata_branch_complete"])
        or (data["live_open_ack"] and data["live_open_attempts"] != 1)
    ):
        fail()
    if data["capture_status"] == "failed" and data["failure"] == "none":
        fail()
    if data["live_frames"]:
        if (
            data["live_codec"] == "unavailable"
            or not data["live_width"]
            or not data["live_height"]
        ):
            fail()
    elif (
        data["live_bytes"]
        or data["live_width"]
        or data["live_height"]
        or data["live_codec"] != "unavailable"
    ):
        fail()
    if data["capture_status"] == "complete" and (
        data["live_frames"] != 4
        or data["live_close_attempts"] != 1
        or data["failure"] != "none"
        or data["stage"] != "complete"
    ):
        fail()
    if data["capture_status"] == "not_requested" and any(
        data[k]
        for k in (
            "live_open_attempts",
            "live_close_attempts",
            "live_open_ack",
            "live_received_bytes",
            "live_payload_received",
            "live_frames_validated",
            "live_frames",
            "live_bytes",
        )
    ):
        fail()
    return SafeResult(**data)


@dataclass(frozen=True, slots=True, repr=False)
class ProviderConfig:
    bundle: Path
    staging: Path
    review_receipt: Path
    deadline_seconds: float = 30
    runtime_receipt: Path | None = None

    def __post_init__(self) -> None:
        if (
            type(self.deadline_seconds) not in (int, float)
            or not 1 <= self.deadline_seconds <= 120
            or not self.bundle.is_absolute()
            or not self.staging.is_absolute()
            or not self.review_receipt.is_absolute()
            or not str(self.bundle).isascii()
            or not str(self.staging).isascii()
            or (
                self.runtime_receipt is not None
                and not self.runtime_receipt.is_absolute()
            )
        ):
            fail()


def verify_review(config: ProviderConfig) -> list[dict[str, Any]]:
    """Root receipt pins owned service files and accepted source/runtime dependencies."""
    receipt = read_json(config.review_receipt)
    dependencies: dict[str, Any] = {}
    for path, status in (
        (ABI_RECEIPT, "ACCEPTED_WINDOWS_SOCKET_ABI_ROOT_REVIEW"),
        (CODEC_RECEIPT, "SOURCE_ACCEPTED_UNPUBLISHED"),
        (INVENTORY_RECEIPT, "SOURCE_ACCEPTED_UNPUBLISHED"),
        (LIVE_RECEIPT, "SOURCE_ACCEPTED_WITH_EVIDENCE_QUALIFICATION_UNPUBLISHED"),
    ):
        if file_hash(ROOT / path)["sha256"] != ACCEPTED_HASHES[path]:
            fail()
        accepted = read_json(ROOT / path)
        if accepted.get("status") != status:
            fail()
        for relative, expected in accepted["files"].items():
            if file_hash(ROOT / relative) != expected:
                fail()
        for relative, expected in accepted.get("dependencies", {}).items():
            if file_hash(ROOT / relative) != expected:
                fail()
            dependencies[relative] = expected
        dependencies[path] = file_hash(ROOT / path)
    for path in (
        "packages/core/src/wso_core/tvt/local_bootstrap.py",
        "packages/core/src/wso_core/tvt/device_qr.py",
        "packages/core/src/wso_core/tvt/local_credentials.py",
        "packages/core/src/wso_core/tvt/local_service.py",
        "packages/contracts/src/wso_contracts/tvt/local_device.py",
    ):
        dependencies[path] = file_hash(ROOT / path)
    dependencies[RUNTIME_RECEIPT] = file_hash(ROOT / RUNTIME_RECEIPT)
    if dependencies[RUNTIME_RECEIPT]["sha256"] != ACCEPTED_HASHES[RUNTIME_RECEIPT]:
        fail()
    if (
        set(receipt)
        != {"status", "files", "dependencies", "critical", "important", "minor"}
        or receipt["status"] != "ACCEPTED_WINDOWS_NATIVE_PROVIDER_ROOT_REVIEW"
        or any(
            type(receipt[k]) is not int or receipt[k] != 0
            for k in ("critical", "important", "minor")
        )
        or receipt["files"] != {p: file_hash(ROOT / p) for p in OWNED}
        or receipt["dependencies"] != dependencies
    ):
        fail()
    return cast(list[dict[str, Any]], read_json(ROOT / ABI_RECEIPT)["bundle"])


def runtime_override(config: ProviderConfig) -> dict[str, dict[str, Any]]:
    if config.runtime_receipt is None:
        return {}
    check_private_acl(config.runtime_receipt)
    if file_hash(config.runtime_receipt)["sha256"] != ACCEPTED_HASHES[RUNTIME_RECEIPT]:
        fail()
    return cast(
        dict[str, dict[str, Any]], read_json(config.runtime_receipt)["allowedOverrides"]
    )


def validate_bundle(
    directory: Path, manifest: list[dict[str, Any]]
) -> dict[str, tuple[int, int]]:
    identity(directory, directory=True)
    if not str(directory).isascii() or len(manifest) != 14:
        fail()
    expected = {row["name"]: row for row in manifest}
    if len(expected) != 14 or {p.name for p in directory.iterdir()} != set(expected):
        fail()
    retained: dict[str, tuple[int, int]] = {}
    for name, row in expected.items():
        if type(name) is not str or re.fullmatch(r"[A-Za-z0-9_]+\.dll", name) is None:
            fail()
        path = directory / name
        retained[name] = identity(path)
        if file_hash(path) != {k: row[k] for k in ("bytes", "sha256")}:
            fail()
        with path.open("rb") as stream:
            header = stream.read(4096)
        if header[:2] != b"MZ" or len(header) < 64:
            fail()
        offset = int.from_bytes(header[60:64], "little")
        if (
            offset + 26 > len(header)
            or header[offset : offset + 4] != b"PE\0\0"
            or header[offset + 4 : offset + 6] != b"\x64\x86"
            or header[offset + 24 : offset + 26] != b"\x0b\x02"
        ):
            fail()
    return retained


def direct_interpreter() -> tuple[Path, Path]:
    """Admit only an existing repository infrastructure venv and its base."""
    venv = Path(sys.prefix)
    if os.name != "nt" or venv not in (
        ROOT / ".venv",
        ROOT / ".superpowers/runtime/windows-media-decode/venv",
    ):
        fail()
    cfg = venv / "pyvenv.cfg"
    raw = read_original(cfg, identity(cfg), 4096).decode("utf-8")
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key in fields:
            fail()
        fields[key] = value
    base = Path(fields.get("home", ""))
    direct = base / "python.exe"
    site = venv / "Lib/site-packages"
    if (
        not base.is_absolute()
        or fields.get("include-system-site-packages") != "false"
        or os.path.normcase(str(base)) != os.path.normcase(sys.base_prefix)
        or os.path.normcase(str(direct))
        != os.path.normcase(str(getattr(sys, "_base_executable", "")))
    ):
        fail()
    identity(direct)
    identity(site, directory=True)
    return direct, site


# stdlib-only admission gate. -I -S excludes cwd, environment, user site and
# all .pth/sitecustomize execution. No application/native imports before Job.
BOOTSTRAP = """import sys, ctypes as c
if sys.stdin.buffer.read(2) != b'J\\n':
    raise SystemExit(91)
k = c.WinDLL('kernel32', use_last_error=True)
k.GetCurrentProcess.restype = c.c_void_p
k.IsProcessInJob.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(c.c_int)]
k.IsProcessInJob.restype = c.c_int
inside = c.c_int()
if not k.IsProcessInJob(k.GetCurrentProcess(), None, c.byref(inside)) or not inside.value:
    raise SystemExit(92)
if len(sys.argv) != 4:
    raise SystemExit(93)
sys.path[:0] = sys.argv[1:]
from wso_tvt_bridge.windows_socket_worker import main
raise SystemExit(main())
"""


def worker_command() -> list[str]:
    direct, site = direct_interpreter()
    sources = (ROOT / "services/tvt-bridge/src", ROOT / "packages/core/src")
    for path in sources:
        identity(path, directory=True)
    return [
        str(direct),
        "-I",
        "-S",
        "-c",
        BOOTSTRAP,
        *(str(p) for p in sources),
        str(site),
    ]


class JobBasicLimits(ct.Structure):
    _fields_ = [
        ("process_time", ct.c_int64),
        ("job_time", ct.c_int64),
        ("flags", ct.c_uint32),
        ("min_working", ct.c_size_t),
        ("max_working", ct.c_size_t),
        ("active_processes", ct.c_uint32),
        ("affinity", ct.c_size_t),
        ("priority", ct.c_uint32),
        ("scheduling", ct.c_uint32),
    ]


class JobExtendedLimits(ct.Structure):
    _fields_ = [
        ("basic", JobBasicLimits),
        ("io", ct.c_uint64 * 6),
        ("process_memory", ct.c_size_t),
        ("job_memory", ct.c_size_t),
        ("peak_process_memory", ct.c_size_t),
        ("peak_job_memory", ct.c_size_t),
    ]


class OwnedJob:
    """One original interpreter; no descendants, breakaway or process lookup."""

    def __init__(self) -> None:
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        k = self.kernel
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = (
            [ct.c_void_p, ct.c_wchar_p],
            ct.c_void_p,
        )
        k.SetInformationJobObject.argtypes = [
            ct.c_void_p,
            ct.c_int,
            ct.c_void_p,
            ct.c_uint32,
        ]
        k.SetInformationJobObject.restype = ct.c_int
        k.AssignProcessToJobObject.argtypes = [ct.c_void_p, ct.c_void_p]
        k.AssignProcessToJobObject.restype = ct.c_int
        k.IsProcessInJob.argtypes = [ct.c_void_p, ct.c_void_p, ct.POINTER(ct.c_int)]
        k.IsProcessInJob.restype = ct.c_int
        k.CloseHandle.argtypes, k.CloseHandle.restype = [ct.c_void_p], ct.c_int
        self.handle: Any = None

    def create(self) -> None:
        if self.handle is not None:
            fail()
        k = self.kernel
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            self.handle = None
            fail()
        try:
            limits = JobExtendedLimits()
            limits.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
            limits.basic.active_processes = 1
            if not k.SetInformationJobObject(
                self.handle, 9, ct.byref(limits), ct.sizeof(limits)
            ):
                fail()
        except BaseException:
            self.close()
            raise

    @property
    def closed(self) -> bool:
        return self.handle is None

    def admit(self, child: subprocess.Popen[bytes]) -> None:
        handle = getattr(child, "_handle", None)  # retained Popen Windows handle
        inside = ct.c_int()
        if (
            self.closed
            or handle is None
            or not self.kernel.AssignProcessToJobObject(self.handle, int(handle))
            or not self.kernel.IsProcessInJob(
                int(handle), self.handle, ct.byref(inside)
            )
            or not inside.value
        ):
            fail()

    def close(self) -> None:
        if self.handle is not None:
            if not self.kernel.CloseHandle(self.handle):
                fail()
            self.handle = None


@dataclass(slots=True, repr=False)
class ChildOwner:
    child: subprocess.Popen[bytes] | None
    writer: threading.Thread | None
    outputs: tuple[BinaryIO, BinaryIO]
    kill_attempted: bool = False
    confirmed: bool = False
    writer_start_attempted: bool = False
    job: OwnedJob | None = None
    service: ParentAuthority | None = None
    _kill_claim: dict[str, object] = field(default_factory=dict)

    def request_stop(self) -> None:
        child = self.child
        if child is not None and not self.kill_attempted and child.poll() is None:
            token = object()
            if self._kill_claim.setdefault("kill", token) is not token:
                return
            self.kill_attempted = True
            try:
                child.kill()
            except BaseException:  # noqa: BLE001 -- retain original handle for wait
                self.confirmed = False

    def finish(self, timeout: float = 1) -> bool:
        try:
            child, writer = self.child, self.writer
            if child is not None:
                self.request_stop()
                child.wait(timeout=timeout)
            if self.job is not None:
                self.job.close()
            if writer is not None and writer.ident is not None:
                writer.join(timeout=timeout)
            elif writer is not None and self.writer_start_attempted:
                # Thread.start interrupted before its start event: no proof that
                # it did not acquire an OS thread. Retain and fence until known.
                return False
            if writer is not None and writer.is_alive():
                return False
            if child is not None and child.stdin is not None and not child.stdin.closed:
                child.stdin.close()
            for output in self.outputs:
                if not output.closed:
                    output.close()
            if self.service is not None:
                if not self.service.close(timeout):
                    return False
                self.service = None
            self.confirmed = True
            return True
        except BaseException:  # noqa: BLE001 -- every cleanup phase preserves custody
            return False

    def passive_wait(self) -> None:
        """Keep original ownership; never issue repeated/discovered process kills."""
        while not self.confirmed:
            try:
                if not self.finish(timeout=0.5):
                    time.sleep(0.05)
            except BaseException:  # noqa: BLE001,S112 -- retain passive ownership
                continue


PENDING_OWNERS: list[ChildOwner] = []
ATTEMPT_LOCK = threading.Lock()


@contextmanager
def attempt_scope(*, blocking: bool) -> Iterator[None]:
    if not ATTEMPT_LOCK.acquire(blocking=blocking):
        raise ProviderBusy()
    try:
        yield
    finally:
        ATTEMPT_LOCK.release()


class WindowsSocketProvider:
    def __init__(self) -> None:
        self.owner: ChildOwner | None = None

    def run(
        self,
        config: ProviderConfig,
        request: PrivateRequest,
        *,
        service: ParentAuthority | None = None,
        current: Callable[[], bool] | None = None,
    ) -> SafeResult:
        if service is not None and (request.mode != "inventory" or current is None):
            fail()
        with attempt_scope(blocking=service is None):
            if (self.owner is not None and not self.owner.confirmed) or any(
                not owner.confirmed for owner in PENDING_OWNERS
            ):
                fail()
            result = SafeResult(uuid.uuid4().hex)
            outputs: tuple[BinaryIO, BinaryIO] | None = None
            generation: Path | None = None
            generation_id: tuple[int, int] | None = None
            try:
                if service is not None:
                    assert current is not None
                    if not service.check(current):
                        fail()
                manifest = verify_review(config)
                runtime_override(config)
                check_private_acl(config.review_receipt)
                validate_bundle(config.bundle, manifest)
                check_private_acl(config.bundle)
                for row in manifest:
                    check_private_acl(config.bundle / row["name"])
                identity(config.staging, directory=True)
                check_private_acl(config.staging)
                if config.staging.is_relative_to(ROOT):
                    fail()
                staging_id = identity(config.staging, directory=True)
                generation = config.staging / result.generation
                generation.mkdir()
                protect_created_acl(generation)
                if identity(config.staging, directory=True) != staging_id:
                    fail()
                generation_id = identity(generation, directory=True)
                receipt = generation / "result.json"
                receipt.touch(exist_ok=False)
                receipt_id = identity(receipt)
                protect_created_acl(receipt)
                outputs = cast(
                    tuple[BinaryIO, BinaryIO],
                    tuple(
                        (
                            Path(os.devnull).open("wb")  # noqa: SIM115 -- original ChildOwner retains and closes streams
                            if service is not None
                            else (generation / name).open("xb")
                        )
                        for name in ("native.stdout", "native.stderr")
                    ),
                )
                if service is None:
                    for name in ("native.stdout", "native.stderr"):
                        protect_created_acl(generation / name)
                packet_data: dict[str, Any] = {
                    "config": {
                        "bundle": str(config.bundle),
                        "staging": str(generation),
                        "review_receipt": str(config.review_receipt),
                        "deadline_seconds": config.deadline_seconds,
                        "runtime_receipt": str(config.runtime_receipt)
                        if config.runtime_receipt
                        else None,
                    },
                    "request": asdict(request),
                    "generation": result.generation,
                    "receipt_identity": list(receipt_id),
                    "generation_identity": list(generation_id),
                    "job_admitted": True,
                    "deadline": service.deadline
                    if service is not None
                    else time.monotonic() + config.deadline_seconds,
                    "service_authority_handle": None,
                }
                deadline = float(packet_data["deadline"])
                # Publish an owner BEFORE acquiring a child or constructing its
                # writer. Every subsequent failure reaches this original owner.
                self.owner = ChildOwner(None, None, outputs)
                PENDING_OWNERS.append(self.owner)
                if service is not None:
                    assert current is not None
                    self.owner.service = service
                    if not service.check(current):
                        fail()
                    service.bind(result.generation)
                command = worker_command()
                self.owner.job = OwnedJob()
                self.owner.job.create()
                self.owner.child = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=outputs[0],
                    stderr=outputs[1],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                    },
                    cwd=str(generation),
                    shell=False,
                )
                child = self.owner.child
                if service is not None:
                    service.start_watchdog(self.owner.request_stop)
                self.owner.job.admit(child)
                if service is not None:
                    packet_data["service_authority_handle"] = service.duplicate_to(
                        child
                    )
                    assert current is not None
                    if not service.check(current):
                        fail()
                packet = json.dumps(packet_data).encode()
                if len(packet) > CAP:
                    fail()

                def send_input() -> None:
                    try:
                        assert child.stdin is not None
                        child.stdin.write(b"J\n" + packet)
                        child.stdin.flush()
                    except BaseException:  # noqa: BLE001 -- private writer boundary
                        return
                    finally:
                        if child.stdin is not None:
                            try:
                                child.stdin.close()
                            except BaseException:  # noqa: BLE001 -- no thread diagnostics
                                return

                self.owner.writer = threading.Thread(target=send_input, daemon=False)
                self.owner.writer_start_attempted = True
                self.owner.writer.start()
                while time.monotonic() < deadline:
                    if service is not None:
                        assert current is not None
                        if not service.tick(current):
                            result.failure = (
                                "deadline"
                                if service.failure == "deadline"
                                else "denied"
                            )
                            break
                    if (
                        identity(generation, directory=True) != generation_id
                        or identity(receipt) != receipt_id
                    ):
                        fail()
                    if receipt.stat().st_size:
                        try:
                            result = parse_result(
                                read_original(receipt, receipt_id, CAP),
                                result.generation,
                            )
                            # The private pipe and structural receipt are separate
                            # transports. Drain the already-published observation
                            # before accepting a successful receipt, within the
                            # same absolute deadline and caller authority checks.
                            if (
                                service is not None
                                and result.failure == "none"
                                and service.observation is None
                            ):
                                time.sleep(0.005)
                                continue
                            break
                        except ProviderError:
                            # The worker writes one bounded receipt to the original file.
                            pass
                    if child.poll() is not None:
                        result.failure = "runtime"
                        break
                    time.sleep(0.02)
                else:
                    result.stage, result.failure = "deadline", "deadline"
            except BaseException:  # noqa: BLE001 -- retain child on interruptions
                result.failure = "custody"
            finally:
                if self.owner is not None:
                    result.reaped = self.owner.finish()
                if outputs is not None and (
                    self.owner is None or self.owner.outputs is not outputs
                ):
                    for output in outputs:
                        output.close()
            if (
                request.mode == "live"
                and result.reaped
                and generation is not None
                and generation_id is not None
            ):
                try:
                    if identity(generation, directory=True) != generation_id:
                        fail()
                    owner_path = generation / "live-owner.json"
                    owner_path.touch(exist_ok=False)
                    owner_id = identity(owner_path)
                    protect_created_acl(owner_path)
                    with owner_path.open("r+b") as output:
                        info = os.fstat(output.fileno())
                        if (info.st_dev, info.st_ino) != owner_id:
                            fail()
                        output.write(result.to_json())
                        output.flush()
                    if (
                        identity(owner_path) != owner_id
                        or identity(generation, directory=True) != generation_id
                    ):
                        fail()
                except BaseException:  # noqa: BLE001 -- original child already reaped; custody proof withheld
                    result.failure = "custody"
                    if result.capture_status == "complete":
                        result.capture_status = "failed"
            return result


def cli_lifetime(provider: WindowsSocketProvider) -> None:
    if provider.owner is not None and not provider.owner.confirmed:
        provider.owner.passive_wait()


def main() -> int:
    provider = WindowsSocketProvider()
    result = SafeResult(uuid.uuid4().hex, failure="invalid")
    try:
        packet = json_object(sys.stdin.buffer.read(CAP + 1))
        if set(packet) != {"config", "request"}:
            fail()
        config = packet["config"]
        request = packet["request"]
        result = provider.run(
            ProviderConfig(
                Path(config["bundle"]),
                Path(config["staging"]),
                Path(config["review_receipt"]),
                config["deadline_seconds"],
                Path(config["runtime_receipt"])
                if config.get("runtime_receipt")
                else None,
            ),
            PrivateRequest(**request),
        )
    except BaseException:  # noqa: BLE001 -- fixed safe boundary also on interruptions
        result.failure = "invalid"
    finally:
        # Outer finally runs even if parsing/run is interrupted. Passive ownership
        # cannot be skipped by a BaseException before the normal CLI return path.
        cli_lifetime(provider)
    sys.stdout.buffer.write(result.to_json() + b"\n")
    return 0 if result.failure == "none" and result.reaped else 1


if __name__ == "__main__":
    raise SystemExit(main())
