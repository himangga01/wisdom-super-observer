# R141 BUSY target scheduling implementation and verification

Date: 2026-10-06, Asia/Seoul. Status: implemented, synthetic/static gates passed,
frozen for independent source review; actual repaired playback unverified.

## Scope, baseline and current evidence

The Stage1 `/monitoring` wall opens one native login per tile, serializes starts,
and supports sixteen active slots. The scheduler owns request intent, priority
and timers; the React runtime/player own original Stop promises, current-player
events, request/negotiation/presentation phases and late accepted-lease cleanup.

Read-before authority: shared analysis policy, worktree `AGENTS.md`, canonical
`docs/service-analysis.md`, Stage1 ledger, R118 liveness evidence, Task6 review,
and [the c10 diagnosis/proposal](c10-busy-scheduler-diagnosis.md). Root supplied
HEAD `6436748` on `codex/superlive-web-service`, with approved uncommitted Stage1
and R137–R140 changes. No Git command or independent whole-tree status inspection
was performed. The diagnosis records the original five frontend hashes.

Root's actual c10 evidence established six LIVE and six queued: S1 channel6
repeatedly returned the correctly classified login BUSY429, while later S1
and S2 requests were never reached. Current scope of429 remains unknown. Root
subsequently retired c10 exceptionally: before terminating its original worker,
67 issued leases included 66 CLOSED and one STOPPING with unconfirmed cleanup.
The original coordinator exited 1/reaped, state removed/source unchanged/private 0;
app/Chrome ports were free and PostgreSQL alone remained running. These are
Root-attributed outcomes, not this author's device or cleanup verification.
Normal complete lease cleanup and twelve-tile acceptance are not asserted.

Root authorized R141 after that retirement, within approved Stage1. Owned edits:
the pure scheduler, its two existing web test files, this supplemental report,
and the existing browser-media guide. React runtime, player, native/media/backend,
receipts, dependencies, original approvals and observation sources were untouched.
Root owns canonical report/ledger/AGENTS updates and new review/approval closure.

## Implemented correction

`live-wall-scheduler.ts` now retains each BUSY target's original queue ticket
and gives it one current, identity-fenced park timer. Its stored consecutive
BUSY delay doubles from 3 to 6 to 12 to 15 seconds, then stays capped; a different
target becoming LIVE does not reset it. The same target's success, explicit Stop,
intentional replacement/new request or non-BUSY outcome clears its old BUSY
state. Duplicate play while queued does not bypass its wait. BUSY consumes no
ordinary retry and creates no global cooldown.

`pump()` selects the first time-eligible, slot-admissible target from the
existing priority queue: eligible focus, eligible replacement, ordinary FIFO.
At most one target can be starting. Park expiry never interrupts that target;
an entirely BUSY queue waits for finite timers instead of spinning.

Explicit `heldSlots` records actually freed replacement slots while their
owners are queued. `activeCount + heldSlots.size` stays within capacity. An
owner consumes its own reservation when starting; ordinary work requires genuine
unreserved capacity. BUSY preserves the replacement reservation. Success,
generic failure, NO_SIGNAL or Stop releases it. Stream changes atomically
transfer existing active/reserved slots, while a never-started queued replacement
does not create a reservation. Multiple concurrent reservations remain bounded.

Only an eligible focus may preempt. A focused reservation owner uses its own
slot without another preemption; an ineligible focus never stops a healthy
player. Generic failed starts keep the existing global 3/6/12/15-second cooldown
and one 2-second retry. NO_SIGNAL remains terminal until manual play and has no
retry/cooldown. Stop one/all, dispose and intentional new request/replacement
cancel and fence old park callbacks. Original effect order, retained Stop
promises, current-player/attempt/phase fences and late lease retirement are
preserved through the unchanged runtime/player composition.

## Executed verification

New causal scheduler tests first produced **8 failed /30 passed** on the
unchanged source. The realistic six LIVE/three S1 BUSY/three S2 ready test failed
because the first S2 request remained queued. Replacement spare-slot and multiple
reservation progress, independent backoff, parked focus and timer-fencing cases
also failed at expected scheduling assertions. One cancellation guard already
passed the old source and was retained as a regression boundary.

