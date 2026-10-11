# Multi-view stage 1: bounded authority, sub streams and wall capacity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposed on 2026-10-05 (Asia/Seoul) and **approved by the user on
2026-10-05** ("1단계 진행"), with subagent-driven execution. The user also
confirmed that store-1 channels 1 and 3 have cameras connected but show only
a black picture because of a camera fault, so "영상 신호 없음" is the expected
outcome for them (R124). Phase 0 (measurement, no source change) of the parent
plan was executed before approval.

**Goal:** The `/monitoring` wall plays every channel of both recorders (8 + 4)
at the same time on sub streams, within measured SQL, CPU and recorder budgets,
and reports channels without video distinctly.

**Architecture:** Keep the accepted per-tile session model (one fresh native
login per tile, exclusive first task, route-0 media) and change four things:
(1) a bounded media-authority hot path (a per-lease 100 ms cache over a
non-locking SQL check); (2) sub-stream opens (APK command 1285 for peer version
5 or later, legacy 1281 with stream 2 otherwise) through codec, native child,
provider, API and web; (3) capacity raised from 2 to 16 streams, with bounded
waits instead of instant refusals; (4) a 10 s first-frame bound with a distinct
no-signal outcome. Per-device multiplexing, viewer fan-out and production
wiring stay in later stages.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy 2.1 with psycopg, aiortc,
PyAV, gRPC), PostgreSQL 17 migrations, Next.js/TypeScript (vitest, ESLint,
tsc), Windows native child over the recovered raw socket ABI.

**Spec:** [`2026-10-04-multiview-live-plan.md`](2026-10-04-multiview-live-plan.md)
(phases; proposed), with evidence in the
[APK parity review §5](../../analysis/2026-10-04-apk-feature-parity-review.md)
and the [liveness review §6c](../../analysis/2026-10-04-local-media-liveness-review.md)
(Phase 0 measurement).

## Evidence this plan argues from

- **Phase 0 (real recorders, 2026-10-05).** One main stream costs about 665
  SQL transactions/s and 200 KB/s of WAL with almost no tuple writes; two
  streams 1,263 tx/s and 393 KB/s; the runtime Python process uses 54% and then
  134% of a core. A no-video channel ends at the 20 s start deadline with 504.
- **Authority call graph (read-only design review).** Every hot-path check
  is a pooled transaction calling the locking `LIVE` predicate (`FOR SHARE` on
  about 10 rows; `0013:74-103`). Native child messages cost 2 checks each, each
  read about 9, the decoder 3 plus a view, the permit heartbeat 40/s.
  Pre-ping doubles the transaction count. Sub streams alone would still need
  about 30 checks per frame.
- **APK, decompiled 1.18.1 (read-only).**
  - `cw3.kb` sends the 1285 XML open and does not wait for its reply.
  - A non-fail reply carries `yz0` (72 bytes) and then `oz0` {int code,
    GUID, short length, text}. Only code `0x20000060` ("sub-stream adaptation
    not turned on") has an effect, a toast.
  - Class-3 open errors `0x20000029` (no authority) and `0x20000030` (device
    busy) are matched by the `yz0` task GUID.
  - Close is always 1282 with `ll2` and the open's stream.
  - Media is dispatched by the `ep3` channel GUID only.
  - Every main/sub switch is close-then-open with no fence.
  - The app reads no recorder connection or stream limit locally.
- **Code map.**
  - Store 1's peer version (`R3`) is 6, so a sub-stream open needs the 1285
    lifecycle.
  - The contract, SQL and web input already admit `sub`. The provider
    (`local_live_provider.py:39,52,203-204`), IPC (`local_live_ipc.py:249-254,304`),
    child (`windows_socket_worker.py:1049-1050,1134`) and codec
    (`local_live.py:215-216,452-466`) reject or hard-code main.
  - Caps of 2 apply at `windows_socket.py:977`, `worker.py:115,145` and the
    test runtime's RPC `capacity=2`. SQL caps are 4 per tenant/actor and 32
    globally (`0013:130-131`).

## Global Constraints

- Never write credentials, device serials, device/session/channel/task GUID
  values, raw SDP, cookies, keys or private media into source comments, docs,
  test output, reports or logs. Tests use synthetic GUIDs and bytes.
- Ruling R104 stays: implementers never commit, stage, stash or reset. The
  controller snapshots the worktree as git tree objects for each review.
- Never edit source while a source-pinned acceptance runtime
  (`run-media-browser-root.py`) is running.
- Receipts and approvals are created only by the controller, after recorded
  independent review verdicts. Recomputing a hash is never a substitute for a
  review.
- Native-receipt-owned files are the 12 OWNED paths at
  `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py:27-40` plus the
  receipt dependencies checked at `:646-695`, which include
  `packages/core/src/wso_core/tvt/local_media_service.py`. The LIVE receipt pins
  `packages/core/src/wso_core/tvt/local_live.py`, `tests/tvt_parity/test_local_live.py`
  and `docs/integrations/tvt-local-live-codec.md`.
  - Tasks 1 and 6 must not edit any of them.
  - Tasks 2–5 may, and their combined native delta gets one independent native
    review before any device run (Task 7).
- `WSO_TEST_LOCAL_MEDIA_TRACE` stays unset in acceptance runs.
- Python gates:
  - `.venv/Scripts/python.exe -m pytest <tests> -q`
  - `.venv/Scripts/python.exe -m ruff check <files>`
  - `.venv/Scripts/python.exe -m ruff format --check <files>`
  - `.venv/Scripts/python.exe -m mypy <files>` (strict, per `pyproject.toml`)
- Web gates, from the repository root:
  - `pnpm --filter @wso/web test`
  - `pnpm --filter @wso/web lint`
  - `pnpm --filter @wso/web typecheck`
- Migrations: `0014_tvt_local_media_hot_authority.py` (Task 1) and
  `0015_tvt_local_media_capacity.py` (Task 5). `0013` is never edited again.
  The parent plan's viewer fan-out migration becomes 0016.
- Korean UI copy, verbatim: "영상 신호 없음" (no signal), "재생 대기 (장치 사용
  중)" (busy, existing), "고화질" (main) and "저화질" (sub).
