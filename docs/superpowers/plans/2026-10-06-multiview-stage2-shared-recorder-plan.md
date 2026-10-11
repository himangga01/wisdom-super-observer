# Shared-recorder Multiview Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two original Windows recorder connections deliver all eight plus four substreams concurrently, with scoped viewer Stop, safe main focus/return and confirmed native retirement.

**Architecture:** Keep immutable substream tasks inside each actor/session recorder epoch. Separate transport, channel retention and viewer publication authority; a dedicated original supplies at most one main focus. New local ingress provenance and typed cleanup preserve fences that the taskless recorder media cannot supply.

**Tech Stack:** Existing Python3.12, FastAPI/Pydantic2, SQLAlchemy/PostgreSQL17, gRPC/protobuf, Windows ctypes provider and owned FFmpeg decoder, aiortc/VP8, Next16/React19/TypeScript/Zod/Tailwind4. Use existing lockfiles; no new product dependency is needed by this plan.

**Spec:** [Approved shared-recorder design](../specs/2026-10-06-multiview-stage2-shared-recorder-design.md), SHA256 `036908e32cbb72024e340d8a3fc3e298838e69e1c19db14427a2fafbad5e53ee`. Independent design review: [C0/I0/M0](../../analysis/2026-10-06-multiview-stage2-design-review.md). User approved the written spec2026-10-06 with "진행해 승인". This plan is being written for its separate review; it is not implemented code.

## Global Constraints

- Worktree `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`; branch `codex/superlive-web-service`, HEAD6436748 plus reviewed uncommitted stage1 throughR143. Preserve those changes. PowerShell tools use `login:false` and explicit workdir.
- One OWNER/wall group per actor/web session; no sharing across users/tabs, staff, cloud devices, TURN, audio, playback/PTZ or production bootstrap. Default legacy mode remains available for rollback. Do not mix a legacy independent viewer and this qualified shared profile in one worker lifetime.
- Immutable task per original epoch/channel/substream; no close/reopen task incarnation on the same shared connection. Never disable the legacy exclusive-first-task fence to achieve mux. Native fields/ACKs are accepted only from decoded evidence.
- Full epoch key includes tenant/tenant epoch, actor, session digest, wall/store/device/connection, generation, secret version, inventory revision and worker epoch. Master True is transport maintenance only, never all-channel publication permission.
- Parked retention expiry at most30s, clipped to wall/session/configuration/credential/master validity; renew only from valid same-owner wall heartbeat plus that channel's current rights. Keepalive6s; native orphan renewal at most30s. No last-reference retention without a current viewer/focus reference.
- FORWARD_PENDING/RETURN_PENDING max20s from original admission, clipped to caller/authority expiry, nonrenewable by repeated clicks. RETURN_PENDING atomically replaces MAIN_ACTIVE before main Stop. Keep single nonclosed viewer/channel, including STOPPING issue rejection.
- Preserve qualified100ms call-entry observation freshness, R120/R133 slow eligible success and immediately expired reusable cache, sticky known denial, separate200ms sender permits/expiry; no end-to-end100ms revocation or camera capture-freshness promise.
- At most2 base originals,1 dedicated main,12 active viewers/decoders and16 physical slots including parked/tombstoned; keep actor16/global64 SQL admission and eight-long-start reservation/8+8 pool. All pending/uncertain originals remain charged.
- Encoded credit16 pictures/4MiB per slot across all stages,64MiB globally; native callback256 chunks/1MiB; outer/IPC envelope1MiB. Latest RGB1/viewer,16MiB/frame,32MiB/response; conversion/pending output charged before allocation. Shared retained media1GiB, worker process2GiB, each decoder/native original512MiB. Proposed9.5GiB maximum process profile is a qualification ceiling, not predicted use; prove Windows Job compatibility and host headroom before enabling it.
- Startup20s, original-custody wait at most10s, accepted-open key10s, first decoded frame10s, pressure/format transition5s; shorter caller/authority budget wins. Current/Stop checks at most50ms. Preserve R135 browser phases Stop26s/request26s/negotiation35s/combined presentation40s without extending backend budgets.
- Local ingress ordinals precede application-visible byte copying; retain provenance through callback/IPC/partial assembly. New viewer first key and required parameter sets must be entirely post-cut; old RGB/returned batches and late registration results are ineligible. Opaque SDK/OS/network capture age remains unknown.
- Preserve R137 same-codec self-contained random-access rotation,16 rotations/rolling60s, original decoder settlement before replacement. Preserve R142 raw nondecreasing/lifetime frame order and mapped minimum24us; no clock/order reset on park/reattach.
- SQL cleanup scopes VIEWER, DEDICATED_NATIVE, LAST_VIEWER_AND_DEVICE_EPOCH are internal evidence. Viewer CLOSED never implies a parked task physically closed. Last-reference/Stop All/main Stop need actual original handle/Job/IPC retirement. Revocation/uncertain slot stop retires the whole recorder master; other recorder may continue.
- Add0016; do not modify applied0013–0015 or confirm old pending/quarantined rows. Native/runtime receipts are immutable under new filenames and independently reviewed; no source edit while a pinned acceptance runtime runs.
- No actual serials, credentials, native/device/session/channel/task GUID values, cookies/SDP, raw video or exception contents in source/tests/reports/output. Tests use synthetic values. Private SDK/media/binaries/generated runtime data remain ignored; source/tests/manifests/reports remain intended Git content.
- R104 persists: implementers do not stage/stash/reset/commit/push. Root snapshots with a temporary Git index, reviews exact deltas and records custody. Git publication is a separate authorized controller action; plan writing does not authorize it.

## Review Focus

1. Complete/partial pre-cut key hidden in callback, IPC or assembler must not initialize a new viewer. Pin in Tasks2/3/8, including parameter-set fragments and returned-uncommitted frames.
2. Sole-viewer focus and return, cancellation at each barrier and repeated clicks must neither strand MAIN_ACTIVE nor keep an authority-free master. Pin in Tasks6/10/11 with the exact20s cap.
3. One stalled/no-credit channel must not create unlimited shared buffering or conceal sibling/control starvation. Pin in Tasks3/7/8; fence the epoch on the bounded pressure failure, do not invent arbitrary active-frame dropping.
4. SQL slow success, role/secret/session/channel revocation and callback return racing denial must preserve qualified freshness and prevent wrong-slot publication. Pin in Tasks5/6/7/8; deny/reap the exact master when required.
5. Last detach racing attach, missing original receipt or native/decoder crash must remain STOPPING/quarantined/charged. Pin in Tasks4/5/6/7/9/12; no PID reacquisition or SQL-only cleanup confirmation.

## Source baseline and existing interface corrections

The current `LiveCodec` is one-task stateful, `CallbackOwner` and raw IPC batches carry bytes without ingress provenance, and `OwnedLocalLiveSession.close()->bool` currently means full original cleanup. Public `MediaLease` has no cleanup flag; preserve that DTO distinction. `LocalMediaAdmission.open()` currently holds a startup transaction over the credential/native callback. Shared startup must explicitly change to short reserve/read/commit operations with native waits outside checkout/transaction, rather than assume that separation already exists.

The unique active-channel index excludes STOPPING, while SQL issue separately blocks every non-CLOSED row under advisory locking. Preserve both checks. The source table is not an actor authority proof by itself. Existing c12 demonstrates nine streams, not shared12; [actual acceptance](../../analysis/2026-10-06-multiview-stage1-acceptance.md) stays historical.

## File structure and ownership

| New boundary | Responsibility | Existing integration |
| --- | --- | --- |
| `core/tvt/local_live_mux.py` | Immutable slot wire state and bounded ingress provenance | Leave `local_live.py` strict; share only pure validation helpers after regression proof |
| `bridge/local_live_mux_ipc.py` | Versioned private mux messages, cuts, credits and original parent/remote owners | `windows_socket_worker.py`, original `ChildOwner` |
| `core/tvt/local_media_mux_types.py` | Sealed scope/reservation/cleanup contracts and capacity constants | Private admission/service/provider boundaries, no frontend native IDs |
| `core/tvt/local_media_mux_admission.py` | Short SQL authority/reservation/typed cleanup | Additive0016 and existing credential codec/cache patterns |
| `core/tvt/local_media_mux_service.py` | Epoch/slot/viewer/focus lifecycle and original cleanup barriers | Existing public live executor/worker adapters |
| `bridge/local_live_mux_provider.py` | One original recorder provider and slot viewer handles | Legacy provider retained for dedicated main; new receipt closure |
| `media/mux_source.py`, `media/mux_budget.py` | Fresh-cut viewer ingress and bounded shared credits | Reuse decoder/peer logic with explicit frame-source port, no new decoder protocol |
| `contracts/tvt/local_media_mux.py` | Public wall/transition DTOs, private request validation | Protobuf/BFF/API routes, generated schemas |
| `web/lib/tvt/local-live-wall-api.ts` | Same-origin wall heartbeat/focus reservation calls | Existing player/API/scheduler/monitoring components |

Here `core/`, `bridge/`, `media/`, `contracts/`, `web/` expand respectively to
`packages/core/src/wso_core/`, `services/tvt-bridge/src/wso_tvt_bridge/`,
`services/tvt-media/src/wso_tvt_media/`, `packages/contracts/src/wso_contracts/`,
`apps/web/src/`. Task Files below use exact paths.

## Task order, parallel work and gates

Root writes the interfaces below once and supplies each implementer its dependencies. Tasks1–6 run sequentially because they transfer pure-type and native worker write ownership; do not pretend shared files are independent. After Task6 freezes ports, Tasks7(provider),8(media) and9(API/RPC) can run in parallel with distinct files. Task10 may begin after Task9 while7/8 finish; Task11 follows10 and waits for7/8 integration before the whole composed gate. Root's Task12 owns final source/SQL/receipt review and staged real probes. Each task has a fresh spec+quality reviewer; only approved source advances. Three worker slots plus Root are available, so at most three implementers/reviewers run concurrently.

The execution method remains main/subagent driven as already requested. No implementation is started while the plan is awaiting its required review. Tasks that cannot fulfill a wire/ABI proof fail at that named gate and revise the affected design; they never fall back to guessed ACK/task fields.

## Task 1: Private mux types and immutable wire codec

**Files:** Create `packages/core/src/wso_core/tvt/local_live_mux.py`, `packages/core/src/wso_core/tvt/local_media_mux_types.py`, `tests/tvt_parity/test_local_live_mux.py`. Modify `packages/core/src/wso_core/tvt/local_live.py` only for explicitly extracted pure helpers. Read `docs/integrations/tvt-local-live-codec.md` and retained APK `fu3.I5/J5`, `cw3.jb/kb/s7/Z9/X7/m8`; save targeted source gate in `docs/integrations/tvt-local-live-mux-codec.md`.

**Interfaces:** Define private frozen `MuxEpochIdentity(generation:int,session:bytes)`, `MuxSlotIdentity(epoch:MuxEpochIdentity,channel:bytes,task:bytes,stream:int)` with only stream2 on a base master; `IngressSpan(first:int,last:int)` positive64bit/no wrap; `IngressChunk(data:bytes,span:IngressSpan)`; `IngressCut(epoch:MuxEpochIdentity,slot:MuxSlotIdentity,registration:UUID,control_sequence:int,after_ordinal:int,expires_monotonic:float)`; sealed `MuxValidatedFrame(frame:PrivateLiveFrame,slot:MuxSlotIdentity,ingress:IngressSpan,mapped_timestamp_us:int,slot_ordinal:int)` and `MuxAcknowledgement(slot:MuxSlotIdentity,accepted:bool,warning:bool)`. `MultiplexLiveCodec(*,epoch:MuxEpochIdentity,peer_capability:int,authorize:Callable[[MuxSlotIdentity],bool])`; `register_slot(slot:MuxSlotIdentity,*,channel_number:int)->None`; `open_slot(slot:MuxSlotIdentity,*,request_guid:bytes,sequence:int)->PrivateLiveBytes`; `feed(chunk:IngressChunk,*,generation:int)->tuple[MuxValidatedFrame|MuxAcknowledgement,...]`; `tombstone(slot:MuxSlotIdentity)->None`. One pending wire control, connection-wide sequence; channel stream/order/time persists. Add `SlotMediaClock.accept(raw_timestamp_us:int,wire_frame_index:int)->tuple[int,int]` implementing R142 exactly for each slot, including parked validated frames; its sealed mapped time/ordinal is reused by Task8, never regenerated from a viewer reset. Keep wire types stdlib/pure-codec only; SQL/contract imports must not break the native isolated bootstrap. SQL native_generation UUID and wire identity generation int are distinct. Native scope key/cleanup enums and sealed SQL grant types are finalized in Task5's Interfaces.

