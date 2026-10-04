"""Owned-process tests: synthetic bytes only; never camera acceptance."""

import datetime
import hashlib
import io
import json
import os
import pickle
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from wso_core.tvt.windows_decode import (
    DecodeBinding,
    DecodeDenied,
    DecodeError,
    DecodeLimits,
    ElementaryPacket,
    WindowsDecoder,
)

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / ".superpowers/runtime/windows-media-decode/venv/Scripts/python.exe"
DECODER_EXECUTABLE = MEDIA


def require_native():
    selected = os.environ.get("WSO_WINDOWS_DECODE_NATIVE") == "1"
    if not selected:
        pytest.skip(
            "Windows native proof requires explicit WSO_WINDOWS_DECODE_NATIVE=1 selection"
        )
    available = (
        os.name == "nt"
        and MEDIA.is_file()
        and os.environ.get("WSO_WINDOWS_DECODE_DISABLE_NATIVE_RUNTIME") != "1"
    )
    if selected and not available:
        pytest.fail(
            "Selected Windows decoder proof requires Windows and the isolated av 19.0.1 runtime",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def portable_contract_runtime(request, monkeypatch):
    # Native acceptance is an explicit fixture admission, never mocked here.
    if (
        "synthetic" in request.fixturenames
        or request.node.name == "test_bad_bitstream_is_sanitized_fenced_and_reaped"
    ):
        require_native()
        return
    import wso_core.tvt.windows_decode as module

    # Portable contract tests use inert standard Python children and simulate
    # only Windows constructor/Job admission, not PyAV/native acceptance.
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(module, "_job", lambda *args: None)
    monkeypatch.setitem(globals(), "DECODER_EXECUTABLE", Path(sys._base_executable))


def binding():
    return DecodeBinding(
        generation=7, owner=b"O" * 16, channel=b"C" * 16, task=b"T" * 16
    )


def packet(data=b"\x00\x00\x00\x01invalid", **kw):
    args = {
        "data": data,
        "binding": binding(),
        "codec": "h264",
        "format": "annexb",
        "generation": 7,
        "width": 64,
        "height": 48,
        "timestamp_us": 1000000,
        "ordinal": 0,
    }
    args.update(kw)
    return ElementaryPacket(**args)


def decoder(**kw):
    args = {
        "binding": binding(),
        "authorize": lambda context: True,
        "executable": DECODER_EXECUTABLE,
    }
    args.update(kw)
    return WindowsDecoder(**args)


def test_module_implements_owned_decode_boundary():
    # Removing generation admission would permit stale packets to spawn native work.
    with decoder() as d:
        with pytest.raises(DecodeError):
            d.decode(packet(generation=6))
        assert d.process is None


@pytest.mark.parametrize(
    "changes",
    [
        {"codec": "vp9"},
        {"format": "avcc"},
        {"format": "mp4"},
        {"encrypted": True},
        {"width": 99999},
        {"data": b"no-annexb"},
    ],
)
def test_unsupported_or_overquota_input_never_spawns(changes):
    with decoder() as d:
        with pytest.raises(DecodeError):
            d.decode(packet(**changes))
        assert d.process is None


def test_denied_and_authority_exception_are_fixed_and_fenced():
    for auth in (
        lambda _: False,
        lambda _: (_ for _ in ()).throw(ValueError("SECRET")),
    ):
        with decoder(authorize=auth) as d:
            with pytest.raises(DecodeDenied) as error:
                d.decode(packet())
            assert "SECRET" not in str(error.value)
            assert error.value.__cause__ is None
            assert d.process is None


@pytest.mark.parametrize("field", ["owner", "channel", "task"])
def test_foreign_packet_binding_cannot_spawn(field):
    values = {
        "generation": 7,
        "owner": b"O" * 16,
        "channel": b"C" * 16,
        "task": b"T" * 16,
    }
    values[field] = b"X" * 16
    foreign = DecodeBinding(**values)
    with decoder() as d:
        with pytest.raises(DecodeError):
            d.decode(packet(binding=foreign))
        assert d.process is None


def test_close_from_authority_cannot_publish_or_spawn():
    d = None

    def auth(_):
        d.close()
        return True

    d = decoder(authorize=auth)
    with pytest.raises(DecodeDenied):
        d.decode(packet())
    assert d.process is None


def test_private_values_refuse_repr_and_pickle():
    for obj in (binding(), packet(data=b"\x00\x00\x00\x01SECRET")):
        assert "SECRET" not in repr(obj)
        with pytest.raises(TypeError):
            pickle.dumps(obj)


def test_unselected_native_admission_skips_without_runtime_lookup(monkeypatch):
    class Unavailable:
        def is_file(self):
            raise AssertionError("private runtime must not be read")

    monkeypatch.setitem(globals(), "MEDIA", Unavailable())
    monkeypatch.setenv("WSO_WINDOWS_DECODE_NATIVE", "0")
    with pytest.raises(pytest.skip.Exception):
        require_native()


def test_selected_native_admission_fails_missing_runtime(monkeypatch):
    monkeypatch.setenv("WSO_WINDOWS_DECODE_NATIVE", "1")
    monkeypatch.setitem(globals(), "MEDIA", SimpleNamespace(is_file=lambda: False))
    with pytest.raises(pytest.fail.Exception, match="requires Windows"):
        require_native()


def test_selected_native_admission_fails_nonwindows(monkeypatch):
    monkeypatch.setitem(
        globals(),
        "os",
        SimpleNamespace(name="posix", environ={"WSO_WINDOWS_DECODE_NATIVE": "1"}),
    )
    with pytest.raises(pytest.fail.Exception, match="requires Windows"):
        require_native()


@pytest.fixture(scope="module", params=["h264", "hevc"])
def synthetic(request, tmp_path_factory):
    require_native()
    # Independent RGB oracle: four known colors and timestamps, reordered B frames.
    out = tmp_path_factory.mktemp("inert") / "fixture.bin"
    script = """
import av, struct, sys
from fractions import Fraction
c=av.CodecContext.create({'h264':'libx264','hevc':'libx265'}[sys.argv[1]],'w')
c.width=64; c.height=48; c.pix_fmt='yuv420p'; c.time_base=Fraction(1,1000000)
c.framerate=Fraction(25,1); c.thread_count=1
c.options={'preset':'ultrafast','bf':'2','g':'20'}
if sys.argv[1]=='hevc': c.options['x265-params']='pools=none:frame-threads=1:log-level=error:bframes=2'
items=[]
for i,color in enumerate([(255,0,0),(0,255,0),(0,0,255),(255,255,255)]):
 f=av.VideoFrame(64,48,'rgb24'); f.planes[0].update(bytes(color)*64*48)
 f=f.reformat(format='yuv420p'); f.pts=1000000+i*40000; f.time_base=c.time_base
 items.extend(c.encode(f))
items.extend(c.encode(None))
with open(sys.argv[2],'wb') as f:
 for p in items:
  b=bytes(p); f.write(struct.pack('!qI',p.pts,len(b))+b)
print(av.__version__, av.library_versions)
"""
    argv = [str(MEDIA), "-I", "-c", script, request.param, str(out)]
    receipt = {
        "argv": argv,
        "cwd": str(ROOT),
        "executable_sha256": hashlib.sha256(MEDIA.read_bytes()).hexdigest(),
        "started_utc": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    (out.parent / "encoder-before.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    result = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    (out.parent / "encoder.stdout").write_bytes(result.stdout)
    (out.parent / "encoder.stderr").write_bytes(result.stderr)
    receipt.update(
        exit_code=result.returncode,
        finished_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),
    )
    (out.parent / "encoder-after.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    data = out.read_bytes()
    packets = []
    offset = 0
    while offset < len(data):
        ts, size = struct.unpack_from("!qI", data, offset)
        offset += 12
        packets.append(
            packet(
                data[offset : offset + size],
                codec=request.param,
                timestamp_us=ts,
                ordinal=len(packets),
            )
        )
        offset += size
    assert len(packets) == 4
    assert [p.timestamp_us for p in packets] != sorted(p.timestamp_us for p in packets)
    return request.param, packets


def test_actual_windows_reordered_continuous_stream_and_original_reap(synthetic):
    _, packets = synthetic
    frames = []
    with decoder() as d:
        original = None
        for item in packets:
            frames.extend(d.decode(item))
            original = original or d.process
            assert d.process is original  # Same codec state for I/P/B packets.
            # A venv launcher could spawn a child before Job assignment.
            assert Path(original.args[0]) != MEDIA
        frames.extend(d.finish())
        assert original.poll() is not None
    assert len(frames) == 4
    assert [f.timestamp_us for f in frames] == [1000000, 1040000, 1080000, 1120000]
    expected = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    by_ts = {p.timestamp_us: p.ordinal for p in packets}
    for frame, rgb in zip(frames, expected, strict=True):
        assert (frame.width, frame.height) == (64, 48)
        assert frame.ordinal == by_ts[frame.timestamp_us]
        raw = frame.private_rgb()
        assert len(raw) == 64 * 48 * 3
        means = [sum(raw[channel::3]) / (64 * 48) for channel in range(3)]
        assert all(abs(a - b) < 12 for a, b in zip(means, rgb, strict=True))
        assert "bytes" not in repr(frame)
        with pytest.raises(TypeError):
            pickle.dumps(frame)


def test_revoked_immediately_before_publication_discards_and_reaps(synthetic):
    _, packets = synthetic
    calls = 0

    def auth(_):
        nonlocal calls
        calls += 1
        return calls < 2

    d = decoder(authorize=auth)
    with pytest.raises(DecodeDenied):
        d.decode(packets[0])
    assert d.process.poll() is not None


def test_bad_bitstream_is_sanitized_fenced_and_reaped():
    d = decoder()
    with pytest.raises(DecodeError) as error:
        d.decode(packet())
    assert "invalid" not in str(error.value).lower()
    assert d.process.poll() is not None
    with pytest.raises(DecodeError):
        d.decode(packet())


def test_deadline_retains_and_reaps_original_child(monkeypatch):
    original_popen = subprocess.Popen
    children = []

    def stalled(*args, **kw):
        child = original_popen(
            [args[0][0], "-I", "-c", "import time; time.sleep(30)"], **kw
        )
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", stalled)
    d = decoder(limits=DecodeLimits(deadline_seconds=0.2))
    start = time.monotonic()
    with pytest.raises(DecodeError):
        d.decode(packet())
    assert 0.18 <= time.monotonic() - start < 5
    assert d.process is children[0]
    assert children[0].poll() is not None


def test_wrong_response_binding_never_becomes_frame(monkeypatch):
    original_popen = subprocess.Popen

    def malformed(*args, **kw):
        return original_popen(
            [
                args[0][0],
                "-I",
                "-c",
                "import sys; sys.stdout.buffer.write(b'x'*128); sys.stdout.buffer.flush()",
            ],
            **kw,
        )

    monkeypatch.setattr(subprocess, "Popen", malformed)
    d = decoder()
    with pytest.raises(DecodeError):
        d.decode(packet())
    assert d.process.poll() is not None


@pytest.mark.parametrize(
    "kind",
    ["binding", "sequence", "count", "dimensions", "length", "timestamp", "ordinal"],
)
def test_exact_output_schema_cannot_publish_mismatched_data(monkeypatch, kind):
    original_popen = subprocess.Popen
    wire_binding = struct.pack("!Q16s16s16s", 7, b"O" * 16, b"C" * 16, b"T" * 16)
    head = [b"WDR1", 0, 1, wire_binding, 1]
    frame = [64, 48, 1000000, 0, 9216]
    if kind == "binding":
        head[3] = bytes(56)
    elif kind == "sequence":
        head[2] = 2
    elif kind == "count":
        head[4] = 17
    elif kind == "dimensions":
        frame[0] = 32
    elif kind == "length":
        frame[4] = 1
    elif kind == "timestamp":
        frame[2] = 2000000
    elif kind == "ordinal":
        frame[3] = 99
    output = (
        struct.pack("!4sBQ56sI", *head) + struct.pack("!IIqII", *frame) + bytes(9216)
    )

    def child(*args, **kw):
        code = f"import sys; sys.stdout.buffer.write(bytes.fromhex({output.hex()!r})); sys.stdout.buffer.flush()"
        return original_popen([args[0][0], "-I", "-c", code], **kw)

    monkeypatch.setattr(subprocess, "Popen", child)
    d = decoder()
    with pytest.raises(DecodeError):
        d.decode(packet())
    assert d.process.poll() is not None


def test_close_during_final_authority_check_discards_output(synthetic):
    _, packets = synthetic
    calls = 0
    d = None

    def auth(_):
        nonlocal calls
        calls += 1
        if calls == 6:
            d.close()  # Third input would emit first reordered picture.
        return True

    d = decoder(authorize=auth)
    d.decode(packets[0])
    d.decode(packets[1])
    with pytest.raises(DecodeDenied):
        d.decode(packets[2])
    assert d.process.poll() is not None


def test_idle_deadline_reaps_original_child_without_next_input(synthetic):
    _, packets = synthetic
    d = decoder(limits=DecodeLimits(deadline_seconds=0.6))
    d.decode(packets[0])
    original = d.process
    try:
        time.sleep(0.9)
        assert original.poll() is not None
    finally:
        d.close()
    with pytest.raises(DecodeError):
        d.decode(packets[1])


@pytest.mark.parametrize(
    "limits",
    [
        DecodeLimits(max_packets=1),
        DecodeLimits(max_output_bytes=1),
        DecodeLimits(max_frames=1),
    ],
)
def test_lifetime_quotas_fence_and_reap(synthetic, limits):
    _, packets = synthetic
    d = decoder(limits=limits)
    with pytest.raises(DecodeError):
        for item in packets:
            d.decode(item)
        d.finish()
    assert d.process.poll() is not None


def test_native_dimensions_disagree_cannot_publish(synthetic):
    _, packets = synthetic
    d = decoder()
    with pytest.raises(DecodeError):
        for item in packets:
            d.decode(
                packet(
                    item._data,
                    codec=item.codec,
                    width=32,
                    timestamp_us=item.timestamp_us,
                    ordinal=item.ordinal,
                )
            )
        d.finish()
    assert d.process.poll() is not None


def test_fallible_job_admission_reaps_already_retained_original(monkeypatch):
    import wso_core.tvt.windows_decode as module

    def broken_job(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(module, "_job", broken_job)
    d = decoder()
    with pytest.raises(KeyboardInterrupt):
        d.decode(packet())
    assert d.process is not None and d.process.poll() is not None


def test_drain_baseexception_cannot_publish_and_reaps(monkeypatch):
    def broken(self):
        raise KeyboardInterrupt()

    monkeypatch.setattr(WindowsDecoder, "_receive", broken)
    d = decoder()
    with pytest.raises(DecodeError):
        d.decode(packet())
    assert d.process.poll() is not None


def test_original_wait_baseexception_remains_supervised(synthetic, monkeypatch):
    _, packets = synthetic
    d = decoder()
    d.decode(packets[0])
    original = d.process
    original_wait = original.wait
    failures = 0

    def interrupted(*args, **kwargs):
        nonlocal failures
        if failures == 0:
            failures += 1
            raise KeyboardInterrupt()
        return original_wait(*args, **kwargs)

    monkeypatch.setattr(original, "wait", interrupted)
    d.close()
    assert original.poll() is not None
    assert failures == 1


class InertOwnedProcess:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.returncode = None
        self._handle = 999
        self.calls = []

    def poll(self):
        self.calls.append("poll")
        return self.returncode

    def kill(self):
        self.calls.append("kill")
        self.returncode = -1

    def wait(self, **kwargs):
        self.calls.append("wait")
        return self.returncode


class InertKernelCall:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


def inert_kernel(monkeypatch, close, assignment=None):
    import ctypes

    kernel = SimpleNamespace(
        CreateJobObjectW=InertKernelCall(lambda *args: 77),
        SetInformationJobObject=InertKernelCall(assignment or (lambda *args: True)),
        AssignProcessToJobObject=InertKernelCall(lambda *args: True),
        CloseHandle=InertKernelCall(close),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    return kernel


@pytest.mark.parametrize(
    "fault",
    [
        "kernel_lookup",
        "job_release",
        "job_false",
        "thread_create",
        "thread_start",
        "thread_started_then_interrupt",
    ],
)
def test_retirement_admission_failures_still_reap_original(monkeypatch, fault):
    import ctypes

    d = decoder()
    original = InertOwnedProcess()
    d._process = original
    d._job_handle = 77
    released = []
    faults = []

    def close(handle):
        if fault == "job_release" and not faults:
            faults.append("fault")
            raise KeyboardInterrupt()
        if fault == "job_false" and not faults:
            faults.append("fault")
            return False
        released.append(handle)
        return True

    kernel = inert_kernel(monkeypatch, close)
    if fault == "kernel_lookup":

        def lookup(*args, **kw):
            if not faults:
                faults.append("fault")
                raise KeyboardInterrupt()
            return kernel

        monkeypatch.setattr(ctypes, "WinDLL", lookup)
    if fault == "thread_create":
        actual = threading.Thread

        def create(*args, **kw):
            if not faults:
                faults.append("fault")
                raise KeyboardInterrupt()
            return actual(*args, **kw)

        monkeypatch.setattr(threading, "Thread", create)
    if fault in ("thread_start", "thread_started_then_interrupt"):
        actual = threading.Thread.start

        def start(thread):
            if not faults:
                faults.append("fault")
                if fault == "thread_started_then_interrupt":
                    actual(thread)
                raise KeyboardInterrupt()
            return actual(thread)

        monkeypatch.setattr(threading.Thread, "start", start)
    error = None
    try:
        d.close()
    except BaseException as exc:  # noqa: BLE001 - causal cleanup fault assertion
        error = exc
    assert error is None
    assert original.returncode is not None
    assert "kill" in original.calls and "wait" in original.calls
    assert released == [77]
    assert original.stdin.closed and original.stdout.closed
    assert d._job_handle is None
    assert d._retire_done.is_set()
    assert d._stop_watchdog.is_set()
    d.close()  # No join of an unstarted thread on subsequent close.


@pytest.mark.parametrize(
    "failure", ["interrupt", "configuration_false", "assignment_false"]
)
def test_job_created_before_assignment_interruption_is_retired(monkeypatch, failure):
    import wso_core.tvt.windows_decode as module

    original = InertOwnedProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kw: original)
    released = []

    def assignment(*args):
        if failure == "interrupt":
            raise KeyboardInterrupt()
        return failure != "configuration_false"

    kernel = inert_kernel(
        monkeypatch, lambda handle: released.append(handle) or True, assignment
    )
    if failure == "assignment_false":
        kernel.AssignProcessToJobObject = InertKernelCall(lambda *args: False)
    # Undo only the fixture's native Job stub; execute the real admission helper.
    monkeypatch.setattr(module, "_job", REAL_JOB)
    d = decoder()
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else DecodeError):
        d.decode(packet())
    assert d.process is original
    assert "wait" in original.calls
    assert released == [77]


def test_retirement_retains_started_io_until_done_even_after_job_fault(monkeypatch):
    original = InertOwnedProcess()
    reaped = threading.Event()
    completed = threading.Event()
    actual_wait = original.wait

    def wait(**kw):
        result = actual_wait(**kw)
        reaped.set()
        return result

    original.wait = wait

    def io_owner():
        reaped.wait()
        completed.set()

    child = threading.Thread(target=io_owner, daemon=True)
    child.start()
    d = decoder()
    d._process = original
    d._threads = [child]
    d._thread_done = (completed,)
    d._job_handle = 77
    attempts = []

    def close(handle):
        attempts.append(handle)
        if len(attempts) == 1:
            raise KeyboardInterrupt()
        return True

    inert_kernel(monkeypatch, close)
    d.close()
    assert "wait" in original.calls and completed.is_set()
    assert not child.is_alive()
    assert d._retirement_threads == (child,)
    assert d._retire_done.is_set()


from wso_core.tvt.windows_decode import _job as REAL_JOB
