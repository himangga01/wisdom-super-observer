# Private Windows compressed video decoder

Analysis date: **2026-10-04, Asia/Seoul** (Fix1; original acceptance 2026-10-03). Root supplied executable baseline
`756946ca73cff31d7ebb23141873088b470a96b4` and documentation baseline
`36fc954e4754d69721596e190c35f9cf14de3e4c`. Git was not invoked by this task.
This guide records an isolated implementation and **synthetic Windows decoder
acceptance**. **MATCHED=0; release_ready=false.** Actual current CCTV framing,
permissions, packets, provider integration and device decoding remain Root work.
The dated continuous-mode section below adds explicitly selected WDC2 behavior;
the WDC1 diagnostic defaults and historical acceptance remain preserved.

For later reviews, read this guide and [the local live codec guide](tvt-local-live-codec.md)
first, verify current source/dependency hashes and refresh changed evidence. Root
owns canonical service-analysis and AGENTS updates. The handoff report and frozen
source/artifact manifests are in the `W08-windows-decode-*` implementation packet.

## Purpose and implemented boundary

`packages/core/src/wso_core/tvt/windows_decode.py` owns a bounded, single-use
decoder task. `windows_decode_worker.py` is a standalone, private binary worker.
Neither imports moving TVT providers/live codecs. The parent imports no PyAV or
FFmpeg. Native media work takes place in a separate, originally owned Python
process, outside the TVT DLL host and outside TVT callbacks.

The trusted caller supplies already source-validated **unencrypted, complete
Annex B access units**, exact `h264` or `hevc`, positive dimensions, packet
ordinal, source presentation timestamp in microseconds, and an immutable private
binding: connection generation, owner identity, channel and task. The owner
identity must incorporate the relevant session/device ownership in the caller's
authority lookup; it is not a session token or a newly inferred grant. Each
packet carries the exact same full binding and generation as the task. Neither
constructing these objects nor reading codec/dimension markers establishes access.

Only the explicit Annex B format is supported. An initial start code check is a
necessary syntactic check; it cannot prove whole access-unit framing. There is no
URL, file demuxing, length-prefixed conversion, arbitrary parser, encryption or
decryption. AVCC/HVCC, containers, unknown codecs, encrypted data, foreign
bindings, stale generations and dimension/codec changes are refused and fence
the task. The caller must prove the real source framing before using this API.
Do not infer Annex B from a TVT H264/H265 fourcc alone. Source `h265` must map
explicitly to `hevc` after that validation.

## Owner lifecycle and authority

1. Allocate fresh owner/task/generation context and serialize admission, current
   read **and** live authority changes, decoding, queueing and delivery in the
   original owner. One thread calls a decoder; a callback must not recursively
   decode or finish. A recursive call fences the task.
2. Construct `WindowsDecoder(binding=..., authorize=..., executable=...)`. The
   callback must return literal `True` only for current read and live rights for
   the exact generation/owner/channel/task. Login/inventory/decoder success is
   insufficient. Closed/denied/failed instances cannot reopen.
3. Construct `ElementaryPacket(data, binding=..., codec='h264'/'hevc',
   format='annexb', generation=..., width=..., height=..., timestamp_us=...,
   ordinal=..., encrypted=False)`. Feed in encoded order with strictly increasing
   ordinals and unique source PTS. Output order may differ. Keep header and I/P/B
   packets in the same decoder process. Output may legitimately be empty while
   native pictures are delayed; that is not acceptance of a decoded frame.
4. `decode` checks authority before admitting input and immediately before
   returning each private batch, including empty batches. Denial/exception or
   callback-triggered close discards the batch and reaps the child. `finish`
   flushes delayed pictures, requires all accepted PTS to resolve, verifies exact
   EOF and zero child exit, then checks authority before returning and closes.
5. `PrivateRGBFrame` exposes immutable binding, dimensions, source PTS/ordinal
   and explicit `private_rgb()` bytes to trusted media code. Any later queued
   delivery needs a fresh authority check under the same original owner. Clear
   queued/retained media on revocation and close. Frame construction is not an
   authority credential. Do not log objects, locals, payloads, callback state,
   identities or traceback locals; private reprs/pickle refusal are defensive
   conventions, not protection against arbitrary Python introspection.
