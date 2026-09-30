"""Verified OIDC exchange and opaque, database-backed web sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from wso_core.tenancy import identity_session

SESSION_COOKIE = "__Host-wso-session"
CSRF_COOKIE = "__Host-wso-csrf"


class AuthFailure(Exception):
    def __init__(self, status: int = 401, code: str = "unauthenticated") -> None:
        self.status = status
        self.code = code


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    audience: str
    jwks_url: str
    exchange_key: str = field(repr=False)
    public_origin: str
    session_database_url: str = field(repr=False)
    max_session_seconds: int = 28800

    def __post_init__(self) -> None:
        for url in (self.issuer, self.jwks_url, self.public_origin):
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                raise ValueError("HTTPS authentication configuration required")
        origin = urlsplit(self.public_origin)
        if origin.path or origin.query or origin.fragment:
            raise ValueError("public origin must be an exact origin")
        if not self.audience or len(self.exchange_key) < 32:
            raise ValueError("authentication configuration incomplete")
        if not self.session_database_url.startswith("postgresql+psycopg://"):
            raise ValueError("explicit PostgreSQL session URL required")
        if not 1 <= self.max_session_seconds <= 28800:
            raise ValueError("session lifetime out of range")

    @classmethod
    def from_environment(cls) -> AuthSettings:
        for name in ("WSO_IDENTITY_DATABASE_URL", "WSO_APP_DATABASE_URL"):
            if not os.environ[name].startswith("postgresql+psycopg://"):
                raise ValueError("explicit restricted PostgreSQL role URLs required")
        return cls(
            issuer=os.environ["WSO_OIDC_ISSUER"],
            audience=os.environ["WSO_OIDC_CLIENT_ID"],
            jwks_url=os.environ["WSO_OIDC_JWKS_URL"],
            exchange_key=os.environ["WSO_AUTH_EXCHANGE_KEY"],
            public_origin=os.environ["WSO_PUBLIC_ORIGIN"],
            session_database_url=os.environ["WSO_SESSION_DATABASE_URL"],
        )


@dataclass(frozen=True)
class VerifiedPrincipal:
    issuer: str
    subject: str
    expires_at: datetime


class OIDCVerifier:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        key_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._jwks = jwt.PyJWKClient(settings.jwks_url, timeout=5)
        self._key_resolver = key_resolver or (
            lambda token: self._jwks.get_signing_key_from_jwt(token).key
        )

    def verify(self, token: str, nonce: str) -> VerifiedPrincipal:
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise AuthFailure()
            claims = jwt.decode(
                token,
                self._key_resolver(token),
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.audience,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
            token_nonce = claims.get("nonce")
            if (
                not isinstance(token_nonce, str)
                or not nonce
                or not hmac.compare_digest(token_nonce.encode(), nonce.encode())
                or not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 255
                or isinstance(claims["exp"], bool)
                or isinstance(claims["iat"], bool)
                or not isinstance(claims["iat"], (int, float))
            ):
                raise AuthFailure()
            audiences = claims["aud"]
            if (
                (isinstance(audiences, list) and len(audiences) > 1) or "azp" in claims
            ) and claims.get("azp") != self.settings.audience:
                raise AuthFailure()
            return VerifiedPrincipal(
                self.settings.issuer,
                claims["sub"],
                datetime.fromtimestamp(claims["exp"], tz=UTC),
            )
        except AuthFailure:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, OSError) as exc:
            raise AuthFailure() from exc


@dataclass(frozen=True)
class WebSession:
    issuer: str
    subject: str
    user_id: UUID
    csrf_digest: str = field(repr=False)
    expires_at: datetime


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore(Protocol):
    def create(
        self, digest: str, session: WebSession, exchange_digest: str
    ) -> bool: ...
    def get(self, digest: str) -> WebSession | None: ...
    def revoke(self, digest: str, csrf_digest: str) -> bool: ...


class PostgresSessionStore:
    """Only function calls are available to the dedicated session DB role."""

    def __init__(
        self, url: str, *, session_factory: sessionmaker[Session] | None = None
    ) -> None:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("explicit PostgreSQL session URL required")
        self._factory = session_factory or sessionmaker(
            create_engine(url, pool_pre_ping=True)
        )

    @staticmethod
    def _check_role(session: Session) -> None:
        if (
            session.execute(text("SELECT current_user")).scalar_one()
            != "wso_web_session"
        ):
            raise AuthFailure(503, "auth_unavailable")

    def create(self, digest: str, session: WebSession, exchange_digest: str) -> bool:
        with self._factory.begin() as db:
            self._check_role(db)
            return bool(
                db.execute(
                    text(
                        "SELECT public.wso_create_web_session(:digest, :csrf, :issuer, "
                        ":subject, :user_id, :expires_at, :exchange_digest)"
                    ),
                    {
                        "digest": digest,
                        "csrf": session.csrf_digest,
                        "issuer": session.issuer,
                        "subject": session.subject,
                        "user_id": session.user_id,
                        "expires_at": session.expires_at,
                        "exchange_digest": exchange_digest,
                    },
                ).scalar_one()
            )

    def get(self, digest: str) -> WebSession | None:
        with self._factory.begin() as db:
            self._check_role(db)
            row = db.execute(
                text("SELECT * FROM public.wso_get_web_session(:digest)"),
                {"digest": digest},
            ).first()
            return (
                None
                if row is None
                else WebSession(
                    row.issuer,
                    row.subject,
                    row.user_id,
                    row.csrf_digest,
                    row.expires_at,
                )
            )

    def revoke(self, digest: str, csrf_digest: str) -> bool:
        with self._factory.begin() as db:
            self._check_role(db)
            return bool(
                db.execute(
                    text("SELECT public.wso_revoke_web_session(:digest, :csrf)"),
                    {"digest": digest, "csrf": csrf_digest},
                ).scalar_one()
            )


class AuthService:
    def __init__(
        self,
        settings: AuthSettings,
        verifier: OIDCVerifier,
        sessions: SessionStore,
        *,
        identity_factory: sessionmaker[Session] | None = None,
        tenant_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.settings, self.verifier, self.sessions = settings, verifier, sessions
        self.identity_factory, self.tenant_factory = identity_factory, tenant_factory

    def identity(self, session: WebSession | VerifiedPrincipal) -> Any:
        return identity_session(
            session.issuer, session.subject, session_factory=self.identity_factory
        )

    def exchange(
        self, token: str, nonce: str, internal_key: str | None
    ) -> dict[str, Any]:
        if not internal_key or not hmac.compare_digest(
            internal_key.encode(), self.settings.exchange_key.encode()
        ):
            raise AuthFailure()
        principal = self.verifier.verify(token, nonce)
        # Verification must finish before opening the restricted identity pool.
        with self.identity(principal) as lookup:
            user_id = lookup.user_id()
        if user_id is None:
            raise AuthFailure(403, "principal_not_provisioned")
        expires = min(
            principal.expires_at,
            datetime.now(UTC) + timedelta(seconds=self.settings.max_session_seconds),
        )
        session_token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        created = self.sessions.create(
            token_digest(session_token),
            WebSession(
                principal.issuer,
                principal.subject,
                user_id,
                token_digest(csrf_token),
                expires,
            ),
            token_digest(json.dumps([principal.issuer, nonce], separators=(",", ":"))),
        )
        if not created:
            raise AuthFailure()
        return {
            "session_id": session_token,
            "csrf_token": csrf_token,
            "expires_at": expires,
        }

    def authenticate(self, request: Request) -> WebSession:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or len(token) > 128:
            raise AuthFailure()
        session = self.sessions.get(token_digest(token))
        if session is None or session.expires_at <= datetime.now(UTC):
            raise AuthFailure()
        return session


def configure_auth(app: FastAPI, service: AuthService | None = None) -> None:
    """Missing environment stays fail closed; configuration never falls back."""
    if service is None:
        try:
            settings = AuthSettings.from_environment()
            service = AuthService(
                settings,
                OIDCVerifier(settings),
                PostgresSessionStore(settings.session_database_url),
            )
        except (KeyError, ValueError):
            pass
    app.state.auth_service = service

    @app.exception_handler(AuthFailure)
    async def auth_failure(request: Request, exc: AuthFailure) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": "Authentication unavailable"
                    if exc.status == 503
                    else "Request failed",
                },
                "request_id": getattr(request.state, "request_id", ""),
            },
            headers={"Cache-Control": "no-store"},
        )


def auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise AuthFailure(503, "auth_unavailable")
    return service


Service = Annotated[AuthService, Depends(auth_service)]
router = APIRouter(prefix="/api/v1", tags=["auth"])


class SessionExchange(BaseModel):
    id_token: str = Field(min_length=1, max_length=16384, repr=False)
    nonce: str = Field(min_length=1, max_length=512, repr=False)


class SessionCreated(BaseModel):
    session_id: str
    csrf_token: str
    expires_at: datetime


class MembershipView(BaseModel):
    tenant_id: UUID
    role: str


class MeView(BaseModel):
    user_id: UUID
    memberships: list[MembershipView]
    expires_at: datetime


@router.post("/auth/sessions", response_model=SessionCreated)
def exchange(
    body: SessionExchange, request: Request, response: Response, service: Service
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return service.exchange(
        body.id_token, body.nonce, request.headers.get("X-WSO-Auth-Key")
    )


@router.get("/me", response_model=MeView)
def me(request: Request, response: Response, service: Service) -> dict[str, Any]:
    session = service.authenticate(request)
    with service.identity(session) as lookup:
        if lookup.user_id() != session.user_id:
            raise AuthFailure()
        memberships = lookup.list_tenants()
    response.headers["Cache-Control"] = "no-store"
    return {
        "user_id": session.user_id,
        "expires_at": session.expires_at,
        "memberships": [
            {"tenant_id": m.tenant_id, "role": m.role} for m in memberships
        ],
    }


@router.delete("/auth/session", status_code=204)
def logout(request: Request, service: Service) -> Response:
    session = service.authenticate(request)
    csrf = request.headers.get("X-CSRF-Token", "")
    if (
        request.headers.get("Origin") != service.settings.public_origin
        or not csrf
        or len(csrf) > 128
        or not hmac.compare_digest(token_digest(csrf), session.csrf_digest)
    ):
        raise AuthFailure(403, "csrf_rejected")
    if not service.sessions.revoke(
        token_digest(request.cookies[SESSION_COOKIE]), token_digest(csrf)
    ):
        raise AuthFailure()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")
    return response
