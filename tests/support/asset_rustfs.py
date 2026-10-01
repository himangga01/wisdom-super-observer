"""Pinned RustFS fixture primitives. No runtime acceptance follows from imports."""

from __future__ import annotations

import calendar
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
import subprocess
import threading
import time
import zipfile
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import httpx

SERVER_VERSION = "1.0.0"
SERVER_COMMIT = "d47f54bfb2f39f48bd1adda334bd27e151fe85b8"
ARCHIVE_URL = "https://github.com/rustfs/rustfs/releases/download/1.0.0/rustfs-linux-x86_64-musl-v1.0.0.zip"
ARCHIVE_SIZE = 194469895
ARCHIVE_SHA = "c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8"
SERVER_SIZE = 264596736
SERVER_SHA = "222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad"
LIMIT = 65536
PAB = dict.fromkeys(
    (
        "BlockPublicAcls",
        "IgnorePublicAcls",
        "BlockPublicPolicy",
        "RestrictPublicBuckets",
    ),
    True,
)
OWNER_ID = "c19050dbcee97fda828689dda99097a6321af2248fa760517237346e5d9c8a66"
FIXED_ENV = {
    "RUSTFS_CONSOLE_ENABLE": "false",
    "RUSTFS_REGION": "us-east-1",
    **{
        f"RUSTFS_OBS_{name}_ENDPOINT": ""
        for name in ("TRACE", "METRIC", "LOG", "PROFILING")
    },
    "RUSTFS_OBS_ENDPOINT": "",
    **{
        f"RUSTFS_OBS_{name}_EXPORT_ENABLED": "false"
        for name in ("TRACES", "METRICS", "LOGS", "PROFILING")
    },
    "RUSTFS_OBS_ENVIRONMENT": "production",
    "RUSTFS_OBS_LOGGER_LEVEL": "error",
    "RUSTFS_OBS_USE_STDOUT": "false",
    "RUSTFS_OBS_LOG_STDOUT_ENABLED": "false",
    "RUSTFS_OBS_LOG_DIRECTORY": "/tmp/logs",
    "RUSTFS_OBS_LOG_FILENAME": "rustfs.log",
}
ENTITIES = frozenset(
    (
        "policies",
        "users",
        "groups",
        "serviceAccounts",
        "userPolicies",
        "groupPolicies",
        "stsPolicies",
    )
)
MAPS = (
    "policies",
    "users",
    "groups",
    "svcaccts",
    "user_mappings",
    "group_mappings",
    "stsuser_mappings",
)
POLICY_NAMES = {"gateway": "wso-gateway", "cleanup": "wso-maintenance"}


class PhaseCutoff(RuntimeError):
    def __init__(self):
        super().__init__("owned RustFS phase cutoff")


class NativeMetadataFailure(RuntimeError):
    pass


class PhaseBudget:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.outer = clock() + 720
        self.cutoff = self.outer
        self.phase = None

    def check(self):
        if self.clock() >= min(self.cutoff, self.outer):
            raise PhaseCutoff() from None

    def enter(self, phase):
        now = self.clock()
        if now >= min(self.cutoff, self.outer):
            raise PhaseCutoff() from None
        expected = {None: "A", "A": "B", "B": "C"}.get(self.phase)
        if phase != expected:
            raise RuntimeError("invalid owned RustFS phase transition")
        self.phase = phase
        self.cutoff = min(self.outer, now + (360 if phase == "A" else 180))

    def allowance(self, cap):
        now = self.clock()
        if now >= min(self.cutoff, self.outer):
            raise PhaseCutoff() from None
        return min(cap, self.cutoff - now, self.outer - now)


def credentials():
    result = {
        name: (secrets.token_hex(10), secrets.token_hex(20))
        for name in ("bootstrap", "gateway", "cleanup")
    }
    validate_credentials(result)
    return result


def validate_credentials(value):
    if type(value) is not dict or set(value) != {"bootstrap", "gateway", "cleanup"}:
        raise RuntimeError("invalid owned RustFS credentials")
    for pair in value.values():
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or not re.fullmatch(r"[0-9a-f]{20}", pair[0])
            or not re.fullmatch(r"[0-9a-f]{40}", pair[1])
        ):
            raise RuntimeError("invalid owned RustFS credentials")
    if len({pair[0] for pair in value.values()}) != 3:
        raise RuntimeError("invalid owned RustFS credentials")


