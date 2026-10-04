"""Worker-only credential-free owned Windows live session port."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, NoReturn, SupportsIndex

from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_live import PrivateLiveFrame
from wso_core.tvt.local_media_service import LocalLiveProof, LocalMediaChannel
from wso_core.tvt.local_service import LocalDeviceFailure

from .local_live_ipc import (
    MAX_QUEUE_BYTES,
    MAX_QUEUE_FRAMES,
    LiveParentAuthority,
    frame_storage,
)
from .windows_socket import (
    PENDING_OWNERS,
    ChildOwner,
    PrivateRequest,
    ProviderBusy,
    ProviderConfig,
    WindowsSocketProvider,
)


@dataclass(frozen=True, slots=True, repr=False)
class LiveSelection:
    channel_guid: bytes
    raw_index: int
    window_index: int
    ordinal: int
    stream: Literal["main"] = "main"

    def __post_init__(self) -> None:
        if (
            type(self.channel_guid) is not bytes
            or len(self.channel_guid) != 16
            or self.channel_guid == bytes(16)
            or type(self.raw_index) is not int
            or not -128 <= self.raw_index <= 255
            or type(self.window_index) is not int
            or not 0 <= self.window_index <= 65535
            or type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 256
            or self.stream != "main"
        ):
            raise ValueError("Invalid private live selection")


def failure(reason: str) -> LocalDeviceFailure:
    code, status = {
        "cancelled": ("LOCAL_DEVICE_CANCELLED", 409),
        "deadline": ("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504),
        "denied": ("LOCAL_DEVICE_DENIED", 404),
        "overflow": ("LOCAL_DEVICE_UNAVAILABLE", 503),
        "closed": ("LOCAL_DEVICE_DENIED", 404),
    }.get(reason, ("LOCAL_DEVICE_PROTOCOL_INVALID", 502))
    return LocalDeviceFailure(code, status)


class OwnedLocalLiveSession:
    __slots__ = ("_authority", "_lock", "_owner", "proof")

    def __init__(self, owner: ChildOwner, authority: LiveParentAuthority) -> None:
        if not authority.ready or not authority.frames or authority.setup_data is None:
            raise failure("protocol")
        frame = authority.frames[0]
        data = authority.setup_data
        self._owner, self._authority = owner, authority
        self.proof = LocalLiveProof(
            data["login_accepted"],
            True,
            data["serial_matched"],
            frame.identity.channel == authority.selection.channel_guid,
            data["live_basis"] in ("legacy_no_group", "explicit_lp"),
            frame.summary().codec in ("h264", "h265"),
            bool(frame.source_header.private_bytes()),
            frame.device_timestamp.unix_microseconds is not None,
            "hevc" if frame.summary().codec == "h265" else "h264",
        )
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "<OwnedLocalLiveSession: private>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("Private session cannot be serialized")

    def current(
        self, *, deadline_monotonic: float, current: Callable[[], bool]
    ) -> bool:
        with self._lock:
            if self._owner.confirmed or not self._authority.renew(
                deadline_monotonic, current
            ):
                self._close()
                return False
            if (
                self._owner.child is None
                or self._owner.child.poll() is not None
                or not self._authority.pump(current)
            ):
                self._close()
                return False
            return True

    def read_frames(
        self,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_monotonic: float,
        current: Callable[[], bool],
    ) -> tuple[PrivateLiveFrame, ...]:
        with self._lock:
            if (
                type(max_frames) is not int
                or not 1 <= max_frames <= MAX_QUEUE_FRAMES
                or type(max_bytes) is not int
                or not 1 <= max_bytes <= MAX_QUEUE_BYTES
                or type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic)
                or not 0 < deadline_monotonic - time.monotonic() <= 20
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
            authority = self._authority
            try:
                if not authority.renew(time.monotonic() + 30, current):
                    raise failure(authority.failure)
                while not authority.frames and time.monotonic() < deadline_monotonic:
                    if (
                        self._owner.confirmed
                        or self._owner.child is None
                        or self._owner.child.poll() is not None
                    ):
                        authority.deny("protocol")
                    if not authority.tick(current):
                        raise failure(authority.failure)
                    time.sleep(0.005)
                if not authority.check(current):
                    raise failure(authority.failure)
                result: list[PrivateLiveFrame] = []
                size = 0
                while authority.frames and len(result) < max_frames:
                    frame = authority.frames[0]
                    length = len(frame.private_bytes())
                    if size + length > max_bytes:
                        break
                    if not authority.check(current):
                        raise failure(authority.failure)
                    result.append(authority.frames.popleft())
                    size += length
                    authority.queued_bytes -= frame_storage(frame)
                if not authority.check(current):
                    raise failure(authority.failure)
                return tuple(result)
            except BaseException:
                self._close()
                raise

    def _close(self) -> bool:
        self._authority.deny("closed")
        confirmed = self._owner.finish()
        confirmed = self._authority.wait_retirement() and confirmed
        if confirmed and self._owner in PENDING_OWNERS:
            PENDING_OWNERS.remove(self._owner)
        return confirmed

    def close(self) -> bool:
        with self._lock:
            return self._close()


class NativeLocalLiveProvider:
    __slots__ = ("_config",)

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def open_session(
        self,
        credentials: LocalDeviceCredentials,
        selection: LiveSelection | LocalMediaChannel,
        *,
        deadline_monotonic: float,
        current: Callable[[], bool],
        cancel: threading.Event,
    ) -> OwnedLocalLiveSession:
        authority = LiveParentAuthority(deadline_monotonic, cancel, selection)
        native = WindowsSocketProvider()
        request = None
        session: OwnedLocalLiveSession | None = None
        error: LocalDeviceFailure | None = None
        try:
            if type(selection) is LocalMediaChannel:
                if selection.stream != "main":
                    raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
                selection = LiveSelection(
                    selection.guid,
                    selection.raw_index,
                    selection.window_index,
                    selection.ordinal,
                    "main",
                )
                authority.selection = selection
            if (
                type(credentials) is not LocalDeviceCredentials
                or type(selection) is not LiveSelection
                or not callable(current)
                or type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic > time.monotonic() + 20
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
            if not authority.check(current):
                raise failure(authority.failure)
            request = PrivateRequest(
                "live",
                credentials.country,
                credentials.serial,
                credentials.username,
                credentials.password,
                metadata_read_opt_in=True,
                live_read_opt_in=True,
                store_ref="SERVICE",
                channel_position=selection.ordinal,
            )
            native.run(self._config, request, service=authority, current=current)
            if (
                not authority.handed_off
                or native.owner is None
                or not authority.check(current)
            ):
                raise failure(authority.failure or "protocol")
            session = OwnedLocalLiveSession(native.owner, authority)
            native.owner = None
        except ProviderBusy:
            error = LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
        except LocalDeviceFailure as caught:
            error = LocalDeviceFailure(caught.code, caught.status)
        except Exception:  # noqa: BLE001 -- fixed private provider boundary
            error = failure("protocol")
        finally:
            request = None
            del credentials
            if native.owner is not None:
                native.owner.finish()
                if native.owner.confirmed and native.owner in PENDING_OWNERS:
                    PENDING_OWNERS.remove(native.owner)
            elif not authority.handed_off:
                authority.close()
        if session is not None:
            return session
        assert error is not None
        raise error from None
