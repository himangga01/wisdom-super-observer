# Shared recorder live acceptance

Updated: 2026-10-06, Asia/Seoul.

## Authority and current baseline

Use `docs/service-analysis.md`, the approved stage2 specification/plan and
`AGENTS.md` for the current source and execution authority. This guide records
the required shared-recorder acceptance gates and their dated outcomes. Read it
before another acceptance run and update it afterward. Preserve prior failures.

Source baseline: branch `codex/superlive-web-service`, HEAD `6436748`, with
retained uncommitted stage1/stage2 implementation. Tasks1–11 and the separate
recovery, proof-phase, diagnostic projection and media-constructor source gates
have independent approvals. Runtime partA and partB are source-approved. The final combined correction
review is C0/I0/M0; the downstream raw-probe startup adapter R188 is independently approved
C0/I0/M0 (final source f2db7a05). Root orchestration requires its separate
source/phase/recorder-association approval before hardware execution.

**Actual Windows inert Job gates have run; bounded two/four recorder gates
have passed; shared Chrome acceptance has not run.**
The earlier stage1 nine-camera acceptance is historical evidence, not a
shared-recorder or twelve-camera result. APK comparison remains a separate gate.

## Service and composition

An OWNER wall uses one original authenticated transport per recorder, immutable
physical substream slots and separately retired viewers. Two base originals,
one exclusive main original, twelve viewers and sixteen retained physical slots
are the reviewed profile. A focus handoff reserves a nonrenewable twenty-second
reference before the old viewer stops. Initial binding permits negotiation;
actual frame and decoded delivery evidence remains required for publication.

Windows runtime uses the same admission, original budget, provider, coordinator,
executor, media ledger and source factory instances. Shared mode defaults off.
Only reviewed schema3 input with `WSO_TEST_LOCAL_MEDIA_SHARED=1` can select it.
Trusted server context supplies the React page flag. Browser payloads cannot
select the worker profile or assert native cleanup.

## Gate status

| Gate | Current outcome | Required next evidence |
| --- | --- | --- |
| Feature source Tasks1–11 | Independently approved | Final combined source review |
| Recovery SQL/Core and initial proof phases | Final owned SQL selection: 90 passed, original process/DB cleanup, source preserved | Actual device/browser composition |
| Wire diagnostic projection | Independently approved; synthetic codec/IPC cases | Actual route, command, sequence and ACK observations |
| Partial media-worker construction | Independently approved; fake thread/loop cases | Actual retained runtime owners and complete shutdown |
| Worker supervisor | Actual 2GiB outer Job and fifteen inert 512MiB inner Jobs admitted and normally retired | Real native/decoder load and host memory measurements |
| Schema3 observer/raw probe | Current-run/deadline correction and R188 startup adapter independently approved | Actual current-run proof and normal cleanup/terminal digest |
| Two-channel recorder probe | COMPLETE: 0899e1ad, two HEVC frames per slot, exact original cleanup | Decoder/Chrome acceptance remains separate |
| Four-channel recorder probe | COMPLETE: 10cec96c, four distinct slots on one original, exact prior-two association | Eight/four store inventory and twelve-camera Chrome |
| Twelve-camera Chrome | Not run | Twelve simultaneously presented streams progressing for at least300s |

## Source and runtime approval

Create new immutable source/native/runtime approval filenames only after the
required independent source gates pass. Never overwrite a historical accepted
envelope or treat a legacy-only receipt as authority for changed mux modules.
Pin all actual imported Core, native, media, API, contracts, runtime, generated
bootstrap, tests and guides. Check exact required path counts, hashes and ACLs.
Missing dependencies or profile fields fail before private input or native work.

The reviewed limits are worker2GiB process memory, native and decoder512MiB
per process, global encoded64MiB, per-slot16frames/4MiB, and common retained
host1GiB. These are source/profile limits. They do not establish process RSS,
physical host headroom or a9.5GiB simultaneous allocation. Measure actual host
headroom and original Job behavior before hardware; retain the historical
single-child nested proof and failed fifteen-child attempts as separate evidence.

## Bounded recorder probes

Run two distinct sub tasks on one recorder before four. Each live phase is at
most120s, followed by separately bounded original cleanup. The probe consumes
real authenticated SQL tickets and retained provider/coordinator ports; it does
not construct grants or synthesize actual device proof.

