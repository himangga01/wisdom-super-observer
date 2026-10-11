# Multi-view stage 1 final composition review

Analysis date: **2026-10-05 (Asia/Seoul)**. Review round: **r0**.

**Spec: changes required in the composed startup outcome. Quality: changes
required before the final source gate. Open findings: Critical 0 / Important 1 /
Minor 1.** I1 is a reproduced client composition defect. M1 is an inaccurate
authority-contract statement. No further actionable finding was identified in
the reviewed scope. This is a source review, not twelve-tile device acceptance.

## Baseline and scope

- Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
- Branch: `codex/superlive-web-service`; HEAD:
  `6436748f37c799fd14ce03e1d72c86c79eda6b0f`.
- Approved plan start: `6436748`. Frozen review tree:
  `aa734a38476ea8727d66148cdee3829004877bf5`.
- Package: `.superpowers/sdd/2026-10-05-multiview-stage1-plan/review-stage1-final-r0.diff`;
  57 paths, 12,813 UTF-8 lines; SHA-256
  `1cc9cab98d0261094b5822ead94740288aef55bb3bf10ea57e696d280c615c8b`.
- Initial checkout contained the uncommitted Tasks 1–6, migrations/tests,
  R131/R132/R133 corrections, R134 observation and its terminal-write fix, and
  controller documentation. No index, history, source or receipt was changed by
  this reviewer. Only this requested report was written.
- Read the complete supplied diff in bounded segments. Direct Git-blob versus
  filesystem comparison, normalizing CRLF, covered all 57 paths. Implementation,
  tests and integration guides match the frozen tree. Three controller handoff
  files changed during review: `AGENTS.md`, the reboot handoff and
  `docs/service-analysis.md`. Their continuation updates are outside the frozen
  implementation claim; no source drift was found.

Read-before inputs were the shared analysis policy, worktree `AGENTS.md`,
[service analysis](../service-analysis.md), supplied final brief and constraints,
approved plan, ledger, affected integration reports, and
[combined native review](2026-10-05-multiview-stage1-native-review.md). Task 6's
existing timeout qualification and the observation fix1 re-review were checked.
Earlier continuous-media commits are unchanged, previously reviewed context.
No broad historical SDK/ABI/APK audit was performed.

The controller maintains the canonical report pointers in `AGENTS.md` and the
service report. Later work should read this report before corrections, preserve
its dated findings, and append the scoped correction/re-review and actual
acceptance evidence afterward.

## Purpose, architecture and implemented composition

The service exposes authorized local-recorder video to the OWNER browser. The
stage-1 goal is the two-recorder 8+4 monitoring wall, using sub streams in the grid
and main on focus, with explicit no-signal outcomes and measured resource use.
One native login/socket/process and one first task remain owned per tile.

The API issues a protected SQL ticket, then dispatches through mTLS to the media
worker. Native startup retains original process/socket/generation and validates
fresh inventory, live permission, stream selection, acknowledgement and first
keyframe before handoff. Decoded sources feed the existing WebRTC path under
bounded authority observations and emission permits. Original native, decoder,
peer and SQL retirement still determine cleanup; UI state and telemetry grant
neither authority nor cleanup confirmation.

