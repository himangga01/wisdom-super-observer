# Shared-recorder whole-branch composition review — R0

Date: **2026-10-06, Asia/Seoul**. Reviewer: `final_combined_source_review`.

**SPEC: not yet compliant. QUALITY: changes required. Critical 0 / Important 4 / Minor 0.**

The frozen composition has four remaining source defects. Correct and independently
review them before issuing the new source/native/runtime/bootstrap execution
authority. The prior task approvals and SQL evidence remain valid for their
recorded scopes; they do not establish these omitted integration schedules.
This is a completed whole-branch composition review, not actual Windows,
recorder, decoder, or Chrome acceptance.

## Authority, purpose, and source correspondence

Read the assigned final brief first, then the shared analysis policy, active
worktree AGENTS, canonical service continuation, approved specification and plan,
execution ledger, affected final task/recovery/runtime/UI reviews, and current
source at the connecting boundaries. Applied the code-review criteria from
`superpowers:requesting-code-review`; the starting-conversation skill explicitly
exempts dispatched subagents. No subagent was dispatched.

The intended service is one authenticated OWNER wall over two owned recorders,
with eight plus four immutable substream tasks, one separately owned main focus,
viewer-local decoding/WebRTC, honest parked-task semantics, and exact original
retirement. SQL separately owns transport, slot-retention and viewer authority;
the coordinator composes admission and original custody; provider/IPC preserve
ingress cuts and credit; the media worker owns local decoder/peer settlement.

Root supplied whole-branch BASE `211d1484aa16eb30f5d362758f149f98dec9dfdf`
through temporary snapshot `b03ae924b1817be7f7dfceb61a64e96858659c13`, **159 paths**,
**3,720,436 bytes** of diff payload. This includes the three prior local commits
and retained uncommitted Stage 1/2 source, tests, manifests, and reports.
Actual checkout HEAD remains Root-reported `6436748` on
`codex/superlive-web-service`; no Git command was run to mutate or independently
rederive that state. Review is of this supplied complete snapshot, not merely a
tracked working diff against the checkout HEAD.

Direct raw SHA-256 checks of all 159 manifest paths were performed twice.
**156 matched**, including every source, test, manifest, generated contract,
specification, and plan. The only differences were Root's expected later updates
to `AGENTS.md`, `docs/service-analysis.md`, and
`docs/analysis/2026-10-04-reboot-handoff.md`. Current canonical continuation was
used for the later execution status; those document updates are not treated as
changes to the frozen product candidate.

| Authority | SHA-256 |
| --- | --- |
| `task-999-review-r0.diff` package | `1ac70c94f1bdd8209af948ea0d658d947884c8470a77772a5846cf2908d6e715` |
| `task-999-frozen-hashes-r0.json` | `624b59d39d8957baa7d9a35ec429051d8c5a34f8f751d49377fa44b262155fa0` |
| Approved specification | `036908e32cbb72024e340d8a3fc3e298838e69e1c19db14427a2fafbad5e53ee` |
| Approved plan | `122796f66f2b41061e6488b6e2d92ebe754d34e2e02c129ef13de5abc559c3f9` |
| Coordinator/executor `local_media_mux_service.py` | `5bbcbba092b1c32cba7cb4d45a6e719501526ec9d3c9262996fa6b5b7bcd9577` |
| Admission `local_media_mux_admission.py` | `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797` |
| Native mux provider | `e0bbe47c78480acfc6691897c546ed22b84bd8a67b5921bb22b9d573f786a156` |
| Mux IPC | `5d9209d36d4db81773fbacfa475df36318b93469cca246f277aad459060321b8` |
| Media worker | `28ebdb89568db9be3c28952b8ec89752df2ee7fea267c497015233b48544e262` |
| Retained native media source | `7725c77ac12c59bbdd6055d26e0c6ccfeb28e577bb2ab0af3e38748a3ffd8243` |
| Web wall group controller | `6bff8ed41244c957567f7db2e1a2ecb79085e855331222eec4b4365a2c89342a` |

Paths below are relative to the active worktree. The full manifest remains the
exact correspondence authority for paths not repeated in this table.

## Important findings

### I1 — A started shared viewer can permanently lose its local retirement supplier

