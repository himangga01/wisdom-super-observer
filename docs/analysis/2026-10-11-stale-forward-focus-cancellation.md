# Stale FORWARD cancellation blocks RETURN before LOW starts

Analysis date: 2026-10-11, Asia/Seoul. **The measured404 is cancellation of
the old FORWARD reference, not a wall heartbeat.** The frontend retains an
attached reference, cancels it again when stopping MAIN for RETURN, then treats
the resulting settlement failure as an unresolved dependency of the new LOW
start. CDP correlation from run5dd confirms the old-reference association.

Baseline: implementation worktree `codex/superlive-web-service`, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with pre-existing uncommitted
Stage1/2/R193-R205 work. Both the measured application and cleanup diagnosis
used the unchanged421-source closure. This report was written only after Root
released the runtime pins. Pre-R206 source hashes captured at writing are below.

Read policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[R204 acceptance](2026-10-11-r204-live-acceptance.md),
[RETURN backend causal map](2026-10-11-return-focus-causal-map.md), and
[R205 source review](2026-10-11-main-return-retention-fix-review.md).
Reuse before frontend focus/cleanup changes and update after reviewed source
or actual acceptance. Root owns canonical handoff updates. No previous report,
application source or frozen evidence was changed by this analysis.

## Measured request sequence

Root/operational lead supplied the exact CDP request correlation for
`5dd75c3db33946b2a9f8b7e382b03d2a`, on the same421-source candidate:

| Order | Measured result |
| --- | --- |
| Reserve RETURN | 200 |
| Settle old FORWARD | 404; exact old-reference match confirmed |
| Settle newly reserved RETURN | 200 |
| Stop wall | 200 |
| Stop MAIN | 504 |

LOW did not start. The old backend current/refresh failure signatures were
absent: no initiating Core current=false, grant=false, inner-refresh, READ or
background mux exception. Normal prior SUB closure and intentional stop-wall
fencing do not identify a new native/parser failure. The observed later MAIN
Stop timeout is a separate cleanup outcome.

The initial shorthand "wall404" described a wall-route response without its
full operation. The new exact CDP correlation selects `focus_settle` of the old
FORWARD reference. This precision applies to run5dd; it does not retroactively
reclassify R204's historically recorded route or prove every earlier RETURN
failure had this frontend cause. The older R203169.56s slot denial remains
unmeasured. R205's independently approved backend retention/race fixes are a
separate source result, not evidence that all RETURN layers were complete.

## Source chain matched to the measurement

The authenticated service separates short pending focus references from
established viewer/native ownership. SQL cancellation accepts only a current
PENDING reference; an attached MAIN must be stopped through its original viewer
and native lifecycle.

1. `apps/web/src/features/monitoring/live-wall.tsx:335` stores the FORWARD
   reference in `playerRefs` for the replacement MAIN. On accepted startup,
   `attached:260` calls `group.attached` and resolves attachment. The group
   clears the pending timer and sets `pending=false`, but keeps its reference
   record. `playerRefs` also keeps the reference.
2. RETURN successfully reserves a new reference. SQL0016 FOCUS_ISSUE at629
   has atomically changed the old MAIN_ACTIVE FORWARD to CONSUMED and inserted
   PENDING RETURN. Frontend focus code at443-450 records the new transfer and
   tells the scheduler to stop/restart the old player.
3. `onStop:352` retrieves the old player's FORWARD reference. Line363 calls
   `group.cancelFocus` unconditionally for that reference. It is not the new
   RETURN held in the transfer map.
4. `live-wall-group.ts:141` returns an existing closing promise if present,
   but otherwise sends settlement even for a positively attached record whose
   `pending` flag is already false. SQL0016 FOCUS_SETTLE_ISSUE at839 selects
   only `state='PENDING'` and unexpired references. The consumed old FORWARD
   therefore cannot yield a settlement ticket and the API returns404 before a
   worker settlement call. This matches exact-old-reference CDP evidence.
5. `onStop:364-365` adds that promise to `stopping` and removes it only on
   success. The replacement player's `begin:339` waits for all original stops;
   a rejected settlement makes it report a handoff failure before calling
   LOW `player.start`.
6. The focus catch at455-456 cancels the genuinely pending new RETURN. Card
   failure handling invokes Stop All. These source paths match the measured
   newRETURNsettle200 and wallSTOP200 following the oldFORWARDsettle404.

The frontend's decision to send a new cancellation is wrong for the known
attached old reference. The strict SQL pending-only cancellation contract is
consistent with its existing lifecycle. Accepting arbitrary CONSUMED references
or broadly ignoring404 is not justified by this evidence.

