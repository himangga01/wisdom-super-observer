# Broad test failure triage

Analysis date: 2026-10-10, Asia/Seoul. Implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`,
with retained Stage1/2/R193/R194 and reviewed R196/R197 changes. Initial working
tree is already modified. Root reports immutable 350-source live run `0601`
is active. This analysis preserves every existing source, pin and report and
creates only this new report. It does not independently reproduce live symptoms.

Read before reuse with [service analysis](../service-analysis.md),
[R196 review](2026-10-10-heartbeat-inner-debug-review.md),
[R197 retirement review](2026-10-10-replacement-transport-retirement-review.md),
and [native reference review](2026-10-10-r197-native-pin-review.md).
Root owns AGENTS and service cross-links after the active run retires.
Refresh this report after relevant source changes or a properly scoped rerun.

## Finding and scope

**The broad gate failed. No behavioral R196/R197 regression is established by
these retained results.** All 23 heartbeat-debug cases and all 13 replacement
transport retirement cases passed in this same JUnit. The remaining failures
include environment prerequisites, historical fixed source fixtures, stale fake
constructor contracts, execution timing/custody assertions and test-order credit
interaction. None may be silently counted as passed or ignored for release.

The service streams authenticated TVT recorder media through web/API/Core/native
and media owners. R196 adds bounded inner-heartbeat diagnostics; R197 closes
exact matching refreshed transport records after authentic epoch retirement.
Broad tests also cover older account/directory RPC, private assets, Linux jobs,
Windows original-child ownership and fixed source activation gates. A bare
pytest invocation combines gates requiring different explicit execution profiles.

Saved evidence directory:
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/r196-r197-full-suite`.
Summary/JUnit agree: **7,816 cases, 85 failures, 172 errors, 736 skipped**, exit 1.
The arithmetic residual is 6,823 cases without failure/error/skip elements;
that count is not acceptance for skipped or errored gates. Root's saved summary
records source_unchanged=true and original_child_reaped=true for the suite
controller; it does not prove every nested failing test's cleanup.

## Structural classification

| Group | Failure | Error |
| --- | ---: | ---: |
| Earlier original-owner custody remains retained | 7 | 0 |
| Fixed original provider review fixture mismatch | 36 | 0 |
| Historical fixed source fixture mismatch | 0 | 114 |
| Historical pool size expectation | 1 | 0 |
| Host-credit test order or retained-credit interaction | 1 | 0 |
| Legacy session capacity/timing assertion | 1 | 0 |
| Old fake server constructor signature | 9 | 0 |
| Original cleanup confirmation assertion | 1 | 0 |
| Owned Linux Celery/Valkey prerequisite | 0 | 10 |
| Owned Linux S3/HTTP prerequisite | 0 | 14 |
| PowerShell 7 prerequisite | 4 | 34 |
| PowerShell builder executable absent | 11 | 0 |
| Real loopback child startup/deadline/lifecycle assertion | 13 | 0 |
| Real original-child deadline/reap assertion | 1 | 0 |

**Environment prerequisites:** 34 domain fixture errors and four foundation
failures explicitly require PowerShell 7. Eleven native builder tests pass
`shutil.which("pwsh")` as the child executable; absent pwsh produces subprocess
TypeError before builder behavior is exercised. Fourteen private-assets and ten
broker-recovery errors explicitly require actual owned Linux S3/HTTP or Linux
Celery/Valkey; their setup fails closed on this Windows run. Their platform
requirement is intentional source behavior, not executed Linux acceptance.

**Historical fixtures:** 16 account source fixture errors fail the approved
source snapshot assertion at `test_account_web_fixture.py:471`; 98 directory
fixture errors fail the initial fixed raw source guard at
`test_directory_source_gate.py:66`. Five current directory fixture source
bindings differ: TVT proto, both generated bridge modules, bridge client and
bridge server. Those bindings belong to earlier source extensions. Thirty-six
Windows source-gate failures hit original native review receipt equality at
`windows_socket.py:723` before reaching their selected Stage2 tampering branch.
The test's temporary source fixture still uses public Stage2 v1 while current
native production references public v4. Do not refresh historical receipts or
weaken native guards to make this broad test green. A separate current-fixture
update must preserve historical negative controls and intentional fixed pins.
A saved pre-change broad execution was not available, so this report does not
claim these tests were actually failing at a prior date.

