# c11 observation publication and source provenance diagnosis

Date: **2026-10-06 (Asia/Seoul)**. Baseline HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, active branch `codex/superlive-web-service`, approved uncommitted R141/R142 implementation. Scope: read-only diagnosis of normally retired c11 `local-devices-6480f49c264246779e1fd209d4a1b72b`; no implementation, SDK, tests, database, browser or services executed during this diagnosis. Shared policy, active AGENTS, canonical service report, current observation guide and R141/R142 author/reviewer reports were read. Root owns canonical/AGENTS/ledger updates.

## Finding

**The observer's legal roster outgrows the runtime's borrowed 65,536-byte writer. The retained summary is an early successful snapshot, not the final state.** The actual persisted summary is **schema2**, not schema1. Terminal schema1 is the intentional separate completion format. Both files are internally consistent with publication failure; no evidence supports a stale observer import or old R141/R142 runtime.

The service provides authenticated recorder playback through SQL authority, original native sources, decoder and WebRTC. Optional observation keeps bounded safe projections outside those resource owners. Its in-memory cardinality bounds allow256 native/source/peer records, up to16 format transitions and six milestones per source. Its runtime writer accidentally borrows the much smaller private-context writer. This is an evidence-publication defect; it does not explain native502 or imply a media/auth failure.

## Retained evidence

| Evidence | Verified result |
| --- | --- |
| `media-observation.json` | schema2; stop_requested=false;90 attempts,90 sources,9 peers; failures0; all omission counts0;65,055 bytes. |
| Canonical snapshot digest | `0c10f5c5f1ebca05db365919680b9f04cd503fae84680d59e006a97b23fc2844`, exactly matching resources.mediaObservation.snapshot_sha256. |
| `resources.json` terminal | schema1; FAILED; writer_settled=true; observation_failures6850; omitted_attempts0; omitted_peers0. |
| Resource flags | apiSettled,workerSettled,contextRemoved,sourceUnchanged all true. |
| Coordinator resources | runtimeExit0,nextExit0,stateRemoved=true,custodyRetained=false,failureReported=false. |
| Original root receipt | coordinator_exit0,reaped=true,ready_seen=true,state_removed=true,known_private_occurrences0,reporting_failure=null. |
| Source snapshots | before equals after,265 entries. All62 entries overlapping the c11 approval have matching approved raw hashes. |
| Read-only current pin comparison |138/140 approved files still match; only canonical service/liveness Markdown differs due to Root's post-retirement reporting. All implementation/helper/runtime pins match. |

Root separately reports201 issued SQL leases, all CLOSED with cleanup confirmed. That total is not independently queried here and cannot be substituted for the missing final source roster. The persisted early90-source slice contains78 executor_start/busy and2 executor_start/protocol_invalid failures; late failures, counters and peer outcomes are unavailable through this snapshot. Native502 diagnosis belongs to the separate investigator.

## Exact publication mechanism

- `scripts/test-local-devices/runtime.py:784` creates MediaObservation with a callback to `helper.write_private(.../media-observation.json, value)`.
- `scripts/test-tvt-account/runtime.py:808` serializes indent2 plus newline, then raises for payloads above65,536 bytes **before** temporary-file creation or replacement.
- `observation.py:490` computes a candidate canonical digest, calls the writer, and updates `_last_digest` / final-published only after success. Its exception handler increments failures without deleting or rewriting the previous file.
- The existing watcher retries once per second. Records are retained in bounded memory and old rows are not deleted to fit the smaller writer.
- Original worker retirement invokes observer.close after server/resource retirement. A settled thread alone is insufficient: COMPLETE also requires final stop-requested publication and zero failures/omissions. The small terminal uses the same private writer successfully, and the runtime carries it into resources.json.

Read-only arithmetic using the exact retained JSON encoding:65,055 bytes leaves481 bytes. Appending a minimal valid source91 row gives65,408 bytes. Appending that attempt's minimal native OPEN_PENDING row gives**65,592 bytes**, exceeding the hard cap even without new milestones, failures or format transitions. This is already far below the advertised256-row bound. No byte-budget test or new test process was needed to establish that contradiction.

Last snapshot modification time was2026-10-05T20:02:15.999171Z; resources modification time2026-10-05T21:58:12.126206Z, a6,956.13-second gap.6,850 one-second failure increments are consistent with repeated failed publication plus ordinary scheduling overhead. The retained counter has no failure-class split, so this does **not** prove each of the6,850 errors was exclusively size-related or reconstruct the exact first failed write. Other callback/filesystem failures cannot be excluded from that aggregate. The cap mismatch itself and inability to publish the legal expanded roster are established from source and bytes.