def environment_bytes(value):
    validate_credentials(value)
    fields = {
        "RUSTFS_ACCESS_KEY": value["bootstrap"][0],
        "RUSTFS_SECRET_KEY": value["bootstrap"][1],
        **FIXED_ENV,
    }
    return "".join(f"{key}={item}\n" for key, item in fields.items()).encode("ascii")


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    def visit(item, depth=0):
        if depth > 16:
            raise ValueError
        if isinstance(item, dict):
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is float and not math.isfinite(item):
            raise ValueError

    try:
        if (
            type(payload) is not bytes
            or len(payload) > LIMIT
            or payload.startswith(b"\xef\xbb\xbf")
        ):
            raise ValueError
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        visit(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise RuntimeError("invalid bounded native JSON") from None


def validate_download_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise RuntimeError("unapproved official RustFS download URL") from None


def download_server(work, budget):
    """Download only in explicit owned Linux fixture; never execute this here."""
    archive = work / "release.zip"
    cutoff = min(budget.cutoff, budget.outer, time.monotonic() + 180)
    current = ARCHIVE_URL
    try:
        with httpx.Client(trust_env=False, follow_redirects=False) as client:
            for _ in range(7):
                validate_download_url(current)
                if time.monotonic() >= cutoff:
                    raise RuntimeError("official RustFS download cutoff")
                with client.stream(
                    "GET",
                    current,
                    timeout=min(20, budget.allowance(20), cutoff - time.monotonic()),
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        current = response.headers.get("location", "")
                        continue
                    if response.status_code != 200:
                        raise RuntimeError("official RustFS download refused")
                    size, digest = 0, hashlib.sha256()
                    descriptor = os.open(
                        archive,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    with os.fdopen(descriptor, "wb") as output:
                        for chunk in response.iter_bytes(65536):
                            budget.check()
                            if time.monotonic() >= cutoff:
                                raise RuntimeError("official RustFS download cutoff")
                            size += len(chunk)
                            if size > ARCHIVE_SIZE:
                                raise RuntimeError(
                                    "official RustFS archive size differs"
                                )
                            digest.update(chunk)
                            output.write(chunk)
                            budget.check()
                            if time.monotonic() >= cutoff:
                                raise RuntimeError("official RustFS download cutoff")
                    if size != ARCHIVE_SIZE or digest.hexdigest() != ARCHIVE_SHA:
                        raise RuntimeError("official RustFS archive identity differs")
                    break
            else:
                raise RuntimeError("official RustFS redirect limit")
        budget.check()
        if time.monotonic() >= cutoff:
            raise RuntimeError("official RustFS download cutoff")
        return extract_server(archive, work / "rustfs", budget)
    except Exception:  # noqa: BLE001 -- no download URLs or exception text escape
        raise RuntimeError("owned official RustFS acquisition failed") from None


def regular_entries(bundle, expected, *, mode=None):
    entries = bundle.infolist()
    if len(entries) != len(expected) or {item.filename for item in entries} != set(
        expected
    ):
        raise RuntimeError("native ZIP member set differs")
    for item in entries:
        member_mode = item.external_attr >> 16
        if (
            item.flag_bits & 1
            or item.create_system != 3
            or not stat.S_ISREG(member_mode)
            or (mode is not None and member_mode != mode)
        ):
            raise RuntimeError("native ZIP member type differs")
    return entries


def extract_server(archive, target, budget):
    try:
        with zipfile.ZipFile(archive) as bundle:
            regular_entries(bundle, {"rustfs", "rustfs-cli"}, mode=0o100755)
            entry = bundle.getinfo("rustfs")
            if entry.file_size != SERVER_SIZE:
                raise ValueError
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            size, digest = 0, hashlib.sha256()
            with os.fdopen(descriptor, "wb") as output, bundle.open(entry) as source:
                while chunk := source.read(65536):
                    budget.check()
                    size += len(chunk)
                    if size > SERVER_SIZE:
                        raise ValueError
                    digest.update(chunk)
                    output.write(chunk)
                    budget.check()
            budget.check()
            if size != SERVER_SIZE or digest.hexdigest() != SERVER_SHA:
                raise ValueError
            return target
    except Exception:  # noqa: BLE001 -- archive names, paths, and data stay private
        raise RuntimeError("official RustFS server identity differs") from None


def verify_version(output):
    try:
        if type(output) is bytes:
            output = output.decode("utf-8")
        if (
            type(output) is not str
            or len(output.encode("utf-8")) > 16384
            or not re.fullmatch(r"[\x20-\x7e\n]+", output)
            or output.endswith("\n\n\n")
        ):
            raise ValueError
        lines = output.splitlines()
        if lines[0] != "rustfs 1.0.0":
            raise ValueError
        labels = (
            "build time",
            "build profile",
            "build os",
            "rust version",
            "rust channel",
            "git branch",
            "git commit",
            "git tag",
            "git status",
        )
        prefixes = (
            "build time   : ",
            "build profile: ",
            "build os     : ",
            "rust version : ",
            "rust channel : ",
            "git branch   : ",
            "git commit   : ",
            "git tag      : ",
            "git status   :",
        )
        for line, label, prefix in zip(lines[1:10], labels, prefixes, strict=True):
            value = line[len(prefix) :]
            if not line.startswith(prefix) or (
                label != "git status"
                and (len(value) > 256 or (not value and label != "git branch"))
            ):
                raise ValueError
            if label == "git commit" and value != SERVER_COMMIT:
                raise ValueError
            if label == "git tag" and value != SERVER_VERSION:
                raise ValueError
        if any(
            re.match(r"(?:" + "|".join(map(re.escape, labels)) + r")\s*:", line)
            for line in lines[10:]
        ):
            raise ValueError
    except (ValueError, IndexError, UnicodeError):
        raise RuntimeError("official RustFS version grammar differs") from None


def zip_maps(maps):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, value in maps.items():
            entry = zipfile.ZipInfo(f"iam-assets/{name}.json")
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            bundle.writestr(entry, json.dumps(value, separators=(",", ":")).encode())
    if len(output.getvalue()) > LIMIT:
        raise RuntimeError("native IAM ZIP exceeds bound")
    return output.getvalue()


def import_payload(identities, policies):
    validate_credentials(identities)
    if set(policies) != set(POLICY_NAMES.values()):
        raise RuntimeError("native IAM policy set differs")
    return zip_maps(
        {
            "policies": policies,
            "users": {
                identities[actor][0]: {
                    "secretKey": identities[actor][1],
                    "status": "enabled",
                }
                for actor in POLICY_NAMES
            },
            "user_mappings": {
                identities[actor][0]: {
                    "version": 1,
                    "policy": policy,
                    "updatedAt": "2026-10-01T00:00:00Z",
                }
                for actor, policy in POLICY_NAMES.items()
            },
        }
    )


def validate_import_result(value, identities):
    try:
        if type(value) is not dict or set(value) != {
            "skipped",
            "removed",
            "added",
            "failed",
        }:
            raise ValueError
        for section, fields in value.items():
            if (
                type(fields) is not dict
                or set(fields) != ENTITIES
                or any(type(item) is not list for item in fields.values())
            ):
                raise ValueError
            if section != "added" and any(fields.values()):
                raise ValueError
        added = value["added"]
        if sorted(added["policies"]) != sorted(POLICY_NAMES.values()) or sorted(
            added["users"]
        ) != sorted(identities[actor][0] for actor in POLICY_NAMES):
            raise ValueError
        expected = [
            {identities[actor][0]: [policy]} for actor, policy in POLICY_NAMES.items()
        ]
        if (
            len(added["userPolicies"]) != 2
            or any(item not in expected for item in added["userPolicies"])
            or added["userPolicies"][0] == added["userPolicies"][1]
        ):
            raise ValueError
        if any(
            added[name] for name in ENTITIES - {"policies", "users", "userPolicies"}
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("native IAM import response differs") from None


def policy_tree(value):
    """Canonical semantic policy without accepting unrecognized fields."""
    if (
        type(value) is not dict
        or set(value) - {"Version", "Id", "Statement"}
        or value.get("Version") != "2012-10-17"
        or value.get("Id", "") != ""
    ):
        raise RuntimeError("native policy shape differs")
    statements = value.get("Statement")
    if type(statements) is not list:
        raise RuntimeError("native policy shape differs")
    result = []
    for item in statements:
        if (
            type(item) is not dict
            or set(item) - {"Sid", "Effect", "Action", "Resource", "Condition"}
            or item.get("Sid", "") != ""
            or item.get("Effect") != "Allow"
        ):
            raise RuntimeError("native policy shape differs")
        normalized = {"Effect": "Allow"}
        for field in ("Action", "Resource"):
            values = item.get(field, [])
            if type(values) is str:
                values = [values]
            if (
                type(values) is not list
                or any(type(entry) is not str for entry in values)
                or len(values) != len(set(values))
            ):
                raise RuntimeError("native policy shape differs")
            normalized[field] = sorted(values)
        condition = item.get("Condition", {})
        if type(condition) is not dict:
            raise RuntimeError("native policy shape differs")
        if condition:
            canonical = {}
            for operation, fields in condition.items():
                if type(operation) is not str or type(fields) is not dict:
                    raise RuntimeError("native policy condition shape differs")
                canonical[operation] = {}
                for key, values in fields.items():
                    values = [values] if type(values) is str else values
                    if (
                        type(key) is not str
                        or type(values) is not list
                        or any(type(entry) is not str for entry in values)
                        or len(values) != len(set(values))
                    ):
                        raise RuntimeError("native policy condition shape differs")
                    canonical[operation][key] = sorted(values)
            normalized["Condition"] = canonical
        result.append(normalized)
    return json.dumps(
        sorted(result, key=lambda item: json.dumps(item, sort_keys=True)),
        sort_keys=True,
        separators=(",", ":"),
    )


def builtin_policies():
    sts = {"Effect": "Allow", "Action": "sts:AssumeRole"}

    def definition(actions, resource=None):
        item = {"Effect": "Allow", "Action": actions}
        if resource:
            item["Resource"] = resource
        return item

    s3 = "arn:aws:s3:::*"
    kms = "arn:aws:kms:::*"
    definitions = {
        "readwrite": [definition("s3:*", s3)],
        "readonly": [
            definition(
                ["s3:GetBucketLocation", "s3:GetObject", "s3:GetBucketQuota"], s3
            )
        ],
        "writeonly": [definition("s3:PutObject", s3)],
        "diagnostics": [
            definition(
                [
                    "admin:" + name
                    for name in (
                        "Profiling",
                        "ServerTrace",
                        "ConsoleLog",
                        "ServerInfo",
                        "TopLocksInfo",
                        "OBDInfo",
                        "Prometheus",
                        "BandwidthMonitor",
                    )
                ],
                s3,
            )
        ],
        "consoleAdmin": [
            definition("admin:*"),
            definition("kms:*"),
            definition("s3:*", s3),
        ],
        "KMSKeyAdministrator": [
            definition(
                [
                    "kms:" + name
                    for name in (
                        "DescribeKey",
                        "ListKeys",
                        "EnableKey",
                        "DisableKey",
                        "RotateKey",
                        "DeleteKey",
                    )
                ],
                kms,
            )
        ],
        "KMSKeyUser": [
            definition(
                [
                    "kms:" + name
                    for name in ("GenerateDataKey", "Decrypt", "DescribeKey")
                ],
                kms,
            )
        ],
        "KMSAuditor": [
            definition(["kms:" + name for name in ("DescribeKey", "ListKeys")], kms)
        ],
    }
    return {
        name: {"Version": "2012-10-17", "Statement": items + [sts]}
        for name, items in definitions.items()
    }


def utc_date(value):
    try:
        if type(value) is str:
            match = re.fullmatch(
                r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{1,9}) \+00:00:00",
                value,
                flags=re.ASCII,
            )
            if not match:
                raise ValueError
            year, month, day, hour, minute, second = map(int, match.groups()[:6])
            datetime(year, month, day, hour, minute, second, tzinfo=UTC)
        elif (
            type(value) is list
            and len(value) == 9
            and all(type(item) is int for item in value)
        ):
            year, ordinal, hour, minute, second, nano, oh, om, os_ = value
            if (
                not 1 <= year <= 9999
                or not 1 <= ordinal <= 365 + calendar.isleap(year)
                or not 0 <= nano <= 999999999
                or (oh, om, os_) != (0, 0, 0)
            ):
                raise ValueError
            datetime(year, 1, 1, hour, minute, second, tzinfo=UTC)
        else:
            raise ValueError
    except (ValueError, TypeError):
        raise NativeMetadataFailure("native policy mutation date differs") from None
    return value


def mapping_date(value):
    try:
        if (
            type(value) is not str
            or len(value) > 64
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})",
                value,
                flags=re.ASCII,
            )
        ):
            raise ValueError
        datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise NativeMetadataFailure("native mapping mutation date differs") from None
    return value


