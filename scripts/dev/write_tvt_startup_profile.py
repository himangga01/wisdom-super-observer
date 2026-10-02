"""Generate reviewed startup JSON before starting the API; never edit environment files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from ipaddress import IPv6Address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wso_core.tvt.startup import StartupProfile

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "apps/web/src/features/tvt/policies/generated-content.json"
APK_SHA256 = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
LOCALES = ("en", "zh-Hans")
REVIEWED = {
    ("en", "terms"): (
        "ServiceTerms_en.html",
        "7973f409b90d62127488bf496de299dc537c32832b1c27b9d37f020ce2525544",
        158863,
    ),
    ("en", "privacy"): (
        "PrivacyStatement_en.html",
        "e2f542f723b332188db98d428a49b15d5430b4b3e2722338b2df8aed31882f1b",
        47981,
    ),
    ("zh-Hans", "terms"): (
        "ServiceTerms_zh-Hans.html",
        "9580039561c539e348a2a45f6682b54fe3f2681749817baceb3e99e6fc9f3965",
        196817,
    ),
    ("zh-Hans", "privacy"): (
        "PrivacyStatement_zh-Hans.html",
        "ff1a8d79ee2ee6b2b095129a0187a54f7e39c83f2b8e233b71988a72e513028d",
        38500,
    ),
}


def trusted_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or "\\" in value
        or any(char.isspace() or ord(char) < 32 for char in value)
    ):
        raise ValueError(
            "public origin must be a trusted HTTPS origin without credentials or URL suffixes"
        )
    # Evaluating .port rejects malformed/out-of-range authority ports.
    if parsed.port is not None and parsed.port == 0:
        raise ValueError("public origin port must be positive")
    host = parsed.hostname
    if ":" in host:
        IPv6Address(host)
    elif len(host) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in host.split(".")
    ):
        raise ValueError("public origin hostname must contain valid ASCII labels")
    if parsed.netloc.endswith(":"):
        raise ValueError("public origin has an empty port")
    return value.removesuffix("/")


def reviewed_documents() -> dict[tuple[str, str], dict[str, Any]]:
    bundle = json.loads(CONTENT.read_text(encoding="utf-8"))
    if (
        bundle["source_apk_sha256"] != APK_SHA256
        or bundle["app_version"] != "1.18.1"
        or bundle["schema_version"] != 1
        or bundle["derivation"] != "visible-body-structured-v1"
    ):
        raise ValueError("unreviewed policy bundle")
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in bundle["documents"]:
        key = (doc["locale"], doc["kind"])
        if (
            key in documents
            or doc["locale"] not in LOCALES
            or doc["kind"] not in ("terms", "privacy")
        ):
            raise ValueError("invalid policy bundle routes")
        filename, sha, size = REVIEWED[key]
        if (doc["source_reference"], doc["source_sha256"], doc["source_bytes"]) != (
            "agreement/" + filename,
            sha,
            size,
        ):
            raise ValueError("policy bundle must retain reviewed source metadata")
        canonical = json.dumps(
            doc["blocks"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != doc["content_sha256"]:
            raise ValueError("policy content digest mismatch")
        documents[key] = doc
    if set(documents) != {
        (locale, kind) for locale in LOCALES for kind in ("terms", "privacy")
    }:
        raise ValueError("four bundled policies required")
    return documents


def build_profile(
    *,
    public_origin: str,
    region: str,
    default_locale: str,
    timezone: str,
    ui_locale: str = "ko",
    enable_settings: bool = False,
    enable_account: bool = False,
) -> StartupProfile:
    origin = trusted_origin(public_origin)
    if not re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]{1,16})?", region):
        raise ValueError("region must be an explicit uppercase deployment region code")
    if default_locale not in LOCALES or ui_locale != "ko":
        raise ValueError("unsupported policy/formatting or interface locale")
    if (
        enable_settings
        and not (ROOT / "apps/web/src/app/tvt/[[...path]]/page.tsx").is_file()
    ):
        raise ValueError("settings web route is not included")
    if enable_account and not all(
        path.is_file()
        for path in (
            ROOT / "apps/web/src/app/tvt/[[...path]]/page.tsx",
            ROOT / "apps/web/src/features/tvt/account/SessionBoundary.tsx",
        )
    ):
        raise ValueError("account web route or component is not included")
    documents = reviewed_documents()
    # The revision includes all locales, original asset digests and derivation.
    revision = "\n".join(
        ["SuperLivePlus:1.18.1", APK_SHA256, "visible-body-structured-v1"]
        + [
            f"{locale}:{kind}:{documents[(locale, kind)]['source_sha256']}:{documents[(locale, kind)]['content_sha256']}"
            for locale in LOCALES
            for kind in ("terms", "privacy")
        ]
    )
    consent = "slp-1.18.1-" + hashlib.sha256(revision.encode("utf-8")).hexdigest()[:40]
    references = {
        kind: {
            "source_reference": documents[(default_locale, kind)]["source_reference"],
            "url": f"{origin}/tvt/policies/{default_locale}/{kind}",
        }
        for kind in ("terms", "privacy")
    }
    return StartupProfile.model_validate(
        {
            "profile_id": "slp-1.18.1-" + region,
            "source_apk_sha256": APK_SHA256,
            "brand": "SuperLivePlus",
            "region": region,
            "consent_version": consent,
            "default_locale": default_locale,
            "default_timezone": timezone,
            "supported_locales": list(LOCALES),
            **references,
            "local_routes": [
                path
                for path, enabled in (
                    ("/tvt/account", enable_account),
                    ("/tvt/settings", enable_settings),
                )
                if enabled
            ],
        }
    )


def write_profile(
    profile: StartupProfile, *, output: Path, output_root: Path, replace: bool = False
) -> None:
    bounded_root = output_root.resolve(strict=True)
    target = output.resolve()
    if (
        not bounded_root.is_dir()
        or not target.is_relative_to(bounded_root)
        or target.suffix != ".json"
        or output.is_symlink()
    ):
        raise ValueError("output must be a JSON file inside the explicit output root")
    if target.exists() and (not replace or not target.is_file()):
        raise ValueError(
            "output exists; explicitly use --replace for a reviewed JSON configuration"
        )
    if not target.parent.is_dir():
        raise ValueError("output parent must already exist")
    raw = (profile.model_dump_json(indent=2) + "\n").encode("utf-8")
    if len(raw) > 16384:
        raise ValueError("startup profile exceeds loader bound")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--default-locale", choices=LOCALES, required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--ui-locale", choices=("ko",), default="ko")
    parser.add_argument("--enable-settings", action="store_true")
    parser.add_argument("--enable-account", action="store_true")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        profile = build_profile(
            public_origin=args.public_origin,
            region=args.region,
            default_locale=args.default_locale,
            timezone=args.timezone,
            ui_locale=args.ui_locale,
            enable_settings=args.enable_settings,
            enable_account=args.enable_account,
        )
        write_profile(
            profile,
            output=args.output,
            output_root=args.output_root,
            replace=args.replace,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(
        "Wrote validated SuperLivePlus startup profile; account "
        + ("enabled" if args.enable_account else "disabled")
        + ", settings "
        + ("enabled" if args.enable_settings else "disabled")
    )


if __name__ == "__main__":
    main()
