# R194 runtime-owned Core close-origin diagnostics

Analysis date: **2026-10-09, Asia/Seoul**.

Read before reuse: [service report](../service-analysis.md),
[shared SUB diagnosis and runtime trace plan](2026-10-09-shared-sub-liveness-diagnosis.md),
[prior Core debug review](2026-10-09-live-core-debug-review.md), and
[API logging authority](2026-10-09-live-api-debug-logging.md).
Refresh this report after a source correction or actual diagnostic execution.
The controller owns the canonical AGENTS/service/handoff bridges, immutable
source envelopes, native receipt references and actual runtime acceptance.

## Scope, baseline and actual evidence

Implementation worktree:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, actual HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained uncommitted Stage1/2,
R193 and concurrent native diagnostics work. Initial Git status confirmed that
existing delta; this task performs no stage, commit, reset, push, database,
SDK, recorder, browser or application-process operation.

The runtime starting bytes were the reviewed R192/R193 runtime SHA256
`35c8a60453470cc72e25f9259a0c5c40ffb4a590a6fdbae9003f8ca1e17e8fc7`.
The scoped runtime diff against tree
`225f9786f273fd6276ac3f1fed50835a912cf3bb` isolates the R194 changes from
the earlier retained implementation. This tree is a source-review baseline,
not the Git commit HEAD.

Controller-supplied evidence: bounded observation run `6c40be51` normally
retired its original coordinator, exit 0/reap, context and owned DB; source
equality/private checks passed and only PostgreSQL remains running. Its first
SUB's earliest retained failure was `peer/explicit_close` at 26984 ms, 245
encoded frames, all omission/failure counters zero, without manual Stop/HIGH.
The repeated SUB reached approximately 203 s, 2038 decoded frames and successful
wall/lease heartbeats, with no first failure before intentional Stop. These
facts were supplied by the controller; this author did not inspect private
run artifacts or execute that device run. They do not prove a fixed TTL cause.

The unobserved synchronous chain remains the next measurement:
coordinator current/fence/close decision, retained provider retirement callback,
scheduled worker cleanup, then peer explicit close. This instrumentation is
implemented and offline verified; **no R194 actual close cause, repaired
playback, MAIN readiness, twelve-camera or APK acceptance is claimed**.

## Service purpose and architecture

The shared local CCTV service retains one recorder transport, channel slots
and separate viewer grants. Core coordinates original custody and retirement;
admission retains immutable authority objects; the provider/native owners
control transport; the worker supplies decoded media and WebRTC peers.

R194 changes only this author's runtime/helper/two focused test files and this
report. Core service/admission, SQL, media worker/source, prepared originals,
binding and receipt suppliers, native/viewer issuers and retirement callbacks
are untouched by this author. A separate native author owns the frozen typed
first-key callback implementation; this runtime consumes that reviewed API.

`compose_shared_media` now constructs the existing coordinator, installs six
exact-instance wrappers retaining each original bound method, retains/starts
the diagnostic publisher, then constructs `MuxMediaExecutor`. Thus the
executor's original monitor cannot start before the hooks are installed.
Existing admission/coordinator/provider/executor/worker owners, two-value
composition return, source factory and media budgets remain the same.

| Original hook | Record condition | Closed output |
| --- | --- | --- |
| Coordinator `current` | Exact returned `False` or original `BaseException` | `COORDINATOR_CURRENT`, fixed result/exception category, bounded caller chain and existing viewer/master state. This observes the final existing refresh retry result. |
| Coordinator `_fence` | First entry per original record | `MASTER_FENCE`, synchronous caller chain and pre-call master/refresh state. |
| Coordinator `_close_viewer` | First entry per original record | `VIEWER_CLOSE`, synchronous caller chain and pre-call starting/stopping/closing/master/refresh state. |
| Admission `current_transport`, `current_slot`, `current_viewer` | Exact returned `False` or original `BaseException` | `GRANT_CURRENT`, fixed `TRANSPORT`/`SLOT_RETENTION`/`VIEWER` purpose, existing registration/denied/closed/replacement/expiry qualification. |

Original invocation occurs once with unchanged arguments/keyword values;
results are returned unchanged and original exceptions use bare re-raise.
Success checks emit nothing. Close/fence snapshots enqueue before the original
call, preserving the synchronous origin before downstream scheduled cleanup.
Optional setup, clock, projection, callback and writer `BaseException` failures
are isolated from the original call/result/failure.

