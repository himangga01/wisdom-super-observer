"""Strict readonly directory requests and presence-aware safe observations."""

from __future__ import annotations

import json
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from wso_contracts.models import WireModel
from wso_contracts.tvt.identity import ScopeLabel

type DirectoryMethod = Literal[
    "device_list",
    "channel_list",
    "device_detail",
    "channel_detail",
    "sent_shares",
    "received_shares",
]
NativeIndex = Annotated[StrictInt, Field(ge=0, le=2**31 - 1)]
ResourceType = Annotated[StrictInt, Field(ge=-(2**31), le=2**31 - 1)]
RequestId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]


def _selector(value: str) -> str:
    if (
        not value
        or value.strip() != value
        or len(value.encode("utf-8")) > 4096
        or any(
            ord(c) < 32
            or ord(c) == 127
            or ord(c) > 0xFFFF
            or 0xD800 <= ord(c) <= 0xDFFF
            for c in value
        )
    ):
        raise ValueError("invalid directory selector")
    return value


Selector = Annotated[StrictStr, AfterValidator(_selector)]


def _distinct[T](values: tuple[T, ...]) -> tuple[T, ...]:
    if len(set(values)) != len(values):
        raise ValueError("duplicate directory selector")
    return values


class DirectoryReference(WireModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    identity_id: UUID
    region: ScopeLabel
    brand: ScopeLabel


class _Page(DirectoryReference):
    page_num: NativeIndex = 0
    page_size: Annotated[StrictInt, Field(ge=0, le=1000)] = 1000


class DeviceListRequest(_Page):
    method: Literal["device_list"] = "device_list"


class ChannelListRequest(DirectoryReference):
    method: Literal["channel_list"] = "channel_list"
    sn_list: Annotated[
        tuple[Selector, ...],
        Field(min_length=1, max_length=100),
        AfterValidator(_distinct),
    ] = Field(repr=False)


class DeviceDetailRequest(DirectoryReference):
    method: Literal["device_detail"] = "device_detail"
    sn: Selector = Field(repr=False)
    return_chl: StrictBool = False


class ChannelDetailRequest(DirectoryReference):
    method: Literal["channel_detail"] = "channel_detail"
    sn: Selector = Field(repr=False)
    chl_index: NativeIndex


class _Shares(_Page):
    resource_types: Annotated[
        tuple[ResourceType, ...], Field(max_length=16), AfterValidator(_distinct)
    ] = ()


class SentSharesRequest(_Shares):
    method: Literal["sent_shares"] = "sent_shares"


class ReceivedSharesRequest(_Shares):
    method: Literal["received_shares"] = "received_shares"


type DirectoryRequest = (
    DeviceListRequest
    | ChannelListRequest
    | DeviceDetailRequest
    | ChannelDetailRequest
    | SentSharesRequest
    | ReceivedSharesRequest
)
REQUEST_TYPES = {
    "device_list": DeviceListRequest,
    "channel_list": ChannelListRequest,
    "device_detail": DeviceDetailRequest,
    "channel_detail": ChannelDetailRequest,
    "sent_shares": SentSharesRequest,
    "received_shares": ReceivedSharesRequest,
}


def checked_request(method: str, body: DirectoryRequest) -> DirectoryRequest:
    cls = REQUEST_TYPES.get(method)
    if cls is None or type(body) is not cls:
        raise ValueError("invalid directory request")
    return cast(DirectoryRequest, cls.model_validate(body.model_dump(warnings=False)))


def canonical_request(method: str, body: DirectoryRequest) -> str:
    result = json.dumps(
        checked_request(method, body).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(result.encode("ascii")) > 65536:
        raise ValueError("directory query exceeds local byte policy")
    return result


# These are decoded field names, never arbitrary upstream map keys.
type ObservationName = Literal[
    "sn",
    "name",
    "userId",
    "devName",
    "mode",
    "createTime",
    "maxShareNum",
    "type",
    "chlIndex",
    "chlName",
    "chls",
    "alarmInNum",
    "alarmOutNum",
    "chlNum",
    "maxConnNum",
    "maxMainstreamNum",
    "maxSubstreamNum",
    "maxPlaybackNum",
    "poeChlNum",
    "posNum",
    "face",
    "raid",
    "talk",
    "supportFun",
    "videoForm",
    "diskInterface",
    "num",
    "platformCaps",
    "recMode",
    "stream",
    "res",
    "fps",
    "value",
    "supEnct",
    "ip",
    "model",
    "version",
    "onlineTime",
    "offlineTime",
    "status",
    "capability",
    "apiVer",
    "kernelVer",
    "platformType",
    "hVer",
    "onvifVer",
    "pCBAV",
    "mac",
    "verDate",
    "verID",
    "codeId",
    "pCUI",
    "pluginVer",
    "sdkVer",
    "aiVer",
    "MCU",
    "pN",
    "deviceNumber",
    "packContentFlag",
    "customerId",
    "cfgId",
    "aiVersion",
    "configId",
    "lang",
    "pcui",
    "snPlain",
    "versionId",
    "whitelistVersion",
    "workMode",
    "checkStatus",
    "delStatus",
    "onlineStatus",
    "checkTime",
    "devInfo",
    "chlInfos",
    "id",
    "devMode",
    "recipientRemark",
    "acceptTime",
    "ownerType",
    "resourceType",
    "auth",
    "recipientId",
    "validData",
    "shardIds",
    "ownerId",
    "devRemark",
    "ownerRemark",
    "devType",
]


class ObservationObject(WireModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    fields: tuple[ObservationField, ...] = Field(repr=False, max_length=100)
    unknown_members: Annotated[StrictInt, Field(ge=0, le=10000)] = 0


class ObservationField(WireModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    name: ObservationName
    state: Literal["missing", "null", "value"]
    value: ObservationValue = Field(default=None, repr=False)
    source_default: StrictStr | StrictInt | None = None
    opaque_kind: Literal["object", "array"] | None = None


type ObservationValue = (
    None
    | StrictBool
    | StrictInt
    | StrictFloat
    | StrictStr
    | ObservationObject
    | tuple[ObservationValue, ...]
)
ObservationObject.model_rebuild()
ObservationField.model_rebuild()


class DirectoryView(DirectoryReference):
    method: DirectoryMethod
    generation: Annotated[StrictInt, Field(ge=1)]
    request_id: RequestId
    records: tuple[ObservationObject, ...] = Field(repr=False, max_length=1000)
    total: StrictStr | StrictInt | None = None
    complete: None = None
    grants_operations: Literal[False] = False
