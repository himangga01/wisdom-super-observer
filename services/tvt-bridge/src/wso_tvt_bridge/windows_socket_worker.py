"""Isolated Windows AMD64 worker; vendor loading occurs only after Root gate."""

from __future__ import annotations

import ctypes as ct
import hashlib
import json
import math
import os
import platform
import queue
import re
import struct
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from xml.dom import minidom
from xml.parsers import expat

from wso_core.tvt.local_inventory import (
    InventoryEvidence,
    InventoryRejected,
    InventorySession,
    ReadQuery,
)
from wso_core.tvt.local_live import (
    LiveAcknowledgement,
    LiveCodec,
    LiveDenied,
    LiveError,
    LiveIdentity,
    LiveRefused,
    PrivateLiveFrame,
    UnsupportedLive,
)
from wso_core.tvt.local_media_mux_types import (
    MAX_ORDINAL,
    IngressChunk,
    IngressCut,
    IngressSpan,
    MuxEpochIdentity,
    MuxSlotIdentity,
)
from wso_core.tvt.local_n9000 import (
    CodecError,
    Credentials,
    LoginHandshake,
    LoginRejected,
    LoginResult,
    N9000Stream,
    UnsupportedBranch,
    parse_greeting,
)

from .local_inventory_ipc import AuthorityError, RemoteAuthority, encode
from .windows_socket import (
    ACCEPTED_HASHES,
    CAP,
    OWNED,
    ROOT,
    PrivateRequest,
    ProviderConfig,
    ProviderError,
    SafeResult,
    check_private_acl,
    fail,
    file_hash,
    identity,
    json_object,
    parse_result,
    protect_created_acl,
    read_original,
    runtime_override,
    select_trusted_nat2,
    validate_bundle,
    verify_review,
)

I32, U32, U16, U64, BOOL, PTR = (
    ct.c_int32,
    ct.c_uint32,
    ct.c_uint16,
    ct.c_uint64,
    ct.c_bool,
    ct.c_void_p,
)
# These physical slot aliases preserve explicit this; no vendor C++ class exists.
DELETE = ct.CFUNCTYPE(PTR, PTR, U32)
DATA = ct.CFUNCTYPE(I32, PTR, U32, PTR, I32, PTR, PTR)


class ObserverTable(ct.Structure):
    _fields_ = [("deleting_destructor", DELETE), ("data", DATA)]


class Observer(ct.Structure):
    _fields_ = [("vptr", ct.POINTER(ObserverTable))]


SPECS: dict[str, tuple[str, Any, tuple[Any, ...]]] = {
    "initial": (
        "?NET_SOCKET_Initial@@YA_NHHPEBDI@Z",
        BOOL,
        (I32, I32, ct.c_char_p, U32),
    ),
    "quit": ("?NET_SOCKET_Quit@@YAXXZ", None, ()),
    "last_error": ("?NET_SOCKET_GetLastError@@YAIXZ", U32, ()),
    "config": (
        "?NET_SOCKET_SetP2PServerAddr@@YAXPEBDI_N0I@Z",
        None,
        (ct.c_char_p, U32, BOOL, ct.c_char_p, U32),
    ),
    "connect_sn": (
        "?NET_SOCKET_AddConnectByP2P2@@YAHIPEBDG@Z",
        I32,
        (U32, ct.c_char_p, U16),
    ),
    "connect_result": (
        "?NET_SOCKET_PopConnectResult@@YA_NHAEAHI@Z",
        BOOL,
        (I32, ct.POINTER(I32), U32),
    ),
    "connected": ("?NET_SOCKET_CheckConnectState@@YA_NH@Z", BOOL, (I32,)),
    "register": (
        "?NET_SOCKET_RegisterNode@@YA_NHPEAVCSocketDataObserver@@PEAXHH@Z",
        BOOL,
        (I32, ct.POINTER(Observer), PTR, I32, I32),
    ),
    "start": ("?NET_SOCKET_Start@@YA_NH@Z", BOOL, (I32,)),
    "stop": ("?NET_SOCKET_Stop@@YAXH@Z", None, (I32,)),
    "destroy": ("?NET_SOCKET_DestroyHNetCommunication@@YAXH@Z", None, (I32,)),
    "del_connect": ("?NET_SOCKET_DelConnect@@YAXH@Z", None, (I32,)),
    "unregister": ("?NET_SOCKET_UnRegisterNode@@YAXH@Z", None, (I32,)),
    "greeting": (
        "?NET_SOCKET_Recv_Immediate@@YAHHPEADH_NI@Z",
        I32,
        (I32, ct.POINTER(ct.c_char), I32, BOOL, U32),
    ),
    "send": (
        "?NET_SOCKET_Send@@YAHHPEBD_K01PEAV?$CChildPairContainer@PEAEH@@I@Z",
        I32,
        (I32, ct.c_char_p, U64, ct.c_char_p, U64, PTR, U32),
    ),
}
RETAINED: list[object] = []
# Official client fu3.N1 timer -> cw3.v5: outer N9000 length-0 heartbeat (magic
# 0x31313131 is byte-order symmetric) at a fixed 6000ms delay. serve_live sends
# it only while its original live task is open, with the open/close Send gating.
LIVE_KEEPALIVE = b"\x31\x31\x31\x31\x00\x00\x00\x00"
LIVE_KEEPALIVE_SECONDS = 6.0


def validate_layout(*, production: bool = True) -> None:
    if production and (
        os.name != "nt"
        or platform.machine().upper() != "AMD64"
        or ct.sizeof(ct.c_long) != 4
        or platform.python_implementation() != "CPython"
        or sys.version_info[:2] != (3, 12)
    ):
        fail()
    if (
        (
            ct.sizeof(PTR),
            ct.sizeof(I32),
            ct.sizeof(U32),
            ct.sizeof(U16),
            ct.sizeof(BOOL),
            ct.sizeof(Observer),
            ct.sizeof(ObserverTable),
        )
        != (8, 4, 4, 2, 1, 8, 16)
        or Observer.vptr.offset != 0
        or ObserverTable.data.offset != 8
    ):
        fail()


class Surface(Protocol):
    def call(self, name: str, *args: Any) -> Any: ...


class NativeSurface:
    def __init__(
        self,
        bundle: Path,
        manifest: list[dict[str, Any]],
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        validate_layout()
        retained = validate_bundle(bundle, manifest)
        check_private_acl(bundle)
        for row in manifest:
            check_private_acl(bundle / row["name"])
        if overrides:
            verify_runtime_override(overrides, mapped_module)
        # Absolute scoped loader search: never PATH, server copies or cwd.
        self.library = ct.CDLL(str(bundle / "NetSocket.dll"), winmode=0x100 | 0x800)
        RETAINED.append(self.library)
        self.runtime_substitutions = verify_mapped(
            bundle, manifest, retained, mapped_module, overrides
        )
        self.functions: dict[str, Any] = {}
        for name, (symbol, result, args) in SPECS.items():
            function = getattr(self.library, symbol)
            function.restype, function.argtypes = result, list(args)
            self.functions[name] = function

    def call(self, name: str, *args: Any) -> Any:
        return self.functions[name](*args)


def mapped_module(name: str) -> Path:
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ct.c_wchar_p]
    kernel.GetModuleHandleW.restype = PTR
    kernel.GetModuleFileNameW.argtypes = [PTR, ct.c_wchar_p, U32]
    kernel.GetModuleFileNameW.restype = U32
    handle = kernel.GetModuleHandleW(name)
    if not handle:
        fail()
    buffer = ct.create_unicode_buffer(32768)
    size = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
    if not 0 < size < len(buffer):
        fail()
    return Path(buffer.value)


def verify_mapped(
    bundle: Path,
    manifest: list[dict[str, Any]],
    retained: dict[str, tuple[int, int]],
    lookup: Callable[[str], Path],
    overrides: dict[str, dict[str, Any]] | None = None,
) -> int:
    substitutions = 0
    if overrides:
        verify_runtime_override(overrides, lookup)
    for row in manifest:
        name = row["name"]
        actual = lookup(name)
        if (
            overrides
            and name in overrides
            and os.path.normcase(str(actual)) != os.path.normcase(str(bundle / name))
        ):
            substitutions += 1
            continue
        if (
            os.path.normcase(str(actual)) != os.path.normcase(str(bundle / name))
            or identity(actual) != retained[name]
            or file_hash(actual) != {k: row[k] for k in ("bytes", "sha256")}
        ):
            fail()
    return substitutions


def verify_runtime_override(
    overrides: dict[str, dict[str, Any]], lookup: Callable[[str], Path]
) -> None:
    expected = {
        "vcruntime140.dll": (
            120400,
            "052ad6a20d375957e82aa6a3c441ea548d89be0981516ca7eb306e063d5027f4",
        ),
        "vcruntime140_1.dll": (
            49776,
            "6a99bc0128e0c7d6cbbf615fcc26909565e17d4ca3451b97f8987f9c6acbc6c8",
        ),
    }
    if set(overrides) != set(expected):
        fail()
    for name, (size, digest) in expected.items():
        row = overrides[name]
        if (
            set(row) != {"path", "bytes", "sha256", "version"}
            or type(row["bytes"]) is not int
            or row["bytes"] != size
            or row["version"] != "14.42.34438.0"
            or row["sha256"] != digest
        ):
            fail()
        actual = lookup(name)
        if (
            not Path(row["path"]).is_absolute()
            or os.path.normcase(str(actual)) != os.path.normcase(row["path"])
            or file_hash(actual) != {k: row[k] for k in ("bytes", "sha256")}
        ):
            fail()