| Area | Source assessment and limits |
| --- | --- |
| Authority and clocks | `local_media_admission.py:392` implements a per-lease call-entry bound, one in-flight observation, sticky denial, waiter isolation, close/shutdown fencing and independent public model copies. Registry/condition locks do not span SQL. Freshness uses the injected clock; waiter liveness uses real monotonic time. Ordinary cache reuse is expiry-clipped. R133 slow-success semantics remain intentional. |
| SQL observation and caps | Migration 0014 adds the non-locking observation path with restricted execution grants; transitions/startup retain locking authority. Migration 0015 changes only actor/global admission caps to 16/64 and restores the original issue body on downgrade. Migration 0013 matches plan-start source. These source conclusions do not replace PostgreSQL execution. |
| Pool and startup reservation | `local_media_admission.py:44,199,267` reserves eight long startup transactions before checkout from the 8+8 pool. Cancellation/deadline polling and settlement-before-semaphore-release are preserved. Eight slots remain unavailable to long startups; arbitrary stalled short work can still exhaust finite resources. |
| Stream/proof interfaces | `local_live_provider.py:39,195`, `windows_socket.py:343,1168`, `windows_socket_worker.py:1505,1759` and `local_live_ipc.py:202` carry and validate main/sub and integer stream 1/2. Both ends independently parse original envelopes. Validated source kind must match selection. Original first-task, generation, channel, proof and keyframe custody remain. |
| ACK/refusal | `local_live.py:454` accepts the pending 1281/1285 ACK with sequence/lifecycle/generation checks. The advisory oz0 warning cannot grant success. Class-3 refusal remains task-correlated under R129; the child forwards the exact envelope and the parent derives the failure independently. Busy/refusal/protocol outcomes remain distinct. No new APK or recorder fidelity claim is made. |
| Native registry and capacity | `windows_socket.py:984` provides short snapshot/append/confirmed-identity-removal operations. All production registry access uses that interface. Health checks, process polling, SQL, callbacks, waits and cleanup occur outside the registry lock. The serialized startup path retains the shared bounded attempt/custody wait and capacity 16. The prior confirmed-predecessor race remains corrected. |
| Media and RPC capacity | `worker.py:29,119,149` checks capacity 16 before and after asynchronous proof work; retained sources still occupy slots. `runtime.py:827` configures RPC capacity 32. Actual recorder limits and CPU/memory sizing remain unverified here. |
| Emission | `native_source.py:274` anchors permits at call time minus F and clips them to lease expiry. Older completions cannot shorten newer permits; stop clears them. Optional counters in `live.py` do not reevaluate predicates or change emission decisions. |
| First-frame phases | `local_live_ipc.py:318,383` bounds ACK-to-first-keyframe at 10 s; `native_source.py:226,431` separately bounds first decoded frame at 10 s. Cancellation, caller deadline, authority and correlated refusal precedence remain. These are phase limits; neither promises whole-request retirement within 10 s. **The wall's earlier generic timer breaks outcome composition: I1.** |
| Error projection | The central failure table includes NO_SIGNAL/504. Existing RPC/API validation consumes it. `local-live-proxy.ts` and `local-live-api.ts` bound error bodies to 4,096 bytes, require the closed envelope and known status/code pair, and replace upstream text. Player/panel/wall consume the validated code. |
| Wall scheduling | Sixteen logical slots, sequential starts, explicit sub/main selection, current-player event fencing and the original-stop barrier compose correctly in the reviewed normal paths. Replacement priority persists through busy, including the 18-request case, while ordinary order is preserved. An actually delivered no-signal outcome is terminal without automatic retry/cooldown. I1 prevents some valid outcomes from reaching that branch. |

Paths in the table are relative to the corresponding core, bridge, media or web
source directories shown in the supplied diff. Exact defect paths follow.

## I1 — The 15-second wall timer masks a valid no-signal result and retries it

**Severity: Important. Correct before the final source gate.**

Primary locations:

- `apps/web/src/lib/tvt/live-wall-scheduler.ts:28,226,236,263`.
- `apps/web/src/features/monitoring/live-wall.tsx:201,230,239`.
- `apps/web/src/lib/tvt/local-live-player.ts:50,74`.

The scheduler arms its generic 15-second timer when a logical start is selected.
It includes any original-stop wait and the entire player startup. On expiry it
calls `fail(id)` with the default generic kind, gives the tile an automatic
retry and begins global cooldown. The wall removes and stops that player;
`LocalLivePlayer.stop()` sets `ended=true` and aborts its request. Its later
failure catch deliberately ignores results once ended.