**Stale fake contracts:** nine account/directory/local worker factory tests
return sanitized ACCOUNT_UNAVAILABLE at `server.py:682`. Their monkeypatched
Server constructors omit one or more `local_device_worker`/`directory_worker`
kwargs that the current factory passes. This is directly visible in
`test_account_flow_rpc.py:707`, `test_directory_rpc.py:521`,
`test_local_device_rpc_api.py:545` and `server.py:669-675`. The factory's current
source is unchanged from the pre-pin review tree. One inert pool test expects
pool size four at `test_local_media_admission_pool.py:48`; implemented admission
uses size eight (`local_media_admission.py:199`), also unchanged by R196/R197.

**Remaining lifecycle assertions:** seven Windows tests fail because the
unchanged guard refuses another original while earlier custody remains retained
(`windows_socket.py:1444`). Three then raise IndexError in test cleanup because
no child/output was acquired. One real-child hard-deadline test reaches deadline
but lacks its expected reap flag. Thirteen loopback account/directory/security
process tests fail deadlines, timing bounds, expected server-arrival signals or
settlement. Their source and saved results do not establish whether this run's
Windows child startup cost, suite interference or an older process defect is
responsible. They remain unresolved failures. No process/native rerun was made.

The sixteen-session capacity test took **37.393 seconds**, while each opening
uses a **20-second session deadline** (`test_local_live_provider.py:275`). It
fails because the seventeenth opening did not raise. Setup expiry is a concrete
possible explanation for this assertion; saved timing does not show each
original's lifetime, so no capacity-bypass conclusion is established. The
`current_cut_after_job_admission` case fails because the already reaped/closed
original is confirmed while the test expects false (`test_local_mux_ownership.py:
848`). This is an older custody assertion, outside the R197 admission delta;
its intended proof distinction requires a later narrow owner review.

**Host-credit interaction:** the saved common IPC/raw/RGB ceiling case rejects
RGB after reserving almost the host limit. One newly executed inert control
called this exact actual-source test in a fresh interpreter; it passed with
`media_credit_usage()` equal to `(0,0)` before and after. The saved broad failure
therefore is not a deterministic isolated allocation failure. Retained global
credits or test-order interaction remain candidates; this investigation did
not identify the exact retaining test and did not reset global accounting.

## R196/R197 attribution and priorities

Read-only comparison to review tree `5ce223fd5e41cdcab4774b33095070d74b523255`
found identical normalized source for local live provider, mux ownership, mux
IPC, media budget, legacy admission and bridge server. Windows source differs
in exactly the top-level LIVE_RECEIPT and ACCEPTED_HASHES AST nodes; all function
and class bodies match that tree. The R197 review documents its narrow admission
finish_epoch delta and source acceptance. Passing R196/R197 causal tests plus
these scope comparisons support no current attribution of the above behavior
failures to those narrow fixes. They do not prove absence of every indirect
interaction or replace live heartbeat/cleanup acceptance.

Priorities:

1. Root should finish the active live symptom/inner exception measurement and
   original retirement before changing any 350 pinned path or existing report.
2. Preserve this red gate and exact failed names. Restore the explicit test
   profiles for PowerShell/Linux prerequisites and historical source guards;
   do not introduce broad skips or update accepted receipts without review.
3. After retirement, isolate the legacy capacity/ownership and host-credit
   order interaction, plus real-child deadlines, with original cleanup evidence.
   Treat these as separate defects/fixtures until a causal trace identifies a
   link to the current heartbeat work.

