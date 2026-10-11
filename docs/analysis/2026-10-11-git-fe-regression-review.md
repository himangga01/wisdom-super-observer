# Git integration frontend regression review

Analysis date: **2026-10-11, Asia/Seoul**. Baseline: active implementation worktree `codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f` plus retained reviewed Stage1/2/R193–R210 changes. This is a narrow test-fixture correction during the user-authorized integration workflow. Root owns staging, documentation reconciliation, Git and publication.

Read shared analysis policy, AGENTS, current LocalLivePlayer/live-wall/group/shared-card source, [FE R1 review](2026-10-11-live-stop-order-fix-review-r1.md), [R210 acceptance](2026-10-11-r210-live-acceptance.md) and [branch audit](2026-10-11-git-branch-audit.md). Read this report before reusing this regression result; update it after changes to the fixture or lifecycle contract.

## Cause and correction

Service purpose is authenticated local CCTV monitoring. The shared connection card reuses the wall/focus/player lifecycle. Its module-level originalStops set retains rejected original cleanup across component replacement. FE R1 deliberately preserves a failed issued-start outcome unless existing evidence proves nonacquisition or the exact original lease is CLOSED.

Root's full frontend gate found **594 passing / 6 failing of600**, all in shared-connection-live.test.tsx. Fresh reproduction of the entire15-test file returned **9 passing / 6 failing**, exit1, 7.81s. Failures occurred before the next first player start, affecting unmount, channel selection, STOPPING inventory/credential/unmount replacement and rejected original Stop controls.

The preceding positive shared-mode propagation test constructs the **actual LocalLivePlayer** through ConnectionsView. Its old fetch fixture returned inventory successfully and **503 for every other request**, including the issued original start. The propagation assertion passed because it only observed the emitted request. Its unmount then retained the failed original acquisition/cleanup promise in the shared-card registry, as R1 requires. Subsequent test cases encountered that retained failure and could not start. This is test-fixture contamination from intentionally unresolved acquisition, not evidence that the production failure fence should be removed.

Causal control: the first otherwise failing unmount-cleanup test passes alone, **1 passing /14 deselected**, exit0, 1.05s. This diagnostic selection was performed before editing; the final gates contain no skips. Whole-file reproduction and current class/registry inspection identified the preceding503 fixture as the cause.

Only the positive propagation test block changed:

- Its peer fixture implements minimal successful offer/answer negotiation.
- Fetch returns a parser-valid original lease with exact tenant/connection/store/device/channel/generation/revision, then an offer answer.
- Explicit Stop returns the same original lease ID in state **CLOSED** using the existing wire shape and request-ID header.
- The test waits for negotiation, still verifies the emitted SUB/wall start body, explicitly stops, then verifies wall Stop, original peer close exactly once and the exact original session Stop route.

The unknown-route fallback remains503. All existing negative pending, rejected original Stop and STOPPING readback/replacement assertions remain unchanged. No cleanup registry reset, timeout widening, extra retry, skipping, blanket404 success, production/API/native contract modification or release of unresolved ownership was introduced.

## Executed verification

Working directory for both full-file/full-web gates: `active/apps/web`.

| Gate | Exact command / result |
| --- | --- |
| RED original15 | `& 'C:/Program Files/nodejs/node.exe' node_modules/vitest/vitest.mjs run tests/shared-connection-live.test.tsx`:9PASS/6FAIL, exit1, 7.81s at13:39:11. |
| Causal isolated control | Same command plus `-t 'unmount cleanup fences a newly mounted card'`:1PASS/14deselected, exit0, 1.05s at13:39:50. |
| GREEN corrected15 | Original15 command: **15PASS**, exit0, 1.76s at13:40:40. |
| Required full frontend gate | `& 'C:/Program Files/nodejs/node.exe' node_modules/vitest/vitest.mjs run`: **600PASS across28 files**, exit0, 11.72s at13:40:51. No skips/failures. |

No further optional suite or new static/type gate was run. Production source remained unchanged; current R1 raw hashes match the accepted candidate.

| Path / evidence | Raw SHA-256 |
| --- | --- |
| shared-connection-live.test.tsx before correction | `8791fb4769e3d1e183d9cbd2dc904d8cd0fc58c99cbde80340e41878684131d6` |
| apps/web/tests/shared-connection-live.test.tsx corrected | `171d8231d35a5a0c51a5b68a812e54f37716ec6ff18ddf87d90a4c80907e34eb` |
| apps/web/src/lib/tvt/local-live-player.ts unchanged | `1c1b22e478ad528092b12dd9b701e59618508979c2fba556345be4e9b2e91e2a` |
| apps/web/src/lib/tvt/live-wall-group.ts unchanged | `72fbcfbf5824ccf80847273d014dccb399017f64dcfea9035dfb50cf8a3b91aa` |
| apps/web/src/features/monitoring/live-wall.tsx unchanged | `8aeb532a4e577932df31df8f7cdd6a5e2c8f4b1037c3e14a482008bc5ade9098` |
| apps/web/src/features/connections/shared-local-live-panel.tsx read-only | `2431dbc806d7356562c5b743acea6dac6aef8008f5ea4aa32653f1caaacb8d79` |

## Findings and limits

**Scoped findings: C0/I0/M0 after fixture correction.** The six integration frontend failures are resolved by an accurate positive fixture; the existing cleanup-fence tests pass in the complete600 gate. Independent FE R1 review and its original I1/I2 history remain preserved; this report does not replace that review or rewrite the prior RED result.

Actual devices, browser, DB, SDK and private inputs were not used. R210 hardware acceptance remains dated evidence, separate from this frontend fixture gate. Backend broad-test/runtime-typing, rare historical failures, frame-drop limits, twelve-camera and APK parity questions remain open as documented. Root may continue integration with the full frontend gate satisfied; this agent did not stage, commit or push.

Update log: Oct11 reproduced15RED, isolated the prior positive fixture's retained unknown acquisition, corrected only its valid start/CLOSED cleanup, then verified15GREEN and full600GREEN.