The React fixture initially tried the absent play-all button after six manual
requests; it was corrected to the actual remaining tile buttons. The causal
RED then asserted that the next player should exist after refusal, and found
only seven players instead of eight. Its GREEN verifies each retained original
Stop barrier before the next player starts, then reaches nine synthetic LIVE
with the three refused targets still queued and the original six players intact.
Unmount plus timer advance creates no new player.

The first implementation run had **65 passed /6 failed**: all new cases passed,
while six older assertions expected the superseded BUSY global/head behavior.
Those assertions were updated to authorized R141 semantics. The generic-global
backoff test now exercises actual generic failures instead of using BUSY as
a proxy. The first composed GREEN passed 122; four further guards for synchronous
all-BUSY input and reservation release passed, yielding 126 focused tests. Existing
eighteenth-channel replacement, held Stop, ten rapid focus/late lease, R135 phase,
typed NO_SIGNAL, ordinary retry and mixed invariant cases are included.

Commands from `apps/web`:

| Command | Actual result |
| --- | --- |
| `node node_modules/vitest/vitest.mjs run tests/live-wall-scheduler.test.ts tests/live-wall.test.tsx tests/local-live-player.test.ts tests/local-live-api.test.ts tests/local-live-proxy.test.ts tests/local-live-panel.test.tsx --reporter=dot` | Final 126 passed /6 files, exit 0 |
| `node node_modules/vitest/vitest.mjs run --reporter=dot` | Exactly one full web run after focused GREEN: 481 passed /22 files, exit 0 |
| `node node_modules/eslint/bin/eslint.js .` | Exit 0, no output |
| `pnpm typecheck` | Command unavailable in this PowerShell; no dependency/install change |
| `node node_modules/next/dist/bin/next typegen` | Exit 0, generated ignored route declarations |
| `node node_modules/typescript/bin/tsc --noEmit` | Exit 0, no output |

Only source comment wording changed after these executable gates. No semantic
code changed after focused/full/static verification. No services, SDK, device,
browser/CDP, SQL, dependency, Git or receipt operation was performed.

## Risks, limits and continuation

This repairs frontend head starvation without increasing backend capacity or
changing BUSY classification. Per-target parking can increase aggregate refused
attempts during genuinely global BUSY: ready requests take a sequential sweep
before their individual backoffs apply. The backend still fences admission,
uncertain original custody and capacity; the runtime still waits for retained
original Stops. Device grouping/new error details are not inferred or introduced.

Reserved replacements deliberately retain their last slot while BUSY. Other
requests can progress only in genuinely free slots. Queue positions express
priority, not guaranteed immediate start while an earlier target is parked.
Persistent BUSY retries remain automatic while requested with capped positive
delays; no new terminal-attempt limit was introduced. Timer timing depends on
the browser event loop. Recorder limits, other clients, actual backend retirement
and full twelve-tile success remain open product/execution questions.

Priority: independent review of these frozen frontend bytes, Root's new source
closure/receipts/approval, then bounded actual acceptance and original cleanup.
Synthetic nine-LIVE progress and 481 tests do not establish actual repaired
recorder playback, twelve concurrent native logins or release readiness.

## Frozen source hashes

| File | SHA256 |
| --- | --- |
| `apps/web/src/lib/tvt/live-wall-scheduler.ts` | `394605161285ce492d5cc948eb0f067b9490ed467c8b39dc0e7d9398ff08290e` |
| `apps/web/tests/live-wall-scheduler.test.ts` | `f1ee3091afd8c8de1523955375a3dfef63a0d83da6c35781a8818d318a04f3a9` |
| `apps/web/tests/live-wall.test.tsx` | `9f92d2188da91b47b20657f1d61dbda1204c502eba0717604816545e62b1c2f1` |
| `docs/integrations/tvt-local-media-web.md` | `4d72fbe79ec58e20a7975675f309fab41359e9a0ba8b3a6fdfadbbc50ad8e53e` |

Read-back confirmed `live-wall.tsx` and `live-tile.tsx` retain their diagnosis
hashes `74b5d68d…` and `1afb99b0…`. The unchanged current player hash is
`ca646616b05ebeb12e1411ac6eea8ea9f0dbee3f9b873fb4583c0dff455c6047`.
Whole-tree integrity/receipt construction remains Root-owned.

Update log: 2026-10-06 — Authorized R141 implemented after exceptional c10
retirement; causal RED/GREEN, one full web run, static results and frozen source
hashes recorded. Independent review and actual repaired acceptance remain open.