Open questions are the exact earlier owner/credit that remains retained in the
full suite, the expected historical-vs-current source fixture contract, and the
intended session capacity assertion when serial setup exceeds lease lifetime.
No source, ignore rule, secret, DB, runtime, native policy, test fixture or
acceptance status was changed by this analysis.

## Verification and limits

Read-only commands parsed summary and XML, compared counts and every failed
name, grouped structural locations/types, read relevant source and review
reports, and used git show/AST/normalized-byte comparisons. No raw SQL,
credentials or arbitrary child failure text is included in this report. The
entire broad suite, native/process tests, DB, browser and hardware were not
rerun. One exact isolated host-credit control ran through Python `-B`, no
pytest cache, listener, DB or child process:

```python
from test_local_media_mux_budget import test_common_ipc_raw_and_rgb_cannot_exceed_host_ceiling
from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
assert media_credit_usage() == (0, 0)
test_common_ipc_raw_and_rgb_cannot_exceed_host_ceiling()
assert media_credit_usage() == (0, 0)
```

Exit 0. Existing broad stderr is empty. Evidence file hashes:

| File | SHA256 |
| --- | --- |
| summary.json | a1fd64eda4a40cecabcfaf35fe0e83b66dc36625013070e2b75317d11795a270 |
| junit.xml | bbed5f0965cb724176cf9565e6456e9570518ab3b03cf663ee62521b7b0311d9 |
| stdout.log | 5ce85ded73e9488c214165856778bf0ab1e8628126a39cf2e505d3e102bda2bb |
| stderr.log | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |

## Appendix: every failed/error case

The following 257 entries are copied by case name and module from JUnit,
without failure messages, locals or captured SQL. Counts match summary.json.

### Earlier original-owner custody remains retained

- failure: `tests/contract/test_windows_socket.py::test_fix1_writer_construction_after_spawn_retains_original_child[KeyboardInterrupt]`
- failure: `tests/contract/test_windows_socket.py::test_fix1_writer_construction_after_spawn_retains_original_child[SystemExit]`
- failure: `tests/contract/test_windows_socket.py::test_fix1_writer_construction_after_spawn_retains_original_child[RuntimeError]`
- failure: `tests/contract/test_windows_socket.py::test_fix1_interrupted_start_keeps_writer_uncertainty_after_child_reap`
- failure: `tests/contract/test_windows_socket.py::test_inventory_job_admission_interruption_never_releases_worker_input[False]`
- failure: `tests/contract/test_windows_socket.py::test_inventory_job_admission_interruption_never_releases_worker_input[True]`
- failure: `tests/contract/test_windows_socket.py::test_live_integration_parent_reap_record_uses_original_owned_child`

### Fixed original provider review fixture mismatch

- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_accepts_exact_current_portable_closure`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-0]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-1]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-2]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-3]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-4]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-5]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-6]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-7]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-8]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-9]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-10]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-11]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-12]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-13]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-14]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Files-15]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-0]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-1]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-2]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-3]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-4]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-5]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_rejects_drift_in_every_reviewed_entry[stage2Dependencies-6]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[old_reference]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[same_name_changed_hash]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[private_receipt_hash]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[missing_dependency]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[extra_dependency]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[source_status]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[native_status]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[critical_bool]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[important_one]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[minor_one]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[owned_missing]`
- failure: `tests/contract/test_windows_socket.py::test_stage2_source_gate_preserves_exact_native_review_guards[owned_extra]`

### Historical fixed source fixture mismatch

