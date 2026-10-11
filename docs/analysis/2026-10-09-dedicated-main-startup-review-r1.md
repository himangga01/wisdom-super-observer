# Dedicated MAIN startup: R1 expiry fixture review

Analysis date: **2026-10-09 (Asia/Seoul)**.

**Verdict: C0 / I0 / M0.** The test-only expiry margin correction and author
checkpoint are accepted. No critical, important or minor finding was identified.
The corrected eight-case SQL rerun remains controller work; this review executes
no database or native/browser acceptance.

## Scope and authority

Read before review: the shared analysis policy and worktree
[AGENTS.md](../../AGENTS.md), the canonical
[service report](../service-analysis.md) R193 first-owned-SQL checkpoint, the
frozen [R0 review](2026-10-09-dedicated-main-startup-review.md), the R1 packet
and updated [author report](2026-10-09-dedicated-main-startup-fix.md).
R0 SHA256 `c3102fe63391fc882d2c2521f60bec097cb8df9d053f660a0942120f38e28449`
remained unchanged. The prior production review is retained, not reopened.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch `codex/superlive-web-service`, established HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with extensive retained Stage 1/2
source, tests and reports. No source, index, HEAD/ref or unrelated work was changed
by this reviewer. Only this separate report is written; the controller owns its
canonical-report/AGENTS bridge and subsequent execution.

R1 baseline tree: `86cfe44397475c672be5a9b3ef44614d07781bf4`.
Candidate tree: `fbc7c55645cf6e784a1226b1ecd3ba13c504e481`.
Packet: `.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/task-1931-review-r1.diff`.
The reviewed implementation delta is one timestamp literal and one comment in
the expired-focus integration fixture. The author report was also refreshed;
this review checks its current checkpoint rather than repeating the R0 review.

| File | Verified raw SHA256 |
| --- | --- |
| `tests/integration/test_local_media_mux_admission.py` | `a9a0f31109d2125a6f8f50084b3fbd1a27afeb2ccc02c65739a4035098f461fb` |
| `docs/analysis/2026-10-09-dedicated-main-startup-fix.md` | `de651bd7f6d7465cb11e01e031bfad1c39f5fdaff0b127214ba41c2794918404` |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `f48373ce7861106a72901165177fede2d3da31a0a7ff9d658a2c16d29398cf33` |

Both other R0 contract-test hashes also matched their retained frozen manifest.
R1 current file contents matched the candidate snapshot with Git newline
normalization, while raw-file hashes were checked independently.

## Cause, behavior and findings

The service presents authorized CCTV streams. The already reviewed correction
uses a dedicated pre-activation authority predicate before native MAIN startup,
preserving later activation and hot authority. R1 changes only test data used to
verify that an expired pending FORWARD focus denies this startup predicate.

Controller run `e592dd93673c49dc92227990dd6dd7df` executed eight selected SQL
cases: **7 passed, 1 failed, 0 errors/skips**. The failed expired-focus setup used
separate `clock_timestamp()` calls for issued 30 seconds ago and expiry 10
seconds ago. The resulting **20.000010-second** lifetime violated the unchanged
`expires_at<=issued_at+interval '20 seconds'` constraint in
`0016_tvt_device_media_epochs.py:70`, before calling the startup predicate.
Positive CLAIMED selection/activation/current and six other negatives passed.
The canonical report and revised author checkpoint agree on those results and
normal original-child/owned-DB cleanup, unchanged source DB/pins and private
occurrences zero. These are controller execution evidence, not reviewer execution.

At `test_local_media_mux_admission.py:1541`, R1 leaves issuance 30 seconds ago
and changes expiry to **15 seconds ago**. Its nominal lifetime is 15 seconds,
giving **five seconds of margin** below the 20-second maximum while keeping the
focus expired. The comment explains the separate-sample margin. It preserves
the tested production denial and all production guards. No SQL migration,
production port, other fixture, receipt or expected assertion is changed.

**Exact findings: none.** The failed gate demonstrates invalid fixture setup,
not a production startup defect. The author checkpoint preserves the failed
run and R0 hashes and correctly leaves the corrected SQL rerun open.

## Fresh verification and limits

Executed one read-only stdin probe through `.venv/Scripts/python.exe -B -`;
exit **0**. It verified R1 and retained R0 raw hashes, the frozen R0 report hash,
candidate content equality, and exact integration-source equality to the prior
source after only the literal/comment substitutions. `compile(source, path,
'exec')` verified the modified integration file's syntax without executing it.
Source inspection verified the unchanged SQL constraint. No cache, bytecode,
DB fixture, native child/Job or browser was created.

Author-reported single-file Ruff/format and eight-case collection are retained
as author evidence; they were not rerun here. No optional suite or broad source
review was added. This review does not claim the corrected SQL case has passed.

Priority P1: the controller reruns the same guarded eight SQL cases, preserves
failed historical receipts, then refreshes source/native/runtime authority and
executes actual Chrome MAIN/return/stop acceptance. Actual SQL after R1, native
reap/BUSY behavior, recorder MAIN playback and twelve-camera/APK acceptance
remain separate gates. No product decision is introduced by this fixture change.

Update log: 2026-10-09 — R1 fixture-only review C0/I0/M0; source and report
hashes, literal margin and syntax verified; R0 report frozen and controller SQL
rerun pending. This report is frozen after its final hash is supplied.
