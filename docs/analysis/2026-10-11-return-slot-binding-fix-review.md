# R207 retained-slot binding: independent SPEC and QUALITY review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0.** No remaining
source findings in the frozen four-path candidate. Approved for fresh reference
closure and actual replay; repaired RETURN playback and full service acceptance
are not established by these source/SQL controls.

## Baseline and scope

Worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, preserving existing uncommitted
Stage1/2/R193-R206 work. The reviewed source/tests remain untracked relative to
HEAD. All four paths match `r207-return-slot-fix-manifest.json` in the
established Stage2 workspace.

Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[normal R206 actual report](2026-10-11-r206-live-acceptance.md),
[slot causal map](2026-10-11-return-slot-binding-causal-map.md), and
[author report](2026-10-11-return-slot-binding-fix.md). Reuse before related
changes and refresh after new source or acceptance. Root owns canonical handoff
updates. Only this review was written.

The service returns from a separately owned MAIN original to a new SUB viewer
on the retained shared slot. Run6db reached replacement-start RPC404 after
RETURN200 and MAINstop200; obsolete cancellation was absent and original
retirement was normal. The product existing-slot branch omitted the per-new-
lease SQL association required by viewer admission. Realistic Core and owned
SQL controls now reproduce that omission and verify the correction.

## SPEC assessment

- `_slot(existing)` obtains the original prepared binding and retained master
  reservation, then invokes the existing authoritative `reserve_slot` for the
  **new viewer lease** and caller budget before `admit_viewer`. SQL SLOT_RESERVE
  validates original master, wire generation/session, requested channel and
  current retained slot, then sets the new lease's `mux_slot_id`. No direct
  assignment or bypass of SQL rights was added.
- Returned `rebound` must be the **same grant object** as `existing.grant`,
  with the existing slot identity and current master/slot checks still true.
  Copied, foreign and denied results reject. It returns the original SlotRecord
  and never calls native `open_slot` on reuse. Fresh viewer registration/cut
  and original custody/credits continue through the unchanged attach path.
- Verified admission semantics: `reserve_slot` validates SQL and original
  binding, finds the current retained grant by SQL slot ID, validates that
  exact registry record and returns it before `_remember`. SQL's existing-slot
  branch ignores the unused proposed random token/task. Thus the accepted reuse
  path creates no new capability requiring installation or retirement; the
  return value is checked rather than discarded. `_reservation` resolves the
  current transport grant while preserving the original reservation binding.
- The existing `record.opening` flag serializes slot work; normal attach also
  holds the attaching count. Heartbeat waits while either is set, so it cannot
  replace the retained grant midway through this association. No state lock is
  held across SQL. Current/master checks run before/after callbacks, caller
  cancellation/deadline remains enforced by admission SQL/budget, and the
  existing exception path fences the original while the finally block clears
  opening. No authority widening, timeout change or late replacement adoption
  is introduced.
- Exact byte reversal of only the new existing-slot block restores production
  hash `0cdf1c30c050d337b738fa12ef8d4c16ceb585839e8959465e2fe93d9aa7cf4f`.
  Admission remains `9ca1bef6...`,0016 remains `64e28f20...`; no SQL/admission/
  runtime source change accompanies this repair. Strict RETURN attachment still
  requires source MAIN CLOSED with both cleanup receipts and a current new SUB.

## Independent execution and retained SQL evidence

Fresh reviewer command, exit0: **15 passed,87 deselected in0.20s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_local_media_mux_service.py -q -p no:cacheprovider --tb=short -k 'park or sole_forward_and_return or last_detach_vs_attach or uncertainty_blocks_same_channel or heartbeat_swaps or return_expiry or cancelled or revoked'
```

The controls cover enforced per-new-lease binding, copied/foreign/denied returned
grants, no extra native open, retained physical slot and fresh registration,
parked heartbeat, original cleanup barriers and RETURN expiry. These Core
controls use inert admission/native ports, not actual recorder playback.

Read-only receipt inspection preserves the causal history:

- Owned SQL `4c450f8a5ccf4bb394d9478a179f9794`:1 test,1 failure,0 error/skip,
  exit1 at the missing-binding admission boundary; normal original/DB/source/
  privacy cleanup recorded. Author Core RED and subsequent GREEN are separately
  documented author evidence.
- Original final run `62b0f1310adf4468b5ef68e693c5558c`:5 passed with normal
  cleanup, but review found the integration test hash was `1478fcc2...`, not
  frozen `b45fc0a7...`. The lead identified post-run Ruff/import formatting.
  This receipt was preserved and was not treated as exact-frozen proof.
- Required replacement run **`e657388442804f80a3fcc2c407c5737a`**:5 passed,
  zero failures/errors/skips, exit0. Reviewer verified every receipt source pin
  against current files and the three overlapping frozen source/test entries;
  all match. Original child reaped, owned DB removed, source DB equality,
  source pins unchanged and zero known private occurrences are true. Receipt
  SHA256: `7347b467bae81a6b69af9eb95cbc6bff38a98f1b641e938e1eb92447c864ee49`.

The owned SQL test executes the actual product `_slot` method using real
SqlMuxAdmission and SQL lifecycle ports. Its coordinator record/current/fence
ports and original native custody are inert test fixtures. It covers original
SUB/FORWARD/MAIN, RETURN consumption, both MAIN receipts, new SUB ticket and
master join, slot association, viewer admission/activation, RETURN ATTACHED and
strict settlement-current. Foreign/revoked channel cases reject; retained-slot
revocation and original-binding replacement controls also pass. This closes
the earlier SQL-port coverage gap without claiming full native/coordinator/
browser end-to-end acceptance.

The author's163 Core/runtime passes and static gates remain author evidence,
not rerun wholesale. No extra DB execution was performed by this reviewer;
the lead ran the same five required SQL cases only to resolve the concrete
test-pin discrepancy. Frozen author report remains unchanged; this review
records the newer exact-source receipt.

## Limits and next gates

Fresh immutable references and actual early RETURN replay remain next, followed
by LOW/HIGH duration, transitions, Stop/reconnect, store2 and normal original
cleanup. The previous normal6db retirement does not qualify a new run or repair
historical5dd exceptional limits. R203169.56s slot denial remains unmeasured;
twelve-camera/APK, broad7816/runtime typing and publication gates remain open.
No source/test/runtime/DB/hardware/browser mutation, private input, nested agent
or commit occurred during this review.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `c324bc1eb0c9c44b1153380a95ab29ebcae1448c6148ef74f6514a5574ffa5b8` |
| tests/tvt_parity/test_local_media_mux_service.py | `0c32a4f9d779aef473d015477e1a709c470f5a60f80b0c3fdaaa020975da44d1` |
| tests/integration/test_local_media_mux_admission.py | `b45fc0a741bdf1295f428d35fa993d37a576129d73577bb8bc62f71df1cc987d` |
| docs/analysis/2026-10-11-return-slot-binding-fix.md | `f0ae53a45e1ac6133536d78828c84865354ced4905091eb2cf883f78a12b6f88` |

Update log: 2026-10-11 frozen R207 SPEC/QUALITY C0/I0/M0,15 reviewer Core
passes and exact-frozen e657 SQL5 verified. Pre-format62b0 history preserved;
actual repaired RETURN acceptance pending.