No added authority, SQL, current, refresh, cleanup, supplier or owner-clock
method is invoked to collect metadata. Exact retained dataclass/dictionary
fields are read without acquiring authority locks. `snapshot_atomic=false`
qualifies concurrent state: individual booleans may describe different moments.
`expired` is present only for the owner's ordinary `time.monotonic` clock;
custom-clock expiry is omitted. That diagnostic comparison does not renew or
authorize anything.

`closed` alone is not labelled superseded. `holder_replaced` is recorded only
when the existing exact transport/slot/viewer holder demonstrably retains a
different object of the same expected grant type. A false old grant during
refresh remains qualified evidence, not a terminal-cause claim.

## Privacy, bounded output and publisher custody

The strict codec accepts fixed event/purpose/result/exception categories,
fixed state booleans and master enum, bounded integers and at most eight
allowlisted module/function/source-line items. Unknown frames consume the same
eight-frame inspection budget. Source paths are used only for internal exact
mapping; filenames and source text are not emitted. It never inspects frame
locals or exception messages, names arbitrary exception classes, formats a
traceback, serializes arguments/identities, exports SQL rows or retains media.
Frames and exceptions are not retained in the queue; only checked canonical
bytes and numeric counters remain.

No observer ordinal mapping is mutated or synthesized. Output uses finite
record sequence and per-hook accepted-event sequence. No UUID, lease, actor,
session, native, scope or channel value is logged. Close deduplication retains
at most 127 internal event/integer-identity pairs, never the argument objects.
It counts suppressed repeated entries. Integer identity reuse can conservatively
suppress a later record; the file is bounded evidence, not complete correlation
or original-owner proof.

The existing explicit `API_DEBUG`/observation opt-in remains independently
usable with observation off. Default-off creates no new files, helper owner,
publisher or hook replacement. New fixed current-run files are
`media-core-state-debug.jsonl` and `media-native-startup-debug.jsonl` under the
existing owned evidence folder. They reuse the private-directory ACL helper,
exact run/context parent checks, link/junction rejection, exclusive creation,
regular-file/original device/inode checks and actual 65536-byte writer bound.

Core reserves at most 127 failure/entry records plus one final summary, 2048
bytes per record and 65536 attempted bytes, including failed writes. A reserved
2048-byte summary allowance ensures omission/failure counters can be attempted
even after event exhaustion. Counters saturate; no failed write is retried.
Summary `written` counts preceding successfully written event rows; runtime
status also includes a successfully written summary.

Hooks enqueue only. One retained non-daemon runtime publisher drains at 250 ms
outside all Core/admission/native locks. Its exact original Thread is retained
before `start`; a start exception does not discard a possibly acquired thread.
On normal shutdown, existing server/media/native/admission disposal completes
before the publisher is stopped/joined and the final bounded flush occurs.
Unknown/failed join returns false; the runtime retains the owner and polls
until settlement instead of reporting it retired. A stalled file operation
can consequently delay runtime retirement. Optional file IO does not enter
the caller's authority critical section.

## Frozen native callback integration

The separate author's frozen API is
`wso_tvt_bridge.local_live_diagnostics.NativeFirstKeySink`:
callable typed record input, `drain() -> tuple[bytes, ...]`, and read-only
`dropped`. Runtime creates it once only with debug opt-in, passes that exact
object as `NativeLocalMuxProvider(first_key_debug=...)`, and attaches it to the
same retained publisher. Provider prepared methods and issuers are not patched.

Native queue occupancy bounds reset on drain. Therefore this publisher adds
an independent **run-total** 128-record/65536-attempted-byte limit for the native
file, including failed writes. It drains canonical bytes outside owner locks;
the separate file does not consume the Core queue's budget. Queue drops,
runtime omissions, accepted/written counts and diagnostic failures appear
under `mediaCoreStateDebug.native` in the final existing `worker-close.json`.
An unavailable native file or Core publisher means evidence may be absent;
optional setup failure does not change media startup authority.

Native callback dependencies independently checked against the author's freeze:

| Dependency | SHA256 |
| --- | --- |
| `local_live_diagnostics.py` | `106dde9503a1207640fbb88b7322f404440e3787aabdd645268f0fa772359b47` |
| `local_live_ipc.py` | `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910` |
| `local_live_mux_provider.py` | `bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339` |

This author's unchanged protected Core service SHA256 is
`9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc`;
R193 admission is
`7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999`;
the prior `core_debug.py` remains
`582e511552961f1905ea42d3ed8472dc9153d0fa94028a3d9c0699fbc6e41a5b`.

## Fresh verification and limits

Observed RED: the initial 12 helper controls failed for the absent helper; three
runtime controls failed for absent state setup/composition wiring; native drain
and two native wiring controls failed before their respective implementation.
A real-admission fixture initially lacked its original `_mux_lock`; that test
setup was corrected without production changes. The later managed-thread and
worker-retirement controls characterize retained cleanup behavior.

Fresh final scoped command, bytecode and pytest cache disabled:

```powershell
.venv/Scripts/python.exe -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_media_diagnostics.py tests/contract/test_native_first_key_debug.py -q -p no:cacheprovider
```

Result: **61 passed in 1.25 s**, exit 0. This includes 20 new Core-state/runtime
controls and 41 prior Core/API/native controls. They exercise actual inert
coordinator fencing, real admission superseded-grant false, unchanged retained
supplier identities, original call/exception preservation, bounded concurrent
queue omission, closed codec negatives, deferred writes, native drain budgets,
temporary fixed file wiring, before-monitor installation, uncertain original
thread start/join, and final worker cleanup ordering. No database/native process,
recorder, browser or listener is opened by these fixtures; the publisher's
ordinary Python thread is exercised and joined.

Scoped Ruff check and Ruff format check: **all checks passed; four files already
formatted**, exit 0. One test import-order issue was corrected before the final
run. Strict helper mypy with `--follow-imports=silent --no-incremental` and an
ignored task-local cache: **no issues in one source file**, exit 0. The first
attempt using Windows `--cache-dir=NUL` produced a mypy internal error; the
ordinary ignored cache resolved that tooling failure. No dependency install or
version change was made. Scoped `git diff --check` for runtime passed. New source
files were read and statically checked; protected raw hashes match the supplied
current source authority.

These are offline source controls, not independent real Windows ACL receipts,
native admission/first-key evidence, SQL acceptance or Chrome playback. No broad
test suite was run under this narrow diagnostic task. Finite bounds, unknown
frames, first-entry suppression, concurrent state and optional writer failure
can omit causal evidence. Empty or missing logs do not prove absence of a fault.

## Frozen author files and next gate

| Author-owned source/test file | SHA256 |
| --- | --- |
| `scripts/test-local-devices/runtime.py` | `2140c0352294f13e9ad387c8482c1d92451b8ad8e636ba3697981ba9f4960008` |
| `scripts/test-local-devices/core_state_debug.py` | `1d705892004167f539566dc251e32ef02230dac9e95abf16f4137b9bc2e524d7` |
| `tests/contract/test_local_media_core_state_debug.py` | `b809635bc84e002204b734fdd365cda6d3ba2d1e902a4881ce0a9c963332872d` |
| `tests/contract/test_local_media_core_state_runtime.py` | `b3da84472497b9f3e01e2f36bd9f8b465d410900c9db67c348822b6cde319030` |

Priority: independently review this frozen five-path source/report scope and the
separate native scope; the controller then refreshes immutable source/native
references before actual execution. Capture the first synchronous Core event
and first-key counters, qualify all omissions/writer/custody outcomes, retire
originals normally, then update the portable reports. Keep every pinned report
unchanged throughout a run.

Open questions remain which actual current/fence/close entry initiates the SUB
failure and whether native MAIN startup fails before key acquisition, parsing,
deadline or current authority. No TTL, reconnect, authority or product-policy
change is selected by this source instrumentation.

Update log: 2026-10-09 — R194 runtime-only state wrappers, retained publisher and
frozen typed native drain integration implemented; 61 scoped offline controls
and scoped static checks passed. Actual R194 execution and independent review
remain controller-owned gates.

## R1 — ambiguous publisher startup custody correction (current source)

