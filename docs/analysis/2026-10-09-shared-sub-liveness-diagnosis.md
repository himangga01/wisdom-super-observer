# Shared SUB liveness denial diagnosis

Analysis date: **2026-10-09, Asia/Seoul**.

Source baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained uncommitted Stage1,
Stage2 and reviewed R193 changes. Initial `git status --short` confirmed the
existing source/test/report delta; this investigation changed no production
source, tests, Git index/HEAD, database, runtime, native process or browser.
The controller supplied the current frozen source-closure and normal-retirement
results; this agent did not independently inspect private execution files.

Read before reuse: [service report](../service-analysis.md),
[Stage2 plan](../superpowers/plans/2026-10-06-multiview-stage2-shared-recorder-plan.md),
[liveness review](2026-10-04-local-media-liveness-review.md), and
[mux admission guide](../integrations/tvt-local-media-mux-admission.md).
Refresh this report after a new source change or measured first failure. Earlier
startup, raw transport and Stage1 acceptance evidence retains its dated scope.

## Finding and actual evidence limits

**The available evidence does not identify the first terminal cause. No missing
grant-renewal path or fixed startup-expiry snapshot was established by this
source trace. Use the already reviewed bounded schema3 observer before choosing
a fix or changing TTLs.**

Controller-supplied actual evidence: SUB start returned 200 in 3375 ms, offer 200
in 202 ms and PLAYING 200 in 47 ms. Approximately 130 s later, after roughly 26
combined wall/lease heartbeats returning 200, a lease heartbeat returned 404
`LOCAL_DEVICE_DENIED` in 47 ms at the API route-handler phase; source Stop ticket
issuance returned 404 in 109 ms, and wall Stop returned 200. The core startup log had
no exception record. A fresh SUB later rendered 352x240 with advancing time
(16.19 s) and 163 decoded frames. A later MAIN no-signal result is a separate
startup/native investigation and supplies no causal explanation for this SUB
retirement.

The controller subsequently reported original coordinator exit 0/reap, API/worker
settlement, context removal, unchanged frozen sources, private-output checks
clear, and owned database cleanup. PostgreSQL alone remains running. These are
supplied execution/retirement results, not a hardware run performed by this
agent. They do not establish long-duration SUB, MAIN return, twelve-camera or
APK-comparison acceptance.

## Purpose, architecture and implemented renewal

The shared service delivers recorder substreams to OWNER viewers using one
retained recorder transport, immutable channel slots, independent viewer
publication grants, local decode and WebRTC. Wall heartbeat retains transport
and channel authority; lease heartbeat retains the particular viewer lease.
They are separate operations.

| Boundary | Current source behavior and evidence |
| --- | --- |
| Application lease heartbeat | `services/api/src/wso_api/tvt/local_media.py:343` calls `LocalMediaReader.heartbeat`; `packages/core/src/wso_core/tvt/local_media_admission.py:124` maps SQL NULL to 404. `infra/migrations/versions/0013_tvt_local_media_leases.py:207` requires current matching actor/session/scope, NEGOTIATING/PLAYING and LIVE before renewing. |
| Application wall heartbeat | `infra/migrations/versions/0016_tvt_device_media_epochs.py:237` validates wall and every retained master, then renews wall/master/slot SQL expiry; pending focus is not renewed. |
| Worker grant refresh | `packages/core/src/wso_core/tvt/local_media_mux_service.py:1777` redeems the heartbeat, marks a refresh generation, enters the original provider IO barrier, then refreshes/replaces transport, each slot and each viewer grant before reporting success. `local_media_mux_admission.py:2173` snapshots already-renewed SQL expiry, supersedes the old immutable object, and preserves sticky known denial. |
| Native/provider coordination | `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py:236` serializes grant suppliers and IO; `:288` holds that barrier during refresh; `:739` replaces exact grants and renews the original parent/native lifetime. Core current/binding checks wait or retry only a proven same-original refresh generation (`local_media_mux_service.py:1129`, `:2257`). |
| Decoded source and sender | `services/tvt-media/src/wso_tvt_media/mux_source.py:125` reacquires the current executor binding and validates the same handle/registration/cut. `native_source.py:611` obtains a current lease and registration before renewing its independently bounded emission permit; `:745` repeats this every 50 ms. `worker.py:601` refreshes peer expiry each second. `live.py:350` preserves terminal current/expiry fences and the separate 2 s continuous permit-staleness fence. |

The qualified 100 ms call-entry SQL observation contract and independent 200 ms
sender permit remain as approved. Slow eligible success does not make the
reusable cache fresh; known denial remains terminal. No source result here
justifies weakening those contracts.

