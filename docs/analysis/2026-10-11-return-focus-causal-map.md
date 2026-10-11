# RETURN focus transition: source causal map

Analysis date: 2026-10-11, Asia/Seoul. **A concrete source-level RETURN
transition gap can report a healthy MAIN viewer as not current.** Actual
ordering supplied by the operational lead is consistent with this gap; the
exact interleaving and later transport denial are not independently replayed
or fully proved by this read-only analysis.

Baseline: implementation worktree `codex/superlive-web-service`, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained uncommitted Stage1/2
and diagnostic work. Coordinator/migration source remains untracked relative
to HEAD. Read policy, AGENTS/service, [R203 acceptance](2026-10-11-r203-live-acceptance.md)
and [slot-refresh map](2026-10-11-slot-refresh-causal-map.md). Those reports and
active runtime pins remain unchanged. Root owns canonical reconciliation after
retirement. Read this map before RETURN repair; refresh with controlled source
proof and subsequent actual acceptance.

## New operational evidence and its limit

The lead reports active R204 run95cef: HIGH progressed from
21.725355s/222frames to344.236933s/3447frames, delta322.511578s/+3225frames with
zero drops. HIGH-to-LOW then failed immediately: focus200/125ms, wall404
DENIED/93ms, no LOW start. No GRANT_REFRESH_EXCEPTION or new heartbeat event
preceded this failure. First COORDINATOR_CURRENT=false came from
`native_source.current:557` while master remained ACTIVE; transport current
later became false with denied=true/QUARANTINED, followed by stop-wall fencing.

These safe facts are supplied by Root/lead. This reviewer did not read private
logs, operate the live runtime or assert its retirement. The older slot-refresh
failure is not the initiating observed branch in this RETURN attempt.

## Concrete ordering mismatch

| Step | Source relationship |
| --- | --- |
| SQL RETURN commit | `0016_tvt_device_media_epochs.py:610` FOCUS_ISSUE finds current MAIN_ACTIVE, then line629 changes it to CONSUMED and line634 inserts a new PENDING RETURN. Both changes occur in one SQL transaction. |
| RPC comes later | `services/api/src/wso_api/tvt/local_media_mux.py:309` issues the focus ticket; the application transaction ends before calling the worker at324. The worker has not yet published the new Python RETURN grant at the SQL commit boundary. |
| Local publication | Coordinator `reserve_focus:1288` redeems SQL then calls `retain_focus:1321`. Several authority/custody checks precede the short mutation at1369, which inserts `_focus`, removes `_main_refs` and pops `_main_acks` for RETURN. |
| Concurrent current observation | `_current_dedicated:1617` snapshots old `_main_acks` and searches local `_focus` for RETURN. If no local pending grant exists yet, it calls `focus_settlement_current(old_ack, ATTACHED)` at1640. |
| Expected old-ACK rejection | Admission `focus_settlement_current:1575` observes the original focus row. `_focus_ack:1553` requires MAIN_ACTIVE for the original FORWARD ATTACHED settlement; CONSUMED fails. SQL FOCUS_SETTLEMENT_OBSERVE also rereads state so a committed RETURN cannot be concealed by its initial snapshot. Admission invalidates its old settlement cache and returns false. |
| No transition retry | `_current_dedicated` returns false for the obsolete observation. `current:1129` retries only master `refresh_version`/`refreshing`, which RETURN retention does not change. The healthy new RETURN cannot correct this particular answer. |

There are two distinguishable schedules:

1. **SQL committed, local RETURN not yet retained.** A MAIN current check can
   see only the consumed old acknowledgement. The SQL master can still be
   current because the newly committed PENDING RETURN retains it. This explains
   how viewer-current false is possible while master is still ACTIVE.
2. **A current call spans the local swap.** Even if its old SQL observation
   returned true before consumption, final `_current_dedicated:1654` demands
   the same `_main_acks` object. `retain_focus` has popped it, so the call returns
   false after successful local publication. There is no focus-version recheck
   or retry here. This schedule can finish around/after a successful focus200.

