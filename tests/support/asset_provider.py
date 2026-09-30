"""Owned official MinIO fixture. Every acceptance probe uses real S3/HTTP."""

from __future__ import annotations

import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import time
from functools import partial
from pathlib import Path
from uuid import uuid4

import httpx

from tests.support.asset_minio import (
    CLIENT_SHA,
    CLIENT_VERSION,
    SERVER_COMMIT,
    SERVER_SHA,
    SERVER_VERSION,
    LocalDocker,
    LoopbackRelay,
    download_artifact,
    private_file,
    provision_users,
    require_linux_ci,
    verify_binary_version,
)

LABEL = "wso.assets.owner"
SECURITY_PROFILE = "minio-inert-acl-dedicated-bucket-v2"
CONTROL_RESULTS = {
    "put_bucket_policy": (403, "AccessDenied"),
    "delete_bucket_policy": (403, "AccessDenied"),
    "put_bucket_acl": (403, "AccessDenied"),
    "put_object_acl": (403, "AccessDenied"),
    "put_bucket_ownership_controls": (400, "MalformedXML"),
    "delete_bucket_ownership_controls": (403, "AccessDenied"),
    "put_public_access_block": (400, "MalformedXML"),
    "delete_public_access_block": (403, "AccessDenied"),
    "create_bucket": (403, "AccessDenied"),
    "get_bucket_ownership_controls": (501, "NotImplemented"),
    "get_public_access_block": (501, "NotImplemented"),
}

ACL_COMPONENTS = frozenset(
    [
        "mutation_response",
        "multipart_identity",
        "upload_part",
        "complete_multipart",
        "signed_head",
        "signed_get_open",
        "signed_get_read",
        "signed_get_close",
        "object_acl",
        "anonymous_get",
        "anonymous_head",
        "bucket_acl",
        "policy_absence",
        "delete_new",
        "absence_head",
        "absence_multipart_page",
    ]
)
ACL_CODES = frozenset(
    [
        "AccessDenied",
        "NotImplemented",
        "MalformedXML",
        "NoSuchKey",
        "NoSuchBucketPolicy",
        "NoSuchUpload",
        "NoSuchBucket",
        "InvalidRequest",
        "InvalidArgument",
        "SlowDown",
        "InternalError",
        "RequestTimeout",
        "SignatureDoesNotMatch",
        "InvalidAccessKeyId",
        "403",
        "404",
        "UNKNOWN",
        "TRANSPORT_ERROR",
        "SUCCESS",
    ]
)
ACL_CONDITIONS = frozenset(
    [
        "STATUS_MISMATCH",
        "LENGTH_MISMATCH",
        "BYTES_MISMATCH",
        "ACL_SHAPE",
        "POLICY_PRESENT",
        "OBJECT_SURVIVED",
        "UPLOAD_SURVIVED",
        "PAGINATION_INVALID",
        "TRANSPORT_ERROR",
        "UNKNOWN",
    ]
)


def acl_status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


def acl_fields(fields):
    """Final output boundary rejects unsafe labels and drops unapproved fields."""
    target, component = fields.get("target"), fields.get("component")
    if (
        type(target) is not str
        or target not in {"new", "original", "bucket", "new_cleanup"}
        or type(component) is not str
        or component not in ACL_COMPONENTS
    ):
        raise RuntimeError("invalid fixed ACL diagnostic metadata") from None
    code, condition = fields.get("observed_code"), fields.get("condition")
    normalized = {
        "target": target,
        "component": component,
        "observed_status": acl_status(fields.get("observed_status")),
        "observed_code": code if type(code) is str and code in ACL_CODES else "UNKNOWN",
        "condition": condition
        if type(condition) is str and condition in ACL_CONDITIONS
        else "UNKNOWN",
    }
    if fields.get("close_failed") is True:
        normalized["close_failed"] = True
    return normalized


class AclEffectFailure(RuntimeError):
    def __init__(self, message, fields):
        super().__init__(message)
        self.fields = acl_fields(fields)


class AclDiagnostic:
    """Explicit per-attempt state; exceptions retain a sanitized immutable snapshot."""

    def __init__(self):
        self.target = "new"
        self.fields = {}

    def begin(self, component):
        if (
            self.target not in {"new", "original", "bucket", "new_cleanup"}
            or component not in ACL_COMPONENTS
        ):
            raise RuntimeError("invalid fixed ACL diagnostic context") from None
        self.fields = {
            "target": self.target,
            "component": component,
            "observed_status": None,
            "observed_code": "UNKNOWN",
            "condition": "UNKNOWN",
        }

    def observe(self, status, code):
        self.fields["observed_status"] = acl_status(status)
        self.fields["observed_code"] = (
            code if type(code) is str and code in ACL_CODES else "UNKNOWN"
        )

    def fail(self, message, condition):
        self.fields["condition"] = (
            condition
            if type(condition) is str and condition in ACL_CONDITIONS
            else "UNKNOWN"
        )
        raise AclEffectFailure(message, self.fields) from None

    def call(self, component, operation):
        from botocore.exceptions import ClientError

        self.begin(component)
        try:
            result = operation()
        except ClientError as error:
            self.observe(*AssetProvider.error_identity(error))
            self.fail("private ACL SDK effect failed", "STATUS_MISMATCH")
        except Exception:  # noqa: BLE001 -- sanitized transport only
            self.observe(None, "TRANSPORT_ERROR")
            self.fail("private ACL effect transport failed", "TRANSPORT_ERROR")
        if isinstance(result, dict):
            metadata = result.get("ResponseMetadata")
            self.observe(
                metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None,
                "SUCCESS",
            )
        else:
            self.observe(None, "SUCCESS")
        return result


def no_host_bindings(value):
    return value is None or (
        isinstance(value, dict)
        and all(binding is None or binding == [] for binding in value.values())
    )


def private_json(path, value):
    private_file(path, json.dumps(value).encode("utf-8"))


def policy_config(bucket, prefix, identities):
    """Dedicated bucket; ordinary listing prefix scoped, multipart metadata bucket scoped."""
    bucket_arn = f"arn:aws:s3:::{bucket}"
    definitions = {}
    for name, actions in (
        (
            "wso-gateway",
            [
                "s3:PutObject",
                "s3:GetObject",
                "s3:AbortMultipartUpload",
                "s3:ListMultipartUploadParts",
            ],
        ),
        (
            "wso-maintenance",
            [
                "s3:DeleteObject",
                "s3:AbortMultipartUpload",
                "s3:ListMultipartUploadParts",
            ],
        ),
    ):
        definitions[name] = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": actions,
                    "Resource": f"{bucket_arn}/{prefix}*",
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": bucket_arn,
                    "Condition": {"StringLike": {"s3:prefix": [prefix, prefix + "*"]}},
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucketMultipartUploads"],
                    "Resource": bucket_arn,
                },
            ],
        }
    return definitions