The first lease-heartbeat 404 proves only that application lease-read conditions
failed at that transaction. It does not distinguish already STOPPING/CLOSED,
lease expiry, grant invalidation, or changed scope/rights/session. Stop ticket
issuance also requires a live NEGOTIATING/PLAYING lease
(`0013_tvt_local_media_leases.py:235`), so its 404 is compatible with the same
already-retired lease. It is not proof of a new native startup error.

Successful preceding heartbeats do not cover later asynchronous decoder,
ingress, authority, pressure, format or peer failures. Those paths can fence the
source and cause subsequent SQL retirement. Current structural diagnostics
wrap only `executor.start` (`scripts/test-local-devices/core_debug.py:187`), so
an empty core log does not exclude those paths. In development observation-off
mode, their existing `FailureObserver` callbacks have no retained sink.

## Minimum next measurement

Priority 1: use the controller's existing reviewed bounded runtime mode with
media observation enabled. The source already composes the schema3 observer,
provider wrapper, `begin_source`, decoded source and peer observer
(`scripts/test-local-devices/runtime.py:1278`; observation enabling predicate
at `:238`). No production diagnostic or policy change is needed for this gate.

Hold one presented SUB with normal wall/lease heartbeats beyond the prior
failure interval, approximately 180–210 s. Avoid HIGH or intentional Stop until
the first failure is saved or that bounded stable window ends; intentional
`explicit_close` can otherwise be the first retained failure. Keep the existing
runtime/observer deadlines and original retirement gates. GPT default Chrome
does not supply the formal original-Chrome/whole-Chrome acceptance receipt.

Retain this exact existing closed projection:

- `source_attempts[].source_attempt`,
  `first_failure.{stage,reason,elapsed_ms}` and
  `milestones[].{stage,elapsed_ms}`. `begin_source` stores the first accepted
  fixed-enum failure only (`scripts/test-local-devices/observation.py:1080`,
  `:1154`). Timestamp metadata and bounded format transitions are available
  under their existing sanitized projections.
- Join `peers[].attempt` to `attempts[].attempt`, then
  `attempts[].source_attempt` to `source_attempts[].source_attempt`. Peer
  counters include `permit_lapse_episodes` and `withheld_datagrams`. Peers do
  not export a direct `source_attempt` field. Use `mux.viewers[].attempt` with
  its viewer/master/slot ordinals for the same join and frame/cleanup evidence.
- Check `observation_failures`, `omitted_attempts`,
  `omitted_source_attempts`, `omitted_peers` and `mux.omitted`; absence of a
  failure row is not useful proof when the projection failed or omitted data.
  Preserve terminal/writer/digest and source/database/original-custody evidence.

| First recorded stage/reason | What it resolves; remaining qualification |
| --- | --- |
| `adapter/timestamp_invalid`, format or queue enum | Selects frame validation, bounded rotation or pressure investigation. It does not imply expired authority. |
| `ingress_read/deadline` or `protocol_invalid` | Selects original read/protocol boundary. Further native evidence may be needed to distinguish missing ingress from a fenced parent. |
| `authority_renew/denied` or `source_current/denied` | Selects collapsed executor/registration authority. It does not identify which SQL predicate or which transport/slot/viewer object failed. |
| `peer_watch/stale_permit`, `peer_check/deadline`, `peer_deadline/invalid_deadline` | Selects sender permit or peer-expiry boundary. Compare preceding source failure, heartbeat intervals and renewal evidence. |
| `worker_lease/denied` or `worker_watch/current_false` | Selects worker retirement trigger, potentially after a prior source/native fence. |

Priority 2 is conditional: if the new first row still says only generic authority
denial, obtain a narrowly reviewed structural measurement of the earliest
transport/slot/viewer/inherited lease observation returning NULL or a local
guard false, together with refresh-generation overlap. Fixed phase/purpose,
relative time and local ordinals suffice; no token, scope value, native identity,
media, exception message or raw SQL row is required. A generic source denial
alone must not be relabelled a proven renewal race.

## Verification and open questions

Executed here: `git status --short`, `git rev-parse HEAD`,
`git branch --show-current`, focused `rg -n` searches and direct bounded reads
of the source/report/plan/guide paths above. No test, synthetic native launch,
SQL query, hardware call or browser operation was performed. Existing focused
refresh/actual-facade tests were inspected as intended coverage; their historical
passes were not rerun or promoted to actual liveness proof.

Open questions: what was the first asynchronous terminal event, how far was it
from the last successful wall and lease renewal, and did an authority failure
precede or follow source/native retirement? Those are execution questions.
Changing TTL, reconnect policy or refresh safety before answering them risks
masking the causal failure and invalidating the approved authority guarantees.

Update log: 2026-10-09 — Created narrow read-only diagnosis from current source
and controller-supplied execution evidence; existing schema3 observation is the
next measurement, with no proven production renewal fix selected.

