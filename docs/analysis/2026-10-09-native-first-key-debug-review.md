# R194 native first-key diagnostics: scoped source review

Analysis date: **2026-10-09 (Asia/Seoul)**. Review round 0, SPEC and QUALITY.

**Verdict: C0 / I0 / M0.** No critical, important or minor finding was identified
in the frozen four-file package. Optional parent diagnostics, closed primitive
encoding and the prepared-start callback satisfy the scoped source contract.
This verdict does not establish runtime publisher integration, recorder MAIN
availability, repaired playback or new source/native execution authority.

## Authority, baseline and scope

Read before review: shared `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
[AGENTS.md](../../AGENTS.md), the latest 150 lines of the canonical
[service report](../service-analysis.md), the
[NO_SIGNAL diagnosis](2026-10-09-dedicated-main-no-signal-diagnosis.md), R193
[R0 startup review](2026-10-09-dedicated-main-startup-review.md),
[R1 fixture review](2026-10-09-dedicated-main-startup-review-r1.md),
[native pin review](2026-10-09-dedicated-main-native-pin-review.md), and the final
[R194 author report](2026-10-09-native-first-key-debug.md).
The verification-before-completion skill was applied. The controller owns
canonical report/AGENTS bridges and future receipt/execution work; this reviewer
writes only this separate report. Read this review with the author report before
reusing or changing the diagnostic contract, and refresh affected evidence after
source changes or actual acceptance.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Freshly checked branch `codex/superlive-web-service`, actual HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial Git status contained extensive
retained Stage 1/2/R193 tracked changes and untracked source, tests and reports.
Those changes were preserved. The primary checkout is not this implementation
baseline.

Frozen review package in
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/`:

- `task-1941-review-r0.diff`, SHA256
  `f9f79b5d18628a01c53808dc189dae07853b75f38ca035ce56e1ceaf7132f263`.
- `task-1941-frozen-hashes-r0.json`, SHA256
  `a76a4bd36f3304e7288363f4f9b30379b88dfc2ae2cde35209b8f94eb2d8f3cb`.
- BASE snapshot tree `fbc7c55645cf6e784a1226b1ecd3ba13c504e481`;
  candidate snapshot tree `65ee337c5217355b17df18b75d669a1b33a6ca0d`.
  These are source trees, not changes to actual HEAD or the index.

The assigned delta has **four files, 754 insertions and one deletion**. The full
snapshot comparison also contains prior pin/documentation and separately owned
runtime changes; those are outside this review. Current raw-file hashes and
newline-normalized candidate blob content were freshly verified:

| Scoped path | Raw SHA256 |
| --- | --- |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py` | `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py` | `106dde9503a1207640fbb88b7322f404440e3787aabdd645268f0fa772359b47` |
| `tests/contract/test_native_first_key_debug.py` | `bf5c4bcc635215c0afc99deecb319d840c0be0a0b677158bd285a74da9b42ba9` |

Final author-report SHA256 freshly matched
`30a4b918f03dc07f59b948a937b93c509ba17924f9d635e5b004511bc9479bc6`.
Protected codec, Windows provider, Windows worker, legacy live provider,
ownership and R193 admission raw hashes matched the author/diagnosis baselines.

## Purpose, implementation and findings

The service presents authorized CCTV recorder channels in Chrome. Shared SUB
uses a retained recorder mux; dedicated MAIN retains its own original native
custodian and legacy IPC parent. Historical controller evidence from retired e9
establishes an accepted matching MAIN ACK followed by the existing first-key
NO_SIGNAL deadline. Parent ACK-only, non-key and late-key outcomes cannot identify
the missing boundary without additional observation. This change measures the
exact original parent's existing state. It does not repair playback.

| Requirement | Source assessment and fresh evidence |
| --- | --- |
| Default off, exact original parent | `LiveParentAuthority.__init__` creates a tracker only for `diagnostics is True`; the provider argument defaults to `None`. The prepared original supplies the option only when its callback is present. Default-off controls produce no record and preserve original progress/current calls. |
| Original check once, exact result/error | `local_live_ipc.py:155` delegates `super().check(current)` once on each selected branch. Clock and tracker failures are isolated with `BaseException`. Independent controls preserve exact `False`, `True`, arbitrary return-object and original exception identity. No duplicated guard or extra supplier call was added. |
| Snapshot before terminal clearing | `deny:240` captures under the existing transition lock before ready/FIFO/codec clear. The real-parent partial-fragment test retains partial/assembly/fragment values after codec close. Subsequent close returns the retained first snapshot. Only completion of an existing check can amend its numeric count/timing fields. |
| Parsed-state observation | Receive/decision hooks read existing IPC progress. ACK timing uses the already established cutoff. Frame counters observe each visited parsed item before the original first-frame guard. The tracker reads codec counters, lengths and structural fragment integers; it stores no authority, codec, media bytes or header identity. |
| Closed primitive privacy and bounds | `local_live_diagnostics.py:46/79` defines a frozen slots record, exact-type encoder, closed enums and command categories, bounded integers and nullable relative milliseconds. No identifiers, arbitrary strings, exception text, media or absolute wall time can enter the serialized record. All 30 fields reject arbitrary objects; an additional control rejects `worker_observed=True`. Counts/times/sizes saturate at 2^31-1. |
| One emission after original startup/cleanup | Provider outer `finally:1385` obtains the original authority snapshot and calls the optional callback once after `constructing()` exit and failed-start cleanup attempt. Focused prepared controls verify authority/custodian locks are not owned, exact original exception identity survives a callback `SystemExit`, NO_SIGNAL remains 504, and repeated close emits no second record. |
| Sink queue custody | `NativeFirstKeySink:118` encodes canonical ASCII bytes before its short private lock, retains at most 128 records/64 KiB and saturates its dropped count. `drain()` clears occupancy; it does no file I/O. Tests verify count/byte bounds and an empty second drain. |
| Preserve R193 and existing acceptance logic | Independent AST comparison removes only the added diagnostic syntax and recovers the exact BASE IPC/provider AST. Original startup predicate, same-issued retired BUSY branch, cleanup, parser validation, timer ordering, authority/cancellation guards and frame acceptance remain structurally identical. Protected worker/native/codec/admission bodies retain their reviewed raw hashes. |

**Exact findings: none.** No source correction is requested by this gate.

The controller clarified the success boundary: a successful startup snapshot in
the outer `finally`, after original handoff and construction exit, is intended.
It is not an atomic measurement at the first-ready instruction. A concurrent
terminal snapshot can win and then supplies the record. The mandatory capture
before clearing applies to terminal deny/close. The source satisfies that
clarified contract without moving callback work into authority/custodian locks.

## Fresh verification and limits

Executed from the implementation worktree:

```powershell
& .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/contract/test_native_first_key_debug.py
git diff --check fbc7c55645cf6e784a1226b1ecd3ba13c504e481 65ee337c5217355b17df18b75d669a1b33a6ca0d -- services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py tests/contract/test_native_first_key_debug.py
```

Both exited **0**. Pytest: **15 passed**, no failures/skips, **0.10 s**. Invented
packets, fake monotonic time and in-memory connections exercised actual parent
setup/pump/check/parser and prepared-start methods. Prepared tests reuse inert
R193 SQL edges; their pipe constructor is replaced before binding. No database
connection, native child/Job, DLL, browser or private input is involved.

Two successful independent stdin probes used `.venv/Scripts/python.exe -B -`:

- Exact raw/candidate hashes for four files, six protected raw hashes, frozen
  author hash and scoped file set passed. Removing the diagnostic-only syntax
  recovered exact original IPC/provider ASTs, preserving all existing bodies.
- **Eight independent controls passed**: six exact return/delegation cases
  across enabled/default-off modes, original exception identity despite clock
  and tracker `BaseException` faults, and diagnostic constructor fault isolation.
  **31 closed-field rejection controls passed**: one for every record field plus
  the forbidden worker-observed claim. A valid record remains at most 2048 bytes.

Initial combined probes stopped on two reviewer harness assumptions: requiring
the whole snapshot delta to contain only these four paths, and omitting the new
annotated diagnostic field from AST removal. The scoped comparison and complete
diagnostic removal resolved those assertions. They did not demonstrate a product
failure or change any source/runtime state.

Author-reported **39 focused passes**, Ruff/format on four paths and mypy on three
production paths remain author evidence; the reviewer independently ran the
15-test diagnostic scope and controls above. The unchanged 24 R193 tests and
static tools were not rerun. Bytecode and pytest cache writes were disabled.
No optional broad suite or nested agent was used. Only this report was written;
application source/tests, index, HEAD/ref and historical reports were preserved.

## Qualifications, priorities and open questions

The record is **parent-only**: `worker_observed` is fixed false. ACK plus zero
parsed parent media cannot establish recorder silence, callback inactivity or
worker forwarding absence. Enclosing-check timing includes original guards and
terminal deny work; it does not isolate supplier/SQL latency. Rounded relative
observations do not change the unchanged precise deadline comparisons.

The snapshot preserves state before parent deny clears it. Malformed input can
make the unchanged codec clear itself inside `feed` first, leaving no prior
partial state to recover. A parsed item beyond an earlier terminal return in the
same feed tuple is not visited/counted. Existing codec packet counts include ACK
and heartbeat parsing; they are not decoded or browser frame counts. Enabled
instrumentation adds bounded observation work and does not prove hardware timing.

The native sink's bound is **queue occupancy**. Draining permits later entries.
The separately reviewed runtime owner must enforce the 128-record/64-KiB run
total and private publisher/file ownership; those implementations are outside
this four-file gate. No source change to this sink is requested for that separate
runtime contract.

Priority P1: complete runtime integration review, include the imported helper
and reviewed report in fresh public/native/source closures, refresh qualified
immutable execution authority, then collect one bounded MAIN reproduction with
normal original cleanup. The controller owns those steps. Current approval pins
do not authorize changed source until refreshed. No database/native/SDK/browser
execution or private approval input was read or performed by this reviewer.

Open measurement questions: which accepted key/non-key/partial/IPC/check pattern
the actual MAIN parent receives, and whether parent-only evidence warrants a
separately reviewed worker measurement. No new product choice is required by
this instrumentation. Actual MAIN/Chrome playback, first SUB close cause,
return/reconnect, duration/performance, twelve-camera and APK parity acceptance
remain open and separate from this source verdict.

Update log: 2026-10-09 — frozen four-file R194 SPEC+QUALITY review C0/I0/M0;
15 diagnostic tests, eight independent delegation/fault controls and 31 primitive
rejections passed; original AST and frozen hashes verified. Runtime/hardware
acceptance not claimed. This report is frozen after its final hash is supplied.