def export_maps(payload):
    decoded = {}
    try:
        if type(payload) is not bytes or len(payload) > LIMIT:
            raise ValueError
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            entries = regular_entries(
                bundle, {f"iam-assets/{name}.json" for name in MAPS}
            )
            if sum(item.file_size for item in entries) > LIMIT:
                raise ValueError
            first = False
            remaining = LIMIT
            for name in MAPS:
                try:
                    with bundle.open(f"iam-assets/{name}.json") as member:
                        body = member.read(remaining + 1)
                    if len(body) > remaining:
                        raise RuntimeError("native IAM export expansion exceeds bound")
                    remaining -= len(body)
                    decoded[name] = strict_json(body)
                except Exception:  # noqa: BLE001 -- finish every safely readable later member
                    first = True
            if first:
                raise NativeExportFailure(decoded)
            return decoded
    except NativeExportFailure:
        raise
    except Exception:  # noqa: BLE001 -- no archive member data escapes
        raise RuntimeError("native IAM export shape differs") from None


class NativeExportFailure(RuntimeError):
    def __init__(self, partial):
        super().__init__("native IAM export shape differs")
        self.partial = partial  # Private only; never rendered, logged, or serialized.


class NativeAdminFailure(RuntimeError):
    def __init__(self, phase, close_failed=False, condition="TRANSPORT_ERROR"):
        super().__init__("native admin request failed")
        self.phase = (
            phase if phase in {"REQUEST", "READ", "ACCESS", "CLOSE"} else "UNKNOWN"
        )
        self.close_failed = close_failed is True
        self.condition = condition if condition in IAM_CONDITIONS else "SHAPE"