class CallbackOwner:
    def __init__(self, handle: int, generation: int, *, capacity: int = 65536) -> None:
        self.handle = handle & 0xFFFFFFFF
        self.generation = generation
        self.capacity = capacity
        self.context = U64(generation)
        self.chunks: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self.lock = threading.Lock()
        self.used = 0
        self._live_claimed = False
        self._mux_epoch: MuxEpochIdentity | None = None
        self._mux_chunks: deque[IngressChunk] = deque()
        self._mux_ordinal = 0
        self._mux_cut_sequence = 0
        # CPython3.12 with its GIL: dict.setdefault on this private dict and
        # fixed built-in string key is one indivisible first-terminal claim.
        # Callback contention must latch failure without waiting on queue lock;
        # using the same claim for sealing prevents a check/store race.
        self._terminal: dict[str, str] = {}
        self.delete_callback = DELETE(self._delete)
        self.data_callback = DATA(self._data)
        self.table = ObserverTable(self.delete_callback, self.data_callback)
        self.observer = Observer(ct.pointer(self.table))
        self.this_address = ct.addressof(self.observer)
        self.context_address = ct.addressof(self.context)
        RETAINED.append(self)

    @property
    def failed(self) -> bool:
        return self._terminal.get("outcome") == "failed"

    @property
    def closed(self) -> bool:
        return "outcome" in self._terminal

    @closed.setter
    def closed(self, value: bool) -> None:
        if value:
            self._terminal.setdefault("outcome", "closed")

    def mark_failed(self) -> None:
        self._terminal.setdefault("outcome", "failed")

    def claim_first_live(self) -> bool:
        with self.lock:
            if self.closed or self._live_claimed or self._mux_epoch is not None:
                return False
            self._live_claimed = True
            return True

    def bind_mux_epoch(self, epoch: MuxEpochIdentity) -> None:
        """Select mux once after this original's validated login has drained.

        The caller must prove same-original login/custody. This RAM binding is
        not SDK evidence, a registered-slot check or publication authority.
        Legacy live ownership and shared ownership cannot coexist here.
        """
        with self.lock:
            if (
                self.closed
                or self._live_claimed
                or self._mux_epoch is not None
                or type(epoch) is not MuxEpochIdentity
                or epoch.generation != self.generation
                or self.context.value != self.generation
                or self.used
                or not self.chunks.empty()
            ):
                self.mark_failed()
                raise LiveError()
            self._mux_epoch = epoch
            self.capacity = 1 << 20

    def cut_mux_ingress(
        self,
        *,
        registration: uuid.UUID,
        slot: MuxSlotIdentity,
        control_sequence: int,
        expires_monotonic: float,
    ) -> IngressCut:
        """Local original ingress cut, serialized with pre-copy ordinals.

        Only the private same-generation control reply may export this value.
        Purpose/current/registered-slot checks belong to that control owner;
        a slot supplied here can never establish or replace our bound epoch.
        """
        with self.lock:
            try:
                if (
                    self.closed
                    or self._mux_epoch is None
                    or self.context.value != self.generation
                    or self._mux_epoch.generation != self.generation
                    or type(slot) is not MuxSlotIdentity
                    or slot.epoch != self._mux_epoch
                ):
                    raise LiveError()
                marker = IngressCut(
                    self._mux_epoch,
                    slot,
                    registration,
                    control_sequence,
                    self._mux_ordinal,
                    expires_monotonic,
                )
                if (
                    control_sequence <= self._mux_cut_sequence
                    or expires_monotonic <= time.monotonic()
                    or self.closed
                ):
                    raise LiveError()
                self._mux_cut_sequence = control_sequence
                return marker
            except LiveError:
                self.mark_failed()
                raise

    def take_mux_batch(self) -> tuple[IngressChunk, ...]:
        """Drain a bounded FIFO snapshot without joining or relabeling bytes."""
        with self.lock:
            if self.closed:
                return ()
            if (
                self._mux_epoch is None
                or self.context.value != self.generation
                or self._mux_epoch.generation != self.generation
            ):
                self.mark_failed()
                raise LiveError()
            parts = tuple(self._mux_chunks)
            self._mux_chunks.clear()
            self.used -= sum(len(part.data) for part in parts)
            return parts

    def seal_success(
        self,
        result: SafeResult | None = None,
        accepted: LoginResult | None = None,
        *,
        inventory: InventoryEvidence | None = None,
        guard: Callable[[int], bool] | None = None,
        seal: bool = True,
    ) -> bool:
        """First terminal claim wins; close admission and commit under queue lock.

        No native, capture or codec calls occur while this lock is held. A
        callback unable to acquire it makes the same nonblocking terminal claim.
        Failures after a sealed outcome belong to closed admission and cannot
        change the already committed decision.
        """
        with self.lock:
            if inventory is not None and seal and self.used:
                self.mark_failed()
                return False
            if guard is not None and not guard(self.generation):
                self.mark_failed()
                return False
            if (
                (self._terminal.setdefault("outcome", "sealed") != "sealed")
                if seal
                else self.closed
            ):
                return False
            if result is not None:
                result.stage = "complete" if seal else "live"
                if accepted is not None:
                    result.reply_accepted = True
                    result.proof_verified = accepted.proof_verified
                    result.key_extracted = accepted.key_extracted
                if inventory is not None:
                    result.metadata_branch_complete = True
                    result.inventory_complete = inventory.permissions_complete
                    result.permissions_availability = (
                        "observed"
                        if inventory.permissions_complete
                        else "not_requested_no_group"
                    )
                    result.serial_matched = inventory.serial_matched
                    result.channel_count = len(inventory.channels)
                    result.channels_complete = inventory.channels_complete
                    result.user_observed = inventory.user is not None
                    result.permissions_complete = inventory.permissions_complete
                    result.inventory_availability = inventory.availability.value
            return True

    def _delete(self, this: int, flags: int) -> int:
        # Preserve stable allocation; never free or call a vendor destructor.
        self.mark_failed()
        return this

    def _data(
        self, this: int, handle: int, data: int, length: int, opaque: int, context: int
    ) -> int:
        # No native reentry/file/decode/wait. Incoming pointer validity remains
        # an unproved native obligation; length checks cannot prove its bounds.
        if self.closed:
            return 0
        if (
            self.failed
            or this != self.this_address
            or context != self.context_address
            or handle != self.handle
            or self.context.value != self.generation
            or opaque
            or not data
            or not 0 < length <= self.capacity
            or not self.lock.acquire(False)
        ):
            self.mark_failed()
            return 0
        try:
            if self.closed:
                return 0
            if self.used + length > self.capacity:
                self.mark_failed()
                return 0
            if self._mux_epoch is not None:
                if (
                    self._mux_epoch.generation != self.generation
                    or len(self._mux_chunks) >= 256
                    or self._mux_ordinal >= MAX_ORDINAL
                ):
                    self.mark_failed()
                    return 0
                # Linearize BEFORE touching borrowed bytes. A held copy, queued
                # batch or later partial assembly can never acquire a new origin.
                self._mux_ordinal += 1
                span = IngressSpan(self._mux_ordinal, self._mux_ordinal)
                copied = ct.string_at(data, length)
                if (
                    self.context.value != self.generation
                    or self._mux_epoch.generation != self.generation
                ):
                    self.mark_failed()
                    return 0
                if self.closed:
                    return 0
                self._mux_chunks.append(IngressChunk(copied, span))
                self.used += length
                return length
            self.chunks.put_nowait(ct.string_at(data, length))
            self.used += length
            return length
        except Exception:  # noqa: BLE001 -- exception cannot cross native callback
            self.mark_failed()
            return 0
        finally:
            self.lock.release()

    def take(self) -> bytes | None:
        with self.lock:
            if self._mux_epoch is not None:
                return None
            try:
                chunk = self.chunks.get_nowait()
            except queue.Empty:
                return None
            self.used -= len(chunk)
            return chunk

    def take_live_batch(self) -> bytes | None:
        """Drain the existing bounded FIFO snapshot after one current grant.

        Callback chunks are transport segmentation, not media frames. Preserve
        every byte/order while avoiding one parent roundtrip per small chunk.
        The queue's existing256-chunk/byte-cap bounds also bound this snapshot;
        joins occur outside the callback lock. Source envelopes still receive
        independent current checks/ACKs in the live parser/parent.
        """
        with self.lock:
            if self.failed or self.closed or self._mux_epoch is not None:
                return None
            parts = [self.chunks.get_nowait() for _ in range(self.chunks.qsize())]
            self.used -= sum(len(part) for part in parts)
        return b"".join(parts) if parts else None


