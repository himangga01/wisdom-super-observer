"""Fixed S3 command executor. Only this spawned child constructs an SDK client."""

from __future__ import annotations

import base64
import os
import socket
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from wso_core.asset_process import (
    CONTROL_CAP,
    child_request,
    child_response,
    decode_control,
    encode_control,
    exchange_owned,
    quiet_child,
)
from wso_core.storage import (
    MAX_BYTES,
    PART_BYTES,
    InstallationNamespace,
    IOBudget,
    MultipartEntry,
    MultipartPage,
    ObjectEntry,
    ObjectHead,
    ObjectLocator,
    ObjectPage,
    S3Command,
    S3Credentials,
    S3Operation,
    S3Result,
    S3RuntimeConfig,
    StorageCode,
    StorageFailure,
    UploadedPart,
    endpoint_origin,
    installation_prefix,
    object_key,
    opaque_valid,
    parse_object_key,
    validate_command,
)

_MUTATIONS = {
    "PUT",
    "DELETE",
    "CREATE_MULTIPART",
    "UPLOAD_PART",
    "COMPLETE_MULTIPART",
    "ABORT_MULTIPART",
}
_ERRORS = {
    "NOT_FOUND",
    "DENIED",
    "UNAVAILABLE",
    "DEADLINE",
    "LIMIT",
    "INTEGRITY",
    "UNSUPPORTED",
}
_MULTIPART_CURSOR_CHARS = 2 + ((4 + 1024 + 4096) * 8 + 14) // 15


def _exact(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise StorageFailure("INTEGRITY")
    return cast(dict[str, Any], value)


def _locator_wire(locator: ObjectLocator | None) -> dict[str, str] | None:
    if locator is None:
        return None
    return {key: value.hex for key, value in asdict(locator).items()}


def _locator_read(value: Any) -> ObjectLocator | None:
    if value is None:
        return None
    data = _exact(value, {"installation_id", "tenant_id", "asset_id", "attempt_id"})
    ids: list[UUID] = []
    for name in ("installation_id", "tenant_id", "asset_id", "attempt_id"):
        raw = data[name]
        if (
            type(raw) is not str
            or len(raw) != 32
            or any(c not in "0123456789abcdef" for c in raw)
        ):
            raise StorageFailure("INTEGRITY")
        ids.append(UUID(hex=raw))
    return ObjectLocator(*ids)


def _configuration(config: S3RuntimeConfig) -> dict[str, Any]:
    return {
        "endpoint_url": config.endpoint_url,
        "region": config.region,
        "credentials": asdict(config.credentials),
        "namespace": {
            "installation_id": config.namespace.installation_id.hex,
            "bucket": config.namespace.bucket,
        },
        "allow_loopback_http": config.allow_loopback_http,
    }


def _config_read(value: Any) -> S3RuntimeConfig:
    data = _exact(
        value,
        {"endpoint_url", "region", "credentials", "namespace", "allow_loopback_http"},
    )
    creds = _exact(
        data["credentials"], {"access_key_id", "secret_access_key", "session_token"}
    )
    ns = _exact(data["namespace"], {"installation_id", "bucket"})
    return S3RuntimeConfig(
        data["endpoint_url"],
        data["region"],
        S3Credentials(**creds),
        InstallationNamespace(UUID(hex=ns["installation_id"]), ns["bucket"]),
        data["allow_loopback_http"],
    )


def _command_wire(args: S3Command) -> dict[str, Any]:
    return {
        "locator": _locator_wire(args.locator),
        "upload_id": args.upload_id,
        "part_number": args.part_number,
        "has_body": args.body is not None,
        "parts": [asdict(p) for p in args.parts],
        "cursor": args.cursor,
        "limit": args.limit,
        "expires_seconds": args.expires_seconds,
        "max_bytes": args.max_bytes,
    }


def _command_read(value: Any, body: bytes) -> S3Command:
    data = _exact(
        value,
        {
            "locator",
            "upload_id",
            "part_number",
            "has_body",
            "parts",
            "cursor",
            "limit",
            "expires_seconds",
            "max_bytes",
        },
    )
    if (
        type(data["has_body"]) is not bool
        or type(data["parts"]) is not list
        or len(data["parts"]) > 10000
        or (not data["has_body"] and body)
    ):
        raise StorageFailure("INTEGRITY")
    parts = tuple(
        UploadedPart(**_exact(p, {"part_number", "etag"})) for p in data["parts"]
    )
    return S3Command(
        _locator_read(data["locator"]),
        data["upload_id"],
        data["part_number"],
        body if data["has_body"] else None,
        parts,
        data["cursor"],
        data["limit"],
        data["expires_seconds"],
        data["max_bytes"],
    )


def _cursor_encode(value: dict[str, Any]) -> str:
    if set(value) == {"key", "upload"}:
        key = value["key"]
        upload = value["upload"]
        if type(key) is not str:
            raise StorageFailure("INTEGRITY")
        opaque_valid(upload)
        key_bytes = key.encode("utf-8")
        upload_bytes = upload.encode("utf-8", "surrogatepass")
        if not 1 <= len(key_bytes) <= 1024:
            raise StorageFailure("INTEGRITY")
        raw = (
            len(key_bytes).to_bytes(2, "big")
            + len(upload_bytes).to_bytes(2, "big")
            + key_bytes
            + upload_bytes
        )
        # 15-bit words map to U+1000..U+8FFF: no controls or surrogates.
        # Every word is at most six bytes under JSON ensure_ascii escaping.
        chars: list[str] = ["M1"]
        accumulator = 0
        bits = 0
        for byte in raw:
            accumulator = (accumulator << 8) | byte
            bits += 8
            while bits >= 15:
                bits -= 15
                chars.append(chr(0x1000 + ((accumulator >> bits) & 0x7FFF)))
                accumulator &= (1 << bits) - 1
        if bits:
            chars.append(chr(0x1000 + (accumulator << (15 - bits))))
        result = "".join(chars)
        opaque_valid(result, 4096)
        return result
    result = base64.urlsafe_b64encode(encode_control(value)).decode("ascii")
    opaque_valid(result, 4096)
    return result


def _cursor_read(value: str, keys: set[str]) -> dict[str, str]:
    try:
        if keys == {"key", "upload"}:
            opaque_valid(value, 4096)
            if not value.startswith("M1") or len(value) > _MULTIPART_CURSOR_CHARS:
                raise StorageFailure("INTEGRITY")
            raw_data = bytearray()
            accumulator = 0
            bits = 0
            for character in value[2:]:
                word = ord(character) - 0x1000
                if not 0 <= word < 32768:
                    raise StorageFailure("INTEGRITY")
                accumulator = (accumulator << 15) | word
                bits += 15
                while bits >= 8:
                    bits -= 8
                    raw_data.append((accumulator >> bits) & 255)
                    accumulator &= (1 << bits) - 1
            if accumulator or len(raw_data) < 4:
                raise StorageFailure("INTEGRITY")
            key_size = int.from_bytes(raw_data[:2], "big")
            upload_size = int.from_bytes(raw_data[2:4], "big")
            payload_size = 4 + key_size + upload_size
            if (
                not 1 <= key_size <= 1024
                or not 1 <= upload_size <= 4096
                or not payload_size <= len(raw_data) <= payload_size + 1
                or any(raw_data[payload_size:])
            ):
                raise StorageFailure("INTEGRITY")
            del raw_data[payload_size:]
            marker = {
                "key": bytes(raw_data[4 : 4 + key_size]).decode("utf-8"),
                "upload": bytes(raw_data[4 + key_size :]).decode(
                    "utf-8", "surrogatepass"
                ),
            }
            opaque_valid(marker["upload"])
            if _cursor_encode(marker) != value:
                raise StorageFailure("INTEGRITY")
            return marker
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        data = _exact(decode_control(raw), keys)
        for part in data.values():
            opaque_valid(part, 2048)
        return cast(dict[str, str], data)
    except (ValueError, TypeError):
        raise StorageFailure("INTEGRITY") from None


def _multipart_page_limit() -> int:
    """Provider page cap proven against maximum accepted opaque-ID wire size."""
    prototype = {
        "locator": {
            name: "f" * 32
            for name in ("installation_id", "tenant_id", "asset_id", "attempt_id")
        },
        "upload_id": "\U0010ffff" * 1024,
        "initiated_at": "9999-12-31T23:59:59.999999+00:00",
    }
    header = {
        "ok": True,
        "result": {
            "kind": "multipart",
            "items": [],
            "next_cursor": "\u8fff" * _MULTIPART_CURSOR_CHARS,
        },
    }
    # One extra comma per entry overestimates the list delimiter cost by one.
    return (CONTROL_CAP - len(encode_control(header))) // (
        len(encode_control(prototype)) + 1
    )


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise StorageFailure("INTEGRITY")
    return value.astimezone(UTC)


