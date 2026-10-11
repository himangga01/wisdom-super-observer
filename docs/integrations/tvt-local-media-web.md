# Local CCTV browser media integration

Date: 2026-10-04 Asia/Seoul. Source baseline: `211d1484aa16eb30f5d362758f149f98dec9dfdf` plus the current uncommitted M3/M4 changes. Read [the service report](../service-analysis.md), [media core](tvt-local-media-service.md), [native session](tvt-windows-live-session.md), [WebRTC](tvt-local-webrtc.md) and [decoder](tvt-windows-decode.md) before changes; update executed evidence in the canonical report afterward.

## Implemented composition

React `LocalLivePanel` opens an explicit selected verified local channel. The Next `/api/live-sessions` proxy enforces the current session, exact origin/CSRF, closed selectors, bounded JSON and25-second combined cancellation. FastAPI `/api/v1/tvt/live-sessions` authenticates before body processing, requires the OWNER tenant entrance and commits a purpose-bound SQL ticket before dispatch. Only the private mTLS worker receives that ticket and bounded signaling data. Device credentials, native indices/GUIDs and media bytes do not pass through these JSON routes.

| HTTP operation | Public input | Worker operation |
| --- | --- | --- |
| POST collection, tenant/connection query | store/device/channel UUIDs, expected generation/inventory revision, default stream | Start with opaque ticket |
| GET lease | tenant query | Scoped SQL view |
| POST lease/heartbeat | Empty object | Exact-session SQL renewal |
| POST lease/webrtc-offer | offer SDP and unique offer ID | One-use Offer ticket |
| POST lease/playing | Positive browser decoded-frame counter | One-use Playing ticket |
| POST lease/stop | Empty object | One-use Stop ticket, original pipeline retirement |

The private pipeline owns one fresh TVT process/socket/task and one decoder per lease. `NativeFrameAdapter` binds exact private generation/session/channel/task values, preserves source microsecond PTS, requires the initial supported keyframe and parameter sets, and validates a conservative single-primary-picture Annex B profile. Only already-decoded RGB frames may be replaced by newer frames for a slow or not-yet-ready browser. One RGB slot and one queued notification bound that backpressure; compressed frames are not arbitrarily dropped.

`LocalMediaWorker` owns a persistent media event-loop thread. Before allocating a decoder or peer, it registers a private retirement barrier with the core lease owner. SQL CLOSED and quota release require both original native closure and confirmed decoder/thread/peer closure. Cancellation of an RPC wait does not discard these original owners. A source/peer cleanup overrun remains pending and is retried against the same objects.

The WebRTC track converts validated RGB to VP8. Empty ICE-server configuration is the current local-test policy; no caller-provided network/file media URL is accepted. API and browser routes do not construct native providers or decrypt credentials.

## Playback state and limits

Encoder admission alone does not mark PLAYING. The browser's actual video-frame callback reports its first presented frame through the authenticated playing route. The worker also requires the original connected peer, at least one actual server-decoded frame, current authority and the native/format/timing proof. This client counter is scoped playback telemetry, not a cryptographic attestation or a new access grant. Root must independently observe actual browser frames/pixels for executed acceptance.

Default media TTL is30 seconds with10-second browser heartbeat. Native orphan expiry and the continuous decoder's at-most5-second inactivity fence are independent. Native capacity is two separate local live owners. Only the source-supported default stream is currently connected; broad quality selection, audio, playback, remote TURN deployment and general multiview capacity are later acceptance work. The initial AU profile rejects reordered source PTS and unsupported multi-picture or multi-slice framing rather than guessing.

## Verification record

Portable checks cover wrong public scope, unsafe counters, private-field rejection, reply correlation, exact auth/CSRF, no automatic retries, late start cancellation, delayed original-source cleanup, browser-receipt gating and SQL retirement ordering. Real inert WebRTC and Windows decoder evidence belong to their separate guides. Guarded media SQL acceptance uses a uniquely owned future database; previous13-case acceptance is historical before the new playing-purpose/barrier extension.

At this document's creation, actual CCTV-to-Chrome continuous playback has **not yet been executed** on this composite source. The owned HTTPS browser fixture is being extended to a separately approved v2 source snapshot. Existing8/4 inventory browser acceptance remains a distinct completed milestone. `MATCHED=0`; `release_ready=false`.

