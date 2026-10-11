# Dedicated MAIN startup authority diagnosis

Analysis date: **2026-10-09 (Asia/Seoul)**.
Scope: the `ba37feae` low-to-high transfer failure, from committed dedicated
preparation through the first native startup authority check. This is a diagnosis
and proposed correction contract; no production correction is implemented here.

## Finding

**The shared dedicated MAIN provider uses the post-activation authority cache
during pre-activation startup.** `prepare_dedicated` commits the lease in
`CLAIMED`. `PreparedDedicatedMain.start` then calls inherited
`LocalMediaAdmission.current`, which queries `media_observe`. That SQL function
selects only `NEGOTIATING`/`PLAYING`. A valid `CLAIMED` lease therefore yields
NULL, which permanently denies its hot authority entry. Native startup consumes
that false answer before its manifest/staging/process work, and the prepared
provider raises `LOCAL_DEVICE_DENIED` 404. Activation cannot precede this check:
the coordinator calls `activate` only after `prepared.start` returns its session
and proof.

This phase mismatch is established by current source and an executed inert
causal control. The actual untruncated runtime trace identifies the same prepared
provider failure boundary. The private runtime did not log the intermediate SQL
answer or lease state; the earliest native denial is established by source
ordering and the control, rather than by a captured private SQL trace. No repaired
device/browser acceptance follows from this diagnosis.

## Authority, source baseline and scope limits

Read before analysis: the shared analysis policy, this worktree's `AGENTS.md`,
the current English service report, the Oct 9 API logging author/review and Core
debug review reports, the existing mux provider/admission guides, and the relevant
admission, migration and provider fixtures. The systematic debugging workflow was
used. Controller ownership of canonical service/handoff/AGENTS updates is
preserved; this agent writes only this separate diagnosis report.

Implementation worktree:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch: `codex/superlive-web-service`. Actual HEAD:
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial status contained extensive
retained, reviewed Stage 1/2 tracked modifications and untracked implementation,
tests and reports. These were present before this analysis. The primary checkout
does not represent this implementation baseline. R192's source candidate
`225f9786` and current execution envelope `a998d930` are distinct authority
artifacts, not Git commit HEAD values.

Fresh SHA256 readings for the causal scope:

| Source | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_media_admission.py` | `60286cf0edf5b0582df73df52ec5a0e343ed6ddb374c4485da47494a27969284` |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797` |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py` | `cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py` | `b34626aa9f3cceabf805b9472570445cd617ce0623c321ffb4d1c9f4635efe39` |
| `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py` | `1ad25ee670dde8397872dc38f3909baca1bac53a8b304f118d6786161fe375fb` |
| `infra/migrations/versions/0013_tvt_local_media_leases.py` | `be9332c6e21d8c691a8a9aaf0b18ec94738304d6d75548bee5bc45da9b902256` |
| `infra/migrations/versions/0014_tvt_local_media_hot_authority.py` | `7e4944ca22dd5aed9cf6669d60af6f7ea380b7ce8988630da7644cda2865305d` |
| `infra/migrations/versions/0016_tvt_device_media_epochs.py` | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |

No application source, tests, dependency files, index, HEAD/ref, private input,
database, native original or browser was changed or launched by this analysis.
The inert probe ran in a separate Python interpreter, with synthetic SQL results,
ownership objects and credentials. It created no SQL connection, native process,
Job, pipe, staging generation or media capture. Python bytecode writing was disabled.

Related portable authorities:

- [Service report](../service-analysis.md), latest R192 actual reproduction and
  retirement update.
- [API logging report](2026-10-09-live-api-debug-logging.md) and
  [Core debug source review](2026-10-09-live-core-debug-review.md).
- [Mux provider guide](../integrations/tvt-local-live-mux-provider.md) and
  [mux admission guide](../integrations/tvt-local-media-mux-admission.md).

## Service purpose and relevant architecture

The local CCTV service presents authorized recorder channels in Chrome. Shared
SUB viewers retain a recorder master/slot, while high quality MAIN uses a
separately owned native original, registered cleanup issuers and a bounded
FORWARD focus transfer. Browser/API controls, Core coordination, SQL admission,
native provider and later media delivery have separate authority and retirement
boundaries.

The dedicated startup sequence already exists: select MAIN, reserve and retain
inert custody, register dedicated issuers, claim/decrypt outside the released SQL
checkout, start the native original, activate the returned proof, settle focus,
then publish/check live authority. Startup needs current actor/session/device/
channel/focus/wall/master authority before it has an activated delivery grant.
The hot authority cache intentionally serves only activated media leases.

## Actual evidence supplied by the controller

Development run `ba37feae` used frozen source. Recorder 1 low start, offer and
PLAYING returned 200. Chrome DOM media metadata showed `352x240`,
`currentTime=32.916270`, `paused=false`, `readyState=4` and 330 decoded frames.
Manual HIGH after actual PLAYING returned focus 200 and SUB stop 200, followed
by MAIN RPC 404 `LOCAL_DEVICE_DENIED`. These facts disprove the earlier missing
PLAYING hypothesis for this transfer. The same failure was historically observed
in run `1be34ba`, which had no presented-frame acceptance evidence.

The `ba37feae` Core JSONL record was untruncated and contained:

```text
MuxMediaExecutor.start:2214
  -> DeviceEpochCoordinator.attach_dedicated:1573
    -> PreparedDedicatedMain.start:1352