- Constants, verbatim:
  - Authority: `AUTHORITY_FRESHNESS_SECONDS = 0.1`, `AUTHORITY_WAIT_SECONDS = 5.0`,
    `AUTHORITY_TOMBSTONES = 64`.
  - First frame: `FIRST_FRAME_SECONDS = 10.0`.
  - Native: `MAX_SERVICE_LIVE_SESSIONS = 16`, `LIVE_ATTEMPT_WAIT_SECONDS = 10.0`.
  - Media worker: `MAX_MEDIA_SOURCES = 16`.
  - SQL caps: 16 per tenant/actor and 64 globally.
  - Test-runtime RPC `capacity=32`.
  - Media admission pool: `pool_size=8, max_overflow=8`.
  - Web: `LIVE_WALL_CONCURRENCY = 16`.
  - Protocol: 1285 success reply command `0x10000505`, `oz0` warning code
    `0x20000060`, refusal codes `0x20000030` (busy) and `0x20000029` (no
    authority).

## Review Focus

1. **RF1. A recorder that refuses or ignores a sub-stream open.** This covers
   a class-3 reply, no reply, media before the reply, or an unknown `oz0` code.
   The tile must end with a clear reason within the first-frame bound, and no
   other tile may be fenced or delayed. Tests: Task 2 and Task 3.
2. **RF2. A revoke, stop, role removal or expiry while 12 streams play.**
   Every stream must stop within the stated bound even though per-frame SQL is
   cached. A cached True never outlives F or the lease expiry. Tests: Task 1.
3. **RF3. Slow SQL or pool exhaustion under 12–16 streams.** Denial must be
   sticky per lease, there must never be more than one in-flight check per
   lease, and one slow lease must never deny another. Tests: Task 1 and Task 5.
4. **RF4. Rapid enlarge and return on one channel**, given one active lease
   per channel. The wall must serialize stop → start, a STOPPING row must
   become a busy re-queue rather than a failure, and no lease may leak.
   Tests: Task 6.
5. **RF5. A no-video channel among many live ones.** It must show "영상 신호
   없음" within about 10 s of the open, with no retry and no global cool-down,
   and its slot must be released. Tests: Task 4 and Task 6.

## Rulings proposed for execution (recorded in the ledger when execution starts)

- **R120. Authority cache.**
  - The media hot path answers `current`/`view` from a per-lease cache in
    `LocalMediaAdmission`. A cached result is used only if its SQL check
    *started* less than 100 ms before the call.
  - At most one check per lease is in flight, and denial is sticky.
  - This amends R106(a) ("every check is a fresh SQL transaction").
  - New bounds: no grant to any call that begins after t_r + 100 ms. The
    WebRTC sender bound stays t_r + 200 ms + one monotonic tick, because the
    permit is anchored at now − F. Overall t_r + 300 ms when check latency is
    200 ms or less.
  - Cost if wrong: revocations land up to 100 ms later than today on the
    native and decoder side.
- **R121. Non-locking hot-path check.**
  - Migration 0014 adds a read-only, non-locking `observe` function for the
    hot path.
  - State transitions and the startup open keep the locking `LIVE`.
  - Cost if wrong: a check that overlaps an uncommitted revoke returns the
    pre-revoke state, which the 100 ms cache bounds anyway.
- **R122. Stage 1 keeps one login per tile.**
  - The recorders send route-0 media, correlated only by the channel GUID.
  - A multi-task connection needs a new channel-dispatch codec contract, which
    is stage 2.
  - Cost if wrong: if the recorders' unmeasured connection limit is below 8,
    the surplus tiles wait as busy until stage 2.
- **R123. Sub-stream opens follow the APK.**
  - Peer version 5 or later uses 1285 XML; earlier versions use 1281 with
    stream 2.
  - The class-2 reply `0x10000505`, matching the pending sequence and
    generation, is the open acknowledgement. The `oz0` code is advisory only:
    `0x20000060` sets a warning flag and never creates or removes success.
  - A class-3 reply correlated by the `yz0` task GUID ends the open: busy →
    429, no authority or other → 502 `LOCAL_DEVICE_UPSTREAM_REJECTED`.
  - Cost if wrong: one more codec iteration after the first device run.
- **R124. First-frame bound.**
  - The source waits at most `FIRST_FRAME_SECONDS = 10.0` after it starts for
    its first decoded frame, then fails with `LOCAL_DEVICE_NO_SIGNAL` (504).
  - The web proxy forwards known upstream error codes.
  - The wall shows "영상 신호 없음" without retry or cool-down.
  - Cost if wrong: a camera with an I-frame interval longer than about 9 s is
    labelled no-signal (measured in Task 7).
- **R125. Capacity.**
  - 16 live owners per bridge process.
  - Live attempts wait for the attempt lock, and for uncertain custody to
    clear, up to min(remaining deadline, 10 s) instead of failing at once.
  - 16 media sources; SQL caps of 16 per tenant/actor and 64 globally.
  - Test-runtime RPC capacity 32; media admission pool 8 + 8.
  - Cost if wrong: server overload shows up in the sizing gate before any
    default changes outside the test runtime.
- **R126. Wall stream policy.**
  - Grid tiles open sub streams.
  - The enlarged view switches its channel to main (stop sub, then start main)
    and returns to sub when closed.
  - `LIVE_WALL_CONCURRENCY = 16`, with the existing busy re-queue.
  - Cost if wrong: a slow focus switch (stop plus start, about 3–5 s).