IAM_COMPONENTS = {
    "export": "EXPORT",
    "gateway": "USER_GATEWAY",
    "cleanup": "USER_CLEANUP",
    "wso-gateway": "POLICY_GATEWAY",
    "wso-maintenance": "POLICY_CLEANUP",
}
IAM_CONDITIONS = {
    "HTTP_STATUS",
    "SHAPE",
    "EXPECTED_STATE",
    "CHANGED_STATE",
    "METADATA",
    "TRANSPORT_ERROR",
    "CUTOFF",
    "CLOSE_ERROR",
}


def iam_condition(error):
    if isinstance(error, PhaseCutoff):
        return "CUTOFF"
    if isinstance(error, NativeMetadataFailure):
        return "METADATA"
    if isinstance(error, NativeAdminFailure):
        return error.condition
    if isinstance(error, (httpx.HTTPError, OSError)):
        return "TRANSPORT_ERROR"
    return "SHAPE"


class NativeSnapshotFailure(RuntimeError):
    def __init__(self, component, condition, status=None):
        self.component = component if component in IAM_COMPONENTS.values() else "EXPORT"
        self.condition = condition if condition in IAM_CONDITIONS else "SHAPE"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        super().__init__(
            f"native IAM snapshot failed component={self.component} condition={self.condition} status={self.status if self.status is not None else 'null'}"
        )


class NativeIamFailure(RuntimeError):
    def __init__(self, actor, phase, component, condition, status=None):
        self.actor = actor.upper() if actor in POLICY_NAMES else "GATEWAY"
        self.phase = (
            phase
            if phase in {"IAM_BEFORE", "IAM_IMPORT", "IAM_AFTER"}
            else "IAM_BEFORE"
        )
        detail = NativeSnapshotFailure(component, condition, status)
        self.component, self.condition, self.status = (
            detail.component,
            detail.condition,
            detail.status,
        )
        if component == "IMPORT_STATUS":
            self.component = component
        super().__init__(
            f"native runtime admin no-effect failed actor={self.actor} phase={self.phase} component={self.component} condition={self.condition} status={self.status if self.status is not None else 'null'}"
        )


