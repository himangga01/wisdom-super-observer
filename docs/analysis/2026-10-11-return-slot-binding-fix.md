# R207 bind replacement SUB lease to the retained slot

2026-10-11, Asia/Seoul. Baseline HEAD6436748 plus retained Stage1/2/R193-R206 uncommitted work. Read AGENTS/service-analysis, r206-live-acceptance and return-slot-binding-causal-map before reuse. Purpose: complete shared SUB -> dedicated MAIN -> RETURN -> fresh SUB without abandoning original transport/task ownership.

## Selected cause and repair

Actual6db RETURN reached fresh SUB start RPC404 after MAINstop200; obsolete FORWARD cancel404 was absent. Core retained-slot branch returned its SlotRecord after current_slot without reserve_slot. SQL MASTER_RESERVE sets only mux_master_id; existing SLOT_RESERVE binds fresh lease.mux_slot_id. VIEWER_ADMIT selects by that exact per-lease binding, so omitted binding denies the new viewer. This causal branch is confirmed by the product _slot branch with real SQL, not inferred from a generic wall404 label.

Only Core _slot(existing) production changes. After existing current_slot/current-master checks, retrieve original prepared binding and reservation, call authoritative reserve_slot with original viewer/reservation/channel/budget, require returned grant object is exactly retained grant, its slot identity unchanged, and current-slot/master checks still true. Return the original SlotRecord. No native open, new task, replacement grant installation, credit/frame effect, SQL/migration/admission policy or timer change. Existing operation flag/failure fencing remains. reserve_slot already returns the retained capability for an existing SQL slot, after validating authoritative per-viewer association; generated unused proposal token/task does not issue a new capability on this branch.

## Verification

- Watched Core per-new-lease binding RED at admit_viewer404, then GREEN. Original slot/task/cut retained, fresh viewer registration, no duplicate native open. Copied returned grant/foreign slot/denied reserve negative controls reject before native open.
- Owned SQL RED4c450f8a5ccf4bb394d9478a179f9794 failed at admit_viewer/checked66. Full transition includes original SUB activation, FORWARD, MAIN attach/activation, RETURN consume, both MAIN receipts and CLOSED, fresh SUB issue/master join, product retained-slot branch, admit/activate, RETURN ATTACHED and strict current settlement.
- GREEN ae8fdf3315924946ab72bbde78681213 passed full transition. An intermediate probe ee6a failed only because test omitted explicit viewer argument to strict settlement_current; corrected test argument, production strict observer unchanged.
- Final owned SQL62b0f1310adf4468b5ef68e693c5558c:5 passed,0fail/error/skip, including foreign-channel/revoked-channel negatives and retained-slot revocation/original-binding controls. Original child reaped, owned DB cleanup, source DB content equality, source pins unchanged/private occurrences0.
- Core/runtime related163 passed; scoped Core mypy no issues, Ruff/format passed. Two test-authoring NameErrors were corrected before final163/5 gates. Existing broad pytest and whole-runtime mypy failures remain historical/open; no optional broad rerun.

## Limits and continuation

No new hardware execution yet. Source candidate requires independent SPEC/QUALITY and fresh reference/full source closure before actual early RETURN, LOW/HIGH300s deltas, transitions/Stop/reconnect/store2 and normal original cleanup. Rare R203 slot refresh denial remains unmeasured and is not declared resolved. No commit or public release. Portable actual evidence and canonical service/handoff update after retirement; keep all source/report pins frozen during runtime.

Update log: Oct11 narrow R207 candidate, causal RED/GREEN and required controls saved.
