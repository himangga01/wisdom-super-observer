"""Owned SeaweedFS capability probe. Never substitute an in-memory S3 service."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from functools import partial
from pathlib import Path
from uuid import uuid4

import httpx

LABEL = "wso.assets.owner"
IMAGE = "chrislusf/seaweedfs:4.47"
SECURITY_PROFILE = "seaweedfs-private-iam-ownership-v1"


def private_json(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream)


def policy_config(bucket, prefix, identities):
    """Static IAM policy documents, deliberately without legacy coarse Actions."""
    bucket_arn = f"arn:aws:s3:::{bucket}"
    object_arn = f"{bucket_arn}/{prefix}*"
    definitions = {
        "bootstrap": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}],
        "gateway": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": object_arn,
            },
        ],
        "cleanup": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": object_arn,
            },
        ],
    }
    for name in ("gateway", "cleanup"):
        definitions[name].append(
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads"],
                "Resource": bucket_arn,
                "Condition": {"StringLike": {"s3:prefix": [prefix, prefix + "*"]}},
            }
        )
    return {
        "identities": [
            {
                "name": name,
                "credentials": [
                    {"accessKey": credentials[0], "secretKey": credentials[1]}
                ],
                "policyNames": [name],
                "account": {"id": "asset-fixture", "displayName": "asset-fixture"},
            }
            for name, credentials in identities.items()
        ],
        "policies": [
            {
                "name": name,
                "content": json.dumps(
                    {"Version": "2012-10-17", "Statement": statements}
                ),
            }
            for name, statements in definitions.items()
        ],
    }


class AssetProvider:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.owner = uuid4().hex
        self.installation_id = uuid4()
        self.bucket = "wso-assets-" + self.owner
        self.prefix = f"wso-assets/v1/{self.installation_id.hex}/"
        self.volume = f"wso-assets-data-{self.owner}"
        self.container = f"wso-assets-s3-{self.owner}"
        self.network = f"wso-assets-net-{self.owner}"
        self.created = []
        self.clients = {}
        self.credentials = {
            name: (secrets.token_hex(12), secrets.token_hex(32))
            for name in ("bootstrap", "gateway", "cleanup")
        }
        self.receipt = None

    def docker(self, *arguments):
        try:
            result = subprocess.run(
                ["docker", *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("owned asset Docker operation failed") from None

    def start(self):
        self.docker("pull", IMAGE)
        image = json.loads(self.docker("image", "inspect", IMAGE))[0]
        digests = [
            digest
            for digest in image["RepoDigests"]
            if re.fullmatch(
                r"(?:docker.io/)?chrislusf/seaweedfs@sha256:[0-9a-f]{64}", digest
            )
        ]
        if len(digests) != 1:
            raise RuntimeError("SeaweedFS immutable image digest unavailable")
        self.image = digests[0]
        version = self.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/usr/bin/weed",
            self.image,
            "version",
        )
        if not re.search(r"\b4\.47\b", version):
            raise RuntimeError("SeaweedFS executable version differs from 4.47")
        config = self.directory / "s3-identities.json"
        private_json(config, policy_config(self.bucket, self.prefix, self.credentials))
        for kind, name in (("volume", self.volume), ("network", self.network)):
            self.docker(kind, "create", "--label", f"{LABEL}={self.owner}", name)
            self.created.append((kind, name))
        self.docker(
            "run",
            "--detach",
            "--name",
            self.container,
            "--label",
            f"{LABEL}={self.owner}",
            "--network",
            self.network,
            "--log-driver",
            "none",
            "--publish",
            "127.0.0.1::8333",
            "--mount",
            f"type=volume,src={self.volume},dst=/data",
            "--mount",
            f"type=bind,src={config},dst=/etc/wso-s3.json,readonly",
            "--entrypoint",
            "/usr/bin/weed",
            self.image,
            "server",
            "-dir=/data",
            "-volume.max=2",
            "-master.volumeSizeLimitMB=64",
            "-ip=127.0.0.1",
            "-ip.bind=0.0.0.0",
            "-s3",
            "-s3.config=/etc/wso-s3.json",
        )
        self.created.append(("container", self.container))
        state = self.inspect("container", self.container)
        if any(
            value.startswith(("AWS_ACCESS_KEY_ID=", "AWS_SECRET_ACCESS_KEY="))
            for value in state["Config"]["Env"]
        ):
            raise RuntimeError("SeaweedFS ambient admin fallback is forbidden")
        ports = state["NetworkSettings"]["Ports"]["8333/tcp"]
        if len(ports) != 1 or ports[0]["HostIp"] != "127.0.0.1":
            raise RuntimeError("asset provider must bind only loopback")
        self.endpoint = "http://127.0.0.1:" + ports[0]["HostPort"]
        self.assert_container_mapping(state, config)
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
        deadline = time.monotonic() + 60
        while True:
            try:
                self.clients["bootstrap"].list_buckets()
                break
            except Exception:  # noqa: BLE001 -- retry startup without provider details
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "SeaweedFS did not become authenticated ready"
                    ) from None
                time.sleep(0.2)
        self.preflight()
        return self

    def inspect(self, kind, name):
        arguments = (
            ["inspect", name] if kind == "container" else [kind, "inspect", name]
        )
        data = json.loads(self.docker(*arguments))[0]
        labels = data["Config"]["Labels"] if kind == "container" else data["Labels"]
        if labels.get(LABEL) != self.owner:
            raise RuntimeError("asset resource owner mismatch; cleanup refused")
        return data

    def assert_container_mapping(self, state, config):
        mounts = {mount["Destination"]: mount for mount in state["Mounts"]}
        if (
            state["Name"] != "/" + self.container
            or state["Config"]["Image"] != self.image
            or set(state["NetworkSettings"]["Networks"]) != {self.network}
            or mounts["/data"]["Type"] != "volume"
            or mounts["/data"]["Name"] != self.volume
            or mounts["/data"]["RW"] is not True
            or mounts["/etc/wso-s3.json"]["Type"] != "bind"
            or mounts["/etc/wso-s3.json"]["Source"] != str(config)
            or mounts["/etc/wso-s3.json"]["RW"] is not False
        ):
            raise RuntimeError("asset container resource mapping mismatch")
        self.inspect("volume", self.volume)
        self.inspect("network", self.network)

    @staticmethod
    def denied(operation, label, *, ownership=False):
        from botocore.exceptions import ClientError

        try:
            operation()
        except ClientError as error:
            denial = (
                error.response["ResponseMetadata"]["HTTPStatusCode"],
                error.response["Error"]["Code"],
            )
            if denial in {(403, "AccessDenied"), (403, "403")} or (
                ownership and denial == (400, "AccessControlListNotSupported")
            ):
                return
        raise RuntimeError("provider security capability failed: " + label)

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

    def configure_ownership(self):
        from botocore.exceptions import ClientError

        admin = self.clients["bootstrap"]
        enforced = {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
        try:
            admin.put_bucket_ownership_controls(
                Bucket=self.bucket, OwnershipControls=enforced
            )
            observed = admin.get_bucket_ownership_controls(Bucket=self.bucket)
        except ClientError:
            raise RuntimeError("required ownership API failed") from None
        if observed.get("OwnershipControls") != enforced:
            raise RuntimeError(
                "required ownership readback differs from BucketOwnerEnforced"
            )

    @staticmethod
    def require_private_acl(response):
        owner = response.get("Owner", {}).get("ID")
        grants = response.get("Grants", [])
        if (
            not isinstance(owner, str)
            or not owner
            or len(grants) != 1
            or grants[0].get("Permission") != "FULL_CONTROL"
            or grants[0].get("Grantee", {}).get("Type") != "CanonicalUser"
            or grants[0]["Grantee"].get("ID") != owner
            or grants[0]["Grantee"].get("URI") is not None
        ):
            raise RuntimeError("ACL is not private owner-only full control")

    def inspect_no_bucket_policy(self):
        from botocore.exceptions import ClientError

        try:
            self.clients["bootstrap"].get_bucket_policy(Bucket=self.bucket)
        except ClientError as error:
            if (
                error.response["ResponseMetadata"]["HTTPStatusCode"] == 404
                and error.response["Error"]["Code"] == "NoSuchBucketPolicy"
            ):
                return
        raise RuntimeError("absence of public bucket policy could not be established")

    def privacy_profile(self, key, body):
        """Real valid-public-grant attempts, with no unsupported-operation fallback."""
        admin = self.clients["bootstrap"]
        bucket = self.bucket
        self.inspect_no_bucket_policy()
        self.require_private_acl(admin.get_bucket_acl(Bucket=bucket))
        object_acl = admin.get_object_acl(Bucket=bucket, Key=key)
        self.require_private_acl(object_acl)
        owner_id = object_acl["Owner"]["ID"]
        public_policy = json.dumps(
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
            client = self.clients[name]
            for operation in (
                partial(client.put_bucket_acl, Bucket=bucket, ACL="private"),
                partial(client.put_object_acl, Bucket=bucket, Key=key, ACL="private"),
                partial(
                    client.put_bucket_ownership_controls,
                    Bucket=bucket,
                    OwnershipControls={"Rules": [{"ObjectOwnership": "ObjectWriter"}]},
                ),
                partial(client.delete_bucket_ownership_controls, Bucket=bucket),
                partial(client.put_bucket_policy, Bucket=bucket, Policy=public_policy),
                partial(client.delete_bucket_policy, Bucket=bucket),
            ):
                self.denied(operation, name + " administrative mutation denial")
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
            client = self.clients[name]
            for variant in variants:
                existing_variant = variant
                if "ACL" not in variant:
                    grant_name, uri_header = next(iter(variant.items()))
                    existing_variant = {
                        "AccessControlPolicy": {
                            "Owner": {"ID": owner_id},
                            "Grants": [
                                {
                                    "Grantee": {
                                        "Type": "CanonicalUser",
                                        "ID": owner_id,
                                    },
                                    "Permission": "FULL_CONTROL",
                                },
                                {
                                    "Grantee": {
                                        "Type": "Group",
                                        "URI": uri_header[5:-1],
                                    },
                                    "Permission": "READ"
                                    if grant_name == "GrantRead"
                                    else "FULL_CONTROL",
                                },
                            ],
                        }
                    }
                # Each new key stays within this owned installation. If a probe
                # unexpectedly succeeds, setup fails and guarded volume teardown
                # removes all bytes/uploads; there is no passing-profile receipt.
                new_key = key + "-privacy-" + uuid4().hex
                for operation in (
                    partial(
                        client.put_object_acl,
                        Bucket=bucket,
                        Key=key,
                        **existing_variant,
                    ),
                    partial(
                        client.put_object,
                        Bucket=bucket,
                        Key=new_key,
                        Body=body,
                        **variant,
                    ),
                    partial(
                        client.create_multipart_upload,
                        Bucket=bucket,
                        Key=new_key,
                        **variant,
                    ),
                ):
                    self.denied(
                        operation, name + " public ACL/grant refusal", ownership=True
                    )
                if admin.list_objects_v2(Bucket=bucket, Prefix=new_key).get("Contents"):
                    raise RuntimeError("denied public PUT left an object")
                if admin.list_multipart_uploads(Bucket=bucket, Prefix=new_key).get(
                    "Uploads"
                ):
                    raise RuntimeError("denied public multipart left an upload")
        object_url = f"{self.endpoint}/{bucket}/{key}"
        bucket_url = f"{self.endpoint}/{bucket}"
        for method, url, arguments in (
            ("GET", object_url, {}),
            ("HEAD", object_url, {}),
            ("GET", bucket_url, {"params": {"list-type": "2", "prefix": self.prefix}}),
            ("PUT", object_url, {"content": b"anonymous-forbidden"}),
        ):
            if self.raw_http(method, url, **arguments)[0] != 403:
                raise RuntimeError(
                    "anonymous " + method + " private access was allowed"
                )
        self.require_private_acl(admin.get_bucket_acl(Bucket=bucket))
        self.require_private_acl(admin.get_object_acl(Bucket=bucket, Key=key))
        self.inspect_no_bucket_policy()
        enforced = {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
        if (
            admin.get_bucket_ownership_controls(Bucket=bucket).get("OwnershipControls")
            != enforced
        ):
            raise RuntimeError("runtime probe changed enforced ownership")
        stream = admin.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            if stream.read() != body:
                raise RuntimeError("privacy probe modified private ciphertext")
        finally:
            stream.close()

    def preflight(self):
        """Every receipt below represents an actual provider request."""
        from botocore.exceptions import ClientError

        admin, gateway, cleanup = (
            self.clients[name] for name in ("bootstrap", "gateway", "cleanup")
        )
        bucket = self.bucket
        admin.create_bucket(Bucket=bucket, ACL="private")
        self.configure_ownership()
        if admin.get_bucket_versioning(Bucket=bucket).get("Status") not in (
            None,
            "Suspended",
        ):
            raise RuntimeError("versioned buckets are forbidden in asset fixture")
        try:
            locking = admin.get_object_lock_configuration(Bucket=bucket)
        except ClientError as error:
            if (
                error.response["Error"]["Code"]
                != "ObjectLockConfigurationNotFoundError"
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
            raise RuntimeError("provider authenticated HEAD failed")
        stream = gateway.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            if stream.read() != body:
                raise RuntimeError("provider authenticated GET failed")
        finally:
            stream.close()
        self.privacy_profile(key, body)
        presign = gateway.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=2
        )
        status, downloaded = self.raw_get(presign)
        if status != 200 or downloaded != body:
            raise RuntimeError("provider actual presigned ciphertext GET failed")
        time.sleep(3)
        if self.raw_get(presign)[0] != 403:
            raise RuntimeError("provider actual presigned URL expiry failed")
        if self.raw_get(f"{self.endpoint}/{bucket}/{key}")[0] != 403:
            raise RuntimeError("anonymous ciphertext access was allowed")
        for operation in (
            lambda: cleanup.get_object(Bucket=bucket, Key=key),
            lambda: cleanup.head_object(Bucket=bucket, Key=key),
            lambda: cleanup.put_object(Bucket=bucket, Key=key, Body=b"forbidden"),
        ):
            self.denied(operation, "cleanup read/write denial")
        uploads = []
        for complete in (True, False):
            upload_key = key + ("-complete" if complete else "-abort")
            upload = gateway.create_multipart_upload(Bucket=bucket, Key=upload_key)[
                "UploadId"
            ]
            uploads.append((upload_key, upload))
            part = gateway.upload_part(
                Bucket=bucket, Key=upload_key, UploadId=upload, PartNumber=1, Body=body
            )
            listed = cleanup.list_multipart_uploads(Bucket=bucket, Prefix=self.prefix)
            if not any(row["UploadId"] == upload for row in listed.get("Uploads", [])):
                raise RuntimeError("cleanup multipart listing failed")
            cleanup.list_parts(Bucket=bucket, Key=upload_key, UploadId=upload)
            if complete:
                gateway.complete_multipart_upload(
                    Bucket=bucket,
                    Key=upload_key,
                    UploadId=upload,
                    MultipartUpload={
                        "Parts": [{"PartNumber": 1, "ETag": part["ETag"]}]
                    },
                )
                cleanup.delete_object(Bucket=bucket, Key=upload_key)
            else:
                cleanup.abort_multipart_upload(
                    Bucket=bucket, Key=upload_key, UploadId=upload
                )
        foreign = f"wso-assets/v1/{uuid4().hex}/foreign"
        admin.put_object(Bucket=bucket, Key=foreign, Body=b"foreign-preserved")
        foreign_upload = admin.create_multipart_upload(Bucket=bucket, Key=foreign)[
            "UploadId"
        ]
        for operation in (
            lambda: cleanup.delete_object(Bucket=bucket, Key=foreign),
            lambda: cleanup.get_object(Bucket=bucket, Key=foreign),
            lambda: cleanup.head_object(Bucket=bucket, Key=foreign),
            lambda: cleanup.put_object(Bucket=bucket, Key=foreign, Body=b"forbidden"),
            lambda: cleanup.abort_multipart_upload(
                Bucket=bucket, Key=foreign, UploadId=foreign_upload
            ),
            lambda: cleanup.list_objects_v2(Bucket=bucket, Prefix="wso-assets/v1/"),
            lambda: cleanup.list_multipart_uploads(
                Bucket=bucket, Prefix="wso-assets/v1/"
            ),
            lambda: gateway.put_object(Bucket=bucket, Key=foreign, Body=b"forbidden"),
        ):
            self.denied(operation, "foreign prefix denial")
        cleanup.delete_object(Bucket=bucket, Key=key)
        if cleanup.list_objects_v2(Bucket=bucket, Prefix=key).get("Contents"):
            raise RuntimeError("cleanup consistent exact-key absence failed")
        if cleanup.list_multipart_uploads(Bucket=bucket, Prefix=key).get("Uploads"):
            raise RuntimeError("cleanup incomplete upload absence failed")
        if admin.head_object(Bucket=bucket, Key=foreign)["ContentLength"] != len(
            b"foreign-preserved"
        ):
            raise RuntimeError("foreign prefix was altered")
        admin.abort_multipart_upload(
            Bucket=bucket, Key=foreign, UploadId=foreign_upload
        )
        admin.delete_object(Bucket=bucket, Key=foreign)
        self.receipt = {
            "provider": "SeaweedFS",
            "version": "4.47",
            "digest": self.image,
            "security_profile": SECURITY_PROFILE,
            "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry",
        }
        private_json(self.directory / "provider-receipt.json", self.receipt)

    def close(self):
        failures = []
        for client in self.clients.values():
            client.close()
        for kind, name in reversed(self.created):
            try:
                state = self.inspect(kind, name)
                if kind == "container":
                    self.assert_container_mapping(
                        state, self.directory / "s3-identities.json"
                    )
                    self.docker("container", "rm", "--force", name)
                else:
                    self.docker(kind, "rm", name)
            except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
                failures.append(kind)
        if failures:
            raise RuntimeError(
                "owned asset resource cleanup failed: " + ", ".join(failures)
            )
