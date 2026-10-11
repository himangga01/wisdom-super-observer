# R191 shared connection-card cleanup: fix-round-1 re-review

Date: **2026-10-09, Asia/Seoul**. Verdict: **C0 / I0 / M0** for the
bounded I1 correction and its direct regressions. **R0 I1 is resolved.**
This is source approval for this correction, not actual recorder/Chrome
playback, native cleanup, twelve-camera acceptance or release readiness.

## Scope, authority and baseline

This review follows the shared analysis policy, worktree `AGENTS.md`, canonical
`docs/service-analysis.md`, approved Stage 2 spec/plan and the preserved R0
review, `docs/analysis/2026-10-09-shared-connection-live-review.md`.
The author report is `docs/analysis/2026-10-09-shared-connection-live-fix.md`;
its updated SHA-256 independently matched
`992376eb14977d7418146176b344d2e72de9787664e68f18281ea73372230c3d`.
Root retains ownership of AGENTS/service updates and actual runtime gates.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Source HEAD remains the R0 baseline `6436748f37c799fd14ce03e1d72c86c79eda6b0f`
plus retained, reviewed Stage 1/2 and separately owned working-tree changes.
This review covers only the seven-file fix delta and the unchanged interfaces
needed to establish its semantics:

- BASE tree: `88ce5a413a607f154f97aef1438602534c1074c2`.
- Candidate tree: `67dcbd2a74f8996c16909f42190242fcb4ed9bee`.
- Freeze directory: `.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/`.
- Inputs: `task-1911-review-r1.diff` and `task-1911-frozen-hashes-r1.json`.
- All seven current files matched the frozen manifest before verification.
  The saved diff measured 21,174 bytes here, versus 20,575 in the dispatch.
  Exact source hashes identify this reviewed candidate; no source discrepancy
  was found. The tree pair also contains Root-owned documentation changes,
  which are outside this review.

## I1 resolution and implementation assessment

The service restores selected-channel playback on an OWNER's connection card
under the existing shared-recorder protocol. R0 found that a fulfilled wall
Stop with state STOPPING was removed from the card's module-level cleanup set;
a remount then lost the previous runtime's remaining fence.

`shared-local-live-panel.tsx:22–42` now supplies `stopCardWall` to the existing
group at line 58. The supplier returns a normal CLOSED result directly. For
STOPPING it retains the same original operation while reading that wall until
an exact CLOSED response. The retained runtime aggregate therefore cannot
fulfill on a nonterminal wall merely because the original Stop POST fulfilled.
The existing aggregate still waits for original player/ref/operation cleanup.

The readback captures the original tenant and wall from the Stop arguments.
Inventory changes, CSRF changes, cancellation and full unmount/remount cannot
replace those arguments. This also applies when the unchanged group retires a
late-created wall. Disposal does not supply cleanup proof or cause a successful
terminal Stop to remain fenced merely because the group is disposed.

Readback has one 25-second cancellation deadline following the existing bounded
Stop POST. Every GET consumes that same signal; still-STOPPING results wait
500ms between attempts. This is a bounded observation period, not a renewal of
the wall or native authority. Unexpected ACTIVE, invalid response, unavailable
wall, HTTP failure, abort or expiry reject the same original operation. The
existing retained rejected-promise barrier then continues to block replacements.
Missing or expired authorization is never interpreted as CLOSED.

## Readback authority and transport review

The only client protocol extension is `readLocalWall` at
`apps/web/src/lib/tvt/local-live-wall-api.ts:30–35`. It validates both UUIDs,
uses the existing exact-wall GET route and applies the existing strict wall
schema, response/header request-ID correlation, tenant equality and wall-ID
equality. It does not accept private fields or fabricate an owner/cleanup ID.

`local-live-api.ts:50–69` adds only a closed GET/POST method option, defaulting
to the existing POST behavior. GET has no request body or CSRF write header.
Both methods retain same-origin credentials, no-store, redirect rejection,
abort/deadline handling and bounded response parsing. Existing POST callers
retain their body/header behavior and are covered by the directly rerun API
suite.

Targeted inspection of the unchanged read authority confirmed:

- The BFF exact-wall route already permits GET, requires the session cookie,
  forwards it to the backend and correlates the public response. No new endpoint
  or weakened write-CSRF rule was introduced.
- Backend `local_media_mux.py:190–196, 278–289` uses the authenticated tenant
  OWNER scope and calls the existing `wall_view`. The Stop response already uses
  that same read authority at lines 344–350.
- Migration 0016 `WALL_VIEW` at lines 261–272 requires exact tenant, actor,
  session, tenant epoch, current OWNER membership and unexpired, unrevoked
  session. It returns the durable wall state without renewing authority.
- Existing `FINALIZE_WALL` at lines 194–212 permits CLOSED only after durable
  master cleanup, physical slot closure, viewer/media/native settlement as
  applicable and focus-reference retirement. Thus the exact authorized CLOSED
  readback consumes the existing terminal wall contract; it is not a newly
  invented native cleanup receipt.

No group/runtime, backend, Core, SQL or native implementation changes were
required. Their broader acceptance remains governed by their existing reviews.

## Direct verification

Executed in this re-review:

```text
pnpm --filter @wso/web test tests/shared-connection-live.test.tsx tests/shared-connection-cleanup-failure.test.tsx tests/local-live-wall-api.test.ts tests/local-live-api.test.ts
  4 files PASS; 41 tests PASS; exit 0

git diff --check 88ce5a413a607f154f97aef1438602534c1074c2 67dcbd2a74f8996c16909f42190242fcb4ed9bee
  PASS; exit 0
```

The directly executed tests cover fulfilled STOPPING across inventory,
credential and full unmount replacement, exact CLOSED release, repeated
STOPPING, cancellation while cleanup waits, deadline/upstream/foreign-scope/
unexpected-state quarantine, rejected original Stop, and actual GET wire
serialization/correlation. Earlier direct-CLOSED positive controls remain.
Tests use synthetic network/player boundaries; they do not access a real device.

The author's causal three-test RED and wider nine-file/132-test GREEN,
typecheck and lint results are preserved report evidence; those broader gates
were not rerun here. A first read-only migration-path search used nonexistent
candidate paths; `rg --files` located the established migration and the targeted
source inspection then completed. No source fix or runtime action followed
from that search miss.

## Frozen fix files

| File | SHA-256 |
| --- | --- |
| `apps/web/src/features/connections/shared-local-live-panel.tsx` | `2431dbc806d7356562c5b743acea6dac6aef8008f5ea4aa32653f1caaacb8d79` |
| `apps/web/src/lib/tvt/local-live-api.ts` | `66e03169ea649aa94025813a92abc810d2e2cef33c32c940d0bb0c71a0551408` |
| `apps/web/src/lib/tvt/local-live-wall-api.ts` | `77389acda14b888276079efbf0ce7864cf0289d1d297a2079256cf32ab2d04ac` |
| `apps/web/src/lib/tvt/owned-shared-mode.ts` | `22852e9f7f222a00b16114a43b46c91e0bfbc3d44a808e24999ffa3442346c56` |
| `apps/web/tests/shared-connection-live.test.tsx` | `8791fb4769e3d1e183d9cbd2dc904d8cd0fc58c99cbde80340e41878684131d6` |
| `apps/web/tests/shared-connection-cleanup-failure.test.tsx` | `074b82bb726fcecde340a5df04dd7487ae696cfccda0ed6b674af2fc2f593eda` |
| `apps/web/tests/local-live-wall-api.test.ts` | `6ae8c898511e29361350fa2208bb6d2492228043dbd5486d894a39ee07fc289d` |

## Remaining limits and next gate

No substantive finding remains in this bounded correction. Unresolved cleanup
intentionally stays quarantined after readback failure; recovery UX remains an
open product/backend decision. Production enablement beyond the owned profile
is still outside scope. Root must create the fresh immutable source approval
before a changed-code runtime and conduct the actual browser/device acceptance.
No private credential, database, SDK, Chrome or application runtime/process
operation was performed here. Only this review report was written.

Update log: 2026-10-09 — R0 I1 re-reviewed as resolved; exact-wall authority
traced; seven frozen hashes matched; direct 41-test gate passed; scoped source
verdict C0/I0/M0 recorded with actual acceptance left open.