Date: **2026-10-09, Asia/Seoul**. The preceding implementation/hashes and 61-test
gate remain historical R0 evidence. Independent
[runtime review R0](2026-10-09-core-close-state-debug-review.md) established
**C0/I1/M0**: retaining a Thread reference did not cover interruption before
its bootstrap identity became visible. The original R0 author-report SHA256 was
`8eb35d0095a50b220ae97dcdf3bc1eab27d58499ef555685cdda96f7fed8cbf2`;
the controller's retained R0 tree/package preserves those exact report bytes.
This appended correction supersedes R0's incomplete startup-custody conclusion;
it does not change the historical review or test evidence.

This author independently reproduced I1 with the actual Python Thread startup
path. A controlled bootstrap barrier held the already acquired platform thread
before identity assignment, while the original startup Event's wait raised
`KeyboardInterrupt`. Both `ident is None` and `is_alive() is False` held for
that acquired original. The new causal test was **RED** because R0 returned
`close() is True` and finalized its output in that window. Its `finally` restored
the original Event wait, released the barrier and joined the exact acquired
thread even on the failed assertion; no test thread was abandoned.

Only `core_state_debug.py`, its focused test file and this report change in R1.
Runtime integration, native callback/helper/IPC/provider and Core/admission/SQL
sources remain frozen and unchanged. The helper now records an explicit startup
attempt and fixed outcome `NOT_ATTEMPTED`/`UNKNOWN`/`RETURNED`/`RETIRED`.
The attempt is recorded before invoking the retained original's start. Any
interrupted attempted start remains `UNKNOWN`; absent identity and false
liveness do not prove non-acquisition. `close()` returns false without final
flush while that original remains unidentified. Once identity is published,
the exact original join must complete normally and liveness must be false
before its outcome becomes `RETIRED` and output can finalize. Python's original
join also checks its positive startup Event; a join exception retains custody.

No diagnostic owner clock, authority, cleanup, SQL, provider supplier or extra
thread-start call is introduced. Startup outcome/attempt appear only as fixed
primitive final-worker status fields; the Core/native JSONL codecs and budgets
are unchanged. Normal setup with no start attempt remains positively unacquired.
An interrupted attempt that never reaches bootstrap cannot automatically be
certified unacquired: the runtime retains it as unknown indefinitely unless
positive original retirement becomes available. No guessed timeout or kill
claims settlement. This may delay cleanup after an optional startup failure,
as required by the original-owner custody contract.

The causal control is now **GREEN**: pre-bootstrap close returns false with
`publisher_settled=false`, `publisher_start_attempted=true`, outcome `UNKNOWN`
and zero writes. After gate release and exact-original join, close returns true,
outcome `RETIRED`, with exactly one summary. The previous known-started/uncertain
join and normal server/native-before-publisher retirement controls remain green.

Fresh scoped command is the same six-file selection listed above: **62 passed
in 1.26 s**, exit 0 (the retained 61 gate plus one causal control). Ruff check
and Ruff format check on the two changed Python files passed; **two files already
formatted**. Strict helper mypy passed with **no issues in one source file**.
These checks exercise inert joined Python threads and temporary fixture files;
no database, SDK/native process, recorder, browser, listener, commit or broad
test suite was used. No actual R194/R1 execution or liveness acceptance is claimed.

Current R1 source/test hashes:

| Path | R1 SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `8ba3e0cc9013c6e783f2b14288d190a7904dc1b1a9d0762edfeda14aea33efed` |
| `tests/contract/test_local_media_core_state_debug.py` | `c3bad0c0324658eb16e623ebfc7368f390e815e574755f852fa1f0052176b9dd` |

Freshly checked unchanged raw hashes: runtime `2140c035…`, runtime tests
`b3da8447…`, Core service `9d055101…`, R193 admission `7e31d5cd…`, native helper
`106dde95…`, IPC `8571477a…`, provider `bbddd3e4…` and native tests `bf5c4bcc…`.
Their complete hashes remain in the preceding frozen tables or native authority.
The controller owns the R1 scoped freeze/re-review and subsequent source/native
closure/actual-run gates; preserve this R1 after that freeze.

Update log: 2026-10-09 — confirmed R0 I1 with a causally RED acquired-thread
pre-bootstrap interruption, corrected only publisher startup custody and
verified GREEN plus the retained scoped selection (62 passes). R0 history and
protected runtime/native/Core bodies preserved; separate R1 review remains open.
