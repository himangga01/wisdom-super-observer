# Windows owned local live session

Analysis date: **2026-10-04 (Asia/Seoul)**. Source baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`; the dispatched worktree was clean.
This report describes the new M3/M4 native session implementation. Concurrent
core/SQL/media/API work belongs to its own review and the
[canonical service report](../service-analysis.md).

Read this report together with the [integration plan](tvt-local-service-integration.md),
[socket provider](tvt-windows-socket-provider.md),
[live wire codec](tvt-local-live-codec.md), and
[historical actual capture/decode acceptance](tvt-windows-live-acceptance.md)
before changing this layer; update affected source and execution evidence after.

## Purpose and implemented architecture

`services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py` supplies
`NativeLocalLiveProvider.open_session(credentials, selection, deadline_monotonic,
current, cancel)`. It accepts the core `LocalMediaChannel` or private immutable
`LiveSelection`. Only the existing proved default main/stream1 path is admitted;
substream requests fail. There is no inferred quality mapping or socket sharing.

The existing Windows supervisor still validates the source receipt, DLL bundle,
ACLs, interpreter and original Job admission. A service live request starts a
fresh original socket/process and obtains fresh same-session inventory and native
live permission. The exact selected GUID/raw/window/ordinal mapping must match
the private setup before the worker can send live-open. The source codec claims
the socket's first exclusive task and checks its original open ACK. Route0 uses
the existing qualified first-and-only-task rules; no route or channel field is
invented. Each reconnect requires fresh admission and a fresh original process.

`local_live_ipc.py` carries a bounded private duplex pipe. JSON is restricted to
private control/setup facts. Original wire envelopes use bounded binary messages;
the child and parent independently parse them through the existing `LiveCodec`.
The parent receives real `PrivateLiveFrame` values reconstructed from those
envelopes, preserving exact source headers, identity, timestamps and ordinals.
No pickle, public media JSON, diagnostic raw capture file, credential, native
handle or raw GUID is exported through public DTOs.

The callback only copies into its existing bounded queue. It performs no SQL,
IPC, decoder or native call. Serialized worker code asks the parent for current
authority after buffer preparation before Send and before native queue dequeue.
The parent invokes the supplied current callback synchronously on its caller
thread, checks authority before/after codec feed, and checks again before/after
frame dequeue. Neither native callbacks nor cleanup threads invoke SQL.

## Credential boundary and session handoff

Before private setup and the first live Send, the worker closes/drops the login
handshake, inventory login, accepted LoginResult, credential-bearing request,
raw serial bytes and parent packet credential fields. The consumed login Send
buffers (including metadata username queries) are overwritten. Only the protocol session/channel/task identifiers,
permission basis and peer capability needed for live remain. The parent drops
its request packet before handoff and does not retain the startup SQL callback.

`OwnedLocalLiveSession` owns only the exact `ChildOwner`, private authority,
immutable core `LocalLiveProof`, and serialization lock. It rejects pickling and
uses a fixed private repr. Read methods receive fresh media authority callbacks;
there is no long credential callback or database transaction wrapping playback.

Open returns after the original ACK and first supported Annex-B keyframe have
passed source parsing. Its proof uses the exact core `LocalLiveProof` type.
Login/serial/channel/native live basis come from the same fresh session. Codec
and timing flags reflect that parsed compressed frame and its retained source
timestamp conversion. The native framing flag currently records source-header
presence after accepted wire parsing; it does **not** establish Annex-B access
unit/unencrypted framing proof. Root's source adapter must independently validate
the access unit and PTS before PLAYING. These flags do **not** prove decoded pictures,
browser codec negotiation, end-to-end latency, synchronized clocks or PLAYING.
Core/browser composition must establish actual decoded delivery separately.

## Bounds, expiry and cleanup

- Native callback queue: at most 256 chunks and 1 MiB total copied bytes.
- Private envelope/IPC message: 1 MiB envelope plus its one-byte tag.
- Parent queue: at most 16 frames and 4 MiB retained source/payload byte values.
  Byte accounting deliberately includes duplicate source byte values; bounded
  object overhead and the codec's partial assembly are separate.
- Only one child message is outstanding before its current-authority ACK.
  Slow consumers eventually overflow the native or parent bound and fence the
  original session. Frames are discarded on overflow, revoke, expiry or close.
- Read request: at most 16 frames, 4 MiB payload and 20 seconds. A payload larger
  than the caller's byte budget remains queued; the caller must provide an
  adequate bounded budget. No oversized frame is returned or silently dropped.
- Source codec lifetime counters remain finite: 1 TiB received bytes and
  1,048,576 packets, with existing 1 MiB packet/64-fragment bounds. They do not
  establish practical uninterrupted runtime capacity.
- The first accepted frame ACK hands the child an independent 30-second native
  orphan deadline. Every later read may renew that deadline only after current
  authority validates an unexpired generation. Explicit `current(...)` uses the
  same rule. These renewals never extend SQL media expiry or revive a denied
  generation. SQL heartbeat policy remains the core's responsibility.

Cancel and expiry are watched independently of a blocked caller/SQL check. The
watchdog stops only the retained original process; a reaper waits for that
watchdog, then waits on the same Popen handle, closes its original Job, joins its
original writer and closes IPC/output streams. `ChildOwner.finish` is serialized
so caller and reaper cannot race resource closure. Cleanup failure retains the
original owner in `PENDING_OWNERS`; it cannot be replaced by a process lookup or
reported as confirmed cleanup. Explicit close also waits for the reaper.

The local service permits at most **two** healthy explicitly handed-off original
live owners. Each has its own process/Job/socket/task/IPC. A third receives fixed
`LOCAL_DEVICE_BUSY`/429. Unknown or uncertain custody fences every new attempt;
existing inventory and diagnostic exclusive custody rules remain. This is a
service capacity policy awaiting actual two-device resource/retirement proof,
not a measured broader multiview capacity claim. Root will first test devices
sequentially and only then measure simultaneous resource use. A fresh reviewed
source receipt must include the new provider/IPC/tests/report `OWNED` entries.
Existing diagnostic inventory/capture paths and historical codec receipts stay
separate; diagnostic 60-second limits do not establish continuous service safety.

## Verification and remaining acceptance

Executed in this worktree using its admitted `.venv/Scripts/python.exe`:

- TDD red evidence: missing modules/interface; absent credential-discard hook;
  expiry/cancel killed the process but did not settle resources; queue accounting
  initially counted payload alone. Each issue was reproduced before its change.
- `python -m pytest -q tests/contract/test_local_live_provider.py --tb=short`:
  **20 passed**. Includes >128 continuous authority exchanges, caller-thread
  current checks, nonrevivable denial/expiry, setup/channel substitution, wrong
  native channel/permission, credential release before live Send, queue overflow
  and discard, bounded reads, and real inert Windows original Job/process
  handoff/close/revoke/cancel/expiry/dead-child retirement. Two simultaneous inert
  original processes prove distinct PIDs/Jobs/generations, close-one isolation,
  third-session BUSY and a fresh replacement after slot release. Private supplier
  exception contexts are discarded from the outgoing fixed failure. Three
  source-drift cases pin imported core media/proof and public media contracts.
- Final combined command `python -m pytest -q tests/contract/test_windows_socket.py
  tests/contract/test_local_inventory_provider.py
  tests/contract/test_local_live_provider.py --tb=short`: **343 passed in 12.47s**,
  zero failures/skips/warnings.
- Final `python -m ruff check` on the four native source modules and both changed
  native test files: passed. Strict `python -m mypy` on the four native source
  modules: **no issues found**. Scoped `git diff --check`: passed.
- The full application suite was not rerun for this native slice; the canonical
  service report retains its existing full-suite failures/limits. Concurrent
  core/SQL/API/media changes require their own current checks.

All new execution used invented byte streams and inert Windows child processes.
No vendor DLL, real CCTV call, credential reading, phone or ADB was used. Previous
real S1 position2/S2 position1 four-frame HEVC acceptance remains historical
bounded-capture evidence. This new continuous path still needs independent
source review and Root's authorized real-device runs for sustained read/decode,
identity/timing, revoke/expiry/close/reconnect, resource retirement and browser
playback. The 30-second orphan/10-second heartbeat policy is a proposed service
bound awaiting that actual safety acceptance.

Native Stop/Destroy are attempted when the worker can run its cleanup path.
Hard cancel/expiry can terminate it before orderly close. A live close Send is
not a close ACK. Vendor pointer lifetime/callback quiescence and memory erasure
inside vendor/native runtime allocations remain unproved. Dropping Python
references and overwriting the consumed buffer is not a guaranteed forensic
erase of immutable copies; no such claim is made.

Priority: review this native delta, then actual sequential device and composed
browser acceptance. Open product questions: measured multi-session capacity,
stream/quality variants, supported recorder variants, reconnect policy and the
actual safe orphan/heartbeat bound. No production enablement or release-ready
claim follows from these tests.

Update log: 2026-10-04 — initial continuous Windows session implementation and
inert original-process lifecycle evidence; actual device/browser acceptance open.

### Review correction — 2026-10-04

The [independent review](../analysis/2026-10-04-windows-live-session-review.md)
reproduced I1: the old native expiry could pass between the first current check
and assignment of a renewed deadline. Its exact invented clock sequence
`9.8, 9.9, 10.1, 10.2, 10.3` previously returned true for expiry10 ->20.
The added deterministic regression was observed failing before correction.

The corrected transition retains the old expiry, checks it immediately before
assignment and serializes that assignment with the permanent denial latch.
SQL callbacks execute outside this lock, preserving independent watchdog cleanup.
The first-frame orphan handoff uses the same guard. The exact crossing now
returns false, retains expiry10, latches `deadline`, and rejects later renewal;
existing valid-renewal tests continue to pass.

Fresh correction checks: **21 live tests passed**; combined native
socket/inventory/live suite **344 passed**; scoped Ruff, strict mypy on all four
native source modules and `git diff --check` passed. Re-review is pending; the
initial C0/I1/M0 decision remains historical evidence. No SDK, credential, device,
SQL, network or Git mutation was used for this correction. Actual acceptance
remains open.

### Actual callback pressure correction — 2026-10-04

Root's controlled child observer in native generation
`c936cccfed5040c990ff9f97bf4e34d2` identified live `LiveDenied` with callback
failed/closed true, context-current and authorized true, remote not closed or
expired, and **255 queued chunks / 287643 bytes**. Parent first-frame handoff had
occurred at6125ms; current SQL checks stayed true. These are attributed Root
structural observations, not private payload inspection by this implementer.
The [safe diagnosis](../analysis/2026-10-04-windows-live-first-attempt-diagnosis.md)
retains earlier attempts and the causal boundary. They establish actual chunk
quota saturation, not sustained browser playback.

The continuous loop previously requested one external current grant per native
callback byte chunk, so small transport segments were drained at parent IPC
pump speed. A live-only FIFO snapshot dequeue now drains the already bounded
callback queue after one current grant, joining bytes outside its lock. It keeps
the exact original byte order, **256 chunks / 1MiB caps**, and independent
per-envelope/frame parent authority/ACKs. Inventory and diagnostic capture keep
their original single-chunk dequeue. This does not remove slow-consumer fencing,
increase memory/session quotas or alter source packets/tasks/payloads.

Two regressions were observed RED before the fix: exact FIFO batch availability,
and an invented64KiB keyframe arriving in64-byte callbacks every2ms with a20ms
parent pump. Both now pass; the latter returns the exact payload with every
produced envelope byte accounted for and an empty callback queue. These tests
use inert native callbacks/IPC only. No device, credential or SQL call was made
for this fix, and Root confirmed all prior actual owners retired before edits.

Fresh combined native regression: **346 passed in13.51s**, zero failures/skips/
warnings; scoped Ruff, four-module strict mypy and diff checks passed. Root reports
independent FIFO correction review **C0/I0/M0**, with both new regressions passed.
A new Root-bound source receipt precedes the next normal
Chrome/device retry. Corrected-source actual acceptance remains open.

### Live keepalive — 2026-10-04

Motivation (Root's executed evidence; not re-run here): real Chrome playback of
both recorders worked, but in four of four sessions frames stopped 29–30 s after
the native live stream opened. SQL authority, ICE consent, packet loss and CPU
were ruled out. In the approved SuperLive Plus 1.18.1 APK (jadx `defpackage`),
`fu3.N1` (fu3.java:965–970) schedules timer task `fu3.b`, whose `run`
(fu3.java:293–295) calls `v5`, with a 6000 ms delay and 6000 ms fixed-delay
period. `cw3.v5` (cw3.java:8011–8020) sends an outer `gg0` with magic 825307441
(0x31313131) and length 0 through `m5`: the N9000 heartbeat ("Length0 is
heartbeat" in the [N9000 codec reference](tvt-local-n9000-codec.md)). Until now
`serve_live` sent only the open request and, from `finally`, at most one close.

`serve_live` now sends exactly `31 31 31 31 00 00 00 00` (`LIVE_KEEPALIVE`, built
in the worker; the magic is byte-order symmetric) while the original live task is
open. The first is due `LIVE_KEEPALIVE_SECONDS` (6.0 s) after the open Send
succeeded, on the loop's monotonic clock. Each next one is due 6 s after the
previous actual Send, so a stalled loop sends one heartbeat at its next iteration,
never a catch-up burst. Every keepalive uses the open/close gating: current `send`
authority, then the `allowed(identity)` recheck (`LiveDenied` if false), then
Send, through one buffer pair allocated and retained once before the loop. A
return other than 8 sets `failure = "send"` and ends the loop like an open short
write; the unchanged `finally` may then attempt its single close. None is sent
before a successful open, after loop exit or from `finally`. Receive handling,
idle/frame authority, deadline semantics, `SafeResult` and limits are unchanged.

Inert verification only (no SDK, device, credential, SQL, browser or network):
13 new `serve_live` cases were observed failing before the change and passing
after it. They cover exact bytes at +6/+12/+18 s and none at the +24 s deadline
exit, a fresh `send` grant before each heartbeat, five revocations inside that
grant, short writes (-1/0/7/9), a 30 s clock stall and one retained buffer pair.
Socket plus live-provider suite: **313 passed**, 0 skipped (baseline 300); scoped
Ruff, format check and strict mypy passed. This worker change needs independent
native review and a new Root source receipt. Real-device and Chrome acceptance
with the keepalive (playback beyond 30 s) is **pending**; nothing here shows that
a recorder keeps streaming.