## Subsequent bounded observation — 2026-10-09

The controller executed the already reviewed observation-enabled runtime on the
same frozen production sources. At this update the runtime remains active and
pinned; this agent changes this unpinned report only. This is supplied actual
evidence, not an execution performed or independently read from private files
by this agent.

Only one SUB was requested; the controller reports no intentional Stop or HIGH.
Source attempt 1's first retained failure is
`{stage: peer, reason: explicit_close, elapsed_ms: 26984}`. Milestones were first
adapter packet at 2562 ms, decoded frame and binding at 3577 ms, peer creation
at 3592 ms, and peer connection at 4015 ms. Attempt 1 joins source attempt 1 and
peer 1. Peer permit-lapse episodes and withheld datagrams were both zero; viewer
1 on master 1/slot 1 observed 245 encoded frames. Bounded Chrome metadata
initially showed time 29.54 s and 231 decoded frames before closure. Media time
and wall-clock elapsed time are different measurements. All supplied omission
and observation-failure counters, including `mux.omitted`, were zero.

**The new first-event time supersedes the earlier approximate 130 s estimate:**
that estimate came from a later controller poll. The measured earliest retained
event is about 27 s. `explicit_close` records that `LocalWebRtcSession.close()`
was called; it does not identify the decision that initiated closure. Later
API heartbeat 404 remains downstream evidence. No permit-staleness failure was
observed before this close.

### Source-supported close-origin gap

Current `LocalMediaWorker` has no `_expire` or `_renew_leases` methods; a focused
repository Python search found neither. The relevant current paths are:

1. `DeviceEpochCoordinator.sweep()` (`local_media_mux_service.py:1947`) can
   fence a master after transport/slot checks, or close an active viewer after
   final coordinator current returns false. `_fence()` is at `:1277`;
   `_close_viewer()` is at `:1214`.
2. `_close_viewer()` calls `MuxSlotViewer.close()`
   (`local_live_mux_provider.py:1144`). That method invokes its exact retained
   retirement callback (`:1185`). The callback from
   `LocalMediaWorker._retain_local()` (`worker.py:173`) requests local cleanup
   and schedules `_close_entry()` with `call_soon_threadsafe` (`:200`).
3. `_close_entry()` (`worker.py:539`) calls the original `peer.close()` before
   source settlement (`:564`). `live.py:464` consequently records
   `peer/explicit_close`, even if the unrecorded initiating decision was an
   upstream coordinator current or fence decision.

This is an implemented, unobserved close-origin chain. It is **not yet proof**
that `sweep`, a particular SQL predicate, grant expiry or refresh caused the
actual close. Other explicit-close paths include startup/signaling failure,
requested Stop and shutdown. The supplied accepted startup/offer/playback and
absence of intentional controls narrow those alternatives.

The worker's ordinary `_watch` path records `worker_watch`, `worker_lease` or
`worker_renew` failure before calling `_close_entry` (`worker.py:628`, `:630`).
Source failure handlers similarly record before stopping, and peer self-fences
record their peer-check/watch reason before scheduled disposal. With no omitted
rows and `explicit_close` as the first event, the Core retirement callback
origin is the leading next measurement. Concurrent event ordering still prevents
calling that inference an actual root cause.

### Minimum further structural measurement

After original runtime retirement and a narrow source review, observe the first
coordinator `_fence` and `_close_viewer` entry **before** they invoke the provider
retirement callback. Preserve the exact original call, return, exception,
barriers, budgets and resources. A fixed allowlisted caller
module/function/source-line projection distinguishes:

- `sweep` master transport/slot denial leading to `_fence`;
- `sweep` pending-versus-active viewer closure;
- heartbeat refresh failure leading to `_fence`;
- explicit executor close, wall Stop, shutdown or startup retirement.

Add only sanitized source/viewer/master ordinals and existing state enums or
booleans: master state, viewer starting/stopping, refresh-in-progress,
grant-expired, and whether the checked grant is the exact current object or
superseded. Do not issue an extra authority check or refresh for logging. Record
the final coordinator current false and the existing transport/slot/viewer
check's observed false/error where needed; a temporary superseded-grant false
during a proven refresh is not by itself terminal evidence.

A trace only at `_close_entry` loses the original synchronous Core origin across
the scheduled callback. Source/peer observer expansion alone would still retain
the same downstream `explicit_close`. If the coordinator result selects SQL
authority, the next narrow step is the already described exact-purpose
observation NULL/local-guard measurement, not a TTL increase.

Approximately 27 s can overlap the initial at-most-30 s authority lifetime
after wall/ticket/setup overhead, but elapsed time alone does not prove expiry.
Confirm the current run's successful wall and lease heartbeat counts and times
before that event. Current source replaces grant objects on wall heartbeat and
renews the native parent (`mux_provider.py:797`); native startup also explicitly
renews its parent after setup (`:618`). No retained fixed 20–30 s startup timer
was demonstrated here.