class NativeIam:
    """Bounded signed native admin surface and private immutable no-effect oracle."""

    def __init__(self, endpoint, identities, policies, budget, *, request=None):
        validate_credentials(identities)
        self.endpoint, self.identities, self.policies, self.budget = (
            endpoint,
            identities,
            policies,
            budget,
        )
        self.payload = import_payload(identities, policies)
        self.request_hook = request

    def request(self, actor, method, path, *, query=None, body=b""):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        url = self.endpoint + "/rustfs/admin/v3/" + path
        if query:
            url += "?" + urlencode(query)
        access, secret = self.identities[actor]
        request = AWSRequest(
            method=method,
            url=url,
            data=body,
            headers={
                "Content-Type": "application/zip"
                if body
                else "application/octet-stream",
                "Content-Length": str(len(body)),
                "X-Amz-Content-SHA256": hashlib.sha256(body).hexdigest(),
            },
        )
        SigV4Auth(Credentials(access, secret), "s3", "us-east-1").add_auth(request)
        timeout = self.budget.allowance(20)
        cutoff = time.monotonic() + timeout

        def check():
            self.budget.check()
            if time.monotonic() >= cutoff:
                raise NativeAdminFailure(phase, condition="CUTOFF")

        phase = "REQUEST"
        try:
            if self.request_hook is not None:
                result = self.request_hook(
                    actor, method, path, query, body, dict(request.headers), timeout
                )
            else:
                chunks, size = [], 0
                context = httpx.stream(
                    method,
                    url,
                    content=body,
                    headers=dict(request.headers),
                    timeout=timeout,
                    trust_env=False,
                    follow_redirects=False,
                )
                check()
                response = context.__enter__()
                first = None
                try:
                    check()
                    phase = "READ"
                    for chunk in response.iter_bytes(LIMIT):
                        check()
                        size += len(chunk)
                        if size > LIMIT:
                            raise RuntimeError("native admin response exceeds bound")
                        chunks.append(chunk)
                    phase = "ACCESS"
                    result = (
                        response.status_code,
                        response.headers.get("content-type", "").split(";")[0],
                        b"".join(chunks),
                    )
                    if method == "GET" and path == "export-iam" and result[0] == 200:
                        length = response.headers.get("content-length", "")
                        if (
                            response.headers.get("content-type") != "application/zip"
                            or response.headers.get("content-disposition")
                            != "attachment; filename=iam-assets.zip"
                            or not re.fullmatch(r"[0-9]+", length)
                            or int(length) != size
                        ):
                            raise RuntimeError(
                                "native IAM export HTTP metadata differs"
                            )
                    check()
                except Exception as error:  # noqa: BLE001 -- retain first read/access phase before close
                    first = NativeAdminFailure(phase, condition=iam_condition(error))
                finally:
                    try:
                        context.__exit__(None, None, None)
                    except Exception:  # noqa: BLE001 -- always attempt required body close
                        if first is not None:
                            first.close_failed = True
                        else:
                            first = NativeAdminFailure("CLOSE", condition="CLOSE_ERROR")
                if first is not None:
                    raise first from None
            check()
            if (
                type(result) is not tuple
                or len(result) != 3
                or type(result[0]) is not int
                or type(result[1]) is not str
                or type(result[2]) is not bytes
                or len(result[2]) > LIMIT
            ):
                raise RuntimeError("native admin response shape differs")
            return result
        except Exception as error:  # noqa: BLE001 -- signed headers, URLs, IDs, and bodies never escape
            raise (
                error
                if isinstance(error, NativeAdminFailure)
                else NativeAdminFailure(phase, condition=iam_condition(error))
            ) from None

    def provision(self):
        status, mime, payload = self.request(
            "bootstrap", "PUT", "import-iam", body=self.payload
        )
        if status != 200 or mime != "application/json":
            raise RuntimeError("native IAM import response differs")
        validate_import_result(strict_json(payload), self.identities)

    def snapshot(self):
        observations, failures = {}, {}
        calls = [
            ("export", "export-iam", None),
            *[
                (actor, "user-info", {"accessKey": self.identities[actor][0]})
                for actor in POLICY_NAMES
            ],
            *[
                (policy, "info-canned-policy", {"name": policy})
                for policy in POLICY_NAMES.values()
            ],
        ]
        for component, path, query in calls:
            try:
                status, mime, payload = self.request(
                    "bootstrap", "GET", path, query=query
                )
                if status != 200:
                    raise NativeSnapshotFailure(
                        IAM_COMPONENTS[component], "HTTP_STATUS", status
                    )
                if mime != (
                    "application/zip" if component == "export" else "application/json"
                ):
                    raise NativeSnapshotFailure(
                        IAM_COMPONENTS[component], "SHAPE", status
                    )
                observations[component] = (
                    export_maps(payload)
                    if component == "export"
                    else strict_json(payload)
                )
            except Exception as error:  # noqa: BLE001 -- finish every safe later observation
                if isinstance(error, NativeExportFailure):
                    observations[component] = error.partial
                failures.setdefault(
                    component,
                    (
                        error
                        if isinstance(error, NativeSnapshotFailure)
                        else NativeSnapshotFailure(
                            IAM_COMPONENTS[component], iam_condition(error)
                        )
                    ),
                )
        for component, value in observations.items():
            try:
                self.validate_component(component, value, observations.get("export"))
            except Exception as error:  # noqa: BLE001 -- only static first-component metadata escapes
                condition = (
                    "METADATA"
                    if isinstance(error, NativeMetadataFailure)
                    else "EXPECTED_STATE"
                )
                failures.setdefault(
                    component,
                    NativeSnapshotFailure(IAM_COMPONENTS[component], condition),
                )
        first = next(
            (failures[component] for component, _, _ in calls if component in failures),
            None,
        )
        if first is not None:
            raise first from None
        canonical = json.loads(json.dumps(observations))
        for name, policy in canonical["export"]["policies"].items():
            canonical["export"]["policies"][name] = policy_tree(policy)
        for policy in POLICY_NAMES.values():
            canonical[policy]["policy"] = policy_tree(canonical[policy]["policy"])
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    def validate_component(self, component, value, exported):
        if component == "export":
            first = set(value) != set(MAPS)
            for member in MAPS:
                if member not in value:
                    continue  # Already invalid; missing never becomes a fake empty map.
                try:
                    self.validate_export_member(member, value[member])
                except Exception:  # noqa: BLE001 -- all safe later comparisons still run
                    first = True
            if first:
                raise RuntimeError("native IAM exported complete state differs")
        elif component in POLICY_NAMES:
            if (
                type(value) is not dict
                or set(value) - {"status", "policyName", "updatedAt", "memberOf"}
                or not {"status", "policyName", "updatedAt"} <= set(value)
                or value["status"] != "enabled"
                or value["policyName"] != POLICY_NAMES[component]
                or value.get("memberOf", []) != []
            ):
                raise RuntimeError("native IAM user information differs")
            mapping_date(value["updatedAt"])
            if (
                exported is not None
                and value["updatedAt"]
                != exported["user_mappings"][self.identities[component][0]]["updatedAt"]
            ):
                raise NativeMetadataFailure("native IAM user metadata differs")
        else:
            if (
                type(value) is not dict
                or set(value) != {"policy_name", "policy", "create_date", "update_date"}
                or value["policy_name"] != component
                or policy_tree(value["policy"]) != policy_tree(self.policies[component])
            ):
                raise RuntimeError("native IAM policy information differs")
            utc_date(value["create_date"])
            utc_date(value["update_date"])
            if exported is not None and policy_tree(value["policy"]) != policy_tree(
                exported["policies"][component]
            ):
                raise RuntimeError("native IAM policy cross consistency differs")

    def validate_export_member(self, member, value):
        if type(value) is not dict:
            raise RuntimeError("native IAM export member shape differs")
        if member == "users":
            expected_users = {
                self.identities[actor][0]: {
                    "secretKey": self.identities[actor][1],
                    "status": "enabled",
                }
                for actor in POLICY_NAMES
            }
            if value != expected_users:
                raise RuntimeError("native IAM exported identities differ")
        elif member == "policies":
            expected_policies = {**builtin_policies(), **self.policies}
            first = set(value) != set(expected_policies)
            for name, expected in expected_policies.items():
                if name not in value:
                    continue
                try:
                    if policy_tree(value[name]) != policy_tree(expected):
                        first = True
                except Exception:  # noqa: BLE001 -- finish safely available later policy trees
                    first = True
            if first:
                raise RuntimeError("native IAM exported policies differ")
        elif member == "user_mappings":
            expected = {self.identities[actor][0] for actor in POLICY_NAMES}
            first = set(value) != expected
            for actor, policy in POLICY_NAMES.items():
                try:
                    mapping = value[self.identities[actor][0]]
                    if (
                        type(mapping) is not dict
                        or set(mapping) != {"version", "policy", "updatedAt"}
                        or type(mapping["version"]) is not int
                        or mapping["version"] != 1
                        or mapping["policy"] != policy
                    ):
                        raise RuntimeError("native IAM exported binding differs")
                    mapping_date(mapping["updatedAt"])
                except Exception:  # noqa: BLE001 -- check the other safely available binding
                    first = True
            if first:
                raise RuntimeError("native IAM exported binding differs")
        elif value:
            raise RuntimeError("native IAM exported extra identities differ")

    def no_effect(self):
        import xml.etree.ElementTree as ET

        for actor in POLICY_NAMES:
            try:
                before = self.snapshot()
            except NativeSnapshotFailure as error:
                raise NativeIamFailure(
                    actor, "IAM_BEFORE", error.component, error.condition, error.status
                ) from None
            first = None
            status = None
            try:
                status, mime, payload = self.request(
                    actor, "PUT", "import-iam", body=self.payload
                )
                if status != 403:
                    first = NativeIamFailure(
                        actor, "IAM_IMPORT", "IMPORT_STATUS", "HTTP_STATUS", status
                    )
                if (
                    mime not in {"application/xml", "text/xml"}
                    or b"<!" in payload
                    or b"\x00" in payload
                    or payload.startswith(b"\xef\xbb\xbf")
                ):
                    raise ValueError
                root = ET.fromstring(payload.decode("utf-8"))
                if root.tag != "Error" or root.findtext("Code") != "AccessDenied":
                    raise ValueError
            except Exception as error:  # noqa: BLE001 -- independent exact status, no unsafe native errors
                first = first or NativeIamFailure(
                    actor, "IAM_IMPORT", "IMPORT_STATUS", iam_condition(error), status
                )
            try:
                after = self.snapshot()
                if before != after:
                    prior, current = json.loads(before), json.loads(after)
                    for component, label in IAM_COMPONENTS.items():
                        if prior[component] != current[component]:
                            left, right = prior[component], current[component]
                            metadata = False
                            if component in POLICY_NAMES:
                                metadata = {
                                    key: value
                                    for key, value in left.items()
                                    if key != "updatedAt"
                                } == {
                                    key: value
                                    for key, value in right.items()
                                    if key != "updatedAt"
                                }
                            elif component in POLICY_NAMES.values():
                                metadata = {
                                    key: value
                                    for key, value in left.items()
                                    if key not in {"create_date", "update_date"}
                                } == {
                                    key: value
                                    for key, value in right.items()
                                    if key not in {"create_date", "update_date"}
                                }
                            elif component == "export":
                                left, right = (
                                    json.loads(json.dumps(left)),
                                    json.loads(json.dumps(right)),
                                )
                                for value in (left, right):
                                    for mapping in value["user_mappings"].values():
                                        mapping.pop("updatedAt")
                                metadata = left == right
                            first = first or NativeIamFailure(
                                actor,
                                "IAM_AFTER",
                                label,
                                "METADATA" if metadata else "CHANGED_STATE",
                            )
                            break
            except NativeSnapshotFailure as error:
                first = first or NativeIamFailure(
                    actor, "IAM_AFTER", error.component, error.condition, error.status
                )
            if first is not None:
                raise first from None


