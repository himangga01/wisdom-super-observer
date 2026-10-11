# Dedicated MAIN maintenance versus shared refresh: causal map

Analysis date: 2026-10-11, Asia/Seoul. **Direct dedicated maintenance has a
source-visible refresh race that can turn a transient local pause into native
denial. Its role in the actual late HIGH failure remains unmeasured.** The first
saved public current=false already describes MAIN stopping/closing and cannot
by itself identify the initiating branch.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted Stage1/2
and reviewed R193-R207 work. Read shared policy, [AGENTS](../../AGENTS.md),
[service report](../service-analysis.md), [R207 actual acceptance](2026-10-11-r207-live-acceptance.md)
and [R207 source review](2026-10-11-return-slot-binding-fix-review.md).
Read before dedicated/refresh changes; refresh after original-cause evidence
or a controlled reproduction. Root owns canonical handoff updates. This new
report was written only after the original runtime retired and pins released.

## Actual observation and limits

Run `73eafbb86b674b9dba97fc3fcb3abac8`, original exec99535, used441 pinned
sources. Early RETURN/new SUB succeeded. Returned LOW sustained311.638506s,
+3117frames with+280drops. Later HIGH's sampled video advanced from22.855011s/
233frames to131.649932s/1320frames with0drops, then reset to0. The300s HIGH gate
failed. CDP recorded session-heartbeat404 and session-stop404; wall Stop was200.

Observation places the second MAIN source at first448046ms, last589500ms,
1415frames. Peer first failure was `explicit_close` at145577ms source age.
The first public Core current=false at589343ms already had MAIN stopping and
closing true while its base remained ACTIVE. No initiating grant-refresh
exception, READ error or format transition was recorded. These are retained
Root/lead report facts; this reviewer did not inspect private live state.

Normal retirement passed: original coordinator exit0/reaped, API/worker settled,
context removed, media COMPLETE/writer settled, owned DB cleanup/source-content
equality, source441 unchanged and known-private0. Historical5dd exceptional
exit97/1 and missing final Job receipt remain distinct FAILED evidence.

## Exact source relationship

The service retains shared SUB authority while a separately owned MAIN original
has its own codec, IPC and native lifetime. A healthy wall heartbeat briefly
replaces immutable shared grants under a provider operation barrier.

| Boundary | Source behavior |
| --- | --- |
| Shared refresh publication | Coordinator `heartbeat:1841` sets `record.refreshing=true`, increments `refresh_version`, replaces grants, then clears the flag/increments the version at1896-1898. |
| Local active predicate | `_active:942` requires ACTIVE state **and not refreshing**. The temporary pause is deliberately visible as not active to raw internal checks. |
| Public current protection | `current:1148` waits outside the registry while refreshing and retries if refresh version changed. It does not treat that internal pause as terminal revocation. |
| Direct dedicated observation | `_current_dedicated:1638` retries only changes to dedicated `focus_version`. `_current_dedicated_once:1650` checks `_active(master)` on entry and before returning; it does not wait/retry shared refresh version. |
| Sweep entry | `sweep:2039` checks `main.master.refreshing` once, then directly calls `_current_dedicated`. A heartbeat can enter after that single check. There is no post-observation shared refresh/version guard for this dedicated branch. |
| Native maintenance supplier | Sweep passes a `still_current` closure that again directly calls `_current_dedicated` into `main.session.current`. It performs another direct current check afterward. Any false/exception leads to `_close_dedicated`, which sets stopping/closing before a later public current check logs its result. |

Two concrete source schedules follow:

1. Sweep sees no refresh; heartbeat starts before or during the direct
   dedicated check. `_active` returns false for the temporary refresh, and
   sweep closes MAIN without the public current wrapper's retry.
2. The first dedicated check succeeds; heartbeat starts while native session
   renewal/pumping calls its direct `still_current` supplier. That false can
   become sticky denial in the legacy IPC parent before sweep returns.

The base-slot sweep earlier in the same function already snapshots shared
refresh version/grants and discards superseded observations. The dedicated
branch lacks that corresponding protection. This source comparison establishes
a testable gap; it does not select which branch occurred in run73eaf.

## Native path and permanent denial

`_DedicatedSession.current` in `local_live_mux_provider.py:1432` enters the
original custodian's external operation, checks its stopping flag and delegates
with the retained supplier. `OwnedLocalLiveSession.current` in
`local_live_provider.py:102` serializes with reads and checks:

1. Original owner not confirmed, then `LiveParentAuthority.renew` succeeds.
2. Original child exists and has not exited.
3. Original authority `pump(current)` succeeds.

`renew:207` checks old expiry/current before validating and replacing its
deadline, then checks current again. `ParentAuthority.check:163` in
`local_inventory_ipc.py` turns supplier false/exception into `deny('denied')`,
setting the permanent failure/stop latch. Cancellation and old deadline retain
their distinct denial paths. `pump:333` in `local_live_ipc.py` additionally
checks IPC, codec, queue bounds and current before its ACK. Failure causes the
session's `_close`, original owner settlement, and watchdog-driven original
stop. A later healthy refresh cannot revive that denied authority.

Thus a refresh-related supplier false can produce subsequent MAIN stopping
with no GRANT_REFRESH_EXCEPTION. Equally, a real MAIN-retention SQL denial,
lease authority error, custody mismatch, native child exit or IPC/codec failure
can reach the same sweep cleanup. Those alternatives remain unselected.

## Lifetime facts, not a fixed600s attribution

The dedicated native parent uses renewable30s authority with strict old-expiry
checks. MAIN SQL lease heartbeat and wall/focus heartbeat are separate; active
focus is clipped to live MAIN/wall expiry. A real SQL/session/custody denial
must remain terminal and must not be hidden by a concurrency correction.

Both live parent and native worker serve-live explicitly configure codec limits
of1TiB cumulative bytes and1,048,576 packets. The smaller default capture codec
limits are not the continuous MAIN configuration. AuthSettings defaults to8h,
clipped to principal expiry; the borrowed synthetic OIDC issuer signs1800s
tokens. A separate account-fixture `fresh_session` contains a600s lifetime, but
its use was not established in this local runtime's OIDC login path. Neither
elapsed runtime near589s nor source age near145s proves a fixed lifetime cause.
The earlier R203169.56s HIGH/slot-refresh failure is not retroactively assigned
to this race or to a common timer.

## Existing tests and next measurement

Inspected, not executed here:

- `test_current_waits_for_inflight_heartbeat_instead_of_retiring_valid_viewer`
  at service-test1044 covers the public current wrapper on a shared viewer.
- `test_sweep_defers_superseded_heartbeat_observation` at1142 covers base
  transport/parked-slot observations, not dedicated maintenance.
- `test_dedicated_legacy_owner_maintenance_requires_current_main_reference`
  at1115 checks normal dedicated maintenance and later detach, without a
  concurrent heartbeat inside the direct supplier.
- Provider tests329/339/347 preserve nonrevival of denied/expired originals
  and old-deadline checks; these safety contracts must remain unchanged.

The next causal controls should interleave a healthy heartbeat after the
dedicated sweep precheck and inside the original native current supplier,
while retaining real revoke/cancel/old-expiry/Stop negatives. First, R208 is
being authored as runtime-only tracing of original dedicated false/close
methods with closed `refreshing_at_entry`/`refresh_changed` facts. Its candidate
is not reviewed by this report. Production behavior is unchanged; evidence
must distinguish direct false from native-maintenance failure before repair.

## Verification and source hashes

Read-only source/test/report inspection, Git baseline and hashes only. No
tests, source/canonical edit, DB/runtime/browser/hardware action, private input,
nested agent or commit. Only this new report was created after pin release.
Full HIGH duration, further transitions/Stop/reconnect/store2, twelve-camera/
APK and existing broad/typing gates remain open.

| Source | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `c324bc1eb0c9c44b1153380a95ab29ebcae1448c6148ef74f6514a5574ffa5b8` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py | `eafc1bea8c66b87d61e9729d1ab66020cba800bc6701d7ea296a4ddc9225e6fa` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py | `cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py | `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910` |
| services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py | `b34626aa9f3cceabf805b9472570445cd617ce0623c321ffb4d1c9f4635efe39` |
| services/tvt-media/src/wso_tvt_media/native_source.py | `85b1c1195c61149af7883c0fe29c48dd3c508956ef54bdce23939c96661bd6ac` |
| tests/tvt_parity/test_local_media_mux_service.py | `0c32a4f9d779aef473d015477e1a709c470f5a60f80b0c3fdaaa020975da44d1` |

Update log: 2026-10-11 direct dedicated/shared-refresh race and native denial
chain mapped after normal73eaf retirement. Actual first cause remains unmeasured.
