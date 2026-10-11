"""Sealed media ownership over the bridge's single retained host ledger."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from wso_core.tvt.local_media_mux_types import MuxSlotIdentity

from .codec import MediaDenied

if TYPE_CHECKING:
    from wso_tvt_bridge.local_live_mux_ipc import MediaCreditToken

EncodedStage = Literal["callback", "parent", "source", "decode"]
MediaStage = Literal["callback", "parent", "source", "decode", "rgb", "conversion"]
_SEAL = object()


@dataclass(frozen=True, slots=True, repr=False)
class MediaCredit:
    id: UUID
    slot: MuxSlotIdentity | None
    registration: UUID | None
    frames: int
    bytes: int
    stage: MediaStage
    _seal: InitVar[object] = field(kw_only=True)

    def __post_init__(self, _seal: object) -> None:
        if _seal is not _SEAL:
            raise MediaDenied()


class MediaCreditLedger:
    """Transfers change the exact owner, never refund and reserve again.

    Already charged IPC frames do not enter this ledger: their original batch
    stays in MuxFrameSource until its downstream consumers release it.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._held: dict[UUID, tuple[MediaCredit, MediaCreditToken]] = {}
        self._rgb: set[UUID] = set()

    def _reserve(
        self,
        slot: MuxSlotIdentity | None,
        registration: UUID | None,
        frames: int,
        size: int,
        stage: MediaStage,
    ) -> MediaCredit | None:
        from wso_tvt_bridge.local_live_mux_ipc import reserve_media_credit

        if type(size) is not int or size <= 0:
            raise MediaDenied()
        with self._lock:
            if stage == "rgb" and (size > 16 << 20 or registration in self._rgb):
                return None
            token = reserve_media_credit(
                slot=slot,
                registration=registration,
                frames=frames,
                bytes=size,
                stage=stage,
            )
            if token is None:
                return None
            credit = MediaCredit(
                uuid4(), slot, registration, frames, size, stage, _seal=_SEAL
            )
            self._held[credit.id] = credit, token
            if stage == "rgb":
                assert registration is not None
                self._rgb.add(registration)
            return credit

    def reserve_encoded(
        self, slot: MuxSlotIdentity, frames: int, bytes: int
    ) -> MediaCredit | None:
        return self._reserve(slot, None, frames, bytes, "callback")

    def reserve_dedicated(
        self, registration: UUID, *, frames: int, bytes: int
    ) -> MediaCredit | None:
        return self._reserve(None, registration, frames, bytes, "source")

    def reserve_rgb(self, registration: UUID, bytes: int) -> MediaCredit | None:
        return self._reserve(None, registration, 0, bytes, "rgb")

    def reserve_conversion(self, registration: UUID, bytes: int) -> MediaCredit | None:
        return self._reserve(None, registration, 0, bytes, "conversion")

    def _original(self, credit: MediaCredit) -> tuple[MediaCredit, MediaCreditToken]:
        if type(credit) is not MediaCredit:
            raise MediaDenied()
        original = self._held.get(credit.id)
        if original is None or original[0] is not credit:
            raise MediaDenied()
        return original

    def transfer(self, credit: MediaCredit, stage: EncodedStage) -> MediaCredit:
        stages = ("callback", "parent", "source", "decode")
        with self._lock:
            _, token = self._original(credit)
            if (
                stage not in stages
                or credit.stage not in stages
                or stages.index(stage) <= stages.index(credit.stage)
            ):
                raise MediaDenied()
            moved = MediaCredit(
                credit.id,
                credit.slot,
                credit.registration,
                credit.frames,
                credit.bytes,
                stage,
                _seal=_SEAL,
            )
            self._held[credit.id] = moved, token
            return moved

    def release(self, credit: MediaCredit) -> None:
        from wso_tvt_bridge.local_live_mux_ipc import release_media_credit

        with self._lock:
            _, token = self._original(credit)
            release_media_credit(token)
            del self._held[credit.id]
            if credit.stage == "rgb":
                assert credit.registration is not None
                self._rgb.remove(credit.registration)