That timeout is earlier than legitimate outcomes from the composed backend.
The API permits 20 seconds (`services/api/src/wso_api/tvt/local_media.py:37`)
and the client request permits 25 seconds (`local-live-api.ts:51`). R131 starts
the encoded no-signal clock at the accepted ACK, not at the browser click.
For example, an ACK at t=6 followed by no keyframe produces NO_SIGNAL at t=16,
inside the 20-second caller budget if original cleanup settles promptly. A
decoded phase following a later valid keyframe can also cross t=15. These are
source-permitted timelines; their occurrence on the real recorders was not
measured in this review.

### Focused reproduction executed in this review

An in-memory Node probe transpiled and loaded the actual scheduler and actual
`LocalLivePlayer`. It used a manual scheduler clock, an inert peer and a pending
synthetic start API result. It requested `empty` followed by `healthy`, then
delivered `LocalLiveError(504, 'LOCAL_DEVICE_NO_SIGNAL')` at t=16. No source file,
network, SDK, database, service or browser was used.

| Time | Actual observed client result |
| --- | --- |
| t=0 | `empty` starts; `healthy` waits. |
| t=15 | `empty=failed`, `retrying=['empty']`, `coolingDown=true`; original player is stopped. |
| t=16 | The real player's late NO_SIGNAL error is ignored; state remains generic failed with retry pending. |
| t=18 | `empty` starts again. `healthy` is still queued. |

The probe asserted those outcomes and exited 0. It establishes the client-side
failure mechanism; it does not claim an actual recorder emitted this timing.
This makes the previously recorded Task 6 timing risk actionable: a valid typed
no-signal outcome can become generic failure, automatic retry and global delay,
contrary to R124/RF5. The same timer can cancel an otherwise valid slower start.

### Required correction and regression scope

Align the wall timer with the existing bounded stop/start/signaling phases.
Do not let the generic wall timer expire while the separately bounded start
request can still return its legitimate typed outcome. Account explicitly for
the original-stop barrier, starting request timing when the request actually
begins, and preserve a bounded negotiation/presentation fallback after startup.
Preserve caller-deadline precedence, current-player fencing and late-result
cleanup. Do not infer NO_SIGNAL from a generic client timeout, extend the native
10-second phase constants, or release original custody to meet a UI deadline.

Add focused regressions for a typed no-signal result after t=15 but within the
request budget, a valid delayed start/negotiation, and time spent behind an
original held Stop. The no-signal regression must assert one attempt, terminal
`nosignal`, no retry/cooldown, and progress of the next queued tile after the
existing cleanup barrier. Existing rapid-focus and busy-replacement behavior
must remain intact. A scoped independent re-review of this correction is needed.

## M1 — The WebRTC guide contradicts R133 slow-success semantics

**Severity: Minor. Documentation-only correction.**

`docs/integrations/tvt-local-webrtc.md:368–369` says that a gate answer is
“never … past the lease's expiry.” The implemented and explicitly accepted
contract at `local_media_admission.py:392` allows a successful in-flight result
to answer its runner/eligible waiters even if response latency crosses expiry.
`test_local_media_authority_gate.py` explicitly preserves that behavior. The
media-service guide and native r1 review already describe it accurately.

Replace the absolute return-time claim with the distinction between
expiry-clipped ordinary cache reuse, eligible slow successful observations, and
the independently expiry-clipped emission permit. State that 100 ms is a
call-entry observation bound, not a return-time freshness guarantee. No authority
code or new execution test is required for this wording correction.

## Observation, privacy and source-approval mechanics

R134 is default off and requires both media-browser and observation activation
in the Python fixture (`runtime.py:135`). API/worker environment propagation is
explicit. The Node coordinator enables its own and Next identity publication
only in the requested media observation mode. Acceptance must keep TRACE unset.

`observation.py:103` uses current-self identity, or the synchronously waiting
original Node parent, with exact creation FILETIME represented as a decimal
string. It cannot establish Chrome/PostgreSQL identity; those still need the
controller's original retained handles. Metadata failure is explicit and cannot
satisfy process measurement admission.

`observation.py:157,294,366` projects validated media kind, codec, dimensions and
the parent's advisory warning, retaining only bounded attempt/peer rosters and
private in-memory correlations. No raw media, SDP, credential digest or
device/session/channel/task identifiers are emitted. The provider returns the
exact original session and preserves its original failure/cleanup path. Counts
measure observed lapse episodes and actual withholding, not all physical permit
expiry events, decoder drops or browser drops.

