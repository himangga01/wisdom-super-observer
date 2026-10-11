# R197 replacement transport retirement review

Analysis date: 2026-10-10, Asia/Seoul. Independent SPEC and QUALITY review.

## Verdict and source baseline

**SPEC: PASS. QUALITY: PASS. Findings: C0/I0/M0.** The exact frozen admission
bookkeeping fix satisfies the requested conditional retirement repair. This is
source approval with inert controls; it does not establish the historical inner
heartbeat exception, authentic native cleanup, owned SQL acceptance or stable
MAIN/SUB/twelve-camera playback.

The service delivers authenticated TVT recorder video through browser/API/media
workers. `SqlMuxAdmission` retains exact grant records and original issuers;
native epoch cleanup and viewer cleanup have separate receipt authority.

Implementation worktree branch: `codex/superlive-web-service`, Git HEAD remains
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Existing modified/untracked Stage1/2,
R193/R194 and R196 source/reports were preserved. Exact review diff baseline:
`712b1b5bde076923110410e43137b2a038dbcafa`; candidate review tree:
`5ce223fd5e41cdcab4774b33095070d74b523255`. Review-tree identifiers are not a
new branch commit or complete immutable runtime approval.

Read the shared analysis policy, current project AGENTS and service report,
[heartbeat exception proposal](2026-10-09-wall-heartbeat-refresh-exception-proposal.md),
exact R197 brief/diff/hash manifest, full affected admission methods, existing
Core heartbeat/retirement barriers, causal tests, and finalized
[author report](2026-10-10-replacement-transport-retirement-fix.md) and local
execution handoff. This reviewer writes only this review report. Root owns
AGENTS/service cross-links and immutable native/source approval reissue.

## Requirement and quality review

The existing `finish_epoch` verifies exact registered grant identity, authentic
retained original issuer and bound callback identity, exact receipt object,
master, worker epoch and native generation. Its recheck after calling the issuer
remains unchanged. SQL `epoch_close` must return successfully before closure
bookkeeping proceeds. Receipt checks or SQL failure do not close the orphaned
replacement transport. The supplied record's earlier denial remains the existing
conservative behavior.

The production delta is confined to
`packages/core/src/wso_core/tvt/local_media_mux_admission.py:1457`: post-SQL
related-record selection now matches exact master ID, retained native generation
and grant worker epoch. Each selected record is retired as before, and exact
`TransportGrant` variants now close alongside `SlotRetentionGrant`. This covers
one or several successful admission refreshes that Core did not publish because
native replacement failed. Closure uses the confirmed original epoch receipt;
no new native/viewer receipt or authority is invented.

Matching `ViewerGrant` records remain denied but open until their independent
viewer receipt settles. Other master/native/worker records remain open and are
not denied by this epoch's receipt. Dedicated settlement, pending attempts,
startup custody, public guards, timeout policy, SQL migration/payload and
provider/runtime behavior are unchanged.

Race review considered `finish_epoch`'s related-record snapshot, refresh
registration and disposal. Existing `_refresh_current_grant` rechecks denied,
closed, denied-master and `_mux_closed` under `_mux_lock` before registration.
`dispose` tests every retained record for closure under that same lock and sets
`_mux_closed` before shutdown. A new open record registered after a retirement
snapshot conservatively blocks disposal; a registration after successful
disposal cannot pass `_mux_closed`. A selected record must be retired before
this patch marks it closed. No new false settlement route was identified.
This is source reasoning, not an exhaustive concurrency model or a new
interleaving acceptance test. The patch preserves existing Core/provider
refresh and original-custody barriers; it does not claim admission-wide atomic
retirement for arbitrary direct concurrent internal calls.

The new controls exercise real admission registration, refresh, retirement,
current-state checks and disposal with inert SQL/observation/original-issuer
ports. They test repeated refresh, pending/wrong/copied/changed-issuer receipt,
SQL failure and retry, foreign master/native/worker, slot closure and unresolved
viewer retention. Existing selected controls retain exact-object/reentrant
issuer rejection, failed-refresh denial, original pending custody and unresolved
attempt guards. No material issue was found in the required source scope.

## Independent verification and frozen identity

Reviewer executed the following affected gates using the existing interpreter,
without pytest cache or Python bytecode writes:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_replacement_transport_retirement.py tests/contract/test_final_mux_handoff_refresh.py -q -p no:cacheprovider --tb=short
```

Result: **53 passed in 1.38 seconds, exit 0**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/integration/test_local_media_mux_admission.py -q -p no:cacheprovider --tb=short -k 'copied_or_foreign_grant or viewer_receipt_cannot_close_epoch or shutdown_does_not_dispose or original_binding_copies or refresh_failure_fences_exact_master or observed_slot_denial_overrides_cached_master or recovery_attempt_is_local_exact_and_inflight'
```

Result: **10 passed, 88 deselected in 0.14 seconds, exit 0**. Selected admission
cases use inert fixtures; database-backed acceptance cases were deselected.

The author's causal RED (7 failed/6 passed), GREEN (13 passed), Ruff and one-file
mypy results were read as historical author evidence. This reviewer did not
replay RED by changing source or rerun static/full-project gates. Focused fresh
verification is sufficient for this narrow post-SQL bookkeeping change.

`Get-FileHash -Algorithm SHA256` independently confirmed source/test match the
frozen manifest and finalized author artifacts:

| Artifact | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `24d50682aab235ca89212d70ab2275548c48305eee32713a844a20945dcd952a` |
| `tests/contract/test_mux_replacement_transport_retirement.py` | `b194e2e7e05e90f2ab5e003dab4cca2f13758b2a31bf5e788d8972bb0d710ef4` |
| Portable author report | `5c3be869cc509d753576b5a34bcc91fa7dc333e8d19decb31274537fb7ffd831` |
| Local author handoff | `23421a4b26147df568f4c8cc5f0132297a80103b9c2ae45fd75c96ac70e1bafc` |

## Limits and next authority

No private runtime input, credentials, DB connection, real SDK/recorder child,
browser or process cleanup was accessed or performed. Inert engine objects are
constructed lazily and disposed without opening a connection. No source,
receipt, approval, runtime/provider, migration, ignore or dependency artifact
was changed by this reviewer; no commit, extra agent or optional broad suite
was performed.

The conditional orphaned transport defect is source-proven and its admission
bookkeeping is repaired by these controls. Whether that defect contributed to
the historical incomplete runtime remains unknown. The initiating maintenance
exception still requires reviewed R196 measurement in a newly owned run.
Root must issue the fresh source/native chain and execute owned SQL followed by
real HIGH/LOW, stop/reconnect and cleanup gates. Preserve prior interrupted
receipts as historical evidence. Real cleanup and stable playback must be
reported separately from this source verdict.

No product contract decision is required for this fix. Full-duration stability,
twelve-camera acceptance and APK comparison remain open in the canonical
service report. Priority is Root's immutable approval and bounded actual
execution, followed by updating service/handoff evidence.

Update log: 2026-10-10, frozen R197 SPEC+QUALITY review, independent 53+10
affected cases and source/report hash confirmation; C0/I0/M0. Read with the
author/proposal before further transport-retirement changes and refresh after
new source or executed original/SQL acceptance.
