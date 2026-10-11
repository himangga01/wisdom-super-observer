"""Viewer-local consumption of original IPC credits and immutable cut bindings."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from wso_core.tvt.local_media_mux_service import MuxMediaExecutor, PreparedMuxViewer
from wso_core.tvt.local_media_mux_types import (
    IngressCut,
    MuxValidatedFrame,
    ViewerCleanupReceipt,
    ViewerGrant,
)
from wso_core.tvt.local_media_service import LocalLiveProof

from .codec import MediaDenied

if TYPE_CHECKING:
    from .mux_budget import MediaCreditLedger
    from .native_source import FailureObserver, NativeDecodedSource


class MuxSourceFactory:
    """Explicit worker profile: shared sub wrappers or exclusive dedicated main."""

    def __init__(self, executor: MuxMediaExecutor, credit: MediaCreditLedger) -> None:
        self.executor, self.credit = executor, credit

    async def __call__(
        self,
        lease_id: UUID,
        executable: Path,
        *,
        proof: LocalLiveProof,
        observe: FailureObserver | None = None,
    ) -> NativeDecodedSource:
        from .native_source import NativeDecodedSource

        registration = await asyncio.to_thread(self.executor.registration, lease_id)
        mode = await asyncio.to_thread(self.executor.source_mode, lease_id)
        if mode == "sub":
            handle, grant = await asyncio.to_thread(self.executor.mux_binding, lease_id)

            def read(**limits: float) -> tuple[MuxValidatedFrame, ...]:
                deadline = float(limits["deadline_monotonic"])
                return self.executor.read_mux_frames(
                    lease_id,
                    max_frames=int(limits["max_frames"]),
                    max_bytes=int(limits["max_bytes"]),
                    deadline_ms=max(1, int((deadline - time.monotonic()) * 1000)),
                )

            ingress = MuxFrameSource(
                handle,
                grant,
                registration,
                handle.cut,
                self.credit,
                binding=lambda: self.executor.mux_binding(lease_id),
                read=read,
                release=lambda batch: self.executor.release_mux_frames(lease_id, batch),
            )
        elif mode == "main":
            ingress = None
        else:
            raise MediaDenied()
        return NativeDecodedSource(
            self.executor,
            lease_id,
            executable,
            proof=proof,
            observe=observe,
            frame_source=ingress,
            media_credit=self.credit,
            registration=registration,
            dedicated=ingress is None,
        )


class MuxFrameSource:
    """A returned batch retains its IPC charge until every consumer settles.

    It is never copied into a second encoded ledger. The exact original tuple is
    released through the original executor/provider only after the last picture.
    """

    def __init__(
        self,
        viewer: PreparedMuxViewer,
        grant: ViewerGrant,
        registration: UUID,
        cut: IngressCut,
        credit: MediaCreditLedger,
        *,
        binding: Callable[[], tuple[PreparedMuxViewer, ViewerGrant]] | None = None,
        read: Callable[..., tuple[MuxValidatedFrame, ...]] | None = None,
        release: Callable[[tuple[MuxValidatedFrame, ...]], None] | None = None,
    ) -> None:
        if (
            type(grant) is not ViewerGrant
            or type(cut) is not IngressCut
            or type(registration) is not UUID
            or registration != grant.registration
            or registration != cut.registration
            or grant.slot != cut.slot
        ):
            raise MediaDenied()
        self.viewer, self.grant = viewer, grant
        self.registration, self.cut, self.credit = registration, cut, credit
        self._binding = binding or (lambda: (viewer, viewer.current_grant()))
        self._read = read or viewer.read_frames
        self._release = release or viewer.release_frames
        self._lock = threading.RLock()
        self._batches: dict[int, tuple[tuple[MuxValidatedFrame, ...], set[int]]] = {}
        self._frames: dict[int, int] = {}
        self._reading = 0
        self._stopped = False

    def current(self) -> bool:
        try:
            handle, grant = self._binding()
            with self._lock:
                old = self.grant
                allowed = (
                    not self._stopped
                    and handle is self.viewer
                    and type(grant) is ViewerGrant
                    and grant.scope == old.scope
                    and grant._authority is old._authority
                    and grant.lease_id == old.lease_id
                    and grant.registration == self.registration
                    and grant.slot == self.cut.slot
                    and handle.registration == self.registration
                    and handle.cut is self.cut
                    and time.monotonic() < grant.expires_monotonic
                )
            if not allowed or not handle.current():
                raise MediaDenied()
            with self._lock:
                if (
                    self._stopped
                    or handle.cut is not self.cut
                    or handle.registration != self.registration
                    or time.monotonic() >= grant.expires_monotonic
                ):
                    self._stopped = True
                    return False
                self.grant = grant
            return True
        except Exception:  # noqa: BLE001 -- authority failures permanently fence this viewer.
            with self._lock:
                self._stopped = True
            return False

    def read_frames(
        self, *, max_frames: int, max_bytes: int, deadline_monotonic: float
    ) -> tuple[MuxValidatedFrame, ...]:
        if (
            type(max_frames) is not int
            or not 1 <= max_frames <= 16
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 4 << 20
            or time.monotonic() >= deadline_monotonic
            or not self.current()
        ):
            raise MediaDenied()
        with self._lock:
            if self._stopped or self._reading:
                raise MediaDenied()
            self._reading += 1
        batch = None
        retained = False
        try:
            batch = self._read(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            if (
                type(batch) is not tuple
                or len(batch) > max_frames
                or any(
                    type(f) is not MuxValidatedFrame
                    or f.slot != self.cut.slot
                    or f.ingress.first <= self.cut.after_ordinal
                    for f in batch
                )
                or sum(len(f.frame.private_bytes()) for f in batch) > max_bytes
                or time.monotonic() >= deadline_monotonic
                or not self.current()
            ):
                raise MediaDenied()
            with self._lock:
                identifiers = {id(f) for f in batch}
                if (
                    self._stopped
                    or len(identifiers) != len(batch)
                    or identifiers.intersection(self._frames)
                ):
                    raise MediaDenied()
                if batch:
                    self._batches[id(batch)] = batch, identifiers
                    self._frames.update((ident, id(batch)) for ident in identifiers)
                retained = True
            return batch
        finally:
            try:
                if batch is not None and not retained:
                    self._release(batch)
            finally:
                with self._lock:
                    self._reading -= 1

    def release_frame(self, frame: MuxValidatedFrame) -> None:
        with self._lock:
            batch_id = self._frames.get(id(frame))
            if batch_id is None:
                raise MediaDenied()
            batch, pending = self._batches[batch_id]
            if not any(item is frame for item in batch):
                raise MediaDenied()
            if len(pending) == 1:
                # Keep the tuple and ownership if original release fails.
                self._release(batch)
                del self._batches[batch_id]
            pending.remove(id(frame))
            del self._frames[id(frame)]

    def close(self) -> ViewerCleanupReceipt | None:
        with self._lock:
            self._stopped = True
            if self._reading or self._batches:
                return None
        return self.viewer.close()