class OrdinaryFrames:
    """Bound raw envelopes only; phase-specific accepted codecs own semantics."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        if len(chunk) + len(self.buffer) > 65536:
            raise CodecError("private transport buffer exceeded")
        self.buffer.extend(chunk)

    def take(self) -> bytes | None:
        while len(self.buffer) >= 8:
            magic, size = struct.unpack_from("<II", self.buffer)
            if magic != 825307441:
                raise CodecError("invalid private transport envelope")
            if size == 0xFFFFFFFF:
                raise UnsupportedBranch("inventory_transport_fragmentation")
            if size == 0:
                del self.buffer[:8]
                continue
            if not 16 <= size <= 65528:
                raise CodecError("invalid private transport length")
            if len(self.buffer) < size + 8:
                return None
            raw = bytes(self.buffer[: size + 8])
            del self.buffer[: size + 8]
            return raw
        return None

    def close(self) -> None:
        self.buffer.clear()


def user_group_provenance(wire: bytes, observed: str | None) -> str:
    """Only after InventorySession accepted this same bounded USER reply.

    Preserve e8's DOM firstChild distinction; ET's discarded comments/CDATA or
    scalar trimming must not manufacture the source no-group branch.
    """
    raw = wire[24:]
    marker = raw.find(b"<?xml")
    if marker >= 0:
        raw = raw[marker:]
    raw = raw.strip(bytes(range(33)))
    path: list[str] = []
    group_cdata = False

    def start(name: str, attrs: dict[str, str]) -> None:
        path.append(name)

    def cdata() -> None:
        nonlocal group_cdata
        if len(path) == 3 and path[-2:] == ["content", "authGroupId"]:
            group_cdata = True

    lexical = expat.ParserCreate()
    lexical.StartElementHandler = start
    lexical.EndElementHandler = lambda name: path.pop()
    lexical.StartCdataSectionHandler = cdata
    lexical.Parse(raw, True)
    document = minidom.parseString(raw.decode("utf-8", "strict"))
    try:
        assert document.documentElement is not None
        contents = [
            n
            for n in document.documentElement.childNodes
            if n.nodeType == n.ELEMENT_NODE and n.nodeName == "content"
        ]
        if len(contents) != 1:
            raise UnsupportedBranch("user_group_provenance")
        groups = [
            n
            for n in contents[0].childNodes
            if n.nodeType == n.ELEMENT_NODE and n.nodeName == "authGroupId"
        ]
        if not groups and observed is None:
            return "missing"
        if len(groups) != 1:
            raise UnsupportedBranch("user_group_provenance")
        first = groups[0].firstChild
        if first is None and observed is None and not group_cdata:
            return "empty"
        if (
            first is not None
            and observed is not None
            and first.nodeType in (first.TEXT_NODE, first.CDATA_SECTION_NODE)
            and first.nodeValue == observed
        ):
            return "value"
        raise UnsupportedBranch("user_group_provenance")
    finally:
        document.unlink()


def live_basis(
    evidence: InventoryEvidence,
    request: PrivateRequest,
    channel_guid: bytes,
    group_shape: str,
) -> str:
    user = evidence.user
    if (
        not evidence.serial_matched
        or evidence.serial != request.serial
        or not evidence.channels_complete
        or user is None
    ):
        raise LiveDenied()
    if user.auth_group_id is None:
        if group_shape not in ("missing", "empty") or evidence.permissions_complete:
            raise LiveDenied()
        return "legacy_no_group"
    if group_shape != "value" or not evidence.permissions_complete:
        raise LiveDenied()
    # Admin-only cases are outside this subset: normalized metadata loses raw
    # e8 child ordering/firstChild provenance. Require the actual selected GUID.
    if any(
        item.guid == channel_guid and "lp" in item.symbols
        for item in evidence.permissions
    ):
        return "explicit_lp"
    # Q7/B3's presence-based system expansion is not copied into this boundary.
    raise LiveDenied()


class LiveEnvelopes:
    """Bounded transport mux; accepted LiveCodec owns fragment/order semantics."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.fragment_pending = False

    def feed(self, chunk: bytes) -> None:
        if len(self.buffer) + len(chunk) > 1 << 20:
            raise LiveError()
        self.buffer.extend(chunk)

    def receive(self, chunk: bytes) -> Iterator[tuple[bytes, bool]]:
        offset = 0
        while offset < len(chunk):
            room = (1 << 20) - len(self.buffer)
            if room <= 0:
                raise LiveError()
            size = min(room, len(chunk) - offset)
            self.feed(chunk[offset : offset + size])
            offset += size
            while (envelope := self.take()) is not None:
                yield envelope

    def take(self) -> tuple[bytes, bool] | None:
        if len(self.buffer) < 8:
            return None
        _, size = struct.unpack_from("<Ii", self.buffer)
        was_fragmented = self.fragment_pending
        if size == -1:
            if len(self.buffer) < 32:
                return None
            _, count, _, index, length, _ = struct.unpack_from("<6i", self.buffer, 8)
            if not 1 <= length <= (1 << 20) - 32:
                raise LiveError()
            total = length + 32
            if len(self.buffer) < total:
                return None
            self.fragment_pending = index != count
            was_fragmented = True
        elif size == 0:
            total = 8
        elif 16 <= size <= (1 << 20) - 8:
            total = size + 8
            if len(self.buffer) < total:
                return None
        else:
            raise LiveError()
        raw = bytes(self.buffer[:total])
        del self.buffer[:total]
        return raw, was_fragmented