The terminal fix composes correctly: `observation.py:229,262` separates writer
snapshots from the custodian's sticky terminal decision. A late snapshot cannot
replace FAILED after the 200 ms join bound. `complete_observation` at line 73
requires COMPLETE, settled writer, zero failures/omissions and the exact summary
digest. The worker writes that decision after original server retirement;
`runtime.py:1068` reads it after original worker settlement and preserves it in
the durable resource result before auth-state deletion. Observation completion
does not replace resource/source/privacy or actual-video acceptance. The separate
observation fix1 reviewer also recorded C0/I0/M0; no duplicate race probe was run.

Receipt checks performed here were read-only hash/source comparisons:

- The controller's LIVE receipt SHA-256 is
  `be556205bc41a47a0c996fb5bc71582225e730ba0ffdd45e2cd0c8bd96a99143`, matching
  the new constant in `windows_socket.py:44`. All three codec/test/guide files
  and its frames dependency match. Its pinned native-review report digest also
  matches. Its qualified status and false actual-substream/multiview/release
  flags remain explicit.
- The supplied native receipt copy SHA-256 is
  `0aa9317e484582dfb43bf4201ce2efa737b367c8257219590aa358fde70c7d03`.
  Its exact six-key schema, 12 OWNED files and 14 dependencies have no hash
  mismatch, and its source counts are C0/I0/M0. `verify_review` checks the LIVE
  receipt and dependencies before native execution. This reviewer did not load
  SDKs, inspect credentials or repeat the controller's private ACL/bundle checks.
- `runtime.py:204` checks explicit media approval, private source bindings and
  every supplied source hash. Its minimum MEDIA_SOURCES list covers the new
  observation helper/test and migrations, but omits monitoring-specific paths.
  The prepared controller `create-c6-approval.py` was inspected for this concrete
  closure question: it adds changed/untracked stage-1 paths, native closure,
  reports and six observation/owner helpers. Thus it includes the changed wall
  implementation/tests. The borrowed before/after snapshot also covers web
  source. This minimum-list omission is not an additional finding for that
  prepared gate; the actual c6 artifact has not been created or accepted here.
  Hash recalculation alone is never an independent review of a changed source.

The controller must create and validate c6 only after I1's scoped re-review and
M1's correction, using the resulting source closure. No approval or receipt is
issued by this report.

## Evidence, qualifications and remaining acceptance

Reviewer-executed work: branch/status and bounded source/diff reads; targeted
unchanged timeout, registry and approval-interface reads; the single inert
15/16/18-second client reproduction; all-57-path frozen comparison; LIVE/native
receipt source checks; and read-only SQL receipt inspection/hash comparison.
No test suite, actual SQL, SDK, recorder, acceptance runtime, browser or private
credential operation was executed. No subagents were created.

The controller SQL receipt for run `df37f981d8ff466f8edc0a13d3792509` reports
47 tests / 0 failures / 0 errors / 0 skipped, exit 0, original child reaped,
owned database cleanup, source database unchanged and zero known private
occurrences. All five receipt source hashes match the current migrations,
admission module and SQL tests. These are inspected controller execution results,
not a new SQL run by this reviewer. Earlier task synthetic/static counts likewise
remain attributed historical evidence.

Accepted qualifications remain:

- R133 denied authority entries can accumulate for the admission/process
  lifetime after distinct sealed closed tokens are re-queried following tombstone
  eviction. The registry has no configured cap; 64 tombstones do not bound it.
- Slow successful in-flight authority results may cross expiry at return.
  Ordinary reusable cache and downstream emission permits remain clipped.
- The two first-frame phases and the 20-second caller budget retain their
  separate meanings. Original cleanup can add response latency. I1 is the
  client composition defect; these approved native contracts are not withdrawn.
- Existing isolated runtime **88 mypy errors**, Ruff **I001** and formatting
  debt remain qualified; no whole-runtime static pass is claimed.
