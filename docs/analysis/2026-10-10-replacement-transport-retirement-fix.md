# R197 replacement transport retirement fix

Date: 2026-10-10, Asia/Seoul. Status: source candidate, awaiting independent
review and Root execution gates.

Baseline: `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, retained uncommitted Stage1/2 and
diagnostics; supplied immutable tree `712b1b5bde076923110410e43137b2a038dbcafa`.
The worktree already contained extensive retained tracked and untracked source,
tests and reports. This task changes only the admission source, one new causal
test file and its two reports. R196 diagnostic source is separately owned.

Read before reuse and update after new source review or executed acceptance.
References: [service report](../service-analysis.md), [heartbeat exception
proposal](2026-10-09-wall-heartbeat-refresh-exception-proposal.md), project
`AGENTS.md`, shared analysis policy and the exact local R197 brief. Root owns
canonical service/handoff/AGENTS reconciliation after this disjoint handoff.

## Purpose, cause and implemented change

The service delivers authenticated local TVT recorder video through API/media
workers. `SqlMuxAdmission` owns exact retained grant identities and registered
original issuers. Native epoch retirement and viewer retirement use distinct
receipts, while `dispose()` refuses any retained unsettled record.

Admission refresh registers a fresh `TransportGrant` before Core publishes it.
Native replacement can raise between those operations. Core then retires using
its retained old transport. Previously, `finish_epoch(old, exact_receipt)` closed
the old transport and slot retention but left the fresh transport open, keeping
real `SqlMuxAdmission.dispose()` false even after that epoch's SQL close.

The change is confined to post-SQL epoch bookkeeping in
`packages/core/src/wso_core/tvt/local_media_mux_admission.py:1457`. After the
unchanged exact original issuer/receipt checks and successful `epoch_close`,
related records must match master ID, native generation and worker epoch.
Those records are denied as before. Exact `TransportGrant` and
`SlotRetentionGrant` records become closed. `ViewerGrant` remains unsettled,
requiring its independent original viewer receipt. No receipt is fabricated.

Original callback identity checks, exact-object registration, SQL payload,
pre-SQL retirement of the supplied old record and startup-charge release remain
unchanged. No provider/runtime, SQL migration, timeout, public API or receipt
file changes were made. Comparison with the supplied tree confirms the only
production delta is the related-record filter and transport closure predicate.

## Causal verification

The new `tests/contract/test_mux_replacement_transport_retirement.py` exercises
real `register_original`, `refresh_grant`, `finish_epoch`, `current_*` and
`dispose`. Lazy engine construction uses an unused URL; no connection is opened.
Only SQL IO/observation and native-original issuance are inert seams. The tests
reuse the established synthetic original issuer and exact receipt fixture.

Before source edits, the new file produced **7 failed, 6 passed**. Failures
showed the actual replacement record remained open after finishing the old
transport, or actual disposal remained false after successful SQL-close retry.
There were no collection/setup errors. After the narrow fix it produced
**13 passed**.

The controls prove:

- One and three sequential refreshes settle when the exact original receipt
  retires the old Core handle. Disposal is false before retirement and true
  afterward when no other record is pending.
- Pending original receipt, receipt copy, wrong master/native/worker and replaced
  issuer method all deny closure, leave the fresh transport open and retain
  disposal false.
- SQL close failure leaves fresh transport open. Retrying the same exact receipt
  after the inert SQL seam succeeds permits disposal.
- Other-master records and same-master records with a foreign native generation
  or worker epoch remain **open and not denied** by this receipt. Their retained
  records still block disposal. These synthetic registry controls verify scope
  isolation without claiming those foreign objects are current live authority.
- A matching slot retention closes, while a matching `ViewerGrant` stays open
  and becomes unusable. The unresolved viewer keeps disposal false.

Commands use `.venv/Scripts/python.exe -B`:

```text
-m pytest tests/contract/test_mux_replacement_transport_retirement.py -q
  RED: 7 failed, 6 passed; GREEN: 13 passed
-m pytest tests/contract/test_mux_replacement_transport_retirement.py tests/contract/test_final_mux_handoff_refresh.py -q
  53 passed
-m pytest tests/integration/test_local_media_mux_admission.py -q -k 'copied_or_foreign_grant or viewer_receipt_cannot_close_epoch or shutdown_does_not_dispose or original_binding_copies or refresh_failure_fences_exact_master or observed_slot_denial_overrides_cached_master or recovery_attempt_is_local_exact_and_inflight'
  10 passed, 88 deselected; all selected cases are inert
-m ruff check packages/core/src/wso_core/tvt/local_media_mux_admission.py tests/contract/test_mux_replacement_transport_retirement.py
  All checks passed
-m ruff format --check packages/core/src/wso_core/tvt/local_media_mux_admission.py tests/contract/test_mux_replacement_transport_retirement.py
  2 files already formatted
-m mypy packages/core/src/wso_core/tvt/local_media_mux_admission.py
  Success: no issues found in 1 source file
```

An initial Ruff run reported redundant `return None` in the test-only SQL seam;
it was removed and the listed final static gates passed. The final focused
commands include the formatted final test artifact. No full suite, owned SQL,
hardware, browser or private input ran in this task, per ownership instructions.

## Candidate identity and remaining limits

SHA256 of admission source:
`24d50682aab235ca89212d70ab2275548c48305eee32713a844a20945dcd952a`.
SHA256 of causal tests:
`b194e2e7e05e90f2ab5e003dab4cca2f13758b2a31bf5e788d8972bb0d710ef4`.
Baseline tree admission blob SHA256:
`7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999`.

This establishes conditional admission bookkeeping repair under inert seams.
It does not establish the historical runtime's inner exception, actual native
settlement, normal cleanup of any interrupted run, continuous MAIN/SUB playback,
twelve-camera acceptance or APK parity. Concurrent refresh/retirement lifecycle
coordination remains owned by the unchanged Core/provider barriers. Independent
source review, fresh immutable native/source chain, full suite, owned SQL and
hardware/browser acceptance remain Root gates. No commit or private runtime
operation was performed.

Open product questions remain those in the canonical service report; this
bookkeeping patch changes no product contract. Priority is narrow independent
review followed by Root execution before any live-repair claim.

Update log: 2026-10-10, R197 causal RED/GREEN and affected/static gates recorded;
source candidate handed to Root for fresh review and executed acceptance.