**Acceptance update — 2026-10-04.** Continuous CCTV-to-Chrome playback has since been executed on the real recorders: run `local-devices-06c7327498f845e787824d8dd019f081` (approval c2) played store 1 continuously for about five minutes and store 2 for 81.7 s concurrently, with stop/reopen, heartbeat/TTL renewal, confirmed cleanup and source stability; run `local-devices-6bfe84c4179f468c8335280eef4b69ce` (approval c3) re-checked the `object-fill` display, which the user visually accepted. Evidence: [liveness review](../analysis/2026-10-04-local-media-liveness-review.md) section 6. `MATCHED=0` and `release_ready=false` are unchanged.

## Stage 1 no-signal outcome — 2026-10-05

Source baseline: reviewed Task 3 tree `effd7000ec7221fc91e2dca920485d79178ab1be`,
with earlier uncommitted stage 1 authority and main/sub work preserved. Task 4
adds `LOCAL_DEVICE_NO_SIGNAL` with HTTP 504 to the central local-device failure
table, which the existing RPC validation and API exception handler consume.
The dedicated live proxy and browser client accept only that table's known
code/status pairs from a strict error envelope, reading at most 4 KiB of error
JSON. Unknown codes, mismatched statuses, extra fields, malformed UTF-8/JSON and
oversized bodies cannot supply a detailed code; upstream messages are replaced
with fixed public text. Existing successful JSON limits, session/CSRF scope,
no-store responses, request selectors and error status mappings are retained.

There are two distinct first-frame phases, both with `FIRST_FRAME_SECONDS = 10.0`:

- Native startup: `LiveParentAuthority` starts its bound at the first open ACK
  independently accepted by the existing codec. A valid encoded keyframe must
  arrive before that deadline for readiness and handoff. An ACK without media
  ends as `no_signal`; duplicate ACKs cannot extend the wait. No ACK, correlated
  refusals, cancellation, caller deadline and fresh authority denial keep their
  existing failure reasons. This R131 correction is required because the native
  session already requires frame/proof before `NativeDecodedSource` exists.
- Decode startup: `NativeDecodedSource.start()` starts a separate 10-second
  bound for its first decoded RGB frame. A binding wait begun later consumes the
  remaining time. A frame first produced at the deadline is refused; one at
  9.9 seconds succeeds. A concurrent terminal stop keeps its denial meaning.

The native IPC retains its isolated standard-library import closure. Its 10.0
literal is deliberately separate from the media facade's core constant:
importing `local_service` in that IPC also requires contracts/Pydantic, which
the isolated child does not expose. Neither bootstrap nor dependency scope was
expanded to share the literal.

On either no-signal outcome the original source/native/decoder owners are
stopped and retained until existing retirement confirms closure. A pending
source cleanup continues to occupy its slot. No cleanup confirmation, SQL
CLOSED or quota release is fabricated to meet the timer. The existing total
20-second caller budget can preempt either phase, and original cleanup can add
response latency. These are phase deadlines, not a proven 10-second bound from
the initial browser POST through final resource retirement.

`LocalLiveError.code` and the player's read-only `failureCode` carry the validated
code to the panel. Only `LOCAL_DEVICE_NO_SIGNAL` displays:
**영상 신호 없음 · 채널에 카메라가 연결되어 있는지 확인하세요.**
Other refusal/deadline errors keep the existing generic panel message. The panel
performs no automatic retry or global cooldown; the wall's scheduling policy is
separate Task 6 work.

Executed synthetic verification: full focused media selection plus native
provider contracts **220 passed**; full web suite **443 passed** across 22 files;
panel rerun after the lint correction **5 passed**. Scoped Ruff check/format
cover 9 Python files and strict mypy covers the 5 production files. Web ESLint,
Next type generation and TypeScript no-emit checks passed. Additional final
source rerun and freeze evidence are in the controller's Task 4 report. The
native provider contracts include real inert Windows original processes, and
the new RPC cases exercise real local mTLS with synthetic data; neither calls
the SDK or a device. The API outcome is checked through its real error handler,
and the React panel uses the real client/player against a synthetic response.

No device, browser, database migration, protected input, acceptance runtime,
receipt, approval or parity status was changed by the author. A late I-frame or
slow first decode can intentionally trigger this outcome; actual recorder
timings, multi-tile behavior and eventual resource retirement remain Task 7
acceptance work. Historical playback acceptance above does not accept this
new source delta. Controller must refresh the canonical service report after
independent Task 4 review and before device execution.