def _perform(
    config: S3RuntimeConfig, operation: S3Operation, args: S3Command
) -> S3Result:
    import boto3  # type: ignore[import-untyped]
    import botocore.session  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    origin = endpoint_origin(config.endpoint_url)

    def outgoing(request: Any, **kwargs: Any) -> None:
        if endpoint_origin(request.url) != origin:
            raise StorageFailure("UNSUPPORTED", outcome_unknown=operation in _MUTATIONS)

    def response_guard(http_response: Any, parsed: Any, **kwargs: Any) -> None:
        region = http_response.headers.get("x-amz-bucket-region")
        if http_response.status_code in (301, 302, 303, 307, 308) or (
            region is not None and region != config.region
        ):
            raise StorageFailure("UNSUPPORTED", outcome_unknown=operation in _MUTATIONS)

    # Ambient profiles, credential/config files and endpoint/proxy overrides
    # never participate in this explicit private runtime configuration.
    for name in tuple(os.environ):
        if name.startswith("AWS_") or name == "BOTO_CONFIG":
            os.environ.pop(name, None)
    sdk_session = botocore.session.Session()
    sdk_session.set_config_variable("config_file", os.devnull)
    sdk_session.set_config_variable("credentials_file", os.devnull)
    client = boto3.session.Session(botocore_session=sdk_session).client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=config.credentials.access_key_id,
        aws_secret_access_key=config.credentials.secret_access_key,
        aws_session_token=config.credentials.session_token,
        verify=True,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"total_max_attempts": 1},
            proxies={},
            ignore_configured_endpoint_urls=True,
            connect_timeout=2,
            read_timeout=2,
        ),
    )
    client.meta.events.register("before-send.s3", outgoing)
    # Before redirect retry handlers; final outgoing hook is a second origin fence.
    client.meta.events.register_first(
        "needs-retry.s3", response_guard_retry(config.region, operation in _MUTATIONS)
    )
    client.meta.events.register("after-call.s3", response_guard)
    kw: dict[str, Any] = {"Bucket": config.namespace.bucket}
    if args.locator is not None:
        kw["Key"] = object_key(args.locator)
    try:
        if operation == "PUT":
            client.put_object(
                **kw, Body=args.body, ContentType="application/octet-stream"
            )
            return None
        if operation == "GET":
            assert args.max_bytes is not None
            result = client.get_object(**kw)
            stream = result["Body"]
            try:
                length = result.get("ContentLength")
                if type(length) is not int or length < 0 or length > args.max_bytes:
                    raise StorageFailure("LIMIT")
                data = bytearray()
                while True:
                    part = stream.read(min(262144, args.max_bytes + 1 - len(data)))
                    if not part:
                        break
                    data.extend(part)
                    if len(data) > args.max_bytes:
                        raise StorageFailure("LIMIT")
                if len(data) != length:
                    raise StorageFailure("INTEGRITY")
                return bytes(data)
            finally:
                stream.close()
        if operation == "HEAD":
            result = client.head_object(**kw)
            return ObjectHead(result["ContentLength"], result["ETag"])
        if operation == "DELETE":
            client.delete_object(**kw)
            return None
        if operation == "CREATE_MULTIPART":
            upload_id = client.create_multipart_upload(
                **kw, ContentType="application/octet-stream"
            )["UploadId"]
            opaque_valid(upload_id)
            return cast(str, upload_id)
        if operation == "UPLOAD_PART":
            result = client.upload_part(
                **kw,
                UploadId=args.upload_id,
                PartNumber=args.part_number,
                Body=args.body,
            )
            assert args.part_number is not None
            return UploadedPart(args.part_number, result["ETag"])
        if operation == "COMPLETE_MULTIPART":
            client.complete_multipart_upload(
                **kw,
                UploadId=args.upload_id,
                MultipartUpload={
                    "Parts": [
                        {"PartNumber": p.part_number, "ETag": p.etag}
                        for p in args.parts
                    ]
                },
            )
            return None
        if operation == "ABORT_MULTIPART":
            client.abort_multipart_upload(**kw, UploadId=args.upload_id)
            return None
        if operation == "PRESIGN_GET":
            url = client.generate_presigned_url(
                "get_object",
                Params=kw,
                ExpiresIn=args.expires_seconds,
                HttpMethod="GET",
            )
            if endpoint_origin(url) != origin:
                raise StorageFailure("UNSUPPORTED")
            return cast(str, url)
        prefix = (
            object_key(args.locator)
            if args.locator is not None
            else installation_prefix(config.namespace)
        )
        list_kw: dict[str, Any] = {"Bucket": config.namespace.bucket, "Prefix": prefix}
        if operation == "LIST_OBJECTS":
            if args.cursor is not None:
                list_kw["ContinuationToken"] = _cursor_read(args.cursor, {"token"})[
                    "token"
                ]
            result = client.list_objects_v2(**list_kw, MaxKeys=args.limit)
            objects: list[ObjectEntry] = []
            for row in result.get("Contents", []):
                locator = parse_object_key(config.namespace, row["Key"])
                if locator is not None and (
                    args.locator is None or locator == args.locator
                ):
                    objects.append(
                        ObjectEntry(locator, row["Size"], _utc(row["LastModified"]))
                    )
            cursor = (
                _cursor_encode({"token": result["NextContinuationToken"]})
                if result.get("IsTruncated")
                else None
            )
            return ObjectPage(tuple(objects), cursor)
        if operation == "LIST_MULTIPART":
            if args.cursor is not None:
                markers = _cursor_read(args.cursor, {"key", "upload"})
                if not markers["key"].startswith(prefix):
                    raise StorageFailure("INTEGRITY")
                list_kw.update(
                    KeyMarker=markers["key"], UploadIdMarker=markers["upload"]
                )
            assert args.limit is not None
            result = client.list_multipart_uploads(
                **list_kw, MaxUploads=min(args.limit, _multipart_page_limit())
            )
            uploads: list[MultipartEntry] = []
            for row in result.get("Uploads", []):
                locator = parse_object_key(config.namespace, row["Key"])
                if locator is not None and (
                    args.locator is None or locator == args.locator
                ):
                    uploads.append(
                        MultipartEntry(locator, row["UploadId"], _utc(row["Initiated"]))
                    )
            if result.get("IsTruncated") and not result["NextKeyMarker"].startswith(
                prefix
            ):
                raise StorageFailure("INTEGRITY")
            cursor = (
                _cursor_encode(
                    {
                        "key": result["NextKeyMarker"],
                        "upload": result["NextUploadIdMarker"],
                    }
                )
                if result.get("IsTruncated")
                else None
            )
            return MultipartPage(tuple(uploads), cursor)
        raise StorageFailure("INTEGRITY")
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("NoSuchKey", "NotFound", "NoSuchUpload", "404") or status == 404:
            if operation in ("DELETE", "ABORT_MULTIPART"):
                return None
            raise StorageFailure("NOT_FOUND") from None
        if code in (
            "AccessDenied",
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
        ) or status in (401, 403):
            raise StorageFailure("DENIED") from None
        if code in (
            "PermanentRedirect",
            "AuthorizationHeaderMalformed",
            "IncorrectEndpoint",
            "IllegalLocationConstraintException",
        ) or status in (301, 302, 307, 308):
            raise StorageFailure(
                "UNSUPPORTED", outcome_unknown=operation in _MUTATIONS
            ) from None
        raise StorageFailure(
            "UNAVAILABLE", outcome_unknown=operation in _MUTATIONS
        ) from None
    finally:
        client.close()