Required evidence includes actual original login/inventory association,
immutable task/slot identity, parsed wire route/kind/command/sequence/ACK,
post-cut complete key and parameter-set origin, advancing frame counts and
normal original retirement. Wire kind and selected stream kind are distinct.
Unknown startup notifications remain a protocol gate; do not suppress them or
weaken parser checks to obtain a pass.

`RAW_GATE_RETIRED` is only a bounded raw-probe result. It cannot replace observer
COMPLETE, writer settlement, final snapshot digest, source/DB preservation or
original runtime/Job cleanup. A live failure remains failed even if cleanup
succeeds. Evidence must belong to the current active observer/run and its exact
owners, registrations and cuts. Completed prior observations cannot qualify a
new run. The prior-two orchestration input requires Root to verify the actual
immutable prior receipt; the input boolean alone is not evidence.

## Chrome acceptance

After source/profile and both recorder probe gates pass, freeze a fresh owned
runtime and start installed trusted Chrome through GPT web control. Verify the
actual8/4 inventories. Measure1/4/12 stable SQL/CPU/memory/startup/drop windows
once per load. Begin the common300s hold only after all twelve streams are
presented. Total live run remains bounded1200s; separately label renewed
observer windows and retire each writer before its bound.

Verify one presented main-to-sub return while siblings progress, ten rapid
request pairs with distinct attempted/accepted/presented/cancelled/settled
counts, individual Stop and fresh-key reattach, last-reference/StopAll, valid
resolution rotations and genuine acknowledged no-frame behavior. Synthetic
negative cases do not become actual device/Chrome results.

## Normal cleanup and reporting

Every applicable viewer, slot, master and reference must settle with its exact
local or native receipt. Preserve original process/Job/pipe/thread handles;
worker exit alone does not prove descendants or encoder/decoder suppliers are
settled. Uncertain owners remain charged and cannot be replaced.

Final acceptance requires original Chrome/coordinator exit0 and reap, API/worker
and owned context retirement, owned DB removal, source DB/source pins unchanged,
zero private output occurrences, and observer COMPLETE with stop requested,
writer settled, no required omissions/failures and exact final digest.
Exceptional retirement is failed acceptance. Update this guide and the canonical
English service report with actual run IDs, bounded counts, outcomes and limits.

## Update log

- 2026-10-06: Created the portable gate/status guide from approved stage2
  requirements and retained source-review evidence. No hardware/runtime/browser
  acceptance is asserted by this preparation entry.

- 2026-10-06: Refreshed source status after the final combined review and
  90-test owned SQL gate. Actual inert Job evidence: single-worker run
  `889e19640b034c4a97944e31d0ee5810` and fifteen-child nested run
  `48c896f8398d421e804ee52cf9fb46ad`, both original ownership and normal
  retirement confirmed. These tests did not load the vendor SDK or decode
  CCTV. Initial single-worker wrapper exit1 used an invalid receipt key;
  corrected predicate verified the retained actual receipt without rerun.

- 2026-10-06: R188 raw startup adapter final scoped review is C0/I0/M0;
  97 focused tests passed with two excluded controls. Pure/source evidence does
  not qualify actual raw frames. Root helper corrections preserve separate
  sticky phase deadlines and bind prior-two proof to the same recorder ordinal
  and exact private input digest. Private digest values remain in ignored
  execution receipts. Root helper re-review and fresh approval precede hardware.

- 2026-10-06: Root raw orchestration final R1 is C0/I0/M0 (2bc85f59),
  helper 8e5e9e61 and unchanged materializer c6a3c665. Separate late phases
  remain FAILED and prior-two proof requires exact recorder/input association.
  New schema3 closure and actual recorder gates follow this source approval.

- 2026-10-06: Actual raw2 `0899e1adda99428b93b2a120ba1f2bbb` and raw4
  `10cec96c431e42a2b0aeb7be5c3d9798` passed under schema3 source740115aa.
  Recorder ordinal1 actual inventory8, one shared original per run, two HEVC
  post-cut key/frame observations per distinct slot; live elapsed raw4=3015ms.
  Original viewer/native/worker/Job/writer/stdin, observer COMPLETE/digest,
  session/ownedDB/context retirement and source preservation/private0 confirmed.
  Parent processes exited0 and were reaped. First setup run e23284c9 remains
  FAILED/unknown root cause; successful retry does not erase it. No decoder,
  twelve-camera capacity or Chrome acceptance is asserted by these raw gates.