## Stage-1 wall stream policy and no-signal UX — 2026-10-05

Task 6 implementation baseline: reviewed Tasks 1–5 tree
`9e508e813d36fca03e3874912d55ec63b7f4bb31`, plus this task's uncommitted
frontend delta. The wall's purpose remains simultaneous monitoring of saved,
verified store/channel inventories; inventory reads themselves do not contact
the device. Read this guide and the canonical service report before changing
the browser media layer, then refresh source and executed evidence afterward.

Implemented browser behavior:

- `LocalLiveBinding.stream` is optional and defaults to `main` at the validated
  start request boundary. The connection panel exposes **고화질** (`main`,
  default) and **저화질** (`sub`), disabled while its player is connecting or
  playing. Existing channel scope, CSRF and failure projection remain intact.
- The wall admits sixteen logical live/starting tiles while keeping starts
  sequential. Grid starts explicitly select `sub`; enlarged starts select
  `main`. Enlarging or returning atomically stops/requeues the affected
  requested channel through the scheduler. The replacement retains its
  original queue ticket and slot priority, including a returning sub start
  refused with busy while an ordinary seventeenth channel waits.
- Player identity still fences stale stream/frame/state events. The original
  Stop promises are retained, and the current player rechecks pending original
  stops before it starts. Ten rapid enlarge/return cycles cancel intermediate
  players and leave the final requested sub player. User stops and terminal
  failures are not revived by navigation.
- Validated `LOCAL_DEVICE_NO_SIGNAL` maps to terminal `nosignal` with
  **영상 신호 없음**. It has no automatic retry or cooldown, releases its
  scheduler slot and permits manual play. Other live tiles remain playing.
  Original native/SQL retirement is still required: a scheduler slot release
  does not establish backend closure or bypass the existing stop barrier.
- Grid/focus quality badges show the selected stream policy. Existing keyboard
  Escape, returned button focus, fit controls and accessible channel labels
  remain covered by the wall tests.

Executed synthetic verification from `apps/web`:

| Command / evidence | Result |
| --- | --- |
| Initial four-file RED run | 15 failed / 52 passed; missing stream selection, capacity and terminal state |
| Full-wall main switch, return, and busy return regressions | Each causally failed before the corresponding queue correction |
| `node node_modules/vitest/vitest.mjs run tests/live-wall-scheduler.test.ts tests/live-wall.test.tsx tests/local-live-api.test.ts tests/local-live-panel.test.tsx --reporter=dot` | Final 69 passed, 4 files |
| `node node_modules/eslint/bin/eslint.js .` | Exit 0, rerun after the final ticket correction |
| `node node_modules/next/dist/bin/next typegen` | Exit 0, generated route types |
| `node node_modules/typescript/bin/tsc --noEmit` | Exit 0, rerun after the final ticket correction |
| `node node_modules/vitest/vitest.mjs run --reporter=dot` | First 455 passed; post-correction run 454 passed / 1 failed; unchanged final rerun 455 passed, 22 files |
| Isolated `tests/tvt-account.test.tsx` rerun | 57 passed |

The recorded intermittent failure was the existing account test
`retains the consumed-image requirement through a delayed same-scope CHALLENGE_EXPIRED recheck`
at `apps/web/tests/tvt-account.test.tsx:99`: a captured password input was not
cleared when the checking status first appeared. No account source or tests
were edited. `LoginForm`'s passive unmount cleanup and the assertion timing are
a plausible explanation, not a verified root cause; this remains a separate
test-stability concern despite the isolated and full successful reruns.

The rapid-switch evidence includes a real `LocalLivePlayer` with synthetic API
results and peer objects. Its initial accepted result is held at the validated
API boundary; a late result receives its original Stop, a concurrent start
gets busy, the final sub attempt plays alone, and unmount retires the last
synthetic lease. Holding fetch itself was rejected as a fixture design because
aborted bounded JSON parsing cannot deliver that late result to the player.
The other fake players retain their synthetic leases until held Stop promises
settle and stop unstarted players without allocating a lease. These tests
exercise scheduler/player lifecycle composition, not recorder resource limits.

