# Local media liveness review and correction — 2026-10-04

Analysis date: 2026-10-04 (Asia/Seoul). Controller: Claude Code (Opus 5.5) after
the reboot checkpoint, using Superpowers 6.4.1 subagent-driven development
(installed from `claude-plugins-official` at the user's request).

Scope: the unreviewed ingress / transport-permit / close delta in
`services/tvt-media/src/wso_tvt_media/native_source.py` and `live.py`, the
pending `worker.py` wiring from the
[reboot handoff](2026-10-04-reboot-handoff.md) section 3, and the SQL
authority path they depend on
(`packages/core/src/wso_core/tvt/local_media_admission.py`).

Source baseline: worktree `codex/superlive-web-service`, HEAD
`211d1484aa16eb30f5d362758f149f98dec9dfdf`; all reviewed media sources are
uncommitted/untracked. Frozen review inputs and their SHA-256 values are kept in
the ignored SDD workspace
`.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/claude-media-c1/`
(`snapshot-r0/` = handoff state, `snapshot-r1/` = after worker wiring).

Initial state verified in this session: the author-frozen hashes matched
(`native_source.py` `b7a7665d…`, `live.py` `91917e6f…`); the focused
source/WebRTC/worker selection passed **42 passed, 0 skipped, 9.83 s**.

## 1. Worker wiring (Task W1)

Implemented as the handoff required: `_prepare` passes
`source.transport_current`; `_watch` and `_browser_received` run their SQL via
`asyncio.to_thread` and re-verify peer/source identity after each await.
Implementer evidence: RED 7 failed / 6 passed, GREEN **51 passed**; ruff,
ruff-format and strict mypy clean. Independent task review: spec compliant,
task quality approved, with one plan-mandated cross-component Important
finding (section 2, C1) and minors m1-m9.

## 2. Findings

Independent review r0 (read-only, inert scratch experiments, no device/DB):
**Ready: No — Critical 1, Important 3, Minor 6.** The safety properties held
(200 ms bound, no transport SQL on the loop, permanent fencing, exact FIFO,
honest close settlement). The liveness properties did not.

| ID | Severity | Finding |
| --- | --- | --- |
| C1 | Critical | The emission permit is renewed only by decoded-frame publication, and `LocalWebRtcSession` treats a lapse as permanent revocation. Inert reproductions: one 220 ms gap at 10 fps fenced the peer at 2.1 s; a 5 fps stream fenced at 0.61 s; 20 ms per SQL transaction fenced at 0.14 s. The startup window (offer, ICE, DTLS) is fully exposed. |
| I1 | Important | The decoder thread ran 7 serialized SQL transactions per frame (plus ingress and provider checks), and each transaction opened a new PostgreSQL connection (`NullPool`). |
| I2 | Important | `NativeDecodedSource.__init__` ran `executor.proof()` SQL (and native retirement on denial) on the media event loop. |
| I3 | Important | No test exercised multi-second liveness or composed the real source with the real session. |
| M1-M6 | Minor | Timing-fragile permit tests; 2 s ingress read deadline could push a normal stop past the 3 s dispose budget; worker retry re-called `peer.peer.close()`; closed-loop posts could skip decoder retirement; thin startup FIFO headroom; dead `_decoder` attribute. |

W1 task review independently reported C1 as plan-mandated Important I1 (the
worker's own 1 s `renew` would fence after a successful fresh SQL check once
the last frame was older than ~200 ms).

Real device timing context: captured real HEVC frames were ~99-109 ms apart
([acceptance guide](../integrations/tvt-windows-live-acceptance.md), line 54).

## 3. Measurement (executed in this session)

The owned PostgreSQL 17 cluster was started with its existing
`runtime.py start` (exit 0; roles verified, no privileged flags; data and
credentials unchanged). Inert transactions using the worker role and the
admission's exact `connect_args` (`set_config`, `SELECT current_user`,
`SELECT 1`):

| Engine | Serial p50 / p95 / p99 / max | 6 threads p50 / p95 / max | Throughput |
| --- | --- | --- | --- |
| `NullPool` (current) | 25.1 / 122.3 / 137.3 / 147.2 ms | 30.4 / 127.8 / 182.4 ms | 163 txn/s |
| `QueuePool` 4+4 | 0.4 / 0.6 / 0.7 / 0.7 ms | 2.3 / 3.1 / 38.5 ms | 2,587 txn/s |

