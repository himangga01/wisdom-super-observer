# RETURN replacement SUB: retained-slot SQL binding gap

Analysis date: 2026-10-11, Asia/Seoul. **The existing-slot Core branch skips
the SQL operation that binds a new viewer lease to that slot.** This is a
concrete source mismatch with `viewer_admit`. Its attribution to the measured
replacement-start404 still requires the lead's realistic fake and full owned
SQL RED/GREEN sequence; this report claims no executed reproduction or fix.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted Stage1/2
and R193-R206 work. Coordinator and admission are untracked relative to HEAD.
Hashes below capture the source before the proposed slot repair. Read shared
policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[RETURN lifecycle map](2026-10-11-return-focus-causal-map.md),
[stale cancellation diagnosis](2026-10-11-stale-forward-focus-cancellation.md),
and [R206 review](2026-10-11-attached-focus-cleanup-fix-review.md).
Reuse before slot reuse/RETURN changes and update after causal proof or actual
acceptance. Root owns canonical handoff updates; only this report was written.

## New actual boundary and retirement

Root/lead report run `6db9d55ab7c347ccb63f2f1209404cfb` on the unchanged431-source
closure: early LOW21.805s/218frames and HIGH25.462s/259frames rendered.
Exact CDP progression was RETURNfocus200, MAINstop200, replacement
POST `/api/live-sessions`404, wallStop200, then newRETURNsettle200.
The obsolete old-FORWARD cancellation was absent. This advances past the
frontend failure measured in run5dd, but replacement SUB did not start.

Root then confirmed normal retirement of retained original exec95525:
coordinator exit0/reaped, context removed, source431 unchanged, known-private0,
API and worker settled, media observation COMPLETE and writer settled. This
normal run does not rewrite run5dd's FAILED exceptional cleanup history.
The live pins were released before this document was created.

Actual request/retirement facts above are supplied by Root/lead. This reviewer
did not open private runtime data, operate the browser/DB/processes or identify
the failing SQL predicate from live rows. A404 alone does not select ticket,
selection, reservation, admission or final attachment failure.

## Expected complete RETURN progression

The authenticated service retains one shared recorder slot while MAIN uses a
separate original. Returning uses a new SUB lease and fresh publication cut;
physical slot/task reuse does not reuse the old viewer's lease registration.

| Phase | Source contract |
| --- | --- |
| Reserve RETURN | SQL0016 FOCUS_ISSUE atomically consumes MAIN_ACTIVE and creates bounded PENDING RETURN; worker retains its exact grant. PENDING retains the base independently of whether source MAIN is still live. |
| Close MAIN | Both original viewer and dedicated-native receipts must settle. Source MAIN becomes CLOSED with cleanup_confirmed; the coordinator removes its dedicated entry. A normal MAINstop200 is the intended prerequisite for new SUB, not a condition to bypass. |
| Issue replacement SUB | API `local_media.py:185` issues a shared ticket before RPC. SQL SHARED_ISSUE at273 requires current wall, exact pending RETURN for channel/direction, no live replacement already attached to that reference, then legacy issue's current metadata/capacity checks. |
| Redeem/select/reserve master | Worker obtains a new lease, prepares its channel and uses MASTER_RESERVE at296. Rejoining a current original binds only the new lease's `mux_master_id`; it does not set its `mux_slot_id`. |
| Bind retained slot to new lease | SLOT_RESERVE at467 validates original master/wire/channel/slot and writes `mux_slot_id` on the new lease at492. An existing slot is reused; a new physical slot is not required. |
| Admit new viewer | VIEWER_ADMIT at531 requires the new LOGIN lease's `mux_slot_id` to select the exact SQL slot by its authority, same master/current slot, and no unsettled previous slot viewer. It assigns a fresh registration and CLAIMED state. |
| Fresh cut and activation | Core prepares a new viewer owner, starts its fresh ingress cut, verifies original slot/registration/proof, activates the new lease and checks current authority. |
| Complete RETURN | `settle_focus(ATTACHED)` requires the new accepted SUB and the source MAIN lease CLOSED with cleanup_confirmed. It cannot substitute for MAIN native cleanup or accept an expired/cancelled reference. |

Source MAIN being CLOSED is explicitly required by SQL FOCUS_SETTLE at745.
PENDING FOCUS_CURRENT does not require that old MAIN to remain live. No source
evidence justifies weakening current metadata or reviving the source lease.

## Concrete source mismatch

