"""Accepted ordinary controls through actual retained original ingress."""

import struct

import pytest
from test_local_mux_callback import invoke, key
from test_shared_ingress_consumer import consumer_rig as original_consumer_rig
from test_shared_ingress_consumer import wait_until
from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

consumer_rig = original_consumer_rig


@pytest.mark.parametrize("command,length", [(2561, 92), (2562, 40), (2563, 36)])
def test_parked_original_control_and_media_drain_without_credit_or_terminal(
    command, length, consumer_rig
):
    master, parent, _, callback, slot = consumer_rig
    sink = NativeFirstKeySink()
    master.provider.first_key_debug = sink
    inner = struct.pack("<HBBIII", 5, 0, 0, command, 0, length) + bytes(length)
    raw = struct.pack("<Ii", 825307441, len(inner)) + inner
    master._start_ingress_consumer()
    assert invoke(callback, raw + key(slot)) > 0
    wait_until(lambda: callback.used == 0 and not parent._raw)
    assert not parent.failed and not callback.failed and not master._closed
    assert parent.credit_usage(slot) == (0, 0)
    assert sink.drain() == ()
