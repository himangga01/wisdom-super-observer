# c10 BUSY scheduler diagnosis and proposed R141

Date: 2026-10-06, Asia/Seoul. Status: source diagnosis and proposal only.

## Scope and baseline

Bounded frontend scheduling diagnosis for the approved Stage1 monitoring wall.
The wall requests recorder channels sequentially and keeps up to sixteen native
source/player sessions active. Its React runtime owns current players and the
original Stop promises; the pure scheduler owns intent, ordering and timers.
Native login multiplexing remains outside this proposal.

Root supplied branch `codex/superlive-web-service`, HEAD `6436748`, and the
current immutable c10 closure of 133 source/tool/report paths. The active tree
contains approved uncommitted Stage1/R137/R138/R139/R140 work. No Git command or
independent working-tree-state verification was performed. Existing authority
was read first: `AGENTS.md`, `docs/service-analysis.md`, the Stage1 progress
ledger, `2026-10-06-c9-channel-open-diagnosis.md`, the liveness report's R118
section, and Task6's replacement-priority review. Their c9/source conclusions
remain dated; Root's following c10 observations are newer evidence.

Root reports five LIVE after main/sub focus and ten rapid cycles. Requesting all
twelve added S1 channel1 successfully, then S1 channel6 repeatedly returned
login BUSY429 while it and five later requests remained queued. The reported
observation contains 160 heartbeat 200, twelve start 429, no 502, six LIVE/six
queued, and healthy existing media sources. These are Root-attributed actual
observations, not a runtime reproduction by this author. No twelve-tile
acceptance, cleanup completion, recorder connection ceiling or BUSY scope is
established here.

## Proven frontend mechanism

In `apps/web/src/lib/tvt/live-wall-scheduler.ts`:

1. `fail(id, 'busy')` for a starting tile calls `halt`, then `enqueue(id,
   'resume')`. The original queue ticket is retained, as is replacement
   metadata. The oldest ordinary BUSY target therefore returns before ordinary
   later requests.
2. That branch calls the same global `beginCooldown()` used for other startup
   failures, increasing the global consecutive-failure streak.
3. `pump()` returns during global cooldown. After its expiry it always calls
   `start(queue[0])`; no target eligibility or parking exists.
4. A repeatedly BUSY head cannot spend its ordinary retry and cannot leave the
   queue automatically. Its repeated refusal recreates the same ordering and
   cooldown, blocking all later requests despite spare capacity.

This matches the reported c10 progression. R139 exposed the exact refusal
correctly; restoring generic502 would merely exhaust that tile's retry and
accidentally let later requests run. The classification is not the scheduler
defect and should remain unchanged.

R118 intentionally introduced global pacing after failed-native retirement
caused a rapid429 cascade in c4. Preserve that policy for generic failed starts.
The current BUSY policy lacks fairness when refusal persists at a particular
target. Existing tests explicitly expect the BUSY head to restart before later
targets, so this is a policy correction requiring changed assertions plus new
regressions, not a missing branch covered by current expectations.

`live-wall.tsx` currently maps NO_SIGNAL first, otherwise any429 to BUSY.
It does not know whether a429 is a device/login limit, shared admission limit,
or uncertain retirement. The runtime deletes the old current-player mapping,
retains its original Stop promise, and checks every pending original Stop again
before invoking any new `player.start()`. This barrier must remain unchanged.
`live-tile.tsx` already displays queued BUSY separately and needs no new state
or failure code for this scheduling repair.

## Minimal proposed R141, not implemented

Keep BUSY IDs in their original priority/ticket queue, but add per-ID eligibility
timers and consecutive BUSY streaks. On refusal, park that ID for 3/6/12/15 s
(capped exponent/streak); do not start or extend a global cooldown for BUSY.
Each ID has at most one current park timer. Another target going LIVE must not
reset this ID's BUSY backoff. Successful LIVE for that ID, explicit Stop/new play
or intentional stream replacement clears its old park/streak as appropriate;
duplicate `requestPlay` while queued does not bypass parking. BUSY continues to
preserve the separate one automatic retry for an ordinary failure.

`pump()` chooses the first time-eligible, slot-admissible ID in the existing
queue: eligible focus first, eligible replacements next, then ordinary FIFO
by unchanged tickets. A timer expiry only makes its ID eligible and pumps;
it does not cancel the current starting player or override priority/capacity.
No clock API is needed: presence of the current fenced timer means ineligible.
After all requested IDs are parked, wait for their finite timers rather than
spinning. Retry attempts remain automatic while requested, with finite positive
capped delays; this proposal does not add a terminal BUSY-attempt limit.

Skipping parked replacements also requires explicit logical slot reservation.
Queue priority alone currently protects that slot. Keep a `heldSlots` set for
queued replacements that actually freed/owned an active slot, including a
replacement that becomes BUSY. Do not reserve a slot merely because a never
started ordinary queued tile receives replacement metadata. Maintain
`activeCount + queuedHeldSlots <= capacity`; an ordinary target needs genuine
unreserved capacity, while a held owner consumes its own reservation atomically
when starting. Preserve reservations through BUSY; release on success,
non-BUSY failure/no-signal, Stop, and replacement cancellation. Thus fifteen
LIVE plus one parked replacement does not admit ordinary channel17 into its
slot; genuine additional spare slots may admit other ready targets. Stop/requeue
of an existing active replacement transfers its slot within the same transaction.