def capture_live(
    native: Surface,
    handle: int,
    request: PrivateRequest,
    accepted: LoginResult,
    inventory: InventorySession,
    group_shape: str,
    callback: CallbackOwner,
    stream: N9000Stream,
    result: SafeResult,
    deadline: float,
    current: Callable[[int], bool],
    buffers: list[object],
    initial: bytes,
    capture: Callable[[str, bytes], None],
    source_provenance: dict[str, Any] | None,
) -> None:
    result.stage, result.capture_status = "live", "pending"
    codec: LiveCodec | None = None
    manifest: dict[str, Any] | None = None
    open_exact = False
    close_attempted = False
    evidence = inventory.inventory
    generation = callback.generation
    mux = LiveEnvelopes()
    envelopes = 0
    captured: list[dict[str, Any]] = []
    request_ids = (uuid.uuid4().bytes_le, uuid.uuid4().bytes_le, uuid.uuid4().bytes_le)
    try:
        if (
            source_provenance is None
            or request.live_read_opt_in is not True
            or request.metadata_read_opt_in is not True
            or len(set(request_ids)) != 3
        ):
            raise LiveDenied()
        channel = next(
            (c for c in evidence.channels if c.position == request.channel_position),
            None,
        )
        if channel is None or not -128 <= channel.raw_index <= 255:
            raise UnsupportedLive()
        basis = live_basis(evidence, request, channel.guid, group_shape)
        identity = LiveIdentity(
            generation=generation,
            session=accepted.session_guid,
            channel=channel.guid,
            task=request_ids[0],
        )
        store_ref, serial = request.store_ref, request.serial

        def authorize(given: LiveIdentity) -> bool:
            return (
                given is identity
                and given.generation == generation
                and given.session == accepted.session_guid
                and given.channel == channel.guid
                and request.store_ref == store_ref
                and request.serial == serial
                and request.channel_position == channel.position
                and request.live_read_opt_in is True
                and request.metadata_read_opt_in is True
                and evidence.generation == generation
                and inventory.inventory is evidence
                and inventory.state == "ready"
                and callback.handle == (handle & 0xFFFFFFFF)
                and current(generation)
                and live_basis(evidence, request, channel.guid, group_shape) == basis
            )

        if not callback.claim_first_live():
            raise LiveDenied()
        codec = LiveCodec(
            identity=identity,
            peer_capability=accepted.peer_version,
            channel_number=channel.raw_index & 255,
            stream=1,
            exclusive_first_task=True,
            authorize=authorize,
            max_packet=1 << 20,
            max_session_bytes=8 << 20,
            max_packets=256,
            max_fragments=64,
        )
        binding = {
            "store_ref": store_ref,
            "serial": serial,
            "generation": result.generation,
            "callback_generation": generation,
            "device_guid_le": accepted.device_guid.hex(),
            "session_guid_le": identity.session.hex(),
            "channel_guid_le": identity.channel.hex(),
            "task_guid_le": identity.task.hex(),
            "task_guid_provenance": "local_owner_generated",
            "channel_position": channel.position,
            "raw_index": channel.raw_index,
            "wire_channel_number": channel.raw_index & 255,
            "stream": 1,
            "peer_version": accepted.peer_version,
            "peer_version_source": "accepted_login_wz0_h4_Z9_ub_R3",
            "open_request_guid_le": request_ids[1].hex(),
            "close_request_guid_le": request_ids[2].hex(),
            "open_sequence": 6,
            "close_sequence": 7,
        }
        manifest = {
            "schema": 1,
            "binding": binding,
            "sources": source_provenance,
            "metadata_branch": "no_group"
            if group_shape in ("missing", "empty")
            else "group",
            "group_shape": group_shape,
            "permissions_availability": result.permissions_availability,
            "upstream_eligibility": basis,
            "source_roster": "complete_same_login_tail_and_detail_join",
            "operator_read_opt_in": True,
            "operator_live_opt_in": True,
            "connection_task_policy": "fresh_original_socket_first_and_only_stream1_open",
            "proof_verified": accepted.proof_verified,
            "authorized": False,
            "live": False,
            "frames": captured,
            "raw_receive_file": "live-receive.bin",
            "raw_receive_role": "unvalidated_original_transport_diagnostic_only",
            "capture_starts_at_key": False,
            "annexb_verified": False,
            "access_units_verified": False,
            "decoder_pts_selected": False,
            "offline_read_requires_separate_authorization": True,
            "parent_reap_required": True,
            "owner_result_file": "live-owner.json",
            "worker_result_file": "result.json",
            "live_source_qualification": "historical_I1_retained_open_blocking_source_findings0",
            "native_quiescence_verified": False,
        }

        def write(name: str, raw: bytes) -> None:
            if not authorize(identity):
                raise LiveDenied()
            capture(name, raw)
            if not authorize(identity):
                raise LiveDenied()

        def send(closing: bool) -> bool:
            nonlocal close_attempted
            assert codec is not None
            if not authorize(identity):
                raise LiveDenied()
            wire = (
                codec.close_request(request_guid=request_ids[2], sequence=7)
                if closing
                else codec.open(request_guid=request_ids[1], sequence=6)
            ).private_bytes()
            first, second = ct.create_string_buffer(wire), ct.create_string_buffer(1)
            buffers.extend((first, second))
            if not authorize(identity):
                raise LiveDenied()
            if closing:
                close_attempted = True
                result.live_close_attempts += 1
            else:
                result.live_open_attempts += 1
            sent = int(
                native.call("send", handle, first, len(wire), second, 0, None, 0)
            )
            if sent != len(wire):
                result.failure = "send"
                return False
            write("live-close.bin" if closing else "live-open.bin", wire)
            return True

        open_exact = send(False)
        if not open_exact:
            return
        pending = initial
        while time.monotonic() < deadline:
            if not authorize(identity):
                raise LiveDenied()
            chunk = pending or callback.take()
            pending = b""
            if chunk is None:
                time.sleep(0.01)
                continue
            if len(chunk) > (8 << 20) - result.live_received_bytes:
                raise LiveError()
            result.live_received_bytes += len(chunk)
            write("live-receive.bin", chunk)
            for raw, fragmented in mux.receive(chunk):
                envelopes += 1
                if envelopes > 512:
                    raise LiveError()
                if not authorize(identity):
                    raise LiveDenied()
                command = (
                    struct.unpack_from("<I", raw, 12)[0]
                    if len(raw) >= 24 and not fragmented
                    else None
                )
                if command in (2561, 2562, 2563):
                    try:
                        notifications = stream.feed(raw)
                    except CodecError:
                        raise UnsupportedLive() from None
                    if len(notifications) != 1 or not authorize(identity):
                        raise LiveDenied()
                    continue
                items = codec.feed(raw, generation=generation)
                if not authorize(identity):
                    raise LiveDenied()
                for item in items:
                    if isinstance(item, LiveAcknowledgement):
                        result.live_open_ack = item.command == 1281
                        continue
                    if (
                        not isinstance(item, PrivateLiveFrame)
                        or item.identity is not identity
                    ):
                        raise LiveError()
                    payload = item.private_bytes()
                    if (
                        not payload
                        or len(payload) > 1 << 20
                        or result.live_frames_validated >= 64
                        or len(payload) > (4 << 20) - result.live_payload_received
                    ):
                        raise LiveError()
                    result.live_payload_received += len(payload)
                    result.live_frames_validated += 1
                    if not captured and not item.key_frame:
                        result.pre_key_frames += 1
                        if result.live_frames_validated == 64:
                            raise UnsupportedLive()
                        continue
                    summary = item.summary()
                    if captured and (summary.codec, summary.width, summary.height) != (
                        result.live_codec,
                        result.live_width,
                        result.live_height,
                    ):
                        raise UnsupportedLive()
                    ordinal = len(captured)
                    stem = f"live-{ordinal:03d}"
                    extension = item.source_extension.private_bytes()
                    metadata = {
                        "schema": 1,
                        "binding": binding,
                        "ordinal": ordinal,
                        "frame_index": item.frame_index,
                        "key_frame": item.key_frame,
                        "codec": summary.codec,
                        "width": summary.width,
                        "height": summary.height,
                        "encrypted": False,
                        "source_encryption_flag": extension[16]
                        if len(extension) >= 17
                        else None,
                        "format_source": "explicit" if extension else "task_inherited",
                        "source_context": list(item.source_context),
                        "media_route": item.source_header.private_bytes()[2],
                        "wire_task_present": item.source_header.private_bytes()[2] == 2,
                        "wire_task_guid_le": item.source_header.private_bytes()[
                            68:84
                        ].hex()
                        if item.source_header.private_bytes()[2] == 2
                        else None,
                        "task_correlation": "wire_task"
                        if item.source_header.private_bytes()[2] == 2
                        else "exclusive_first_task_after_matching_ack",
                        "payload_file": stem + ".bin",
                        "payload_bytes": len(payload),
                        "payload_sha256": hashlib.sha256(payload).hexdigest(),
                        "capture_admission": {
                            "current": True,
                            "callback_generation": generation,
                            "original_owner_open": True,
                        },
                    }
                    for key in (
                        "source_header",
                        "source_envelope",
                        "source_extension",
                        "source_padding",
                        "source_outer_headers",
                    ):
                        metadata[key + "_hex"] = (
                            getattr(item, key).private_bytes().hex()
                        )
                    for key in (
                        "device_timestamp",
                        "ecm_timestamp",
                        "envelope_timestamp",
                    ):
                        timestamp = getattr(item, key)
                        metadata[key] = {
                            "ticks": timestamp.ticks,
                            "unix_microseconds": timestamp.unix_microseconds,
                        }
                    encoded = json.dumps(metadata, sort_keys=True).encode()
                    if len(encoded) > 65536:
                        raise LiveError()
                    write(stem + ".bin", payload)
                    write(stem + ".json", encoded)
                    captured.append(
                        {
                            "payload_file": stem + ".bin",
                            "metadata_file": stem + ".json",
                            "bytes": len(payload),
                            "sha256": metadata["payload_sha256"],
                            "metadata_bytes": len(encoded),
                            "metadata_sha256": hashlib.sha256(encoded).hexdigest(),
                        }
                    )
                    result.live_frames += 1
                    result.live_bytes += len(payload)
                    result.live_codec, result.live_width, result.live_height = (
                        summary.codec,
                        summary.width,
                        summary.height,
                    )
                    manifest["capture_starts_at_key"] = True
                    if result.live_frames == 4:
                        if not send(True):
                            return
                        if not authorize(identity):
                            raise LiveDenied()
                        result.capture_status = "complete"
                        return
        result.failure = "deadline"
    except UnsupportedLive:
        result.failure = "unsupported"
    except LiveDenied:
        result.failure = "denied"
    except (LiveError, CodecError):
        result.failure = "codec"
    except BaseException:  # noqa: BLE001 -- fixed private interruption boundary
        result.failure = "runtime"
    finally:
        # No retransmission after uncertain Send. A fenced codec may refuse its
        # close_request; native Stop/Destroy/owned-process reap still follow.
        if codec is not None and open_exact and not close_attempted:
            try:
                if result.failure not in ("send", "denied") and current(generation):
                    send(True)
            except BaseException:  # noqa: BLE001 -- original native cleanup remains mandatory
                result.quiescence_verified = False
        if result.capture_status != "complete":
            result.capture_status = "failed"
        if manifest is not None:
            manifest.update(
                {
                    "outcome": "frames_captured_close_sent"
                    if result.capture_status == "complete"
                    else result.capture_status,
                    "terminal_outcome_source": "live-owner.json",
                    "failure": result.failure,
                    "validated_frames": result.live_frames_validated,
                    "pre_key_frames": result.pre_key_frames,
                    "received_bytes": result.live_received_bytes,
                    "payload_received_bytes": result.live_payload_received,
                    "open_attempts": result.live_open_attempts,
                    "open_acknowledged": result.live_open_ack,
                    "close_attempts": result.live_close_attempts,
                    "close_acknowledgement_observed": False,
                    "native_cleanup": "Stop_Destroy_Quit_then_parent_reap_required",
                }
            )
            try:
                write(
                    "live-capture.json", json.dumps(manifest, sort_keys=True).encode()
                )
            except BaseException:  # noqa: BLE001 -- no private manifest on revoked admission
                if result.failure == "none":
                    result.failure = "denied"
                result.capture_status = "failed"
        if codec is not None:
            codec.close()
        mux.buffer.clear()


