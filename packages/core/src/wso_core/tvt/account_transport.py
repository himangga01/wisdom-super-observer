"""Real stdlib HTTPS account transport, isolated from public routes and vaults.

No proxies, retries, redirect following, or APK-insecure TLS. Session origins
must be configured explicitly by region. DC responses produce one pending,
validated candidate; they cannot mutate the transport origin.
"""

from __future__ import annotations

import http.client
import math
import re
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from .account_protocol import (
    KNOWN_PATHS,
    MAX_BODY_BYTES,
    AccountProtocolError,
    AccountRequest,
    AccountResponse,
    parse_response,
    private_json,
)

CONTENT_TYPE = "application/json;charset=UTF-8"


class AccountTransportError(ValueError):
    """Safe fixed failure messages, with no URL/body/token interpolation."""


@dataclass(frozen=True, slots=True, repr=False)
class _Origin:
    url: str
    host: str
    port: int
    prefix: str


def _origin(value: str) -> _Origin:
    try:
        if not isinstance(value, str) or len(value) > 2048 or not value.isascii():
            raise ValueError
        if any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port or 443
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or parsed.path not in ("", "/mobile_v1.0")
            or not 1 <= port <= 65535
            or not re.fullmatch(r"[a-z0-9.-]+", host)
            or host.startswith(".")
            or host.endswith(".")
            or ".." in host
        ):
            raise ValueError
        authority = host + (f":{port}" if port != 443 else "")
        canonical = f"https://{authority}{parsed.path}"
        if canonical != value:
            raise ValueError
        return _Origin(canonical, host, port, parsed.path)
    except (ValueError, TypeError):
        pass
    raise AccountTransportError("Invalid account transport configuration.") from None


@dataclass(frozen=True, slots=True, repr=False, init=False)
class OriginPolicy:
    _regions: Mapping[str, frozenset[str]]

    def __init__(self, regions: Mapping[str, frozenset[str]]) -> None:
        checked: dict[str, frozenset[str]] = {}
        if not regions or len(regions) > 64:
            raise AccountTransportError("Invalid account transport configuration.")
        for region, origins in regions.items():
            if (
                not isinstance(region, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", region)
                or not origins
                or len(origins) > 64
            ):
                raise AccountTransportError("Invalid account transport configuration.")
            checked[region] = frozenset(_origin(value).url for value in origins)
        object.__setattr__(self, "_regions", MappingProxyType(checked))

    def resolve(self, region: str, origin: str) -> _Origin:
        candidate = _origin(origin)
        if not isinstance(region, str) or candidate.url not in self._regions.get(
            region, ()
        ):
            raise AccountTransportError("Invalid account transport configuration.")
        return candidate


class AccountTransport(Protocol):
    def send(self, request: AccountRequest) -> AccountResponse: ...


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_BODY_BYTES:
        raise AccountTransportError("Invalid account transport configuration.")
    return value


class HttpsAccountTransport:
    def __init__(
        self,
        policy: OriginPolicy,
        *,
        region: str,
        origin: str,
        timeout_seconds: float = 10,
        max_body_bytes: int = 65_536,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._origin = policy.resolve(region, origin)
        if (
            type(timeout_seconds) not in (int, float)
            or not 0 < timeout_seconds <= 60
            or not math.isfinite(timeout_seconds)
        ):
            raise AccountTransportError("Invalid account transport configuration.")
        self._timeout = float(timeout_seconds)
        self._max_body = _limit(max_body_bytes)
        self._monotonic = monotonic
        self._tls = ssl.create_default_context()
        if self._tls.verify_mode != ssl.CERT_REQUIRED or not self._tls.check_hostname:
            raise AccountTransportError("Invalid account transport configuration.")

    @property
    def origin(self) -> str:
        """Trusted configuration only; no untrusted response can change this value."""
        return self._origin.url

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise AccountTransportError("Account request deadline exceeded.")
        return min(remaining, self._timeout)

    def _socket_deadline(
        self, connection: http.client.HTTPSConnection, deadline: float
    ) -> None:
        timeout = self._remaining(deadline)
        if connection.sock is not None:
            connection.sock.settimeout(timeout)

    def send(self, request: AccountRequest) -> AccountResponse:
        if (
            request.path not in KNOWN_PATHS
            or not isinstance(request.body, bytes)
            or len(request.body) > MAX_BODY_BYTES
        ):
            raise AccountTransportError("Invalid account request.")
        deadline = self._monotonic() + self._timeout
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(
                self._origin.host,
                self._origin.port,
                timeout=self._remaining(deadline),
                context=self._tls,
            )
            connection.connect()
            self._socket_deadline(connection, deadline)
            connection.request(
                "POST",
                self._origin.prefix + request.path,
                body=request.body,
                headers={"Content-Type": CONTENT_TYPE},
            )
            self._socket_deadline(connection, deadline)
            response = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while True:
                self._socket_deadline(connection, deadline)
                chunk = response.read1(min(8192, self._max_body + 1 - size))
                self._remaining(deadline)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > self._max_body:
                    raise AccountTransportError("Account response exceeded its limit.")
            return parse_response(
                response.status, b"".join(chunks), max_body_bytes=self._max_body
            )
        except (AccountProtocolError, AccountTransportError):
            raise
        except (OSError, http.client.HTTPException, ValueError):
            pass
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass
        raise AccountTransportError("Account transport failed.") from None


@dataclass(frozen=True, slots=True)
class DcRedirectCandidate:
    origin: str = field(repr=False)
    private_body: bytes = field(repr=False)


class PendingDcRedirect:
    """One pending candidate per instance. Caller owns any later explicit adoption."""

    def __init__(self) -> None:
        self._candidate: DcRedirectCandidate | None = None
        self._lock = threading.Lock()

    def offer(
        self, response: AccountResponse, policy: OriginPolicy, *, region: str
    ) -> DcRedirectCandidate:
        with self._lock:
            if self._candidate is not None:
                raise AccountTransportError("Account redirect is already pending.")
            try:
                if response.native_msgcode != 404:
                    raise ValueError
                data = private_json(response.private_body).get("data")
                if not isinstance(data, dict) or data.get("httpPrefix") != "https://":
                    raise ValueError
                domain = data.get("domain", "")
                host = domain or data.get("dcIp") or data.get("ip")
                if not isinstance(host, str) or not host:
                    raise ValueError
                port = data.get("dcPort", 0)
                if type(port) is not int:
                    raise ValueError
                if port == 0:
                    port = data.get("port", 0)
                if type(port) is not int or not 0 <= port <= 65535:
                    raise ValueError
                suffix = f":{port}" if port not in (0, 443) else ""
                origin = policy.resolve(region, f"https://{host}{suffix}/mobile_v1.0")
                # chain remains private raw bytes: type and semantics are unknown.
                candidate = DcRedirectCandidate(origin.url, response.private_body)
                self._candidate = candidate
                return candidate
            except (ValueError, TypeError):
                pass
        raise AccountTransportError("Invalid account redirect candidate.") from None
