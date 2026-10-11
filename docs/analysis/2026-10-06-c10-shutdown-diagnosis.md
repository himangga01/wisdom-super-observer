# c10 original-worker shutdown diagnosis

Analysis date:2026-10-06 Asia/Seoul. Active c10 run
`local-devices-39e833ce10b1449db3865e3cc87a5b49`, immutable approval
`ad14894ef8d63fde7ef63723da607a9fa9aef180418ad96984ff93126be53f15`.
The original runtime was still pending when this report was written. No pinned
application/source/report, runtime setting or control file was changed. This new
diagnosis is outside the pinned closure. Root retains the original supervisor
and owns canonical report/instruction updates after actual retirement.

## Measured blocking condition

The original worker is executing the fixture's **settle_media loop because
LocalMediaWorker.shutdown() keeps returning False**. It has not reached the
subsequent native-owner passive-wait loop or admission shutdown. This is measured
stack evidence; the exact retained asynchronous media object remains unknown.

Existing safe status files establish:

- shutdown.json and runtime-shutdown.json both exist, written17:35:38 UTC.
- api-settled.json: exit0, custody_retained=false, incomplete=false.
- worker-settled.json at17:36:18 UTC: exit=null, custody_retained=true,
  incomplete=true. Its forty-second wait allowance expired without releasing
  the exact original worker handle.
- Coordinator summary: Next exited0, runtime remains pending, state retained.
- bridge/worker-close.json and final resources.json remain absent.
- The observation writer continues updating with stop_requested=false and
  observation_failures0. Its close() has not yet run.

Root separately reported issued67/CLOSED66 with one STOPPING/unconfirmed at the
cleanup SQL observation. This agent performed no SQL query. Root also reported
original Chrome reaped0 and holds original coordinator execution session59988.
These do not establish worker/native/media cleanup or completion of the run.

## Original process verification and safe stack sample

Root explicitly authorized an isolated purpose-bound py-spy helper after plain
status inspection could not locate the disposer. PyPI0.4.2 Windows AMD64 wheel
was downloaded into ignored `.superpowers/tools/c10-py-spy-0.4.2`, verified against
upstream SHA256
`8b06a353c177677e4e1701b288d8c58e2f8d4208ee81a8048d9f72ba800918f8`, and its one
executable extracted. No app/global dependency, hook or installation changed.

The published worker and runtime birth FILETIMEs were compared with their actual
Windows process creation times; the worker's OS parent was verified as that
same original runtime. All checks passed immediately before and after sampling.
PID lookup was used only for this read-only observation, never as signaling or
cleanup authority. The sampler used `dump --json --nonblocking`, with no locals,
native frames, subprocess traversal or signal. Raw output stayed in memory;
only fixed function/module/line, ordinal and boolean fields were saved. Process
arguments, thread names/IDs, locals, credentials and media were not exported.

py-spy documents external Windows ReadProcessMemory sampling and the nonblocking
option that avoids pausing the target. Its dump locals option was not selected.
See the [official tool documentation](https://github.com/benfred/py-spy) and
[0.4.2 distribution metadata](https://pypi.org/project/py-spy/0.4.2/).

Sanitized evidence is
`.superpowers/sdd/2026-10-05-multiview-stage1-plan/c10-worker-stacks.json`.
The21 Python thread stacks include:

| Thread role inferred from functions | Measured top/chain |
| --- | --- |
| Worker main | runtime.py:611 settle_media → runtime.py:805 dispose → server.py:460 dispose_resources → session_pool.py:25 _dispose_if_idle → session_pool.py:38 close → server.py:535 close → runtime.py:847 worker_process |
| Media event loop | windows_events.py:774 _poll → windows_events.py:445 select → base_events.py:1961 _run_once → run_forever → worker.py:68 run |
| Media executor monitor | threading wait → local_media_service.py:162 monitor |
| Observation writer | threading wait → observation.py:511 watch |
| Seventeen pool workers | thread.py:90 _worker, idle |

No sampled Python thread was in source ingress/decoder/authority production,
decoder reap, native retirement, an active SQL call or RPC method. This does not
prove OS child-process/Job settlement and does not inspect suspended asyncio task
frames. The worker's matching original process remained alive with36 OS threads;
Python stack count alone is not a count of resource owners.

## Source interpretation and remaining uncertainty

The service's original resource chain is coordinator→runtime→worker→media/native
owners. Fixture settle_child sends `close\n` once, records pending custody after
its budget, then continues waiting on the same original Popen. It intentionally
does not terminate or rediscover a process. The worker reads one stdin line,
then AccountRpcServer.close stops new RPCs and SessionPool invokes disposal.
Runtime dispose first calls settle_media, then original native passive_wait,
then ordinary admission shutdown. The measured stack stops at the first step.

LocalMediaWorker.shutdown may return False while startup is inflight, while its
original asynchronous shutdown future is pending, when that future completes
False due to quarantined/retained media state, or while executor shutdown is
unconfirmed. The executor monitor still sleeping rather than stopped narrows
the sample toward the earlier media shutdown conditions. Idle RPC/pool workers
provide no evidence of an executing startup at the sample time.

A concrete permanent path exists in worker.py: `_quarantined` records an
original source/peer close failure; `_shutdown()` returns False and later calls
keep the same completed-False future. A pending async close/barrier is another
possible path. Default thread stacks do not reveal those safe aggregate object
states, so this report **does not claim quarantine is the actual cause**. It
does establish repeated False return from media shutdown rather than the earlier
speculation that native passive_wait or a synchronous SQL close is blocking.

## Existing-control remedy boundary

The already-issued shutdown request reached the worker disposer. Writing those
files again, sending another stdin line, or repeating API/Chrome close cannot
advance that disposer: worker code no longer reads commands, API is settled,
and server.stop(0) has closed RPC admission. No second cleanup command or
exceptional original-handle retirement path exists in the inspected immutable
fixture controls. No new safe action through those existing controls was found.

Root must retain the original supervisor handle and must not certify CLOSED,
cleanup_confirmed or resource retirement from this sample. Further recovery
requires a separately authorized original-custody observation/control plan;
PID-based signaling, source mutation in the active runtime, injected cleanup,
or fabricated SQL completion would not establish original settlement. A future
diagnostic should expose bounded aggregate shutdown stage and pending/failed
owner counts, without IDs, media, locals or authority changes. It cannot be
added to the currently pinned process by changing files.

Priority is actual original-worker/media retirement with honest pending/failed
evidence. Recorder capacity, timestamp handling and the frontend busy queue are
separate work and were not modified or tested in this investigation.

## Verification limits and update log

Read-only actions: source/control-flow inspection, fixed status projections,
log file size inspection (no raw logs), original process birth/parent metadata,
and one nonblocking no-locals stack sample using an isolated verified helper.
No SDK, RPC, SQL, browser, test suite, Git, signal/kill, injected code, memory dump,
raw stack file, receipt or dependency-manifest operation occurred. Original
shutdown remains pending; final terminal evidence belongs to its custodian.

2026-10-06 — Recorded exact worker-disposer stack, retained statuses, safe helper
provenance and control limitations while all active application sources remained
unchanged.
