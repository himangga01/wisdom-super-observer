"""Fixed numeric facts for the existing mux packet rejection; offline only."""

import json
import struct
from itertools import pairwise
from pathlib import Path

import pytest
from wso_core.tvt import local_live_mux
from wso_core.tvt.local_live import LiveError, UnsupportedLive
from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
from wso_core.tvt.local_media_mux_types import (
    IngressChunk,
    IngressSpan,
    MuxEpochIdentity,
)
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.contract.test_local_media_core_state_debug import helper_module
from tests.tvt_parity.test_local_media_mux_service import attached_pair

ROOT = Path(__file__).resolve().parents[2]


def codec():
    return local_live_mux.MultiplexLiveCodec(
        epoch=MuxEpochIdentity(7, bytes([1]) * 16),
        peer_capability=6,
        authorize=lambda _: True,
    )


def packet(command, route):
    inner = struct.pack("<HBBIII", 0, route, 0, command, 0, 0)
    return struct.pack("<Ii", 825307441, len(inner)) + inner


@pytest.mark.parametrize(
    "command,route", [(2561, 0), (2562, 2), (2563, 255), (0, 0), (0xFFFFFFFF, 255)]
)
def test_real_unknown_packet_still_rejects_but_logs_numeric_pair_before_close(
    command, route
):
    helper = helper_module()
    coordinator, admission, _, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    parser, written, original = codec(), [], coordinator._close_viewer
    sink = helper.BoundedCoreStateDiagnostics(written.append)

    def read(**kwargs):
        try:
            return parser.feed(
                IngressChunk(packet(command, route), IngressSpan(1, 1)), generation=7
            )
        except UnsupportedLive:
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502) from None

    def close(*args, **kwargs):
        row = json.loads(sink._queue[0])
        assert (row.get("wire_command"), row.get("wire_route")) == (command, route), (
            "original rejected command/route must be captured before cleanup"
        )
        return original(*args, **kwargs)

    handle.read_frames, coordinator._close_viewer = read, close
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure):
        executor.read_mux_frames(
            first.id, max_frames=1, max_bytes=1024, deadline_ms=1000
        )
    assert parser._closed and handle.stopped
    sink.close()
    row = json.loads(written[0])
    assert row["event"] == "VIEWER_READ_EXCEPTION" and row["chain_count"] == 2
    assert "wire_command" not in json.loads(written[1])
    for change in ({"wire_command": True}, {"wire_route": 256}, {"wire_command": -1}):
        with pytest.raises(ValueError):
            helper.checked_record(row | change)
    with pytest.raises(ValueError):
        helper.checked_record(
            {key: value for key, value in row.items() if key != "wire_route"}
        )


def test_only_existing_parse_rejection_has_typed_facts_other_rejections_preserved():
    parser = codec()
    with pytest.raises(UnsupportedLive) as failure:
        parser._parse(
            memoryview(struct.pack("<HBBIII", 0, 1, 0, 65537, 0, 0)),
            memoryview(b""),
            IngressSpan(1, 1),
        )
    assert type(failure.value) is getattr(local_live_mux, "UnsupportedMuxPacket", None)
    assert (failure.value.command, failure.value.route) == (65537, 1)
    parser = codec()
    with pytest.raises(UnsupportedLive) as earlier:
        parser.feed(IngressChunk(packet(65537, 1), IngressSpan(1, 1)), generation=7)
    assert type(earlier.value) is UnsupportedLive and parser._closed
    with pytest.raises(LiveError):
        codec()._parse(memoryview(b"short"), memoryview(b""), IngressSpan(1, 1))


@pytest.mark.parametrize(
    "command,route",
    [(True, 0), (-1, 0), (2**32, 0), (0, True), (0, -1), (0, 256), ("private", 0)],
)
def test_invalid_diagnostic_constructor_values_are_rejected(command, route):
    error_type = getattr(local_live_mux, "UnsupportedMuxPacket", None)
    assert error_type is not None
    with pytest.raises(UnsupportedLive):
        error_type(command, route)


def test_projection_omits_forged_types_malformed_attrs_and_out_of_chain_facts():
    helper = helper_module()
    error_type = getattr(local_live_mux, "UnsupportedMuxPacket", None)
    assert error_type is not None

    class Forged(error_type):
        pass

    errors = [Forged(2561, 0), error_type(2561, 0), error_type(2561, 0)]
    errors[1].command = "private"
    del errors[2].route
    for error in errors:
        projected, _ = helper.project_read_failure(error, root=ROOT)
        assert "wire_command" not in projected and "wire_route" not in projected
    typed = error_type(2561, 0)
    typed.__context__ = typed
    projection, _ = helper.project_read_failure(typed, root=ROOT)
    assert projection["truncated"] is True and projection["wire_command"] == 2561
    assert "wire_command" not in helper.project_heartbeat_failure(typed, root=ROOT)
    outer = [RuntimeError("private") for _ in range(4)] + [typed]
    for current, following in pairwise(outer):
        current.__cause__ = following
    projection, _ = helper.project_read_failure(outer[0], root=ROOT)
    assert projection["truncated"] is True and "wire_command" not in projection