**Locations:** `services/tvt-media/src/wso_tvt_media/worker.py:178`, `:185`,
`:204`, `:214`, `:251`; `packages/core/src/wso_core/tvt/local_media_mux_service.py:1055`,
`:2313`; `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py:1056`.

`executor.start` completes native cut/viewer startup before the worker schedules
`_prepare`. The local cleanup owner and retirement callback are created only
inside `_prepare`, after its initial stopping/capacity rejection. If shutdown
wins between those two calls, `_prepare` exits at line 210 without registering
any local owner. `start` then calls `executor.close`, but the exact started
`MuxSlotViewer` refuses to issue a receipt when its retirement supplier is absent.
Neither the worker watcher nor shutdown can repair this: the lease was never
entered in `_sources` or `_runtime_closed`. Repeated coordinator cleanup therefore
remains STOPPING even though no decoder or peer was ever created. Cancellation
before the queued coroutine reaches callback registration presents the same
unowned handoff boundary.

This is a liveness/custody composition defect, not a request to relax the
provider's correct absent-supplier rejection. It can strand viewer uniqueness,
capacity and normal runtime retirement after an ordinary start/Stop All race.

**Independent narrow evidence:** the real `LocalMediaWorker.start` and `_prepare`
were exercised with an inert executor return that sets the stop flag at exactly
this boundary, plus a genuine `MuxSlotViewer` started through the synthetic
original IPC rig. Output was:

```text
viewer_started=True; retirement_hook_missing=True; worker_local_owner_count=0
initial_close_confirmed=False; repeated_close_confirmed=False
```

The scheduling adapter ran the actual coroutine with `asyncio.run`; it was not a
real media-worker/service startup. The genuine parent rig started one ordinary
Python watchdog thread, then `parent.close()` returned True and joined it in
synthetic teardown. No native process, Job, decoder, SQL or device was involved.

**Minimum correction:** retain an exact local startup/retirement owner and bind
its supplier across the executor-to-worker handoff before cancellation or a
preparation rejection can lose it. If a cleanup-only attachment port is needed,
bind it to the original retained lease/registration/source and permit no reading
or publication through that port. Keep unknown or still-running preparation
charged; do not infer an empty pipeline from cancellation or issue a fabricated
boolean receipt. This needs the media owner and the exact Core/provider handoff
contract, including any observer facade that captures that contract.

**Required regression:** genuine started provider viewer plus actual worker
startup, with shutdown/cancellation before `_prepare`, before callback attachment,
and after attachment. The known empty path must eventually close through the
same receipt issuer; a held original preparation/read must remain unconfirmed
until settlement. Preserve last-master/native and local-viewer distinctions.

### I2 — Retained media-source thread startup still certifies uncertain originals as settled

**Locations:** `services/tvt-media/src/wso_tvt_media/native_source.py:498`,
`:510`, `:685`, `:1103`; downstream worker receipt at `worker.py:471`.

The retained Stage 1 source marks a stage done whenever `thread.ident is None`
after a failed `Thread.start`, and repeats that inference in `close`. It then
joins only threads whose identity is already visible. An interrupted start may
have acquired an original thread that has not yet entered its target or exposed
its identity. In that state all done flags can be set, `_ended` becomes True,
and `source.close()` returns without joining the attempted original. The worker
can consequently confirm local cleanup before that original target settles.
The corrected R187 media-worker constructor does not cover these three source
threads; this old path is used by both shared and retained legacy media.

**Independent narrow evidence:** actual `NativeDecodedSource.start/close` with
fake Threads that retain an unresolved attempted acquisition while reporting
`ident=None`. The first `start` raises; no fake target has entered. Observed:

```text
close_returned=True; source_ended=True; all_done=True
original_pending=True; attempted_threads=1; joined=0
```

Only after that observation was the retained fake target explicitly allowed to
run its stopped-path finalizer. There was no real thread or decoder in this
particular reproduction. The existing ordinary partial-start tests reject before
acquiring the failed thread and do not cover this uncertain-acquisition schedule.

