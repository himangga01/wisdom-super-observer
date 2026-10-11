# Wall heartbeat exception and conditional shutdown gap

Analysis date: **2026-10-09, Asia/Seoul**.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD `6436748`,
retained Stage1/2, R193 and reviewed R194 diagnostics. The controller reports
the current 340-path closure unchanged. Current runtime/original cleanup is
still unsettled. This new, unpinned report is the only project file changed by
this investigation; pinned source and original reports remain unchanged.

Read with [service report](../service-analysis.md),
[shared SUB diagnosis](2026-10-09-shared-sub-liveness-diagnosis.md),
[Core state diagnostic authority](2026-10-09-core-close-state-debug.md), and the
[approved Stage2 plan](../superpowers/plans/2026-10-06-multiview-stage2-shared-recorder-plan.md).
After original retirement, the controller should record this path in AGENTS
and reconcile these findings into the canonical reports. No fix is selected or
implemented by this proposal.

## Supplied actual evidence and causal boundary

One channel's SUB rendered 1280x720, advancing to 49.597 s/501 decoded frames.
Manual HIGH then returned focus 200, SUB Stop 200, MAIN start 200 in 5469 ms,
offer 200 in 62 ms and PLAYING 200 in 62 ms. Native startup accepted the matching
1281 ACK at 2765 ms and first key at 4265 ms. The decoded milestone was 5405 ms
and peer connection 5640 ms. This proves that selected MAIN startup passed in
this attempt; it is not continuous MAIN/return/twelve-camera acceptance.

The subsequent wall heartbeat returned 503 in 266 ms, followed by 404. MAIN's
first source failure was `authority_renew/denied` at 14250 ms. Core state records
the master fence with pre-call state ACTIVE/refreshing and exact caller
`DeviceEpochCoordinator.heartbeat:1858`. Later coordinator false records show
the master CLOSED. No `GRANT_CURRENT` false preceded the fence. These facts were
supplied by the controller; this agent did not read private run files.

**The observed initiating boundary is the heartbeat refresh catch. Its inner
exception remains unmeasured.** `local_media_mux_service.py:1815–1866` spans
original IO-barrier entry, grant refresh/replacement, native renewal and final
checks. Admission `refresh_grant` raises on failed local guard, SQL observation
or replacement; it does not call the three instrumented `current_*` methods on
every failure. Native replacement can also raise without a preceding SQL
current false. Therefore absence of `GRANT_CURRENT` false does not distinguish
SQL refresh failure, provider/native renewal, replacement validation or budget
failure. The later authority denial follows the already fenced master.

## Confirmed conditional admission shutdown defect

The current source permits this failure sequence:

1. `SqlMuxAdmission._refresh_current_grant` creates/registers a fresh transport
   record, assigns `_master_grants[master]`, and marks the old record closed
   (`local_media_mux_admission.py:2191`).
2. Core calls `prepared.replace_grant(old, fresh)` before assigning
   `record.transport = fresh` (`local_media_mux_service.py:1834`, `:1836`).
3. Provider replacement sets its own transport to the new grant, then calls
   native parent renewal and heartbeat (`local_live_mux_provider.py:742`,
   `:797`). Either can raise before Core assigns its new holder.
4. Heartbeat fences; Core retirement passes its still-old transport to
   `finish_epoch` (`local_media_mux_service.py:931`). That method closes the
   supplied record and related slot records, but not another newly registered
   transport record (`local_media_mux_admission.py:1425`).
5. `SqlMuxAdmission.dispose` rejects any record still open (`:1969`). The unused
   fresh transport record can therefore keep admission disposal false after
   the Core master reaches CLOSED.

**One narrow inert control confirmed this bookkeeping defect.** It used actual
`SqlMuxAdmission.refresh_grant`, `finish_epoch` and `dispose`, with synthetic
scope/receipt objects and mocked observation, SQL and original-issuer ports.
No engine, connection, native child, SDK or browser was constructed. Output:
one unclosed replacement record after finishing the old epoch; actual
`dispose()` returned false. A comparison finishing the fresh transport record
left all records closed. Command was an inline script through the existing
`.venv/Scripts/python.exe -B -`; exit 0. No source/test or bytecode files were
written. Mock receipt equality does not establish real native cleanup.