6. `close` fences first and retains exact Popen, Job, feeder/drainer and their
   completion-event ownership. It establishes a **running** retirement owner
   before stopping the deadline watchdog or attempting Job release. Job lookup,
   CloseHandle false/error/interruption and original kill/wait failures retain
   custody and retry; original-Popen kill/wait also runs when Job release fails.
   Reaper creation/start failure falls back to the current caller retiring these
   resources synchronously. An unstarted thread is never reused or joined.
   Completion is recorded only after original reap, started IO completion/join,
   pipe closure and Job release; retries remain supervised until then. New Job
   ownership is retained immediately after creation and before configuration or
   assignment, including failed admission. No PID, executable-name or port-based
   kill is used. Use a context manager or `finally: close()`.

## Codec state and exact timestamp mapping

One PyAV codec context preserves SPS/PPS/VPS and reference pictures over the
ordered packet series. No media parser silently invents access-unit boundaries.
Each packet uses `time_base=1/1000000`, source `pts`, and a private opaque tuple
`(source_timestamp_us, source_ordinal)`. `AV_CODEC_FLAG_COPY_OPAQUE` is enabled.
Every returned frame must preserve that exact tuple, have the matching frame PTS
and still-pending source mapping, and preserve the declared dimensions. Unknown,
duplicate, missing or foreign mappings fail closed. The parent independently
checks response binding, sequence, count, dimensions, exact RGB byte length and
pending PTS/ordinal before publication.

