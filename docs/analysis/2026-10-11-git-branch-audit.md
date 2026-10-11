# Git branch and worktree integration audit

Analysis date: **2026-10-11, Asia/Seoul**. Read-only snapshot completed at approximately **13:35 KST**. Purpose: identify code and documentation that must be preserved when publishing the latest implementation to main. This audit does not merge, stage, commit, fetch, push or alter source. Root owns integration. Only this English portable report was written.

Read the shared analysis policy, both relevant AGENTS instructions, canonical service-analysis, primary research introductions and [R210 acceptance](2026-10-11-r210-live-acceptance.md). Read this report before integration; refresh its baseline after refs change. Root must add its canonical pointer to AGENTS when integrating the existing instruction changes.

## 1. Exact refs and ancestry

The fetch was performed by Root before this audit. All advertised local refs in this repository were inventoried; no tags or additional branch/stash refs appeared.

| Ref | Commit |
| --- | --- |
| main | `211d1484aa16eb30f5d362758f149f98dec9dfdf` |
| origin/main | `211d1484aa16eb30f5d362758f149f98dec9dfdf` |
| origin/HEAD, symbolic to origin/main | `211d1484aa16eb30f5d362758f149f98dec9dfdf` |
| codex/superlive-web-service | `6436748f37c799fd14ce03e1d72c86c79eda6b0f` |
| origin/codex/superlive-web-service | `211d1484aa16eb30f5d362758f149f98dec9dfdf` |
| Detached service-foundation worktree HEAD | `87ca6bacd95f66f4daf0aeb39d8e906098d3e4ac` |

`main...codex/superlive-web-service` has **0 main-only / 3 feature-only commits**. Merge base is exactly main211d1484. Thus the committed feature history is eligible for fast-forward integration; there is no divergent committed main history to reconcile. This is an ancestry result, not an executed merge.

Feature-only commits, oldest first:

| Commit | Inspected scope |
| --- | --- |
| `0834efbfc0c043e2d275b4f7bd7eecf7b1c18b05` | Continuous native local live media, decoder liveness/keepalive, media lease SQL/RPC/API/WebRTC, media worker/service, tests and qualified reports. |
| `bf4c110a24fa71dbbdab10f3530eb74991a8ac9d` | Documentation preserving the earlier publication limitation. |
| `6436748f37c799fd14ce03e1d72c86c79eda6b0f` | Owner-scoped monitoring page, multi-camera wall/tile/scheduler, shell navigation, tests and reports. |

The aggregate committed difference is **78 files, 17,107 insertions / 82 deletions**. Commit scopes and representative monitoring, player, decoder and media package differences were inspected. These commits form one linear implementation history; recommending the entire feature history avoids selecting only the UI while omitting its backend dependencies.

The remote feature ref does **not** contain these three commits. Latest Stage1/2/R193–R210 work is also not represented by any current commit or remote ref.

## 2. Worktree contents that branches alone omit

Initial counts exclude this new report. No staged files were present in any worktree.

| Worktree | HEAD / mode | Tracked dirty files | Untracked files |
| --- | --- | ---: | ---: |
| C:/2026_project/wisdom-super-observer | main211d1484 | 2 | 5 |
| C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer | feature6436748f | 67 | 199 |
| C:/Users/강지혜/.codex/worktrees/service-foundation/wisdom-super-observer | detached87ca6bac | 1 | 3 |

The active worktree's 199 untracked files include 116 documentation files, 46 tests, 12 frontend files, 9 service files, 6 package/migration files, 5 scripts and 5 root files. Its tracked edits cover frontend live orchestration and tests, Core admission/live service/codecs, API/bridge/native/media services, runtime helpers, generated contracts, lockfile and portable evidence. No tracked deletions appeared.

Service purpose remains authenticated local CCTV monitoring. Its newer architecture adds per-recorder shared SUB transports and independently owned MAIN originals with SQL focus/grant authority and explicit viewer/native cleanup. Latest implementation must therefore include coordinated frontend, Core, API, bridge, media, migrations, contracts and tests, not just the latest seven frontend repair paths.

[R210 acceptance](2026-10-11-r210-live-acceptance.md) records historical real LOW313.6s/HIGH311.8s, RETURN/rapid/ordered Stop/reconnect and normal retirement. It also explicitly retains frame drops, rare prior failure attribution, twelve-camera/full APK, broad-test and typing limits. Those runtime facts were read, not re-executed here.

The existing ignore rules exclude local runtime/private/capture data, credentials/TLS/native binaries, dependency/build caches and .superpowers evidence. Commit source, dependency manifests/locks, checked-in generated contracts, portable reports and required public source receipts. This inventory is not a new full secret scan or approval of every untracked file; Root must inspect the explicit staged set rather than force-add ignored artifacts.

## 3. Primary documentation must be carried forward

The primary checkout has no dirty application code. Its two tracked edits are **AGENTS.md (+99 lines)** and **docs/service-analysis.md (+69 lines)**. The service addition records Oct8 research and historical Chrome refusal/remaining-work evidence. It must be incorporated as dated history alongside the feature's latest R210 service authority. Replacing the entire active service report with the primary copy would discard approximately four thousand newer added lines.

