# Frontend Stop ordering R0: independent SPEC and QUALITY review

2026-10-11, Asia/Seoul. **SPEC C0/I2/M1; QUALITY C0/I2/M1**, two shared
Important code findings and one Minor documentation finding. **R0 is not
approved.** The principal authenticated-Stop ordering improvement is present,
but unknown start outcomes and synchronous initialization reentry still violate
the requested original-cleanup contract. Root and author were notified before
this report; corrections require a new frozen candidate and scoped re-review.

## Scope and baseline

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted
Stage1/2/R193-R209 work. R0 seven-path manifest SHA256:
`6fde415dcf34251bd65da1c6689b62c09622dd214c8c07823bd6af9507732be0`.
All seven files matched when inspected/tested. Author's correction work may
advance the worktree afterward; this report remains the R0 history.

Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[R208 actual evidence](2026-10-11-r208-live-acceptance.md),
[author report](2026-10-11-live-stop-order-fix.md) and previous focus/cleanup
diagnoses. The service coordinates authenticated lease Stop, browser peer
cleanup and shared wall retirement. Reuse this review before re-review; Root
owns canonical handoff updates. Only this report was written.

Actual749b reported wall200/session404 response order; request initiation order
was not retained. These source findings do not establish that historical live
schedule or the separate worker server-close wait. Core R209's accepted scope
is unchanged and outside these findings.

## I1: completed unknown start rejection is forgotten before Stop

`local-live-player.ts:35` clears `this.requesting` in `finally` when the start
request rejects. The outer catch calls `fail()`, whose `stop()` now sees both
`lease=null` and `requesting=null`. It closes the peer and resolves the retained
Stop promise without an authenticated Stop or positive proof that no original
lease was acquired.

This differs from the new tested schedule where explicit Stop begins while
the request is still pending and captures that exact request. A transport
failure after remote lease creation but before its response arrives is unknown
ownership; rejecting first does not turn it into known absence.

Fresh reviewer in-memory control transpiled the actual frozen player with the
installed TypeScript compiler and inert API/peer seams. The fake server marked
an original lease created, then rejected the start as a lost response. After
`await player.start(); await player.stop()`, observation was:

```json
{"stopResolved":true,"stopCalls":0,"peerClosed":1,"serverLeaseStillActive":true}
```

Required correction: retain the uncertain original start outcome through
cleanup and preserve its rejected/unresolved Stop barrier unless an existing
authoritative contract proves nonacquisition or closure. Do not broadly turn
unknown network outcomes into success. Preserve legitimate existing startup
error semantics with explicit controls.

## I2: Stop during synchronous connecting notification precedes peer creation

`start()` sets started and calls `events.state('connecting')` before entering
its initialization body. A synchronous callback can call `stop()`: the new
original Stop promise captures no peer/request, resolves and sets ended.
`start()` then continues creating a peer despite ended. The start request sees
an aborted signal and rejects; the catch skips cleanup because ended is true.
Repeated Stop only returns its already-resolved original promise, leaving the
later-created peer unclosed.

Fresh reviewer in-memory control used the actual player and called Stop from
the connecting callback. Its API seam rejected the aborted request. Result:

```json
{"reentrant":true,"made":1,"closed":0,"stops":0,"stopOutcome":"resolved","playerClosed":true}
```

Required correction: do not initialize/acquire a peer or start request after a
synchronous lifecycle notification has retired that player; retain original
ownership across other initialization callbacks too. Add the connecting
reentry schedule alongside the existing stopped-notification reentry case.

## M1: author hash table does not match its own group manifest entry

The author report records group hash beginning `72fbcbfb5824...`; the exact
manifest/current hash begins `72fbcfbf5824...`. Correct the table in the next
author revision. The R0 manifest is the source identity used for this review;
the typo did not conceal a production-file mismatch.

## Other reviewed behavior

For an already-owned lease, Stop latches its promise before stopped callbacks,
quiesces UI/timers/handlers, calls the same original authenticated Stop before
peer close, and requires existing wire `lease.id` equality/state CLOSED.
HTTP failure closes the peer while preserving the Stop rejection; no404 is
treated as success. Runtime claims its wall fence before scheduler reentry,
passes a deferred original-owner barrier to the group, and waits original
player/focus work. The group attempts wall cleanup after settled failures,
then retains failure; same tenant/wall CLOSED is required before unfencing.

The changed wire checks match the existing API response contract. Related
late-start, rapid-cycle, focus and held-cleanup tests were read. The found
problems are the untested initialization outcomes above, not a request to
relax wall/lease proof or discard rejected original promises.

## Independent checks and limits

Fresh existing controls, exit0, from `apps/web`:

```powershell
.\node_modules\.bin\vitest.CMD run tests/local-live-player.test.ts tests/live-wall-group.test.ts
# 47 passed
.\node_modules\.bin\vitest.CMD run tests/live-wall.test.tsx -t "R210|real player late-start cleanup|test_last_tile_focus_and_return|cancelled late reservation"
# 6 passed,59 excluded
```

The53 passing controls do not cover I1/I2. Additional reviewer controls used
`node -` and `typescript.transpileModule` on frozen source, with synthetic
stateful API/peer seams and no filesystem output. They reproduced the two
failures above. No source/test changes, dependency installation, browser,
runtime, DB, native operation, private input, nested agent or commit occurred.
Author112 passes/TypeScript/ESLint remain reported author evidence.

R208 exceptional worker exit97/coordinator1 remains FAILED; normal worker
cleanup was not proved by that run. Historical R203 slot and R207 terminal
attribution, combined actual Stop/reconnect/store2 and broader acceptance stay
open. A corrected frozen FE candidate must clear I1/I2 before combined replay.

## R0 frozen hashes

| Path | SHA256 |
| --- | --- |
| apps/web/src/lib/tvt/local-live-player.ts | `13b04560e264d57ee974a4f90b99d12df0513aed0c62dff4bc6d2e0fef16dcf4` |
| apps/web/src/lib/tvt/live-wall-group.ts | `72fbcfbf5824ccf80847273d014dccb399017f64dcfea9035dfb50cf8a3b91aa` |
| apps/web/src/features/monitoring/live-wall.tsx | `8aeb532a4e577932df31df8f7cdd6a5e2c8f4b1037c3e14a482008bc5ade9098` |
| apps/web/tests/local-live-player.test.ts | `5e7575ee3fe7d4fab610db0f8801d1953f54d5a5cbb3d0c16d9df51c0439e8be` |
| apps/web/tests/live-wall-group.test.ts | `be1de7c8926529addf77b618045194035070f27f5b855bae26259338b65432ee` |
| apps/web/tests/live-wall.test.tsx | `700de0ea2899603a515540ebd90a060404a5bfc89fe4c3fd4fae336ad7949316` |
| docs/analysis/2026-10-11-live-stop-order-fix.md | `2ac8f7a6d13b0f586633a74dface527d8c0dd5c0abbdb10fd00128002ac28f67` |

Update log: 2026-10-11 R0 C0/I2/M1 saved; unknown completed-start outcome and
connecting-reentry failures independently reproduced, correction pending.