**Minimum correction:** track never-attempted versus attempted start for each
original source thread, with positive target-entry/exit and original join proof.
Only genuinely never-attempted threads may settle without a target. An
interrupted attempt with no positive terminal proof stays pending, including
through repeated close and late target entry. Apply this at the shared underlying
source rather than granting a special provider cleanup exception.

**Required regression:** interrupt each of the ingress/decoder/authority start
positions after possible acquisition but before visible identity; verify no
source close, viewer receipt, source-capacity removal or worker completion until
the same original target settles and joins. Preserve successful startup and
proven pre-acquisition failure controls. Use fake thread controls for this gate.

### I3 — A normal channel attachment turns the next wall heartbeat into Stop All

**Locations:** `packages/core/src/wso_core/tvt/local_media_mux_service.py:1030`,
`:1108`, `:1772`, `:1782`; `apps/web/src/lib/tvt/live-wall-group.ts:55`, `:80`,
`:88`; public call/response boundary `services/api/src/wso_api/tvt/local_media_mux.py:323`.

The coordinator returns `LOCAL_DEVICE_BUSY`/429 if heartbeat overlaps an
otherwise healthy record's `attaching` or `opening` operation; a first-master
construction can also hit the no-active-record/pending branch. These are normal
short-lived construction states. The wall controller's ten-second heartbeat
classifies every rejected response as terminal failure and immediately invokes
Stop All. Thus a scheduled heartbeat landing during addition of another camera
can stop all already healthy siblings, even with valid wall/channel authority.
This is independent of the correct startup scheduler's BUSY retry handling.

**Independent narrow evidence:** actual coordinator heartbeat against its inert
established two-viewer fixture, with the documented attachment counter held:

```text
code=LOCAL_DEVICE_BUSY; status=429; sibling_current=True; native_retired=False
```

The actual current TypeScript controller was transpiled in memory and invoked
with a typed BUSY error and inert API/timer ports:

```text
events=["failed"]; stopWallCalls=1
```

The Python probe's final convenience assertion `coordinator.shutdown() is True`
failed because that fixture intentionally defaults its fake original's
`can_close=False`. This does not change the preceding heartbeat observations.
The command exited 1, and is **not** a passing test or cleanup receipt. That probe
created no external resource/thread; its synthetic objects ended with the probe
process. The Node controller probe exited 0 and used no HTTP, service or browser.

**Minimum correction:** make heartbeat/construction serialization a bounded
non-terminal wait or a specifically handled transient BUSY outcome. Prefer a
single consistent contract: original wall/channel expiry and caller deadline
must still win, success must mean actual per-purpose renewal, and real denial,
failure, Stop and uncertainty must still fence. Do not simply return success
while skipping refresh or extend authority on a client retry. Core serialization
may avoid changing the public API; any frontend handling must remain bounded by
the already accepted expiry.

**Required regression:** heartbeat overlapping initial master construction and
an additional channel's open/cut while a sibling remains current; on completion,
renew the actual retained scopes without any automatic Stop All or new original.
Keep expired, denied, cancelled and permanently blocked controls terminal.

### I4 — Immutable grant replacement can fence healthy native IO during heartbeat

**Locations:** `packages/core/src/wso_core/tvt/local_media_mux_service.py:1799`,
`:1803`, `:1807`, `:1815`; `packages/core/src/wso_core/tvt/local_media_mux_admission.py:2139`,
`:2164`; `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py:256`,
`:272`, `:637`; `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py:893`.

Admission correctly makes an old immutable grant unusable before returning its
fresh replacement. The coordinator publishes that replacement to the provider
only afterward. Its `record.refreshing`/version guard protects coordinator
`current` calls and sweep, but does not stop an already admitted provider/IPC read
from making a purpose check in this interval. Provider transport/slot/viewer
checks call the admission directly with their still-held old object. The IPC
interprets the resulting False as a permanent authority failure and requests
original retirement, even though the fresh grant is valid and SQL has reported
no revocation. A provider snapshot spanning the local replacement has the same
uncoordinated generation problem. Later publication cannot revive the fenced
parent, as required by its sticky-failure contract.

**Independent narrow evidence:** actual `SqlMuxAdmission.refresh_grant`, actual
`OriginalRecorderMaster._authorize/_transport_current`, and actual
`MuxParentAuthority._check` were composed over sealed synthetic transport state,
an inert SQL-observation seam and inert original resources. The purpose check was
scheduled exactly after refresh returned and before provider replacement:

```text
initial_transport_check=True; fresh_grant_current=True; old_grant_current=False
original_provider_still_old=True; parent_failed=True; original_stop_requested=True
watchdog_created=False
```

This establishes the local protocol race, not actual SQL/native timing. No parent
bind/worker/thread/SDK/SQL connection was started in this reproduction.

**Minimum correction:** add an explicit original-scoped refresh barrier covering
the native provider/IPC purpose-check callers as well as the coordinator. It
must begin before invalidating the old grant, settle or safely defer in-flight
checks, and publish the exact replacement before readers resume. Supplier/SQL
callbacks stay outside short state locks; waits retain their original deadlines
and cancellation. Old grants must continue to deny and genuine known denial must
remain sticky. Do not treat every False as retryable or temporarily authorize
superseded grants. This is a Core/admission/provider integration contract, not an
IPC failure-policy relaxation.

**Required regression:** real facade grant lifecycle and provider/IPC methods,
with controlled pauses before/after each transport, slot and viewer replacement
and a previously admitted read/check. Healthy refresh must neither fence nor
retire its original; old/copy/foreign grants and concurrent actual revocation
must never publish. Include timeout, cancellation and Stop during the barrier.

## Composition coverage and retained evidence

The review uses prior qualified gates for generated/per-task internals rather
than claiming another execution of every suite or line-by-line review of the
large generated diff. The following connecting behavior was checked directly
against frozen code and the prior reviews:

| Boundary | Result and qualification |
| --- | --- |
| Default-off/shared runtime and trusted monitoring context | Runtime schema-3 approval/profile validation, same-instance admission/coordinator/provider/budget/factory wiring, OWNER page context, and legacy/shared separation remain explicit. No actual profile approval has been issued. |
| Public BFF/API/private RPC | Strict bounded closed DTOs, same-origin/CSRF checks, OWNER tenant/session-derived ticket issuance, commit before worker dispatch, response scope checks, mTLS identity and ticket-only RPC remain connected. Existing generated-contract gates are reused; no generator rerun. |
| Fresh startup and delivery proof | Core `binding_proof`, R186 initial activation and worker consumer accept genuine initial identity/permission proof. Full delivery proof, validated post-cut picture, decoder output and browser presentation remain separate before PLAYING. I1 affects the cleanup handoff. |
| Scope/renewal/focus | Immutable tasks, per-slot retention, separate publication grants, 20-second pending references, RETURN consuming MAIN_ACTIVE and exact main/native cleanup barriers remain represented. I3 and I4 prevent approving the whole heartbeat composition. Prior UI queued/manual/cancellation/retained Stop review is retained. |
| Native/IPC/credit and media | Prior Task 3/4/7 and R183/R147/R148 reviews establish the inspected raw/scratch/encoded provenance and credit contracts; Task 8's actual encode-callable ownership and no-payload-copy correction remain unchanged. I2 adds the retained source-thread custody gap. Source credit bounds do not prove physical RSS or actual twelve-stream pressure capacity. |
| R176 recovery | Original pre-SQL attempt/journal, ABSENT plus separate local closure, authentic empty-provider NOT_CREATED/SQL/budget barriers and follower-local retirement remain separate. No general crash recovery or safe pruning of the permanent 65,536-entry journal is inferred. |
| Worker Job/bootstrap | Current helper uses captured raw HANDLE for assignment/membership/signaling, requires J before imports, preserves uncertain acquisition/writer ownership and checks descendant count zero before closure. R187 retained partial worker callback remains connected. Actual nested Jobs/headroom are unexecuted. |
| Observation/raw probe | Current interval binds original writer/master/slot/viewer/registration/cut; old COMPLETE cannot qualify a new probe. Final live-budget failure remains sticky, raw retirement is distinct from observer/runtime COMPLETE, and current wire projection uses validated private tuples. R143 terminal/digest limits and prior qualified observer review remain in force. |
| Retained Stage 1/older commits | Prior continuous-media, sizing, main/sub, clock/rotation, registry, scheduler and observer acceptance is historical and qualified. Nine streams from c12 remain nine-stream evidence. The old source-thread path was revisited because shared media still uses it; I2 is not covered by R187's separate constructor correction. |

