"""Private, fixed APK bootstrap facts for the separate NatTraveral helper.

No device identity, credentials, authority grant, runtime file read or transport.
Trusted context types express a caller contract, not authenticated provenance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Self


class LocalBootstrapError(ValueError):
    """Fixed safe error without echoing private context or input."""


_APK_SHA256 = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
_SOURCE_SHA256 = (
    ("custom.xml", "b2521a3837868b2a96605e0456eaf4a1db72e23654e9b8192564baf1ebe2dc2f"),
    (
        "AreasDomain.json",
        "e47dae84995270f644a58f34743615e9854bbafb51400e4db7e954408c968e94",
    ),
    (
        "CustomPath.java",
        "0323621e2566a51b092e27a531fb637d8bd5ce6496daab28b43a406e017aea2d",
    ),
    (
        "GlobalUnitItem.java",
        "e5e25420694341064ed4a510192e67b2682019904092daa05592c8cdc00aea68",
    ),
    (
        "GlobalUnit.java",
        "0a4c202de827cb2597588c9437d88c11c9df47c0d13054148f76ff0c518acba2",
    ),
    ("m42.java", "dbfe5f964c1c85481ac734be44389a760cf2dbbfbc8038b7a6f8c0a086ddaa02"),
    ("apktool.yml", "c732e5c92b79351e03df61da5905e7332531702c48f2a6518ab510073c03b79e"),
    ("strings.xml", "9206e8cb5379119d102ab7c890d8797d7f5b2d13214bf9d44f49662f0d97cf60"),
    (
        "LaunchApplication.java",
        "13e04e70da181ec6f8309993ed1c0b4695b42c26d277f732435242b8b84597a3",
    ),
    (
        "MainActivity.java",
        "483926f7d61a77cbd0597a9332c9db126df21d36b25402dae22547c499fb977e",
    ),
    (
        "base/tool/b.java",
        "0ab4bd2f5badb21a2f30695082a91982fba39e3bb4b67797c9a9afd5b7b1c576",
    ),
)

# Exact ordered AreasDomain.json memberships; no geographic inference.
_AREAS = (
    ("US", "autonat.us", "US"),
    ("CN", "autonat.cn", "CN"),
    ("RU", "autonatru.com", "RU"),
    (
        "EU",
        "autonateu.com",
        (
            "BY BG CZ HU PL MD RO SK UA AX GG JE DK EE FO FI IS IE IM LV LT NO SJ SE GB "
            "AL AD BA HR GI GR VA IT MT ME MK PT SM RS SI ES AT BE FR DE LI LU MC NL CH"
        ),
    ),
    (
        "AP",
        "autonatap.com",
        (
            "AQ KZ KG TJ TM UZ HK MO KP JP MN KR BN KH ID LA MY MM PH SG TH TL VN AF BD "
            "BT IN IR MV NP PK LK AM AZ BH CY GE IQ IL JO KW LB OM QA SA PS SY TR AE YE "
            "AU CX CC HM NZ NF FJ NC PG SB VU GU KI MH FM NR MP PW UM AS CK PF NU PN WS "
            "TK TO TV WF"
        ),
    ),
    (
        "GLB",
        "autonatglb.com",
        (
            "DZ EG LY MA SD TN EH IO BI KM DJ ER ET TF KE MG MW MU YT MZ RE RW SC SO SS "
            "UG TZ ZM ZW AO CM CF TD CG CD GQ GA ST BW SZ LS NA ZA BJ BF CV CI GM GH GN "
            "GW LR ML MR NE NG SH SN SL TG AI AG AW BS BB BQ VG KY CU CW DM DO GD GP HT "
            "JM MQ MS PR BL KN LC MF VC SX TT TC VI BZ CR SV GT HN MX NI PA AR BO BV BR "
            "CL CO EC FK GF GY PY PE GS SR UY VE BM CA GL PM"
        ),
    ),
)
_NAT1_ADDRESS = "c2.autonat.com:40002"
_NAT2_ADDRESSES = frozenset(
    [f"cli-nat20.{domain}:7968" for _, domain, _ in _AREAS] + ["c2020.autonat.com:8888"]
)
_ATTEMPTS = {
    "initial": (0, False),
    "retry_nat1": (1, False),
    "retry_disable_upnp": (0, True),
    "retry_nat1_disable_upnp": (1, True),
}


def _text(value: str, maximum: int) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise LocalBootstrapError("Invalid local bootstrap text.")
    try:
        valid = len(value.encode("utf-8", errors="strict")) <= maximum
    except UnicodeEncodeError:
        valid = False
    if not valid:
        raise LocalBootstrapError("Invalid local bootstrap text.")
    return value


def _endpoint(address: str, maximum: int) -> tuple[str, int]:
    _text(address, maximum + 6)
    host, separator, port_text = address.partition(":")
    if not separator or not re.fullmatch(r"[1-9][0-9]{0,4}", port_text):
        raise LocalBootstrapError("Invalid local bootstrap endpoint.")
    port = int(port_text)
    if not 1 <= port <= 65535 or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise LocalBootstrapError("Invalid local bootstrap endpoint.")
    return _text(host, maximum), port


@dataclass(frozen=True, slots=True, repr=False)
class TrustedAndroidRuntime:
    """Private helper context. single_id is GlobalUnit.O output, not Build.MODEL.

    The owning helper resolves private_files_path for its Android API/ownership.
    This module neither reads SINGLE_ID nor generates or persists an identity.
    """

    private_files_path: str
    single_id: str
    source_network_type: int

    def __post_init__(self) -> None:
        path = _text(self.private_files_path, 255)
        _text(self.single_id, 63)
        if (
            not path.startswith("/")
            or "\\" in path
            or "//" in path
            or any(part in (".", "..") for part in path.split("/"))
        ):
            raise LocalBootstrapError("Invalid Android private path.")
        if type(
            self.source_network_type
        ) is not int or self.source_network_type not in (0, 2, 3, 4, 5):
            raise LocalBootstrapError("Invalid source network type.")


@dataclass(frozen=True, slots=True, repr=False)
class ReviewedSavedOverrides:
    """Operator input restricted to reviewed resource endpoint/domain identities.

    A supplied value does not prove actual app preferences were recovered.
    Arbitrary saved debug endpoints require a separately reviewed future change.
    """

    root_domain: str | None = None
    nat1_address: str | None = None
    nat2_address: str | None = None

    def __post_init__(self) -> None:
        if all(
            value is None
            for value in (self.root_domain, self.nat1_address, self.nat2_address)
        ):
            raise LocalBootstrapError("Explicit saved override required.")
        if self.root_domain is not None:
            domain = _text(self.root_domain, 63)
            if domain not in {row[1] for row in _AREAS}:
                raise LocalBootstrapError("Unreviewed root domain.")
        if self.nat1_address is not None:
            _endpoint(self.nat1_address, 127)
            if self.nat1_address != _NAT1_ADDRESS:
                raise LocalBootstrapError("Unreviewed NAT1 endpoint.")
        if self.nat2_address is not None:
            _endpoint(self.nat2_address, 63)
            if self.nat2_address not in _NAT2_ADDRESSES:
                raise LocalBootstrapError("Unreviewed NAT2 endpoint.")


@dataclass(frozen=True, slots=True, repr=False, init=False)
class LocalBootstrapProfile:
    """Immutable result; use select_local_bootstrap, then private helper only."""

    package_name: str
    apk_sha256: str
    source_sha256: tuple[tuple[str, str], ...]
    country_code: str
    source_region_id: str
    region_id: str
    selection_reason: str
    saved_state: str
    attempt_branch: str
    _helper_fields: tuple[tuple[str, str | int | bool], ...]

    def __new__(cls) -> Self:
        raise TypeError("Use the fixed source profile selector.")

    def private_helper_json(self) -> str:
        """Deterministic private config fields; never send to a public route/log."""
        return json.dumps(
            dict(self._helper_fields), sort_keys=True, separators=(",", ":")
        )


def select_local_bootstrap(
    *,
    country_code: str,
    runtime: TrustedAndroidRuntime,
    attempt_branch: str,
    saved_overrides: ReviewedSavedOverrides | None = None,
) -> LocalBootstrapProfile:
    """Select exact source defaults with explicit locale/attempt/runtime inputs.

    Empty or unknown uppercase country -> source GLB fallback, not runtime fact.
    AP/EU resource IDs are rejected as mistaken country input. No saved state is
    inferred. Optional operator overrides take precedence exactly as documented.
    """
    if (
        type(country_code) is not str
        or (country_code != "" and not re.fullmatch(r"[A-Z]{2}", country_code))
        or country_code in ("AP", "EU")
    ):
        raise LocalBootstrapError("Invalid explicit country code.")
    if type(runtime) is not TrustedAndroidRuntime or (
        saved_overrides is not None
        and type(saved_overrides) is not ReviewedSavedOverrides
    ):
        raise LocalBootstrapError("Typed private context required.")
    if type(attempt_branch) is not str or attempt_branch not in _ATTEMPTS:
        raise LocalBootstrapError("Explicit source attempt branch required.")
    source_region, root_domain, _ = _AREAS[-1]
    reason = "resource_default"
    for region, domain, countries in _AREAS:
        if country_code in countries.split():
            source_region, root_domain, reason = region, domain, "country_match"
            break
    region = source_region
    if saved_overrides is not None and saved_overrides.root_domain is not None:
        root_domain = saved_overrides.root_domain
        region = next(row[0] for row in _AREAS if row[1] == root_domain)
        reason = "operator_root_domain"
    address1 = _NAT1_ADDRESS
    address2 = f"cli-nat20.{root_domain}:7968"
    if saved_overrides is not None:
        address1 = saved_overrides.nat1_address or address1
        address2 = saved_overrides.nat2_address or address2
    host1, port1 = _endpoint(address1, 127)
    host2, port2 = _endpoint(address2, 63)
    mode, disabled = _ATTEMPTS[attempt_branch]
    fields = (
        ("nat1Host", host1),
        ("nat1Port", port1),
        ("nat2Host", host2),
        ("nat2Port", port2),
        ("networkFlag", 1 if runtime.source_network_type == 4 else 0),
        ("traversalMode", mode),
        ("disableUPnP", disabled),
        ("privateFilesPath", runtime.private_files_path),
        ("platform", _text("AND", 31)),
        ("appVersion", _text("1.18.1.20267", 63)),
        ("appName", _text("AND_M_PH_SuperLivePlus", 63)),
        ("model", runtime.single_id),
    )
    profile = object.__new__(LocalBootstrapProfile)
    for key, value in {
        "package_name": "com.tvt.superliveplus",
        "apk_sha256": _APK_SHA256,
        "source_sha256": _SOURCE_SHA256,
        "country_code": country_code,
        "source_region_id": source_region,
        "region_id": region,
        "selection_reason": reason,
        "saved_state": "unobserved" if saved_overrides is None else "operator_supplied",
        "attempt_branch": attempt_branch,
        "_helper_fields": fields,
    }.items():
        object.__setattr__(profile, key, value)
    return profile
