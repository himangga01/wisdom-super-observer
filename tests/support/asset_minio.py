"""Pinned official artifact and secret-file bootstrap support, not S3 acceptance."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

SERVER_VERSION = "RELEASE.2025-04-22T22-12-26Z"
SERVER_SHA = "53e2a2cb16c5366ea6fbbc479c19ddb4c6a0948273e752f740fb1fbf27bb817c"
SERVER_COMMIT = "0d7408fc9969caf07de6a8c3a84f9fbb10a6739e"
CLIENT_VERSION = "RELEASE.2025-04-16T18-13-26Z"
CLIENT_SHA = "ac90da87a35641be5a0ac75d49de5161ddb47d629b5ba01261b0ae9e00aea15f"
CLIENT_COMMIT = "b00526b153a31b36767991a4f5ce2cced435ee8e"
ARTIFACTS = {
    "minio": ("minio", SERVER_VERSION, SERVER_SHA, SERVER_COMMIT, 118849720),
    "mc": ("mc", CLIENT_VERSION, CLIENT_SHA, CLIENT_COMMIT, 30179512),
}
LOCAL_DOCKER_ENDPOINT = "unix:///var/run/docker.sock"


def verify_private_path(path, mode):
    observed = Path(path).lstat()
    expected_type = stat.S_ISDIR if mode == 0o700 else stat.S_ISREG
    if (
        not expected_type(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != mode
        or observed.st_uid != os.getuid()
    ):
        raise RuntimeError("owned Docker CLI config identity/mode differs")


def local_socket_identity():
    try:
        observed = Path("/var/run/docker.sock").lstat()
        if not stat.S_ISSOCK(observed.st_mode) or observed.st_uid != 0:
            raise ValueError
        return observed.st_dev, observed.st_ino, observed.st_uid
    except (OSError, ValueError):
        raise RuntimeError(
            "required local root-owned Docker socket unavailable"
        ) from None


class LocalDocker:
    """Fixed local socket and owned empty CLI config; never ambient contexts."""

    def __init__(self, directory):
        require_linux_ci()
        self.directory = Path(directory)
        self.config = self.directory / "docker-config"
        self.config.mkdir(mode=0o700)
        private_file(self.config / "config.json", b"{}")
        self.socket = local_socket_identity()
        self.environment = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "TZ")
            if key in os.environ
        }
        self.environment.update(
            HOME=str(self.directory),
            TMPDIR=str(self.directory),
            DOCKER_CONFIG=str(self.config),
        )

    def command(self, *arguments):
        for path, mode in (
            (self.directory, 0o700),
            (self.config, 0o700),
            (self.config / "config.json", 0o600),
        ):
            verify_private_path(path, mode)
        if (self.config / "config.json").read_bytes() != b"{}":
            raise RuntimeError("owned Docker CLI configuration changed")
        if local_socket_identity() != self.socket:
            raise RuntimeError("local Docker socket identity changed")
        return (
            [
                "docker",
                "--config",
                str(self.config),
                "--host",
                LOCAL_DOCKER_ENDPOINT,
                *arguments,
            ],
            dict(self.environment),
        )


def require_linux_ci():
    if (
        sys.platform != "linux"
        or os.environ.get("CI") != "true"
        or platform.machine() not in {"x86_64", "amd64"}
    ):
        raise RuntimeError("MinIO provisioning requires explicit Linux amd64 CI")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT") not in {
        None,
        "default",
    }:
        raise RuntimeError("remote Docker fixture target forbidden")


def validate_download_url(url):
    parsed = urlsplit(url)
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
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise RuntimeError("official artifact redirect refused")


def validate_artifact(length, digest, expected_length, expected_digest):
    if length != expected_length or digest != expected_digest:
        raise RuntimeError("official artifact byte length/hash mismatch")


def download_artifact(directory, name):
    require_linux_ci()
    repository, version, digest, _, size = ARTIFACTS[name]
    target = Path(directory) / name
    url = f"https://github.com/minio/{repository}/releases/download/{version}/{name}.linux-amd64.{version}"
    started = time.monotonic()
    created = False
    try:
        with httpx.Client(
            timeout=20, trust_env=False, follow_redirects=False
        ) as client:
            for _ in range(6):
                validate_download_url(url)
                with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code != 200:
                        raise RuntimeError("official artifact unavailable")
                    descriptor = os.open(
                        target,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600,
                    )
                    created = True
                    hashed = hashlib.sha256()
                    length = 0
                    with os.fdopen(descriptor, "wb") as output:
                        for chunk in response.iter_bytes(65536):
                            length += len(chunk)
                            if length > size or time.monotonic() - started > 180:
                                raise RuntimeError(
                                    "official artifact download bound exceeded"
                                )
                            hashed.update(chunk)
                            output.write(chunk)
                    validate_artifact(length, hashed.hexdigest(), size, digest)
                    os.chmod(target, 0o700)  # Only verified bytes become executable.
                    return target
            raise RuntimeError("official artifact redirect bound exceeded")
    except (OSError, httpx.HTTPError, RuntimeError):
        if created:
            target.unlink(missing_ok=True)
        raise RuntimeError("official artifact acquisition failed") from None


def private_file(path, data):
    descriptor = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def safe_run(arguments, directory, *, timeout=30):
    """No raw subprocess output escapes; mc gets no ambient aliases/credentials."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ")
        if key in os.environ
    }
    environment.update({"HOME": str(directory), "TMPDIR": str(directory)})
    try:
        with (
            tempfile.TemporaryFile(dir=directory) as stdout,
            tempfile.TemporaryFile(dir=directory) as stderr,
        ):
            result = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=environment,
                timeout=timeout,
                check=False,
            )
            if result.returncode or stdout.tell() > 1048576 or stderr.tell() > 1048576:
                raise RuntimeError("owned bootstrap command failed")
            stdout.seek(0)
            return stdout.read(1048577).decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise RuntimeError("owned bootstrap command failed") from None