def response_guard_retry(region: str, mutating: bool) -> Any:
    def guard(response: Any = None, **kwargs: Any) -> None:
        if response is not None:
            http, _ = response
            advertised = http.headers.get("x-amz-bucket-region")
            if http.status_code in (301, 302, 303, 307, 308) or (
                advertised is not None and advertised != region
            ):
                raise StorageFailure("UNSUPPORTED", outcome_unknown=mutating)

    return guard


def _result_wire(result: S3Result) -> tuple[dict[str, Any], bytes]:
    if result is None:
        return {"kind": "none"}, b""
    if isinstance(result, bytes):
        return {"kind": "bytes"}, result
    if isinstance(result, str):
        return {"kind": "str", "value": result}, b""
    if isinstance(result, (ObjectHead, UploadedPart)):
        return {
            "kind": "head" if isinstance(result, ObjectHead) else "part",
            "value": asdict(result),
        }, b""
    items: list[dict[str, Any]] = []
    for item in result.items:
        if isinstance(item, ObjectEntry):
            items.append(
                {
                    "locator": _locator_wire(item.locator),
                    "byte_size": item.byte_size,
                    "last_modified": item.last_modified.isoformat(),
                }
            )
        else:
            items.append(
                {
                    "locator": _locator_wire(item.locator),
                    "upload_id": item.upload_id,
                    "initiated_at": item.initiated_at.isoformat(),
                }
            )
    return {
        "kind": "objects" if isinstance(result, ObjectPage) else "multipart",
        "items": items,
        "next_cursor": result.next_cursor,
    }, b""