---

## Task 1: Bounded media-authority hot path (final-review I3)

**Files:**
- Modify: `packages/core/src/wso_core/tvt/local_media_admission.py`. Add the
  constants after `:31`, extend `__init__` at `:134-156`, the `_query` allowlist
  at `:299`, and `current`/`view` at `:323-332`, `close` at `:359-369` and
  `shutdown` at `:389-393`.
- Create: `infra/migrations/versions/0014_tvt_local_media_hot_authority.py`
  (down revision `0013`).
- Modify: `services/tvt-media/src/wso_tvt_media/native_source.py:262` (permit
  anchoring).
- Modify the revision pins:
  - `tests/integration/test_local_media_admission.py:62`
  - `scripts/test-local-devices/runtime.py:79` (add 0014 to `MEDIA_SOURCES`)
    and `:498` (migrate to 0014)
  - `tests/contract/test_local_device_browser_fixture.py:331`
- Create: `tests/tvt_parity/test_local_media_authority_gate.py`.
- Create, or extend if present: `tests/tvt_parity/test_local_media_migrations.py`.
- Modify tests:
  - `tests/tvt_parity/test_local_media_source.py`
  - `tests/tvt_parity/test_local_media_service.py`
  - `tests/integration/test_local_media_admission.py`
- Docs: the authority bounds in `docs/integrations/tvt-local-media-service.md`
  and `docs/integrations/tvt-local-webrtc.md`.
- Must not edit any native-receipt-owned or receipt-dependency file. That
  includes:
  - `local_media_service.py`, `local_live_provider.py`, `local_live_ipc.py`,
    `local_inventory_ipc.py`, `windows_socket.py`, `windows_socket_worker.py`
  - `docs/integrations/tvt-windows-live-session.md`

**Interfaces:**
- Consumes: the existing `LocalMediaAdmission._query(kind, ...)` transaction
  wrapper with its per-transaction `current_user` check and transaction-local
  timeouts.
- Produces:
  - `AUTHORITY_FRESHNESS_SECONDS: float` exported from
    `wso_core.tvt.local_media_admission`; `native_source.py` imports it.
  - `LocalMediaAdmission.__init__(worker_url, keys, *, clock=time.perf_counter)`.
  - `current(lease) -> bool` and `view(lease) -> MediaLease`, both answered
    through the gate.
- SQL produced:
  - `wso_private.wso_tvt_local_media_live_read(...)`: the 0013 `LIVE` predicate
    with every `FOR SHARE` / `FOR SHARE OF` removed.
  - `public.wso_tvt_local_media_observe(p_authority text, p_worker uuid, p_native uuid) RETURNS jsonb`:
    the 0013 worker view built on `live_read`, additionally requiring state
    `NEGOTIATING` or `PLAYING`. It uses the same function options as `0013:62`
    and owner `wso_tvt_local_owner`, is revoked from all runtime roles and
    grants EXECUTE to `wso_connection_worker` only. Downgrade drops both.

**Gate semantics (verbatim requirements):**
1. A call begins at clock time c. If the lease token is denied or tombstoned,
   return None with no SQL.
2. **Cache hit.** Return the cached result when `clock() < valid_until`.
   - `valid_until = min(s + F, s + (expires_at − UTC_at_s))`.
   - s is the clock time sampled immediately before `engine.begin()` of the
     check that produced it.
3. **A check is already in flight.**
   - If it belongs to the calling thread, deny (re-entry).
   - Otherwise wait up to `AUTHORITY_WAIT_SECONDS`; a timeout denies.
   - Accept the finished result only if its s is greater than c − F;
     otherwise loop.
4. **Otherwise this thread runs the check.**
   - Sample s and UTC.
   - Run `observe` outside every lock.
   - Publish the result and wake the waiters under the per-lease condition.
5. **Sticky denial.** Each of these marks the lease permanently denied and
   wakes all waiters:
   - a NULL result;
   - any exception (pool timeout, statement timeout, role mismatch,
     `ValidationError`);
   - a waiter timeout;
   - `close()` during a check.

   The caller that ran a failing check still receives the existing 503
   mapping, so `test_checkout_timeout_maps_to_unavailable` keeps passing. A
   slow but successful check is honoured.
6. The first call for a lease always runs SQL, and nothing is shared between
   leases.
   - `close()` denies and tombstones before its own SQL.
   - `shutdown()` denies all.
   - Tombstones keep the 64 most recent tokens.
7. Locks: one lock plus one condition per entry, and one registry lock. No SQL
   and no callback runs under any lock.
8. Invariant: any True returned to a call that began at c is backed by a check
   that began after c − F.
9. **Permit anchoring.** At `native_source.py:262`,
   `observed = time.monotonic() - AUTHORITY_FRESHNESS_SECONDS`.