The comment at `retain_focus:1367` describes a gap-free *local mutation*.
It does not cover the earlier committed SQL transition or a current call
already running outside that short lock. This is the source-proven mismatch.

## What is and is not explained downstream

SQL FOCUS_CURRENT at639 accepts unexpired PENDING independently of the old
MAIN lease; MASTER_CURRENT at147 can therefore retain the base throughout
normal MAIN stop. VIEWER_CLOSE at569 sees that retention and should avoid
retiring the base just because MAIN closes. A PENDING RETURN is the intended
bridge through original MAIN cleanup, and ordinary expiry widening is not
needed to explain the identified gap.

`MuxMediaExecutor.current:2227` delegates to coordinator current.
`NativeMediaSource.current:551` propagates false. Decoder authority checks
and media worker `_watch:600` treat false as terminal, and the worker starts
source/peer cleanup. Thus the first false answer can end usable MAIN media.

That Boolean path alone does **not** directly prove the later transport denial
or master quarantine. Subsequent SQL lease/focus transitions and frontend
cleanup need exact order correlation. Relevant continuations are:

- `live-wall-group.ts:115` rejects/cancels a returned focus response when the
  original player is already closed; SQL terminal focus settlement removes
  PENDING retention. `live-wall.tsx:450` also cancels reserved transitions on
  failure. These are possible downstream paths, not measured attribution here.
- Dedicated cleanup and wall heartbeat may race those changes. The first
  logged current=false must not be dismissed as the result of a later wall
  stop. Conversely, the source gap does not establish every later denial.

## Existing coverage and next causal control

Existing tests were inspected, not run:

- Service `test_sole_forward_and_return_refs_cover_both_gaps:668` reserves
  RETURN before MAIN detach and exercises native cleanup gating sequentially.
- Service `test_return_consumes_main_active_atomically:698` checks the local
  maps after `reserve_focus` returns.
- Service `test_return_consumed_main_ack_uses_exact_pending_return_authority:1312`
  removes the old acknowledgement, fully reserves RETURN, then checks current.
- SQL integration `test_main_active_return_consumed_atomically:659` validates
  MAIN_ACTIVE consumption and PENDING creation, but does not interleave a
  coordinator/media current call across SQL commit and local retention.

None of these inspected controls covers the two schedules above. The next
source proof should place an exact original MAIN current check after committed
RETURN but before local retention, and another across local ACK replacement.
It must separately retain denial for actual expired/cancelled/wrong-source
RETURN, revoked MAIN lease and foreign original custody. Preserve confirmed
MAIN native cleanup before SUB admission. This report makes no fix and grants
no bypass, timer change or synthetic authority.

## Verification and hashes

Read-only Git baseline/status, targeted source/test/report reads and SHA256
inspection only. No tests, source changes, runtime/DB/browser operations,
private input, nested agents, commits or pinned-report updates. Only this new
report was created. HIGH duration is lead-reported pass; successful RETURN,
stop/reconnect and broader camera acceptance remain open.

| Source | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| packages/core/src/wso_core/tvt/local_media_mux_admission.py | `24d50682aab235ca89212d70ab2275548c48305eee32713a844a20945dcd952a` |
| infra/migrations/versions/0016_tvt_device_media_epochs.py | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |
| services/api/src/wso_api/tvt/local_media_mux.py | `9b823ae281b90d5f9ccdd09a4c0c87c804c71bf4ce78b8144197faf85428d42f` |
| services/tvt-media/src/wso_tvt_media/native_source.py | `85b1c1195c61149af7883c0fe29c48dd3c508956ef54bdce23939c96661bd6ac` |
| apps/web/src/lib/tvt/live-wall-group.ts | `6bff8ed41244c957567f7db2e1a2ecb79085e855331222eec4b4365a2c89342a` |

Update log: 2026-10-11 two concrete RETURN observation schedules mapped;
operational lead/Root notified early. Actual exact schedule and downstream
transport cause still require correlation or an inert causal control.
