# Local TVT WebRTC media transport

## R142 mapped presentation clock — 2026-10-06

The source adapter now accepts fully validated equal derived device timestamps
while preserving raw-regression rejection. It keeps raw PTS separate from the
strict lifetime presentation PTS passed to the existing decoder and peer:
first mapped PTS is raw, then `max(raw, last_mapped + 24)` microseconds. This
does not reset on resolution rotation. Original decoder opaque/pending mapping,
track PTS/ordinal validation, permits and original peer ownership are unchanged.

The 24µs minimum is deliberate: aiortc converts microseconds to 90kHz using
`int(Fraction)`. The widest equal-value interval is around signed zero and is
less than 22.23µs; 24µs therefore separates converted timestamps across all signs.
All mapped values stay signed-int64; overflow rejects without committing state.
Ordinary source advances pass through when ahead. The original source timestamp
remains private and unchanged; transport `timestamp_us` is now presentation time.

One focused actual synthetic VP8/SRTP same-peer test passed: equal raw inputs
mapped to 1,000,000/1,000,024/1,000,048/1,000,072µs and the receiving track returned
relative RTP PTS 0/2/4/6. It verified unchanged peer identity and peer/source close.
This is local synthetic media, not Chrome/recorder acceptance or a codec benchmark.
The complete source gate and limits are in
[the R142 report](../analysis/c10-duplicate-timestamp-report.md). Read it before
changing the mapping and update affected source/execution evidence afterward.

## Same-peer dimension transitions — 2026-10-06 (R137)

Source baseline: `6436748` plus the active uncommitted stage-1 worktree.
`NativeDecodedSource` now rotates isolated same-codec decoders after confirmed
old-decoder retirement, retaining the exact binding wire identity and original
WebRTC peer. `DecodeBinding` contains no dimensions. Existing per-frame RGB
dimension/byte checks and global increasing source PTS/ordinal checks support
this source change without modifications to `live.py` or `codec.py`.

The new inert source tests cover transitions before the first decoded frame and
while consuming the original peer's track, in both H264 and HEVC. A separate
real local aiortc VP8/SRTP receive test passed for **352×240 → 1280×720 →
352×240**, increasing received PTS and the same server peer. The existing
decoder/WebRTC/worker suite also passed138 tests. This is local synthetic media
verification, not Chrome or actual recorder acceptance. Existing transport
permit, stale grace, lease and shutdown behavior remain unchanged. See
[R137 source ownership](tvt-local-media-service.md) and the canonical service
report before subsequent changes or actual device sizing.

Analysis and implementation date: **2026-10-04, Asia/Seoul**. Source baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`. Initial tree already included another agent's
untracked local-media contract test. Parallel core, native and worker changes
continued during this isolated source slice. This report covers the media
package, its inert tests and this guide; it does not certify that parallel code.

Read [service-analysis.md](../service-analysis.md) and
[local service integration](tvt-local-service-integration.md), especially Phase 2,
before reuse; verify the current source and refresh this guide afterward. The
canonical service report controls overall implementation and execution status.

## Purpose and architecture

`services/tvt-media` converts privately decoded, authorized RGB frames into one
browser-compatible VP8 WebRTC video track. The trusted worker supplies an exact
`DecodeBinding`, a credential-free decoded source, a current-authority callback
and an admitted lease deadline. This package opens no device, DLL, file, URL or
media player. It neither decrypts credentials nor establishes SQL authority.

The package depends on `wso-core`, `aiortc==1.15.0` and `av>=14,<18`.
The existing Windows decoder uses its separate PyAV 19 subprocess. Native DLL,
that decoder and the media process must remain isolated. RGB uses padded PyAV
plane copies without a NumPy dependency. The upstream
[aiortc API](https://aiortc.readthedocs.io/en/latest/api.html) defines the peer,
SDP and ICE contracts used here; the pinned
[1.15 RTP sender source](https://github.com/aiortc/aiortc/blob/1.15.0/src/aiortc/rtcrtpsender.py)
shows encoding awaits an executor before outgoing packets.

Implemented files:

- `src/wso_tvt_media/codec.py`: strict existing `PrivateRGBFrame` / `DecodeBinding`
  checks, RGB byte and dimension bounds, and source microsecond PTS adaptation.
- `src/wso_tvt_media/signaling.py`: bounded video receive-only offer validation
  and immutable `SessionAnswer(sdp, type="answer")`.
- `src/wso_tvt_media/live.py`: original-peer/session lifetime, source protocol,
  bounded decoded queue, authority checks, VP8 track and transport fencing.
- `tests/tvt_parity/test_local_webrtc.py`: inert protocol negatives and real
  local aiortc encode/SRTP/receive/decode acceptance.

## Trusted integration contract

```python
class AuthorizedDecodedSource(Protocol):
    async def recv(self) -> PrivateRGBFrame: ...
    async def close(self) -> None: ...