def serve_live(
    native: Surface,
    handle: int,
    callback: CallbackOwner,
    stream: N9000Stream,
    result: SafeResult,
    buffers: list[object],
    initial: bytes,
    setup: dict[str, Any],
    authority: Any,
) -> None:
    """Credential-free continuation of one first/exclusive original live task."""
    identity = LiveIdentity(
        generation=callback.generation,
        session=bytes.fromhex(setup["session"]),
        channel=bytes.fromhex(setup["channel"]),
        task=bytes.fromhex(setup["task"]),
    )
    codec: LiveCodec | None = None
    mux = LiveEnvelopes()
    authorized = False
    opened = False

    def allowed(given: LiveIdentity) -> bool:
        return (
            authorized
            and given is identity
            and not callback.closed
            and not callback.failed
            and callback.context.value == identity.generation
            and time.monotonic() < authority.deadline
        )

    try:
        if not callback.claim_first_live():
            raise LiveDenied()
        authority.setup(setup)
        authorized = True
        codec = LiveCodec(
            identity=identity,
            peer_capability=setup["peer_version"],
            channel_number=setup["raw_index"] & 255,
            stream=setup["stream"],
            exclusive_first_task=True,
            authorize=allowed,
            max_packet=1 << 20,
            max_session_bytes=1 << 40,
            max_packets=1 << 20,
            max_fragments=64,
        )
        wire = codec.open(
            request_guid=bytes.fromhex(setup["open_request"]), sequence=6
        ).private_bytes()
        first, second = ct.create_string_buffer(wire), ct.create_string_buffer(1)
        buffers.extend((first, second))
        authority.require("send")
        if not allowed(identity):
            raise LiveDenied()
        result.live_open_attempts += 1
        if int(
            native.call("send", handle, first, len(wire), second, 0, None, 0)
        ) != len(wire):
            result.failure = "send"
            return
        opened = True
        next_keepalive = time.monotonic() + LIVE_KEEPALIVE_SECONDS
        # One retained pair for vendor pointer custody, reused by every keepalive.
        keepalive_first, keepalive_second = (
            ct.create_string_buffer(LIVE_KEEPALIVE),
            ct.create_string_buffer(1),
        )
        buffers.extend((keepalive_first, keepalive_second))
        pending = initial
        next_idle = time.monotonic()
        while time.monotonic() < authority.deadline:
            if callback.failed or callback.closed:
                raise LiveDenied()
            if time.monotonic() >= next_idle:
                authority.require("idle")
                next_idle = time.monotonic() + 0.1
            if time.monotonic() >= next_keepalive:
                # At most one per due time; the next is scheduled from this
                # actual Send, so a stalled loop never sends a catch-up burst.
                authority.require("send")
                if not allowed(identity):
                    raise LiveDenied()
                if int(
                    native.call(
                        "send",
                        handle,
                        keepalive_first,
                        len(LIVE_KEEPALIVE),
                        keepalive_second,
                        0,
                        None,
                        0,
                    )
                ) != len(LIVE_KEEPALIVE):
                    result.failure = "send"
                    return
                next_keepalive = time.monotonic() + LIVE_KEEPALIVE_SECONDS
            # External current admission immediately before native queue dequeue.
            authority.require("frame")
            chunk = pending or callback.take_live_batch()
            pending = b""
            if chunk is None:
                time.sleep(0.01)
                continue
            for raw, fragmented in mux.receive(chunk):
                command = (
                    struct.unpack_from("<I", raw, 12)[0]
                    if len(raw) >= 24 and not fragmented
                    else None
                )
                if command in (2561, 2562, 2563):
                    notifications = stream.feed(raw)
                    if len(notifications) != 1:
                        raise UnsupportedLive()
                    continue
                # Both ends independently use the accepted source codec. The
                # typed frame is reconstructed from the original envelope in
                # the parent, never fabricated/pickled from frame attributes.
                try:
                    items = codec.feed(raw, generation=identity.generation)
                except LiveRefused:
                    # Forward the exact correlated envelope: the parent must
                    # independently derive its denial with its own codec.
                    if not allowed(identity):
                        raise LiveDenied() from None
                    authority.envelope(raw)
                    raise
                if not allowed(identity):
                    raise LiveDenied()
                for item in items:
                    if isinstance(item, LiveAcknowledgement):
                        result.live_open_ack = item.command in (1281, 1285)
                    elif (
                        not isinstance(item, PrivateLiveFrame)
                        or item.identity is not identity
                    ):
                        raise LiveError()
                authority.envelope(raw)
    except (AuthorityError, LiveDenied):
        result.failure = "denied"
    except (LiveError, CodecError):
        result.failure = "codec"
    finally:
        # If external authority still exists, at most one source close Send is
        # permitted. Revoke/expiry goes directly to native Stop/Destroy/reap.
        if opened and codec is not None:
            try:
                authority.require("send")
                close = codec.close_request(
                    request_guid=uuid.uuid4().bytes_le, sequence=7
                ).private_bytes()
                first, second = (
                    ct.create_string_buffer(close),
                    ct.create_string_buffer(1),
                )
                buffers.extend((first, second))
                authority.require("send")
                if not allowed(identity):
                    raise LiveDenied()
                result.live_close_attempts += 1
                native.call("send", handle, first, len(close), second, 0, None, 0)
            except BaseException:  # noqa: BLE001 -- original owner still performs Stop/Destroy/reap
                result.quiescence_verified = False
        authorized = False
        if codec is not None:
            codec.close()
        mux.buffer.clear()


@dataclass(frozen=True, slots=True)
class _OriginalMuxTerminalPublisher:
    directory: Path
    directory_id: tuple[int, int]
    receipt: Path
    receipt_id: tuple[int, int]
    generation: str

    def __call__(self, raw: bytes) -> bool:
        if type(raw) is not bytes or not 0 < len(raw) <= CAP:
            fail()
        result = parse_result(raw, self.generation)
        if not result.mux_terminal_observed:
            fail()
        check_private_acl(self.directory)
        check_private_acl(self.receipt)
        if (
            identity(self.directory, directory=True) != self.directory_id
            or identity(self.receipt) != self.receipt_id
        ):
            fail()
        with self.receipt.open("r+b") as output:
            info = os.fstat(output.fileno())
            if (info.st_dev, info.st_ino) != self.receipt_id:
                fail()
            if output.write(raw) != len(raw):
                fail()
            output.truncate(len(raw))
            output.flush()
        if (
            identity(self.directory, directory=True) != self.directory_id
            or read_original(self.receipt, self.receipt_id, CAP) != raw
        ):
            fail()
        return True


class NativeMuxWorker(RemoteAuthority):
    """Original bootstrap authority, then one raw mux dispatcher on the same pipe."""

    def __init__(
        self,
        connection: Any,
        generation: str,
        deadline: float,
        *,
        callback_generation: int,
    ) -> None:
        super().__init__(connection, generation, deadline)
        self.callback_generation = callback_generation
        self.dispatch: Any = None
        self._serve_result: SafeResult | None = None
        self._original_callback: CallbackOwner | None = None
        self._terminal_publisher: _OriginalMuxTerminalPublisher | None = None
        self._terminal_published = False
        self.buffers: list[object] = []
        RETAINED.append(self.buffers)

    def serve(
        self,
        native: Surface,
        handle: int,
        callback: CallbackOwner,
        setup: dict[str, Any],
        *,
        result: SafeResult | None = None,
    ) -> None:
        from .local_live_mux_ipc import MuxRemoteAuthority

        epoch = callback._mux_epoch
        if epoch is None:
            raise AuthorityError()

        def send(wire: bytes) -> int:
            if (
                callback.closed
                or callback.failed
                or self.dispatch.closed
                or time.monotonic() >= self.dispatch.deadline
            ):
                raise AuthorityError()
            first, second = ct.create_string_buffer(wire), ct.create_string_buffer(1)
            self.buffers.extend((first, second))
            if (
                callback.closed
                or callback.failed
                or time.monotonic() >= self.dispatch.deadline
            ):
                raise AuthorityError()
            sent = int(
                native.call("send", handle, first, len(wire), second, 0, None, 0)
            )
            if (
                callback.closed
                or callback.failed
                or time.monotonic() >= self.dispatch.deadline
            ):
                raise AuthorityError()
            return sent

        channels = {
            bytes.fromhex(row["guid"]): row["raw_index"] & 255
            for row in setup["channels"]
        }
        keepalive_first, keepalive_second = (
            ct.create_string_buffer(LIVE_KEEPALIVE),
            ct.create_string_buffer(1),
        )
        self.buffers.extend((keepalive_first, keepalive_second))

        def heartbeat() -> None:
            if (
                callback.closed
                or callback.failed
                or self.dispatch.closed
                or time.monotonic() >= self.dispatch.deadline
            ):
                raise AuthorityError()
            sent = int(
                native.call(
                    "send",
                    handle,
                    keepalive_first,
                    len(LIVE_KEEPALIVE),
                    keepalive_second,
                    0,
                    None,
                    0,
                )
            )
            if (
                sent != len(LIVE_KEEPALIVE)
                or callback.closed
                or callback.failed
                or time.monotonic() >= self.dispatch.deadline
            ):
                raise AuthorityError()

        self.dispatch = MuxRemoteAuthority(
            epoch=epoch,
            callback=callback,
            deadline_monotonic=self.deadline,
            peer_capability=setup["peer_capability"],
            native_send=send,
            native_heartbeat=heartbeat,
            native_slot_allowed=lambda slot, number: (
                slot.epoch == epoch and channels.get(slot.channel) == number
            ),
        )
        try:
            while not callback.closed and not callback.failed:
                if not self.dispatch.serve_once(self.connection):
                    break
        finally:
            terminal_result = result if result is not None else self._serve_result
            if terminal_result is not None:
                self.capture_terminal(terminal_result, callback)
            self.dispatch.close()

    def capture_terminal(self, result: SafeResult, callback: CallbackOwner) -> None:
        from .local_live_diagnostics import (
            NativeMuxTerminalRecord,
            validate_mux_terminal_record,
        )

        if (
            result.mux_terminal_observed
            or result is not self._serve_result
            or callback is not self._original_callback
            or result.generation != self.generation
            or callback.generation != self.callback_generation
            or callback._mux_epoch is not None
            and callback._mux_epoch.generation != self.callback_generation
            or self.dispatch is not None
            and self.dispatch.epoch is not callback._mux_epoch
        ):
            return
        try:
            # No new callback lock, native call, wait or borrowed-pointer access.
            # Fields are a non-atomic sample. A concurrent callback may already
            # be completing; counters do not prove a particular terminal cause.
            record = NativeMuxTerminalRecord(
                callback._mux_epoch is not None,
                callback.failed,
                callback.closed,
                (
                    len(callback._mux_chunks)
                    if callback._mux_epoch is not None
                    else len(callback.chunks.queue)
                ),
                callback.used,
                callback._mux_ordinal,
                callback.capacity,
            )
            validate_mux_terminal_record(record)
            result.mux_epoch_bound = record.epoch_bound
            result.mux_callback_failed = record.failed
            result.mux_callback_closed = record.closed
            result.mux_queued_chunks = record.queued_chunks
            result.mux_queued_bytes = record.queued_bytes
            result.mux_ingress_ordinal = record.ingress_ordinal
            result.mux_capacity_bytes = record.capacity_bytes
            result.mux_terminal_observed = True
            publisher = self._terminal_publisher
            if type(publisher) is _OriginalMuxTerminalPublisher:
                self._terminal_published = publisher(result.to_json()) is True
        except BaseException:  # noqa: BLE001,S110 -- diagnostics cannot alter native outcome
            pass

    def close(self) -> None:
        if self.dispatch is not None:
            self.dispatch.close()
        super().close()