```

The controller subsequently confirmed normal retirement: original coordinator
exit 0/reaped, Next/runtime exit 0, API/worker settled, context removed, source
unchanged, owned DB cleanup/source-before-after contents equal and known private
occurrences 0. This agent did not independently operate Chrome, inspect private
run inputs or execute the retirement. Those actual outcomes remain controller
evidence in the canonical service/handoff authorities. The development run is
not formal five-minute, multichannel or twelve-camera acceptance.

## Source proof and working startup pattern

| Boundary | Current implementation and consequence |
| --- | --- |
| `local_media_mux_service.py:1554` / `:1561` | Registers dedicated issuers, then calls `admission.prepare_dedicated` before native startup. |
| `local_media_mux_admission.py:368` | `SqlMuxAdmission.prepare_dedicated` checks the exact known lease/custody and selection, calls legacy `media_use`, commits/releases its checkout, decrypts, and rechecks custody/selection. |
| `0013_tvt_local_media_leases.py:149` | `USE` accepts `LOGIN` and changes it to `CLAIMED`; it does not activate a media grant. |
| `local_media_mux_service.py:1573` / `:1584` | `prepared.start` precedes `admission.activate`. The latter is unreachable if startup denies. |
| `local_live_mux_provider.py:1315` | Nested startup `current()` checks budget/stopping and calls `provider.admission.current(self.lease)`. |
| `local_media_admission.py:475` / `:392` / `:442` | Inherited `current` runs `_authority`, which calls `_query(..., "observe")`. |
| `0014_tvt_local_media_hot_authority.py:53` | `OBSERVE` selects only `NEGOTIATING`/`PLAYING`, although underlying `LIVE_READ` admits valid `LOGIN`/`CLAIMED` too. The outer selector rejects `CLAIMED` before the underlying predicate can help. |
| `local_media_admission.py:452` | A NULL view calls `entry.deny()`. Subsequent calls return false without another SQL check, including after a hypothetical later activation. |
| `windows_socket.py:1461` | The first `service.check(current)` occurs before `verify_review`, ACL/bundle/staging generation and child creation. |
| `local_inventory_ipc.py:163` | `ParentAuthority.check` converts a false answer into sticky `failure="denied"`. Cancellation/deadline still have precedence. |
| `windows_socket.py:1689` / `local_live_mux_provider.py:1351` | Native run's catch returns a failure result without handoff. Prepared start raises `failure(authority.failure or result.failure)`, so the parent's `denied` maps to the observed 404. |

The working legacy startup path is `LocalMediaAdmission.open` at line 284,
with its transaction-local nested `current` at line 312. That callback calls
**`public.wso_tvt_local_media_current`**, using the same token/worker/native
binding and caller budget. `0013 CURRENT` uses locking `LIVE`, which accepts
valid `CLAIMED` startup leases. Native provider startup receives that callback;
the post-activation hot cache does not run during the legacy open callback.

That legacy SQL current function alone is not a sufficient proposed mux guard:
its body contains no mux wall, focus or registration predicates. The existing
`0016 VIEWER_SELECTION` at line 506 is the closer mux pattern. It already admits
registered MAIN in `CLAIMED` for the post-decryption recheck, and validates the
lease binding, locking LIVE, exact wall actor/session scope, pending FORWARD
focus, channel, worker, retained master and complete device/secret scope.
`SqlMuxAdmission._selection` at line 337 surrounds this short query with exact
known-lease checks. `_dedicated_owner` at line 1968 retains the exact lease,
registration and unchanged native/viewer issuer methods.

`VIEWER_SELECTION` requires a non-NULL SQL registration for the `CLAIMED` MAIN
case; it does not project that value for an equality comparison. Dedicated SQL
registration is one-shot in `DEDICATED_REGISTER` at line 662; the only other
registration setter is SUB `VIEWER_ADMIT`. A new startup port must preserve the
existing one-shot registration contract and match its retained registration;
it must not claim SQL registration equality from the selection response itself.
If direct equality against SQL is required by the correction's reviewed contract,
use a narrow worker-only helper/projection rather than weakening existing SQL.

## Executed inert causal verification

Executed command shape, from the implementation worktree:

```powershell
@'
# Python probe described below, supplied through stdin.
'@ | & .venv/Scripts/python.exe -B -
```

Exit **0**, elapsed **1.31 s**. The probe used actual `SqlMuxAdmission.current`,
`_authority`, `_query`, `PreparedDedicatedMain.start`, `WindowsSocketProvider.run`
and `LiveParentAuthority.check`. It substituted only the SQL engine/result,
inert custody/resource accounting and final cleanup. Native `verify_review`
had a sentinel which recorded any reach and stopped before native operations.
The source `OBSERVE`, `LIVE_READ` and legacy `CURRENT` constants were read through
AST literals and asserted to contain their current phase predicates. All other
SQL authority predicates were assumed satisfied by this single-variable model;
no real PostgreSQL predicates or lock behavior were executed.

Observed stdout:

```json
{"after_activation_same_gate": false, "claimed_hot_current": false, "fresh_negotiating_current": true, "legacy_startup_phase_control": true, "native_manifest_calls": 0, "prepared_start": {"code": "LOCAL_DEVICE_DENIED", "status": 404}, "resources_created": 0, "startup_observe_queries": 1, "sticky_observe_queries": 1}
```

The causal checks were:

1. A synthetic `CLAIMED` lease enters the real hot gate; the SQL phase model
   returns NULL and `current` returns false after exactly one observe query.
2. Changing that same model to `NEGOTIATING` still returns false, with the query
   count unchanged at one. This demonstrates the permanent early denial.
3. A fresh gate and `NEGOTIATING` lease return true. This isolates the startup
   phase difference from a generally broken live cache.
4. Actual prepared start and native-run methods with the `CLAIMED` model raise
   exactly `LOCAL_DEVICE_DENIED` 404. Native manifest sentinel count is zero;
   the inert acquisition marker is followed by the inert cleanup marker.
5. A fresh `LiveParentAuthority` with a true startup callback accepts it. This
   is a phase control, not proof of full legacy/mux SQL or native handoff.

Existing fixture evidence explains the coverage gap. The historical SQL test
`test_media_sql_observe_matches_current` in
`tests/integration/test_local_media_admission.py:795` explicitly expects
pre-activation current true and observe NULL. Mux SQL preparation tests at
`test_local_media_mux_admission.py:1420` verify the committed claim/decrypt
boundary but do not call the real prepared provider with that claimed SQL lease.
Its `focus_setup` at line 582 commonly uses legacy `gate.open` and then activates,
which follows the working startup callback instead. The provider coexistence
fixture at `test_local_live_mux_provider.py:1400` substitutes
`admission.current = lambda lease: True`. These separate tests can pass while
the composition has the demonstrated phase mismatch. They were inspected,
not rerun as live SQL tests by this diagnosis.

## Minimum proposed correction contract

Priority **P1**: repair the dedicated startup callback using a fresh,
phase-appropriate admission check on the exact retained dedicated lease and
registration. Keep the correction limited to the admission/provider startup
boundary and its causal/composition tests.

Proposed private port, with its final name/signature subject to implementation
review: `current_dedicated_startup(lease, registration, selection, *, budget)`.
It should revalidate `_known_lease`, the same `_dedicated_owner`, retained
registration/issuer identity, expected MAIN selection and current SQL
wall/focus/master/channel/actor/session/secret authority. Reusing existing short
`_selection` is the smallest available current pattern; a narrow SQL helper is
needed only if the accepted contract requires explicit SQL state/registration
equality beyond that projection. Check local custody and known denial before and
after SQL, preserve cancellation/deadline and stopping precedence, release the
checkout before native operations, and fail closed on NULL/error/substitution.
No valid startup check should seed the activated hot cache.

Use this startup check for the callback passed to `native.run`, its immediate
handoff postcheck, and the startup login-BUSY authority recheck. Keep later
coordinator `activate`, exact focus ATTACHED settlement and post-activation
`admission.current/view` cache behavior intact. Do not globally widen `OBSERVE`,
clear sticky denials, treat handoff as SQL activation, synthesize proof, admit
before native proof, replace native owners, hold a transaction across native
startup, or add a PLAYING/timer/retry workaround.

Required correction controls: the composed `CLAIMED` preparation-to-provider
startup case; native handoff then real activation before ordinary hot current;
copied/foreign lease or registration; replaced custody/selection; revoked
session/role/device/channel/secret, stopped/expired wall/master/focus;
cancellation/deadline before and after SQL and native handoff; confirmed original
retirement/credit refund; and preserved post-activation sticky denial/freshness.
Use guarded, owned PostgreSQL acceptance for SQL predicates after source/inert
controls. This diagnosis does not execute or approve that future implementation.

## Authority refresh and remaining acceptance

Changing `local_media_mux_admission.py` invalidates its current source receipt;
changing `local_live_mux_provider.py` invalidates the native `OWNED` file closure
used by `windows_socket.verify_review`. The runtime source envelope pins both,
their tests/guides and review/report authorities. Therefore a correction requires:

1. Preserve the retired `ba37feae` and prior failure receipts; implement and
   independently review the scoped new source/tests, including any SQL delta.
2. Update the affected portable admission/provider guide and this report after
   source verification. The controller records this canonical path in AGENTS
   and the read-before/update-after service/handoff workflow.
3. Preserve historical `tvt-local-live-mux-stage2-source-v1.json`. Create a fresh
   source-qualified admission/LIVE receipt and update the exact
   `windows_socket.py` `LIVE_RECEIPT` path/hash constants only after independent
   review, then refresh the native review receipt and dependent immutable
   runtime/source approval envelope for the new bytes.
   Refresh bootstrap/runtime references only where their source dependencies
   actually change. Historical R192/Stage 1/2 receipts cannot authorize a changed
   provider or admission body.
4. Execute a fresh bounded controller-owned Chrome SUB PLAYING -> HIGH MAIN
   start/offer/PLAYING -> return/stop and cleanup run. Record actual HTTP,
   presented-frame advance, current source stability and original retirement.
   Five-minute, twelve-camera and APK comparison remain separate open gates.

No new product decision is needed to establish this startup defect: existing
approved MAIN transfer is meant to run after confirmed SUB closure under a
current pending focus. Open implementation question: whether the startup port's
accepted contract can reuse the existing selection projection under its one-shot
registration invariant, or needs explicit SQL state/registration readback.
Source/inert evidence cannot establish recorder MAIN formats, concurrent native
coexistence performance, real SQL lock behavior or corrected Chrome playback.

Update log: 2026-10-09 — read-only source tracing and an inert causal probe
establish the dedicated startup/cache phase mismatch; proposed narrow guard and
required authority refresh recorded; no source fix or repaired acceptance claimed.
All ten causal source SHA256 values were re-read after the inert probe and report
creation and remained identical to the baseline table.