- [ ] Write `test_twelve_interleaved_slots_keep_original_identity`, `test_second_open_same_channel_fences_epoch`, `test_route0_cannot_bind_unregistered_channel`, `test_wrong_epoch_stream_task_or_ack_sequence_rejected`, `test_cross_cut_partial_preserves_first_byte_origin`, `test_slot_raw_order_survives_park`. Assert12 distinct slots, immutable task, stream2, strict per-channel wire index and complete first/last ingress provenance; native sequence never resets/wraps.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_live_mux.py -q`; confirm the new behavior is RED before adding it.
- [ ] Implement the exact private types/codec; preserve source-confirmed1285/legacy1281, task-correlated class3 refusal and adaptation warning. Extract no stateful legacy `_media` as if it were a pure helper; unknown/ambiguous routing fences the epoch. Parser bounds are retained/envelope/fragment bounds, not an inherited32MiB/4096-packet capture-lifetime limit across twelve continuous streams; use checked64bit cumulative counters and fail before wrap, never silently reset. Pin a long inert feed exceeding those legacy constructor defaults with bounded retained memory.
- [ ] Run new codec plus `tests/tvt_parity/test_local_live.py`; GREEN, all legacy invariants preserved. Record focused Ruff/mypy commands and results on changed production paths.
- [ ] Save APK/source facts versus unresolved owned-probe gates; freeze task delta and fresh independent review. No task commit.

## Task 2: Original callback ingress cuts and worker provenance

**Files:** Modify `services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py`; create `tests/contract/test_local_mux_callback.py`. Task3 owns the new IPC module; serialize edits to this shared worker file if Tasks2/3 overlap.

**Interfaces:** Task1 `IngressChunk/Span/Cut`. Add `CallbackOwner.take_mux_batch()->tuple[IngressChunk,...]` without altering legacy `take_live_batch`; `CallbackOwner.cut_mux_ingress(*,registration:UUID,slot:MuxSlotIdentity,control_sequence:int,expires_monotonic:float)->IngressCut`. Mux callback ordinals are assigned under the same short nonblocking original callback guard before byte copy; mux assembly emits frames with their contributing provenance. The child exports a cut only through its private same-generation control reply, not a public SDK field.

- [ ] Write `test_callback_before_cut_cannot_gain_post_cut_origin`, `test_complete_and_partial_key_held_before_cut_ineligible`, `test_cut_races_nonblocking_copy`, `test_ingress_overflow_and_counter_wrap_sticky`, `test_legacy_first_claim_and_batches_unchanged`. Hold a borrowed-buffer copy before admission; assert first ordinal cannot be rewritten after queued/assembled delivery,256 chunks/1MiB caps remain and cut has the exact original epoch/registration/sequence/expiry.
- [ ] Run only `tests/contract/test_local_mux_callback.py` RED against the new entry points.
- [ ] Implement callback provenance and a separate mux worker mode. Preserve borrowed-buffer copy lifetime, retained callbacks/context and native no-reentry rules. Do not block a callback for cut/SQL/control.
- [ ] Run callback tests plus affected `test_windows_socket.py` callback/claim cases. GREEN; no actual SDK import/call. Scoped native review inspects original-owner/overflow paths.
- [ ] Freeze Task2 and hand Task3 the typed batches/cut response. No receipt or runtime acceptance is implied.

## Task 3: Private mux IPC, framing and shared credit

**Files:** Create `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py`, `tests/contract/test_local_live_mux_ipc.py`; modify mux worker dispatch in `windows_socket_worker.py` after Task2 gate.

**Interfaces:** Define `MuxPurpose` enum TRANSPORT/SLOT_CONTROL/SLOT_RETENTION/VIEWER in pure mux types. `MuxParentAuthority(*,epoch:MuxEpochIdentity,authorize:Callable[[MuxPurpose,MuxSlotIdentity|None,UUID|None],bool],clock:Callable[[],float])`; `pump(owner:ChildOwner,*,deadline_monotonic:float)->bool`; `register_slot(slot:MuxSlotIdentity,*,channel_number:int)->None`; `admission_cut(slot:MuxSlotIdentity,*,registration:UUID,deadline_monotonic:float,cancel:Event)->IngressCut`; `read_frames(slot:MuxSlotIdentity,*,cut:IngressCut,max_frames:int,max_bytes:int,deadline_monotonic:float)->tuple[MuxValidatedFrame,...]`; `park(slot:MuxSlotIdentity)->None`; `confirmed_closed()->bool`. TRANSPORT names only original epoch; slot purposes require slot and VIEWER additionally requires registration. `MuxRemoteAuthority` implements that strict private child message envelope; a generic True cannot satisfy another purpose.

- [ ] Write `test_provenance_survives_callback_batch_ipc_and_fragments`, `test_cut_rejects_foreign_epoch_registration_sequence_expiry`, `test_no_credit_has_bounded_control_progress`, `test_stalled_slot_cannot_allocate_hidden_batch`, `test_unknown_slot_tombstone_and_deadline_fence`. Interleave12 slots, pre-cut IPC/key fragments and one exhausted slot; assert16frames/4MiB total slot credit,64MiB aggregate and1MiB envelopes, exactly charged bytes and preserved sibling order.
- [ ] Run new IPC tests RED. Use inert original-child controls, not recorder fixtures.
- [ ] Implement versioned strict mux envelopes carrying unchanged raw bytes and explicit span/cut/proof metadata. Authenticate generation/sequence/purpose/current grant at both ends; retain at most one outstanding raw/control owner. Five-second pressure or shorter authority deadline fences the original epoch; at most50ms Stop/current polling. Do not drop arbitrary active inter pictures or invent extra FIFO capacity.
- [ ] Define private `make_mux_worker_input(credentials:LocalDeviceCredentials,*,generation:int,initial_expiry_ms:int)->bytes` here using existing validated credential/worker-input encoding patterns; strict closed fields, max16384bytes, expiry clipped to remaining caller/transport authority and at most30000ms. Keep only native-required credential/generation/lifetime input, not arbitrary caller-supplied authority/SQL scope. Parent retains and rechecks typed SQL scope; child obtains purpose-bound renew/cut/slot controls over the original pipe. No input/secret logging.
- [ ] Run new IPC and affected legacy `test_local_live_pressure.py`/provider IPC selections GREEN. Check cancellation/denial precedes credit/cut responses and original ACK order remains intact.
- [ ] Freeze IPC contract and independent review before any provider/owned probe uses it.

## Task 4: Original Windows ownership and process memory caps

**Files:** Modify `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py`; create `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ownership.py`, `tests/contract/test_local_mux_ownership.py`. Reuse exact `ChildOwner`/Job custody; new mux provider is Task7.

**Interfaces:** Add `WindowsSocketProvider.open_mux(serialized_input:bytes,*,deadline_monotonic:float,current:Callable[[],bool],cancel:Event)->ChildOwner` for a separately reviewed mux worker entry. Input is only Task3's bounded private packet, validated again by worker before native use; Job admission/current recheck precedes its release. Original `ChildOwner` remains the custodian of pipe/thread/Job/Popen handles; native slots are not separately reacquired OS processes. Define sealed `MuxOriginalReservation(id:UUID,kind:Literal['base','main'],worker_epoch:UUID)` in pure mux types and `MuxOriginalBudget` in the new bridge ownership module. Its Core `MuxOriginalBudgetPort` Protocol declares `reserve(kind:Literal['base','main'])->MuxOriginalReservation`, `release_confirmed(reservation:MuxOriginalReservation,receipt:EpochCleanupReceipt)->None`. Bridge-only `bind_original(reservation:MuxOriginalReservation,owner:ChildOwner)->None` binds once before native input; release verifies that privately retained exact owner is confirmed and matches receipt scope. Reserve base2/main1/physicalslots16, keep pending/quarantine charged; callers cannot forge capacity release. Core imports no bridge/native module at runtime.

- [ ] Write `test_two_base_one_main_and_uncertain_owner_are_charged`, `test_failed_ownership_never_adopts_new_pid`, `test_original_job_memory_limit512mib`, `test_cut_current_and_cancel_precede_open`, `test_existing_native_busy_recovery_is_unchanged`. Assert base3/main2 reject BUSY, pending originals count, and only exact confirmed original retirement releases quota.
- [ ] Run inert ownership/Job tests RED. No native DLL calls or unknown process signals.
- [ ] Implement separate mux launch plus512MiB per-native process limit and existing active-process1/kill-on-close Job. Prove nested Job/owned decoder/worker2GiB process-limit compatibility with an owned inert child; do not enable a cap based on OS assumptions. Keep current global uncertain-owner creation fence and bounded10s/50ms waits.
- [ ] Run focused ownership and R139 original-result tests GREEN, original child/Job receipts retained. Read host physical memory/core count for the9.5GiB qualification profile, report measured headroom; if incompatible, keep shared mode disabled and revise the profile before actual probes.
- [ ] Freeze native ownership delta for independent review. New source/native receipts occur only in Task12 after the whole native closure is approved.

## Task 5: Additive0016 and purpose-specific SQL admission

**Files:** Create `infra/migrations/versions/0016_tvt_device_media_epochs.py`, `packages/core/src/wso_core/tvt/local_media_mux_admission.py`, `tests/integration/test_local_media_mux_admission.py`, `tests/tvt_parity/test_local_media_mux_migrations.py`; extend `local_media_mux_types.py` (Task1 owner hands off). Preserve applied0013–0015. Extend the owned SQL fixture to migrate0016 without changing source database.

**Interfaces:** Define private frozen `MuxScopeKey(tenant_id:UUID,tenant_epoch:int,actor_user_id:UUID,session_digest:bytes,wall_id:UUID,store_id:UUID,device_id:UUID,connection_id:UUID,connection_generation:int,secret_version:int,inventory_revision:int,worker_epoch:UUID)`. `TransportGrant`, `SlotRetentionGrant`, `ViewerGrant`, `FocusGrant` are different sealed types, each with private authority token, exact scope and clipped expiry; viewer adds lease/registration, slot adds immutable slot, transport adds SQL native_generation UUID. Only this admission factory can mint them. Add `MasterLoginProof(login_accepted:bool,same_original_session:bool,serial_matched:bool,device_matched:bool,inventory_session_matched:bool,peer_capability:int)` from exact original login/inventory, separate from per-channel LocalLiveProof. Master activation never invents channel_matched/live_permission flags; every slot still requires its own same-session rights and open/frame proof. `CleanupScope` enum VIEWER/DEDICATED_NATIVE/LAST_VIEWER_AND_DEVICE_EPOCH; `ViewerCleanupReceipt(lease_id:UUID,registration_id:UUID,decoder_settled:bool,peer_settled:bool,media_cleared:bool)` and `EpochCleanupReceipt(master_id:UUID,worker_epoch:UUID,native_generation:UUID,original_state:Literal['NOT_CREATED','REAPED'],callback_settled:bool,ipc_settled:bool,job_settled:bool)` are separate sealed custodian capabilities, not caller boolean proofs. NOT_CREATED is valid only from the registered original constructor that proves no process/socket was created and all partial owners settled; it cannot certify a started/uncertain child.

`SqlMuxAdmission` reuses the approved engine/pool/cache pattern: `reserve_master(viewer:LocalMediaLease,*,budget:LocalVerifyBudget)->MasterReservation`; `prepare_login(reservation:MasterReservation,*,budget:LocalVerifyBudget)->tuple[LocalDeviceCredentials,TransportGrant]` returns credentials after its short transaction ends; `activate_master(reservation:MasterReservation,proof:MasterLoginProof,*,budget:LocalVerifyBudget)->TransportGrant`; `reserve_slot(viewer:LocalMediaLease,reservation:MasterReservation,*,budget:LocalVerifyBudget)->SlotRetentionGrant`; `admit_viewer(viewer:LocalMediaLease,slot:SlotRetentionGrant,*,registration:UUID,budget:LocalVerifyBudget)->ViewerGrant`; purpose-specific `current_transport(grant:TransportGrant)/current_slot(grant:SlotRetentionGrant)/current_viewer(grant:ViewerGrant)/current_focus(grant:FocusGrant)->bool`; `activate_viewer(grant:ViewerGrant,proof:LocalLiveProof,*,budget:LocalVerifyBudget)->MediaLease`; `finish_viewer(grant:ViewerGrant,receipt:ViewerCleanupReceipt,*,scope:CleanupScope)->None`; `finish_epoch(grant:TransportGrant,receipt:EpochCleanupReceipt)->None`; `dispose()->bool`. `MasterReservation` carries scope, master_id, creator bool, sealed transport authority/native UUID and deadline; followers receive the same original reservation, never a second creator.

New tables: walls, masters, slots, focus_refs under the existing TVT owner/FORCE RLS/no runtime direct privileges; nullable private viewer linkage on existing leases, with legacy cleanup scope unchanged. Slot unique(master,channel), sub only, immutable task, expiry<=30s. Closed viewer does not release retained slots/master; tombstones and uncertainty remain charged. New SECURITY DEFINER functions use fixed owner/search_path/lock budgets and explicit app/worker execute lists:

| New function suffix on `public.wso_tvt_local_media_` | Parameters / result |
| --- | --- |
| `wall_issue` / `wall_read` / `wall_stop_issue` | `(p_session text,p_ttl integer)->jsonb`; `(p_session text,p_wall uuid,p_heartbeat boolean)->jsonb`; `(p_session text,p_wall uuid)->text` |
| `shared_issue` | Existing issue argument list plus `p_wall uuid,p_focus uuid DEFAULT NULL` -> text; missing wall uses unchanged legacy issue |
| `master_reserve` | `(p_authority text,p_worker uuid,p_native uuid,p_master_authority text,p_master_native uuid)->jsonb` |
| `master_login` / `master_activate` / `master_observe` | Transport AUTH `(p_master_authority text,p_worker uuid,p_master_native uuid)` -> bounded private JSON; activate adds `p_proof jsonb`; login grants only the exact original login scope |
| `slot_reserve` / `slot_observe` | `(p_authority text,p_worker uuid,p_native uuid,p_master_authority text,p_master_native uuid,p_slot_authority text,p_task uuid)->jsonb`; observe `(p_slot_authority text,p_worker uuid,p_master_native uuid)->jsonb` |
| `viewer_admit` / `viewer_observe` / `viewer_activate` / `viewer_close` | Existing viewer AUTH plus `p_registration uuid` -> JSON; admit also names exact `p_slot_authority text`; activate adds `p_proof jsonb`; close adds `p_scope text,p_receipt jsonb` -> void |
| `focus_issue` / `focus_redeem` / `focus_settle` | `(p_session text,p_id uuid,p_direction text,p_deadline_at timestamptz)->text`; `(p_ticket text,p_worker uuid)->jsonb`; `(p_focus_authority text,p_worker uuid,p_transition text,p_viewer uuid DEFAULT NULL)->void` |
| `epoch_close` | Transport AUTH plus `p_receipt jsonb` -> void; accepts only exact custodian completion, never a viewer receipt |

`p_direction` is FORWARD/RETURN; settlement is ATTACHED/CANCELLED/FAILED/EXPIRED. SQL validates scope and durable state, while only worker custodian code can supply sealed receipt evidence. Extend lifecycle invalidation to new resources without changing legacy trigger meaning; retained slot revocation marks its whole master/attached viewers STOPPING. Preserve unique index plus non-CLOSED issue check and actor16/global64. No startup login/read holds SQL checkout or coordinator lock.

- [ ] Write tests `test_reserved_master_login_runs_after_transaction_release`, `test_viewer_receipt_cannot_close_epoch`, `test_stopping_viewer_blocks_shared_issue`, `test_each_retained_slot_revocation_stops_master`, `test_same_device_other_actor_or_secret_revision_never_joins`, `test_slow_success_has_expired_cache_and_denial_stays`, `test_new_rls_execute_and_caps`, `test_legacy_pending_cleanup_not_reclassified`. Assert2base/1main/16slots plus actor16/global64 and purpose-type mismatches, rollback/uncertain commit handling.
- [ ] Run new migration/offline cases RED and a new owned PostgreSQL selected suite through its explicit wrapper; no production/source DB migration. Pin0016 and test contents in that wrapper.
- [ ] Implement0016 down_revision=`0015_tvt_local_media_capacity`, grant constructors/functions and short reservation/login/activation transactions. Keep semaphore8 as reservation concurrency bound without retaining eight pool checkouts during native waits. Release/decrypt only exact current creator scope; followers wait outside SQL.
- [ ] Run selected migration/SQL tests GREEN with zero skips, original child reaped, owned DB removed/source DB content and historical0013–0015 function bodies/ACLs unchanged. Scoped Ruff/mypy; one fresh SQL/security review.
- [ ] Freeze admission/interfaces. No SQL JSON receipt alone is physical retirement evidence.

## Task 6: Epoch coordinator, parking and focus references

**Files:** Create `packages/core/src/wso_core/tvt/local_media_mux_service.py`, `tests/tvt_parity/test_local_media_mux_service.py`; extend Task1 mux types. Modify `local_media_service.py` with an explicit typed cleanup adapter while retaining legacy executor behavior.

**Interfaces:** Task4 reservation/budget port; `DeviceEpochCoordinator(admission:SqlMuxAdmission,provider:RecorderMasterPort,budget:MuxOriginalBudgetPort)`; `attach(viewer:LocalMediaLease,*,budget:LocalVerifyBudget)->MuxViewerHandle`; `detach(lease_id:UUID,*,budget:LocalVerifyBudget)->CleanupScope`; `reserve_focus(lease_id:UUID,direction:Literal['FORWARD','RETURN'],*,budget:LocalVerifyBudget)->FocusGrant`; `settle_focus(grant:FocusGrant,outcome:Literal['ATTACHED','CANCELLED','FAILED','EXPIRED'],*,viewer_id:UUID|None)->None`; `stop_wall(wall_id:UUID,*,budget:LocalVerifyBudget)->bool`; `shutdown()->bool`. `RecorderMasterPort.open_master(credentials:LocalDeviceCredentials,scope:MuxScopeKey,grant:TransportGrant,*,budget:LocalVerifyBudget)->OwnedRecorderMaster`; `OwnedRecorderMaster.open_slot(selection:LocalMediaChannel,grant:SlotRetentionGrant,*,budget:LocalVerifyBudget)->MuxSlotIdentity`, `attach_viewer(grant:ViewerGrant,*,budget:LocalVerifyBudget)->MuxViewerHandle`, `close()->EpochCleanupReceipt|None`. `MuxViewerHandle` exposes immutable `registration:UUID,cut:IngressCut,proof:LocalLiveProof`, `read_frames(*,max_frames:int,max_bytes:int,deadline_monotonic:float)->tuple[MuxValidatedFrame,...]`, `current()->bool`, `attach_retirement(check:Callable[[],ViewerCleanupReceipt|None])->None`, `close()->ViewerCleanupReceipt|None` only after its exact media barrier callback; it never closes a physical epoch implicitly. Task7 implements these ports. Define `MuxMediaExecutor` here with the existing executor's public start/current/lease/proof/playing/authorize_control/stop/finish_stop/shutdown contracts and explicit `read_mux_frames(lease_id:UUID,*,max_frames:int,max_bytes:int,deadline_ms:int)->tuple[MuxValidatedFrame,...]`; its legacy `read_frames` rejects in shared mode. Do not pass wrappers to the legacy raw-reader method.

- [ ] Write `test_concurrent_creators_publish_one_epoch`, `test_last_detach_vs_attach_requires_original_barrier`, `test_park_keeps_slot_identity_not_rgb`, `test_sole_forward_and_return_refs_cover_both_gaps`, `test_return_consumes_main_active_atomically`, `test_twenty_second_pending_never_renews`, `test_failed_busy_cancel_or_expiry_last_ref_retires_master`, `test_retention_denial_fences_all_master_viewers`. Assert short locks, credential work outside them, MAIN_ACTIVE cannot survive RETURN_PENDING and native uncertainty stays charged.
- [ ] Run coordinator cases RED with inert ports and exact20/30s fake clocks.
- [ ] Implement STARTING/ACTIVE/STOPPING/QUARANTINED/CLOSED, one original construction result, serialized slot opens, typed references/receipts. Set local denial before SQL close. Normal park drains/validates/discards upstream without decoding; every renewal is slot-specific. Main issuance waits sub CLOSED; returning sub waits main CLOSED/exact original reap and fresh cut. No replacement during pending custody.
- [ ] Run new service tests plus legacy service/worker stop-barrier cases GREEN. Add controllable delayed SQL beyond freshness/expiry and cancellation before/after each focus barrier; report qualified timing boundaries.
- [ ] Freeze coordinator and fresh security/concurrency review. Provider/media can implement these fixed ports in parallel without editing this coordinator file.

## Task 7: Shared original provider and custodian adapters

**Files:** Create `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py`, `tests/contract/test_local_live_mux_provider.py`, `tests/contract/test_local_live_mux_pressure.py`; integrate reviewed Tasks2–4 entry points in `windows_socket.py/windows_socket_worker.py` sequentially with their file owners. Add integration guide `docs/integrations/tvt-local-live-mux-provider.md`.

**Interfaces:** `NativeLocalMuxProvider(native:WindowsSocketProvider).open_master(...)` implements Task6 `RecorderMasterPort`. `OriginalRecorderMaster` owns exact ChildOwner/MuxParentAuthority and Task1 identity; `MuxSlotViewer` implements `MuxViewerHandle` and binds each returned frame to original epoch, immutable slot, registration, cut and current publication grant. Only exact original owners mint EpochCleanupReceipt; only settled registration/decoder/peer owners mint ViewerCleanupReceipt. Task4 ledger release requires the epoch receipt plus same ChildOwner identity, not generic object equality.

- [ ] Write `test_one_login_carries_twelve_original_slots`, `test_post_cut_viewer_frames_keep_real_task_not_local_generation`, `test_park_discard_and_retention_heartbeat_no_blanket_allow`, `test_cut_read_rechecks_current_after_callback`, `test_original_crash_quarantines_without_scope_adoption`, `test_sibling_stall_epoch_pressure_fences_at_five_seconds`. Inert coupled callback→child→parent→viewer tests must cover no hidden frame/byte FIFO and exactly one original.
- [ ] Run new provider/pressure suites RED. These are synthetic custody/protocol tests, not recorder acceptance.
- [ ] Implement original login/same-session inventory and per-slot permission proof before open, strict mux pipe/cut handling and purpose-bound renewal. Dedicated main delegates to the unchanged exclusive provider; preserve R139 only exact known login BUSY after original reap. Do not reclassify arbitrary protocol/network errors.
- [ ] Run mux/provider/pressure and affected existing original custody tests GREEN; scope static/native independent review. Explicitly prove no second slot/task for a channel, no viewer-only receipt frees native quota and callback remains nonblocking.
- [ ] Freeze provider closure; record actual route/ACK behavior as an open Task12 probe gate, not a native success claim.

## Task 8: Shared frame-source port, persistent clocks and media budgets

**Files:** Create `services/tvt-media/src/wso_tvt_media/mux_source.py`, `services/tvt-media/src/wso_tvt_media/mux_budget.py`, `tests/tvt_parity/test_local_media_mux_source.py`, `tests/tvt_parity/test_local_media_mux_budget.py`. Modify `native_source.py`, `worker.py`, `live.py` only at explicit source/budget ports; keep legacy exact-type/decoder/peer fences.

**Interfaces:** `MuxFrameSource(viewer:MuxViewerHandle,grant:ViewerGrant,registration:UUID,cut:IngressCut,credit:MediaCreditLedger)`; `read_frames(*,max_frames:int,max_bytes:int,deadline_monotonic:float)->tuple[MuxValidatedFrame,...]`; `current()->bool`; `close()->ViewerCleanupReceipt|None`. Add `NativeFrameAdapter.packet_mux(frame:MuxValidatedFrame,*,registration:UUID,cut:IngressCut)->ElementaryPacket`, validating exact sealed wrapper/original epoch/provenance before using its exact PrivateLiveFrame. Do not feed wrapper/subclass to legacy `packet` or erase its exact-type checks. Mapped time/slot ordinal come only from Task1 persistent SlotMediaClock; raw frame bytes/time are unchanged. Cut expiry is its one-shot admission/key-acceptance deadline: admit the first qualifying key before expiry, consume that exact cut into the registration and never reuse it for another viewer. After activation the immutable watermark persists; ongoing publication is governed by independently current/renewed ViewerGrant, not the expired admission timer. Test a rejected late first key and continuing authorized frames beyond the consumed cut's expiry.

Define sealed `MediaCredit(id:UUID,slot:MuxSlotIdentity|None,registration:UUID|None,frames:int,bytes:int,stage:Literal['callback','parent','source','decode','rgb','conversion'])` and `MediaCreditLedger.reserve_encoded(slot:MuxSlotIdentity,frames:int,bytes:int)->MediaCredit|None`; `transfer(credit:MediaCredit,stage:Literal['callback','parent','source','decode'])->MediaCredit`; `release(credit:MediaCredit)->None`; `reserve_rgb(registration:UUID,bytes:int)->MediaCredit|None`; `reserve_conversion(registration:UUID,bytes:int)->MediaCredit|None`. Credit is single sealed ownership, not reallocated at every queue; in-flight batches/conversion bytes remain charged. Worker receives an explicit `source_factory` mode, bounded to12 active shared viewers and no concurrent legacy profile. Existing dedicated main source uses the same budget ledger but exclusive native protocol.

- [ ] Write `test_held_complete_partial_and_old_rgb_cannot_seed_new_viewer`, `test_new_post_cut_key_and_sibling_progress`, `test_legacy_exact_private_frame_gate_unchanged`, `test_mapped_slot_clock_never_resets_on_park`, `test_shared_credit_counts_every_stage_once`, `test_dimension_rotation_waits_original_decoder`, `test_denial_or_registration_change_blocks_late_decoder_output`. Assert16frames/4MiB per slot,64MiB encoded, latestRGB1/16MiB, retained host1GiB, no decode before current post-cut key.
- [ ] Run new source/budget cases RED; existing source/timestamp/transition tests stay separate.
- [ ] Implement explicit shared source mode and sealed frame validation, persistent clock consumption, cold decoder startup and actual original retirement. Keep five-second pressure/rotation,16rotations/60s, first-key/decoded deadlines and non-terminal sender staleness contract. Mux shutdown waits viewer-local owners before coordinator last-epoch cleanup; no fabricated close on a task timeout.
- [ ] Run source/transition/worker/WebRTC focused regressions GREEN, including one same-peer synthetic decoded/RTP proof where code changed. Verify worker2GiB/native/decoder512MiB Job profile with Task4 inert probe and actual retained memory ledger; no guessed nested Job support.
- [ ] Freeze media implementation and a fresh media/concurrency review. Provider and media disagreements revise the declared port, not a parallel unsafe cast.

## Task 9: Wall/focus contracts, SQL tickets, RPC and API

**Files:** Create `packages/contracts/src/wso_contracts/tvt/local_media_mux.py`, `services/api/src/wso_api/tvt/local_media_mux.py`, `services/tvt-bridge/src/wso_tvt_bridge/local_media_mux_rpc.py`, `tests/tvt_parity/test_local_media_mux_rpc_api.py`. Modify `local_media.py` in contracts/API, `packages/contracts/proto/tvt_bridge.proto`, bridge `server.py`, API `main.py`; regenerate the existing protobuf/OpenAPI/TypeScript artifacts, never hand-edit generated output.

**Interfaces:** `LocalLiveRequest` adds optional public `wall_id:UUID|None` and `focus_ref_id:UUID|None`; all existing selectors/stream defaults remain. No native ID, actor/session digest or source proof enters public JSON. Define `LocalWallView(id:UUID,tenant_id:UUID,expires_at:datetime,state:Literal['ACTIVE','STOPPING','CLOSED'])`, `LocalWallResponse(wall:LocalWallView,request_id:str)`; `LocalFocusRequest(direction:Literal['FORWARD','RETURN'])`, `LocalFocusView(id:UUID,wall_id:UUID,lease_id:UUID,connection_id:UUID,channel_id:UUID,direction:Literal['FORWARD','RETURN'],expires_at:datetime,state:Literal['PENDING','ACTIVE','CLOSED'])`, `LocalFocusResponse(reference:LocalFocusView,request_id:str)`. `LocalFocusSettleRequest(outcome:Literal['CANCELLED','FAILED'])`; successful attachment settlement is server-only. Public identifiers are opaque application IDs; constructors alone never grant authority. Keep `LocalLiveResponse={lease,request_id}` and public MediaLease unchanged; cleanup scopes remain internal SQL/RPC custodian evidence.

New HTTP routes, all cookie/session/tenant OWNER/CSRF/origin/current-scope checked:

| Method / route under `/api/v1/tvt` | Operation |
| --- | --- |
| POST `/live-walls?tenant_id=...` (strict empty body) | Issue wall30s clipped to session validity; qualify only one active wall/actor/session |
| POST `/live-walls/{wall_id}/heartbeat?tenant_id=...` | Renew wall and each retained slot independently; denied slot fences its master |
| GET `/live-walls/{wall_id}?tenant_id=...` | Bounded scope-correlated public state |
| POST `/live-walls/{wall_id}/stop?tenant_id=...` | Fence group references, stop viewers and wait original master cleanup; remain STOPPING if uncertain |
| POST `/live-sessions/{lease_id}/focus-reservations?tenant_id=...` | Admit fixed20s forward/return reference before old viewer Stop |
| POST `/live-walls/{wall_id}/focus-reservations/{reference_id}/settle?tenant_id=...` | Cancel/fail pending reference; no client-controlled ATTACHED/native completion |

In shared mode, start without current wall is422 INPUT_INVALID; do not silently start an independent legacy owner. In legacy mode, absent-wall requests use unchanged admission, and new wall routes are unavailable. Mode chosen at worker/bootstrap startup, not client payload. Scope of a supplied wall/ref must match derived session, selector and direction; RETURN refs cannot start main. Server deadline is clipped, never a browser-provided timestamp.

Add private `LocalMediaMuxBridgeV1` service, retaining `LocalMediaBridgeV1` and reserved RpcContext fields. Define proto `LocalMediaMuxRequest { RpcContext context = 1; }`, reserving other fields/authority names, and reuse actual existing `LocalMediaReply { bytes public_json = 1; string failure_code = 2; }`. Methods `StartShared/WallHeartbeat/StopWall/FocusReserve/FocusSettle(LocalMediaMuxRequest)->LocalMediaReply` redeem purpose-bound SQL tickets. Public selector/direction validation and ticket issue are app operations; worker derives all scope from that ticket. Define `LocalMuxTicketIssuer.issue_shared(session_digest:str,connection_id:UUID,request:LocalLiveRequest)->str`, `issue_wall_control(session_digest:str,wall_id:UUID,purpose:Literal['heartbeat','stop'])->str`, `issue_focus(session_digest:str,lease_id:UUID,request:LocalFocusRequest,deadline_at:datetime)->str`, `issue_focus_settle(session_digest:str,wall_id:UUID,reference_id:UUID,request:LocalFocusSettleRequest)->str`. Add SQL `wall_control_issue(p_session text,p_wall uuid,p_purpose text)->text`, `wall_control_redeem(p_ticket text,p_purpose text,p_worker uuid)->jsonb` and `focus_settle_issue(p_session text,p_wall uuid,p_focus uuid,p_outcome text)->text`, `focus_settle_redeem(p_ticket text,p_worker uuid)->jsonb` for those tickets, plus exact-purpose redemption before Task6 calls. The plan's issue/redeem additions belong to Task5 admission; Task9 consumes them. Existing live offer/playing/stop continue with exact worker-owned lease identity.

- [ ] Write `test_shared_selector_wall_ref_and_session_scope`, `test_no_body_authority_or_unknown_rpc_fields`, `test_focus_body_is_explicitly_validated`, `test_client_cannot_settle_attached_or_native_cleanup`, `test_shared_mode_rejects_legacy_bypass`, `test_last_wall_stop_remains_stopping_until_epoch_receipt`. Assert same-owner correlation, strict body<=4096/context<=1024/response<=262144, no master/task/native fields and unchanged legacy DTO/defaultstream.
- [ ] Run new RPC/API tests RED plus generated-contract tests baseline; no whole foundation rerun.
- [ ] Implement routes/ticket issuer and purpose-bound RPC adapter. Existing LocalMediaRoute rejects nonempty bodies except start/offer/playing: add explicit focus validation or a separate route, not an unvalidated mount. SessionPool keeps original active callbacks/calls and disposal barriers; timed-out RPC cannot dispose a master still owned by the coordinator.
- [ ] Run `.venv/Scripts/python.exe scripts/generate_tvt_bridge_stubs.py`, `scripts/generate_tvt_types.py`, `scripts/export_contracts.py`; installed pinned tools only. Run new/affected API/RPC/generated schema cases GREEN. Compare fresh temporary generated output with committed artifacts where generators support `--out-dir`; no invented `--check` option.
- [ ] Freeze API contracts and fresh auth/RPC review. Generate public schema before Task10 begins strict Zod/BFF validation.

## Task 10: Same-origin wall/focus BFF and client

**Files:** Create `apps/web/src/lib/tvt/local-live-wall-api.ts`, `apps/web/src/lib/tvt/local-live-wall-proxy.ts`, `apps/web/src/app/api/live-walls/[[...segments]]/route.ts`, `apps/web/tests/local-live-wall-api.test.ts`, `apps/web/tests/local-live-wall-proxy.test.ts`. Modify `local-live-api.ts`, `local-live-proxy.ts`, existing live API route, `local-live-player.ts` and their tests for explicit focus paths/binding. Preserve existing standalone panel default in legacy mode.

**Interfaces:** `LocalLiveBinding` adds `wallId?:string,focusRefId?:string`; strict start Zod mirrors Task9 optional fields. `createLocalWall(tenantId:string,csrf:string,signal:AbortSignal):Promise<LocalWallResponse>`; `heartbeatLocalWall(tenantId:string,wallId:string,csrf:string,signal:AbortSignal):Promise<LocalWallResponse>`; `stopLocalWall(tenantId:string,wallId:string,csrf:string):Promise<LocalWallResponse>`; `reserveLocalFocus(binding:LocalLiveBinding,leaseId:string,direction:'FORWARD'|'RETURN',csrf:string,signal:AbortSignal):Promise<LocalFocusResponse>`; `settleLocalFocus(tenantId:string,wallId:string,referenceId:string,outcome:'CANCELLED'|'FAILED',csrf:string,signal:AbortSignal):Promise<LocalWallResponse>`. Add read-only `LocalLivePlayer.currentLeaseId:string|null` for the exact owned current view; it is not a native identity or authority proof. API proxy routing allowlists new paths before query/body parse; correlate tenant/wall/reference/lease/connection/channel/direction to submitted selectors/request_id and hide any upstream internal data.

- [ ] Write `test_wall_heartbeat_same_origin_and_response_scope`, `test_focus_wrong_direction_or_wall_denied`, `test_optional_fields_legacy_omitted`, `test_no_native_identity_json_or_redirect`, `test_abort_and_expired_reference_no_extension`, `test_readonly_lease_id_follows_exact_current_player`. Assert strict schemas, existing25s HTTP bound, CSRF/cookie no-store/Vary and bounded response bodies.
- [ ] Run Vitest on those files RED before client/proxy additions.
- [ ] Implement strict Task9 field/routes with same existing auth/bounded fetch helpers; do not spread unknown backend JSON or infer viewer cleanup from a transport receipt. Preserve LocalLivePlayer Stop's original promise and stale accepted-lease cleanup.
- [ ] Run affected live API/proxy/player and new wall suites GREEN, scoped ESLint/Next typegen/tsc. Installed tools: `pnpm --filter @wso/web exec vitest run <files>`; if pnpm is unavailable, use existing `apps/web/node_modules/vitest/vitest.mjs` and ESLint/Next CLI with explicit `apps/web` cwd, not reinstall tools.
- [ ] Freeze strict client/BFF and independent review before UI lifecycle wiring.

## Task 11: Monitoring group heartbeat, focus transfer and honest Stop

**Files:** Modify `apps/web/src/features/monitoring/live-wall.tsx`, `live-tile.tsx`, `apps/web/src/lib/tvt/live-wall-scheduler.ts`; create `apps/web/src/lib/tvt/live-wall-group.ts` and `apps/web/tests/live-wall-group.test.ts`; extend existing wall/scheduler tests. Preserve React/Tailwind design/layout and no autoplay until user's Play.

**Interfaces:** `LiveWallGroupController({tenantId,csrf,timer,api})`: `ensure(signal:AbortSignal)->Promise<string>` lazy group ID; `heartbeat()->Promise<void>` at10s while current wall/ref exists; `beginFocus(binding:LocalLiveBinding,player:LocalLivePlayer,direction:'FORWARD'|'RETURN',signal:AbortSignal)->Promise<LocalFocusResponse>` before its Stop; `cancelFocus(referenceId:string,outcome:'CANCELLED'|'FAILED')->Promise<void>`; `stopAll()->Promise<void>`; `dispose()->Promise<void>`. Add server-provided `LiveWallProps.sharedMode:boolean` defaultfalse, determined from reviewed owned bootstrap mode, never client actor/URL input. Configure createWallRuntime with this controller only in shared mode. Maintain one monotonically fenced local intent generation; old async group/ref results may only retire their own original, never adopt a new current player.

Focus flow: reserve FORWARD while sub current -> original player Stop -> start main with focus_ref_id -> server attachment transfers MAIN_ACTIVE. Return: reserve RETURN while main current -> main Stop plus server original reap -> start sub with focus_ref_id/fresh cut. Local intent cancellation settles pending ref; the server enforces20s/nonrenewal/last-ref retirement even if browser vanishes. All Stop stops queued/player requests, calls group Stop and awaits its original group promise. Individual tile says stopped video; no claim that shared upstream disconnected. Keep BUSY per-target3/6/12/15s, terminal NO_SIGNAL and old phase clocks; never extend focus ref because UI Stop may last26s.

- [ ] Write `test_last_tile_focus_and_return_reserve_before_stop`, `test_return_cannot_leave_main_active`, `test_ten_rapid_requests_report_attempted_and_settled_counts`, `test_expired_focus_does_not_open_new_current_player`, `test_wall_heartbeat_failure_and_tab_dispose_fence_all`, `test_stopped_tile_does_not_publish_upstream_disconnect`. Assert lazy group,10s heartbeat, exact20s deadline/failure, original Stop before new start, one current view and stale result retirement.
- [ ] Run group/wall/scheduler cases RED; report actual collected/passed counts rather than hardcoding a historical count.
- [ ] Implement group and reference composition; a missing lease ID cannot reserve or revive stopped/failed/no-signal tiles. Original stop/group-stop owners remain retained if cleanup is pending. A failed sole-viewer handoff may retire its base; report bounded failure rather than quietly reconnect a still-owned epoch.
- [ ] Run focused UI suites GREEN, then one full web test run plus lint/typecheck/build after composition. No repeated unchanged full test loops. Fresh UI/concurrency reviewer checks shared-mode lifecycle and body-schema alignment.
- [ ] Save attempted/acknowledged/presented/cancelled/settled test counters in task report; no real twelve-camera claim from component tests.

## Task 12: Controller source gates, owned probes and12-camera acceptance

**Files:** Modify `scripts/test-local-devices/runtime.py`, `server.mjs`, `observation.py`, `tests/contract/test_local_device_browser_fixture.py`, `tests/contract/test_local_media_observation.py`; add owned native probe `scripts/test-local-devices/mux-probe.py`, `tests/contract/test_local_mux_probe.py` and owned-worker memory tests. Actual media worker subprocess supervision is `runtime.py` (`worker_process` plus retained child launcher), not a nonexistent production worker_process.py; add its original worker Job/process2GiB cap before enabling shared native input, preserving original Popen/Job release and default legacy supervisor behavior. Create/update `docs/integrations/tvt-local-live-mux-acceptance.md`, canonical service/liveness/parity/handoff/AGENTS reports. Root owns source/native review receipts and private launch/approval wrappers; no implementer edits accepted historical envelopes.

**Interfaces:** Shared mode default off, enabled only by explicit owned fixture input and new immutable source approval. `MuxProbePlan(channels:tuple[int,...],max_seconds:int)` uses source-reviewed grant/custody/provenance ports and private configured devices; emits ordinal/count/codec/dimension/timing/closed enums only. Observer schema3 adds bounded master/slot/viewer/focus ordinals, first/last ingress cut decisions, custody/cleanup scope and memory/credit maxima. Preserve R1431MiB final snapshot, independent4096 terminal, stop/writer/hash gate and legacy schema2 compatibility. Native IDs/credentials/SDP/raw media never emitted.

- [ ] Run final combined source review on codec/native/SQL/media/API/UI composition; fix one wave and scoped re-review until C0/I0. Preserve approved parked-resource and freshness qualifications. Controller validates all declared types/signatures and actual rollback of mode switches.
- [ ] Run new guarded0016 SQL selection once after fixes, zero skips and all required named tests collected; owned child/DB/source preservation receipts required. Refresh new mux core/native/runtime receipts under new immutable filenames, exact closure including imported new modules/tests/contracts/guide and generated bootstrap. verify_review exact counts/hashes/ACL before native use.
- [ ] Run approved inert memory/Job/provenance/custody probe before hardware. Read actual host headroom; keep shared mode disabled if512MiB children/2GiBworker/nested Job/global credit profile fails. No relaxed cap, unknown process kill or silent standby replacement.
- [ ] Freeze a new owned runtime approval, reviewed sources/report hashes and bounded protocol. First actual master opens two distinct sub tasks on one recorder; then four. Each probe max120s plus separately bounded original cleanup; record route/kind/channel/ACK/control proof, one original owner and no cross-cut replay. Stop original and verify grants/quota/Job/IPC/observer terminal before source edits.
- [ ] Only after2/4 proof gates pass, freeze full fixture approval and open trusted installed Chrome via GPT web control. Verify8/4 inventories first. Measure1/4/12 stable SQL/CPU/memory/startup/drop windows once per load; begin12common progress hold>=300s after all are presented. Record actual BUSY/refusal codes instead of assuming a universal device cap. Total live run bounded1200s; browser observation saved/retired before900s and distinct windows labelled if renewed.
- [ ] Complete one presented main→sub return with sibling frame progress; separately10rapid request pairs with attempted/accepted/presented/cancelled/settled counters and one current viewer. Test individual Stop/reattach post-cut key, last-reference/Stop All, valid resolution rotations, real no-media only on acknowledged no-frame case and source-level negative cases separately.
- [ ] Execute controlled authority/cancel/foreign/custody/pressure faults first inert/owned fixture; never mutate recorder settings or another client's sessions. Confirm current/known denial, slot/master scope, no replacement before reap and honest quarantine. Unknown wire behavior returns to design revision, not disabling a check.
- [ ] Save final frame/start/resource outcomes, all typed viewer/dedicated/epoch cleanup receipts and exact original launch completions. Every applicable SQL lease/slot/master must settle; original Chrome/coordinator0/reaped, API/worker/context/ownedDB/source preservation/private0 and COMPLETE final hash gate. Exceptional retirement is FAILED acceptance.
- [ ] Update portable reports and parity affected rows with actual counts/limits, preserve c10/c11/c12 history and MATCHED0 unless independent APK comparison runs. Mark12target only after twelve concurrent five-minute progress and normal cleanup, SQL<=25tx/s/live and no unexplained429/5xx. Report incomplete gates as incomplete, not release ready.

## Verification commands and exact failure handling

### Test assertions to pin in each task's RED step

These fragments follow the task's described synthetic/fake-clock arrangement;
the implementer writes that test arrangement using the declared ports and
existing test patterns before running RED. Variables below are test-local
observations, not undefined new production functions. This table fixes the
assertions without supplying an implementation body.

```python
# Task1: test_twelve_interleaved_slots_keep_original_identity
assert len({f.slot for f in received}) == 12
assert all(f.frame.identity.task == f.slot.task for f in received)
assert all(f.slot.stream == 2 for f in received)
# Task2: test_callback_before_cut_cannot_gain_post_cut_origin
assert held_chunk.span.first <= cut.after_ordinal
assert held_key_was_admitted is False
# Task3: test_stalled_slot_cannot_allocate_hidden_batch
assert charged_frames <= 16
assert charged_slot_bytes <= 4 * 1024 * 1024
assert charged_global_bytes <= 64 * 1024 * 1024
assert bounded_pressure_result == "EPOCH_FENCED"
# Task4: test_two_base_one_main_and_uncertain_owner_are_charged
assert reserved_base_count == 2 and reserved_main_count == 1
assert unresolved_original_still_charged is True
assert replacement_open_count == 0
# Task5: test_reserved_master_login_runs_after_transaction_release
assert checkouts_held_during_native_login == 0
assert transaction_held_during_native_login is False
# Task6: test_return_consumes_main_active_atomically
assert main_active_after_return_reserve == 0
assert return_pending_count == 1
assert pending_expiry_seconds <= 20
assert renewed_pending_expiry == original_pending_expiry
# Task7: test_park_discard_and_retention_heartbeat_no_blanket_allow
assert original_login_count == 1
assert parked_decoded_frame_count == 0
assert foreign_slot_publication_count == 0
# Task8: test_mapped_slot_clock_never_resets_on_park
assert mapped_after_reattach >= mapped_before_park + 24
assert old_registration_decoder_result_was_published is False
assert admitted_first_key.ingress.first > cut.after_ordinal
```

```typescript
// Task9/API tests use equivalent Python assertions on strict DTO/ticket scope.
// Task10: test_optional_fields_legacy_omitted
expect(legacyStartBody).not.toHaveProperty('wall_id');
expect(sharedStartBody.wall_id).toBe(currentWallId);
expect(focusResponse.reference.lease_id).toBe(originalLeaseId);
// Task11: test_last_tile_focus_and_return_reserve_before_stop
expect(events.indexOf('reserve-forward')).toBeLessThan(events.indexOf('stop-sub'));
expect(events.indexOf('reserve-return')).toBeLessThan(events.indexOf('stop-main'));
expect(returningSubStartedBeforeMainOriginalReap).toBe(false);
expect(activeViewersForChannel).toBe(1);
```

```python
# Task9: strict scope and client-settlement negatives
assert wrong_wall_rpc_invocations == 0
assert client_attached_settlement_response.status_code == 422
assert client_native_cleanup_response.status_code == 422
assert uncertain_last_viewer_response.lease.state == "STOPPING"
```

Task9 strict negative assertions: unknown authority fields raise validation;
wrong-wall/session/direction tickets never invoke coordinator; client ATTACHED
or native cleanup settlement is422; expired/uncertain last-stop is STOPPING,
never CLOSED. Task12 actual evidence assertions are the listed twelve-camera common five-minute,
typed cleanup, source/private and observer gates; cannot be substituted with
constants or mock reports.

Run commands from the active worktree; use `& ./.venv/Scripts/python.exe` on Windows. Each task runs its named tests, then only concrete affected regressions. Scoped Ruff check/format and strict mypy target changed production paths; existing whole-repository type/test failures are separate historical debt, never relabelled a green release.

Owned SQL wrapper (new ignored Root file `run-local-media-mux-sql.py`) follows the existing isolated run-local-media-admission-sql-s1 pattern, supplies private existing PostgreSQL57056 credentials in memory/environment, pins0016/tests, requires zero skips and cleanup. PostgreSQL source data is never the test target. Native source approval closure includes Task1/2/3/4/7 plus imported Task5/6 contracts; source-only reviews are different from actual SDK/recorder proof.

No stage2 test or command above has been executed while writing this plan. Current fact mapping is read-only; completed stage1 tests/acceptance retain their own dated sources and actual limits. Implementation plan approval is distinct from approved design and from future native source/runtime receipts.

## Spec coverage and self-review record

| Approved spec section | Plan owner / verification |
| --- | --- |
|1–3 intent/original identity/model |Tasks1/4/6/7/12; one original epoch and no cross-actor pooling |
|4 parked rights/resources |Tasks5/6/7/11;30s slot rights, charged/discarded parked media, last-owner native retirement |
|5 wire/ingress/time |Tasks1–3/7/8; immutable channel task, first-byte cut provenance, fresh key, persistent R142 clock |
|6 sole forward/return |Tasks5/6/9–11;20s typed refs, MAIN_ACTIVE consumed, one viewer and exact main reap |
|7 authority/startup |Tasks5–8/9; short SQL checkout, purpose-specific grants and qualified slow-success/permit tests |
|8 credits/memory |Tasks3/4/7/8/12; single ledger, no hidden FIFO, original Job caps and measured host/probe qualification |
|9 typed cleanup/schema |Tasks4–7/9/12;0016/legacy scope, viewer vs epoch sealed receipts, pending/quarantine remain charged |
|10 public/module sequence |Tasks6–11; ticket-derived scope, strict RPC/Zod/BFF/response correlation |
|11 stage gates |Task1 source→Tasks2–11 inert/SQL/source reviews→Task12 owned2/4→12 |
|12 acceptance |Task12 matrix/normal original cleanup; one presented functional handoff separate from10rapid requests |
|13 evidence/approval |Named guides/reports, frozen spec036908e3 and separate current plan review |

Root self-review completed2026-10-06 against spec036908e3, current source and
the two read-only fact maps. Corrections included exact NativeFrameAdapter and
LocalMediaReply names, a separate transport login proof, callback-through-IPC
first-byte provenance, one-shot cut expiry versus ongoing viewer authority,
short SQL startup, typed no-original-created retirement, strict public wall/focus
correlation and the real owned runtime worker supervisor. Shared file owners
make Tasks1–6 sequential; disjoint provider/media/API then run in parallel.

Named future wire/Job/pressure questions remain explicit Task12 proof gates;
they are not filled with guessed native behavior or claimed implementation.

- [x] Compare exact types/method names across each Interfaces block; every referenced production type/function has a defining task.
- [x] Resolve callback/provenance and legacy exact-PrivateLiveFrame integration without unsafe casts or weakened checks.
- [x] Resolve typed cleanup/SQL transaction separation/current actor scopes against the read-only fact maps.
- [x] Ensure each Review Focus item has the listed task test assertions and finite budgets.
- [x] Check every proposed source/test/generator path and current command; distinguish future files from existing.
- [x] Check spec coverage table, plan length and no function bodies masquerading as an implementation transcript.
- [x] Save dated planning/status/proof limits in canonical service/handoff/AGENTS and local ledger; no secret/private values or premature12/service-complete claim.

## Execution handoff

The user's main/subagent method is preserved. After this complete plan and Root self-review are saved, present the plan for the required review; do not ask the method again. Implementation begins only after that plan review. Tasks with disjoint file ownership can run in parallel after interface dependencies; each gets a fresh reviewer and Root records exact reviewed source snapshots. Actual SDK/SQL/Chrome probes remain behind their explicit source/receipt gates. R104/Git publication rules remain unchanged.