def drive(
    native: Surface,
    request: PrivateRequest,
    generation: str,
    deadline: float,
    capture: Callable[[str, bytes], None],
    *,
    source_provenance: dict[str, Any] | None = None,
    service_authority: RemoteAuthority | None = None,
    discard_credentials: Callable[[], None] | None = None,
) -> SafeResult:
    from .local_live_ipc import LiveRemoteAuthority

    live_service = isinstance(service_authority, LiveRemoteAuthority)
    mux_service = isinstance(service_authority, NativeMuxWorker)
    result = SafeResult(generation, stage="load", loaded=True)
    if mux_service:
        assert isinstance(service_authority, NativeMuxWorker)
        service_authority._serve_result = result
    handle = 0
    initialized = False
    callback: CallbackOwner | None = None
    handshake: LoginHandshake | None = None
    stream: N9000Stream | None = None
    inventory: InventorySession | None = None
    retained_login: LoginResult | None = None
    group_shape = "unavailable"
    framing = OrdinaryFrames()
    buffers: list[object] = []
    RETAINED.append(buffers)
    try:
        if service_authority is not None:
            if request.mode != ("live" if live_service or mux_service else "inventory"):
                raise AuthorityError()
            service_authority.require("connect")
        if request.mode == "load":
            result.stage = "complete"
            return result
        result.stage = "initialize"
        initialized = bool(native.call("initial", 0, 0, None, 0))
        result.initialized = initialized
        if not initialized:
            result.native_error = int(native.call("last_error")) & 0xFFFFFFFF
            result.failure = "runtime"
            return result
        if request.mode == "initialize":
            result.stage = "complete"
            return result
        host, port = select_trusted_nat2(request.country)
        native.call("config", None, 0, False, host, port)
        result.stage = "connect"
        serial_bytes = request.serial.encode("ascii")
        if service_authority is not None:
            service_authority.require("connect")
        handle = I32(native.call("connect_sn", 0, serial_bytes, 0)).value
        if handle == 0:
            result.failure = "connect"
            return result
        while time.monotonic() < deadline:
            status = I32(0)
            if native.call("connect_result", handle, ct.byref(status), 0):
                if status.value not in (-1, 0, 1):
                    result.failure = "connect"
                    return result
                result.connect_status = status.value
                if status.value == -1:
                    result.failure = "connect"
                    return result
                if status.value == 1 and native.call("connected", handle):
                    result.transport = True
                    break
            time.sleep(0.01)
        if not result.transport:
            result.failure = "deadline"
            return result
        result.stage = "greeting"
        buffer = ct.create_string_buffer(64)
        buffers.append(buffer)
        count = int(native.call("greeting", handle, buffer, 64, False, 0))
        if count != 64:
            result.failure = "greeting"
            return result
        result.greeting_bytes = 64
        raw = buffer.raw
        greeting = parse_greeting(raw)
        capture("greeting.bin", raw)
        callback = CallbackOwner(
            handle,
            service_authority.callback_generation
            if isinstance(service_authority, NativeMuxWorker)
            else int(generation[:15], 16) + 1,
            capacity=(1 << 20) if request.mode == "live" else 65536,
        )
        if mux_service:
            assert isinstance(service_authority, NativeMuxWorker)
            service_authority._original_callback = callback
        owned_generation = callback.generation
        metadata_opt_in = request.metadata_read_opt_in

        def current(given: int) -> bool:
            # Single serialized drive owner. Callback revocation may only close
            # its first-terminal latch; this supplier never calls native code.
            return (
                metadata_opt_in is True
                and callback is not None
                and given == owned_generation == callback.generation
                and callback.context.value == owned_generation
                and not callback.closed
                and time.monotonic() < deadline
            )

        def inventory_current(given: int) -> bool:
            if not current(given):
                return False
            if service_authority is not None:
                service_authority.require("metadata")
            return current(given)

        if not native.call(
            "register",
            handle,
            ct.byref(callback.observer),
            ct.byref(callback.context),
            0,
            0,
        ):
            result.failure = "callback"
            return result
        if not native.call("start", handle):
            result.failure = "connect"
            return result
        if callback.failed:
            result.failure = "callback"
            return result
        if request.mode == "connect":
            if not callback.seal_success(result):
                result.failure = "callback"
            return result
        result.stage = "handshake"
        handshake = LoginHandshake(
            generation=callback.generation,
            sequence=1,
            credentials=Credentials(request.username, request.password),
        )
        stream = N9000Stream(greeting=greeting)
        wire = handshake.build_request(greeting).data
        if not 0 < len(wire) <= 65536:
            fail()
        first, second = ct.create_string_buffer(wire), ct.create_string_buffer(1)
        buffers.extend((first, second))
        if request.mode in ("inventory", "live") and not current(owned_generation):
            result.failure = "deadline" if time.monotonic() >= deadline else "callback"
            return result
        if service_authority is not None:
            service_authority.require("send")
            if not current(owned_generation):
                raise AuthorityError()
        result.send_count = int(
            native.call("send", handle, first, len(wire), second, 0, None, 0)
        )
        if result.send_count <= 0:
            result.failure = "send"
            return result
        if request.mode in ("inventory", "live") and result.send_count != len(wire):
            result.failure = "send"
            return result

        queries = (
            ReadQuery.BASIC,
            ReadQuery.CHANNELS,
            ReadQuery.USER,
            ReadQuery.PERMISSIONS,
        )

        def send_query() -> bool:
            assert inventory is not None and callback is not None
            if not current(owned_generation):
                raise CodecError("private inventory admission expired")
            query_wire = inventory.build_query(
                queries[result.inventory_queries_sent],
                sequence=result.inventory_queries_sent + 2,
                generation=owned_generation,
            ).data
            if not current(owned_generation):
                raise CodecError("private inventory admission expired")
            first_query = ct.create_string_buffer(query_wire)
            second_query = ct.create_string_buffer(1)
            buffers.extend((first_query, second_query))
            # Revalidate after all buffer allocation/retention, immediately
            # before counting or invoking Send; no native call holds the lock.
            if not current(owned_generation):
                raise CodecError("private inventory admission expired")
            if service_authority is not None:
                service_authority.require("send")
                if not current(owned_generation):
                    raise AuthorityError()
            result.inventory_queries_sent += 1  # native invocation attempts, no retries
            sent = int(
                native.call(
                    "send",
                    handle,
                    first_query,
                    len(query_wire),
                    second_query,
                    0,
                    None,
                    0,
                )
            )
            if sent != len(query_wire):
                result.failure = "send"
                return False
            return True

        while time.monotonic() < deadline:
            if callback.failed:
                result.failure = "callback"
                return result
            chunk = callback.take()
            if chunk is None:
                time.sleep(0.01)
                continue
            if len(chunk) > 65536 - result.received_bytes:
                callback.mark_failed()
                result.failure = "callback"
                return result
            result.received_bytes += len(chunk)
            capture("reply.bin", chunk)
            if request.mode in ("inventory", "live"):
                framing.feed(chunk)
                while (raw_frame := framing.take()) is not None:
                    if not current(owned_generation):
                        result.failure = (
                            "deadline" if time.monotonic() >= deadline else "callback"
                        )
                        return result
                    if inventory is None:
                        packets = stream.feed(raw_frame)
                        if len(packets) != 1:
                            raise CodecError("invalid private login envelope")
                        accepted = handshake.accept_reply(
                            packets[0], generation=owned_generation
                        )
                        if accepted is None:
                            continue
                        # Login acceptance is historical evidence, not terminal
                        # callback success or a metadata authority grant.
                        result.reply_accepted = True
                        result.proof_verified = accepted.proof_verified
                        result.key_extracted = accepted.key_extracted
                        retained_login = accepted
                        result.stage = "inventory"
                        inventory = InventorySession(
                            login=accepted,
                            generation=owned_generation,
                            expected_serial=request.serial,
                            username=request.username,
                            security=greeting.security,
                            peer_version=accepted.peer_version,
                            read_authority=inventory_current,
                        )
                        if not send_query():
                            return result
                        continue
                    command = struct.unpack_from("<I", raw_frame, 12)[0]
                    if command in (2561, 2562, 2563):
                        # Accepted greeting-bound codec validates every flat
                        # header/length. Diagnostic continuation suppresses all
                        # source application effects; the same query stays pending.
                        try:
                            notifications = stream.feed(raw_frame)
                        except CodecError:
                            raise UnsupportedBranch(
                                "inventory_notification_shape"
                            ) from None
                        if (
                            len(notifications) != 1
                            or notifications[0].command != command
                            or inventory.state != "awaiting_reply"
                        ):
                            raise UnsupportedBranch("inventory_notification_context")
                        if not current(owned_generation):
                            raise CodecError("private inventory admission expired")
                        continue
                    if command & 0x0FFFFFFF != 2331:
                        raise UnsupportedBranch("inventory_unsolicited_packet")
                    evidence = inventory.accept_reply(
                        raw_frame, generation=owned_generation
                    )
                    result.inventory_replies += 1
                    if result.inventory_replies == 3:
                        if evidence.user is None:
                            raise UnsupportedBranch("inventory_user_unavailable")
                        group_shape = user_group_provenance(
                            raw_frame, evidence.user.auth_group_id
                        )
                    no_group = result.inventory_replies == 3 and group_shape in (
                        "missing",
                        "empty",
                    )
                    if result.inventory_replies == 4 or no_group:
                        if not (
                            evidence.serial_matched
                            and evidence.channels_complete
                            and evidence.user is not None
                            and (no_group or evidence.permissions_complete)
                        ):
                            raise UnsupportedBranch("inventory_incomplete")
                        if request.mode == "live":
                            if not callback.seal_success(
                                result, inventory=evidence, guard=current, seal=False
                            ):
                                result.failure = "callback"
                                return result
                            assert retained_login is not None
                            remaining = bytes(framing.buffer)
                            result.received_bytes -= len(remaining)
                            framing.close()
                            if mux_service:
                                assert isinstance(service_authority, NativeMuxWorker)
                                if (
                                    remaining
                                    or callback.used
                                    or callback.failed
                                    or inventory._login is not retained_login
                                    or evidence.generation != owned_generation
                                    or callback.handle != (handle & 0xFFFFFFFF)
                                ):
                                    raise AuthorityError()
                                channels = []
                                for mux_channel in evidence.channels:
                                    try:
                                        basis = live_basis(
                                            evidence,
                                            request,
                                            mux_channel.guid,
                                            group_shape,
                                        )
                                    except LiveDenied:
                                        continue
                                    channels.append(
                                        {
                                            "guid": mux_channel.guid.hex(),
                                            "raw_index": mux_channel.raw_index,
                                            "window_index": mux_channel.window_index,
                                            "ordinal": mux_channel.position,
                                            "kind": mux_channel.kind,
                                            "basis": basis,
                                        }
                                    )
                                setup = {
                                    "session": retained_login.session_guid.hex(),
                                    "callback_generation": owned_generation,
                                    "peer_capability": retained_login.peer_version,
                                    "login_accepted": result.reply_accepted,
                                    "same_original_session": inventory._login
                                    is retained_login,
                                    "serial_matched": evidence.serial_matched,
                                    "inventory_session_matched": inventory._login
                                    is retained_login
                                    and evidence.generation == owned_generation,
                                    "channels": channels,
                                }
                                epoch = MuxEpochIdentity(
                                    owned_generation, retained_login.session_guid
                                )
                                callback.bind_mux_epoch(epoch)
                                service_authority.require("publish")
                                service_authority.publish(encode(setup))
                                handshake.close()
                                handshake = None
                                inventory.close()
                                inventory = None
                                retained_login = accepted = None
                                del evidence
                                del request
                                serial_bytes = wire = chunk = raw_frame = b""
                                packets = ()
                                for consumed in buffers:
                                    if isinstance(consumed, ct.Array):
                                        ct.memset(
                                            ct.addressof(consumed),
                                            0,
                                            ct.sizeof(consumed),
                                        )
                                if discard_credentials is not None:
                                    discard_credentials()
                                stream.close()
                                stream = None
                                service_authority.serve(native, handle, callback, setup)
                                return result
                            if live_service:
                                assert isinstance(
                                    service_authority, LiveRemoteAuthority
                                )
                                channel = next(
                                    (
                                        c
                                        for c in evidence.channels
                                        if c.position == request.channel_position
                                    ),
                                    None,
                                )
                                if channel is None:
                                    raise LiveDenied()
                                basis = live_basis(
                                    evidence, request, channel.guid, group_shape
                                )
                                setup = {
                                    "session": retained_login.session_guid.hex(),
                                    "channel": channel.guid.hex(),
                                    "task": uuid.uuid4().bytes_le.hex(),
                                    "open_request": uuid.uuid4().bytes_le.hex(),
                                    "peer_version": retained_login.peer_version,
                                    "callback_generation": owned_generation,
                                    "raw_index": channel.raw_index,
                                    "window_index": channel.window_index,
                                    "ordinal": channel.position,
                                    "stream": request.stream,
                                    "live_basis": basis,
                                    "login_accepted": result.reply_accepted,
                                    "serial_matched": evidence.serial_matched,
                                }
                                # Drop all login/credential objects before the
                                # setup ACK and first live Send. Retain only the
                                # immutable wire session identifiers above.
                                handshake.close()
                                handshake = None
                                inventory.close()
                                inventory = None
                                retained_login = accepted = None
                                del evidence
                                del request
                                serial_bytes = b""
                                wire = b""
                                packets = ()
                                chunk = raw_frame = b""
                                # All login/metadata Sends have corresponding
                                # consumed replies. Keep the original ctypes
                                # allocations pinned for vendor pointer custody
                                # but overwrite their now-consumed contents.
                                for consumed in buffers:
                                    if isinstance(consumed, ct.Array):
                                        ct.memset(
                                            ct.addressof(consumed),
                                            0,
                                            ct.sizeof(consumed),
                                        )
                                if discard_credentials is not None:
                                    discard_credentials()
                                serve_live(
                                    native,
                                    handle,
                                    callback,
                                    stream,
                                    result,
                                    buffers,
                                    remaining,
                                    setup,
                                    service_authority,
                                )
                                return result
                            capture_live(
                                native,
                                handle,
                                request,
                                retained_login,
                                inventory,
                                group_shape,
                                callback,
                                stream,
                                result,
                                deadline,
                                current,
                                buffers,
                                remaining,
                                capture,
                                source_provenance,
                            )
                            if (
                                result.capture_status == "complete"
                                and result.failure == "none"
                                and not callback.seal_success(result, guard=current)
                            ):
                                result.failure, result.capture_status = (
                                    "callback",
                                    "failed",
                                )
                            return result
                        # No unreviewed trailing packet or partial packet is
                        # silently discarded at publication. Complete buffered
                        # heartbeat8 envelopes can be consumed by take().
                        if (
                            framing.take() is not None
                            or framing.buffer
                            or callback.used
                        ):
                            raise UnsupportedBranch("inventory_trailing_data")
                        observation_wire: bytes | None = None
                        if service_authority is not None:
                            if (
                                retained_login is None
                                or inventory._login is not retained_login
                                or evidence.generation != owned_generation
                                or callback.handle != (handle & 0xFFFFFFFF)
                            ):
                                raise AuthorityError()
                            observation_wire = encode(
                                {
                                    "login_accepted": result.reply_accepted,
                                    "same_original_session": True,
                                    "serial_matched": evidence.serial_matched,
                                    "channels_complete": evidence.channels_complete,
                                    "metadata_branch_complete": True,
                                    "permissions_complete": evidence.permissions_complete,
                                    "proof_verified": evidence.proof_verified,
                                    "group_provenance": group_shape,
                                    "channels": [
                                        {
                                            "guid": c.guid.hex(),
                                            "raw_index": c.raw_index,
                                            "window_index": c.window_index,
                                            "ordinal": c.position,
                                            "kind": c.kind,
                                        }
                                        for c in evidence.channels
                                    ],
                                }
                            )
                            service_authority.require("publish")
                        if not callback.seal_success(
                            result, inventory=evidence, guard=current
                        ):
                            result.failure = "callback"
                        elif (
                            service_authority is not None
                            and observation_wire is not None
                        ):
                            service_authority.publish(observation_wire)
                        return result
                    if not send_query():
                        return result
                continue
            for packet in stream.feed(chunk):
                accepted = handshake.accept_reply(
                    packet, generation=callback.generation
                )
                if accepted is None:
                    continue
                if not callback.seal_success(result, accepted):
                    result.failure = "callback"
                return result
        result.failure = "deadline"
        return result
    except AuthorityError:
        result.failure = "denied"
    except (LoginRejected, InventoryRejected) as error:
        result.failure, result.native_error = "rejected", error.code
    except UnsupportedBranch:
        result.failure = "unsupported"
    except CodecError:
        result.failure = "codec"
    except BaseException:  # noqa: BLE001 -- private native exception boundary
        result.failure = "runtime"
    finally:
        if mux_service and callback is not None:
            assert isinstance(service_authority, NativeMuxWorker)
            service_authority.capture_terminal(result, callback)
        if callback is not None:
            callback.closed = True
        if handshake is not None:
            handshake.close()
        if stream is not None:
            stream.close()
        if inventory is not None:
            inventory.close()
        framing.close()
        result.cleanup_attempted = initialized
        # Orderly cleanup is attempted, not a callback join. Parent kills/reaps.
        for name, args in (("stop", (handle,)), ("destroy", (handle,)), ("quit", ())):
            if (name == "quit" and initialized) or (name != "quit" and handle != 0):
                try:
                    native.call(name, *args)
                except BaseException:  # noqa: BLE001 -- cleanup failure stays private
                    result.quiescence_verified = False
    return result