session = LocalWebRtcSession(
    binding=original_decode_binding,
    source=original_owned_source,
    current=fresh_current_local_lease_check,
    expires_at=admitted_monotonic_deadline,
    on_delivery=optional_encoder_admission_observer,
)
answer = await session.answer(browser_offer_sdp, one_use_offer_id)
session.renew(fresh_authorized_monotonic_deadline)
await session.close()
```

`answer` has `sdp: str` and `type: str = "answer"`; callers can explicitly map
these two fields to their strict HTTP/RPC DTO. `current()` must return literal
`True` only for the exact live lease, actor, web session, store, connection
generation, selected channel and original native/decoder binding. It must run
on the worker's authorized execution context, and cannot be supplied by callers.

The source adapter must dequeue only currently authorized frames, close its
original native and decoder owners, and confirm disposal or raise. Root's
composition supplies elementary-packet/source proof and isolated decode before
this boundary. `BoundedDecodedSource` is an optional media-event-loop queue:
its producer calls `put_nowait(frame)`. It does not permit arbitrary thread or
native-callback mutation and does not itself own a native process.

An admitted deadline is at most 30 seconds ahead. Heartbeat integration must
call `renew` using a fresh committed lease check and the exact remaining lease
duration. Renewal never revives an expired, revoked or closed session. A
50 ms monitor catches expiry, source fencing or failed current checks while
the receiver is idle. Caller cancellation of a pending frame read or signaling
request closes the original session. Public close shields its owned disposal
task from cancellation.

## Bounds and implemented behavior

The default decoded queue holds at most three frames and 16 MiB total; any
overflow permanently closes and clears it. Per-frame limits are 4096 by 2160
and 16 MiB RGB. Incorrect binding, payload size, type, ordinal or PTS rejects
delivery. Track ordinals and source timestamps must increase; the adapter
preserves `timestamp_us` with `Fraction(1, 1_000_000)`. WebRTC subsequently uses
the standard 90 kHz video RTP clock and a randomized RTP origin. Browser PTS
is consequently normalized and quantized, rather than an absolute copy of the
private timestamp. No fabricated real-time source PTS replaces it.

Only one offer is accepted for one video `recvonly` browser transceiver;
server SDP is `sendonly`. SDP is capped at 65,536 UTF-8 bytes, 512 lines,
2,048 characters per line and 64 ICE candidates, with at most 32 codecs.
Malformed Unicode and syntax, audio/data/multiple tracks, wrong direction,
missing RTCP multiplexing, missing VP8, arbitrary resource/ICE URL fields,
expired offers and replay all return fixed signaling denial and close the
session. RTP extension URI identifiers are allowed because they are identifiers
and are not fetched. The package exposes no trickle-candidate mutation API.

ICE is explicitly `RTCConfiguration(iceServers=[])`: host candidates and no
default external STUN/TURN service. SDP necessarily carries peer candidates;
these are interpreted only through the bounded ICE protocol. Production TURN
policy and credentials must be trusted deployment configuration reviewed
separately; this implementation accepts no caller-configured ICE server URLs.

Authority is checked before and after source dequeue, before and after RGB
conversion, before handing a frame to the encoder, and on each original DTLS
media send. The pinned aiortc transport hook fences encoded packets after the
encoder await and also fences retransmits. Any observed authority loss becomes
a permanent local fence even if membership or another fact is later restored.
The hook uses aiortc's private `_send_rtp` method and therefore requires review
and regression execution before changing the pinned dependency.

`on_delivery` observes a decoded frame admitted to the RTP encoder. It is not
proof that Chrome rendered a frame. SDP negotiation, queued RGB, raw HEVC and
track creation do not establish PLAYING. Core/browser state must use its
separate actual received-frame proof before claiming browser acceptance.

Close fences the source and stops the original track and peer. Caller waits for
source and peer disposal each have a three-second bound. Separately retained
original close tasks are shielded and continue until actual settlement; caller
timeout never cancels those resource owners. Peer disposal is attempted even
when source disposal fails. Cleanup uncertainty is retained as a fixed
`MediaDenied` from `close` and `wait_closed`; it cannot become clean-close
acceptance. The source owner remains responsible for independently reaping its
original process when its close deadline fails.

## Verification executed in this slice

The first scoped run failed collection with missing `wso_tvt_media` before the
package existed. Meaningful regression failures then demonstrated that the
original implementation could revive after an observed transport denial,
leave a cancelled frame read alive, and leak malformed Unicode as a raw
encoding exception. A later regression demonstrated that a valid frame could
escape after a PTS failure but before scheduled disposal ran; close scheduling
now fences synchronously. These failures were corrected and rerun.

Final commands on 2026-10-04:

```powershell
$env:PYTHONPATH='packages/core/src;services/tvt-media/src'
.superpowers/webrtc-venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_webrtc.py --tb=short
.venv/Scripts/python.exe -m ruff check services/tvt-media tests/tvt_parity/test_local_webrtc.py
.venv/Scripts/python.exe -m mypy --python-executable .superpowers/webrtc-venv/Scripts/python.exe --follow-imports=silent services/tvt-media/src/wso_tvt_media
```

Results: **19 passed, zero skipped** in 0.65 seconds; scoped Ruff passed;
strict mypy passed for all four package modules. The ignored scratch venv had
aiortc 1.15.0 and PyAV 17.1.0. Workspace dependency/lock integration is Root's
separate change, not established by this scratch-environment result.

Actual inert video execution established answer SDP, negotiated VP8, local
ICE/DTLS/SRTP transmission, decoded 64 by 48 RGB pixels, and adjacent received
PTS spacing of 2,999 or 3,000 ticks for 33,333-microsecond source spacing.
It also established original-peer closure and queue discard on revocation.
Negative tests cover wrong bindings, dimension/payload bounds, queue overflow,
offer replay, expiry, renewal limits, permanent authority fencing, cancelled
frame reads, decreasing PTS, cleanup uncertainty and malformed/sendrecv SDP.

These results do not establish actual Chrome behavior, real CCTV decode,
continuous native lifetime, SQL/API/RPC integration, camera/channel identity,
packet loss handling, high-resolution performance, multiview capacity or
production NAT/TURN deployment. No real device, private credential, database
migration or Git commit was used. The complete project test suite was not run
by this scoped agent; Root owns integrated verification and canonical outcomes.

## Remaining priorities and product questions

Root must compose current SQL admission and heartbeat renewal, the exact
native frame proof / elementary-packet adapter, isolated decoder and source
cleanup owner before production exposure. Actual browser receive/render proof
and device identity remain the M4 gate. Measure portrait-frame encoding cost,
slow-consumer behavior, maximum tiles and cleanup failure handling before
choosing service capacity. Decide deployment TURN policy and whether VP8-only
initial support meets supported-browser requirements; H.264 and audio remain
separate changes.

Update log: 2026-10-04 — initial media package; preserve source PTS, bound
signaling/queues, fence original transport after asynchronous encoding, and
record 19 inert cases with actual VP8 loopback plus explicit execution limits.

## Review corrections — 2026-10-04

The [independent media review](../analysis/2026-10-04-local-webrtc-review.md)
reported C0/I0/M2. Only its two exception-contract corrections were applied:

- `validate_offer` now normalizes aiortc's `AttributeError` for a value-less
  candidate and `StopIteration` for an unknown format-parameter payload to the
  fixed `SignalingDenied` contract.
- `answer` preserves its signaling denial or original `CancelledError` even
  when original-source cleanup reports uncertainty. It handles only the fixed
  `MediaDenied` from disposal; the persistent cleanup-failure flag remains and
  subsequent `close` / `wait_closed` still raise `MediaDenied`.

Four new inert regressions first failed on the two parser exception classes,
cleanup-masked signaling denial, and cleanup-masked actual aiortc negotiation
cancellation. After correction, the integrated workspace's `.venv` scoped
pytest completed **23 passed, zero skipped, 0.70 seconds**. Scoped Ruff and
strict mypy passed for all four package modules. Commands used the same scoped
pytest selection above with `.venv/Scripts/python.exe`, and mypy used that
integrated interpreter rather than the scratch `--python-executable` option.

This update does not change the current-authority transport hook, native
ownership bounds, codec, lease policy or deployment behavior. No real-device,
SQL, browser or complete-project acceptance was executed in this correction.

## Ingress, transport permit and close corrections — 2026-10-04

Scope: `native_source.py`, `live.py` and their two focused test files. Baseline
remains `211d1484aa16eb30f5d362758f149f98dec9dfdf` plus parallel disjoint service
integration. Root supplied two actual failed-run observations: native callbacks
filled 256 chunks / 299,812 bytes while the combined ingress/decode producer
was blocked; shutdown later retained an unresolved aiortc close future. Root
retired those exact failed runtimes before this source window. Those outcomes
are coordinator-reported failed acceptance, not this agent's device execution.
The canonical service report retains actual run/process/cleanup evidence.

`NativeDecodedSource` now registers both original threads and completion events
before starting either. Dedicated native ingress checks current authority, reads
bounded native batches and adapts exact source packets into a FIFO of at most
**16 compressed frames / 4 MiB**. The dedicated decoder checks scope before
dequeue/decode and keeps one original WDC2 decoder. FIFO overflow fences and
clears the stream; compressed frames are never dropped or reordered to recover.
Only the existing single latest decoded RGB slot may replace old decoded frames.
Partial thread-start failures retain started owners; close waits for both stages,
actual decoder `wait_closed=True` and both joins. Interrupted decoder cleanup
retains its exact decoder and retrying owner instead of signaling settlement.

To avoid synchronous SQL on every RTP fragment, `transport_current()` uses a
private monotonic delivery permit, with **200 ms maximum permission-observation
window**. Only freshly SQL-authorized decoded-frame publication renews it; its
deadline is clipped to the freshly read SQL lease expiry, and query latency
consumes the window. Native ingress, decoder and publication retain fresh SQL
checks on their background threads. Event-loop `recv`/`binding` and the RTP
guard can use the fast permit without SQL or native calls. Known stop/revocation
clears it immediately; expired or stopped source cannot revive an old peer.
Root must supply `source.transport_current` to the peer and keep SQL/native
lease renewal and any fresh SQL watch checks outside the event loop. This
implements a bounded observation window, not instantaneous observation of an
external SQL revocation before it reaches an owning stage.

aiortc 1.15 creates its original internal close future before awaiting transceiver
retirement. Cancelling that original coroutine on timeout can strand every later
close. Source and peer now each have a separately retained original close task;
only shielded caller waits time out. A retained settlement observer waits for
both actual tasks before signaling `wait_closed`. Timeout/error remains fixed
cleanup uncertainty even after later settlement; it does not claim clean close.
Source-before-peer close ordering is preserved. Root's worker may await those
same originals after uncertainty, rather than recreate or cancel ownership.

Three causal tests first failed against old behavior: a blocked first decode
prevented draining a native burst; no second-thread start existed to retain on
partial failure; and delayed actual aiortc transceiver close reported settlement
before its original future completed. Final focused execution:

```powershell
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_webrtc.py --tb=short
```

**38 passed, zero skipped, 7.24 seconds**. Ruff passed for both owned sources and
tests; strict mypy passed for both source modules. Tests additionally prove exact
ten-frame compressed order during decoder stall, 16-frame overflow fencing,
fast transport with no event-loop SQL, shorter SQL-expiry clipping, idle permit
expiry, observed revocation/no revival, delayed original source/peer close and
honest pending settlement. Existing inert actual VP8 loopback remains in this
focused selection. No callback quota, SQL pool, native SDK, codec or wire limit
was raised. An interim concurrent-close attempt failed the existing offer-replay
case; preserving original source-before-peer order resolved that regression.

No new device/browser/SQL or long-duration acceptance was executed here. Actual
pipeline throughput, frame identity, native lifetime, browser rendering and
shutdown after the two failed Root runs still require reviewed Root execution.
This source correction is not a browser PLAYING or release-readiness claim.

## Liveness correction: authority heartbeat, non-terminal staleness and pooled SQL — 2026-10-04 (post-reboot)

Scope: `native_source.py`, `live.py`, `worker.py`, their three focused test
files and `packages/core/src/wso_core/tvt/local_media_admission.py`. Baseline
`211d1484aa16eb30f5d362758f149f98dec9dfdf` plus the saved uncommitted media
work. Review findings, the SQL latency measurement and rulings R106/R107 are in
[the liveness review](../analysis/2026-10-04-local-media-liveness-review.md).

Problem: the previous section's permit was renewed only by decoded-frame
publication, and `LocalWebRtcSession` treated every lapse as permanent
revocation. Two independent reviews reproduced permanent peer closure after a
single ~220 ms gap at 10 fps, at 5 fps, and at 20 ms per SQL transaction. Root
measured the media admission's `NullPool` path on this Windows runtime at
p50 25 ms / p95 ~125 ms / max 182 ms per transaction (pooled: ~0.4–2.3 ms).

Implemented correction (source exists; acceptance below is separate):

- **Pooled admission engine.** `LocalMediaAdmission` uses a bounded dedicated
  `QueuePool` (size 4, overflow 4, 1 s checkout timeout, pre-ping, 300 s
  recycle). Every authority check is still its own fresh transaction with
  transaction-local timeouts and the per-transaction `current_user` check;
  other admissions keep `NullPool`. Checkout timeout maps to the fixed 503
  boundary; `shutdown()` already disposes the engine.
- **Authority heartbeat.** `NativeDecodedSource` owns a third stage thread,
  `local-live-authority-owner`, registered with its completion event before any
  start, included in partial-start handling, settlement and joins. Every
  `AUTHORITY_HEARTBEAT_SECONDS = 0.05` it renews the permit from one fresh
  `executor.lease()` through the helper shared with `_publish`:
  `min(pre-SQL observation + PERMIT_SECONDS (0.2), SQL lease expiry)`. A
  slow-but-successful round renews nothing (publish drops that frame); denial
  or error still fences the source.
- **Non-terminal staleness.** `LocalWebRtcSession(..., permitted=...)` separates
  terminal liveness (`current`: revocation, stop, end, expiry) from the 200 ms
  emission permit. While stale, the transport hook silently drops RTP/RTCP
  (returning normally so aiortc's send loops survive) and `track.recv`
  withholds frames; no media leaves. Staleness longer than
  `STALE_GRACE_SECONDS = 2.0` fences permanently. A fence is never revived.
  Omitting `permitted` keeps the previous behavior exactly.
- **Wiring.** The worker builds the peer with `current=source.alive` (lock-only:
  not stopped, not ended) and `permitted=source.transport_current`. Proof
  retrieval and retirement attachment run via `asyncio.to_thread`; the source
  constructor receives `proof=` and makes no executor call. A loop-local
  re-check after those awaits refuses to start a source for a lease retired or
  capped meanwhile. `_watch`/`_browser_received` SQL runs off the loop with
  identity re-checks (and deny while `_closing`).
- **SQL reduction.** Decoder stage: 4 transactions per frame (two decoder
  `authorize` checks plus `lease`), down from 7 or more; no SQL per idle poll.
  Ingress keeps one check before each read and one per adapted frame.
- **Ingress read deadline (R108).** `INGRESS_READ_DEADLINE_MS = 2000`, the
  previously reviewed value. Under the unchanged executor/provider contract an
  empty read that reaches its deadline is terminal (the provider's final
  authority check meets the exhausted budget and closes the native session and
  lease), so this value is also the longest tolerated gap between compressed
  frames; a channel below about 0.5 fps cannot play. An interim 500 ms value was
  withdrawn after re-review showed it ended the lease on any 500 ms gap.
- **Permit assignment (R110).** Renewals keep the later of the existing and new
  deadlines while the source is not stopped; each candidate is bounded by its
  own pre-SQL observation plus 200 ms and that observation's SQL expiry. Stop
  zeroes the permit and nothing renews afterwards.
- **Retirement retry and quarantine (R109).** After a reported close timeout
  the worker awaits the original source close and `peer.wait_closed()`
  (settlement of both original tasks) instead of calling aiortc `close()` a
  second time. `LocalWebRtcSession.original_close_failed` is true only when an
  original close task itself raised. In that case the worker quarantines the
  lease: no retirement confirmation, no confirmed SQL close, custody and the
  two-source capacity slot retained, no further retries, and worker shutdown
  reports not-closed. A bounded-wait timeout followed by clean settlement still
  confirms normally.

Executed evidence for this correction: implementer TDD (RED recorded per
finding; GREEN 73 passed ×3, then 78 passed ×2 after the follow-up round, each
with a clean `log_cli` run); Root's independent rerun on the final combined
tree: **111 passed** across source/WebRTC/worker/pool/service/contracts/RPC
selections, Ruff, Ruff format and strict mypy clean; owned real-SQL admission
suite with the pooled engine: **15 passed, 0 skipped**, owned database removed,
source database unchanged, no known private values in output.

Not established by this section: continuous Chrome playback, two-store
operation, stop/reopen or clean retirement on the real runtime.

## Authority gate and permit anchoring (R120) — 2026-10-05

Scope: multi-view stage-1 Task 1 (final review I3). `native_source.py` changes
one line plus comments; the gate itself lives in `local_media_admission.py`
and is specified in the media-service guide's
[hot-path authority gate](tvt-local-media-service.md#hot-path-authority-gate-r120r121--2026-10-05)
section. Baseline: worktree at `6436748` plus the uncommitted Task 1 delta.

- `executor.current()` and `executor.lease()` are now answered by a per-lease
  gate: an answer may come from a non-locking SQL check that began up to
  `AUTHORITY_FRESHNESS_SECONDS = 0.1` before the call, never earlier. This is
  a call-entry observation bound, not a return-time freshness guarantee.
  Ordinary reusable cache answers are clipped to lease expiry. Under R133,
  an eligible successful in-flight observation may answer its runner and
  waiters even when response latency crosses expiry; the downstream emission
  permit is independently clipped to expiry. Ingress, decoder `authorize`,
  publication and the 50 ms authority heartbeat together cost at most one SQL
  check per 100 ms per stream, instead of about 33 per frame.
- `_renew` now records `observed = time.monotonic() − AUTHORITY_FRESHNESS_SECONDS`
  (imported from the admission module). The candidate permit is still
  `min(observed + PERMIT_SECONDS, now + SQL lease expiry left)`, and R110's
  keep-the-later rule and stop zeroing are unchanged. So a permit never outlives
  the backing check's start plus 200 ms, and the sender bound stays
  t_r + 200 ms + one `time.monotonic` tick (15.625 ms on this Python).
- Ingress, decoder and publication: no grant to a call that begins after
  t_r + 100 ms (before R120: a fresh check per call, plus the latency of a check
  already in flight). Overall t_r + 300 ms while check latency is 200 ms or less.
- Consequence: one renewal now extends the permit to about its call time plus
  100 ms (previously plus 200 ms). The 50 ms heartbeat keeps the permit
  continuous while heartbeat gaps plus check latency stay under 100 ms; a
  renewal answered later than that renews nothing and is staleness, which stays
  non-terminal for `STALE_GRACE_SECONDS = 2.0`.

Tests (inert, executed 2026-10-05): `test_permit_anchored_at_earliest_gate_observation`;
`test_composed_gate_pipeline_stays_live_with_bounded_sql` (real executor and
gate with stubbed observe SQL at 3 ms, 10 fps, 8 packets per frame: no fence,
no permit lapse, no withheld datagram, at most elapsed/F + 2 observe checks and
no `current`/`worker_view` SQL); `test_revocation_with_gate_meets_bounds` (no
grant to calls beginning after t_r + 116 ms, no datagram after t_r + 216 ms,
fenced, never revived). `test_older_renewal_never_shortens_newer_permit_or_renews_after_stop`
was updated to the anchored values (permit 100.15, later finish at 100.08). The
media selection passed with 139 tests. Not established: device or browser
playback with the gate.

Update **2026-10-05, final stage-1 review M1**: corrected the absolute
past-expiry answer claim above to the accepted R133 distinction between
call-entry observation age, ordinary cache reuse, eligible slow-success
in-flight results and expiry-clipped emission permits. Documentation only;
no authority code or new gate execution was changed or claimed.