**Steps:**
- [ ] **Step 1: Write the failing tests.**
  - In `tests/tvt_parity/test_local_media_authority_gate.py`, using a fake clock
    and a stubbed `_query`:
    - `test_sql_budget_per_simulated_second[1,8,32]` (packets per frame).
      - Simulates 3 s at 10 fps: 2 pump calls per packet; per frame 10 ingress
        calls plus decoder and publish calls; the 50 ms heartbeat; a 1 Hz sweep
        and watch.
      - Asserts at most 31 `observe` calls for every N, a variation of at most
        1 across N, and zero `current`/`worker_view` SQL calls.
    - `test_cache_requires_start_within_freshness`: at s + 99.9 ms, 0 SQL
      calls; at s + 100 ms, 1 SQL call.
    - `test_first_call_runs_sql_and_leases_isolated`.
    - `test_denial_sticky_without_sql` (RF2).
    - `test_sql_error_denies_sticky[pool_timeout,statement_timeout,role_mismatch,invalid_view]` (RF3).
    - `test_concurrent_callers_share_one_in_flight_check`: 8 threads named
      pump, ingress, decoder, heartbeat, sweep and watch; exactly 1 SQL call
      and identical results (RF3).
    - `test_waiter_rejects_check_started_before_call_minus_F`.
    - `test_slow_success_honored`.
    - `test_waiter_timeout_and_reentrancy_deny`.
    - `test_close_during_flight_discards_true`.
    - `test_cache_clipped_to_lease_expiry`.
    - `test_one_slow_lease_never_denies_another` (RF3).
    - `test_parent_pump_with_gate_bounds_sql_and_latches_denial`: drives the
      real `LiveParentAuthority` over a `multiprocessing.Pipe`, importing the
      owned modules without editing them.
  - In `tests/tvt_parity/test_local_media_source.py`:
    - `test_revocation_with_gate_meets_bounds` (RF2): no True for calls that
      begin after t_r + 116 ms, no datagram after t_r + 216 ms, fenced, never
      revived.
    - `test_permit_anchored_at_earliest_gate_observation`.
    - `test_composed_gate_pipeline_stays_live_with_bounded_sql`.
  - In `tests/tvt_parity/test_local_media_service.py`:
    `test_executor_fences_immediately_despite_fresh_gate`.
  - In `tests/tvt_parity/test_local_media_migrations.py`:
    `test_0014_live_read_equals_live_without_locks`. It compares the 0013
    `LIVE` text with `live_read` after removing the `FOR SHARE` clauses.
  - In `tests/integration/test_local_media_admission.py` (guarded PostgreSQL):
    - `test_media_sql_observe_assigns_no_xid_and_no_row_locks`:
      `pg_current_xact_id_if_assigned()` is NULL inside `observe`; control
      check that the locking `current` assigns one.
    - `test_media_sql_observe_matches_current[...]`: 8 lifecycle changes plus
      expiry, stop and close.
    - `test_media_sql_observe_never_waits_on_uncommitted_revoke`: uses the
      existing paused-owner-call pattern.
    - `test_media_sql_observe_privileges`.
    - `test_media_sql_gate_end_to_end_revocation`: 1,000 calls make at most 6
      `observe` calls; after a revoke, False within 150 ms and sticky.
- [ ] **Step 2: Run the new tests and confirm they fail** for the expected
  reason (missing gate, function or migration).
  - Unit tests:
    `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_media_authority_gate.py tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_media_service.py tests/tvt_parity/test_local_media_migrations.py -q`.
  - The guarded SQL suite runs only through the runner the controller names in
    the dispatch (an adapted `run-local-media-admission-sql-c1.py` pinning 0014).
- [ ] **Step 3: Implement** the gate, migration 0014 and permit anchoring
  exactly as specified above.
- [ ] **Step 4: Run the tests and confirm they pass.** Run the whole media
  selection:
  `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_media_admission_pool.py tests/tvt_parity/test_local_media_worker.py tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_webrtc.py tests/tvt_parity/test_local_media_service.py tests/tvt_parity/test_local_media_contracts.py tests/tvt_parity/test_local_media_rpc_api.py tests/tvt_parity/test_local_media_authority_gate.py tests/tvt_parity/test_local_media_migrations.py -q`.
  Run the guarded SQL suite through the controller's runner (expect 0
  failures, 0 errors, 0 skipped).
- [ ] **Step 5: Static gates.** Run ruff check, ruff format --check and mypy
  on every changed Python file.
- [ ] **Step 6: Docs.** State the R120 bounds in the two integration guides.
- [ ] **Step 7: Report** to the task report file. Do not commit (R104).

## Task 2: Sub-stream open lifecycle in the live codec

**Files:**
- Modify: `packages/core/src/wso_core/tvt/local_live.py`:
  - the constructor rule at `:215-216`;
  - `_parse` at `:436-466`, with a new 1285 acknowledgement and a class-3
    refusal branch;
  - route-0 admission at `:458-466`;
  - `LiveAcknowledgement` at `:110-112`, which gains a `warning` field;
  - a new exception `LiveRefused(reason)`.
- Test: `tests/tvt_parity/test_local_live.py`.
- Docs: `docs/integrations/tvt-local-live-codec.md`, replacing the
  "1285 replies … unsupported" limits at `:119-123` and `:180` with the
  lifecycle below.
- Read-only references: `C:/wso-private/superliveplus/1.18.1-2026-09-27/jadx-full/sources/defpackage/{cw3,oz0,yz0,ll2}.java`
  (`kb` 6641-6688, Z9 5200-5211, m8 7093-7122, r7 7459-7468) and
  `ServerNVMSHeader.java:2701-2709`. Cite class and line only; copy no code and
  no literal GUID.

**Interfaces:**
- Produces:
  - `LiveCodec(..., stream=2, exclusive_first_task=True)` is now valid.
  - `LiveAcknowledgement(command: int, warning: Literal["", "SUB_STREAM_ADAPTATION_OFF"] = "")`.
  - `class LiveRefused(UnsupportedLive)` with read-only `reason: Literal["busy", "denied", "refused"]`.
  - All three are exported for the bridge (Task 3).

**Requirements:**
1. **Construction.** `exclusive_first_task=True` is accepted with stream 1 or 2.
   Every other constructor rule is unchanged.
2. **Requests.** The builders are unchanged:
   - stream 2 with `peer_capability >= 5` builds the 1285 XML;
   - otherwise 1281 with `ll2` carrying the stream;
   - close is always 1282 with `ll2` carrying the open's stream.

   Verify, by reading `cw3.r7`, that the XML `<chNo>` and the `ll2`
   channel-number byte follow the same rule as the documented
   `channel_number = r7 -> iz0.r` (the chlIndex only for analog channels,
   otherwise 0). Record the evidence. If they differ, report it as a concern
   and change nothing.