Five primary-only files are absent from the active worktree:

| Path | Raw SHA-256 |
| --- | --- |
| docs/analysis/2026-10-08-apk-selected-features-research.md | `6114a82d2cea81a1dcc990cf7032043daf5d0240c92954ad8b1109b7d153f8ff` |
| docs/analysis/2026-10-08-cctv-incident-research.md | `7814e1184c932fae76ecea7555ded39a358e223e9973615b44ef857453d4d760` |
| docs/analysis/2026-10-08-chrome-access-test.md | `7a359396bf4cd27d0a43c3224f556da59cc1f35800c8a07d90b03e2eb4661d37` |
| docs/analysis/2026-10-08-original-plans-remaining-work.md | `34a20cf39e2b0ee70d5957af06b20314de8a8bfdacb7c410562df25b01f6263a` |
| docs/superpowers/specs/2026-10-08-cctv-service-completion-design.md | `5dfecc6d056cc06cfee7bd53ed76f5fadd80e44f575f69c7ffe62f5aa3766683` |

These describe proposed APK operations, incident detection/evidence architecture and historical gaps. Their proposal/verification qualifications must remain intact. Selectively merge primary AGENTS research pointers and dated service sections with current active instructions/evidence. The two common documentation paths are the concrete overlap requiring reconciliation; the five new files have no existing active counterpart.

## 4. Foundation requires no additional code merge

Detached87ca6bac is already an ancestor of both main and feature. `main...87ca6bac` is **50 main-only / 0 foundation-only**. There is no unique detached commit to merge.

All four dirty/untracked foundation paths were inspected:

| Path | Finding |
| --- | --- |
| docs/superpowers/plans/2026-09-21-wisdom-super-observer-implementation-plan.md | Current bytes are identical in all three worktrees, SHA `8ee02f8d8ee4f4db64f8add272bf7503798ff9217d7476bd3c9b7ffcc04337e7`. The old detached baseline makes this appear dirty; no missing content. |
| docs/integrations/superlive-static-analysis.md | Older core-path static report. Current main/feature preserve its evidence and narrow its title/scope/completion wording to avoid claiming whole-APK completion. Do not overwrite the newer qualification. |
| docs/integrations/tvt-call-map.md | Same call-map body; main/feature add explicit core-path/whole-APK qualification and coverage reference. |
| tests/contract/test_health.py | Two older health controls. Main/feature retain liveness and unavailable-database secrecy controls using current injected-readiness API, plus broader request-ID, exception, wire-contract and export controls. No distinct application behavior to add. |

Main and feature versions of these integration docs and health test match after CRLF/LF normalization. No uncommitted foundation application source or unique test requirement was found. Preserve that worktree until Root decides its disposition; this audit does not delete or clean it.

## 5. Recommended integration order and safeguards

1. Preserve primary research/design files and reconcile its two documentation appendices with active canonical history before main checkout changes.
2. Commit the active reviewed implementation, directly related tests/contracts/locks and portable evidence as an explicit source set. Preserve older failed reviews/acceptance and immutable public receipt history.
3. Include the primary-only research and reconciled instruction/service updates in the resulting history, with no stale claim replacing R210 evidence.
4. Integrate the resulting feature descendant into main. Current ancestry supports fast-forward; recheck refs after Root's new commits. Publish main and optionally the updated feature ref according to the user's instruction.
5. No separate foundation or other branch merge is indicated by this inventory.

Git emitted LF-to-CRLF warnings on many existing paths. The active untracked .gitattributes contains exact-byte rules for selected receipt/source paths. Public receipt validators bind raw source hashes, so Root should preserve intended bytes and check publication effects; Git blob equality after normalization alone does not prove runtime raw-hash acceptance. R210 also warns that post-retirement report changes invalidate old launch envelopes. Git publication must not be presented as a fresh native/device acceptance gate.

No .gitmodules exists in the inspected worktrees; git submodule status is empty, and recursive trees for main, feature and detached foundation contain no mode160000 gitlinks. No submodule integration is required.

## 6. Evidence and limits

Read-only commands: git worktree list --porcelain, status --porcelain/--short, for-each-ref/show-ref, rev-list --left-right --count, merge-base, branch --contains, log/stat, diff/name-status/numstat, ls-files --others --exclude-standard, ls-tree and submodule status. Raw file SHA-256, normalized-byte comparisons and unified content comparisons covered primary-only and all foundation dirty paths. Active git diff --check returned0, with line-ending warnings.

This is a branch/inclusion audit, not independent review of every retained source change or a new test gate. No merge simulation, dependency installation, application/DB/SDK/browser operation, private read, commit or push was performed. The sole report write changes the active untracked count after the initial snapshot. Root received the remote-feature gap and foundation conclusions promptly.

Priority is preserving all requested source and research before integration. Remaining product questions (camera count, acceptable latency/drop thresholds and final APK scope) remain as recorded in R210/research and do not change branch inclusion.

Update log: Oct11 all local/remote refs, three worktrees, missing primary research, superseded foundation files, dependency structure and integration order audited.
