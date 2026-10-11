# Slot-retention refresh causal map

Analysis date: 2026-10-11, Asia/Seoul. Read-only preparation for the next
measured failure. **No new source-proven playback defect is established.**
The parked slot is explicitly renewed; the next original refresh traceback
must select a branch before a repair is justified.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted Stage1/2
and R193-R204 work. The four main inspected paths below are untracked relative
to HEAD. Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[R203 actual acceptance](2026-10-11-r203-live-acceptance.md), and R204
[author](2026-10-11-grant-refresh-inner-debug.md)/[review](2026-10-11-grant-refresh-inner-debug-review.md).
Reuse this map before slot-refresh work and update after measured evidence.
Root owns canonical handoff changes; frozen reports remain unchanged.

## Established boundary

The service retains shared SUB recorder slots while a dedicated MAIN viewer
plays. Saved R203 evidence reports LOW331.11s passed and HIGH failed at169.56s.
The initiating captured call is `local_media_mux_service.py:1840`, refreshing
the old slot grant, followed by fixed DENIED at `local_admission.py:66`.
Transport refresh/publication had completed. No initiating READ/background mux
failure was recorded. These are historical report facts, not a new replay.

The existing admission `_boundary` catches the original exception then raises
outside its exception handlers, losing the original refresh traceback. That
measurement gap is source-confirmed and addressed by source-reviewed R204.
QUARANTINED observed during outer logging can be a consequence of this failure:
`refresh_grant:2185` retires/fences the exact known grant on failure, and
coordinator `heartbeat:1858` fences its master. It does not independently prove
the slot was already invalid before refresh entered.

## Branch to source and existing test map

All line numbers refer to the hashes below. `admission` means
`packages/core/src/wso_core/tvt/local_media_mux_admission.py`.
`integration` means `tests/integration/test_local_media_mux_admission.py`.
Tests were inspected, not executed in this task.

| Original refresh branch | Exact source meaning | Existing evidence and next interpretation |
| --- | --- | --- |
| First `_record`, line2201 | `_record:496` requires exact type, retained object identity, issuer and open factory; its second guard rejects denied/closed grant, denied master or monotonic expiry. | Integration `test_copied_or_foreign_grant_never_reaches_sql:35`; `test_refresh_failure_fences_exact_master_and_siblings:1149`, `expired_entry`. Selects local capability validity before this refresh's SQL, not SQL returning null. Nested `_record` raise distinguishes identity guard from the grouped liveness guard, but not each Boolean inside that group. |
| `_observe`, line2203 | `_observe:1186` executes slot SQL using retained authority plus original worker/native generation. Non-null rows must match scope/master and slot task/channel. SQL/shape exceptions can originate here. | Integration `test_same_device_other_actor_or_secret_revision_never_joins:377`, `test_each_retained_slot_revocation_stops_master:409`; refresh failure test `exception`. Trace into `_sql` versus post-row identity checks matters. A SQL privilege error can also map to404; fixed DENIED alone does not identify a predicate. |
| Null row, line2206 | `_observe` returned None; code first retires this grant. SQL `SLOT_OBSERVE:497` requires matching authority/worker/native, current slot and current master. | Refresh failure test `none`; `test_observed_slot_denial_overrides_cached_master:862`. Need distinguish missing row/binding, slot expiry/state/channel, master metadata/wall, or lost live/focus retention. The Python line alone cannot separate SQL predicates. |
| Second `_record`, line2208 | The old exact capability must still be valid after observation. SQL renewal cannot revive an old Python object that expired or was denied/superseded during the call. | Refresh failure test `expired_during`; replacement test `test_refresh_replaces_grant_without_reviving_old_or_wrong_purpose:829`. Points to elapsed observation time or a concurrent local validity change even if SQL returned a row. |
| `_expiry`, line2211 | `_expiry:531` computes `started + (row.expires_at - observed_wall_time)` and denies a nonpositive remainder; malformed timestamp conversion may also fail. | No specific standalone negative `_expiry` test was identified in this targeted read. `test_slow_success_has_expired_cache_and_denial_stays:483` covers related cache timing, not this exact branch. This branch requires timestamp evidence before a clock cause is claimed. |
| Locked publication guard, line2221 | After constructing the fresh grant, factory closure, record denial/closure or denied master blocks publication. | Refresh-fencing tests and `tests/contract/test_final_mux_handoff_refresh.py:578` cover terminal refresh behavior. A selected line2221 would narrow the problem to concurrent local retirement/fencing after observation. No dedicated exact line2221 interleaving proof was identified. |

