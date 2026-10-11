# Frontend original Stop ordering fix

2026-10-11, Asia/Seoul. Status: **frozen R1 candidate, scoped independent
re-review pending**. R0 was C0/I2/M1 and remains unapproved history in the
[R0 review](2026-10-11-live-stop-order-fix-review.md), SHA `699b633173b05d8fd8fbb73333666c4d9ad0d143bda01a04af991a4ed324ba25`.
Worktree `codex/superlive-web-service`, HEAD6436748 with retained
Stage1/2/R193-R208 changes; lead owns disjoint Core R209 and canonical reports.
Read shared policy, AGENTS/service evidence and R206 focus/RETURN reports before
reuse. Preserve historical failed receipts and update after actual acceptance.

## Cause and implementation

The service presents authenticated shared SUB/dedicated MAIN through original
browser, Core and native owners. Root supplied run749b final Stop responses:
wall200 then session404. Request order was not retained after tab closure;
response order does not establish request order. Core close ENTRY at
executor.close2590 can also follow peer-induced cleanup. All camera/viewer
originals were REAPED, while worker server.close remained outstanding. Root
released454 pins only after exact-owned exceptional worker28780 exit97 and
coordinator1/reap/context/DB/source/privacy settlement. This remains FAILED
exceptional history, not normal worker cleanup.

Source and stateful controls prove two conditional frontend defects: real
LocalLivePlayer closes its peer before authenticated lease Stop, permitting
peer-driven retirement to deny that ticket; runtime launches wall teardown
while original lease/focus Stop is still pending. The original player also
silently resolved every Stop error. These defects can produce the observed
404, but this task does not attribute the exact live request schedule or the
separate Python server.close wait.

Only three FE sources change:

- Player Stop latches its original promise before synchronous notifications,
  promptly quiesces timers/handlers/UI, retains an in-flight start result and
  its late lease, and requests authenticated Stop before closing the peer.
  Success requires existing wire `lease.id` equality and `lease.state=CLOSED`.
  Failure closes the browser peer but preserves the original rejected promise;
  no404/403/504 or unknown response becomes cleanup success. Failure/start
  notification catches do not alter that retained Stop promise.
  R1 also latches peer acquisition and the issued request before invoking their
  original ports. Rejected start outcomes remain retained after response
  completion; only an accepted lease transfers ownership to the lease field.
  Connecting/requesting reentry cannot issue later acquisition; factory reentry
  waits and closes only its exact returned peer. Negotiation notifications also
  recheck retirement. No Stop/start reentrancy cycle or new timeout is introduced.
- Runtime claims its cleanup fence before reentrant effects, supplies the
  original group a deferred player/focus barrier, stops scheduler owners and
  waits all original cleanup results. Manual, heartbeat and unmount share that
  original promise. Unknown starts and failed cleanup block replacement starts.
- Group waits original owners, pending focus operations/late originals before
  wall teardown. It still attempts wall cleanup after an individual failure,
  then retains that failure/fence. Unfencing requires same tenant/wall CLOSED
  metadata and no original cleanup rejection; STOPPING is not success.

No BE/API contract, grant/current/native/SQL call, request timeout, focus/heartbeat
interval, authority guard or ignore rule changes. Existing network/cancellation
bounds remain; serial phases do not authorize an unbounded retry or new lease.
Positive public CLOSED metadata is not an independent native Job receipt.

## Executed gates

TDD using actual player/runtime/group with inert peers and stateful API seams:

- Player RED:9 failures/16 excluded; peer-close-before-ticket, premature peer
  release, swallowed errors, false CLOSED proof, reentry and unknown start.
- Wall/group RED:7 failures/1 existing-negative pass/79 excluded; premature
  manual/unmount/heartbeat wall teardown and insufficient terminal proof.
- New17 controls GREEN; final affected gate **112 passed in8.12s, exit0**.
  Real rapid-cycle and late-start tests now wait original cleanup rather than
  expect a premature busy retry. Old STOPPING-success expectation becomes a
  retained rejection; held cleanup test releases player before wall response.
  New negative controls remain strict. Stop fixtures use existing CLOSED wire
  shape. A baseline prefer-const warning was corrected by explicit initial
  undefined, preserving the stateful old-FORWARD fixture.

Commands from `apps/web`:

```powershell
.\node_modules\.bin\vitest.CMD run tests/local-live-player.test.ts tests/live-wall-group.test.ts tests/live-wall.test.tsx --reporter=dot
.\node_modules\.bin\tsc.CMD --noEmit
.\node_modules\.bin\eslint.CMD src/lib/tvt/local-live-player.ts src/lib/tvt/live-wall-group.ts src/features/monitoring/live-wall.tsx tests/local-live-player.test.ts tests/live-wall-group.test.ts tests/live-wall.test.tsx
```

R0 TypeScript and scoped ESLint exited0. No optional broad suite was run;
broad7816/runtime typing and full service gates remain separately qualified.

### R1 review corrections and current gates

I1 retained unknown response: a stateful seam created a server lease then lost
its start response. R0 cleared the issued promise and falsely resolved Stop.
R1 preserves that exact rejection even when response failure precedes Stop.
HTTP status/code and failed UI remain; errors contain no nonacquisition/CLOSED
proof. Root explicitly approved the conservative consequence: even an issued
NO_SIGNAL start remains a failed cleanup barrier, limiting automatic/manual
acquisition retry until authoritative cleanup is available. Two old expectations
now assert this rejection/no new request rather than pretend cleanup succeeded.

I2 initialization reentry: R0 continued creating a peer after connecting Stop.
R1 guards connecting/requesting/negotiating notifications and latches factory
and request-port outcomes before invocation. The exact returned factory peer
is retired once; canceled initialization makes no later acquisition. M1 group
hash typo is corrected below.

Targeted real-class RED: **5 failed/25 excluded** on frozen R0, no setup error.
After correction: **5 passed/25 excluded**. Final required three suites:
**117 passed in8.34s, exit0**, preserving all previous17 controls. Final app
TypeScript noEmit and scoped six-file ESLint both exit0. Commands above are
unchanged; targeted command adds `-t R1`. No optional cases or broader gates ran.
R0's112 results remain dated history, not R1 proof.

R0 seven raw preimages are preserved in
`WORK/fe-stop-order-r0-preimages.json`, SHA
`a3ce2f213ba9ee1c536601fb522667a8ad5ebe49158b819de3ec14b7737e2122`;
original R0 manifest `6fde415d...` and review are unchanged. Only player source,
its test, the two strict NO_SIGNAL wall expectations and this report advance
in R1. Group/runtime source and group tests stay byte-identical to R0.

## Frozen identity and handoff

Pre-change source SHA prefixes: player3e34a933, group47d64ee6, runtimec300c143.
The seven-path `fe-stop-order-fix-manifest-r1.json` binds these final six files and
this report; all source changes stay within Root-approved ownership.

| Path under `apps/web` | SHA256 |
| --- | --- |
| src/lib/tvt/local-live-player.ts | `1c1b22e478ad528092b12dd9b701e59618508979c2fba556345be4e9b2e91e2a` |
| src/lib/tvt/live-wall-group.ts | `72fbcfbf5824ccf80847273d014dccb399017f64dcfea9035dfb50cf8a3b91aa` |
| src/features/monitoring/live-wall.tsx | `8aeb532a4e577932df31df8f7cdd6a5e2c8f4b1037c3e14a482008bc5ade9098` |
| tests/local-live-player.test.ts | `64761c76f8b135de9cfe14ef8d6e6c428c2bd1aa90cdae939d66d127f278f0f8` |
| tests/live-wall-group.test.ts | `be1de7c8926529addf77b618045194035070f27f5b855bae26259338b65432ee` |
| tests/live-wall.test.tsx | `5bdced6698d2602e7ffdb633dea1ff7732a5c89e56e4020af6f741eec3aa1379` |

No live server/browser/SDK/DB operation, private mutation, commit, push or
subagent was performed. An unresolved/rejected original intentionally stays
fenced; recovery is not inferred from UI disappearance or HTTP404. Independent
Astra review and fresh combined source/native references precede actual Stop,
rapid restart/unmount, transitions and normal original worker retirement.
Core maintenance cause, historical R203 slot denial, store2/twelve-camera/APK
and release/publication remain separate. No new product decision is introduced.

Update log: 2026-10-11 causal17 controls (16 RED failures/one preserved negative)
to GREEN112, static gates and frozen FE candidate recorded after pins release.
2026-10-11 R1: preserved R0 I1/I2/M1; RED5/GREEN5, current117/static passes,
unknown-outcome/reentry corrections and exact hash table recorded. Actual749b
request sequence and normal worker cleanup remain unmeasured by this source fix.