class AssetProvider:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.owner = uuid4().hex
        self.installation_id = uuid4()
        self.bucket = "wso-assets-" + self.owner
        self.prefix = f"wso-assets/v1/{self.installation_id.hex}/"
        self.volume = "wso-assets-data-" + self.owner
        self.container = "wso-assets-s3-" + self.owner
        self.network = "wso-assets-net-" + self.owner
        self.image_tag = "wso-assets-minio:" + self.owner
        self.work = None
        self.created = []
        self.clients = {}
        self.credentials = {
            name: (secrets.token_hex(12), secrets.token_hex(32))
            for name in ("bootstrap", "gateway", "cleanup")
        }
        self.receipt = None
        self.outcomes = []
        self.control_outcomes = []
        self.docker_target = None
        self.relay = None
        self.relay_pin = None

    def docker_invocation(self, *arguments):
        if self.docker_target is None:
            if self.work is None:
                raise RuntimeError("owned local Docker target is not initialized")
            self.docker_target = LocalDocker(self.work)
        return self.docker_target.command(*arguments)

    def docker(self, *arguments):
        command, environment = self.docker_invocation(*arguments)
        try:
            result = subprocess.run(
                command,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if len(result.stdout) > 1048576:
                raise RuntimeError("owned Docker output exceeded bound")
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("owned asset Docker operation failed") from None

    def start(self):
        require_linux_ci()
        self.work = self.directory / ("minio-" + self.owner)
        self.work.mkdir(mode=0o700)
        private_json(self.work / "owner.json", {"owner": self.owner})
        # Fix and verify the local target before any download/build/mutation.
        self.docker_target = LocalDocker(self.work)
        for name in ("minio", "mc"):
            binary = download_artifact(self.work, name)
            verify_binary_version(binary, name, self.work)
        context = self.work / "image"
        context.mkdir(mode=0o700)
        data_root = context / "data-root"
        data_root.mkdir(mode=0o700)
        (data_root / "data").mkdir(mode=0o700)
        shutil.copyfile(self.work / "minio", context / "minio")
        dockerfile = (
            "FROM scratch\n"
            f'LABEL {LABEL}="{self.owner}" wso.assets.source="{SERVER_COMMIT}" wso.assets.binary="{SERVER_SHA}"\n'
            "COPY --chmod=0555 minio /minio\n"
            # BuildKit preserves the top-level copy destination's metadata.
            # Copy /data as a child so explicit ownership/mode are applied.
            "COPY --chown=65532:65532 --chmod=0700 data-root /\n"
            'USER 65532:65532\nVOLUME ["/data"]\nEXPOSE 9000\nENTRYPOINT ["/minio"]\n'
        )
        private_file(context / "Dockerfile", dockerfile.encode())
        self.created.append(("image", self.image_tag))
        self.docker("build", "--network=none", "--tag", self.image_tag, str(context))
        image = self.inspect("image", self.image_tag)
        self.image = image["Id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise RuntimeError("local image identity unavailable")
        self.assert_image(image)
        for kind, name, extra in (
            ("volume", self.volume, ()),
            ("network", self.network, ("--internal",)),
        ):
            self.created.append((kind, name))
            identity = self.docker(
                kind, "create", *extra, "--label", f"{LABEL}={self.owner}", name
            )
            if kind == "network":
                if not re.fullmatch(r"[0-9a-f]{64}", identity):
                    raise RuntimeError("owned network identity unavailable")
                self.network_id = identity
        self.env_file = self.work / "server.env"
        private_file(
            self.env_file,
            (
                f"MINIO_ROOT_USER={self.credentials['bootstrap'][0]}\nMINIO_ROOT_PASSWORD={self.credentials['bootstrap'][1]}\n"
                "MINIO_BROWSER=off\nMINIO_UPDATE=off\n"
            ).encode(),
        )
        if (
            self.env_file.stat().st_mode & 0o777 != 0o600
            or self.env_file.stat().st_uid != os.getuid()
        ):
            raise RuntimeError("bootstrap environment file is not private")
        self.created.append(("container", self.container))
        self.container_id = self.docker(
            "create",
            "--name",
            self.container,
            "--label",
            f"{LABEL}={self.owner}",
            "--network",
            self.network,
            "--log-driver",
            "none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--read-only",
            "--memory=2g",
            "--cpus=2",
            "--pids-limit=128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=0700,uid=65532,gid=65532",
            "--mount",
            f"type=volume,src={self.volume},dst=/data",
            "--env-file",
            str(self.env_file),
            self.image,
            "server",
            "/data",
            "--address",
            ":9000",
            "--console-address",
            ":9001",
            "--quiet",
        )
        if not re.fullmatch(r"[0-9a-f]{64}", self.container_id):
            raise RuntimeError("owned container identity unavailable")
        self.assert_container_mapping(self.inspect("container", self.container))
        self.verify_data_volume()
        self.docker("start", self.container)
        state = self.inspect("container", self.container)
        self.assert_container_mapping(state)
        self.relay = LoopbackRelay(self.relay_target, self.work)
        cutoff = time.monotonic() + self.relay.VALIDATION_SECONDS
        observed = self.read_relay_identity(
            cutoff, self.relay.stop, self.relay.commands
        )
        if self.relay.stop.is_set() or time.monotonic() >= cutoff:
            raise RuntimeError("owned relay startup validation cutoff")
        self.relay_pin = observed
        self.relay.start(deadline=cutoff)
        self.endpoint = "http://127.0.0.1:" + str(self.relay.address[1])
        self.configure_clients()
        deadline = time.monotonic() + 60
        while True:
            try:
                self.clients["bootstrap"].list_buckets()
                break
            except Exception:  # noqa: BLE001 -- sanitize startup provider details
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "MinIO did not become authenticated ready"
                    ) from None
                time.sleep(0.2)
        provision_users(
            self.work,
            self.endpoint,
            self.credentials,
            policy_config(self.bucket, self.prefix, self.credentials),
        )
        self.preflight()
        return self

    def configure_clients(self):
        import boto3
        from botocore.config import Config

        for name, (access, secret) in self.credentials.items():
            self.clients[name] = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                region_name="us-east-1",
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=3,
                    read_timeout=5,
                    retries={"total_max_attempts": 1},
                    s3={"addressing_style": "path"},
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )

    def inspect(self, kind, name):
        arguments = (
            ["inspect", name] if kind == "container" else [kind, "inspect", name]
        )
        data = json.loads(self.docker(*arguments))[0]
        labels = (
            data["Config"]["Labels"]
            if kind in {"container", "image"}
            else data["Labels"]
        )
        if labels.get(LABEL) != self.owner:
            raise RuntimeError("asset resource owner mismatch; cleanup refused")
        return data

    def assert_image(self, image):
        config = image["Config"]
        if (
            config["User"] != "65532:65532"
            or config["Entrypoint"] != ["/minio"]
            or config["Labels"].get("wso.assets.source") != SERVER_COMMIT
            or config["Labels"].get("wso.assets.binary") != SERVER_SHA
            or image["Os"] != "linux"
            or image["Architecture"] != "amd64"
        ):
            raise RuntimeError("owned scratch image mapping mismatch")

    def assert_container_mapping(self, state):
        host = state["HostConfig"]
        mounts = state["Mounts"]
        data = [item for item in mounts if item["Destination"] == "/data"]
        environment = dict(item.split("=", 1) for item in state["Config"]["Env"])
        temporary = host.get("Tmpfs", {}).get("/tmp", "").split(",")
        if (
            state["Name"] != "/" + self.container
            or state["Image"] != self.image
            or state["Config"]["Image"] != self.image
            or state["Config"]["User"] != "65532:65532"
            or state["Config"]["Entrypoint"] != ["/minio"]
            or state["Config"]["Cmd"]
            != [
                "server",
                "/data",
                "--address",
                ":9000",
                "--console-address",
                ":9001",
                "--quiet",
            ]
            or set(state["NetworkSettings"]["Networks"]) != {self.network}
            or host["NetworkMode"] != self.network
            or len(data) != 1
            or data[0]["Type"] != "volume"
            or data[0]["Name"] != self.volume
            or data[0]["RW"] is not True
            or any(
                item["Destination"] != "/data"
                and not (item["Destination"] == "/tmp" and item["Type"] == "tmpfs")
                for item in mounts
            )
            or host.get("Binds")
            or host.get("Devices")
            or host.get("DeviceRequests")
            or host["Privileged"] is not False
            or host["ReadonlyRootfs"] is not True
            or host["CapDrop"] != ["ALL"]
            or host["SecurityOpt"] != ["no-new-privileges:true"]
            or host["Memory"] != 2147483648
            or host["NanoCpus"] != 2000000000
            or host["PidsLimit"] != 128
            or host["LogConfig"]["Type"] != "none"
            or not no_host_bindings(host.get("PortBindings"))
            or not no_host_bindings(state["NetworkSettings"].get("Ports"))
            or set(host.get("Tmpfs", {})) != {"/tmp"}
            or len(temporary) != 8
            or set(temporary)
            != {
                "rw",
                "noexec",
                "nosuid",
                "nodev",
                "size=64m",
                "mode=0700",
                "uid=65532",
                "gid=65532",
            }
            or environment.get("MINIO_ROOT_USER") != self.credentials["bootstrap"][0]
            or environment.get("MINIO_ROOT_PASSWORD")
            != self.credentials["bootstrap"][1]
            or environment.get("MINIO_BROWSER") != "off"
            or environment.get("MINIO_UPDATE") != "off"
            or any(key.startswith("AWS_") for key in environment)
        ):
            raise RuntimeError("asset container resource mapping mismatch")
        if (
            self.inspect("volume", self.volume)["Name"] != self.volume
            or self.inspect("network", self.network).get("Internal") is not True
        ):
            raise RuntimeError("private volume/internal network mapping mismatch")
        image = self.inspect("image", self.image)
        self.assert_image(image)

    def verify_relay_identity(self, state, network):
        try:
            endpoints = state["NetworkSettings"]["Networks"]
            endpoint = endpoints[self.network]
            address = ipaddress.IPv4Address(endpoint["IPAddress"])
            configs = network["IPAM"]["Config"]
            if len(configs) != 1:
                raise ValueError
            subnet = ipaddress.IPv4Network(configs[0]["Subnet"])
            gateway = ipaddress.IPv4Address(configs[0]["Gateway"])
            membership = network["Containers"][self.container_id]
            member_address = ipaddress.IPv4Interface(membership["IPv4Address"])
            observed = (
                state["Id"],
                network["Id"],
                endpoint["EndpointID"],
                str(address),
            )
            if (
                state["Id"] != self.container_id
                or state["Name"] != "/" + self.container
                or state["Config"]["Labels"].get(LABEL) != self.owner
                or state["State"]["Running"] is not True
                or set(endpoints) != {self.network}
                or network["Id"] != self.network_id
                or network["Name"] != self.network
                or network["Labels"].get(LABEL) != self.owner
                or network["Driver"] != "bridge"
                or network["Internal"] is not True
                or network["EnableIPv6"] is not False
                or endpoint["NetworkID"] != self.network_id
                or not re.fullmatch(r"[0-9a-f]{64}", endpoint["EndpointID"])
                or endpoint.get("Gateway")
                or endpoint.get("IPv6Gateway")
                or endpoint.get("GlobalIPv6Address")
                or set(network["Containers"]) != {self.container_id}
                or membership["Name"] != self.container
                or membership["EndpointID"] != endpoint["EndpointID"]
                or membership.get("IPv6Address")
                or member_address.ip != address
                or member_address.network != subnet
                or not subnet.is_private
                or address not in subnet
                or gateway not in subnet
                or address
                in {subnet.network_address, subnet.broadcast_address, gateway}
                or address.is_unspecified
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or not address.is_private
                or not no_host_bindings(state["HostConfig"]["PortBindings"])
                or not no_host_bindings(state["NetworkSettings"]["Ports"])
                or (self.relay_pin is not None and observed != self.relay_pin)
            ):
                raise ValueError
            return observed
        except (KeyError, TypeError, ValueError, AttributeError):
            raise RuntimeError("owned relay target identity differs") from None

    def read_relay_identity(self, deadline, stop, commands):
        states = []
        for kind, identity in (
            ("container", self.container_id),
            ("network", self.network_id),
        ):
            if stop.is_set() or time.monotonic() >= deadline:
                raise RuntimeError("owned relay validation cutoff")
            arguments = (
                ("inspect", identity)
                if kind == "container"
                else (kind, "inspect", identity)
            )
            invocation, environment = self.docker_invocation(*arguments)
            result = commands.run(invocation, environment, deadline)
            if (
                not isinstance(result, list)
                or len(result) != 1
                or not isinstance(result[0], dict)
            ):
                raise RuntimeError("owned relay inspect shape differs")
            states.append(result[0])
        observed = self.verify_relay_identity(*states)
        if stop.is_set() or time.monotonic() >= deadline:
            raise RuntimeError("owned relay validation cutoff")
        return observed

    def relay_target(self, deadline, stop, commands):
        if self.relay_pin is None:
            raise RuntimeError("owned relay target not pinned")
        return self.read_relay_identity(deadline, stop, commands)[3]

    def verify_data_volume(self):
        # Before server execution the copy-up volume is empty. Docker cp supplies
        # actual tar metadata without a privileged shell/helper or host mount.
        diagnostic = {
            "stage": "invocation",
            "returncode": None,
            "archive_bytes": None,
            "entry_count": None,
            "directory": "unobserved",
            "type": "unobserved",
            "uid": None,
            "gid": None,
            "mode": None,
        }

        def numeric(value):
            return value if type(value) is int and -(2**32) < value < 2**32 else None

        try:
            command, environment = self.docker_invocation(
                "cp", self.container + ":/data", "-"
            )
            diagnostic["stage"] = "command"
            result = subprocess.run(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=15,
                check=True,
            )
            diagnostic["returncode"] = numeric(result.returncode)
            diagnostic["stage"] = "archive_bound"
            diagnostic["archive_bytes"] = numeric(len(result.stdout))
            if len(result.stdout) > 1048576:
                raise ValueError
            diagnostic["stage"] = "archive_parse"
            with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
                entries = archive.getmembers()
            diagnostic["entry_count"] = numeric(len(entries))
            if entries:
                entry = entries[0]
                diagnostic.update(
                    directory="expected_data"
                    if entry.name.rstrip("/") == "data"
                    else "unexpected",
                    type="directory"
                    if entry.isdir()
                    else "regular"
                    if entry.isfile()
                    else "symlink"
                    if entry.issym()
                    else "hardlink"
                    if entry.islnk()
                    else "other",
                    uid=numeric(entry.uid),
                    gid=numeric(entry.gid),
                    mode=numeric(entry.mode),
                )
            else:
                diagnostic.update(directory="missing", type="missing")
            diagnostic["stage"] = "entry_count"
            if len(entries) != 1:
                raise ValueError
            diagnostic["stage"] = "entry_type"
            if not entries[0].isdir():
                raise ValueError
            diagnostic["stage"] = "entry_name"
            if entries[0].name.rstrip("/") != "data":
                raise ValueError
            diagnostic["stage"] = "entry_identity"
            if (entries[0].uid, entries[0].gid, entries[0].mode) != (
                65532,
                65532,
                0o700,
            ):
                raise ValueError
        except (
            OSError,
            ValueError,
            tarfile.TarError,
            subprocess.SubprocessError,
        ) as error:
            if isinstance(error, subprocess.CalledProcessError):
                diagnostic["returncode"] = numeric(error.returncode)
            raise RuntimeError(
                "actual nonroot data volume UID/GID/mode verification failed: "
                + json.dumps(diagnostic, sort_keys=True)
            ) from None

    @staticmethod
    def error_identity(error):
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = error.response.get("Error", {}).get("Code", "unknown")
        return status, code if isinstance(code, str) and re.fullmatch(
            r"[A-Za-z0-9]{1,64}", code
        ) else "unknown"

    @staticmethod
    def denied(operation, label, *, head=False):
        from botocore.exceptions import ClientError

        try:
            result = operation()
        except ClientError as error:
            status, code = AssetProvider.error_identity(error)
            if (status, code) == (403, "AccessDenied") or (
                head and (status, code) == (403, "403")
            ):
                return
        else:
            status = (
                result.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if isinstance(result, dict)
                else None
            )
            code = "SUCCESS"
        status = status if isinstance(status, int) else None
        raise RuntimeError(
            "provider security capability failed: "
            + label
            + f" actual_status={status} actual_code={code}"
        ) from None

    @staticmethod
    def unsupported(operation):
        from botocore.exceptions import ClientError

        try:
            operation()
        except ClientError as error:
            if AssetProvider.error_identity(error) == (501, "NotImplemented"):
                return
        raise RuntimeError("pinned unsupported-control behavior differs")

    @staticmethod
    def raw_http(method, url, **kwargs):
        try:
            response = httpx.request(
                method,
                url,
                timeout=5,
                trust_env=False,
                follow_redirects=False,
                **kwargs,
            )
            return response.status_code, response.content
        except httpx.HTTPError:
            raise RuntimeError("provider private HTTP probe failed") from None

    @staticmethod
    def raw_get(url):
        return AssetProvider.raw_http("GET", url)

    @staticmethod
    def require_private_acl(response):
        owner = response.get("Owner", {})
        grants = response.get("Grants", [])
        if (
            owner.get("ID", "") != ""
            or owner.get("DisplayName", "") != ""
            or len(grants) != 1
        ):
            raise RuntimeError("synthetic private ACL shape differs")
        grant = grants[0]
        grantee = grant.get("Grantee", {})
        if (
            grant.get("Permission") != "FULL_CONTROL"
            or grantee.get("Type") != "CanonicalUser"
            or grantee.get("ID", "") != ""
            or grantee.get("DisplayName", "") != ""
            or grantee.get("URI") is not None
        ):
            raise RuntimeError("synthetic private ACL shape differs")

    def inspect_no_bucket_policy(self, diagnostic=None):
        from botocore.exceptions import ClientError

        diagnostic = diagnostic or AclDiagnostic()
        diagnostic.begin("policy_absence")
        try:
            response = self.clients["bootstrap"].get_bucket_policy(Bucket=self.bucket)
        except ClientError as error:
            diagnostic.observe(*self.error_identity(error))
            if self.error_identity(error) == (404, "NoSuchBucketPolicy"):
                return
            diagnostic.fail(
                "absence of public bucket policy could not be established",
                "STATUS_MISMATCH",
            )
        except Exception:  # noqa: BLE001 -- sanitized transport only
            diagnostic.observe(None, "TRANSPORT_ERROR")
            diagnostic.fail("private policy probe transport failed", "TRANSPORT_ERROR")
        diagnostic.observe(
            response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if isinstance(response, dict)
            else None,
            "SUCCESS",
        )
        diagnostic.fail(
            "absence of public bucket policy could not be established", "POLICY_PRESENT"
        )

    def private_effect(self, key, body, diagnostic=None):
        diagnostic = diagnostic or AclDiagnostic()
        admin = self.clients["bootstrap"]
        if diagnostic.call(
            "signed_head", lambda: admin.head_object(Bucket=self.bucket, Key=key)
        )["ContentLength"] != len(body):
            diagnostic.fail("private signed bytes length changed", "LENGTH_MISMATCH")
        stream = diagnostic.call(
            "signed_get_open", lambda: admin.get_object(Bucket=self.bucket, Key=key)
        )["Body"]
        first_failure = None
        try:
            if diagnostic.call("signed_get_read", lambda: stream.read()) != body:
                diagnostic.fail("private signed bytes changed", "BYTES_MISMATCH")
        except Exception as error:  # noqa: BLE001 -- snapshot first failure before close
            first_failure = (
                error
                if isinstance(error, AclEffectFailure)
                else AclEffectFailure(
                    "private signed bytes check failed", diagnostic.fields
                )
            )
            raise first_failure from None
        finally:
            try:
                diagnostic.call("signed_get_close", lambda: stream.close())
            except AclEffectFailure:
                if first_failure is None:
                    raise
                if isinstance(first_failure, AclEffectFailure):
                    first_failure.fields["close_failed"] = True
        response = diagnostic.call(
            "object_acl", lambda: admin.get_object_acl(Bucket=self.bucket, Key=key)
        )
        try:
            self.require_private_acl(response)
        except Exception:  # noqa: BLE001 -- fixed ACL shape, never raw grant data
            diagnostic.fail("synthetic private ACL shape differs", "ACL_SHAPE")
        for method in ("GET", "HEAD"):
            status = diagnostic.call(
                "anonymous_" + method.lower(),
                lambda method=method: self.raw_http(
                    method, f"{self.endpoint}/{self.bucket}/{key}"
                ),
            )[0]
            diagnostic.observe(status, "SUCCESS")
            if status != 403:
                diagnostic.fail(
                    "anonymous " + method + " private access was allowed",
                    "STATUS_MISMATCH",
                )

    def materialize_public_upload(self, actor, key, upload, body, diagnostic=None):
        diagnostic = diagnostic or AclDiagnostic()
        part = diagnostic.call(
            "upload_part",
            lambda: actor.upload_part(
                Bucket=self.bucket, Key=key, UploadId=upload, PartNumber=1, Body=body
            ),
        )
        etag = part.get("ETag") if isinstance(part, dict) else None
        if type(etag) is not str or not etag:
            diagnostic.fail("upload part response lacks usable identity", "UNKNOWN")
        diagnostic.call(
            "complete_multipart",
            lambda: actor.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload,
                MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": etag}]},
            ),
        )
        self.private_effect(key, body, diagnostic)

    def multipart_pages(self, actor, prefix, diagnostic=None):
        diagnostic = diagnostic or AclDiagnostic()
        rows, seen, markers = [], set(), {}
        for _ in range(1000):
            page = diagnostic.call(
                "absence_multipart_page",
                lambda markers=markers: actor.list_multipart_uploads(
                    Bucket=self.bucket, Prefix=prefix, MaxUploads=1, **markers
                ),
            )
            for row in page.get("Uploads", []):
                if (
                    not isinstance(row.get("Key"), str)
                    or not row["Key"].startswith(prefix)
                    or not isinstance(row.get("UploadId"), str)
                    or not row["UploadId"]
                ):
                    diagnostic.fail(
                        "multipart listing returned foreign or malformed row",
                        "PAGINATION_INVALID",
                    )
                rows.append(row)
            if page.get("IsTruncated") is False:
                return rows, len(seen) + 1
            next_marker = (page.get("NextKeyMarker"), page.get("NextUploadIdMarker"))
            if (
                page.get("IsTruncated") is not True
                or not all(isinstance(item, str) and item for item in next_marker)
                or next_marker in seen
            ):
                diagnostic.fail(
                    "multipart pagination checkpoint invalid", "PAGINATION_INVALID"
                )
            seen.add(next_marker)
            markers = {"KeyMarker": next_marker[0], "UploadIdMarker": next_marker[1]}
        diagnostic.fail("multipart pagination bound exceeded", "PAGINATION_INVALID")

    def object_pages(self, actor, prefix):
        rows, seen, arguments = [], set(), {}
        for _ in range(1000):
            page = actor.list_objects_v2(
                Bucket=self.bucket, Prefix=prefix, MaxKeys=1, **arguments
            )
            for row in page.get("Contents", []):
                if not isinstance(row.get("Key"), str) or not row["Key"].startswith(
                    prefix
                ):
                    raise RuntimeError("object listing returned foreign row")
                rows.append(row)
            if page.get("IsTruncated") is False:
                return rows, len(seen) + 1
            token = page.get("NextContinuationToken")
            if (
                page.get("IsTruncated") is not True
                or not isinstance(token, str)
                or not token
                or token in seen
            ):
                raise RuntimeError("object pagination checkpoint invalid")
            seen.add(token)
            arguments = {"ContinuationToken": token}
        raise RuntimeError("object pagination bound exceeded")

    def exact_absence(self, key, diagnostic=None):
        from botocore.exceptions import ClientError

        diagnostic = diagnostic or AclDiagnostic()
        diagnostic.begin("absence_head")
        admin = self.clients["bootstrap"]
        try:
            response = admin.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            diagnostic.observe(*self.error_identity(error))
            if self.error_identity(error) not in {(404, "NoSuchKey"), (404, "404")}:
                diagnostic.fail("exact absence HEAD failed", "STATUS_MISMATCH")
        except Exception:  # noqa: BLE001 -- sanitized transport only
            diagnostic.observe(None, "TRANSPORT_ERROR")
            diagnostic.fail("exact absence HEAD transport failed", "TRANSPORT_ERROR")
        else:
            diagnostic.observe(
                response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if isinstance(response, dict)
                else None,
                "SUCCESS",
            )
            diagnostic.fail("unexpected surviving object", "OBJECT_SURVIVED")
        if self.multipart_pages(admin, key, diagnostic)[0]:
            diagnostic.fail("unexpected surviving upload", "UPLOAD_SURVIVED")

    def public_attempt(self, actor, operation, arguments, diagnostic=None):
        from botocore.exceptions import ClientError

        diagnostic = diagnostic or AclDiagnostic()
        diagnostic.begin("mutation_response")
        try:
            result = getattr(actor, operation)(**arguments)
        except ClientError as error:
            status, code = self.error_identity(error)
            diagnostic.observe(status, code)
            if (status, code) not in {(403, "AccessDenied"), (501, "NotImplemented")}:
                diagnostic.fail(
                    "public mutation unexpected response", "STATUS_MISMATCH"
                )
            return False, {"status": status, "code": code}, None
        except Exception:  # noqa: BLE001 -- sanitized mutation transport only
            diagnostic.observe(None, "TRANSPORT_ERROR")
            diagnostic.fail("public mutation transport failed", "TRANSPORT_ERROR")
        status = result.get("ResponseMetadata", {}).get("HTTPStatusCode")
        diagnostic.observe(status, "SUCCESS")
        if status not in {200, 204}:
            diagnostic.fail(
                "public mutation unexpected success status", "STATUS_MISMATCH"
            )
        return True, {"status": status, "code": "accepted-inert-candidate"}, result

    def verify_public_attempt(
        self, actor, name, index, operation, arguments, original, body
    ):
        if (
            type(name) is not str
            or name not in {"bootstrap", "gateway", "cleanup"}
            or type(operation) is not str
            or operation
            not in {"put_object_acl", "put_object", "create_multipart_upload"}
            or type(index) is not int
            or not 0 <= index <= 6
        ):
            raise RuntimeError("invalid fixed ACL attempt identity") from None
        diagnostic = AclDiagnostic()
        diagnostic.target = "original" if operation == "put_object_acl" else "new"
        record = {
            "actor": name,
            "operation": operation,
            "variant": index,
            "status": None,
            "code": "UNKNOWN",
            "effects_verified": False,
        }
        self.outcomes.append(record)
        outcome = {"status": None, "code": "UNKNOWN"}
        try:
            accepted, outcome, result = self.public_attempt(
                actor, operation, arguments, diagnostic
            )
        except Exception as error:  # noqa: BLE001 -- bounded mutation attribution
            fields = (
                error.fields
                if isinstance(error, AclEffectFailure)
                else diagnostic.fields
            )
            raise RuntimeError(
                f"inert ACL effect failed actor={name} operation={operation} variant={index} status=None code=UNKNOWN diagnostic="
                + json.dumps(acl_fields(fields), sort_keys=True)
            ) from None
        record.update(status=acl_status(outcome["status"]), code=outcome["code"])
        new_key = arguments["Key"]
        try:
            if accepted and operation == "create_multipart_upload":
                diagnostic.begin("multipart_identity")
                diagnostic.observe(outcome["status"], "SUCCESS")
                upload = result.get("UploadId")
                if not isinstance(upload, str) or not upload:
                    diagnostic.fail(
                        "accepted public multipart lacks upload identity", "UNKNOWN"
                    )
                self.materialize_public_upload(actor, new_key, upload, body, diagnostic)
            elif accepted and operation == "put_object":
                diagnostic.begin("signed_head")
                self.private_effect(new_key, body, diagnostic)
            elif operation != "put_object_acl":
                self.exact_absence(new_key, diagnostic)
            diagnostic.target = "original"
            diagnostic.begin("signed_head")
            self.private_effect(original, body, diagnostic)
            admin = self.clients["bootstrap"]
            diagnostic.target = "bucket"
            response = diagnostic.call(
                "bucket_acl", lambda: admin.get_bucket_acl(Bucket=self.bucket)
            )
            try:
                self.require_private_acl(response)
            except Exception:  # noqa: BLE001 -- fixed ACL shape, never raw grant data
                diagnostic.fail("synthetic private ACL shape differs", "ACL_SHAPE")
            self.inspect_no_bucket_policy(diagnostic)
            if accepted and operation != "put_object_acl":
                diagnostic.target = "new_cleanup"
                diagnostic.call(
                    "delete_new",
                    lambda: admin.delete_object(Bucket=self.bucket, Key=new_key),
                )
                self.exact_absence(new_key, diagnostic)
        except Exception as error:  # noqa: BLE001 -- bounded effect attribution
            fields = (
                error.fields
                if isinstance(error, AclEffectFailure)
                else diagnostic.fields
            )
            raise RuntimeError(
                f"inert ACL effect failed actor={name} operation={operation} variant={index} status={acl_status(outcome['status'])} code={outcome['code']} diagnostic="
                + json.dumps(acl_fields(fields), sort_keys=True)
            ) from None
        record["effects_verified"] = True

    def control_effects(self, key, body):
        """One bounded pass, retaining every component after a failed readback.

        Signed object HEAD/bytes plus the bucket ACL establish presence of the
        owned bucket. No repair runs here. Existing one-attempt SDK/HTTP timeouts
        apply; this does not claim OS-call preemption or remote quiescence.
        """
        admin = self.clients["bootstrap"]

        def signed_head():
            if admin.head_object(Bucket=self.bucket, Key=key)["ContentLength"] != len(
                body
            ):
                raise RuntimeError("signed length differs")

        def signed_bytes():
            stream = admin.get_object(Bucket=self.bucket, Key=key)["Body"]
            try:
                if stream.read(len(body) + 1) != body:
                    raise RuntimeError("signed bytes differ")
            finally:
                stream.close()

        def anonymous(method):
            if self.raw_http(method, f"{self.endpoint}/{self.bucket}/{key}")[0] != 403:
                raise RuntimeError("anonymous access differs")

        failed = []
        for component, operation in (
            ("signed_head", signed_head),
            ("signed_bytes", signed_bytes),
            (
                "object_acl",
                lambda: self.require_private_acl(
                    admin.get_object_acl(Bucket=self.bucket, Key=key)
                ),
            ),
            (
                "bucket_acl",
                lambda: self.require_private_acl(
                    admin.get_bucket_acl(Bucket=self.bucket)
                ),
            ),
            ("policy_absence", self.inspect_no_bucket_policy),
            ("anonymous_get", partial(anonymous, "GET")),
            ("anonymous_head", partial(anonymous, "HEAD")),
        ):
            try:
                operation()
            except Exception:  # noqa: BLE001 -- finish diagnostics without raw SDK errors
                # Only fixed component enums escape; never SDK bodies or URLs.
                failed.append(component)
        return failed

    def control_attempt(self, name, operation_name, operation, key, body):
        from botocore.exceptions import ClientError

        if (
            operation_name not in CONTROL_RESULTS
            or name not in ("bootstrap", "gateway", "cleanup")
            or (name == "bootstrap" and not operation_name.startswith("get_"))
        ):
            raise RuntimeError("invalid fixed control probe identity")
        status, code = None, "TRANSPORT_ERROR"
        try:
            result = operation()
            status = (
                result.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if isinstance(result, dict)
                else None
            )
            code = "SUCCESS"
        except ClientError as error:
            try:
                status, code = self.error_identity(error)
            except Exception:  # noqa: BLE001 -- malformed SDK metadata must fail closed
                status, code = None, "TRANSPORT_ERROR"
        except Exception:  # noqa: BLE001 -- never expose raw transport/SDK exception text
            status, code = None, "TRANSPORT_ERROR"
        # Exact typed classification is separate from the bounded diagnostic enum.
        status = status if type(status) is int and 100 <= status <= 599 else None
        matched = (status, code) == CONTROL_RESULTS[operation_name]
        code = (
            code
            if code
            in {
                "AccessDenied",
                "MalformedXML",
                "NotImplemented",
                "InvalidRequest",
                "403",
                "SUCCESS",
                "TRANSPORT_ERROR",
            }
            else "UNKNOWN"
        )
        record = {
            "actor": name,
            "operation": operation_name,
            "status": status,
            "code": code,
            "response_verified": matched,
            "effects_verified": False,
        }
        self.control_outcomes.append(record)
        failed = self.control_effects(key, body)
        record["effects_verified"] = not failed
        if not matched or failed:
            raise RuntimeError(
                f"provider control probe failed actor={name} operation={operation_name} "
                f"actual_status={status} actual_code={code} "
                f"effects_verified={not failed} failed_components={','.join(failed) or 'none'}"
            ) from None

    def control_profile(self, key, body):
        admin, bucket = self.clients["bootstrap"], self.bucket
        try:
            self.inspect_no_bucket_policy()
            self.require_private_acl(admin.get_bucket_acl(Bucket=bucket))
        except Exception:  # noqa: BLE001 -- baseline failure must not expose private SDK text
            raise RuntimeError("provider control baseline privacy unverified") from None
        policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    }
                ],
            }
        )
        for name in ("gateway", "cleanup"):
            actor = self.clients[name]
            for operation_name, arguments in (
                ("put_bucket_policy", {"Policy": policy}),
                ("delete_bucket_policy", {}),
                ("put_bucket_acl", {"ACL": "private"}),
                ("put_object_acl", {"Key": key, "ACL": "private"}),
                (
                    "put_bucket_ownership_controls",
                    {
                        "OwnershipControls": {
                            "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
                        }
                    },
                ),
                ("delete_bucket_ownership_controls", {}),
                (
                    "put_public_access_block",
                    {
                        "PublicAccessBlockConfiguration": {
                            name: True
                            for name in (
                                "BlockPublicAcls",
                                "IgnorePublicAcls",
                                "BlockPublicPolicy",
                                "RestrictPublicBuckets",
                            )
                        }
                    },
                ),
                ("delete_public_access_block", {}),
                ("create_bucket", {}),
            ):
                # The two valid control PUT XML roots fail parsing before IAM.
                # Ordinary no-body CreateBucket supplies separate authority proof.
                self.control_attempt(
                    name,
                    operation_name,
                    partial(getattr(actor, operation_name), Bucket=bucket, **arguments),
                    key,
                    body,
                )
        # Exact unsupported GET behavior, not IAM enforcement. Omit bootstrap
        # PUT/DELETE queries that source routing could treat as bucket mutations.
        for name in ("bootstrap", "gateway", "cleanup"):
            actor = self.clients[name]
            for operation_name in (
                "get_bucket_ownership_controls",
                "get_public_access_block",
            ):
                self.control_attempt(
                    name,
                    operation_name,
                    partial(getattr(actor, operation_name), Bucket=bucket),
                    key,
                    body,
                )

    def privacy_profile(self, key, body):
        bucket = self.bucket
        self.control_profile(key, body)
        variants = [
            {"ACL": acl}
            for acl in ("public-read", "public-read-write", "authenticated-read")
        ]
        for group in ("AllUsers", "AuthenticatedUsers"):
            for grant in ("GrantRead", "GrantFullControl"):
                variants.append(
                    {grant: f'uri="http://acs.amazonaws.com/groups/global/{group}"'}
                )
        for name in ("bootstrap", "gateway", "cleanup"):
            actor = self.clients[name]
            for index, variant in enumerate(variants):
                existing = variant
                if "ACL" not in variant:
                    grant, header = next(iter(variant.items()))
                    # A syntactically valid known fixture canonical identifier;
                    # MinIO's synthetic empty-ID ACL is not identity authority.
                    owner = "0" * 64
                    existing = {
                        "AccessControlPolicy": {
                            "Owner": {"ID": owner},
                            "Grants": [
                                {
                                    "Grantee": {"Type": "CanonicalUser", "ID": owner},
                                    "Permission": "FULL_CONTROL",
                                },
                                {
                                    "Grantee": {"Type": "Group", "URI": header[5:-1]},
                                    "Permission": "READ"
                                    if grant == "GrantRead"
                                    else "FULL_CONTROL",
                                },
                            ],
                        }
                    }
                for operation in (
                    "put_object_acl",
                    "put_object",
                    "create_multipart_upload",
                ):
                    new_key = (
                        key
                        if operation == "put_object_acl"
                        else key + "-privacy-" + uuid4().hex
                    )
                    arguments = {
                        "Bucket": bucket,
                        "Key": new_key,
                        **(existing if operation == "put_object_acl" else variant),
                    }
                    if operation == "put_object":
                        arguments["Body"] = body
                    self.verify_public_attempt(
                        actor, name, index, operation, arguments, key, body
                    )
        if len(self.outcomes) != 63 or not all(
            row["effects_verified"] is True for row in self.outcomes
        ):
            raise RuntimeError("incomplete public grant effect matrix")
        private_json(self.work / "public-effects.json", self.outcomes)
        for method, arguments in (
            ("GET", {"params": {"list-type": "2", "prefix": self.prefix}}),
            ("PUT", {"content": b"anonymous-forbidden"}),
        ):
            url = f"{self.endpoint}/{bucket}" + ("/" + key if method == "PUT" else "")
            if self.raw_http(method, url, **arguments)[0] != 403:
                raise RuntimeError("anonymous list/write capability failed")
        self.private_effect(key, body)

    def preflight(self):
        """Real provider-only bootstrap, followed by the unchanged HTTP harness."""
        from botocore.exceptions import ClientError

        admin, gateway, cleanup = (
            self.clients[name] for name in ("bootstrap", "gateway", "cleanup")
        )
        bucket = self.bucket
        admin.create_bucket(Bucket=bucket)
        if admin.get_bucket_versioning(Bucket=bucket).get("Status") not in (
            None,
            "Suspended",
        ):
            raise RuntimeError("versioned buckets are forbidden")
        try:
            locking = admin.get_object_lock_configuration(Bucket=bucket)
        except ClientError as error:
            if self.error_identity(error) != (
                404,
                "ObjectLockConfigurationNotFoundError",
            ):
                raise RuntimeError(
                    "Object Lock profile cannot be established"
                ) from None
        else:
            if (
                locking.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled")
                == "Enabled"
            ):
                raise RuntimeError("Object Lock must be disabled")
        key = self.prefix + "capability/" + uuid4().hex
        body = b"WSOAST01" + secrets.token_bytes(128)
        gateway.put_object(Bucket=bucket, Key=key, Body=body)
        if gateway.head_object(Bucket=bucket, Key=key)["ContentLength"] != len(body):
            raise RuntimeError("gateway authenticated HEAD failed")
        stream = gateway.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            if stream.read() != body:
                raise RuntimeError("gateway authenticated GET failed")
        finally:
            stream.close()
        self.privacy_profile(key, body)
        presign = gateway.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=2
        )
        if self.raw_get(presign) != (200, body):
            raise RuntimeError("actual presigned ciphertext GET failed")
        time.sleep(3)
        if self.raw_get(presign)[0] != 403:
            raise RuntimeError("actual signed URL expiry failed")
        for operation in (
            partial(cleanup.get_object, Bucket=bucket, Key=key),
            partial(cleanup.put_object, Bucket=bucket, Key=key, Body=b"forbidden"),
        ):
            self.denied(operation, "maintenance no-read/write")
        self.denied(
            partial(cleanup.head_object, Bucket=bucket, Key=key),
            "maintenance HEAD no-read",
            head=True,
        )
        # Seed a synthetic foreign namespace and a separate owned foreign bucket.
        foreign = f"wso-assets/v1/{uuid4().hex}/foreign"
        admin.put_object(Bucket=bucket, Key=foreign, Body=b"foreign-preserved")
        foreign_upload = admin.create_multipart_upload(Bucket=bucket, Key=foreign)[
            "UploadId"
        ]
        foreign_bucket = bucket + "-foreign"
        admin.create_bucket(Bucket=foreign_bucket)
        for actor in (gateway, cleanup):
            self.denied(
                partial(actor.head_object, Bucket=bucket, Key=foreign),
                "foreign HEAD authority",
                head=True,
            )
            for operation in (
                partial(actor.get_object, Bucket=bucket, Key=foreign),
                partial(actor.delete_object, Bucket=bucket, Key=foreign),
                partial(
                    actor.put_object, Bucket=bucket, Key=foreign, Body=b"forbidden"
                ),
                partial(
                    actor.abort_multipart_upload,
                    Bucket=bucket,
                    Key=foreign,
                    UploadId=foreign_upload,
                ),
                partial(
                    actor.list_parts,
                    Bucket=bucket,
                    Key=foreign,
                    UploadId=foreign_upload,
                ),
                partial(actor.list_objects_v2, Bucket=bucket, Prefix="wso-assets/v1/"),
                partial(
                    actor.list_objects_v2, Bucket=foreign_bucket, Prefix=self.prefix
                ),
                partial(
                    actor.list_multipart_uploads,
                    Bucket=foreign_bucket,
                    Prefix=self.prefix,
                ),
            ):
                self.denied(operation, "foreign namespace/bucket authority")
        # Truthful raw bucket metadata authority; not a same-bucket prefix denial.
        raw_foreign = cleanup.list_multipart_uploads(Bucket=bucket, Prefix=foreign)
        if not any(
            row.get("UploadId") == foreign_upload
            for row in raw_foreign.get("Uploads", [])
        ):
            raise RuntimeError(
                "dedicated bucket multipart metadata observation differs"
            )
        uploads = []
        objects = [key]
        for index in range(3):
            upload_key = key + f"-page-{index}"
            gateway.put_object(Bucket=bucket, Key=upload_key, Body=body)
            objects.append(upload_key)
            upload = gateway.create_multipart_upload(Bucket=bucket, Key=upload_key)[
                "UploadId"
            ]
            part = gateway.upload_part(
                Bucket=bucket, Key=upload_key, UploadId=upload, PartNumber=1, Body=body
            )
            uploads.append((upload_key, upload, part["ETag"]))
            cleanup.list_parts(Bucket=bucket, Key=upload_key, UploadId=upload)
        object_rows, object_pages = self.object_pages(cleanup, self.prefix)
        upload_rows, upload_pages = self.multipart_pages(cleanup, self.prefix)
        if (
            object_pages < 2
            or upload_pages < 2
            or {row["Key"] for row in object_rows} != set(objects)
            or {(row["Key"], row["UploadId"]) for row in upload_rows}
            != {(item[0], item[1]) for item in uploads}
        ):
            raise RuntimeError("actual forced pagination/filter checkpoints failed")
        for index, (upload_key, upload, etag) in enumerate(uploads):
            if index == 0:
                gateway.complete_multipart_upload(
                    Bucket=bucket,
                    Key=upload_key,
                    UploadId=upload,
                    MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": etag}]},
                )
                self.private_effect(upload_key, body)
            else:
                cleanup.abort_multipart_upload(
                    Bucket=bucket, Key=upload_key, UploadId=upload
                )
        for object_key in objects:
            cleanup.delete_object(Bucket=bucket, Key=object_key)
            self.exact_absence(object_key)
        if (
            self.object_pages(cleanup, self.prefix)[0]
            or self.multipart_pages(cleanup, self.prefix)[0]
        ):
            raise RuntimeError("maintenance final prefix absence failed")
        stream = admin.get_object(Bucket=bucket, Key=foreign)["Body"]
        try:
            if stream.read() != b"foreign-preserved":
                raise RuntimeError("foreign object bytes changed")
        finally:
            stream.close()
        if not any(
            row.get("UploadId") == foreign_upload
            for row in admin.list_multipart_uploads(Bucket=bucket, Prefix=foreign).get(
                "Uploads", []
            )
        ):
            raise RuntimeError("foreign upload was altered")
        admin.abort_multipart_upload(
            Bucket=bucket, Key=foreign, UploadId=foreign_upload
        )
        admin.delete_object(Bucket=bucket, Key=foreign)
        admin.delete_bucket(Bucket=foreign_bucket)
        self.assert_container_mapping(self.inspect("container", self.container))
        if self.relay is None:
            raise RuntimeError("owned relay unavailable at acceptance")
        self.relay.assert_healthy()
        self.receipt = {
            "provider": "MinIO",
            "version": SERVER_VERSION,
            "security_profile": SECURITY_PROFILE,
            "artifact_kind": "official-binaries-local-scratch-image",
            "binary_sha256": SERVER_SHA,
            "client_version": CLIENT_VERSION,
            "client_binary_sha256": CLIENT_SHA,
            "source_commit": SERVER_COMMIT,
            "image_id": self.image,
            "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry",
            "owned_resource_mapping": True,
        }
        private_json(self.work / "provider-receipt.json", self.receipt)

    def close(self):
        failures = []
        if self.relay is not None:
            try:
                self.relay.close()
            except Exception:  # noqa: BLE001 -- never recycle under unknown relay ownership
                self.receipt = None
                # Retain exact Docker/private resources while forwarding ownership
                # is unsettled. Never recycle the target under a late worker.
                raise RuntimeError(
                    "owned relay cleanup unsettled; target retained"
                ) from None
            if self.relay.failed:
                self.receipt = None
                failures.append("relay-transport")
        for client in self.clients.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001 -- still tear down all owned resources
                failures.append("client")
        for kind, name in reversed(self.created):
            try:
                state = self.inspect(kind, name)
                if kind == "container":
                    self.assert_container_mapping(state)
                    self.docker("container", "rm", "--force", name)
                elif kind == "image":
                    self.assert_image(state)
                    if getattr(self, "image", state["Id"]) != state["Id"]:
                        raise RuntimeError("image cleanup identity differs")
                    self.docker("image", "rm", state["Id"])
                else:
                    self.docker(kind, "rm", name)
            except Exception:  # noqa: BLE001 -- finish other guarded teardown steps
                failures.append(kind)
        if self.work is not None:
            try:
                resolved = self.work.resolve()
                if (
                    resolved.parent != self.directory
                    or resolved.name != "minio-" + self.owner
                    or self.work.is_symlink()
                    or json.loads((self.work / "owner.json").read_text())["owner"]
                    != self.owner
                ):
                    raise RuntimeError("private fixture directory owner mismatch")
                shutil.rmtree(resolved)
            except Exception:  # noqa: BLE001 -- refuse foreign private file cleanup
                failures.append("private-files")
        if failures:
            raise RuntimeError(
                "owned asset resource cleanup failed: " + ", ".join(failures)
            )


def provider_only():
    import tempfile

    require_linux_ci()
    root = Path(__file__).resolve().parents[2]
    receipt = root / ".superpowers/verification/private-assets-provider-evidence.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="wso-private-assets-") as directory:
        os.chmod(directory, 0o700)
        provider = AssetProvider(directory)
        try:
            provider.start()
            evidence = dict(provider.receipt)
        finally:
            provider.close()
        private_json(receipt, evidence)
    print("actual MinIO provider preflight and owned teardown passed")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["--provider-only"]:
        raise SystemExit("requires --provider-only")
    provider_only()