PyAV 19.0.1 source
[codec context](https://github.com/PyAV-Org/PyAV/blob/v19.0.1/av/codec/context.py),
[packet](https://github.com/PyAV-Org/PyAV/blob/v19.0.1/av/packet.py) and
[frame](https://github.com/PyAV-Org/PyAV/blob/v19.0.1/av/frame.py) were reviewed.
`decode(None)` uses the codec's packet time base; this standalone elementary
context leaves it unset. Opaque propagation supplies the exact source mapping
for those flushed frames; no timestamp is guessed from arrival order. Real
synthetic tests prove both H264 and HEVC opaque/PTS propagation through B-frame
reordering and delayed flush. This does not prove every source packet family.
Packets containing only parameter sets without an associated decoded picture
remain unresolved and are deliberately refused at final flush. Initial synthetic
access units contain their parameter sets and picture together.

## Process and resource bounds

The Windows venv `Scripts/python.exe` is a launcher. Assigning that launcher to
a Job can race an interpreter child that already exists. The parent instead
reads the bounded `pyvenv.cfg` executable reference, invokes the actual base
interpreter with `-I`, and passes only the isolated site's package directory as
infrastructure argv. Worker media and all private bindings travel exclusively
through bounded binary stdin/stdout. PyAV loads only after the parent assigns the
retained actual process to its Windows Job and sends configuration.

The Job permits **one process** with kill-on-close, process and aggregate Job
memory bounds. Decoder and RGB conversion threads are both explicitly **one**;
PyAV 19's [reformatter source](https://github.com/PyAV-Org/PyAV/blob/v19.0.1/av/video/reformatter.py)
otherwise defaults conversion threads to automatic selection. FFmpeg `max_pixels`
also limits decoded picture allocation; exact dimensions are checked before RGB
conversion. Parent timeouts and an automatic idle watchdog fence and reap the
same original process. stderr is discarded rather than exported or accumulated;
worker exceptions can emit only a fixed binary failure.

| Bound | Default | Constructor ceiling |
| --- | ---: | ---: |
| Width / height | 1920 / 1080 | 4096 / 2160 |
| Per compressed packet | 1 MiB | 4 MiB |
| Per RGB picture | 6,220,800 bytes | 26,542,080 bytes |
| Accepted packets / decoded pictures | 256 / 256 | 1024 / 1024 |
| Lifetime compressed input / RGB output | 16 / 64 MiB | 64 / 256 MiB |
| Pictures per response | 16 | 32 |
| Entire task elapsed deadline, including idle | 30 seconds | 60 seconds |
| Process and Job committed memory | 512 MiB | 1 GiB |

Native allocations precede some returned-frame count checks; the input quota,
FFmpeg pixel bound and OS memory/deadline bounds contain that native work. This
is a limited task API, not an indefinitely running monitor. The caller must
budget aggregate decoder count, memory, queued frames and deadlines across tasks,
refresh authority on reconnect and select a fresh task when a bound is reached.
Production packaging, scheduler ownership and throughput sizing are pending.

## Exact isolated dependency and official references

Official [PyPI 19.0.1 metadata](https://pypi.org/pypi/av/19.0.1/json) selected
`av-19.0.1-cp312-abi3-win_amd64.whl`, 28,149,519 bytes, SHA-256
`906fc3db09288319a75ea23ffefb59961c7dbe0d1c074601507a89de7d8593d8`.
The acquisition script downloaded the exact files.pythonhosted.org URL from
that metadata and verified upstream size/hash before installing with
`--no-index --no-deps`. Raw upstream metadata, its hash, full wheel record and
wheel bytes are under `.superpowers/runtime/windows-media-decode/`. This task
changed no global installation, shared pyproject or lock file. The worker
refuses PyAV versions other than 19.0.1.

Interpreter: CPython **3.12.10**, Windows x64. The isolated package root is
`.superpowers/runtime/windows-media-decode/venv/Lib/site-packages`. Exact
interpreter/launcher paths, version, DLL/PYD paths, sizes and individual SHA-256
hashes are preserved in `dependency-inventory.json` and the final artifact
manifest. Bundled reported library versions are:

| Library | Version |
| --- | --- |
| libavutil | 61.1.102 |
| libavcodec / libavformat / libavdevice | 63.1.102 |
| libavfilter | 12.1.102 |
| libswscale | 10.1.102 |
| libswresample | 7.1.102 |

The executed wheel reports FFmpeg **9.0.2**. Its bundled libraries live under
`venv/Lib/site-packages/av.libs` inside the isolated runtime. Exact primary DLL
filenames and hashes follow; `dependency-inventory.json` additionally records all
23 bundled DLLs and 50 PyAV PYDs with absolute paths, sizes and hashes.

| DLL filename | SHA-256 |
| --- | --- |
| avcodec-63-2756d4fffb772585dcdece87427716a4.dll | 8e13fdedbeefb6a8b5d22b567122ec3c00384add569de9e589e53a86bd08422c |
| avdevice-63-2b26d22512639c049532c0bc6f6c022f.dll | 43247c1bdaaec40977738037fdea7e8b779b3e93213dd529b1d25735b3099d8c |
| avfilter-12-87c7677b784d3ea4ecceb3e6cae9c9f1.dll | a9b9e84178dd73162f47a3a531c321fad955ca3a7ff04a9517db7e7c78bf9ab2 |
| avformat-63-e8c4f8fc30664f2b7e85dcc683bd4b0d.dll | 49759edae5286f10e4b11a442f51fb70bacde1f92b7b876038231c4d8140c506 |
| avutil-61-e540ec7976bbd26a4a94dc737be3001c.dll | ff2ba1b0d884336d53f1aee7b05873c5a3bbb987d0ffc79a49b92ed77579cd19 |
| swresample-7-4f9462a1fb73b949ccad2774dd941624.dll | a8bfee136c4c4e49d95b4439b1b80136504b2783cf93638f64bd3ad7de8e0ebe |
| swscale-10-9af0a10ad7003982e48548ff39e98465.dll | f2956978470b3ed26c4f5db80b45d4c3a9188a4a8622133f73ded71504df85d6 |

These are the executed wheel's versions. The current official
[installation](https://pyav.basswood.io/docs/stable/overview/installation.html)
and [elementary decoding cookbook](https://pyav.basswood.io/docs/stable/cookbook/basics.html)
pages carry version 19.0.0 documentation; the chosen dependency is 19.0.1.
No older PyAV 9 / FFmpeg 4 instructions were used. Licence notices, production
distribution, deployed hash pinning and update policy need packaging review.

## Executed acceptance and actual limits

Scoped tests cover generation and full owner/channel/task binding, denied and
throwing authority, close during admission and prepublication, encrypted/AVCC/
container/unsupported input, quota/dimension rejection, original child deadline
and idle reap, malformed response magic/binding/sequence/count/dimensions/length/
timestamp/ordinal, failed Job admission, drainer BaseException, interrupted
original wait, sanitized errors and private repr/pickle refusal.

On this Windows host, four inert 64x48 RGB pictures (red, green, blue, white) were
locally encoded with libx264 and libx265 and decoded through the actual owned
process. Both codecs returned picture counts **0,0,1,1 then 2 at flush**. H264
input PTS order was `1000000,1120000,1040000,1080000`; HEVC input PTS order was
`1000000,1120000,1080000,1040000`. Both outputs had PTS
`1000000,1040000,1080000,1120000`, exact source ordinal mappings and 9,216 RGB
bytes per picture. Independently prescribed RGB channel means were within 12
of each intended color; dimensions and all four distinct PTS were checked.
The same original Popen served every packet and was actually reaped at exit 0.
Fixtures came from no camera, device identifier, vendor or downloaded sample.

Original 2026-10-03 scoped acceptance was **43 passed** and remains preserved,
along with the two four-picture proofs and original 325-artifact manifest. Root's
independent review identified cleanup-admission and ordinary-checkout test
portability gaps; Fix1 corrects both and keeps that historical evidence intact.

Default tests now run **37 portable contract cases** and explicitly skip **19
unselected native cases**. The contracts use inert owned processes or ordinary
Python children and simulate only Windows constructor/Job admission, so they
need no private PyAV runtime. Native fixtures are separate: select them with
`WSO_WINDOWS_DECODE_NATIVE=1`. Selection without Windows or the isolated runtime
fails with an explicit prerequisite error, before any child starts; it never
becomes a skipped or mocked native success. Unselected native admission skips
before reading the ignored runtime. The same 37/19 outcomes were verified with
a sentinel that forbids runtime lookup and a simulated non-Windows test module;
this was executed on Windows, not an executed Ubuntu/CI claim.

Fix1 ran the one necessary selected real changed-close proof: three preserved
locally generated H264 access units produced counts 0,0,1 and one exact 64x48 red
RGB frame with PTS1000000/ordinal0. The actual native interpreter was still live
at close. An injected interruption **before** the first actual OS Job release
proved running reaper/retained Job ownership, safe original-Popen fallback,
second-attempt Job release, IO retirement and actual original wait/reap. Its
forced-close child exit was1, not a successful flush exit. H264/HEVC historical
eight-picture acceptance was not broadly replayed. No actual CCTV is involved.

Four causal mutants were rejected: absent thread-start fallback, unowned newly
created Job, discarded interrupted Job, and fake unselected native admission.
Ruff and strict mypy cover the current owned sources (ruff also covers tests).
Mypy ignores unavailable third-party imports in the shared project environment;
this is not static verification of PyAV. Fixed-source/full-command receipts,
preimages, delta and readsets are in `W08-windows-decode-Fix1-*`. Optional broad
tests were not invoked. Failed interim attempts remain separate receipts.

Priority gaps: prove current device read/live authority and exact access-unit/
PTS semantics; bind real source bytes to the private decoder; verify at least
two real decoded frames under Root's controlled acceptance; review the fixed
resource/deadline policy and production package hashes/licences. Audio,
playback, encrypted media, AVCC configuration and browser transcoding are outside
this boundary. This task establishes no device compatibility or release claim.

Update log: 2026-10-03 — initial independent Windows decoder, official isolated
PyAV dependency acquisition and four-picture H264/HEVC synthetic acceptance.

2026-10-04 — Fix1 establishes active retirement before fallible Job/reaper
release, adds synchronous fallback and newly created Job custody, and separates
portable contracts from explicitly selected real Windows native acceptance.

## Explicit continuous mode — 2026-10-04

Current source baseline: `211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, plus this uncommitted slice and concurrent disjoint
core/native/API/media work. Scope: the two decoder modules, their existing test
file and this guide. Read the canonical [service analysis](../service-analysis.md),
[Phase 2 integration](tvt-local-service-integration.md) and
[WebRTC guide](tvt-local-webrtc.md) before reuse; verify source and refresh the
affected evidence afterward. This section records synthetic execution, not
actual CCTV or browser acceptance.

The diagnostic lifetime quotas can stop persistent video while authority is
still current. The new mode explicitly preserves one original codec and worker:

```python
limits = DecodeLimits(continuous=True, inactivity_seconds=5.0)
decoder = WindowsDecoder(binding=binding, authorize=fresh_exact_authority,
                         executable=isolated_pyav19_python, limits=limits)
try:
    frames = decoder.decode(proved_elementary_packet)
finally:
    decoder.close()
    settled = decoder.wait_closed(timeout=3.0)
```

`continuous=False` remains the default, with identical **WDC1** configuration
bytes and lifetime bounds. Continuous configuration explicitly uses **WDC2**,
the same 48-byte `!4s9Id` layout with the final double interpreted as inactivity
seconds, constrained to **0.05 through 5 seconds**. Unknown versions, ambiguous
non-boolean mode values and non-finite deadlines fail before native work.
Existing WDQ1/WDR1 request/response binding, sequence and frame schemas remain.

Only fresh literal-True exact authority at an unexpired parent admission renews
the deadline. The worker independently rejects late requests and renews only
after receiving a complete bounded Annex B packet. The original codec, process,
Job, generation, owner, channel and task remain unchanged. A renewal event and
deadline lock update the original watchdog; expiry fences under that lock so
late renewal cannot revive it. Revocation, scope substitution and close remain
permanent fences. Authority is still rechecked before frame publication.

There is no fixed 60-second continuous lifetime ceiling. Each operation and idle
interval remain bounded by admitted inactivity; startup is included. The
original one-process, memory, pixel and kill-on-close Job bounds remain. Root's
initial live composition uses the five-second policy; narrow timeouts require
actual Windows startup/load measurement. Aggregate sessions and queues remain
the service owner's responsibility.

| Limit | WDC1 diagnostic | WDC2 continuous |
| --- | --- | --- |
| Packet/RGB/dimensions | Per packet/picture | Same |
| `max_packets` | Lifetime packets | Maximum unresolved PTS mappings |
| `max_input_bytes` | Lifetime input | Per admitted packet |
| `max_frames` | Lifetime pictures | Pictures per response |
| `max_output_bytes` | Lifetime RGB | RGB per response |
| `max_response_frames` | Pictures per response | Same |
| `deadline_seconds` | Entire task, maximum 60s | Does not define lifetime |
| `inactivity_seconds` | Unused by wire/lifetime | Renewed inactivity, maximum 5s |
| Process/Job memory | Original owner memory | Same |

The stricter applicable per-packet/per-response cap wins. Both processes bound
pending mappings by `max_packets` and pop them as exact frames resolve.
Continuous mode does not accumulate lifetime input/frame/output counters or
append to the historical timestamp set. Each response retains only bounded
temporary counters, bytes and frame lists. Native picture/reference state
remains constrained by pixel and Job memory bounds. The existing 64-bit request
sequence and 32-bit source ordinal bounds are checked; neither counter resets
or grows beyond its wire range. Reaching a bound closes the task.

Initial WDC2 input requires **strictly increasing original microsecond PTS and
packet ordinals**. Repeated/decreasing PTS rejects and reaps the original owner;
retired PTS cannot be reused without an unbounded historical set. Encoded-order
non-monotonic PTS, including the earlier B-frame fixture, is deliberately
unsupported in this initial live mode. WDC1 preserves that fixture's existing
reordering/opaque/flush behavior. No PTS is synthesized to fit the restriction.

### Original disposal confirmation

`close` still establishes retirement and has a bounded join; its return alone
does not prove that interrupted Job release completed. New public
`wait_closed(timeout: float | None = None) -> bool` requires initiated close
and observes the original retirement event. `True` establishes original reap,
started IO completion/join, pipe closure and Job release. Timeout returns
`False` while the retained owner keeps retrying. Invalid timeout or waiting
before close raises the fixed decoder error; `None` waits for settlement in
the trusted ownership context. Request cancellation must not discard the source's
original decoder, handles or retirement owner; Root's source composition retains
them independently until confirmation.

### Verification and actual limits

Missing mode/settlement APIs failed before implementation. New cases cover
configuration bounds, pending-map saturation, stale generation, monotonic PTS,
revocation, idle expiry, original-process reuse and unreleased Job custody that
makes `wait_closed` remain false until release and complete retirement.

Actual isolated PyAV **19.0.1** Windows execution encoded and decoded **260
640-by-544 frames per codec**, both H264 and HEVC. Each used one original decoder,
retained exact source PTS/ordinal mapping and returned **271,564,800 RGB bytes**
before successful flush/reap. Batches were discarded promptly, without retaining
all images or writing a large RGB artifact. Per response was bounded to one
frame / 1,044,480 RGB bytes; pending mappings to four; input to the largest
individual encoded packet. This exceeded 256 packets/frames, 256 MiB cumulative
RGB and the configured 0.2-second diagnostic deadline without restarting.
`wait_closed(0)` additionally confirmed actual original resource settlement.

```powershell
$env:WSO_WINDOWS_DECODE_NATIVE='1'
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_windows_decode.py --tb=short
.venv/Scripts/python.exe -m ruff check packages/core/src/wso_core/tvt/windows_decode.py packages/core/src/wso_core/tvt/windows_decode_worker.py tests/tvt_parity/test_windows_decode.py
.venv/Scripts/python.exe -m mypy --follow-imports=silent packages/core/src/wso_core/tvt/windows_decode.py packages/core/src/wso_core/tvt/windows_decode_worker.py
```

Fresh selected decoder suite: **71 passed, zero skipped, 22.42 seconds**;
scoped Ruff and strict mypy passed. After adding the public settlement assertion,
both continuous codec proofs were rerun: **2 passed, 69 deselected, 3.16 seconds**.
Default portable selection passed **44 cases / 27 explicitly unselected native
skips, 3.74 seconds**; those skips are not native acceptance.

Earlier outcomes remain recorded: H264 first-packet startup with a one-second
inactivity budget failed at ordinal zero after 1.016 seconds; an independently
owned trace of the same inert packet completed in 0.282 seconds. Admitted
five-second continuous proofs subsequently passed. The first full native run
was **68 passed / 1 failed**: the unchanged HEVC diagnostic idle case did not
finish its first packet within 0.6 seconds. That unchanged case then passed
separately, followed by the full 71-case success. Startup is load-sensitive;
no diagnostic deadline was widened or reset to suppress these outcomes.

The continuous proof lasted seconds, not an actual 60-plus-second soak. It
establishes removal of cumulative diagnostic quotas and renewal beyond its short
configured diagnostic deadline, not long-duration leak/performance acceptance.
No CCTV, private credentials, SQL migration, TVT DLL, browser, whole-project
suite or Git publication was used. Root must independently review WDC2 and prove
actual identity, continuous native/decoder/browser delivery, permission changes,
orphan cleanup and capacity. Original PyAV packaging and WDC1 bounds remain;
production readiness is unestablished.

Update log: 2026-10-04 — explicit WDC2 renewal, bounded bookkeeping and monotonic
source PTS; honest original settlement API; actual two-codec 260-frame proof,
preserved failed runs/reruns and fresh 71-case selected acceptance.

### Minor timeout review correction — 2026-10-04

The [independent continuous-decoder review](../analysis/2026-10-04-continuous-decoder-review.md)
reported C0/I0/M1 and independently executed **71 passed / zero skipped** actual
inert native cases before this correction. Its bounded reproduction found raw
`OverflowError` from `math.isfinite(10**400)` outside `wait_closed`'s fixed error
boundary. The added regression first failed with that exact exception. Numeric
validation now runs inside the existing normalization boundary, returning fixed
`DecodeError` for this invalid timeout. Completed original settlement remains
observable with finite and `None` waits afterward; retirement ownership is
unchanged.

Scoped correction verification: `pytest ... -k wait_closed --tb=short` completed
**3 passed / 69 deselected, 3.10 seconds**. Ruff and strict mypy passed. No broad
native replay, device or browser call was made for this minor change. The
existing native original-resource proofs and their execution limits remain as
dated evidence; Root owns approval and actual CCTV execution of the corrected
source.