- error: `tests/contract/test_account_web_fixture.py::test_current_approved_source_reaches_guard_without_runtime_start[LF-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_approved_source_reaches_guard_without_runtime_start[LF-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_approved_source_reaches_guard_without_runtime_start[CRLF-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_approved_source_reaches_guard_without_runtime_start[CRLF-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[byte-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[byte-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[newline-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[newline-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[arbitrary-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_source_guard_rejects_drift_instead_of_accepting_live_computed_hash[arbitrary-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_rejects_malformed_residual_carriage_return[\r-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_rejects_malformed_residual_carriage_return[\r-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_rejects_malformed_residual_carriage_return[\r\n\r-tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_rejects_malformed_residual_carriage_return[\r\n\r-services/api/src/wso_api/main.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_normalizes_ordinary_mixed_lf_crlf_per_r75[tests/integration/test_tvt_account_rpc.py]`
- error: `tests/contract/test_account_web_fixture.py::test_current_source_normalizes_ordinary_mixed_lf_crlf_per_r75[services/api/src/wso_api/main.py]`
- error: `tests/contract/test_directory_source_gate.py::test_fixed_committed_ci_gate_accepts_reviewed_current19`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[None-WSO_TEST_W07_DIRECTORY_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[None-WSO_TEST_W07_API_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[None-WSO_TEST_W07_PARENT_SHA256]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[-WSO_TEST_W07_DIRECTORY_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[-WSO_TEST_W07_API_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[-WSO_TEST_W07_PARENT_SHA256]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[0-WSO_TEST_W07_DIRECTORY_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[0-WSO_TEST_W07_API_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[0-WSO_TEST_W07_PARENT_SHA256]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[true-WSO_TEST_W07_DIRECTORY_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[true-WSO_TEST_W07_API_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[true-WSO_TEST_W07_PARENT_SHA256]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[1 -WSO_TEST_W07_DIRECTORY_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[1 -WSO_TEST_W07_API_ACCEPTANCE]`
- error: `tests/contract/test_directory_source_gate.py::test_partial_or_invalid_activation_fails_closed[1 -WSO_TEST_W07_PARENT_SHA256]`
- error: `tests/contract/test_directory_source_gate.py::test_all_settings_absent_preserves_optional_opt_in`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[None-CI]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[None-WSO_CI_DISPOSABLE_POSTGRES]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[None-WSO_TEST_RECOVERY_DATABASE_NAME]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[None-WSO_TEST_RECOVERY_DATABASE_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[None-WSO_CI_RUNTIME_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[-CI]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[-WSO_CI_DISPOSABLE_POSTGRES]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[-WSO_TEST_RECOVERY_DATABASE_NAME]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[-WSO_TEST_RECOVERY_DATABASE_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[-WSO_CI_RUNTIME_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[wrong-CI]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[wrong-WSO_CI_DISPOSABLE_POSTGRES]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[wrong-WSO_TEST_RECOVERY_DATABASE_NAME]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[wrong-WSO_TEST_RECOVERY_DATABASE_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_linux_requires_every_managed_ci_opt_in[wrong-WSO_CI_RUNTIME_OWNER]`
- error: `tests/contract/test_directory_source_gate.py::test_other_platforms_cannot_select_ci_fixture[darwin]`
- error: `tests/contract/test_directory_source_gate.py::test_other_platforms_cannot_select_ci_fixture[linux2]`
- error: `tests/contract/test_directory_source_gate.py::test_other_platforms_cannot_select_ci_fixture[]`
- error: `tests/contract/test_directory_source_gate.py::test_windows_still_requires_explicit_root_current_flat19`
- error: `tests/contract/test_directory_source_gate.py::test_windows_never_falls_back_to_ci_fixture`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[missing-approval-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[missing-approval-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[false-approval-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[false-approval-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[wrong-family-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[wrong-family-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[wrong-parent-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[wrong-parent-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[missing-source-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[missing-source-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[extra-source-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[extra-source-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[duplicate-source-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[duplicate-source-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[duplicate-key-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[duplicate-key-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[extra-field-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[extra-field-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[invalid-digest-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[invalid-digest-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[computed-approval-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[computed-approval-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[empty-sources-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[empty-sources-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[bom-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[bom-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[bare-cr-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[bare-cr-local]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[mixed-eol-fixture]`
- error: `tests/contract/test_directory_source_gate.py::test_closed_fixed_receipts_reject_tampering[mixed-eol-local]`
- error: `tests/contract/test_directory_source_gate.py::test_exact_recorded_raw_or_lf_sources_are_accepted[raw]`
- error: `tests/contract/test_directory_source_gate.py::test_exact_recorded_raw_or_lf_sources_are_accepted[lf]`
- error: `tests/contract/test_directory_source_gate.py::test_unrecorded_source_bytes_cannot_be_normalized_into_approval[bom]`
- error: `tests/contract/test_directory_source_gate.py::test_unrecorded_source_bytes_cannot_be_normalized_into_approval[bare-cr]`
- error: `tests/contract/test_directory_source_gate.py::test_unrecorded_source_bytes_cannot_be_normalized_into_approval[mixed-eol]`
- error: `tests/contract/test_directory_source_gate.py::test_unrecorded_source_bytes_cannot_be_normalized_into_approval[content]`
- error: `tests/contract/test_directory_source_gate.py::test_unrecorded_source_bytes_cannot_be_normalized_into_approval[new-crlf]`
- error: `tests/contract/test_directory_source_gate.py::test_parent_live_bytes_are_pinned_before_authority`
- error: `tests/contract/test_directory_source_gate.py::test_exact_lf_fixture_is_portable_without_local_evidence`
- error: `tests/contract/test_directory_source_gate.py::test_linux_missing_committed_fixture_never_falls_back_to_local`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[packages/contracts/src/wso_contracts/tvt/directory.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[infra/migrations/versions/0011_tvt_directory_read_tickets.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[packages/core/src/wso_core/tvt/directory_admission.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/api/src/wso_api/tvt/device_service.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/tvt_parity/test_directory_service.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/integration/test_tvt_directory_admission.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/integration/test_tenant_isolation.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/integration/test_tvt_account_flow_admission.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/contract/test_flow_fixture_portability.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[docs/integrations/tvt-directory-service.md]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[packages/contracts/proto/tvt_bridge.proto]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2_grpc.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/client.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/server.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/selected.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[services/tvt-bridge/src/wso_tvt_bridge/directory_config.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[tests/tvt_parity/test_directory_rpc.py]`
- error: `tests/contract/test_directory_source_gate.py::test_each_reviewed_source_is_required_and_verified[docs/integrations/tvt-directory-rpc.md]`
- error: `tests/contract/test_directory_source_gate.py::test_local_root_requires_exact_raw_not_ci_lf_alias`
- error: `tests/contract/test_directory_source_gate.py::test_consumed_api_fixture_validates_source_before_owned_database`

### Historical pool size expectation

- failure: `tests/tvt_parity/test_local_media_admission_pool.py::test_engine_uses_bounded_queue_pool`

### Host-credit test order or retained-credit interaction

- failure: `tests/tvt_parity/test_local_media_mux_budget.py::test_common_ipc_raw_and_rgb_cannot_exceed_host_ceiling`

### Legacy session capacity/timing assertion

- failure: `tests/contract/test_local_live_provider.py::test_sixteen_original_windows_live_sessions_are_isolated_and_seventeenth_is_busy`

### Old fake server constructor signature

- failure: `tests/tvt_parity/test_account_flow_rpc.py::test_worker_factory_owns_each_resource_once_and_closes_all_after_failure[disabled]`
- failure: `tests/tvt_parity/test_account_flow_rpc.py::test_worker_factory_owns_each_resource_once_and_closes_all_after_failure[enabled]`
- failure: `tests/tvt_parity/test_account_flow_rpc.py::test_worker_factory_owns_each_resource_once_and_closes_all_after_failure[quarantined]`
- failure: `tests/tvt_parity/test_directory_rpc.py::test_worker_bootstrap_cleans_all_resources_and_never_half_starts[absent]`
- failure: `tests/tvt_parity/test_directory_rpc.py::test_worker_bootstrap_cleans_all_resources_and_never_half_starts[valid]`
- failure: `tests/tvt_parity/test_directory_rpc.py::test_worker_bootstrap_cleans_all_resources_and_never_half_starts[close-false]`
- failure: `tests/tvt_parity/test_directory_rpc.py::test_worker_bootstrap_cleans_all_resources_and_never_half_starts[close-raise]`
- failure: `tests/tvt_parity/test_local_device_rpc_api.py::test_local_worker_bootstrap_constructs_admission_only_for_configured_provider[False]`
- failure: `tests/tvt_parity/test_local_device_rpc_api.py::test_local_worker_bootstrap_constructs_admission_only_for_configured_provider[True]`

### Original cleanup confirmation assertion

- failure: `tests/contract/test_local_mux_ownership.py::test_current_cut_after_job_admission_releases_no_private_input`

### Owned Linux Celery/Valkey prerequisite

- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_producer_crash_after_commit_before_publication`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_dispatcher_crash_after_publication_before_ack`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_worker_child_crash_before_effect`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_worker_process_crash_before_effect`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_worker_crash_after_effect_before_ack`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_valkey_aof_restart_preserves_delivery`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_empty_broker_rebuilds_published_and_running_jobs`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_external_write_crash_reconciles_without_resubmit`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_unresolved_external_write_blocks_resubmit`
- error: `tests/jobs_recovery/test_job_broker_recovery.py::test_queue_isolation_prevents_starvation`

### Owned Linux S3/HTTP prerequisite

- error: `tests/integration/test_private_assets.py::test_photo_upload_does_not_require_a_store`
- error: `tests/integration/test_private_assets.py::test_upload_validation_rejects_truncation_checksum_and_type`
- error: `tests/integration/test_private_assets.py::test_upload_enforces_byte_pixel_dimension_and_frame_limits`
- error: `tests/integration/test_private_assets.py::test_pending_ready_and_ticket_authorization_isolation`
- error: `tests/integration/test_private_assets.py::test_stored_bytes_are_encrypted_and_tamper_fails_closed`
- error: `tests/integration/test_private_assets.py::test_multipart_and_adapter_capabilities_against_real_s3`
- error: `tests/integration/test_private_assets.py::test_upload_crash_recovery_and_abandoned_expiry`
- error: `tests/integration/test_private_assets.py::test_download_revocation_and_stream_deadline`
- error: `tests/integration/test_private_assets.py::test_parent_crop_scope_retention_and_cleanup`
- error: `tests/integration/test_private_assets.py::test_asset_job_restart_and_wrong_tenant_reference`
- error: `tests/integration/test_private_assets.py::test_cleanup_survives_actor_revocation_and_restart`
- error: `tests/integration/test_private_assets.py::test_delete_during_upload_and_retryable_provider_failure`
- error: `tests/integration/test_private_assets.py::test_encryption_key_rotation_and_missing_key_fail_closed`
- error: `tests/integration/test_private_assets.py::test_expired_pending_asset_and_orphan_reconciliation`

### PowerShell 7 prerequisite

- error: `tests/config/test_tvt_domain_selection.py::test_foundation_excludes_only_dormant_domain_modules[switches0]`
- error: `tests/config/test_tvt_domain_selection.py::test_foundation_excludes_only_dormant_domain_modules[switches1]`
- error: `tests/config/test_tvt_domain_selection.py::test_foundation_accepts_only_registered_opt_in_extensions[False]`
- error: `tests/config/test_tvt_domain_selection.py::test_foundation_accepts_only_registered_opt_in_extensions[True]`
- error: `tests/config/test_tvt_domain_selection.py::test_foundation_rejects_unregistered_ignore_in_copied_script[tests/integration/test_tvt_unregistered.py]`
- error: `tests/config/test_tvt_domain_selection.py::test_foundation_rejects_unregistered_ignore_in_copied_script[tests/unrelated]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_requires_postgres_before_any_dependency_invocation`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_packet_is_explicit_and_acceptance_environment_is_scoped[None]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_packet_is_explicit_and_acceptance_environment_is_scoped[previous-value]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-count]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-deselected]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-wrong_module]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-failure]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-error]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-hidden_failure]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-hidden_error]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-hidden_skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-summary_skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-missing]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[None-exit]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-count]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-deselected]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-wrong_module]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-failure]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-error]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-hidden_failure]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-hidden_error]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-hidden_skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-summary_skipped]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-missing]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_rejects_unverified_packet_and_restores_environment[previous-value-exit]`
- error: `tests/config/test_tvt_domain_selection.py::test_domain_preserves_nine_role_url_requirement`
- failure: `tests/contract/test_foundation_selection.py::test_foundation_collects_ordinary_postgres_but_excludes_opt_in_native`
- failure: `tests/contract/test_foundation_selection.py::test_real_postgres_guard_rejects_selected_integration_skip[tests.integration.test_unexpected-True-True]`
- failure: `tests/contract/test_foundation_selection.py::test_real_postgres_guard_rejects_selected_integration_skip[tests.integration.test_unexpected-False-False]`
- failure: `tests/contract/test_foundation_selection.py::test_real_postgres_guard_rejects_selected_integration_skip[tests.contract.test_optional-True-False]`

### PowerShell builder executable absent

- failure: `tests/contract/test_windows_android_probe.py::test_fix2_reparse_staging_root_refused_without_touching_target`
- failure: `tests/contract/test_windows_android_probe.py::test_build_rejects_author_receipt_before_tool_or_extraction`
- failure: `tests/contract/test_windows_android_probe.py::test_packaged_library_inventory_checks_real_zip_content`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[timeout]`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[kill-failed]`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[inherited-pipe]`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[start-failed]`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[exit-failed]`
- failure: `tests/contract/test_windows_android_probe.py::test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership[capture-bound]`
- failure: `tests/contract/test_windows_android_probe.py::test_actual_builder_passive_owner_waits_for_inherited_pipes`
- failure: `tests/contract/test_windows_local_device.py::test_builder_refuses_author_receipt_without_tool_execution`

### Real loopback child startup/deadline/lifecycle assertion

- failure: `tests/tvt_parity/test_account_client.py::test_actual_loopback_tls_login_profile_renew_logout`
- failure: `tests/tvt_parity/test_account_flows.py::test_actual_owned_verified_tls_prelogin_register_and_separate_recovery`
- failure: `tests/tvt_parity/test_account_process.py::test_startup_and_blocked_large_pipe_write_share_deadline`
- failure: `tests/tvt_parity/test_account_process.py::test_real_child_https_success_private_bytes_and_clean_environment`
- failure: `tests/tvt_parity/test_account_process.py::test_real_child_https_failure_and_header_block_are_sanitized_and_settled[malformed]`
- failure: `tests/tvt_parity/test_account_process.py::test_real_child_https_failure_and_header_block_are_sanitized_and_settled[header-block]`
- failure: `tests/tvt_parity/test_account_process.py::test_real_child_https_failure_and_header_block_are_sanitized_and_settled[body-block]`
- failure: `tests/tvt_parity/test_account_process.py::test_child_reply_overflow_malformed_and_exit_fail_closed[import os;os._exit(7)]`
- failure: `tests/tvt_parity/test_directory_adapter.py::test_actual_process_verified_loopback_https_runs_six_readonly_source_requests`
- failure: `tests/tvt_parity/test_security_adapter.py::test_actual_contained_verified_https_all_eight_paths_and_cleanup`
- failure: `tests/tvt_parity/test_security_adapter.py::test_actual_https_uncertain_writes_tls_redirect_and_challenge[cancel]`
- failure: `tests/tvt_parity/test_security_adapter.py::test_actual_https_uncertain_writes_tls_redirect_and_challenge[redirect]`
- failure: `tests/tvt_parity/test_security_adapter.py::test_actual_https_uncertain_writes_tls_redirect_and_challenge[challenge]`

### Real original-child deadline/reap assertion

- failure: `tests/contract/test_windows_socket.py::test_parent_hard_deadline_owns_original_inert_process`

Update log: 2026-10-10 initial retained broad-gate triage. No confirmed
R196/R197 behavioral regression; red gate and unresolved original ownership,
credit-order and real-child timing assertions are preserved.