## Cleanup invariants for the narrow R206 correction

Positive attachment, pending reservation and uncertain cleanup must stay
distinct. The existing Boolean `pending=false` can mean attachment, a timeout
handler that flipped the flag before cleanup, or a cancellation already started.
A blanket early return for all false flags would lose required cleanup paths.

- A positively attached old reference must not initiate a new pending-focus
  cancellation merely because its MAIN player is stopping for RETURN.
- An already-started cancellation retains its exact original promise and
  result. Replacing or swallowing it cannot certify cleanup.
- A still-pending replacement, cancellation during reservation, late response,
  expiry or unknown in-flight reservation retains its existing bounded cleanup
  obligations. Removing stale attached references cannot suppress those paths.
- MAIN viewer/native Stop must still settle before LOW starts. The fix cannot
  remove failed native Stop promises, bypass custody or declare them successful.
- Tests should model the backend state machine: settlement is accepted for
  eligible PENDING references and rejected for attached/consumed references.
  Existing shared-wall mocks return CLOSED for settlement without enforcing
  that distinction (`live-wall.test.tsx:124`, `live-wall-group.test.ts:15`),
  concealing this specific integration failure.

Lead owns R206 frontend cancellation and API route-enumeration changes/TDD.
This report adds no implementation, guard relaxation or unexecuted test claim.

## Exceptional cleanup outcome, separate from the frontend cause

Normal shutdown retained original exec48233, but API exit0 did not imply
worker retirement. The saved pre-force worker state had exit=null,
original_reaped=false, job_empty=false, writer_settled=false,
custody_retained=true, incomplete=true, failed=false. Context and owned DB
were preserved while that original remained outstanding.

Root subsequently reports positive creation/bootstrap/parent/Job identity for
the exact current original and termination through its retained handle. Worker
exit97 and the original coordinator's natural exit1 are **FAILED exceptional
termination**, not normal COMPLETE. Context removal, owned DB cleanup/source
content equality, known-private0 and source421 unchanged were confirmed by
the lead. `workerSettled` remains false; observation was not COMPLETE. A final
worker Job receipt was not persisted after context cleanup removed its working
location. The pre-force copy and exceptional-worker-termination artifacts are
retained. Do not fill that missing receipt with inferred normal custody proof.

Read-only cleanup source analysis found no simple rule requiring an ACTIVE
base grant to close dedicated MAIN: coordinator `_original_current` checks
retained object/method identity, and admission `finish_dedicated`/viewer use
cleanup owner identity. Potential retained gates include in-flight worker calls,
original peer/source stage settlement, native owner/IPC/Job completion, SQL
receipt delivery and admission bookkeeping. None was matched to an exact live
wait in this analysis. `writer_settled=false` alone is not a writer root cause:
the supervisor's healthy close path can retain the newer close-writer flag
while waiting for child exit. Earlier unrelated PID/approval history is not
authority for any later runtime operation.

## Verification limits and source baseline

This reviewer read source, existing tests/reports and Git/hash metadata; no
tests, DB/hardware/browser/process actions or source changes were performed.
The request correlation and exceptional cleanup facts are attributed to
Root/lead's actual observations. No raw CDP credentials, GUIDs, media or private
exception text were exported. No report was written while runtime pins were
active. The next gate is reviewed R206 source plus actual RETURN/Stop/reconnect
and normal original cleanup; other store/camera/APK acceptance remains open.

| Pre-R206 source | SHA256 |
| --- | --- |
| apps/web/src/features/monitoring/live-wall.tsx | `c300c1436208ed6a466e0755dc15d05b2192d0ef9a8ef63479161c6812db6220` |
| apps/web/src/lib/tvt/live-wall-group.ts | `6bff8ed41244c957567f7db2e1a2ecb79085e855331222eec4b4365a2c89342a` |
| apps/web/src/lib/tvt/local-live-player.ts | `3e34a933aa8d62434ef9988aade8f45f763eaae7dbdc071835587b24f5fbc4ac` |
| services/api/src/wso_api/tvt/local_media_mux.py | `9b823ae281b90d5f9ccdd09a4c0c87c804c71bf4ce78b8144197faf85428d42f` |
| infra/migrations/versions/0016_tvt_device_media_epochs.py | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |

Update log: 2026-10-11 matched old-FORWARD cancellation source/CDP sequence
saved after exceptional original retirement. Frontend fix and normal cleanup
acceptance are pending; prior backend findings and failed receipts preserved.