With `NullPool`, `_publish` alone (three transactions) costs ~75 ms at the
median and exceeds the 200 ms permit at p95, and seven transactions per frame
exceed the ~100 ms frame interval. This is consistent with — but does not by
itself prove the cause of — the earlier failed runs' queue saturation.
Per-transaction timeouts are transaction-local (`set_config(..., true)`) and
`SQLAlchemyError`, including a pool checkout timeout, already maps to the fixed
503 boundary.

## 4. Rulings

- **R106.** Fix before any device run: (a) bounded dedicated `QueuePool`
  (size 4, overflow 4, 1 s checkout timeout, pre-ping, 300 s recycle) for the
  media admission only — every check is still a fresh SQL transaction;
  (b) a third owned authority-heartbeat thread renews the permit every 50 ms
  from a fresh `executor.lease()`, sharing the publish helper; a slow but
  successful round skips renewal rather than fencing; (c) staleness is
  non-terminal in the transport (RTP/RTCP dropped and `recv` paused while
  stale; fence after 2.0 s continuous staleness), while revocation, stop, end
  and expiry stay terminal; (d) redundant serialized SQL removed; (e) proof and
  retirement attachment SQL moved off the loop. The 200 ms window is not
  lengthened, SQL is not cached beyond it, and the permit never substitutes
  for admission.
- **R107.** Reviewer minors folded into the same fix wave; decoder spawn time
  becomes an acceptance measurement.
- **R108.** R106 item 4 withdrawn: the ingress read deadline returns to the
  reviewed 2000 ms, because an empty read reaching its deadline is terminal
  under the existing executor/provider contract (native-receipt-covered code,
  not changed here). A compressed-frame gap of 2 s or more still ends the lease.
- **R109.** Supersedes R107's unconditional suppression: SQL cleanup is
  confirmed only after both original close tasks settle without raising; if an
  original close raised, the lease is quarantined (stays STOPPING, keeps its
  capacity slot, worker shutdown reports not-closed).
- **R110.** Permit assignment takes the maximum of valid deadlines while not
  stopped; stop still clears it.

## 5. Correction and re-review status

**Pooling (Task P1).** Implemented as ruled; task review spec-compliant and
approved (Critical 0 / Important 0; three test-brittleness minors deferred).
Root resolved the reviewer's open item: `max_connections` 100 (3 reserved),
worker role `rolconnlimit` -1, so the 8-connection cap fits. Owned real-SQL
admission suite with the pooled engine: **15 passed, 0 failures, 0 skipped**
(run `d7dc899c84f1434aa69f5c4c86496d4f`), owned database removed, source
database unchanged, no known private values in output.

**Liveness (Task L1).** Implemented R106 (design in the
[WebRTC guide](../integrations/tvt-local-webrtc.md), "Liveness correction"
section). Implementer evidence: RED recorded, GREEN 73 passed ×3, clean
`log_cli` run. Root's independent run on the combined L1+P1 tree:
**106 passed** (source, WebRTC, worker, pool, service, contracts, RPC API),
Ruff and strict mypy clean.

Scoped re-review: **17 of 17 original findings addressed**, including C1
re-run under the original failing schedules (220/250/300 ms gaps at 10 fps,
steady 5 fps, 20 ms SQL, paired delivery, 1.5 s first decode — no fence, no
permit lapse, no datagram without a permit). It found one new Important issue
and six minors:

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| N1 | Important | The 500 ms ingress read deadline (from R106 item 4) makes any compressed-frame gap of 500 ms or more terminal: the provider waits to the deadline, its final authority check calls the executor's exhausted budget, and the denial closes the native session and lease. Root confirmed this in `local_live_provider.py` and `local_service.py`. | R108: restore 2000 ms; executor/provider contract unchanged; contract-modelling test |
| N2 | Minor | Suppressing `wait_closed` uncertainty let the worker confirm SQL cleanup even if aiortc's original close raised. | R109: confirm only after clean settlement; quarantine otherwise |
| N3 | Minor | Persistently slow but successful SQL delays startup failure to the caller's budget. | Parked: bounded, fails closed |
| N4 | Minor | Last-writer-wins permit assignment can shorten a valid deadline. | R110: `max()` while not stopped |
| N5 | Minor | Windows 15.6 ms timer granularity makes harness sleeps busy-spin. | Parked: flake watch |
| N6 | Minor | Saved RED output predates the final test count; one claimed mutant not in the log. | Parked: evidence note only |
| N7 | Minor | `NativeDecodedSource.recv()` no longer enforces the permit itself. | Parked: enforced at the session layer; wiring tested |

Out of scope, recorded: the permit clock is `time.monotonic`, whose Windows
tick is ~15.6 ms, so the effective emission bound is 200 ms plus at most one
tick; two stores add ~80 heartbeat transactions per second (measure pooled
latency under that load during acceptance).

**Fix round 1 (N1, N2, N4).** Implemented under R108–R110: ingress
`INGRESS_READ_DEADLINE_MS = 2000` with a test whose fake read models the
terminal-deadline contract (a single 1.0 s gap at 10 fps neither ends the lease
nor fences the session; RED at 500 ms); read-only
`LocalWebRtcSession.original_close_failed` and worker quarantine; `max()`
permit assignment. Implementer: RED per finding, GREEN 78 passed ×2 with a clean
`log_cli` run, two quarantine mutants killed. The implementer's harness blocked
its append to the SDD report file; Root did not perform that blocked write on
its behalf, and this document, the ledger and the WebRTC guide carry the final
state. Root's independent run on the final tree: **111 passed**; Ruff, Ruff
format and strict mypy clean. Final source hashes: `native_source.py`
`22fca26c…`, `live.py` `c9f9ec81…`, `worker.py` `845e2d40…`,
`local_media_admission.py` `37970c0e…`.

Scoped re-review of fix round 1: **N1, N2, N4 addressed; no new Critical or
Important breakage.** The reviewer's own experiment with the real worker and
the real aiortc session confirmed that clean or slow-then-clean original close
confirms cleanup, while a raising original close yields 503, quarantine,
retained custody and zero confirmations.

Final verdict for this delta: open blocking findings C0/I0. Deferred minors
for the whole-branch review: three P1 test-brittleness items; N3, N5, N6, N7;
an unguarded test-worker start; the missing fix-round section in the SDD report
file; and the out-of-scope items below.

Open items for production bootstrap (not blockers for the owned acceptance
run):

- A quarantined lease holds SQL capacity beyond restart: the SQL close is bound
  to the original worker epoch (migration 0013), so the STOPPING row counts
  against the 32 global and 4 per tenant/actor caps until manual cleanup, and
  the 1 Hz sweep repeats unconfirmed writes with no operator signal. A recovery
  path is needed.
- The test runtime's dispose loop polls `worker.shutdown()` without a bound, so
  a quarantined lease would keep the owned runtime from exiting (custody kept,
  no false success).
- Compressed-frame gaps of 2 s or more remain terminal, and on an idle stream a
  sweep's close can wait up to 2 s behind the provider's read lock.
- `_prepare` registers the peer without re-checking `_closing` after its last
  awaits; such an orphan peer self-fences because `source.alive()` turns false.

## 6. Actual Chrome acceptance run and diagnosis (executed 2026-10-04)

Run `local-devices-30b1015b9f664d85908abc5400de9f2e`, launched with the new
immutable approval `root-source-approval-c1.json` (SHA-256 `3fdf98ab…`, 91
bound sources; the unchanged native receipt was reused read-only after its 12
owned files and 14 dependencies were re-verified). `WSO_TEST_LOCAL_MEDIA_TRACE`
was unset. Per the user's instruction, the controller launched Chrome 154 itself
with a dedicated profile and drove it over the DevTools protocol on
`127.0.0.1:9333`, with no certificate-bypass flags.

**Accepted in this run (actual devices, actual Chrome):**

| Item | Evidence |
| --- | --- |
| Trusted HTTPS | TLS 1.3, local mkcert CA, HTTP 200; navigation would have failed on a certificate error. |
| OWNER login and device checks | Normal sign-in; `기기 확인` returned 8 channels (store 1) and 4 channels (store 2). |
| Real video in Chrome | Store 1 channel 2 and store 2 channel 1 each rendered 1280×1936 video at ~10 fps, with increasing `currentTime`, server-confirmed PLAYING, and 0 dropped frames when the tab was in front. |
| Two stores at once | Both stores played simultaneously (store 1 at 43 frames and store 2 at 255 frames in the same sample). |
| Stop / reopen / retirement | A user stop produced a consumed `stop` control and a `CLOSED`, `cleanup_confirmed=true` lease; store 1 then reopened and played again, and stopped cleanly. All six leases in the run ended `CLOSED`, cleanup confirmed. |
| Runtime cleanup | Shutdown through `shutdown.json`: coordinator exit 0, runtime exit 0, Next exit 0, private state removed, no custody retained, 0 known private values in evidence; no listener left on 3543. |

**Not accepted: continuous playback beyond ~30 s.** Every one of four sessions
(three on store 1, one on store 2) stopped delivering video **29–30 s after the
native session opened** (frames froze at 287 and 292), and the server retired
the lease about 2 s later. Diagnosis, without changing any code between
attempts:

1. SQL authority was not the cause: re-evaluating every clause of the lease's
   liveness function afterwards found them all still true (web session, OWNER
   membership, connection generation and status, store, device row, channel,
   tenant epoch); only the grant was invalidated, which the worker's close does.
2. An instrumented browser timeline showed heartbeats returning 200 PLAYING
   through 34.2 s, video RTP stopping at ~33.5 s while ICE consent was healthy
   in both directions (Chrome answered every aiortc consent request and aiortc
   answered Chrome's), and aiortc ceasing to answer ~2 s later — the 2000 ms
   ingress read deadline retiring the lease after compressed frames stopped.
   The player's stop then received 404. No packet loss, NACK or PLI preceded the
   stop. The earlier hypothesis of aioice consent expiry was refuted by these
   counters.
3. CPU was not saturated (runtime ~0.5–0.9 of one core of 12, decoder child
   ~12%, native child ~4%).
4. **Root cause (source evidence):** the official SuperLive Plus client
   (`jadx-full` 1.18.1, `fu3.N1`) schedules `Timer("createMessageTimer")` to call
   `cw3.v5()` every **6000 ms**, which sends the 8-byte N9000 heartbeat
   (`gg0` magic `0x31313131`, length 0) on the device connection; it also runs a
   30 s connection check. The Windows native live loop
   (`windows_socket_worker.serve_live`) sends only the stream-open request and
   never a keepalive, so the recorder ends the stream ~30 s after open. Earlier
   bounded captures (four frames) and earlier continuous runs (failing at
   ~5 s for other reasons) never reached this window.

**Ruling R111 (next step):** add a native keepalive in `serve_live` that mirrors
the official client — the 8-byte heartbeat every 6 s while the original live
task is open, each send behind a fresh `authority.require("send")` and the same
identity checks as the open/close sends, carrying no credentials and leaving
receive policy unchanged. Because `windows_socket_worker.py` is owned by the
native receipt, the change needs an independent native review and a **new**
immutable native receipt before the next device run.

**K1 implementation and review (R111).** `windows_socket_worker.serve_live` now
sends the 8-byte heartbeat (`LIVE_KEEPALIVE`, `LIVE_KEEPALIVE_SECONDS = 6.0`)
first 6 s after a successful open and then on a fixed delay rescheduled from
each actual send (no catch-up bursts), each send behind a fresh
`authority.require("send")` and the `allowed(identity)` check exactly like the
open/close sends; a short write fails closed; buffers are allocated once; the
receive path, limits, `finally` close and `SafeResult` schema are unchanged.
Implementer: 13 new tests RED→GREEN, 313 passed, 0 skipped; Ruff, Ruff format
and strict mypy clean. Root's independent rerun: 313 passed, Ruff and strict
mypy clean. Result of the independent native keepalive review: C0/I0/M0
(receipt eligible). The reviewer verified the bytes and cadence against the
official client source, confirmed that only the three task files changed from
the receipted base, reproduced RED from the frozen base and killed 14 of 15
mutants (the survivor is functionally neutral). Pre-existing watch item: if the
recorder echoes a heartbeat between `og0` fragments, the frozen live codec ends
the session as a codec failure (fail-closed); watch for endings near multiples
of 6 s during acceptance.

**Acceptance with the keepalive (executed 2026-10-04).** Run
`local-devices-06c7327498f845e787824d8dd019f081` used approval
`root-source-approval-c2.json` (`d8365af7…`, 91 sources) and the new native
receipt `source-approved-local-live-service-m3-keepalive.json` (`c54e5eb1…`,
verified against the 14-entry bundle; no SDK call during approval), again with a
controller-launched Chrome over the DevTools protocol and no certificate bypass:

| Item | Result |
| --- | --- |
| Device checks | 8 channels (store 1), 4 channels (store 2) |
| Continuous playback | **Accepted.** Store 1 channel 2 played continuously for about five minutes (sampled to 272 s; lease issued 22:58:38, last heartbeat 23:03:31); the former 29–30 s cutoff did not occur. |
| Two stores concurrently | **Accepted.** Store 2 channel 1 played 81.7 s alongside store 1; both ~10 fps with server-confirmed PLAYING. |
| Rendering | Render probes over 8 s: store 1 72–79 presented of 80 decoded, store 2 78 of 80; luma mean/sd 99.8/33.2 and 128.1/28 (distinct real images). Earlier high "dropped" counts were an offscreen-element artifact. |
| TTL / heartbeat | Browser heartbeats every 10 s returned 200 PLAYING for the whole run; SQL expiry rolled 30 s ahead of the last heartbeat. |
| Stop / reopen | Store 2 stopped and reopened while store 1 kept playing; final stops of both via the UI. |
| Retirement | All four leases `CLOSED` with `cleanup_confirmed=true`, including a rejected simultaneous start. Shutdown: coordinator 0, runtime 0, Next 0, state removed, no retained custody, 0 known private values; no listeners left. |
| Source stability | All 91 approved sources and the private inputs re-hashed unchanged after the run. |

Finding: starting two stores within the same few seconds returned **HTTP 429**
for the second start (the first native start was still in flight); the player
shows a failure and does not retry. Starting a store while another is already
playing works. This is a UX item (retry or queue), not a capacity defect.

**Display proportions (user report).** The user observed that the picture's
proportions looked wrong. Both recorders deliver HEVC 1280×1936 with no
sample-aspect-ratio information (a half-width encode of 2560×1936). The
official app draws into its full live window and only preserves native
proportions when the Local Config switch `sw_original_scale` is enabled
(default off), so by default it stretches the picture to fill the window. The
web panel preserved the 0.66:1 shape (`object-contain`). Ruling R112: fill the
existing 16:9 player box (`object-fill`) like the app's default; an "original
scale" option is a separate parity item.

F1 implemented R112 as a one-token change in `local-live-panel.tsx` with a new
component test (`apps/web/tests/local-live-panel.test.tsx`, RED→GREEN); web
suite 367/367, ESLint clean, `next typegen` + `tsc --noEmit` clean; Root's
independent run of the five live-media web test files passed 17/17. Result of
the task review — display fill review: C0/I0 (one procedural minor: the panel
hash is pinned by the media browser approval, so a new reviewed approval is
required before the visual re-check). Open question: the official app's live
window aspect was not verified; in the 16:9 box the 1280×1936 stream displays at
1.78:1, whereas a true 2560×1936 scene is 1.32:1, so the user's visual check
decides whether the box should be 4:3 instead.

**Visual re-check (executed 2026-10-04).** Run
`local-devices-6bfe84c4179f468c8335280eef4b69ce` with approval
`root-source-approval-c3.json` (`2af6b972…`, 92 sources; keepalive native
receipt reused read-only). Both stores played concurrently again (~64 s and
~60 s; started one after the other, so no 429). Measured geometry: computed
`object-fit: fill`, player box 597×336 (1.778), intrinsic 1280×1936 (0.661).
**The user looked at the live picture and confirmed the proportions now look
right, choosing to keep the 16:9 fill.** Both leases closed with confirmed
cleanup; shutdown exits 0 with state removed, no retained custody and 0 known
private values; all 92 approved sources and private inputs unchanged.

## 6a. Final whole-branch review and fix wave (2026-10-05)

An independent final review of the entire uncommitted change set (24 modified
and 45 new files) returned **Ready to merge — with fixes: Critical 0,
Important 3, Minor 9**. Rulings R114–R117:

| Finding | Disposition |
| --- | --- |
| I1 — a lease revoked before any worker redeemed it could never close (stranded channel, leaked caps) | Fixed in unpublished 0013 on all three paths (revoke trigger, API non-live path, expiry sweep): never-redeemed → `CLOSED`, cleanup confirmed |
| I2 — the revoke trigger rewrote every grant ever, unindexed | Fixed: CTE-scoped grant invalidation, unchanged rows skipped, partial index `local_media_open` |
| R116 — API read path could revive a worker-`CLOSED` lease to `STOPPING` (found during the fix) | Fixed: no `STOPPING` writer touches a `CLOSED` row |
| I3 — per-stream authority-check volume (estimated, unmeasured) | Deferred: production prerequisite; measure tx/s and WAL per stream in the next acceptance |
| M1 watch loop could die on a close exception; M2 20 Hz close retry | Fixed (exception contained; 0.05 s→1 s back-off) |
| M6 player failed on Chrome's transient `disconnected` and on one heartbeat error; R117 | Fixed: fail only on `failed`/`closed`; two consecutive transient misses; 404/403 or STOPPING/CLOSED end immediately |
| M7 missing psycopg URL guard | Fixed |
| M3 decoder pending-map eviction, M4 ICE candidate addresses, M5 lock hold during native login | Deferred with rulings (inference only / production ICE policy / documented) |
| M8 stale docs, M9 missing tests | Docs refreshed here and in the integration guides (the native-receipt-pinned live-session guide waits for the next receipt); tests added for I1, I2, R116, M1, M2, M6, M7 |

Evidence: the fix implementer recorded RED then GREEN for each item. Root's
independent runs: owned SQL suite **29 passed, 0 skipped** with the migration
hash pinned (run `288e51e5…`, 0013 `be9332c6…`, owned database removed, source
unchanged, 0 private values); Python media selection 116 passed; web 22 files /
404 tests passed with typecheck and lint clean. A scoped re-review found **all
findings addressed and no new Critical or Important breakage** (one test-timing
minor). A pre-existing lock-order inversion between close and heartbeat can
deadlock but fails safe as 503 with retry; it joins I3 as a production item.
Because 0013, the worker and the player changed after the device runs, the next
device run needs a new source approval; the device evidence in section 6 was
recorded on the pre-fix revisions.

## 7. Verification limits

No device, browser or network was used for the reviews. Scratch latencies in
review r0 were injected assumptions; the SQL figures above are real
measurements on this machine but with inert statements, not the media
functions. The acceptance runs in section 6 used real devices and real Chrome.
The first run accepted playback, two-store operation, stop/reopen and cleanup
within the first ~30 s of a session and isolated the cutoff; the second run,
with the R111 keepalive, accepted continuous two-store playback (about five
minutes on store 1, 81.7 s on store 2 concurrently), confirming the keepalive
root cause. Limits: two channels on two recorders were exercised, sessions ran
minutes rather than hours, the audio, sub-stream, playback, PTZ and other APK
features remain outside this acceptance, and the display-proportion change
(R112) still needs its own review and a visual re-check. Native result
placeholders in the private staging directory were empty, so no native-side
failure record exists for the earlier cutoff sessions.

## Update log

- 2026-10-04 — Created: W1 wiring and review, independent r0 review,
  real SQL latency measurement, rulings R106/R107.
- 2026-10-04 — P1/L1 fixes, re-reviews (R108–R110), new source approval,
  actual Chrome acceptance run, ~30 s cutoff diagnosis and ruling R111.
- 2026-10-04 — K1 keepalive implemented and natively reviewed (C0/I0/M0), new
  native receipt and approval c2, continuous two-store playback accepted on
  real recorders; user-reported proportions traced to stretch-by-default in the
  official app (R112).
