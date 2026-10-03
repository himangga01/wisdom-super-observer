"""Optional immutable worker-only directory profile mapping."""

from collections.abc import Mapping
from pathlib import Path

from wso_api.tvt.session_service import AccountEndpoint
from wso_core.tvt.directory_admission import DirectoryPolicy

from .selected import directory_json, failure


def load_directory_configuration(
    env: Mapping[str, str], endpoints: tuple[AccountEndpoint, ...]
) -> tuple[DirectoryPolicy, ...] | None:
    name = "WSO_TVT_DIRECTORY_PROFILE_FILE"
    if name not in env:
        return None
    result = None
    try:
        if not env[name]:
            raise ValueError
        with Path(env[name]).open("rb") as stream:
            raw = stream.read(65537)
        if not 0 < len(raw) <= 65536:
            raise ValueError
        value = directory_json(raw)
        if type(value) is not list or not 1 <= len(value) <= 64:
            raise ValueError
        policies = []
        for item in value:
            if type(item) is not dict or set(item) != {
                "region",
                "brand",
                "profile_id",
                "consent_version",
            }:
                raise ValueError
            policies.append(DirectoryPolicy(**item))
        pairs = {(p.region, p.brand) for p in policies}
        selections = {(e.region, e.brand) for e in endpoints}
        if (
            len(pairs) != len(policies)
            or len(selections) != len(endpoints)
            or pairs != selections
        ):
            raise ValueError
        result = tuple(policies)
    except Exception:  # noqa: BLE001, S110 -- redact trusted deployment file contents
        pass
    if result is None:
        raise failure("ACCOUNT_UNAVAILABLE") from None
    return result