No device, real browser, database migration, protected input, acceptance
runtime, receipt or approval was run or changed by Task 6. Actual twelve-tile
playback, main/sub recorder acceptance, focus timing, no-video timing and final
native/SQL resource closure remain Task 7. At this initial Task 6 checkpoint,
the fifteen-second wall start deadline and backend phase deadlines were not a
demonstrated ten-second browser-to-label bound; the R135 correction below
replaces that wall timer. Product questions remain the acceptable focus-switch
latency and treatment of cameras whose first I-frame arrives beyond the
configured bounds. Controller must refresh the canonical service report after
independent Task 6 review; historical playback acceptance does not accept this
new source delta.

### Task 6 review correction I1 — 2026-10-05

UI correction baseline: `8313837f6185c3821eab776eac54c4ab89a2e834`.
Independent review found that an original numeric ticket alone was insufficient
for replacement priority: after requesting18 channels and playing1–16,
focus18 preempts1; returning18 to sub and receiving busy allowed older ordinary
waiter17 to take its slot. This refines the initial Task6 queue evidence above.

The scheduler now retains pending stream replacement priority through busy
refusal, ordered after a queued focused tile and before ordinary ticket order.
Success, manual Stop, non-busy failure or a new manual play releases that
priority. Ordinary waiting order remains stable. No new lease/player ownership
or Stop completion rule was added.

The exact18 regressions first failed **2 cases /49 passed**; corrected scheduler
and wall suites then passed **51 tests /2 files**. Scheduler repeated busy
3s/6s and resumed18 before17, thenpreempted1. The wall held every original Stop,
expired busy cooldown before the refused sub Stop settled, and proved its
replacement did not start until original closure. The other15 players and
their held leases were preserved; subsequent explicit releases admitted17
then1 with16 final synthetic leases.

Fix1 commands from `apps/web` were the focused scheduler/wall Vitest command,
`node node_modules/eslint/bin/eslint.js .`, and
`node node_modules/typescript/bin/tsc --noEmit` (all exit0). One required full
web run, `node node_modules/vitest/vitest.mjs run --reporter=dot`, passed
**457 tests /22 files**. Diff whitespace check passed. The earlier intermittent
account failure remains historical evidence; no account source/test or native
source was changed and no unchanged retry loops were run. Independent Task6
re-review and actual Task7 device/browser acceptance remain separate gates.

### Final composition I1 correction: startup phase clocks (R135) — 2026-10-05

Source baseline: controller tree `ec7fceb844ced9285e6b230cd465e6ff5538824e`
on `codex/superlive-web-service`, HEAD `6436748`. Read-before inputs include
the [final composition review](../analysis/2026-10-05-multiview-stage1-final-review.md),
this guide and the canonical service report. Earlier task changes remain
uncommitted and were preserved. This dated evidence supersedes only the old
generic wall timeout composition; source re-review and device acceptance are
still pending.

The old wall deadline began at logical selection and cancelled the real player
at 15 s, masking a valid typed NO_SIGNAL received at 16 s. The corrected wall
receives optional startup-phase events from the actual `LocalLivePlayer` and
forwards them only while that player is current. The scheduler advances phase
clocks once, in order; duplicate/regressive reports and callbacks from cleared
older phase timers cannot extend or expire the new phase.

| Phase | Trigger | Generic fallback |
| --- | --- | --- |
| Original Stop wait | Logical tile selected | 26 s: client Stop HTTP 25 s plus delivery margin |
| Start request | Immediately before `startLocalLive`, after the original Stop barrier | 26 s: client HTTP 25 s plus delivery margin |
| Negotiation | Accepted lease, before offer creation / ICE | 35 s: ICE 8 s + offer HTTP 25 s + 2 s allowance |
| Presentation / confirmation | Remote description applied | 40 s combined allowance for a presented frame and the playing HTTP confirmation |

The presentation fallback is a combined 40 s limit, nominally allowing 15 s
for a frame plus 25 s for the playing request. It does **not** implement a
separate 15 s first-frame timer. HTTP 25 s, ICE 8 s, backend encoded/decoded
10 s phases and API 20 s remain unchanged. Real successful playback still
requires a presented frame and the server's playing confirmation.

Every fallback is ordinary failure, never inferred NO_SIGNAL. A typed
NO_SIGNAL within the actual request budget reaches terminal `nosignal` without
retry or cooldown. Original Stop promises remain in the wall's barrier even
after a waiting tile times out; retries recheck them. Original player abort,
late accepted lease Stop, current-player event fencing, busy replacement
priority and single retry semantics are preserved. A UI timeout or resolved
client request is not proof of native/SQL closure.

