"""Private managed USER directory composition; worker admission is separate.

AccountClient owns the sole process/TLS/deadline/DC/cancel/quarantine boundary.
Scope equality only proves consistency. W02 must supply current admitted bytes.
"""

from __future__ import annotations

from collections.abc import Callable

from wso_contracts.tvt.identity import AccountScope, TvtIdentityRef

from .account_client import AccountClient
from .account_protocol import (
    AccountProtocol,
    AccountProtocolError,
    AccountRequest,
    AccountResponse,
    SessionTaskIds,
)
from .account_transport import OriginPolicy
from .directory_projection import (
    ChannelDirectory,
    DevicePage,
    ObjectObservation,
    Presence,
    SharePage,
    parse_channel_detail,
    parse_channel_list,
    parse_device_detail,
    parse_device_list,
    parse_received_shares,
    parse_sent_shares,
)
from .directory_protocol import DEFAULT_BOUNDS, DirectoryBounds, DirectoryProtocol
from .ports import AccountResult, PrivateToken


class DirectoryClient:
    def __init__(
        self,
        scope: AccountScope,
        policy: OriginPolicy,
        *,
        origin: str,
        identity: TvtIdentityRef,
        protocol: DirectoryProtocol | None = None,
        bounds: DirectoryBounds = DEFAULT_BOUNDS,
        max_body_bytes: int = 65_536,
    ) -> None:
        if protocol is not None and type(protocol) is not DirectoryProtocol:
            raise AccountProtocolError("Invalid directory protocol input.")
        self._directory = protocol or DirectoryProtocol(
            AccountProtocol(task_ids=SessionTaskIds()), bounds=bounds
        )
        self._account = AccountClient(
            scope,
            policy,
            origin=origin,
            identity=identity,
            protocol=self._directory._account,
            max_body_bytes=max_body_bytes,
        )

    def close(self) -> None:
        self._account.close()

    def _execute[T](
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        request: Callable[[], AccountRequest],
        parse: Callable[[AccountResponse], T],
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[T]:
        return self._account._run(
            lambda: self._account._postlogin(scope, token),
            request,
            parse,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def device_list(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        page_num: int,
        page_size: int,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[DevicePage]:
        return self._execute(
            scope,
            token,
            lambda: self._directory.device_list(token.value, page_num, page_size),
            lambda response: parse_device_list(response, bounds=self._directory.bounds),
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def channel_list(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        sn_list: list[str],
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[ChannelDirectory]:
        selectors = sn_list.copy() if type(sn_list) is list else sn_list

        def decode(response: AccountResponse) -> ChannelDirectory:
            result = parse_channel_list(response, bounds=self._directory.bounds)
            seen: set[str] = set()
            for device in result.devices:
                sn = device.field("sn").value
                if not isinstance(sn, str) or sn not in selectors or sn in seen:
                    raise AccountProtocolError("Invalid directory response.")
                seen.add(sn)
                channels = device.field("chls").value
                if isinstance(channels, tuple):
                    indices: set[int] = set()
                    for channel in channels:
                        assert isinstance(channel, ObjectObservation)
                        index = channel.field("chlIndex").value
                        if type(index) is int:
                            if index in indices:
                                raise AccountProtocolError(
                                    "Invalid directory response."
                                )
                            indices.add(index)
            return result

        return self._execute(
            scope,
            token,
            lambda: self._directory.channel_list(token.value, selectors),
            decode,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def device_detail(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        sn: str,
        return_chl: bool,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[ObjectObservation]:
        def decode(response: AccountResponse) -> ObjectObservation:
            result = parse_device_detail(response, bounds=self._directory.bounds)
            info = result.field("devInfo").value
            if isinstance(info, ObjectObservation):
                self._match(info, "sn", sn)
            channels = result.field("chlInfos").value
            if isinstance(channels, tuple):
                for channel in channels:
                    assert isinstance(channel, ObjectObservation)
                    self._match(channel, "sn", sn)
            return result

        return self._execute(
            scope,
            token,
            lambda: self._directory.device_detail(token.value, sn, return_chl),
            decode,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def channel_detail(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        sn: str,
        chl_index: int,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[ObjectObservation]:
        def decode(response: AccountResponse) -> ObjectObservation:
            result = parse_channel_detail(response, bounds=self._directory.bounds)
            self._match(result, "sn", sn)
            self._match(result, "chlIndex", chl_index)
            return result

        return self._execute(
            scope,
            token,
            lambda: self._directory.channel_detail(token.value, sn, chl_index),
            decode,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _match(result: ObjectObservation, key: str, expected: str | int) -> None:
        observed = result.field(key)
        if observed.state is Presence.VALUE and observed.value != expected:
            raise AccountProtocolError("Invalid directory response.")

    def sent_shares(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        page_num: int,
        page_size: int,
        resource_types: list[int],
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[SharePage]:
        return self._execute(
            scope,
            token,
            lambda: self._directory.sent_shares(
                token.value, page_num, page_size, resource_types
            ),
            lambda response: parse_sent_shares(response, bounds=self._directory.bounds),
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def received_shares(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        page_num: int,
        page_size: int,
        resource_types: list[int],
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[SharePage]:
        return self._execute(
            scope,
            token,
            lambda: self._directory.received_shares(
                token.value, page_num, page_size, resource_types
            ),
            lambda response: parse_received_shares(
                response, bounds=self._directory.bounds
            ),
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )
