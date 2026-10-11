# Final combined source correction — I1–I4

Date: **2026-10-06, Asia/Seoul**. Author: `final_combined_fix`.
Status: **source frozen for Root's one independent re-review**. This report
records implementation and scoped synthetic verification, not native, SQL,
Windows profile, recorder, browser, or twelve-camera acceptance.

## Baseline and scope

Read the supplied final correction brief first, shared analysis policy, active
AGENTS/canonical continuation/ledger, approved specification and plan, and
`docs/analysis/final-combined-source-review-r0.md` (`d322c00f11d7bd6bee903e5a8c78628b14d30c779beac3bc4f89bf5d3a9def54`).
That review reports **C0/I4/M0**, with supplied frozen source snapshot
`b03ae924b1817be7f7dfceb61a64e96858659c13`. Root reports actual HEAD `6436748`,
branch `codex/superlive-web-service`, with retained uncommitted Stage 1/2 work.
No Git mutation or independent reconstruction of that snapshot was performed.

The service remains an OWNER wall with per-recorder native originals, immutable
channel tasks, separate transport/retention/viewer grants, viewer-local media,
and exact original retirement. This correction joins the worker startup owner,
source-thread custody and heartbeat/native authority boundaries identified by
the complete four-finding review. No new product scope or decision is needed.

Production changes are confined to media `worker.py` / `native_source.py`, Core
`local_media_mux_service.py`, and bridge `local_live_mux_provider.py`. Admission,
SQL, IPC failure policy, public DTO/proto, UI production, observer, runtime/Job,
approval receipts and historical reports are unchanged. Existing tests plus one
focused composition module and one wall-controller test were changed. No
subagents, installations, private credentials, database connections, native
SDK/DLL invocation, native child/Job launch, services, Chrome or device action
were used by this author.

## Implemented corrections and evidence

### I1 — retain the local supplier before native viewer start

The shared executor's private optional `retain_local` callback flows unchanged
through the shared/dedicated coordinator attachment. After retaining the exact
provider handle/registration and before invoking its native start, Core captures
that handle's retirement-attachment callable, obtains the worker-owned supplier,
and invokes the captured callable. A later method substitution during the
callback cannot redirect that attachment. Observer preparation already returns
the exact instrumented original before Core captures its methods; no observer
edit or additional authority port was required.

The worker retains `_LocalStartup` against the exact lease and registration.
Its supplier owns one receipt identity. Preparation completion and original
source/peer closure are separate events. A caller timeout/cancellation stops
publication through the existing executor close; it does not cancel and forget
the original shared preparation coroutine. The close task waits for that
preparation to settle and then rereads the retained source/peer before disposing
them. A start that fails before scheduling local preparation marks only that
known-empty preparation complete. Shutdown still waits for retained entries.

The initial causal test failed with a genuine started `MuxSlotViewer` lacking
its retirement supplier after worker shutdown won the executor handoff. Current
controls exercise actual worker start with a genuine viewer at before-hook,
after-hook and before-prepare shutdown boundaries. A cancelled asynchronous
factory and subsequently held exact source close keep the original supplier,
worker registration/capacity and unconfirmed viewer receipt until settlement.
The final receipt is the original supplier's same object; local viewer cleanup
does not claim that the fake master was reaped. The provider's missing-supplier
and outstanding-read/batch rejection remain intact.

### I2 — source thread attempts require positive settlement and exact joins

Each original ingress/decoder/authority thread now has explicit attempted,
entered, exited and joined state. The attempted bit is set immediately before
the captured `start` callable is invoked. Exceptions while obtaining the start
callable are therefore positively before an attempt; exceptions from the call
are uncertain. `ident=None` and `is_alive()==False` are no longer terminal
proof. Original targets signal exit only from their retained target wrapper.

Source close waits for construction completion, each attempted target's positive
entry/exit, and each exact original join. A stop observed between starts marks
only remaining never-attempted stages done and returns through normal stopped
startup behavior. A late original target sees the existing stop. `_ended` now
means that source-owned join bookkeeping is complete, including when a closed
event loop prevented completion notifications. Existing closed-loop verification
therefore calls source close before asserting that state.

The three initial RED cases interrupted the ingress, decoder and authority start
positions after possible acquisition while all fake identities remained absent.
Final controls cover all three positions for legacy and shared sources through
actual worker close: no receipt, source removal or capacity removal before the
same late targets settle and join. Three separate pre-attempt-callable-failure
controls settle without running/joining the never-attempted originals. Existing
normal-start and decoder/peer/credit retirement suites remain passing.

Two existing partial-start fixtures now explicitly release the same stopped
original target after showing pending close. The binding-clock-only fixture
starts no stage; its previous no-op `Thread.start` stub would correctly be an
uncertain attempt under the new contract. These are fixture adaptations, not
production exceptions for fake or missing threads.

### I3 — bounded heartbeat serialization across healthy construction

Heartbeat waits outside the coordinator state lock while an original is STARTING
or has attaching/opening/refresh work. It retains its original caller budget and
cancellation and checks terminal wall/worker/master state and original transport
expiry. Once ready, it claims the retained active records' refresh state under a
short lock, renews every actual transport/slot/viewer scope, and returns success
only after those replacements and final budget/state checks. No renewal is
skipped or fabricated to suppress BUSY. Real failure remains terminal.

The initial attaching/opening controls each produced terminal BUSY before the
fix. Final controls exercise a real coordinator's initial held master constructor
and a later held slot open while the existing sibling stays current. They retain
one original and refresh three/five actual purpose scopes on completion. Deadline,
cancellation, authority expiry, denial and Stop controls report no successful
renewal. The actual TypeScript group controller now has an additional bounded
pending-heartbeat test: the same wall remains usable and no failed event/Stop All
is triggered before or after the successful response. Public API/error behavior
and the controller's real-denial handling are unchanged.

### I4 — original IO barrier covers native checks and exact replacement

Core enters the original provider's `refresh_grants` context **before** calling
admission `refresh_grant`. The provider uses its already-retained reentrant IO
operation mutex as this barrier. Transport, slot, viewer and binding authority
suppliers take that same mutex before capturing their grant snapshot, and retain
invocation custody even while waiting. Thus an already-entered native purpose
check/IO operation settles before admission invalidates its object; later checks
wait until exact replacements have been published to every holder. Nested IPC
checks during transport renewal remain reentrant on the original owner.

The mutex is an operation-serialization mutex, not `_lock` or the coordinator
registry lock. SQL/supplier callbacks execute outside those short state locks.
Waits retain parent/original grant expiry, native operation/supplier deadline and
cancellation, a bounded current-check limit, and the heartbeat caller budget.
Parent failure, original Stop/kill/confirmation and object replacement still
deny. Partial-refresh failure fences the original inside the barrier before
waiting checks can resume. IPC False remains sticky failure. Superseded, copied
and foreign grant objects remain denied by the genuine admission facade.

`MuxSlotViewer.current` retains its local invocation before waiting, and reads
take their grant snapshot after acquiring original IO serialization, preserving
all existing original/cut/batch/credit postchecks. No read/output authority is
granted by a cleanup hook or refresh context alone.

Final connecting inspection identified one additional schedule within I4:
`MuxMediaExecutor.mux_binding` could capture an old viewer grant, cross a healthy
refresh, then fail its unchanged identity postcheck and permanently fence
`MuxFrameSource`. A separate causal RED demonstrated this. A bounded retry now
requires the **same original record/handle and an observed refresh-version
change**; original expiry, Stop, replacement scope/issuer/registration checks
still win. No-generation-change denial is immediately terminal. Final healthy,
Stop, denial and copied-handle-grant controls cover the actual media binding.

Real facade/provider/IPC tests pause before and after transport, slot and viewer
replacement and drain already-entered checks for each purpose. Healthy checks
resume without fencing or a new original; current replacements succeed while
old/copy/foreign objects deny. Actual facade revocation and deadline/cancel/Stop
controls fence before a waiting viewer check resumes. The SQL observation and
native transport endpoints are inert seams; no SQL or SDK execution is claimed.

## Verification chronology and limits

Commands used the existing `.venv/Scripts/python.exe -m pytest`, existing Ruff
and mypy, and installed `apps/web/node_modules/.bin/vitest.CMD`. All commands ran
in this active worktree. Counts below overlap and **must not be summed**.

| Gate | Actual result and qualification |
| --- | --- |
| First collection | One test-helper import setup error; corrected before causal execution. |
| Initial I1–I4 causal module | **7 failed / 0 passed**, expected ownership/BUSY/grant-gap assertions, before product edits. |
| First correction | Intermediate **5 pass / 2 erroring failures** from an author enum-name typo; then **7 pass**. |
| Expanded purpose tests | Intermediate **18 pass / 9 failures** from a synthetic-clock fixture mismatch at actual provider transport replacement; corrected real monotonic fixture, then **27 pass**. |
| Expanded I2 worker control setup | The fake `threading.Thread` also intercepted asyncio's offload executor. The partial run was interrupted with tool Ctrl-C; no complete count or normal exit is claimed. The test now uses an explicit inline async offload seam. |
| First affected gate | **407 pass / 5 fail**, 412 collected. Two stopped-stage-start return-shape regressions, two provider `binding_for` denial-return-shape regressions, and one stale closed-loop `_ended` assertion. Failure left an ordinary inert decoder test thread held; the exact tool session was interrupted by Ctrl-C. This was **not normal cleanup** and is not a passing gate. |
| Corrected focused/failed targets | **38 pass**, including the five affected failures; later legacy/shared worker controls **36 pass**. |
| Corrected affected gate before final binding patch | **416 pass**, 37.00s; tool session `94254` completed normally with **exit 0**. This is the preceding Core source dependency, not a whole-suite claim on the final binding patch. |
| Final binding causal | **1 failed**, genuine media binding fenced across healthy refresh; then **99 pass** for that control plus Core module. |
| Final Core/media selection | Initial **165 pass / 1 fail**: an existing rotation test observed publication before its decoder finally released input credit. The test now waits for the actual release before asserting two returned batches. No production credit rule changed. Final **166 pass**, 1.71s, normal **exit 0**, on frozen final dependencies. |
| Actual TypeScript controller | `pnpm` was absent from PATH, so that invocation ran no tests. Existing `vitest.CMD` ran **15 pass**, normal exit 0; no package installation. |
| Static | Initial test-import/lint issues and one worker lambda typing issue were fixed. Final **Ruff 9 changed Python paths passed**; **mypy 4 production files passed** with `--follow-imports=silent`. |

The 416-case affected command selected exactly:

```text
tests/contract/test_final_mux_handoff_refresh.py
tests/tvt_parity/test_local_media_worker.py
tests/tvt_parity/test_local_media_worker_construction.py
tests/tvt_parity/test_local_media_mux_source.py
tests/tvt_parity/test_local_media_source.py
tests/tvt_parity/test_local_media_mux_service.py
tests/contract/test_local_live_mux_provider.py
tests/contract/test_local_live_mux_ipc.py
```

After the final Core binding correction, the necessary 166-case selection was
the final composition module (**40 cases**), Core mux service module (**98**) and
media mux source module (**28**). The new composition cases divide into I1 **4**,
I2 **9**, I3 **9**, I4 **18**. The web selection was only
`apps/web/tests/live-wall-group.test.ts`. No unchanged foundation/whole-web run
was added after these sufficient targeted gates.

Ordinary Python worker/event-loop/watchdog/fixture threads and installed media
libraries were used by affected tests. The final corrected affected interpreter
and final targeted interpreters exited normally; the two explicitly interrupted
earlier runs remain qualified above. In I2 thread-acquisition controls, threads
are fake retained originals. These are not Windows process/Job custody proofs.
Sample delays establish controlled ordering only, not an end-to-end revocation
or latency guarantee. Credit/source bounds do not prove physical RSS, scheduling
headroom or sustained twelve-stream throughput.

## Frozen hashes

SHA-256 of final changed files, before handoff to Root:

| Path | SHA-256 |
| --- | --- |
| `services/tvt-media/src/wso_tvt_media/worker.py` | `83dbb7e868122e9e3ad07c27f028664fc72a4a1810ef22137dfd21eecda9e5ea` |
| `services/tvt-media/src/wso_tvt_media/native_source.py` | `85b1c1195c61149af7883c0fe29c48dd3c508956ef54bdce23939c96661bd6ac` |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| `tests/contract/test_final_mux_handoff_refresh.py` | `766c4f70f17a9f37c2970088f1027fc8127eefc76d4f33b855c6eee566fcf373` |
| `tests/contract/test_local_live_mux_provider.py` | `5248f60561c26ac87dba8e984534936bbdd45930bccf4acca1b8aded3575d8a9` |
| `tests/tvt_parity/test_local_media_source.py` | `8ed0f690a4721fa5091099a865b670c0a78bb302deb327e6fd5a4a2a97eca6da` |
| `tests/tvt_parity/test_local_media_mux_service.py` | `96d6b76e08fccee45a144adcceccd4a1ed8befd56bc04cb4abcc8ce2859ccca7` |
| `tests/tvt_parity/test_local_media_mux_source.py` | `9f06fc2f8255d14f43cb26a9f94cab8c39a3f194a791da8a730865c4d859d392` |
| `apps/web/tests/live-wall-group.test.ts` | `2ac326eb12d6f84b28eabc51e9764e268b431b8aaf373dce27414326eb3982cc` |

Unchanged dependency/authority hashes checked directly:

- Admission: `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797`.
- IPC: `5d9209d36d4db81773fbacfa475df36318b93469cca246f277aad459060321b8`.
- Observer: `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f`.
- Approved spec: `036908e32cbb72024e340d8a3fc3e298838e69e1c19db14427a2fafbad5e53ee`.
- Approved plan: `122796f66f2b41061e6488b6e2d92ebe754d34e2e02c129ef13de5abc559c3f9`.

## Remaining gates and handoff

All four requested source corrections are implemented and submitted together
for one independent re-review. The barrier deliberately serializes current
authority observations with original IO; actual heartbeat/native scheduling
cost remains to be measured in the approved bounded execution gates. Unknown
thread acquisition remains charged indefinitely without positive original
settlement; this is retained custody, not a cleanup timeout waiver.

Root owns AGENTS, the execution ledger, canonical service analysis, approval
closure and actual SQL/native/browser work. Register this portable report there
and read it with R0 before the scoped re-review. Preserve Root's final SQL
**90-pass** receipt `cd80d4f2380f41ceb00c71cd228d8f38` and the prior **89/1 failed**
receipt with their original scopes; neither was rerun or retroactively changed.
Admission production bytes remain unchanged. This report does not issue source,
native, runtime or bootstrap authority.

Required follow-up remains Root's independent source gate, exact immutable
closure/approval refresh, actual Windows memory/nested-Job qualification,
bounded two/four-channel probes, and twelve-tile common-five-minute Chrome
acceptance with original retirement. There is no new open product question in
this correction wave, and no claim that these execution gates have passed.

Update log: 2026-10-06 — implemented the four R0 corrections in one controlled
wave; recorded causal RED, intermediate failures, qualified final GREEN/static
evidence and exact final hashes; source frozen for independent re-review.