3. **1285 acknowledgement.** Accept exactly one reply with wz0 command
   `0x10000505` when all of these hold:
   - the pending command is 1285;
   - wz0 sequence equals the open's sequence;
   - the generation matches;
   - state is `open` and the open is not yet acknowledged.

   The payload after the 16-byte wz0 must be at least 76 bytes. The `oz0` code
   is the little-endian int32 at payload offset 72. Code `0x20000060` sets
   `warning="SUB_STREAM_ADAPTATION_OFF"`, and every other code sets none. The
   body never decides success; the header class and command do. Any other
   `0x10000505` (wrong sequence, duplicate, before open, while closing, short
   payload) raises `LiveError` and fences.
4. **Refusals.** While an open (1281 or 1285) is pending and unacknowledged,
   a reply whose wz0 command is in `[0x20000000, 0x30000000)` is a refusal if
   its payload is at least 72 bytes and the `yz0` task (payload `[52:68]`)
   equals the identity task.
   - It closes the codec and raises `LiveRefused` with reason `busy` for
     `0x20000030`, `denied` for `0x20000029` and `refused` otherwise.
   - Confirm in `cw3.m8` that the code is the wz0 command field. If the source
     shows otherwise, follow the source and record it.
   - Uncorrelated class-3 replies, and any class-3 reply while closing, fence
     as today (`UnsupportedLive`).
5. **Route-0 media.** Admitted when the open is exclusive, acknowledged and in
   state `open`, and the pending command is 1281 **or 1285**. The existing check
   that `ep3` kind (`data[6]`) equals the stream stays.
6. Route 2, route 1, ACK sequence/generation rules, close semantics and all
   bounds are unchanged.

**Steps:**
- [ ] **Step 1: Write the failing tests** in `tests/tvt_parity/test_local_live.py`.
  Keep the existing 1281/1285 byte-selection tests.
  - `test_exclusive_first_task_accepts_stream_two[cap6,cap4]`.
  - `test_sub_1285_ack_admits_route0_kind2_media`: an R3=6 open, reply
    `0x10000505` with matching sequence and a 340-byte payload (code 0), then
    route-0 media with kind 2, gives a `PrivateLiveFrame`.
  - `test_sub_1285_adaptation_off_is_warning_only`: code `0x20000060` gives
    the warning and media is still admitted.
  - `test_sub_1285_ack_unknown_code_is_not_failure` (RF1).
  - `test_sub_1285_reply_rejected[wrong_sequence,duplicate,before_open,closing,short_payload,wrong_generation]`.
  - `test_route0_media_before_1285_ack_fences` (RF1).
  - `test_route0_kind1_on_sub_codec_fences`.
  - `test_open_refusal_reasons[0x20000030-busy,0x20000029-denied,0x20000031-refused]`
    for both 1281 and 1285 (RF1).
  - `test_refusal_requires_task_match_and_pending_open[mismatch,closing,acked]`.
  - `test_legacy_sub_1281_stream2_ack_admits_route0_kind2` (R3=4).
  - `test_sub_close_uses_1282_ll2_stream2`.
- [ ] **Step 2: Run them and confirm they fail.**
  `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_live.py -q`.
- [ ] **Step 3: Implement** requirements 1–6.
- [ ] **Step 4: Run** the codec tests plus `tests/contract/test_windows_socket.py`
  and `tests/contract/test_local_live_provider.py`. Existing tests that pin the
  old "stream 2 unsupported" behaviour are updated only where this task changes
  that behaviour; list each such change in the report.
- [ ] **Step 5: Static gates** on changed files.
- [ ] **Step 6: Docs.** Update the codec guide's lifecycle, its limits table and
  the owner contract (exclusive first task, stream 1 or 2).
- [ ] **Step 7: Report.** No commit. The LIVE receipt is the controller's
  (Task 7).

## Task 3: Stream selection and device refusals through native child, IPC and provider

**Files (native-receipt-owned; native review in Task 7):**
- `services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py`:
  - `LiveSelection.stream` becomes `Literal["main", "sub"]`, with validation at
    `:39,52`;
  - `open_session` passes `LocalMediaChannel.stream` through (`:202-211`);
  - `failure()` gains the refusal reasons.
- `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py`: `PrivateRequest`
  (`:342-352`) and `live_selection` (`:1100-1108`) carry the stream as 1 or 2.
- `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py`:
  - setup keys gain `"stream"` (`:198-211`);
  - `LiveCodec(stream=setup["stream"], exclusive_first_task=True)`
    (`:249-254`);
  - `open_ack` accepts the codec's acknowledgement for the pending command
    1281 or 1285 (`:304-307`);
  - `LiveRefused` maps to `deny("device_busy" | "device_denied" | "device_refused")`.
- `services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py`:
  - setup carries the stream (`:1498-1511`);
  - `serve_live` uses it (`:1049-1050`), and `live_open_ack` accepts the
    1281/1285 acknowledgement (`:1134`);
  - the child forwards a correlated class-3 reply envelope to the parent
    before closing, so the parent's own codec yields the same `LiveRefused`.
  - The diagnostic `capture_live` stays stream 1, unchanged.
- Docs: `docs/integrations/tvt-windows-live-session.md`. Replace "substream
  requests fail" at `:19-21` with stream selection and refusal mapping.
- Tests:
  - `tests/contract/test_local_live_provider.py`, including the stream pin at
    `:16`;
  - `tests/contract/test_windows_socket.py`, including the pins at
    `:3369-3370` and `:3400`.

**Interfaces:**
- Consumes the Task 2 `LiveCodec`, `LiveAcknowledgement.warning` and `LiveRefused`.
- Produces the provider failure mapping:
  - `device_busy` → `LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)`;
  - `device_denied` and `device_refused` →
    `LocalDeviceFailure("LOCAL_DEVICE_UPSTREAM_REJECTED", 502)`.
- `LiveParentAuthority.sub_stream_adaptation_off: bool` is a read-only
  diagnostic that is never exported publicly.

**Requirements:**
1. Stream travels as `main` → 1 and `sub` → 2 from `LocalMediaChannel` to the
   child, validated at every hop. The parent rejects a setup whose stream
   differs from its selection.
2. Child and parent build their codecs with the same stream and independently
   parse the same envelopes. Neither invents status.
3. Keepalive, authority requests, credential handoff and the original-owner
   rules are unchanged.

**Steps:**
- [ ] **Step 1: Write the failing tests.**
  - `test_provider_opens_sub_stream_selection`.
  - `test_provider_maps_device_refusals[busy-429,denied-502,refused-502]` (RF1).
  - `test_setup_stream_mismatch_denied`.
  - `test_serve_live_sub_cap6_sends_1285_and_accepts_10000505`.
  - `test_serve_live_sub_cap4_sends_1281_stream2`.
  - `test_serve_live_forwards_refusal_then_closes` (RF1).
  - `test_keepalive_unchanged_for_sub_stream`.
  - `test_main_stream_behaviour_unchanged`.

  All of them use fake natives, pipes and synthetic bytes.
- [ ] **Step 2: Run and confirm they fail.**
  `.venv/Scripts/python.exe -m pytest tests/contract/test_local_live_provider.py tests/contract/test_windows_socket.py -q`.
- [ ] **Step 3: Implement** requirements 1–3.
- [ ] **Step 4: Run** both contract files and `tests/tvt_parity/test_local_live.py`.
  The recorded baseline is 313 passing in `test_windows_socket.py`. Report the
  new count and any pre-existing environmental failures separately.
- [ ] **Step 5: Static gates and docs.**
- [ ] **Step 6: Report.** No commit. The native receipt is the controller's.

## Task 4: No-signal first-frame bound and error-code forwarding

**Files:**
- Modify: `services/tvt-media/src/wso_tvt_media/native_source.py`:
  - `start()` records the start time;
  - `binding()` (`:411-418`) waits at most `FIRST_FRAME_SECONDS` from start,
    then stops the source and raises `MediaNoSignal`, a new subclass of
    `MediaDenied`.
- Modify: `services/tvt-media/src/wso_tvt_media/worker.py`. In `start()`
  (`:77-109`), `MediaNoSignal` becomes
  `LocalDeviceFailure("LOCAL_DEVICE_NO_SIGNAL", 504)`. Every other failure maps
  exactly as today.
- Modify: `packages/core/src/wso_core/tvt/local_service.py`. Add
  `"LOCAL_DEVICE_NO_SIGNAL": 504` to `LOCAL_DEVICE_FAILURES`. This file may be
  a native-receipt dependency, in which case Task 7's receipt covers it.
  - Grep for every table or enum that lists `LOCAL_DEVICE_DEADLINE_EXCEEDED`
    (contracts, RPC validation, API responses, web schemas) and add the new
    code wherever one is listed.
- Modify: `apps/web/src/lib/tvt/local-live-proxy.ts`. On `!upstream.ok`, read
  at most 4 KiB of the upstream JSON. Forward `error.code` only when it is in
  the `LOCAL_DEVICE_*` table and the status matches that table; otherwise keep
  `LOCAL_DEVICE_UNAVAILABLE`.
- Modify: `apps/web/src/lib/tvt/local-live-api.ts`:
  - `LocalLiveError(status, code: string | null = null)`;
  - `request()` parses a bounded error body (at most 4 KiB, strict schema) to
    fill `code`.
- Modify: `apps/web/src/lib/tvt/local-live-player.ts`. Add a read-only
  `failureCode: string | null` getter beside `failureStatus`.
- Modify: `apps/web/src/features/connections/local-live-panel.tsx`.
  `LOCAL_DEVICE_NO_SIGNAL` shows "영상 신호 없음 · 채널에 카메라가 연결되어
  있는지 확인하세요."
- Tests:
  - `tests/tvt_parity/test_local_media_source.py` and `tests/tvt_parity/test_local_media_worker.py`;
  - `apps/web/tests/local-live-proxy.test.ts`, `local-live-api.test.ts`,
    `local-live-player.test.ts` and `local-live-panel.test.tsx`.

**Steps:**
- [ ] **Step 1: Write the failing tests.**
  - `test_binding_without_frames_raises_no_signal_after_bound`: a fake clock
    and no frames gives `MediaNoSignal` at 10.0 s and not before (RF5).
  - `test_binding_first_frame_at_9_9s_succeeds`.
  - `test_worker_maps_no_signal_to_504_code_and_releases_source` (RF5).
  - `proxy forwards known upstream codes and masks unknown`.
  - `api error carries code`.
  - `player exposes failureCode`.
  - `panel shows 영상 신호 없음`.
- [ ] **Step 2: Run and confirm they fail.** Use the media selection (Task 1
  Step 4 command) and `pnpm --filter @wso/web test`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Python media selection, the web tests, lint and
  typecheck.
- [ ] **Step 5: Report.** No commit.

## Task 5: Capacity of 16 streams with bounded waits

**Files:**
- `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py` (native-owned):
  - `MAX_SERVICE_LIVE_SESSIONS = 16` (`:977`).
  - `LIVE_ATTEMPT_WAIT_SECONDS = 10.0`.
  - For live service calls, `attempt_scope` acquires `ATTEMPT_LOCK` with a
    timeout of min(remaining deadline, 10 s); a timeout raises `ProviderBusy`.
  - The uncertain-custody fence (`:1018-1029`) polls every 50 ms while time
    remains and raises `ProviderBusy` (not `ProviderError`) at the bound.
  - A full live count still raises `ProviderBusy` immediately.
  - Inventory calls keep today's behaviour, so verification is refused while
    live owners are pending. Record this as a stage-2 limit.