No additional Critical, Important or Minor finding was established in this pass.
The four items above are the complete requested correction list for this review;
none is silently deferred as a load-bearing future task.

## Verification evidence and actual limits

Reviewer commands were direct `Get-Content`, `rg`, raw `Get-FileHash`, the narrow
Python/Node probes described above, and writing/checking this report. No product
source/test/manifest edit, Git command, SQL connection/private-credential read,
DLL/SDK invocation, Popen/Job/native launch, service/Chrome/device activity,
installation, or routine broad suite/static rerun occurred. The one genuine
ordinary Python watchdog in I1 was explicitly retired; all native custody in
the probes was synthetic. Tool-invoked Python/Node interpreters are not claimed
as actual service or process-custody acceptance.

Root's final SQL receipt `cd80d4f2380f41ceb00c71cd228d8f38` was relayed and its
`final-quota-fixture-report.md` was read: **90 passed, zero failures/errors/skips**,
original child exited 0/reaped, owned DB removed, source DB and source pins
unchanged, zero known private occurrences. Production SQL `64e28f20...` and
admission `0a4162c6...` remain frozen; final test `cf013bae...` matches the manifest.
The 90-case module includes pure facade cases; it does not mean 90 distinct DB
connections. The earlier `1013998992534c44b681fea86c27b417` remains **89 pass /
1 stale same-lease quota-fixture failure**. The test-only fresh-lease correction
and separate one-pass target `4a7eec6e...` do not retroactively change that failure.
These are Root-executed results, not reviewer SQL runs.

Other retained evidence remains attributed to its prior reviewed baselines:
whole web 550; runtime final 37 helper cases plus separately qualified prior 80
and final constructor 2; observer final 82 subset and earlier qualified 297/78;
Core 205 on older admission dependencies plus 21 on current R186; and the
per-task codec/native/media/generator/static results. They are not summed into
a new final-dependency whole-suite claim. Earlier real kernel32 identity reads
and Node helpers in historical runtime/observer tests retain those reports'
qualifications; they are not reclassified as entirely inert.

## Open gates, priorities, and handoff

1. Resolve I1–I4 in Root's single controlled final correction wave, with exact
   author ownership and a scoped independent re-review of the completed wave.
2. Rebuild/review the exact immutable source/native/runtime/bootstrap closure.
   Current Windows LIVE receipt is still the historical Stage 1 receipt. It must
   not authorize the corrected shared candidate.
3. Qualify the actual Windows 2 GiB worker and 512 MiB original-child Job profile,
   nested Jobs, retained-host credit behavior and host/OS headroom. The 9.5 GiB
   sum is a ceiling, not measured allocation. Root's reported 15.60 GiB physical /
   3.37 GiB free snapshot is not qualification.
4. Execute bounded current two-channel then four-channel native probes with
   verified original receipts, followed by twelve-tile common five-minute Chrome
   playback, focus/return, revocation/pressure and normal full retirement.
   RAW_GATE_RETIRED alone never supplies observer/runtime COMPLETE.

Declined-to-judge behaviors: actual recorder route/ACK behavior, decode/display
quality and sustained twelve-camera capacity; actual Windows Job/headroom and
RSS; general production bootstrap, multi-actor/tab fan-out, cloud/TURN/audio/PTZ,
and recovery after loss of original custody. The first two remain required
execution gates; the latter product features are expressly excluded by the
approved scope. None of these exclusions removes I1–I4. No new product decision
is needed to fix the four source defects.

Root remains the sole owner of AGENTS, the execution ledger and canonical
`docs/service-analysis.md` integration. Register this portable report there and
reuse it before the correction review; update the canonical record with the
qualified verdict and later actual outcomes. Preserve this R0 and all failed
receipts instead of replacing their verdicts.

Update log: 2026-10-06 — completed whole-branch composition pass; all frozen
source hashes matched; four Important integration/custody defects established
with narrow evidence; SPEC not yet compliant / QUALITY changes required /
C0 I4 M0. Actual execution authority remains pending.