- The existing account test had an intermediate 454/1 web-suite result followed
  by passing isolated/unchanged full reruns. Its root cause remains unproven;
  this review does not erase it or certify test stability.

Priority order: one controller fix wave for I1/M1; focused verification and scoped
independent re-review; final source/approval binding; then the actual Task 7
one/four/twelve-tile recorder and Chrome gate. Open product/execution questions
are real substream kind/format/warning/refusal behavior, first-I-frame and focus
latency, recorder connection limits, five-minute simultaneous operation, SQL/WAL
cost, CPU/memory, browser dropped frames, permit withholding and confirmed
original resource cleanup. Source capacity constants do not establish any of
those measurements. Full APK parity and release readiness remain unaccepted.

Update log: **2026-10-05** — Final whole-stage-1 r0 composition review completed;
I1 reproduced using the actual client classes, M1 identified, source/receipt
closures checked, C0/I1/M1. Implementation corrections and scoped re-review are
pending.

## Independent final fix1 re-review — 2026-10-05 (Asia/Seoul)

**Current verdict: spec compliant with R135; quality approved for the final
stage-1 source composition gate. Final open counts C0/I0/M0.** I1 and M1 are
resolved. This verdict supersedes r0's changes-required conclusion; the r0
findings and reproduction above remain historical evidence. No additional
actionable defect was found in the correction's scope. Actual recorder/Chrome
acceptance and c6 issuance remain separate controller work.

### Reviewed baseline and scope

- Fix BASE: `ec7fceb844ced9285e6b230cd465e6ff5538824e`.
- Frozen fix tree: `f9a872b93e0fed32b962648439fcb6f815a1c0c8`.
- Package: `.superpowers/sdd/2026-10-05-multiview-stage1-plan/review-stage1-final-fix1.diff`;
  all 963 lines and eight supplied paths read.
- Package SHA-256:
  `d83798776e79d0cb955255c9851ddfbcf5635840871f306a1c2fc9556d0539ac`.
- Direct frozen Git-blob versus current-file comparison, normalizing CRLF,
  confirmed all eight paths match. Controller service/handoff/report updates
  are excluded from this implementation delta.

Read the author report `task-7-final-fix-report.md`, r0 I1/M1 and the ledger's
R135 ruling/clarification. This was a scoped correction review, without repeating
the whole stage-1 audit, earlier receipt checks or suites. The eight paths are
the wall runtime, scheduler and player; two wall test files; the web/WebRTC
integration guides; and the approved stage-1 plan's R135 addendum.

### I1 — resolved by bounded startup phases

`apps/web/src/lib/tvt/local-live-player.ts:31,44,53` now emits optional startup
phase events at the actual operation boundaries: immediately before the start
HTTP call, after a lease is accepted and before offer/ICE work, and after the
remote description is applied. The last event is suppressed after termination.
The existing playback states and presented-frame/server-confirmation path still
determine LIVE; a phase event supplies no playback or access authority.

`apps/web/src/features/monitoring/live-wall.tsx:215` forwards these events only
from the exact current player. The existing original-stop set and repeated
barrier check remain intact. The request event occurs after that barrier, so
24 seconds spent awaiting an original Stop does not consume the new request's
own budget. Timing out a waiting replacement does not erase an original Stop
promise; a retry still waits for the retained barrier.

`apps/web/src/lib/tvt/live-wall-scheduler.ts:30,233,402` implements R135:

| Phase | Budget and anchor |
| --- | --- |
| Original Stop wait | 26 s from logical selection. |
| Requesting | 26 s from the real player's start-request event. |
| Negotiating | 35 s from accepted lease, before offer/ICE work. |
| Presenting | Combined 40 s from remote-description completion through frame/playing confirmation. |

Each transition advances its phase rank. Duplicate or regressive events cannot
rearm a deadline. A deadline callback captures both attempt and phase and must
still match the current starting attempt before failing it. Thus a callback
already dispatched from a cleared earlier phase cannot expire a later phase,
and a previous attempt cannot expire a replacement. Halt and LIVE remove the
phase state. Missing phase events retain the finite prior-phase fallback.