- `services/tvt-media/src/wso_tvt_media/worker.py`: `MAX_MEDIA_SOURCES = 16`
  replaces the literal `2` at `:115,145`.
- `packages/core/src/wso_core/tvt/local_media_admission.py`: pool
  `pool_size=8, max_overflow=8` (`:139-150`). Every other pool argument is
  unchanged.
- Create `infra/migrations/versions/0015_tvt_local_media_capacity.py`:
  - `CREATE OR REPLACE` of the 0013 issue function, changing only the
    per-tenant/actor cap (4 → 16) and the global cap (32 → 64) at `0013:130-131`;
  - downgrade restores the 0013 body verbatim;
  - `MEDIA_SOURCES` and the migrate target in `runtime.py` move to 0015.
- `scripts/test-local-devices/runtime.py:783`: RPC `capacity=32`. Find the
  API-side media RPC client registry capacity (the `registry.admit` →
  `AccountFailure` → BUSY path, `local_media_rpc.py:118,152`) and raise it to at
  least 32 if it is lower.
- Tests:
  - `tests/contract/test_local_live_provider.py`, replacing
    `test_two_original_windows_live_sessions_are_isolated_and_third_is_busy`
    with a 16-plus-one equivalent;
  - `tests/contract/test_windows_socket.py`, adding
    `test_live_attempt_waits_for_lock_then_busy`,
    `test_uncertain_custody_waits_then_busy_not_error` and
    `test_full_capacity_busy_immediately`;
  - `tests/tvt_parity/test_local_media_worker.py`, updating the capped
    parameter cases;
  - `tests/tvt_parity/test_local_media_migrations.py`, adding
    `test_0015_changes_only_caps`;
  - guarded SQL: `test_media_sql_actor_cap_16` and `test_media_sql_global_cap_64`.

**Steps:** write the failing tests → run them and confirm they fail → implement
→ run the contract files, the media selection and the guarded SQL suite →
static gates → report (no commit).

## Task 6: Wall stream policy, capacity and no-signal UX

**Files:**
- `apps/web/src/lib/tvt/local-live-api.ts`: `LocalLiveBinding` gains
  `stream?: 'main' | 'sub'` (default `'main'`); `startLocalLive` sends it
  (`:46`).
- `apps/web/src/lib/tvt/live-wall-scheduler.ts`:
  `LIVE_WALL_CONCURRENCY = 16` (`:26`).
- `apps/web/src/features/monitoring/live-wall.tsx` and `live-tile.tsx`:
  - Grid tiles start with `stream: 'sub'`.
  - Enlarging a live tile stops its sub session and then starts `main`; closing
    the enlarged view stops `main` and restarts `sub` if the tile was live.
    Both go through the scheduler, so stop completes before start.
  - A busy refusal during a switch uses the existing busy re-queue (RF4).
  - `LOCAL_DEVICE_NO_SIGNAL` puts the tile in a terminal `nosignal` state
    labelled "영상 신호 없음": no retry, no cool-down, and a manual play
    restarts it (RF5).
  - The tile shows "고화질" or "저화질".