Only an eligible focused target may cause preemption. A parked focus must not
stop a healthy player, and a focused target with a held slot must use that slot
without stopping an additional live player. Preserve current stream selection,
current-player fencing, effect order (`onStop` before the next `onStart`), one
starting ID, capacity16, original Stop custody, and startup phase/attempt clocks.

Keep generic failed-start global cooldown and its 2 s single retry, terminal
NO_SIGNAL semantics, and live-failure handling. Stop one/all and runtime dispose
must clear park timers/reservations and fence already dispatched callbacks by
their exact pending identity, so old callbacks cannot revive stopped/new attempts.
`busy` continues to mark queued refused IDs; `coolingDown` denotes only the
remaining global generic-failure hold. Existing queue-position text represents
priority among requests, not a guarantee that a parked ID starts next.

## Tradeoffs and remaining questions

A global429 episode can cause one sequential sweep of ready targets before
their individual delays apply; aggregate rejection frequency can exceed the
current one-head/15 s cadence. This does not bypass backend admission, caps,
uncertain-custody fencing or original Stop settlement. It avoids assuming the
scope of429 without adding backend codes, details, device grouping or media
changes. A separate global BUSY reason/cadence is a later option only if new
actual evidence requires it; it is not needed to remove the demonstrated head
starvation. Recorder connection/session limits and other clients remain unknown.

Reserved replacements intentionally prevent ordinary targets using their last
slot while parked. This is required by the already reviewed full-wall focus
contract; tests must also prove that unrelated genuinely free slots can progress.
Fairness permits ready requests to start; it cannot establish that every
recorder accepts twelve per-tile logins. Stage2 multiplexing remains separate.

## Targeted RED proof for the later author

1. Capacity 16, six existing LIVE; S1 ch6 BUSY, S1 ch7/8 and S2 ch2/3/4 ready:
   later targets start sequentially while ch6 is parked, and repeated ch6 BUSY
   cannot keep S2 queued. Tickets remain stable among eligible ordinary IDs.
2. Two independent BUSY IDs: each retries at 3/6/12/15 s; another ID's LIVE
   does not reset their streaks; timer expiry during a pending start never
   creates parallel starts. All-BUSY input has no immediate retry loop.
3. Full sixteen-slot wall with eighteenth-channel focus return: its BUSY
   replacement keeps its slot ahead of older 17 and preempted 1. With a separate
   genuine spare slot, ready ordinary work progresses without stealing the
   reserved slot. Multiple reservations keep total accounting bounded.
4. Parked focused target causes no preemption; once eligible it preempts only
   when needed. A reservation-owning focus never preempts an extra live player.
5. Mixed BUSY and generic failure: generic global hold remains, ordinary retry
   is still single 2 s, BUSY never consumes it; NO_SIGNAL remains terminal and
   releases reservation with no retry/cooldown.
6. Stop one/all, dispose, manual play and stream changes cancel/fence old
   park timers. Already dispatched stale timer callbacks cannot restart IDs.
7. React integration: parked BUSY permits another eligible player to be
   created, but held original Stop keeps its HTTP start blocked. Releasing
   that original Stop starts only the current player; existing fifteen
   players, late lease cleanup and phase clocks remain intact.

Revise existing BUSY-specific global-cooldown assertions. Preserve and rerun
the existing generic cooldown, held original Stop, eighteen-channel replacement,
rapid-focus, NO_SIGNAL, startup-phase and mixed invariant regressions. Execute
no recorder/browser reproduction until Root retires c10, rules on R141 and
creates fresh source review/receipts/approval after implementation.

## Verification and handoff

Executed here: read-only `Get-Content`, bounded `rg`, path existence and
`Get-FileHash`. No tests, SDK, SQL, browser/RPC/device, Git, source edits,
existing report edits, receipt edits or helper edits occurred. New documentation
is outside the supplied c10 pinned closure; Root owns canonical report/ledger
and AGENTS updates after retirement. This supplemental report is linked from
the local Stage1 plan note; existing canonical authority remains
`docs/service-analysis.md`.

Inspected SHA256 baseline:

| File | SHA256 |
| --- | --- |
| `apps/web/src/lib/tvt/live-wall-scheduler.ts` | `ac8a330591415b9961fd7b8a7f0bd1a0de964f89d3e0cf98fed9e614a638b129` |
| `apps/web/src/features/monitoring/live-wall.tsx` | `74b5d68ddb789fe1978a6660ad6ca459b55af9ca5c740ea3016d5b3f1d793617` |
| `apps/web/src/features/monitoring/live-tile.tsx` | `1afb99b068b17cc8dc8a2936ba8069841c8301b0a785a35f92a2d471af68ef22` |
| `apps/web/tests/live-wall-scheduler.test.ts` | `8d02fd31a7e5bdd4e88b4eb432ac1299b11204bc480e1d32ac0b2a0985be8b8d` |
| `apps/web/tests/live-wall.test.tsx` | `82a29914493727635cb312599622124f5288d3719536e5f28fae37ff3b81db19` |

Update log: 2026-10-06 — Read current approved sources and historical R118/Task6
evidence; recorded Root-attributed c10 results and a bounded frontend proposal.
No repair or repaired acceptance is claimed.
