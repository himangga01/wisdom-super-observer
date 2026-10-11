# Parked shared ingress and worker receipt causal diagnosis

Analysis date: 2026-10-10, Asia/Seoul. Source authority: implementation worktree
`codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted Stage1/2,
R193/R194 application/native changes. The initial tree was already extensively
modified. This investigation changes no application, native or runtime source.
Its only new files are this portable report and one isolated inert control.

Read before reuse with [service analysis](../service-analysis.md),
[heartbeat exception proposal](2026-10-09-wall-heartbeat-refresh-exception-proposal.md),
[shared SUB diagnosis](2026-10-09-shared-sub-liveness-diagnosis.md), and the
[Stage2 plan](../superpowers/plans/2026-10-06-multiview-stage2-shared-recorder-plan.md).
The parent controller should record this authority in AGENTS and reconcile the
service report after its concurrent investigation. Refresh this report after
targeted source changes or new actual acceptance.

## Purpose, architecture and measured boundary

The service streams privately registered TVT cameras to authenticated web
viewers. Shared SUB slots retain one original recorder transport, IPC owner and
callback. A dedicated MAIN uses a separate native session while retaining the
base shared epoch. Stopping the last SUB viewer parks its slot, removes the
parent admission cut and refunds queued publication credits. It does not close
the recorder's already opened SUB stream.

Historical R195 evidence locates the initiating master fence at
`DeviceEpochCoordinator.heartbeat:1858`, during grant refresh. The inner runtime
exception remains absent. Today's controls establish a conditional source
failure mechanism, not the actual cause of that historical run. No private run
inputs, database, hardware, browser, existing process or PID operation was used.

## Confirmed source behavior and controls

| Actual-source inert control | Result |
| --- | --- |
| Parked slot, inject 256 synthetic 137-byte callback chunks; renew and heartbeat every 32 chunks | Eight renewal/heartbeat pairs succeed and retain all bytes; chunk 257 fails with 35,072 bytes queued. The 256-chunk bound triggers before the byte bound. |
| One callback chunk exactly 1 MiB, then one extra byte | First chunk succeeds; extra byte latches failure. |
| Existing parent pump after each parked valid frame | 1,024 frames drain without overflow; slot credits return to zero after every frame. |
| Partial frame starts before new cut and finishes after cut | It cannot publish to the new viewer. A subsequent entirely fresh key publishes with ingress ordinal above the cut. |
| Parked slot retention becomes denied during pump | Pump fences the parent and requests original-owner stop. No blanket parked authority is introduced. |
| Actual NativeMuxWorker.serve receives heartbeat after callback overflow during poll | Original native heartbeat guard rejects before native send; dispatcher closes, zero native send calls. |
| Real Python writer thread writes only to fake child's BytesIO | Start returns, writer finishes and thread is no longer alive, but receipt reports writer_start_uncertain until the stored joined flag is updated. |

Source boundaries:

- `windows_socket_worker.py:345-428,486-543`: mux binding sets 1 MiB capacity;
  callback increments ingress ordinal before copying, retains at most 256 chunks,
  and latches terminal failure on capacity overflow. `take_mux_batch` drains RAM.
- `local_live_mux_ipc.py:504-554`: only `pull` calls `take_mux_batch`; `park` has
  no child-side drain, and renewal only changes the control deadline. Heartbeat
  sends the native keepalive without draining callback or remote pending batch.
- `windows_socket_worker.py:1372-1416`: heartbeat rejects failed/closed callback;
  the native service loop exits when callback fails. An inert direct dispatcher
  renewal after failure would not model this real service-loop lifetime.
- `local_live_mux_ipc.py:1144-1178,1281-1356,1426-1432`: pump parses original
  FIFO ingress, checks slot-retention authority, reserves bounded credits,
  refunds frames without a cut, and preserves pre-cut origin. Park refunds
  queued frames and removes the cut; it does not rewrite raw provenance.
- `local_live_mux_provider.py:703-705,1037-1068`: existing shared pumps are slot
  startup and active SUB reads under the exact master's serialized IO. MAIN
  reads its separate session and supplies no shared base pump.

Consequently, if the original recorder keeps delivering SUB callback chunks
while all SUB viewers are parked, continuing renewal/heartbeat alone cannot
prevent eventual overflow. At a synthetic 20 chunks per second, 256 chunks fill
in 12.8 seconds. This is a mathematical example, not a measured camera rate.
Increasing queue bounds or pumping only at a roughly 15-second wall heartbeat
does not remove the missing consumer.

## Smallest valid proposed production boundary

The validated primitive is the existing **parent pump**, including its existing
codec, cut filtering and credit accounting. A raw callback clear, byte dropping
in `park`, arbitrary parser reset, relabeling ingress ordinals, manufactured cut
or synthetic viewer admission is not a validated replacement.

Place a retained ingress consumer at **PreparedNativeMux/base-epoch lifetime**
in `local_live_mux_provider.py`, rather than retaining an ended viewer's media
threads. NativeSource's ingress/decoder/authority threads belong to one viewer
(`native_source.py:475-508`) and retire on its Stop; MAIN's corresponding threads
belong to a distinct native session. The parent watchdog (`local_live_mux_ipc.py:
721-738`) currently only fences expiry/cancel/pressure and owns no master grant
refresh barrier, so directly making that watchdog pump would require importing
new authority/IO coupling into the lower IPC layer.

Proposed narrow behavior, requiring implementation and review:

1. Keep one exact original pump-thread owner in PreparedNativeMux after original
   shared startup is ready. Retain the thread and attempt/completion state before
   start. Run bounded pump iterations while the epoch is retained and all shared
   viewer cuts are parked. Use a short idle wait, not the wall heartbeat interval.
2. Enter the master's existing `_invocation` and `_serialized_io`/authority
   operation, capture its exact owner/parent/grants after acquiring the barrier,
   and recheck readiness, stop and same-original identities. Call existing
   `parent.pump(original_owner, deadline_monotonic=bounded_original_budget)`.
   Refresh, viewer attach/admission cut, viewer read and park must use that same
   barrier; a cut becoming active atomically hands consumption back to readers.
3. Preserve FIFO raw ownership, one pending response, original ordinals, all
   transport/slot-retention checks, pressure deadlines and reserve/rollback.
   Parked pumping allocates bounded temporary validation credits and refunds
   them. A new viewer gets its original fresh cut and requires a fresh key.
4. Stop admission and signal the retained consumer during original close. Leave
   entered operations normally, join the exact original thread, require positive
   completion/join evidence, then issue the original native/custodian receipt.
   Interrupted thread start or join retains custody. A thread's absence inferred
   from ident/alive cannot certify cleanup. Do not add a force-withdraw path.

The existing executor monitor calls sweep once per second by default
(`local_media_mux_service.py:2151-2177`). A single pump per sweep can return only
one chunk from the child's retained batch, so it is not demonstrated to keep up
with ingress. Reusing that thread with a bounded drain loop is a possible design
alternative, but requires a reviewed provider maintenance port and demonstrated
throughput/time fairness. The inert controls prove the primitive's authority,
cut and credit semantics; they do not choose a production scheduling budget or
establish new thread/refresh/start/close race acceptance.

## Worker receipt meaning and smallest next instrumentation

`worker_job.py:549-550` defines `writer_start_uncertain` as any writer with
`start_attempted and not joined`. That field does not inspect `start_returned`,
`finished`, or actual liveness. `_write:329-336` records a returned start and may
join the real thread for 0.2 seconds, but does not mark `joined`. Only
`_writers_settled:371-386` records the final joined flag after finish/liveness
checks. `close_step:478-485` calls this settlement before sending close; after
`_stop_sent` becomes true and the child still runs, it returns without settling
the new close writer. Thus a later 40-second receipt can retain the flag for a
normally completed close writer.

The inert completed-writer receipt changes from uncertain=true/settled=false to
uncertain=false/settled=true solely after the existing settlement poll. The fake
worker still runs and remains incomplete at that point. This proves neither
that the historical writer was healthy nor that historical cleanup succeeded.
It refutes interpreting the field alone as an interrupted Thread.start cause.

Next diagnostic priorities:

1. Capture the existing heartbeat catch exception with the bounded allowlisted
   synchronous traceback proposal. This establishes whether SQL refresh,
   replacement or native renewal/heartbeat initiated the actual fence.
2. Capture typed base callback metadata on original native service control/exit:
   used bytes/chunk count/high-water values, primitive terminal reason, ordinal,
   active/parked slot counts, last pull age and reply/exit outcome. Snapshot
   outside native callback execution; export no bytes, identities, locals,
   arbitrary exception text or new authority decisions. Preserve bounded private
   publisher omissions and original child/publisher custody.
3. At worker receipt publication, project per-writer counts of attempted,
   start-returned, finished and joined plus close-sent state. Give the existing
   flag its exact unsettled-writer meaning. No diagnosis should infer uncertain
   thread startup from the flag alone. If a future change polls settled close
   writers while the child remains alive, review its original custody and
   exception behavior independently; do not mark joined based only on flags.

Open acceptance questions: does the actual recorder continue SUB deliveries
after park; which FIFO bound or terminal condition initiates the real failure;
what drain throughput survives twelve-camera rates and decoder pressure; can
attach/refresh/stop race with the proposed consumer while preserving original
receipt settlement? Those require new reviewed source and bounded actual runs.

## Verification and exact baseline

Executed command, exit 0, six controls and final zero outstanding inert parents:

```powershell
.venv/Scripts/python.exe -B .superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/parked-ingress-inert-20261010.py
```

The artifact imports current production callback/IPC/native-worker/supervisor
source and existing inert fixture ports. Native surface, original process and
Job are fakes; writer uses a real Python thread and in-memory pipe. Python `-B`
prevents bytecode writes. No broad tests, DLL calls, Popen, SQL, private input,
runtime process control or camera acceptance ran.

| Source | SHA256 |
| --- | --- |
| local_live_mux_ipc.py | 5d9209d36d4db81773fbacfa475df36318b93469cca246f277aad459060321b8 |
| windows_socket_worker.py | cba9407fcde2956a3dc48c0596bd2a74a51b101bfd9f4553c83a01f91170cdaf |
| local_live_mux_provider.py | bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339 |
| worker_job.py | 7d2144638b2ce697095b9b90ee05c569dde9dff7920c225d9d01408d95f736b6 |

Update log: 2026-10-10 initial causal source/control report. Conditional parked
overflow and receipt flag ambiguity are established. Historical runtime inner
exception, actual overflow and normal cleanup remain unproven. No source fix,
hardware acceptance, stage completion, commit or publication is claimed.