- `apps/web/src/features/connections/local-live-panel.tsx`: a 화질 select,
  고화질 (default, today's behaviour) or 저화질.
- Tests:
  - `apps/web/tests/live-wall-scheduler.test.ts` (concurrency 16 pin at `:43-44`);
  - `live-wall.test.tsx` (sub in grid, main on enlarge, return to sub, rapid
    toggle ×10 leaves exactly one live session per channel and no leaked
    leases (RF4), no-signal terminal without retry or cool-down (RF5));
  - `local-live-api.test.ts` (stream default and sub; pin at `:20-27`);
  - `local-live-panel.test.tsx` (quality select).

**Steps:** write the failing tests → run them and confirm they fail → implement
→ `pnpm --filter @wso/web test`, `lint` and `typecheck` → report (no commit).

## Task 7 (controller): reviews, receipts, approval, device acceptance and sizing gate

Final-review correction R135 (2026-10-05): replace the inherited generic 15 s
wall timer with bounded forward-only phase clocks: original Stop wait 26 s;
actual start HTTP 26 s beginning immediately before the player request;
negotiation 35 s; combined presentation/playing confirmation 40 s. The latter
is a combined allowance, not a separate 15 s frame timer. Preserve HTTP 25 s,
ICE 8 s, native first-frame phases 10 s and API 20 s. Fallbacks are generic
failure; validated NO_SIGNAL remains terminal without retry/cooldown.
Original Stop ownership and current-player fencing remain authoritative.
The [browser integration guide](../../integrations/tvt-local-media-web.md)
records exact triggers, TDD, verification and the longer failure-detection
tradeoff. This correction requires the scoped final re-review below.

- [x] **Independent native review** (most capable model; reads the APK
  references) of the combined native-owned delta from Tasks 2, 3 and 5.
  - The reviewer also acknowledges R120's change to the owner-contract wording
    (the callback is now at most 100 ms old).
  - Record it in `docs/analysis/2026-10-05-multiview-stage1-native-review.md`
    with a verdict line.
  - Fix and re-review until the blocking findings are C0/I0.
- [x] **Receipts.**
  - A new W08-style LIVE receipt for the codec, then the `windows_socket.py`
    receipt constants.
  - Then a new immutable native receipt under a new filename (`open('xb')`,
    ACL-protected). `verify_review` must return the expected row count.
- [x] **Guarded SQL evidence run** pinning 0014, 0015, the admission and the
  integration tests.
- [x] **Final whole-branch review** of stage 1, then one fix wave and a scoped
  re-review.
- [x] **Approval c6**, with sources plus 0014, 0015, the new tests and docs.
  Record the new review phrases in liveness review §6d before it is created.
  Execution update2026-10-06: these source gates passed. Actual c6/c7 did not
  pass the complete sizing gate; c7 proved dimension changes were the initiating
  fault. R137 bounded source decoder rotation is frozen for independent review;
  new immutable c8 is required before repeating actual acceptance. Existing
  approvals/evidence remain unchanged. See the canonical service analysis for
  actual results and verification limits.
- [ ] **Device acceptance (partial; executed c6–c12)** with controller Chrome (R105) and the runtime
  stopped before any edit.
  1. A sub stream on one tile per store. Record whether the acknowledgement
     warning flag was set, media kind 2, resolution, codec and frames per second.
  2. **Sizing gate** at 1, 4 and 8 + 4 tiles on `/monitoring`. Record:
     - SQL tx/s, WAL B/s, CPU and memory per process, and Chrome dropped
       frames;
     - start latency p50/p95 (browser trace);
     - recorder refusals and their codes.
  3. Store 1 channels 1 and 3 show "영상 신호 없음" within about 12 s, without
     retry.
  4. Enlarge → main and return → sub.
  5. Stop all: every lease is `CLOSED` with confirmed cleanup.
  6. Clean shutdown, source stability and 0 private occurrences.
- [ ] **Acceptance target.** All 12 tiles are concurrently either live on sub
  streams for at least 5 minutes or explicitly "영상 신호 없음". SQL stays at
  25 tx/s or less per live stream. No unexpected 429 or 5xx.
- [x] **Docs (source and partial actual outcomes; target remains open).**
  - Liveness review §6d.
  - Parity review statuses for the multi-view and sub-stream rows.
  - The service-analysis update log.
  - `AGENTS.md` pointers and the reboot handoff.
- [ ] **Commit locally only with the user's authorization.** Pushing remains
  the user's action.

## Out of scope (stage 2 and later)

### Task7 execution correction — 2026-10-06

Tasks1–6 and combined source reviews are complete; device acceptance is still
open. c9/c11 reached nine concurrently playing substreams. Login BUSY is proven
and is mapped only after exact original-child retirement; occasional c11
connect/greeting failures occurred before login and remain protocol failures.
The current per-tile connection model did not meet the twelve-tile target.
This does not justify changing the acceptance checkbox to complete or asserting
a universal recorder limit. Per-device shared channel transport remains the
specified stage2 dependency for APK-equivalent simultaneous viewing.

Step3's assumed NO_SIGNAL result on store1 channels1/3 is contradicted for
substreams: both deliver valid352x240 frames. Accept valid substream media;
require terminal NO_SIGNAL only when an acknowledged open actually yields no
qualifying frame within the two reviewed10s phases. The source-level negative
tests pass; actual no-media negative acceptance has not yet run on this stream.
Do not reject a valid placeholder frame merely to satisfy the old assumption.

c10 was exceptionally retired after67issued/66CLOSED/oneSTOPPING-unconfirmed;
it remains a failed normal cleanup. c11 normal cleanup confirmed all201 leases
and original Chrome/coordinator0, API/worker settled/context removed/source
unchanged/private0, but its final observer publication failed at the65536-byte
writer limit. R143 repairs the observation-specific bounded budget only after
TDD and independent review. A fresh immutable approval and a bounded actual
run must follow; old approvals/results remain immutable. The canonical service
report and live/parity reviews preserve these separate outcomes.

R143 source gate passed C0/I0/M0 and c12 executed146 pinned sources
(approvald6cdf6e2/native0e7880d6). Actual results:

- [x] Both recorders' substreams/media kind2, HEVC, no adaptation-off warning;
 352×240 and704×480 returned formats.
- [x] Nine substreams progressed through one common300.849s interval; longer
 live-test elapsed1091.280s still had nine progressing videos. No recorded
 timestamp_invalid/ingress overflow/format_changed first failure.
- [x] SQL1/4/8 historical sizing plus current nine-stream sizing below25tx/s/live;
 current60s nine-stream six samples19.722–20.789; five CPU samples complete.
- [x] Actual1280×1936 main focus, return352×240 sub; ten rapid UI click pairs
 end nine subleases. These are not ten completed main opens.
- [x] All90 leases CLOSED/confirmed(main3/sub87), original Chrome/coordinator0,
 API/worker/context/ownedDB settled, approved source stable/private0.
- [x] Final observer COMPLETE/errors+omissions0/stoptrue/writersettled/hash gate
 true, digestccd899a5...;45511 compact bytes replace71089 old pretty bytes.
- [ ] All twelve simultaneous tiles/five-minute gate, no unexpected429/5xx.
 The per-tile login model still receives native BUSY and startup protocol failures.
- [ ] Actual acknowledged-no-media negative on a qualifying stream; known
 store1channels1/3 are valid substream media and cannot supply that negative.

See canonical service analysis and the dated stage1 acceptance report for
process/window/memory/latency limits. Post-retirement reports may now update.
Normal c12 acceptance preserves the old c10/c11 failures. Per-device shared
transport is the next architectural design; no stage2 implementation is granted
by declaring this incomplete capacity target complete.

- A per-device multiplexer: one login per recorder carrying channel-dispatched
  route-0 tasks. It needs a new codec contract, because the APK dispatches by
  `ep3.e` only, with no fence.
- Viewer fan-out (migration 0016).
- Production bootstrap, quarantine recovery, TURN and the staff viewer role.
- Device verification while streaming.
- Stream selection for `capture_live`.
- Mapping the recorder's login-time `0x20000030` (busy) refusal, unless the
  sizing gate shows connection refusals.

## Execution handoff

Recommended: **subagent-driven**. The six implementer tasks share tight
interfaces (codec → bridge → API → web), touch native-receipt and SQL
security boundaries, and a shipped mistake would weaken live authority, so each
task needs its own reviewer. **Execution starts only after the user approves
this plan.**