def _result_read(control: dict[str, Any], body: bytes) -> S3Result:
    kind = control.get("kind")
    if kind == "bytes":
        _exact(control, {"kind"})
        return body
    if body:
        raise StorageFailure("INTEGRITY")
    if kind == "none":
        _exact(control, {"kind"})
        return None
    if kind == "str":
        _exact(control, {"kind", "value"})
        if type(control["value"]) is not str:
            raise StorageFailure("INTEGRITY")
        return control["value"]
    if kind in ("head", "part"):
        _exact(control, {"kind", "value"})
        if kind == "head":
            return ObjectHead(**_exact(control["value"], {"byte_size", "etag"}))
        return UploadedPart(**_exact(control["value"], {"part_number", "etag"}))
    _exact(control, {"kind", "items", "next_cursor"})
    if type(control["items"]) is not list or len(control["items"]) > 100:
        raise StorageFailure("INTEGRITY")
    if kind == "objects":
        objects: list[ObjectEntry] = []
        for value in control["items"]:
            row = _exact(value, {"locator", "byte_size", "last_modified"})
            locator = _locator_read(row["locator"])
            if locator is None:
                raise StorageFailure("INTEGRITY")
            objects.append(
                ObjectEntry(
                    locator,
                    row["byte_size"],
                    datetime.fromisoformat(row["last_modified"]),
                )
            )
        return ObjectPage(tuple(objects), control["next_cursor"])
    if kind == "multipart":
        uploads: list[MultipartEntry] = []
        for value in control["items"]:
            row = _exact(value, {"locator", "upload_id", "initiated_at"})
            locator = _locator_read(row["locator"])
            if locator is None:
                raise StorageFailure("INTEGRITY")
            uploads.append(
                MultipartEntry(
                    locator,
                    row["upload_id"],
                    datetime.fromisoformat(row["initiated_at"]),
                )
            )
        return MultipartPage(tuple(uploads), control["next_cursor"])
    raise StorageFailure("INTEGRITY")


def s3_child(sock: socket.socket) -> None:
    quiet_child()
    deadline = 0.0
    mutation = False
    try:
        control, body, deadline = child_request(sock, PART_BYTES + 36)
        _exact(control, {"version", "config", "operation", "command"})
        if type(control["version"]) is not int or control["version"] != 1:
            raise StorageFailure("INTEGRITY")
        config = _config_read(control["config"])
        op = cast(S3Operation, control["operation"])
        command = _command_read(control["command"], body)
        validate_command(op, command, config.namespace)
        mutation = op in _MUTATIONS
        result = _perform(config, op, command)
        response, data = _result_wire(result)
        child_response(
            sock, {"ok": True, "result": response}, data, MAX_BYTES + 36, deadline
        )
    except BaseException as error:  # noqa: BLE001 - sanitize SDK/transport failures
        if deadline:
            code = error.code if isinstance(error, StorageFailure) else "UNAVAILABLE"
            unknown = (
                error.outcome_unknown if isinstance(error, StorageFailure) else mutation
            )
            try:
                child_response(
                    sock,
                    {"ok": False, "code": code, "outcome_unknown": unknown},
                    b"",
                    MAX_BYTES + 36,
                    deadline,
                )
            except BaseException:  # noqa: BLE001 - disconnected private channel
                return
    finally:
        sock.close()


def execute_owned(
    config: S3RuntimeConfig, operation: S3Operation, args: S3Command, budget: IOBudget
) -> S3Result:
    mutation = operation in _MUTATIONS
    control, body = exchange_owned(
        s3_child,
        {
            "version": 1,
            "config": _configuration(config),
            "operation": operation,
            "command": _command_wire(args),
        },
        args.body or b"",
        request_cap=PART_BYTES + 36,
        response_cap=args.max_bytes
        if operation == "GET" and args.max_bytes is not None
        else 0,
        budget=budget,
        mutating=mutation,
    )
    try:
        if control.get("ok") is False:
            _exact(control, {"ok", "code", "outcome_unknown"})
            if (
                control["code"] not in _ERRORS
                or type(control["outcome_unknown"]) is not bool
                or body
            ):
                raise StorageFailure("INTEGRITY", outcome_unknown=mutation)
            raise StorageFailure(
                cast(StorageCode, control["code"]),
                outcome_unknown=control["outcome_unknown"],
            )
        _exact(control, {"ok", "result"})
        if control["ok"] is not True:
            raise StorageFailure("INTEGRITY", outcome_unknown=mutation)
        return _result_read(control["result"], body)
    except StorageFailure as error:
        if error.code == "INTEGRITY" and mutation:
            raise StorageFailure("INTEGRITY", outcome_unknown=True) from None
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StorageFailure("INTEGRITY", outcome_unknown=mutation) from None