Executed TDD: seven new composed wall/player cases initially failed from
premature 15 s cancellation. One delayed-start assertion was moved before its
now-absent negotiation fixture and independently reproduced the closed-player
failure; the seven then passed after the phase correction. Eight wall cases
and two scheduler cases now cover 16 s typed NO_SIGNAL with one empty-channel
attempt/no retry/no cooldown/next healthy tile, a 24 s Stop wait followed by a
fresh 24 s request, delayed start and negotiation, all stuck phases, bounded
request retry exhaustion, original Stop retention across timeout, late lease
retirement, duplicate/regressive events and old phase timer fencing. The
existing ten rapid focus cycles and exact18 busy replacement cases also pass.

Verification from `apps/web`, 2026-10-05:

| Command | Actual result |
| --- | --- |
| `node node_modules/vitest/vitest.mjs run tests/live-wall-scheduler.test.ts tests/live-wall.test.tsx tests/local-live-player.test.ts tests/local-live-api.test.ts tests/local-live-proxy.test.ts tests/local-live-panel.test.tsx --reporter=dot` | 112 passed / 6 files; an intermediate run was 111 passed / 1 failed solely on the obsolete 15 s constant assertion, removed in favor of timed behavior tests |
| `node node_modules/vitest/vitest.mjs run --reporter=dot` | One full run: 467 passed / 22 files, exit 0 |
| `node node_modules/eslint/bin/eslint.js .` | Exit 0 |
| `node node_modules/next/dist/bin/next typegen` | Exit 0 |
| `node node_modules/typescript/bin/tsc --noEmit` | Exit 0 |

Tradeoff: generic failure detection is longer than the old 15 s timer. A
single logical attempt can consume up to 127 s across all four phase budgets
when each transition occurs just before expiry; retries and queue waits add
time. Timers require the browser event loop to run. The combined presentation
budget can expire during a playing confirmation if the first frame arrives
late. These are bounded client fallback policies, not a latency or cleanup
guarantee. The tests use a manual scheduler clock, synthetic validated HTTP
results and inert peers; real browser timing, transport cancellation, recorder
latency, twelve-tile operation and eventual backend closure remain unverified.

The earlier account-test flake remains historical evidence with an unproven
root cause; it did not recur in this single full run. The WebRTC guide's final
review M1 wording was also corrected to distinguish R133 eligible slow-success
returns from expiry-clipped reusable cache and emission permits. No authority
policy changed. Controller should now obtain the one scoped independent
re-review before source approval and actual Task 7 execution.

Update log: **2026-10-05** — Final composition I1/R135 implementation and
synthetic/static evidence added; M1 wording corrected in the WebRTC guide.
Independent re-review and recorder/Chrome acceptance remain pending.

## Stage 1 BUSY scheduling correction — 2026-10-06, R141

The retired c10 run correctly returned login BUSY429 after R139, but a BUSY
target retaining the first queue ticket repeatedly restarted after global
cooldown and prevented later ready channels from being attempted. Current
frontend source parks each refused target independently for 3/6/12/15 s and
selects the first eligible request in the existing focus/replacement/FIFO
priority order. Other targets becoming LIVE do not reset its BUSY backoff.
BUSY does not consume the ordinary single retry. Generic startup failures
retain R118 global cooldown and the single 2 s retry; NO_SIGNAL remains terminal.

Queued replacements retain their actually freed logical slots. Active tiles
plus these reservations cannot exceed sixteen; a replacement consumes its
reservation when starting, and ordinary requests use only genuine spare slots.
An ineligible focused request never preempts a live player. Stop/all/dispose
and intentional new requests fence/cancel the original BUSY timer. The runtime,
player, original Stop promises, phase clocks and late accepted-lease retirement
are unchanged. Queue position expresses request priority while a parked
target may wait behind eligible later requests.

The [R141 source report](../analysis/c10-busy-scheduler-report.md) records causal
RED and synthetic GREEN, the single full web run and static verification. This
is source evidence awaiting independent review and fresh actual acceptance.
c10 ended exceptionally with one unconfirmed STOPPING lease before its original
worker was terminated; no normal complete lease cleanup is inferred.

429 scope is unknown: device/login limits and global admission/custody fences
share the existing classification. Per-target parking can increase aggregate
rejected attempts during global BUSY. Starts remain sequential, backend
capacity/custody fences remain authoritative, and there is no capacity increase
or device multiplexing. Twelve-tile recorder/browser acceptance remains open.