Verification for this update: bounded reads and `rg` of worker, peer,
coordinator, provider, IPC and observation composition; no tests, database or
hardware operations and no production/test/runtime edits. Open question now:
which coordinator/explicit-close entry initiated the observed 27 s cleanup?

## Repeat evidence and runtime trace plan — 2026-10-09

New controller-supplied source-attempt-1 API aggregates before the first HTTP
failure: three successful wall-route requests, two lease heartbeats, one start,
one offer, one PLAYING, and no source Stop or focus. The wall aggregate does not
distinguish heartbeat from wall Stop and its schema has no event timestamps;
it cannot independently establish the exact preceding wall renewal time.

Source attempt 2 subsequently reached 47 s of actual Chrome playback
(time 47.105 s, 472 decoded frames), with no first failure and all observation
omissions clear. The controller's supported CDP Network observation captured
wall creation, session start, offer, PLAYING, five wall heartbeats and four lease
heartbeats returning 200, with no source Stop, wall Stop or focus request.
**This repeat contradicts an unconditional fixed 30 s expiry explanation on the
same frozen sources.** It does not prove a particular transient false/race or
qualify long-duration acceptance. Both observations belong to the still active,
pinned runtime; this agent changes no runtime or production source.

The minimal proposed next trace is runtime-only, on the original admission and
coordinator instances. It is a plan, not implemented diagnostics:

| Hook | Capture only when | Closed projection and purpose |
| --- | --- | --- |
| Original `coordinator.current` | Final returned false or original exception | Event `COORDINATOR_CURRENT`, result `FALSE`/fixed exception category, caller module/function/line, local source/viewer/master ordinal and relative elapsed time. Observe the final result after the existing refresh retry, not every internal intermediate false. |
| Original `coordinator._fence` | First entry per original master | Event `MASTER_FENCE`, allowlisted synchronous caller chain, existing master state and refresh-in-progress boolean. A sweep callsite selects retained transport/slot checks; a heartbeat callsite selects refresh failure. |
| Original `coordinator._close_viewer` | First entry per original viewer | Event `VIEWER_CLOSE`, allowlisted synchronous caller chain, existing viewer starting/stopping and master-state/refresh booleans. `sweep` lines 1997/2000 distinguish pending and active viewer decisions; the `_fence` chain distinguishes master-wide retirement. |
| Original admission `current_transport`, `current_slot`, `current_viewer` | Returned false or original exception | Event `GRANT_CURRENT`, purpose `TRANSPORT`/`SLOT_RETENTION`/`VIEWER`, result `FALSE`/fixed exception category, caller chain and same local ordinals. Include only existing registered/superseded/denied/expired and refresh-overlap booleans needed to distinguish conservative refresh observations from terminal denial. |

Keep a finite sequence/count and bounded source-callsite projection in the
existing private diagnostics style, with a finite per-original event budget and
explicit omitted/diagnostic-failure counters. Preserve the exact original
method invocation once, exact result/exception, cancellation, caller deadlines,
authority barriers and original resource ownership. Capture failure/close
events only; do not turn per-frame successful current checks into file writes.
No extra SQL/current/renew/close call may be made to collect diagnostics.

Install these instance-scoped wrappers before the executor starts its monitor
or any media request. Retain each original bound method in its wrapper. Leave
provider `binding_for`, `issued_receipt`, viewer `issued_receipt`, native/viewer
issuers and retirement callbacks intact: Core captures and later compares those
methods/objects (`local_media_mux_service.py:709`, `:834`, `:1056`, `:1230`).
Wrapping those protected provider callbacks after capture can itself create an
identity denial and would invalidate the measurement.

Publish the coordinator close/fence entry before invoking the original method,
so its synchronous origin survives the later scheduled worker cleanup. A final
coordinator false combined with the purpose/callsite events distinguishes the
existing `current_viewer -> handle.current -> _original_current` short-circuit
chain without changing it. If admission purpose checks remain true but the
final coordinator current is false, the next selected measurement is the
provider/local original predicate; if a registered current grant check fails,
the next selected measurement is its SQL observation NULL versus local guard.
Neither branch is presently an actual cause finding.

Required narrow verification before execution: original invocation/result and
exception preservation, diagnostic sink failure isolation, finite counters,
closed enum/field rejection, protected callback identity unchanged, and an
inert refresh-overlap control demonstrating that superseded-grant false is
reported with its qualification and never changes retirement. Original runtime
retirement, source review and a fresh immutable closure precede any changed
diagnostic run. No broad test suite or source mutation was performed for this
plan.