class OwnedCommands:
    """Bound both pipes while reading; retain unsettled exact children/readers."""

    def __init__(self):
        self.active = []

    def run(
        self, command, environment, allowance, *, binary=False, output_limit=1048576
    ):
        self.assert_settled()
        if (
            type(allowance) not in {int, float}
            or not math.isfinite(allowance)
            or allowance <= 0
            or type(output_limit) is not int
            or not 0 < output_limit <= 1048576
        ):
            raise RuntimeError("invalid owned command allowance")
        cutoff = time.monotonic() + allowance
        process = subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        buffers = [bytearray(), bytearray()]
        failed = threading.Event()

        def read(index, pipe):
            try:
                while chunk := pipe.read(65536):
                    if len(buffers[index]) + len(chunk) > output_limit:
                        failed.set()
                        return
                    buffers[index].extend(chunk)
            except (OSError, ValueError):
                failed.set()
            finally:
                try:
                    pipe.close()
                except (OSError, ValueError):
                    failed.set()

        threads = [
            threading.Thread(target=read, args=(index, pipe), daemon=True)
            for index, pipe in enumerate((process.stdout, process.stderr))
        ]
        record = (process, threads)
        self.active.append(record)
        try:
            for thread in threads:
                thread.start()
            while process.poll() is None:
                if failed.is_set() or time.monotonic() >= cutoff:
                    process.kill()
                    break
                time.sleep(min(0.02, max(0, cutoff - time.monotonic())))
            # Fixed responsive settlement target, never an OS preemption claim.
            settle = min(cutoff, time.monotonic() + 3)
            process.wait(timeout=max(0.001, settle - time.monotonic()))
            for thread in threads:
                thread.join(max(0, settle - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                raise RuntimeError("owned command settlement refused")
            self.active.remove(record)
            if failed.is_set() or process.returncode != 0 or time.monotonic() >= cutoff:
                raise RuntimeError("owned command failed")
            result = bytes(buffers[0])
            return result if binary else result.decode("utf-8").strip()
        except Exception:  # noqa: BLE001 -- no argv or private pipe output escapes
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            raise OwnedCommandFailure(process.returncode) from None

    def assert_settled(self):
        if self.active:
            raise RuntimeError("owned RustFS command ownership unsettled")


class OwnedCommandFailure(RuntimeError):
    def __init__(self, returncode):
        super().__init__("owned RustFS command failed or unsettled")
        self.returncode = (
            returncode
            if type(returncode) is int and -(2**32) < returncode < 2**32
            else None
        )


def native_pages(actor, bucket, prefix, stream, expected, *, start=None):
    """Keep real cursors private; diagnostic predicates use only received pages."""
    marker = dict(start or {})
    rows, cursors, seen, marker_seen = [], [], set(), set()
    summary = {
        "pages": 0,
        "rows": 0,
        "unique_rows": 0,
        "expected_rows": len(expected),
        "set_equal": None,
        "missing_rows": None,
        "extra_rows": None,
        "marker_valid": None,
        "terminal": None,
        "same_key_boundary": None if stream == "objects" else False,
    }
    try:
        if stream not in {"objects", "multipart"} or len(expected) > 1000:
            raise ValueError
        for _ in range(1000):
            if stream == "objects":
                page = actor.list_objects_v2(
                    Bucket=bucket, Prefix=prefix, MaxKeys=1, **marker
                )
            else:
                page = actor.list_multipart_uploads(
                    Bucket=bucket, Prefix=prefix, MaxUploads=1, **marker
                )
            summary["pages"] += 1
            if type(page) is not dict:
                raise ValueError
            incoming = page.get("Contents" if stream == "objects" else "Uploads", [])
            if type(page) is not dict or type(incoming) is not list:
                raise ValueError
            summary["rows"] += len(incoming)
            if len(incoming) > 1:
                raise ValueError
            for row in incoming:
                key = row.get("Key") if type(row) is dict else None
                upload = row.get("UploadId") if type(row) is dict else None
                if (
                    type(key) is not str
                    or not key.startswith(prefix)
                    or key == prefix
                    or (stream != "objects" and (type(upload) is not str or not upload))
                ):
                    raise ValueError
                identity = key if stream == "objects" else (key, upload)
                if identity in seen:
                    raise ValueError
                if (
                    stream != "objects"
                    and rows
                    and rows[-1]["Key"] == key
                    and rows[-1]["UploadId"] != upload
                ):
                    summary["same_key_boundary"] = True
                seen.add(identity)
                rows.append(row)
                summary["unique_rows"] = len(seen)
            if page.get("IsTruncated") is False:
                summary["terminal"] = True
                summary["marker_valid"] = True
                break
            summary["terminal"] = False
            summary["marker_valid"] = False
            if page.get("IsTruncated") is not True:
                raise ValueError
            if len(incoming) != 1:
                raise ValueError
            if stream == "objects":
                token = page.get("NextContinuationToken")
                if type(token) is not str or not token:
                    raise ValueError
                marker = {"ContinuationToken": token}
                identity = token
            else:
                key, upload = page.get("NextKeyMarker"), page.get("NextUploadIdMarker")
                if (
                    type(key) is not str
                    or not key.startswith(prefix)
                    or type(upload) is not str
                    or not upload
                ):
                    raise ValueError
                if (key, upload) != (incoming[0]["Key"], incoming[0]["UploadId"]):
                    raise ValueError
                marker = {"KeyMarker": key, "UploadIdMarker": upload}
                identity = (key, upload)
            if identity in marker_seen:
                raise ValueError
            marker_seen.add(identity)
            summary["marker_valid"] = True
            cursors.append(dict(marker))
        summary.update(
            set_equal=seen == set(expected),
            missing_rows=len(set(expected) - seen),
            extra_rows=len(seen - set(expected)),
        )
        if not summary["terminal"] or not summary["set_equal"]:
            raise ValueError
        return rows, cursors, summary
    except Exception:  # noqa: BLE001 -- no SDK payload, key, upload, or marker escapes
        summary.update(
            set_equal=seen == set(expected),
            missing_rows=min(1000, len(set(expected) - seen)),
            extra_rows=min(1000, len(seen - set(expected))),
        )
        raise NativeListingFailure(stream, summary) from None


class NativeListingFailure(RuntimeError):
    def __init__(self, stream, summary):
        super().__init__("native provider paging predicate failed")
        self.stream = (
            stream
            if type(stream) is str and stream in {"objects", "multipart"}
            else "objects"
        )
        fields = (
            "pages",
            "rows",
            "unique_rows",
            "expected_rows",
            "set_equal",
            "missing_rows",
            "extra_rows",
            "marker_valid",
            "terminal",
            "same_key_boundary",
        )
        counts = {
            "pages",
            "rows",
            "unique_rows",
            "expected_rows",
            "missing_rows",
            "extra_rows",
        }
        self.summary = {}
        for field in fields:
            value = summary.get(field) if type(summary) is dict else None
            self.summary[field] = (
                value
                if (
                    type(value) is int and 0 <= value <= 1000
                    if field in counts
                    else type(value) is bool
                )
                else None
            )
        if self.stream == "objects":
            self.summary["same_key_boundary"] = None


class BudgetS3Client:
    """Keep original SDK timeouts; refuse calls without their full allowance.

    No mutation of private SDK/session internals or retry/pool configuration.
    Existing connect3/read5 caps require eight remaining seconds at admission.
    Returning late fails; this makes no preemption claim.
    """

    def __init__(self, client, budget):
        self.client, self.budget = client, budget
        self.streams = set()

    def reserve(self, seconds):
        if self.budget.allowance(seconds) < seconds:
            raise RuntimeError("owned SDK phase allowance exhausted")

    def __getattr__(self, name):
        operation = getattr(self.client, name)
        if name == "generate_presigned_url":
            return operation

        def call(**kwargs):
            self.reserve(8)
            try:
                result = operation(**kwargs)
            except Exception:
                self.budget.check()
                raise
            if isinstance(result, dict) and "Body" in result:
                result["Body"] = OwnedBody(result["Body"], self)
            self.budget.check()
            return result

        return call

    def close(self):
        first = None
        for stream in tuple(self.streams):
            try:
                stream.close()
            except Exception:  # noqa: BLE001 -- settle every exact owned body
                first = first or "body"
        try:
            self.client.close()
        except Exception:  # noqa: BLE001 -- no SDK message escapes
            first = first or "client"
        if first or self.streams:
            raise RuntimeError("owned SDK client settlement refused")


class OwnedBody:
    def __init__(self, body, owner):
        self.body, self.owner = body, owner
        owner.streams.add(self)

    def read(self, *args):
        self.owner.reserve(5)
        result = self.body.read(*args)
        self.owner.budget.check()
        return result

    def close(self):
        self.body.close()
        self.owner.streams.discard(self)
