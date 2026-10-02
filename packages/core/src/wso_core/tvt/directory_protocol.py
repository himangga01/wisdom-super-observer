"""Six private readonly APK serializers; configured bounds are web policy."""

from __future__ import annotations

from dataclasses import dataclass, fields

from .account_protocol import (
    MAX_NATIVE_INT,
    MAX_STRING_BYTES,
    AccountProtocol,
    AccountProtocolError,
    AccountRequest,
    JsonValue,
    _integer,
    _text,
)


@dataclass(frozen=True, slots=True)
class DirectoryBounds:
    """Local ceilings, not server maxima or completeness guarantees."""

    max_page_size: int = 1000
    max_selectors: int = 100
    max_resource_types: int = 16
    max_records: int = 1000
    max_list_items: int = 1000
    max_string_bytes: int = MAX_STRING_BYTES
    max_depth: int = 16
    max_nodes: int = 10_000

    def __post_init__(self) -> None:
        ceilings = (1000, 100, 16, 1000, 1000, MAX_STRING_BYTES, 16, 10_000)
        for field, ceiling in zip(fields(self), ceilings, strict=True):
            _integer(getattr(self, field.name), 1, ceiling)


DEFAULT_BOUNDS = DirectoryBounds()


class DirectoryProtocol:
    """No arbitrary command/path input; reuse ordinary AccountProtocol basic."""

    def __init__(
        self, account: AccountProtocol, *, bounds: DirectoryBounds = DEFAULT_BOUNDS
    ) -> None:
        if type(account) is not AccountProtocol or type(bounds) is not DirectoryBounds:
            raise AccountProtocolError("Invalid directory protocol input.")
        self._account = account
        self.bounds = bounds

    def _selector(self, value: object) -> str:
        checked = _text(value, nonempty=True)
        if (
            len(checked.encode("utf-8")) > self.bounds.max_string_bytes
            or checked.strip() != checked
            or any(ord(char) < 32 or ord(char) == 127 for char in checked)
        ):
            raise AccountProtocolError("Invalid directory protocol input.")
        return checked

    def _page(self, number: int, size: int) -> dict[str, JsonValue]:
        return {
            "pageNum": _integer(number, 0, MAX_NATIVE_INT),
            "pageSize": _integer(size, 0, self.bounds.max_page_size),
        }

    def _send(
        self, path: str, token: str, data: dict[str, JsonValue]
    ) -> AccountRequest:
        return self._account._request(
            path, self._account._basic(token=_text(token, nonempty=True)), data
        )

    def device_list(self, token: str, page_num: int, page_size: int) -> AccountRequest:
        return self._send(
            "/resource/device/list", token, self._page(page_num, page_size)
        )

    def channel_list(self, token: str, sn_list: list[str]) -> AccountRequest:
        if (
            type(sn_list) is not list
            or not 1 <= len(sn_list) <= self.bounds.max_selectors
        ):
            raise AccountProtocolError("Invalid directory protocol input.")
        selectors = [self._selector(value) for value in sn_list]
        if len(set(selectors)) != len(selectors):
            raise AccountProtocolError("Invalid directory protocol input.")
        return self._send("/resource/channel/list", token, {"snList": list(selectors)})

    def device_detail(self, token: str, sn: str, return_chl: bool) -> AccountRequest:
        if type(return_chl) is not bool:
            raise AccountProtocolError("Invalid directory protocol input.")
        return self._send(
            "/resource/device/detail",
            token,
            {"sn": self._selector(sn), "returnChl": return_chl},
        )

    def channel_detail(self, token: str, sn: str, chl_index: int) -> AccountRequest:
        return self._send(
            "/resource/channel/detail",
            token,
            {
                "sn": self._selector(sn),
                "chlIndex": _integer(chl_index, 0, MAX_NATIVE_INT),
            },
        )

    def _shares(
        self,
        path: str,
        token: str,
        page_num: int,
        page_size: int,
        resource_types: list[int],
    ) -> AccountRequest:
        data = self._page(page_num, page_size)
        if (
            type(resource_types) is not list
            or len(resource_types) > self.bounds.max_resource_types
        ):
            raise AccountProtocolError("Invalid directory protocol input.")
        types = [_integer(value, -(2**31), MAX_NATIVE_INT) for value in resource_types]
        if len(set(types)) != len(types):
            raise AccountProtocolError("Invalid directory protocol input.")
        if types:
            data["resourceTypes"] = list(types)
        return self._send(path, token, data)

    def sent_shares(
        self, token: str, page_num: int, page_size: int, resource_types: list[int]
    ) -> AccountRequest:
        return self._shares(
            "/resource/channel/share/to-other/list",
            token,
            page_num,
            page_size,
            resource_types,
        )

    def received_shares(
        self, token: str, page_num: int, page_size: int, resource_types: list[int]
    ) -> AccountRequest:
        return self._shares(
            "/resource/channel/share/from-other/list",
            token,
            page_num,
            page_size,
            resource_types,
        )