## SQL and focus relationships that constrain hypotheses

1. Wall heartbeat does renew parked slots. SQL `WALL_CONTROL_ISSUE:770`
   invokes `WALL_READ(true):238`; lines250-256 update wall/master expiry,
   every unexpired RESERVED/ACTIVE/PARKED slot, and eligible MAIN_ACTIVE focus.
   Worker `WALL_HEARTBEAT_REDEEM:806` validates the already-renewed wall and
   masters. Python heartbeat refreshes every `record.slots` entry at1837,
   independently of its active viewers. The test at service-test717 explicitly
   checks a parked slot's replacement.
2. Closing the original SUB viewer does not by itself invalidate its retained
   slot. `VIEWER_CLOSE:569` parks the slot at586; live sibling/focus authority
   can retain the base. `MASTER_SCOPE:123` verifies immutable source-lease
   identity, then normalizes a local copy to CLAIMED with wall/master expiry
   solely for current metadata checks, including after source-viewer closure.
   `SLOT_CURRENT:137` expressly accepts PARKED. No persistent source lease is
   revived by that local SQL record projection.
3. With no active SUB, `MASTER_CURRENT:147` requires current focus or another
   live lease. `FOCUS_CURRENT:639` uses renewable `active_expires_at` and the
   attached live MAIN lease for MAIN_ACTIVE. The original pending20s deadline
   is a separate phase. MAIN_ACTIVE expiry is clipped to MAIN lease, wall and
   at most30s. Ordinary MAIN lease heartbeat is separate from wall heartbeat;
   both browser schedules are10s (`local-live-player.ts:37`,
   `live-wall-group.ts:5,55`). A delayed MAIN heartbeat can therefore affect
   base retention despite healthy video, but this remains a hypothesis here.
4. Transport observation already checks `MASTER_CURRENT`, which checks every
   retained slot and focus/live retention. Therefore a completed transport
   refresh followed by slot SQL null requires a later state/time change or a
   slot authority/binding discrepancy. Master and slot observations use
   separate transactions (`admission._sql:537`); success is not one atomic
   snapshot covering subsequent slot checks.
5. SQL may be renewed while the old immutable Python slot grant still has its
   prior expiry. Core replaces transport first, then slots. Expiry before or
   during slot observation is deliberately rejected by the two `_record`
   checks. Scheduling/SQL/IO delay near that previous deadline is a concrete
   possible mechanism, not measured causality. No fixed170s expiry was found in
   these paths. Elapsed HIGH age alone does not select this mechanism.
6. Native parent checks/parked pumping share the provider refresh IO barrier;
   contract test537 proves already-entered native checks settle before refresh.
   Coordinator sweep also observes transport/slots directly and defers results
   if refresh version/identity changed (`local_media_mux_service.py:1947`,
   service-test1087). Admission can still record a real observed denial or its
   five-second single-flight wait timeout (`admission:1270`); this is a possible
   concurrent source for a local guard failure, not proof of a race defect.

No obvious missing parked-renewal, closed-source-viewer or pending20s-versus-
MAIN_ACTIVE mismatch was found. First priority is the R204 original branch.
If it selects null SQL, the SQL predicate remains a second measurement boundary;
if it selects `_record`, SQL capacity/recorder attribution is premature. Do not
widen expiry or authority guards based on these hypotheses.

## Verification limits and source hashes

Only Git baseline/status, targeted `rg`/source/test/report reads and SHA256
inspection ran. No tests, SQL queries, DB/hardware/browser/runtime inspection,
source fixes, guard changes, new agents or commits. Existing tests show intended
contracts and are not newly executed acceptance. LOW/HIGH full duration,
stop/reconnect, store2 and twelve-camera acceptance remain open as recorded by
the operational lead.

| Source | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_admission.py | `24d50682aab235ca89212d70ab2275548c48305eee32713a844a20945dcd952a` |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| infra/migrations/versions/0016_tvt_device_media_epochs.py | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |
| apps/web/src/lib/tvt/live-wall-group.ts | `6bff8ed41244c957567f7db2e1a2ecb79085e855331222eec4b4365a2c89342a` |

Update log: 2026-10-11 pre-replay causal branch map saved. Actual inner slot
denial remains unmeasured; no repair or playback completion claimed.
