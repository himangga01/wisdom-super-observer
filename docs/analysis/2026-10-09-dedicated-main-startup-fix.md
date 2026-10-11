# Dedicated MAIN startup authority correction

Date: **2026-10-09 (Asia/Seoul)**. Scope: the two-file startup phase correction,
focused inert verification and prepared owned-SQL cases. Independent review,
real SQL and repaired recorder/Chrome acceptance remain controller gates.

Current checkpoint: the controller's first owned-SQL gate passed seven cases
and failed only the expired-focus fixture setup. The test-only R1 correction
below is frozen pending the controller's rerun; production code is unchanged.

Read before work: shared analysis policy, worktree `AGENTS.md`, canonical English
service report, mux admission guide, Oct 9 API/Core debug reports/reviews and
[diagnosis](2026-10-09-dedicated-main-startup-diagnosis.md), SHA256
`5b078f74f5c089052febf9ca3f3abc09ac1c17a439aa9e2b3f2cd0582aeaaa30`.
Systematic debugging, test driven development and verification skills were used.
Controller owns canonical report/AGENTS/guide updates, receipt refresh and execution.

## Baseline and defect

Worktree `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with extensive existing retained
Stage 1/2 tracked modifications and untracked source/tests/reports. The primary
checkout lacks this implementation baseline. Before this correction admission
was `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797`,
provider `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f`.

The service presents authorized CCTV channels in Chrome. Dedicated MAIN startup
follows registered original custody and a pending FORWARD focus, then native
proof, lease activation and publication. The established defect is that startup
used activated hot authority while preparation had committed `CLAIMED`; observe
returned NULL and permanently denied the lease before native work. The diagnosis
and service report retain controller evidence for failed actual run `ba37feae`.

## Implemented contract

`SqlMuxAdmission.current_dedicated_startup(lease, registration, selection, *,
budget, retired_native_receipt=None)` checks the exact known lease, same retained
dedicated record, unchanged native/viewer issuer methods, retained UUID
registration, worker scope, expected MAIN channel and budget before/after the
existing short `viewer_selection` SQL query. Existing locking predicates validate
current wall, pending FORWARD focus, retained master and complete actor/session/
device/secret/channel scope. Checkout returns before native I/O. Normal startup
requires no native or viewer cleanup receipt. NULL/error, changed selection,
custody, cancellation/deadline or known denial fails closed; query/postcheck
failure retires the exact lease through the existing tombstone path.

Selection does **not** project SQL registration equality: this port relies on the
existing one-shot `dedicated_register`, non-NULL registered MAIN predicate and
exact retained registration. No SQL migration or competing setter was added.
A successful startup check seeds no hot cache, claim, proof or activation.
`LocalMediaAdmission.current`/`_authority`, sticky denial, freshness and later
activation/publication remain unchanged.

`PreparedDedicatedMain.start` uses that predicate for actual native-run current
checks and the immediate handoff postcheck. Original owner, custodian, issuer,
registration, proof and cleanup identities are preserved.

**R193a:** preserve original login-BUSY classification after confirmed cleanup.
The provider captures the existing `close_native` return once. Only after the
existing original `recover_retired_login_busy` result and `protocol`/`closed`
failure does classification readback receive that exact receipt. It must be the
same retained issuer's `EpochCleanupReceipt`, `REAPED`, with matching lease ID,
worker/native generation and no viewer receipt; all registration/selection/
budget/denial guards still apply. Missing, copied, foreign and `NOT_CREATED`
receipts fail. Normal native I/O never passes this option. Classification grants
no revived I/O/live authority, and no extra close/current retry was added.

## Initial R0 verification and limits

Causal RED, before startup production changes:
`python -B -m pytest -q tests/contract/test_dedicated_main_startup_authority.py -k claimed_dedicated_start`:
**1 failed, 17 deselected** at the intended assertion: native review was never
reached (`[]` versus checkout-free `[0]`). Initial correction: **18 passed**.
R193a preservation RED then observed actual prepared fallback returning 404
instead of expected known-original BUSY 429; it passed after exact-receipt readback.

Final commands used `.venv/Scripts/python.exe -B`:

```powershell
-m pytest -q tests/contract/test_dedicated_main_startup_authority.py tests/contract/test_local_live_mux_provider.py tests/tvt_parity/test_local_media_authority_gate.py
-m pytest -q tests/integration/test_local_media_mux_admission.py --collect-only -k dedicated_startup_authority
-m ruff check packages/core/src/wso_core/tvt/local_media_mux_admission.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py tests/contract/test_dedicated_main_startup_authority.py tests/contract/test_local_live_mux_provider.py tests/integration/test_local_media_mux_admission.py
-m ruff format --check packages/core/src/wso_core/tvt/local_media_mux_admission.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py tests/contract/test_dedicated_main_startup_authority.py tests/contract/test_local_live_mux_provider.py tests/integration/test_local_media_mux_admission.py
-m mypy --follow-imports=silent packages/core/src/wso_core/tvt/local_media_mux_admission.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py
```

- **92 passed, 0 failures/skips, 1.91 s**: 24 new composed/negative controls plus
  existing custody/coexistence and sticky-denial/freshness controls. New tests
  exercise actual admission redeem/register/prepare/decrypt/selection/SQL/hot
  authority and actual prepared/native-run guards, with fake SQL results and a
  native-review sentinel before OS resource acquisition. Inert cleanup and raw
  credit refund are checked. BUSY fixtures explicitly model a known result and
  REAPED receipt; they do not prove actual native BUSY/reap.
- New negatives: copied lease, registration, selection/stream/worker scope, SQL
  denial, cancelled/expired budget, closed custody, hot denial and custody/issuer/
  budget/retirement changes during SQL. Existing provider fixture now delegates
  startup to its existing `current` overrides, preserving negative controls.
- **Eight integration cases collected only** (8/98, 90 deselected): CLAIMED
  startup/zero checkouts then real activation/current; cancelled/expired focus,
  revoked session, disabled channel, foreign lease, registration and selection.
  New cases clear the historical fixture's eagerly stored future viewer receipt
  to `None`, representing unsettled custody; historical helper is unchanged.
- **Ruff5, format5 and strict mypy2 passed.** Initial format check required three
  files to be formatted; final checks passed. Scoped diff whitespace check passed.
- No database fixture, recorder, native DLL, native child/Job or browser was run.
  Fake SQL proves phase composition, not PostgreSQL predicates/locks. No full
  project suite or optional broad testing was run, per controller scope.

## Initial R0 frozen files and next gates

| File | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `f48373ce7861106a72901165177fede2d3da31a0a7ff9d658a2c16d29398cf33` |
| `tests/contract/test_dedicated_main_startup_authority.py` | `a6a3d4fceca2529013ee1333ee1ebc5d0e517b212481a80870af62400d4d5682` |
| `tests/contract/test_local_live_mux_provider.py` | `a15803b23f3c9b9085bc3bbd42ce348442eb182676fb2b88c078bf9b0fc71a51` |
| `tests/integration/test_local_media_mux_admission.py` | `b1ed2895f230cf41368640fcca4e3f5ab9b2f324e1db17d0df8699ed42d21899` |

Rechecked unchanged: hot admission `60286cf0edf5b0582df73df52ec5a0e343ed6ddb374c4485da47494a27969284`,
0016 migration `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92`,
Windows provider `1ad25ee670dde8397872dc38f3909baca1bac53a8b304f118d6786161fe375fb`.
No source beyond the two production files and three test files was changed;
no stage/commit/reset/push, private input or historical receipt was touched.

Priority P1: independent source review; existing guarded owned-SQL runner with
`-k dedicated_startup_authority`; new source/native/runtime receipt authority;
actual low PLAYING → HIGH MAIN start/offer/PLAYING → return/stop/confirmed cleanup.
Old pins cannot authorize changed files. Real MAIN formats, coexistence,
continuous/multichannel/twelve-camera performance and APK parity remain open.
No new product decision is required for the approved transfer behavior.

Update log: 2026-10-09 — scoped correction, causal RED/GREEN, R193a preservation,
92 inert passes/static and eight unexecuted SQL cases frozen for review.

## 2026-10-09 R1 expired-focus fixture correction

Controller owned-SQL run `e592dd93673c49dc92227990dd6dd7df` executed the eight
cases: **7 passed, 1 failed, 0 errors/skips**, with normal original/owned-DB/
source cleanup and known private occurrences 0. This is controller evidence;
the author executed no DB fixture. The failed case was
`test_dedicated_startup_authority_rejects_changed_binding_or_sql_scope[focus_expired]`.
Its setup used separately evaluated `clock_timestamp()` samples for issued
30 seconds ago and expiry 10 seconds ago, producing a 20.000010-second span
which violates the existing maximum 20-second focus lifetime constraint.
The failure occurred before the production startup predicate. Actual positive
CLAIMED/activation and six other negative predicates passed in that run.

R1 changes only that fixture's expiry to **15 seconds ago**, leaving approximately
15 seconds of issued-to-expiry span and a five-second constraint margin. The
focus remains expired. The existing failed receipt and R0 hashes above remain
historical authority; the initial report SHA was
`b628e87d6f3214de1846ca837bb87ac02a79b27f3328eb30dd50dbcc700375ef`.
No production file, SQL migration, other fixture or acceptance receipt changed.

Local R1 checks: focused collection again found **8/98 cases, 90 deselected**;
Ruff and formatting passed for the single changed integration file. No SQL or
optional test rerun was performed. Corrected actual SQL acceptance remains open
until the controller reruns the same guarded eight-case selection.

Revised integration SHA256:
`a9a0f31109d2125a6f8f50084b3fbd1a27afeb2ccc02c65739a4035098f461fb`.
All production and other test hashes remain the R0 hashes above.

Update log: 2026-10-09 R1 — preserved failed owned-SQL receipt, corrected only
expired-focus fixture lifetime margin, collected/static verified and froze for
test-only review and controller SQL rerun.