def make_mux_dispatch(
    raw_input: bytes,
    *,
    epoch: MuxEpochIdentity,
    callback: CallbackOwner,
    deadline_monotonic: float,
) -> Any:
    """Inert mux dispatch after an original's validated login/epoch binding.

    Task 7 owns the native drive branch. This constructor does not load an SDK,
    claim login proof, or weaken the default exclusive service entry point.
    """
    from .local_live_mux_ipc import (
        MuxIpcError,
        MuxRemoteAuthority,
        parse_mux_worker_input,
    )

    credentials, generation, ttl = parse_mux_worker_input(raw_input)
    del credentials
    if (
        type(epoch) is not MuxEpochIdentity
        or type(callback) is not CallbackOwner
        or callback._mux_epoch != epoch
        or callback.generation != generation
        or epoch.generation != generation
        or callback.closed
        or callback.failed
        or type(deadline_monotonic) not in (int, float)
        or not math.isfinite(deadline_monotonic)
        or not 0 < deadline_monotonic - time.monotonic() <= ttl / 1000
    ):
        raise MuxIpcError()
    return MuxRemoteAuthority(
        epoch=epoch, callback=callback, deadline_monotonic=deadline_monotonic
    )


def main() -> int:
    result: SafeResult | None = None
    receipt: Path | None = None
    receipt_id: tuple[int, int] | None = None
    service: RemoteAuthority | None = None
    try:
        packet = json_object(sys.stdin.buffer.read(CAP + 1))
        live_packet = "live_selection" in packet
        mux_packet = packet.get("mode") == "mux"
        mux_credentials = None
        callback_generation = 0
        if mux_packet:
            from .local_live_mux_ipc import parse_mux_worker_input

            if (
                set(packet)
                != {
                    "version",
                    "mode",
                    "config",
                    "generation",
                    "generation_identity",
                    "receipt_identity",
                    "job_admitted",
                    "deadline",
                    "service_authority_handle",
                    "mux_input",
                }
                or type(packet["version"]) is not int
                or packet["version"] != 1
            ):
                fail()
            mux_credentials, callback_generation, _ = parse_mux_worker_input(
                json.dumps(packet["mux_input"], separators=(",", ":")).encode()
            )
        elif set(packet) != {
            "config",
            "request",
            "generation",
            "receipt_identity",
            "generation_identity",
            "deadline",
            "job_admitted",
            "service_authority_handle",
        } | ({"live_selection"} if live_packet else set()):
            fail()
        # Defense in depth if this private module is invoked without the
        # supervisor bootstrap. No vendor code is loaded before this check.
        inside = ct.c_int()
        kernel = ct.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ct.c_void_p
        kernel.IsProcessInJob.argtypes = [
            ct.c_void_p,
            ct.c_void_p,
            ct.POINTER(ct.c_int),
        ]
        kernel.IsProcessInJob.restype = ct.c_int
        if (
            packet["job_admitted"] is not True
            or not kernel.IsProcessInJob(
                kernel.GetCurrentProcess(), None, ct.byref(inside)
            )
            or not inside.value
        ):
            fail()
        generation = packet["generation"]
        if (
            type(generation) is not str
            or re.fullmatch(r"[a-f0-9]{32}", generation) is None
        ):
            fail()
        values = packet["config"]
        config = ProviderConfig(
            Path(values["bundle"]),
            Path(values["staging"]),
            Path(values["review_receipt"]),
            values["deadline_seconds"],
            Path(values["runtime_receipt"]) if values.get("runtime_receipt") else None,
        )
        deadline = packet["deadline"]
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or not 0 < deadline - time.monotonic() <= config.deadline_seconds
        ):
            fail()
        if packet["service_authority_handle"] is not None:
            from .local_live_ipc import LiveRemoteAuthority

            authority_type = LiveRemoteAuthority if live_packet else RemoteAuthority
            service = authority_type.from_handle(
                packet["service_authority_handle"], generation, deadline
            )
            if mux_packet:
                service = NativeMuxWorker(
                    service.connection,
                    generation,
                    deadline,
                    callback_generation=callback_generation,
                )
            service.require("prepare")
        manifest = verify_review(config)
        overrides = runtime_override(config)
        check_private_acl(config.review_receipt)
        request: PrivateRequest | None
        if mux_packet:
            assert mux_credentials is not None
            request = PrivateRequest(
                "live",
                mux_credentials.country,
                mux_credentials.serial,
                mux_credentials.username,
                mux_credentials.password,
                metadata_read_opt_in=True,
                live_read_opt_in=True,
                store_ref="SERVICE",
                channel_position=1,
                stream=2,
            )
            mux_credentials = None
            if service is None:
                fail()
        else:
            request = PrivateRequest(**packet["request"])
        assert request is not None
        if service is not None and request.mode != (
            "live" if live_packet or mux_packet else "inventory"
        ):
            fail()
        if live_packet:
            selection = packet["live_selection"]
            if (
                type(selection) is not dict
                or set(selection)
                != {"channel_guid", "raw_index", "window_index", "ordinal", "stream"}
                or type(selection["stream"]) is not int
                or selection["stream"] != request.stream
            ):
                fail()
        check_private_acl(config.staging)
        if (
            config.staging.name != generation
            or config.staging.is_relative_to(Path(__file__).resolve().parents[4])
            or list(identity(config.staging, directory=True))
            != packet["generation_identity"]
        ):
            fail()
        receipt = config.staging / "result.json"
        receipt_id = identity(receipt)
        if list(receipt_id) != packet["receipt_identity"] or receipt.stat().st_size:
            fail()
        check_private_acl(receipt)
        if isinstance(service, NativeMuxWorker):
            service._terminal_publisher = _OriginalMuxTerminalPublisher(
                config.staging,
                identity(config.staging, directory=True),
                receipt,
                receipt_id,
                generation,
            )
        captures: dict[str, tuple[int, int]] = {}

        def capture(name: str, raw: bytes) -> None:
            if service is not None:
                return  # service facts use private IPC; no diagnostic body files
            bounds = {
                "greeting.bin": 64,
                "reply.bin": 65536,
                "live-receive.bin": 8 << 20,
                "live-capture.json": 65536,
                "live-open.bin": 1024,
                "live-close.bin": 1024,
            }
            for index in range(4):
                bounds[f"live-{index:03d}.bin"] = 1 << 20
                bounds[f"live-{index:03d}.json"] = 65536
            if name not in bounds:
                fail()
            path = config.staging / name
            if name not in captures:
                with path.open("xb"):
                    pass
                protect_created_acl(path)
                captures[name] = identity(path)
            if (
                identity(path) != captures[name]
                or path.stat().st_size + len(raw) > bounds[name]
            ):
                fail()
            with path.open("ab") as output:
                info = os.fstat(output.fileno())
                if (info.st_dev, info.st_ino) != captures[name]:
                    fail()
                output.write(raw)
            if identity(path) != captures[name]:
                fail()

        result = SafeResult(generation, failure="linkage")
        native = NativeSurface(config.bundle, manifest, overrides)
        RETAINED.append(native)
        provenance = {
            "source_review": file_hash(config.review_receipt),
            "receipts": {path: file_hash(ROOT / path) for path in ACCEPTED_HASHES},
            "files": {path: file_hash(ROOT / path) for path in OWNED},
        }

        def discard_credentials() -> None:
            nonlocal request
            request = None
            packet.pop("request", None)
            packet.pop("mux_input", None)

        assert request is not None
        result = drive(
            native,
            request,
            generation,
            deadline,
            capture,
            source_provenance=provenance,
            service_authority=service,
            discard_credentials=discard_credentials,
        )
        result.runtime_substitutions = native.runtime_substitutions
    except ProviderError:
        if result is not None:
            result.failure = "custody"
    except OSError as error:
        if result is not None:
            result.failure = "linkage"
            code = getattr(error, "winerror", 0)
            result.native_error = (
                code if type(code) is int and 0 <= code <= 0xFFFFFFFF else 0
            )
    except Exception:  # noqa: BLE001 -- private loader exception boundary
        # No native/loader exception details are printed or placed in results.
        if result is not None:
            result.failure = "linkage"
    finally:
        if service is not None:
            service.close()
    if result is not None and receipt is not None and receipt_id is not None:
        try:
            if identity(receipt) != receipt_id:
                fail()
            with receipt.open("r+b") as output:
                info = os.fstat(output.fileno())
                if (info.st_dev, info.st_ino) != receipt_id:
                    fail()
                raw_result = result.to_json()
                if len(raw_result) > CAP or output.write(raw_result) != len(raw_result):
                    fail()
                output.truncate(len(raw_result))
                output.flush()
            if identity(receipt) != receipt_id:
                fail()
        except Exception:  # noqa: BLE001 -- private receipt exception boundary
            return 1
        # Keep custom slots, buffers and DLLs alive until original parent kills.
        while True:
            time.sleep(0.25)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
