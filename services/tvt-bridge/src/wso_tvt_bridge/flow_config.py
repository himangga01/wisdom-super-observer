"""Worker-only closed flow profile and stable binding-key configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from wso_api.tvt.flow_service import FlowEndpointConfig
from wso_api.tvt.session_service import AccountEndpoint

from .selected import _pairs, failure


@dataclass(frozen=True, slots=True, repr=False)
class FlowConfiguration:
    profiles: Mapping[tuple[str, str], FlowEndpointConfig]
    binding_key: bytes

    @property
    def key_commitment(self) -> str:
        return hashlib.sha256(self.binding_key).hexdigest()


def _text(value: object, *, nonempty: bool = False) -> bool:
    return (
        type(value) is str
        and (not nonempty or bool(value))
        and len(value.encode("utf-8")) <= 4096
        and not any(
            ord(char) == 0 or ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF
            for char in value
        )
    )


def load_flow_configuration(
    env: Mapping[str, str], endpoints: tuple[AccountEndpoint, ...]
) -> FlowConfiguration | None:
    names = ("WSO_TVT_ACCOUNT_FLOW_PROFILE_FILE", "WSO_TVT_ACCOUNT_FLOW_KEY_FILE")
    if all(name not in env for name in names):
        return None
    result = None
    try:
        if any(not env.get(name) for name in names):
            raise ValueError
        with Path(env[names[1]]).open("rb") as stream:
            key = stream.read(33)
        if len(key) != 32:
            raise ValueError
        with Path(env[names[0]]).open("rb") as stream:
            raw = stream.read(65537)
        if not 0 < len(raw) <= 65536:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not list or not 1 <= len(value) <= 64:
            raise ValueError
        profiles = {}
        for item in value:
            if (
                type(item) is not dict
                or not {"region", "brand", "default_domain"} <= item.keys()
                or item.keys() - {"region", "brand", "default_domain", "terminal_id"}
                or any(
                    not _text(v, nonempty=k in {"region", "brand"})
                    for k, v in item.items()
                )
            ):
                raise ValueError
            pair = (item["region"], item["brand"])
            if pair in profiles:
                raise ValueError
            profiles[pair] = FlowEndpointConfig(
                item["default_domain"], item.get("terminal_id", "")
            )
        selections = {(endpoint.region, endpoint.brand) for endpoint in endpoints}
        if len(selections) != len(endpoints) or set(profiles) != selections:
            raise ValueError
        result = FlowConfiguration(profiles, key)
    except Exception:  # noqa: BLE001, S110 -- never expose private parser inputs
        pass
    if result is None:
        raise failure("ACCOUNT_UNAVAILABLE") from None
    return result