def verify_binary_version(path, name, directory):
    require_linux_ci()
    _, version, _, commit, _ = ARTIFACTS[name]
    output = safe_run([str(path), "--version"], directory)
    first = output.splitlines()[0] if output else ""
    if first != f"{name} version {version} (commit-id={commit})":
        raise RuntimeError("observed executable version/commit differs from pin")


def validate_import_result(raw, credentials):
    def no_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=no_duplicates)
        if not isinstance(value, dict) or set(value) - {
            "added",
            "skipped",
            "removed",
            "failed",
        }:
            raise ValueError
        allowed = {
            "policies",
            "users",
            "groups",
            "serviceAccounts",
            "userPolicies",
            "groupPolicies",
            "stsPolicies",
        }
        for section in ("skipped", "removed", "failed"):
            entries = value.get(section, {})
            if (
                not isinstance(entries, dict)
                or set(entries) - allowed
                or any(item != [] for item in entries.values())
            ):
                raise ValueError
        added = value["added"]
        if not isinstance(added, dict) or set(added) != {
            "policies",
            "users",
            "userPolicies",
        }:
            raise ValueError
        users = [credentials[name][0] for name in ("gateway", "cleanup")]
        for field in ("users", "policies"):
            if not isinstance(added[field], list) or not all(
                isinstance(item, str) for item in added[field]
            ):
                raise ValueError
        if sorted(added["users"]) != sorted(users) or sorted(added["policies"]) != [
            "wso-gateway",
            "wso-maintenance",
        ]:
            raise ValueError
        mappings = added["userPolicies"]
        expected = [{users[0]: ["wso-gateway"]}, {users[1]: ["wso-maintenance"]}]
        if (
            not isinstance(mappings, list)
            or len(mappings) != 2
            or any(item not in mappings for item in expected)
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("exact IAM import result could not be established") from None


def iam_archive_bytes(credentials, policies):
    users = {
        credentials[name][0]: {"secretKey": credentials[name][1], "status": "enabled"}
        for name in ("gateway", "cleanup")
    }
    mappings = {
        credentials[name][0]: {"version": 1, "policy": policy}
        for name, policy in (("gateway", "wso-gateway"), ("cleanup", "wso-maintenance"))
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        for name, content in (
            ("policies", policies),
            ("users", users),
            ("user_mappings", mappings),
        ):
            zipped.writestr(f"iam-assets/{name}.json", json.dumps(content).encode())
    return stream.getvalue()


def provision_users(directory, endpoint, credentials, policies):
    require_linux_ci()
    config = Path(directory) / "mc-config"
    config.mkdir(mode=0o700)
    bootstrap = credentials["bootstrap"]
    private_file(
        config / "config.json",
        json.dumps(
            {
                "version": "10",
                "aliases": {
                    "fixture": {
                        "url": endpoint,
                        "accessKey": bootstrap[0],
                        "secretKey": bootstrap[1],
                        "api": "S3v4",
                        "path": "on",
                    }
                },
            }
        ).encode(),
    )
    archive = Path(directory) / "iam-import.zip"
    private_file(archive, iam_archive_bytes(credentials, policies))
    for path in (config, config / "config.json", archive):
        expected = 0o700 if path.is_dir() else 0o600
        if path.stat().st_mode & 0o777 != expected or path.stat().st_uid != os.getuid():
            raise RuntimeError("bootstrap private file ownership/mode mismatch")
    output = safe_run(
        [
            str(Path(directory) / "mc"),
            "--config-dir",
            str(config),
            "--json",
            "admin",
            "cluster",
            "iam",
            "import",
            "fixture",
            str(archive),
        ],
        directory,
        timeout=60,
    )
    validate_import_result(output, credentials)