The terminal hash identifies the last successful early snapshot. Hash equality does not establish finality: stop_requested=false, FAILED and nonzero failures independently reject completion. No terminal/hash gate bypass or falsely certified COMPLETE occurred.

## R141/R142 source provenance

Approval file: `.superpowers/verification/local-device-media-browser-runtime/root-source-approval-c11.json`,140 pinned source paths; raw SHA256 `4844c47eb8c341d2c18034638b810c861a9970731c9ca50ba5827fda61461d32`. This matches the independent recorded approval digest in root-approval-evidence-c11.json.

| File | Approved/current SHA256 | Before/after snapshot |
| --- | --- | --- |
| R141 `apps/web/src/lib/tvt/live-wall-scheduler.ts` | `394605161285ce492d5cc948eb0f067b9490ed467c8b39dc0e7d9398ff08290e` | Present and equal. |
| R142 `services/tvt-media/src/wso_tvt_media/native_source.py` | `e72c3aa8d451971e26863cfc2fef79c31a2a69fce082a067780ff5d4a2c361cc` | Absent from borrowed snapshot; covered by full approval checks. |
| Observation helper | `617a9ae9f477db6a602c09973a1c7c93cb66b65171764c2034047beca0aa67de` | Absent from borrowed snapshot; covered by full approval checks. |
| Local runtime | `5ea250f25990d3f28821b2fbd8cefc5a75698a870396a28f5787a5912bd57e98` | Present and equal. |
| Borrowed writer runtime | `1d961908c917d66f2da4e111c4dd1eddf46d1c130d8a542957c92b3944a0ba97` | Present and equal. |

The two implementation hashes equal their respective author freezes and independently reviewed tree `1ecbae2f1c384536e000d4ac45163d0082e56895`. R141 contains per-target BUSY backoff; R142 keeps raw/mapped clocks and PRESENTATION_STEP_US24, compares raw regression strictly with `<`, and maps accepted timestamps after validation. The approved run was not pointed at their pre-repair versions.

Launch/import chain is rooted in resolved source-file locations, not shell CWD: c11 wrapper derives active root from its own absolute file path and starts the server with cwd=root; server derives root from import.meta.url; it launches the root .venv-derived interpreter and the exact runtime absolute path. Next runs dev=true against root/apps/web. Runtime derives ROOT from its own __file__, loads observation through spec_from_file_location at ROOT/scripts/test-local-devices/observation.py, and inserts ROOT/services/tvt-media/src before importing wso_tvt_media.worker. The inspected earlier bridge/core imports do not import wso_tvt_media. The worker imports native_source through that package. Borrowed helpers also load the exact root script by path.

Runtime verifies every approved source before starting resources (`verify_source_approval`, lines206?296). On final exit, lines1177?1182 compare **all** approved hashes again, beyond the narrower source-before/after snapshot. The retained normal runtime/coordinator exit0 supports completion of that full check. `sourceUnchanged=true` alone would only prove the265-entry borrowed snapshot and must not be represented as independently containing the media files.

This establishes the approved source/launch/import chain and preserved source bytes at the fixture boundaries. No live module __file__, loaded-code digest, browser bundle digest or per-branch execution receipt was retained; therefore it cannot prove which individual R142 equal-time candidates or R141 cooldown branches executed. The published observation slice cannot establish late stability or acceptance. There is no evidence of main-checkout execution; using login:false here avoids the controller shell profile's CWD reset during evidence inspection.

## Priority and proposed correction

P1: provide an observation-specific finite serialization budget derived from the maximum legal256-record/six-milestone/16-transition projection. Keep the ordinary private-context65,536-byte limit, path/atomic-write rules, fixed safe schema, independent terminal, final-stop, writer-settled and digest checks. Add narrow regressions for91/201 records, maximum legal projection and oversize preservation/failure. Avoid truncating rows or treating an early successful snapshot as COMPLETE. This proposal is not implemented by the diagnosis.

After independent source review and a new immutable approval, reproduce a bounded small actual run. No product decision is needed for repairing this accidental budget mismatch. Actual12-tile acceptance and native502 cause remain open and are not resolved by the observer repair.

## Verification limits and update log

Executed only read-only source/artifact reads, scoped git status/HEAD, JSON structural projections, canonical digest/raw-pin comparisons and serialized-size arithmetic via the existing Python interpreter. No SDK/native imports, services, SQL, browser, test suite, dependency changes or existing evidence mutation. Console output excluded secrets, IDs, raw media and full logs. Historical runtime acceptance remains qualified above.

2026-10-06: created this portable diagnosis after c11 retirement; corrected schema confusion, established writer-budget mismatch, audited R141/R142 source provenance and recorded exact evidence limits. Read with the canonical service report before changing observation; update after correction/review/execution.
