"""Immutable private source observations, never media/account grants.

Only decoded nonsecret fields enter the projection. Unknown members are bounded
while parsing, counted, then discarded; no raw credential-bearing passthrough.
Java initialization metadata is separate from explicit server observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from .account_protocol import (
    MAX_NATIVE_INT,
    AccountProtocolError,
    AccountResponse,
    JsonValue,
    private_json,
)
from .directory_protocol import DEFAULT_BOUNDS, DirectoryBounds


class Presence(StrEnum):
    MISSING = "missing"
    NULL = "null"
    VALUE = "value"


type ObservedValue = (
    None
    | bool
    | int
    | float
    | str
    | tuple[ObservedValue, ...]
    | ObjectObservation
    | OpaqueObservation
)


@dataclass(frozen=True, slots=True)
class OpaqueObservation:
    """Shape-only metadata for Java Object members; arbitrary contents discarded."""

    kind: str


@dataclass(frozen=True, slots=True)
class FieldObservation:
    state: Presence
    value: ObservedValue = field(default=None, repr=False)
    source_default: str | int | None = None


def _project(value: ObservedValue) -> JsonValue:
    if isinstance(value, ObjectObservation):
        return value.project()
    if isinstance(value, tuple):
        return [_project(item) for item in value]
    if isinstance(value, OpaqueObservation):
        raise _invalid()
    return value


@dataclass(frozen=True, slots=True)
class ObjectObservation:
    fields: tuple[tuple[str, FieldObservation], ...] = field(repr=False)
    unknown_members: int = 0

    def field(self, name: str) -> FieldObservation:
        for key, observation in self.fields:
            if key == name:
                return observation
        raise KeyError(name)

    def project(self) -> dict[str, JsonValue]:
        """Fresh safe field map; mutation cannot change the private observation."""
        return {
            key: _project(observation.value)
            for key, observation in self.fields
            if observation.state is not Presence.MISSING
            and not isinstance(observation.value, OpaqueObservation)
        }

    @property
    def complete(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class DevicePage:
    total: str
    records: tuple[ObjectObservation, ...] = field(repr=False)
    unknown_members: int = 0
    complete: None = None

    def project(self) -> dict[str, JsonValue]:
        return {
            "total": self.total,
            "records": [record.project() for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class SharePage:
    total: int
    records: tuple[ObjectObservation, ...] = field(repr=False)
    unknown_members: int = 0
    complete: None = None

    def project(self) -> dict[str, JsonValue]:
        return {
            "total": self.total,
            "records": [record.project() for record in self.records],
        }


@dataclass(frozen=True, slots=True)
class ChannelDirectory:
    devices: tuple[ObjectObservation, ...] = field(repr=False)
    complete: None = None

    def project(self) -> list[JsonValue]:
        return [device.project() for device in self.devices]


@dataclass(frozen=True, slots=True)
class _Schema:
    kind: str
    members: dict[str, _Schema] | None = None
    element: _Schema | None = None
    source_default: str | int | None = None


_TEXT, _INT, _BOOL = _Schema("text"), _Schema("int"), _Schema("bool")


def _object(members: dict[str, _Schema]) -> _Schema:
    return _Schema("object", members=members)


def _list(element: _Schema) -> _Schema:
    return _Schema("list", element=element)


def _members(names: str, schema: _Schema) -> dict[str, _Schema]:
    return dict.fromkeys(names.split(), schema)


_DEVICE_RECORD = _object(
    {
        **_members("sn name userId devName mode createTime", _TEXT),
        "maxShareNum": _Schema("text", source_default="0"),
        "type": _Schema("int", source_default=0),
    }
)
_CHANNEL = _object({"chlIndex": _INT, "chlName": _TEXT})
_CHANNEL_DEVICE = _object({"sn": _TEXT, "chls": _list(_CHANNEL)})
_CAP_MEMBERS = {
    **_members(
        "alarmInNum alarmOutNum chlNum maxConnNum maxMainstreamNum "
        "maxSubstreamNum maxPlaybackNum poeChlNum posNum",
        _INT,
    ),
    **_members("face raid talk", _BOOL),
    **_members("supportFun videoForm", _list(_TEXT)),
    "diskInterface": _list(_object({"name": _TEXT, "num": _INT})),
    "platformCaps": _object({"recMode": _list(_TEXT)}),
}
_CHANNEL_CAPABILITY = _object(
    {
        **_CAP_MEMBERS,
        "stream": _list(
            _object(
                {
                    "name": _TEXT,
                    "res": _list(_object({"fps": _INT, "value": _TEXT})),
                    "supEnct": _list(_TEXT),
                }
            )
        ),
    }
)
_CHANNEL_DETAIL = _object(
    {
        **_members("sn chlName ip model version onlineTime offlineTime", _TEXT),
        **_members("chlIndex status", _INT),
        "capability": _CHANNEL_CAPABILITY,
    }
)
_DEVICE_BASIC = _object(
    {
        **_members(
            "apiVer kernelVer platformType hVer onvifVer pCBAV mac verDate verID "
            "codeId pCUI pluginVer sdkVer model aiVer MCU pN name deviceNumber",
            _TEXT,
        ),
        **_members("packContentFlag type customerId cfgId", _INT),
    }
)
_DEVICE_INFO = _object(
    {
        **_members(
            "aiVersion configId customerId lang mac model name offlineTime onlineTime "
            "packContentFlag pcui sn snPlain version versionId whitelistVersion workMode",
            _TEXT,
        ),
        **_members("checkStatus delStatus maxConnNum onlineStatus type", _INT),
        # Java Object: preserve only explicit safe scalar observations; complex or
        # credential-bearing objects stay private and are not exported as wire JSON.
        "userId": _Schema("scalar"),
        "checkTime": _Schema("scalar"),
        "devInfo": _DEVICE_BASIC,
        "capability": _object(_CAP_MEMBERS),
    }
)
_DEVICE_DETAIL = _object({"devInfo": _DEVICE_INFO, "chlInfos": _list(_CHANNEL_DETAIL)})
_SHARE_COMMON = {
    **_members(
        "id sn chlName devName devMode recipientRemark createTime acceptTime", _TEXT
    ),
    **_members("chlIndex ownerType status resourceType", _INT),
    "auth": _list(_TEXT),
    "devInfo": _object({"name": _TEXT, "type": _INT}),
}
_SENT_SHARE = _object(
    {
        **_SHARE_COMMON,
        "recipientId": _TEXT,
        "validData": _INT,
        "shardIds": _list(_TEXT),
    }
)
_RECEIVED_SHARE = _object(
    {
        **_SHARE_COMMON,
        **_members("ownerId devRemark ownerRemark", _TEXT),
        "devType": _INT,
    }
)


def _invalid() -> AccountProtocolError:
    return AccountProtocolError("Invalid directory response.")


def _bounded(value: JsonValue, bounds: DirectoryBounds) -> None:
    """Also bound unknown members before omitting them from safe output."""
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > bounds.max_nodes or depth > bounds.max_depth:
            raise _invalid()
        if type(item) is str:
            if (
                any(ord(c) == 0 or 0xD800 <= ord(c) <= 0xDFFF for c in item)
                or len(item.encode("utf-8")) > bounds.max_string_bytes
            ):
                raise _invalid()
        elif type(item) is list:
            if len(item) > bounds.max_list_items:
                raise _invalid()
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is dict:
            if len(item) > bounds.max_nodes:
                raise _invalid()
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)


def _payload(
    response: AccountResponse, bounds: DirectoryBounds, *, array: bool = False
) -> JsonValue:
    if type(bounds) is not DirectoryBounds:
        raise _invalid()
    response.require_success()
    root = private_json(response.private_body)
    _bounded(root, bounds)
    data = root.get("data")
    if (data is None or data == "") and not array:
        data = root.get("array")
    if type(data) is not list if array else type(data) is not dict:
        raise _invalid()
    return data


def _decode(value: JsonValue, schema: _Schema) -> ObservedValue:
    if value is None:
        return None
    if schema.kind == "text" and type(value) is str:
        return value
    if (
        schema.kind == "int"
        and type(value) is int
        and -(2**31) <= value <= MAX_NATIVE_INT
    ):
        return value
    if schema.kind == "bool" and type(value) is bool:
        return value
    if schema.kind == "scalar" and type(value) in (str, bool, int, float):
        return cast(str | bool | int | float, value)
    if schema.kind == "scalar" and type(value) in (dict, list):
        return OpaqueObservation("object" if type(value) is dict else "array")
    if schema.kind == "list" and type(value) is list and schema.element is not None:
        if any(item is None for item in value):
            raise _invalid()
        return tuple(_decode(item, schema.element) for item in value)
    if schema.kind == "object" and type(value) is dict and schema.members is not None:
        observations = []
        for name, member in schema.members.items():
            state = (
                Presence.MISSING
                if name not in value
                else Presence.NULL
                if value[name] is None
                else Presence.VALUE
            )
            observations.append(
                (
                    name,
                    FieldObservation(
                        state,
                        _decode(value[name], member) if name in value else None,
                        member.source_default,
                    ),
                )
            )
        return ObjectObservation(
            tuple(observations), len(value.keys() - schema.members.keys())
        )
    raise _invalid()


def _record(value: JsonValue, schema: _Schema) -> ObjectObservation:
    if type(value) is not dict:
        raise _invalid()
    return cast(ObjectObservation, _decode(value, schema))


def _page(
    response: AccountResponse, bounds: DirectoryBounds, schema: _Schema, *, shares: bool
) -> DevicePage | SharePage:
    data = cast(dict[str, JsonValue], _payload(response, bounds))
    total, records = data.get("total"), data.get("records")
    if (
        type(total) is not (int if shares else str)
        or type(records) is not list
        or len(records) > bounds.max_records
    ):
        raise _invalid()
    parsed = tuple(_record(record, schema) for record in records)
    unknown = len(data.keys() - {"total", "records"})
    if shares:
        if not 0 <= cast(int, total) <= MAX_NATIVE_INT:
            raise _invalid()
        return SharePage(cast(int, total), parsed, unknown)
    return DevicePage(cast(str, total), parsed, unknown)


def parse_device_list(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> DevicePage:
    return cast(DevicePage, _page(response, bounds, _DEVICE_RECORD, shares=False))


def parse_channel_list(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> ChannelDirectory:
    data = cast(list[JsonValue], _payload(response, bounds, array=True))
    if len(data) > bounds.max_records:
        raise _invalid()
    return ChannelDirectory(tuple(_record(record, _CHANNEL_DEVICE) for record in data))


def parse_device_detail(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> ObjectObservation:
    return _record(_payload(response, bounds), _DEVICE_DETAIL)


def parse_channel_detail(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> ObjectObservation:
    return _record(_payload(response, bounds), _CHANNEL_DETAIL)


def parse_sent_shares(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> SharePage:
    return cast(SharePage, _page(response, bounds, _SENT_SHARE, shares=True))


def parse_received_shares(
    response: AccountResponse, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
) -> SharePage:
    return cast(SharePage, _page(response, bounds, _RECEIVED_SHARE, shares=True))