The prior I1 timeline is corrected in source: a NO_SIGNAL result at t=16 arrives
before the request fallback, reaches the real player's existing failure-code
path, and becomes terminal `nosignal` with no retry or cooldown. Generic phase
expiry still produces generic failure; the implementation does not infer a
server no-signal condition from a client timeout. The existing late accepted
lease branch still stops that exact lease without negotiating or reviving its
ended player. Busy replacement ordering and single-retry behavior are unchanged.

The added tests target the reproduced mechanism and the correction's risks:

- `live-wall.test.tsx:152` drives the real wall/scheduler/player with a typed
  t=16 response, requires one empty-channel attempt, no retry/cooldown, and the
  next healthy channel reaching LIVE; further timer advancement does not retry
  the no-signal channel.
- `:164,173` cover delayed start/offer/presentation and a held 24-second Stop
  followed by a fresh 24-second request.
- `:185,203,211` cover finite request/negotiation/presentation fallbacks,
  request retry exhaustion, exact late-lease Stop and preservation of the
  original Stop barrier across a wait timeout and retry.
- `live-wall-scheduler.test.ts:318,332` exercise duplicate/regressive phase
  reports and already-dispatched old deadline callbacks. The actual attempt
  and phase guards also cover stale callbacks after replacement.

These assertions provide appropriate regression coverage. Their HTTP results,
peers and scheduler clock are synthetic; they do not measure actual HTTP/ICE,
heartbeat, device timing or backend retirement.

### M1 — resolved without changing authority policy

`docs/integrations/tvt-local-webrtc.md:369` now states that 100 ms is a
call-entry observation bound, not return-time freshness. It distinguishes
expiry-clipped ordinary cache reuse, R133 eligible successful in-flight returns
that can cross expiry, and independently clipped downstream emission permits.
The inaccurate absolute past-expiry assertion was removed and a dated update
records the correction. No authority code changed.

### Evidence and retained limits

Reviewer execution was limited to read-only diff/source inspection and the
eight-path frozen comparison. No additional probe was needed because the
correction and new regressions directly address the r0 reproduction. No suite,
SQL, SDK, device, runtime, browser, private credentials, source/receipt write,
Git index/history change or child-agent delegation occurred. Only this report
addendum was written.

The author reports seven causal RED wall/player cases, then 112 focused passes
across six files, one full run of 467 passes across 22 files, and successful
ESLint, Next type generation, TypeScript and whitespace checks. These remain
author-executed results; the reviewer did not rerun or independently reproduce
their counts. The intermediate obsolete 15-second constant assertion was
replaced by a timed 26-second Stop-wait behavior test. Historical account-test
flakiness remains unproven and is not erased by this passing run.

R135 explicitly accepts longer generic failure detection: one attempt can
approach 127 seconds across all four phase budgets, with retries, cooldown and
queue waiting adding time. Timers require the event loop to run. The 40-second
presentation phase is a combined fallback, not an independently enforced
15-second frame timer, and can expire during confirmation after a late frame.
HTTP 25 s, API 20 s, ICE 8 s and native first-frame phases 10 s remain unchanged.
This preserves legitimate in-budget typed results without promising ten-second
browser-to-label latency or native/SQL cleanup timing.

All r0 qualifications outside I1/M1 remain: R133 lifetime denied-registry memory,
slow-success authority semantics, runtime 88/I001/format debt, historical source
versus actual acceptance distinctions, and unmeasured twelve-tile resource and
recorder behavior. The controller may now bind the corrected reviewed closure
into c6 and proceed to its separately authorized Task 7 execution. This source
verdict grants no actual-video, parity or release-readiness claim.

Update log: **2026-10-05** — Independent scoped final fix1 review completed;
I1/M1 resolved at frozen tree `f9a872b93e0fed32b962648439fcb6f815a1c0c8`,
final source composition approved with C0/I0/M0 and the stated R135 tradeoffs.
