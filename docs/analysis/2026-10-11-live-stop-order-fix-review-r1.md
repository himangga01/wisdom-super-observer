# Frontend Stop ordering R1: independent SPEC and QUALITY review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0. R0 I1/I2/M1
resolved.** No remaining findings in the corrected frozen scope. Approved for
fresh combined references and actual replay with separately reviewed Core
R209. This is source approval, not normal worker-cleanup or service acceptance.

## Baseline and preserved history

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained uncommitted
Stage1/2/R193-R209 work. All seven R1 paths match the manifest whose SHA256 is
`5e9c1699c267aec3fd10885ac42e1b39d5d353d88b8c5b1e8ba5827265299d4e`.

Read shared policy, [AGENTS](../../AGENTS.md), canonical service/actual evidence,
[R0 review](2026-10-11-live-stop-order-fix-review.md) and corrected
[author report](2026-10-11-live-stop-order-fix.md). R0 remains unchanged at
`699b633173b05d8fd8fbb73333666c4d9ad0d143bda01a04af991a4ed324ba25`, with its
C0/I2/M1 verdict and reproduced failures. The seven raw R0 preimages were
decoded and verified against their stored hashes; archive SHA256 is
`a3ce2f213ba9ee1c536601fb522667a8ad5ebe49158b819de3ec14b7737e2122`.
Reuse these reports before related changes and refresh after actual acceptance.
Root owns canonical handoff updates. Only this new R1 review was written.

R1 changes player source/tests, strict NO_SIGNAL wall-test expectations and
the author report. Group source, wall runtime source and group tests are
byte-identical to R0. All four Core R209 frozen hashes also remain unchanged.

## Finding resolution and SPEC assessment

**I1 resolved: unknown completed start rejection remains owned.** The exact
issued request Promise is installed before the API port is invoked and retained
after rejection. It is cleared only when a lease ID is accepted into ownership.
`fail()` may catch the rejection for UI notification, but `stop()` keeps the
same rejected original Promise/error. A lost response does not prove absence
or CLOSED; no authenticated Stop with a fabricated lease ID is attempted.
HTTP status/code and failed UI reporting remain available, while replacement
starts remain blocked by unresolved/rejected original cleanup.

**I2 resolved: synchronous initialization reentry cannot create an unowned
resource.** Lifecycle checks follow connecting/requesting and negotiation
notifications. Peer acquisition is latched before factory invocation; if the
factory reenters Stop, that original Stop waits for and closes its exact returned
peer. The request outcome is similarly latched before request-port invocation;
reentrant Stop waits for its late original lease, issues the authenticated Stop
and does not negotiate it. There is no peer/request acquisition after a
connecting/requesting callback has already retired the player.

The acquisition and Stop waits do not form a cycle: factory/request outcomes
resolve independently of the Stop promise. Start may await that Stop afterward,
but Stop awaits only the latched acquisition/request and authenticated cleanup.
The targeted reentry controls verify completion and exact promise/peer reuse.

For known leases, authenticated same-lease CLOSED still precedes successful
peer release. Failures close the browser peer while preserving original Stop
failure. R0's reviewed group barrier still waits player/start/focus cleanup,
attempts wall teardown as a backstop after failures and retains those failures;
same tenant/wall CLOSED remains required to unfence. No404/403/504 is silently
accepted as cleanup success and no backend/SQL/native/timeout contract changed.

**M1 resolved:** the author's group hash now exactly matches manifest/current
`72fbcfbf...`. The R0 typo remains documented in the unchanged R0 review.

The adjusted NO_SIGNAL wall test correctly distinguishes a reported startup
failure from proof that its issued server acquisition was absent or closed.
It preserves visible status/code, blocks a fresh request without cleanup proof
and asserts the original Stop rejection. This strengthens the unknown-outcome
contract rather than deleting its negative control.

## Fresh independent verification

Both original reviewer reproductions were rerun on the actual frozen R1 class
using installed TypeScript transpilation in memory and inert API/peer seams:

- Lost response after synthetic server creation: peer closes once; no guessed
  lease Stop; server outcome remains unknown; Stop rejects with the exact
  original error and every reentry returns the same Promise.
- Stop from connecting notification: zero peer factories, zero start requests,
  no server lease, same original Stop Promise completes. The R0 orphaned peer
  no longer exists in this schedule.

Fresh Vitest commands, exit0, from `apps/web`:

```powershell
.\node_modules\.bin\vitest.CMD run tests/local-live-player.test.ts -t "R1|authenticates original Stop|quiesces immediately|retains an original|shares original Stop|retains a pending start"
# 12 passed,18 excluded
.\node_modules\.bin\vitest.CMD run tests/live-wall.test.tsx -t "R210|fencing an issued start|retains real player late-start cleanup"
# 5 passed,60 excluded
```

These17 fresh tests include factory/request-port reentry, connecting/requesting
Stop, retained unknown start failure, successful authenticated Stop ordering,
held Stop, original error propagation, manual/unmount/heartbeat wall ordering
and late-start cleanup before replacement. No unhandled rejection or stalled
test was reported. Author targeted RED5/GREEN5, final117 related passes and
TypeScript/ESLint exit0 are retained author evidence, not rerun wholesale.

No source/test/runtime/DB/browser/hardware mutation, dependency installation,
private input, nested agent or commit occurred. The in-memory controls wrote
no test files. Preimages, manifests and R0 review were read-only.

## Actual limits

R208's wall200/session404 response order did not preserve request initiation
order. The source fixes and controls do not retrospectively select the actual
749b schedule or explain its separate worker server-close stall. Exceptional
worker97/coordinator1 retirement remains FAILED evidence, not normal COMPLETE.

Fresh combined actual LOW/HIGH/RETURN, manual Stop/rapid restart/unmount,
reconnect/store2 and normal original worker cleanup remain required. Historical
R203 slot/R207 terminal attribution, broad/runtime typing, twelve-camera/APK
and release readiness remain separate open gates. Unknown cleanup intentionally
stays fenced; UI disappearance is not original retirement proof.

## R1 frozen hashes

| Path | SHA256 |
| --- | --- |
| apps/web/src/lib/tvt/local-live-player.ts | `1c1b22e478ad528092b12dd9b701e59618508979c2fba556345be4e9b2e91e2a` |
| apps/web/src/lib/tvt/live-wall-group.ts | `72fbcfbf5824ccf80847273d014dccb399017f64dcfea9035dfb50cf8a3b91aa` |
| apps/web/src/features/monitoring/live-wall.tsx | `8aeb532a4e577932df31df8f7cdd6a5e2c8f4b1037c3e14a482008bc5ade9098` |
| apps/web/tests/local-live-player.test.ts | `64761c76f8b135de9cfe14ef8d6e6c428c2bd1aa90cdae939d66d127f278f0f8` |
| apps/web/tests/live-wall-group.test.ts | `be1de7c8926529addf77b618045194035070f27f5b855bae26259338b65432ee` |
| apps/web/tests/live-wall.test.tsx | `5bdced6698d2602e7ffdb633dea1ff7732a5c89e56e4020af6f741eec3aa1379` |
| docs/analysis/2026-10-11-live-stop-order-fix.md | `293d10328591b172d23773307645f6aad12276f2204acc9aec9b5e2bb0fda043` |

Update log: 2026-10-11 R1 C0/I0/M0 after independent I1/I2 reruns and17 scoped
passes; R0 findings/preimages preserved, combined actual acceptance pending.