Coordinator `local_media_mux_service.py:_slot`, existing-slot branch near971,
checks `current_slot(existing.grant)` and returns the existing SlotRecord
immediately. It does not call admission `reserve_slot` on this path.
The new-slot branch does call it before opening the physical task.

The SQL contracts expose the missing step:

1. New lease creation does not initialize `mux_slot_id`.
2. MASTER_RESERVE writes `mux_master_id` only.
3. SLOT_RESERVE is the relevant authoritative operation that associates the
   new lease with the already retained SQL slot.
4. Core `attach` nevertheless calls `admit_viewer(viewer, slot.grant)` directly
   after the existing-slot return.
5. VIEWER_ADMIT looks up `s` by `l.mux_slot_id` and the supplied slot authority.
   If that new lease still has NULL slot binding, `s.id IS NULL` returns NULL;
   admission raises fixed DENIED for the absent row.

This explains a deterministic source failure for a fresh lease reusing a slot
without its SQL binding, including normal parked-slot reattachment beyond
RETURN. Cold SUB follows the new-slot path and does not omit this operation.
Matching the actual404 requires confirming that the measured call reached
this path; if API ticket issuance failed earlier, it needs separate evidence.

## Existing coverage and missing integrated proof

- Core `test_park_keeps_slot_identity_not_rgb:546` and
  `test_sole_forward_and_return_refs_cover_both_gaps:673` exercise reattachment
  with a fake admission whose `admit_viewer` builds a grant from the supplied
  slot without requiring a lease-to-slot association. They cannot expose the
  real SQL NULL-binding guard.
- Real SQL `test_main_active_return_consumed_atomically:914` proves MAIN_ACTIVE
  consumption, dedicated cleanup and new SUB ticket/redeem/master follower
  reservation. It stops after verifying the reused master. It does not execute
  slot binding, viewer admission, activation and RETURN settlement through the
  coordinator's existing-slot branch.
- Initial SQL slot setup calls `reserve_slot` explicitly before `admit_viewer`;
  that validates the individual ports but not Core's reuse orchestration.

The lead's next causal controls must therefore make the fake enforce the
per-lease association and execute the complete owned SQL RETURN progression,
not only the individual SQL helpers. Required preservation includes genuine
revocation, wrong original/channel/worker, occupied previous viewer, expired
RETURN and incomplete original MAIN cleanup.

## Capability and custody constraints for the repair

The physical slot's original epoch/channel/task must survive reuse. No repeated
native open, synthetic slot identity, arbitrary SQL assignment or viewer-grant
reuse is justified. Each replacement still needs a fresh viewer registration
and cut that excludes pre-cut ingress, with original credit/custody accounting.

`SqlMuxAdmission.reserve_slot` performs SQL validation even when it later finds
an existing slot grant in its retained registry. It may return the currently
retained capability for that SQL slot. The caller must validate and use the
returned grant rather than ignore it or assume every capability is the old
object. `_reservation` resolves the current transport capability from
`_master_grants`, so historical reservation identity is not permission to use a
superseded transport. Any source correction must preserve scope, exact slot/
original identity and existing refresh/attachment serialization across the SQL
callback. These are repair constraints, not an implemented patch here.

## Verification limits and source hashes

Only source/test/report reads, Git baseline/status and SHA256 inspection ran.
No tests, source/canonical edits, DB/runtime/hardware/browser operation, private
input, nested agent or commit. Actual causality and repair acceptance remain
pending the lead's controlled RED/GREEN proof, independent candidate review and
new replay. Historical R203 late slot denial, full duration/Stop/reconnect,
store2/twelve-camera/APK and broad-suite gaps remain separate open work.

| Pre-fix source | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `0cdf1c30c050d337b738fa12ef8d4c16ceb585839e8959465e2fe93d9aa7cf4f` |
| packages/core/src/wso_core/tvt/local_media_mux_admission.py | `9ca1bef6a7066968c8e4aedad17fb7a93b9b74918f79c0c8601c5f0c0ffd1c7e` |
| infra/migrations/versions/0016_tvt_device_media_epochs.py | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |
| tests/tvt_parity/test_local_media_mux_service.py | `e4720ef10ba5f9b1410adcf9d5d565fd0480f0cdb16b704ac3dba274f52cd54d` |
| tests/integration/test_local_media_mux_admission.py | `b3fb291c5a7cf2fe40ac63c6935a680e0a5a5f5d7895233d0f9afd195f4e06e5` |

Update log: 2026-10-11 source reuse/binding mismatch and coverage gap saved
after normal run6db retirement. No actual cause selection or fix claimed.
