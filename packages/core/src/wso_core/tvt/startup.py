"""Trusted APK profile and protected per-actor local startup state.

No provider calls, credentials, or media capabilities are involved here.
"""

from __future__ import annotations

import os
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session
from wso_contracts.models import WireModel
from wso_contracts.tvt.startup import (
    ConsentUpdate,
    Locale,
    PolicyReference,
    PreferenceUpdate,
    StartupAccount,
    StartupBootstrap,
    StartupConsent,
    StartupIdentity,
    StartupMenuEntry,
    Version,
)

APK_SHA256 = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"


class StartupFailure(Exception):
    def __init__(self, status: int = 503, code: str = "startup_unavailable") -> None:
        self.status, self.code = status, code
        super().__init__(code)


class StartupProfile(WireModel):
    """Deployment-reviewed config, never an HTTP request body.

    MainActivity D2/x2 and e32.b select bundled policy references. ef2.v
    leaves LocalConfig available; vendor flags never enable local routes.
    An operator must explicitly provide published policy locations and the
    consent revision after reviewing them. No policy text is invented here.
    """

    profile_id: Version
    source_apk_sha256: Literal[
        "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
    ]
    brand: Literal["SuperLivePlus"]
    region: Version
    consent_version: Version
    default_locale: Locale
    default_timezone: str
    supported_locales: list[Locale] = Field(min_length=1, max_length=64)
    terms: PolicyReference
    privacy: PolicyReference
    local_routes: list[Literal["/tvt/settings", "/tvt/account", "/tvt/devices"]] = (
        Field(default_factory=list, max_length=3)
    )

    @model_validator(mode="after")
    def trusted_references(self) -> Self:
        if len(set(self.local_routes)) != len(self.local_routes):
            raise ValueError("duplicate local route")
        PreferenceUpdate(locale=self.default_locale, timezone=self.default_timezone)
        if self.default_locale not in self.supported_locales or len(
            set(self.supported_locales)
        ) != len(self.supported_locales):
            raise ValueError("invalid profile locales")
        for kind, reference in (
            ("ServiceTerms", self.terms),
            ("PrivacyStatement", self.privacy),
        ):
            if not reference.source_reference.startswith("agreement/" + kind + "_"):
                raise ValueError("invalid policy purpose")
            parsed = urlsplit(reference.url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in reference.url)
            ):
                raise ValueError("trusted HTTPS policy reference required")
        return self


def load_profile() -> StartupProfile | None:
    raw = os.environ.get("WSO_TVT_STARTUP_PROFILE")
    if raw is None or len(raw) > 16384:
        return None
    try:
        return StartupProfile.model_validate_json(raw)
    except ValueError:
        return None


def menu(profile: StartupProfile) -> list[StartupMenuEntry]:
    # APK ef2.java:477 local config is unconditional. Explicit deployment
    # registration confirms the corresponding web route is actually present.
    registered = {
        "/tvt/settings": StartupMenuEntry(
            id="local-settings", label="Settings", path="/tvt/settings"
        ),
        "/tvt/account": StartupMenuEntry(
            id="local-account", label="Account", path="/tvt/account"
        ),
        "/tvt/devices": StartupMenuEntry(
            id="local-devices", label="Devices", path="/tvt/devices"
        ),
    }
    return [registered[path] for path in profile.local_routes]


class StartupRepository:
    def __init__(self, session: Session, profile: StartupProfile) -> None:
        self.session, self.profile = session, profile

    def consent(self, status: str | None, decided_at: object) -> StartupConsent:
        return StartupConsent.model_validate(
            {
                "version": self.profile.consent_version,
                "status": status or "pending",
                "decided_at": decided_at,
                "terms": self.profile.terms,
                "privacy": self.profile.privacy,
            }
        )

    def bootstrap(self, tenant_id: UUID) -> StartupBootstrap:
        row = (
            self.session.execute(
                text("SELECT * FROM public.wso_tvt_startup_read(:profile,:version)"),
                {
                    "profile": self.profile.profile_id,
                    "version": self.profile.consent_version,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise StartupFailure(404, "not_found")
        accounts = [
            StartupAccount.model_validate(dict(item))
            for item in self.session.execute(
                text("SELECT * FROM public.wso_tvt_startup_accounts()")
            ).mappings()
        ]
        locale = (
            row["locale"]
            if row["locale"] in self.profile.supported_locales
            else self.profile.default_locale
        )
        return StartupBootstrap(
            selected_tenant_id=tenant_id,
            profile_id=self.profile.profile_id,
            brand=self.profile.brand,
            region=self.profile.region,
            locale=locale,
            timezone=row["timezone"] or self.profile.default_timezone,
            supported_locales=self.profile.supported_locales,
            consent=self.consent(row["status"], row["decided_at"]),
            identity=StartupIdentity(
                state="linked" if accounts else "unlinked", accounts=accounts
            ),
            menu=menu(self.profile),
        )

    def record_consent(self, body: ConsentUpdate) -> StartupConsent:
        if body.version != self.profile.consent_version:
            raise StartupFailure(409, "consent_version_changed")
        row = (
            self.session.execute(
                text(
                    "SELECT * FROM public.wso_tvt_consent_write(:profile,:version,:decision)"
                ),
                {
                    "profile": self.profile.profile_id,
                    "version": body.version,
                    "decision": body.decision,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise StartupFailure(404, "not_found")
        return self.consent(row["status"], row["decided_at"])

    def preferences(self, body: PreferenceUpdate) -> PreferenceUpdate:
        if body.locale not in self.profile.supported_locales:
            raise StartupFailure(422, "validation_error")
        row = (
            self.session.execute(
                text(
                    "SELECT * FROM public.wso_tvt_preferences_write(:profile,:locale,:timezone)"
                ),
                {
                    "profile": self.profile.profile_id,
                    "locale": body.locale,
                    "timezone": body.timezone,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise StartupFailure(404, "not_found")
        return PreferenceUpdate.model_validate(dict(row))