This is a confirmed **conditional source defect**, not proof that this runtime's
missing exception took that branch. It also does not authorize modifying live
admission records or calling `finish_epoch` with a guessed object. The minimal
safe state evidence would be counts of open records by grant kind and a boolean
comparing the original coordinator's transport with admission's current master
transport; no identifiers or values need to be exported.

## Additional source-supported candidate: parked ingress

The last SUB viewer's Stop parks its upstream slot while MAIN retains the base
epoch. `MuxRemoteAuthority.handle` drains callback ingress only for `pull`
(`local_live_mux_ipc.py:530`); park, renew and heartbeat do not drain it. The
child's serve loop only processes those incoming operations
(`windows_socket_worker.py:1412`). The regular parent pump callsites are slot
startup and active SUB frame read (`local_live_mux_provider.py:705`, `:1058`).
Callback ingress remains bounded to 1 MiB/256 chunks, failing when full
(`windows_socket_worker.py:505`, `:515`). Thus continuing parked media with no
active SUB reader can fill the callback queue before a later native renewal.

This identifies a source-supported pressure mechanism. The current actual
evidence does not show base callback occupancy/failure or its native exit, so
it is not an established actual cause. A future inert callback/remote-authority
control can characterize retained bytes across park/renew/heartbeat without a
native child. Preserve all current authority and queue bounds.

## Minimum runtime-only exception measurement

At the existing original `_fence` wrapper, when the fixed allowlisted caller is
the heartbeat catch, `sys.exception()` provides the currently handled original
exception **before** `_fence` runs. Project that exception's finite traceback,
cause/context chain into a new fixed heartbeat event. An outer heartbeat
wrapper observing rethrow after retirement is an alternative; the pre-fence
observation is closer to the failing decision.

Use fixed LocalDeviceFailure code/status or `unexpected`, bounded relative
time/counters, fixed module/function/line entries and explicit truncation. Add
only required exact source/function mappings: heartbeat/check-replacement;
refresh-grant/record/observe/SQL; provider refresh barrier/replace/heartbeat;
IPC renew/RPC/check. Unknown frames consume a finite inspection budget. Do not
emit frame locals, arguments, arbitrary class names, exception messages, source
paths, identities, SQL rows or private media. Convert directly to checked
canonical bytes; retain neither frames nor exception objects in the queue.

Reuse the existing bounded publisher, omission/failure accounting and failure
isolation. Preserve the same original `_fence` call once, all exceptions,
budgets and original provider/receipt callback identities. No extra authority,
SQL, refresh or cleanup call is justified for logging. Retirement, narrow
review and a fresh immutable closure precede changed diagnostics or source.

## Pending original cleanup and limits

The controller reports API settled but original worker/Job/writer still retained
and incomplete. A CLOSED/STOPPING base master alone does **not** make
`_dedicated_retained` false. `_original_current`/`_retained` compare retained
registry, scope/native and captured method identities; they do not require an
ACTIVE master (`local_media_mux_service.py:694`, `:709`, `:1661`). Dedicated
cleanup bypasses live `_current_dedicated` and uses original issuers/receipts
(`:1689`). No dedicated custody deadlock from master state alone was proven.

Existing normal worker withdrawal is the retained owner's `close_step`: one
original stdin close request followed by actual original process/Job/writer
settlement. `OwnedMediaWorkerOwner` has no public normal-force withdrawal port;
its original Job termination branch is for recorded failed ownership/launch,
not a normal-close timeout (`worker_job.py:451`). This investigation does not
authorize falsifying that failure flag, bypassing custody, editing active
sources, or terminating a process by a reacquired PID. The controller must keep
the original handle until an approved original-custody withdrawal path settles.

Verification: source/report/guide reads and one isolated inert admission
bookkeeping control only. No private input read, database/hardware/browser
operation, broad test run or production/runtime edit. Actual heartbeat inner
exception and the exact pending-disposal component remain open.
