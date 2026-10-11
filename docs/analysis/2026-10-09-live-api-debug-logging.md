# Bounded local live API diagnostics

Analysis date: 2026-10-09 (Asia/Seoul).
Source baseline: `codex/superlive-web-service`, HEAD `6436748`, with the previously
reviewed uncommitted Stage 1/2 implementation and concurrent frontend correction.
This worktree is the implementation authority; the primary checkout lacks those
changes. The preexisting working tree was already substantially modified. Git's
HEAD diff includes earlier work and must not be interpreted as this change's scope.

Read before work: shared `C:/Users/강지혜/.agents/analysis-policy.md`, this worktree's
`AGENTS.md`, `docs/service-analysis.md`, Stage 2 progress ledger and
`docs/analysis/2026-10-06-multiview-stage2-browser-runtime-source-review.md`.
Read this report before reusing or changing these diagnostics and update it after
source review or actual log capture. The controller owns canonical AGENTS/service
report bridges, new immutable source approvals and actual execution.

## Purpose and observed cause

The local CCTV service authenticates browser control requests, validates their
query/body and shared-mode selectors, issues one-use application tickets and calls
the separate worker through RPC. The API never opens local device credentials or
native media itself. Existing runtime API/worker output is discarded and console
logs cannot establish which API phase produced a failure.

The controller supplied actual run evidence for `7cbe5b4a`: login and real 8/4
channel inventories passed, playback returned `422 LOCAL_DEVICE_INPUT_INVALID`,
and worker observation remained zero. The shared-mode guard requires a wall, and
main additionally requires a focus reference. Legacy panel requests lacked these
selectors. These supplied observations are not a hardware test executed by this
author. The frontend correction is independently owned; this logging change does
not relax the guard or claim browser playback acceptance.

## Implemented architecture and behavior

`services/api/src/wso_api/tvt/local_media_diagnostics.py` defines a request-local
phase tracker and a synchronized bounded sink. `LocalMediaRoute` records a final
structural result for successful requests and failures. Dispatch advances through
mode, worker lookup, tenant authorization, ticket issuance, RPC and response
validation. Authentication, query shape, bounded body parsing and FastAPI handler
validation remain separately identifiable. Route names derive from registered
route templates, never request URLs. Live-wall/focus routes inherit the route
wrapper; their internal mux SQL/RPC phases are not separately instrumented by
this bounded source scope. Lease reads likewise retain handler-level outcomes.

The closed record schema contains only version, fixed route and phase enums,
completed phase enums, shared boolean, main/sub/unknown enum, wall/focus presence
booleans, bounded elapsed milliseconds, status, fixed failure code and a known
exception class label. Unknown exception classes are represented as `unexpected`.
No request identifier correlation is stored. The codec refuses unknown fields,
arbitrary strings, wrong types and records over 1024 bytes. The sink attempts at
most 128 records and 65536 bytes, including failed writer attempts. Concurrent
writes are serialized. Later records are silently omitted after either cap;
absence of a later record does not establish absence of its request.

Production configuration initializes the app-state sink to `None` and performs no
filesystem writes. The private runtime's `configure_api_debug(app, folder)` really
sets that sink, so records reach a file despite discarded console output. Either
explicit `WSO_TEST_LOCAL_MEDIA_API_DEBUG=1` with media mode enabled, or existing
media observation opt-in, enables it. The separate debug option does not enable
the formal media observer or inherit its reporting deadline. Invalid explicit
values (`0`, `true`, empty, or debug without media mode) are rejected. The API child
environment propagates this option even when observation is absent.

The target is fixed by the owned current-run folder:
`.superpowers/verification/local-device-browser-runtime/<current-owned-run>/media-api-debug.jsonl`.
There is no request-supplied path. Setup verifies the owned context name/location,
checks directory link boundaries, applies the existing reviewed private-directory
ACL helper and exclusively creates the file. Appends check links, regular-file
type, original file identity and the byte cap. Each file descriptor is closed
after its operation; no extra process, thread, worker or native owner is introduced.
Writer/setup failures leave the optional logger disabled or omit the record.
Even a callback `BaseException` cannot replace an original HTTP/authentication
failure. Native TRACE/bootstrap and media ownership/cancellation are unchanged.

Excluded data: credentials, cookies, tokens, session/device/native/channel/store
identifiers, request bodies, SDP, SQL, exception strings/messages/stacks and raw
media. The safe selector facts are booleans and trusted enums only.

## Executed verification

Initial causal RED reproduced three missing-evidence failures against existing
HTTP behavior: shared-mode 422, later RPC 502 and query rejection. A test-cookie
fixture error initially produced 500 for the RPC case; correcting the fixture to
the actual session-cookie name restored expected 502 before the missing-log RED.
The independent runtime opt-in/wiring tests then produced three expected RED
assertions before implementation. Additional privacy/concurrency/success controls
passed. Later RED caught a wall-template classification defect and a callback
KeyboardInterrupt replacing the original request failure; both were corrected.

Final command (exit 0):

```powershell
.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_media_diagnostics.py tests/tvt_parity/test_local_media_rpc_api.py tests/tvt_parity/test_local_media_mux_rpc_api.py tests/contract/test_local_media_debug_runtime.py tests/contract/test_local_device_browser_fixture.py -q
```

Result: **126 passed in 7.69s**. Coverage includes phase distinction, private
field/string rejection, unknown exception text/class omission, failing writers,
concurrent caps, successful response progress, independent/default-off flags,
fixed JSONL wiring and existing media API/runtime regressions. External
authorization/ticket dependencies are replaced only in focused diagnostic tests;
existing in-process mTLS tests exercise their established synthetic transport.

Scoped Ruff check and Ruff format check passed for the two API modules, runtime
and two added test files. Strict mypy passed for the two API modules. Initial
unused-import/format and return-cast static findings were corrected before the
final gates. No general whole-repository suite was run: this delegated execution
is restricted to focused/static gates; database/native/process acceptance remains
controller-owned. Runtime-wide strict mypy was not claimed.

No real recorder, native SDK, owned API/worker process, PostgreSQL fixture or
Chrome session was launched by this author. The temporary file test uses the real
guarded JSONL writer with a substitute ACL callback; it confirms fixed path and
file behavior, not a new Windows ACL execution receipt. Actual current-run file
capture and ACL enforcement still require the controller's reviewed execution.

## Frozen source evidence

| Path | SHA256 |
| --- | --- |
| `services/api/src/wso_api/tvt/local_media_diagnostics.py` | `8580c141a1f22f7eb33e4af18fcc68effd9e98c0ddb4a1343b0c4ee544e1b125` |
| `services/api/src/wso_api/tvt/local_media.py` | `a9b630c0af10789692ab4d3f7b0dc8d70361a87487b17d0d3bec0cb677328103` |
| `scripts/test-local-devices/runtime.py` | `4706807aebe53f3199d89df717a5a3894c7c51b9ae801e4cbbe68513f68d2210` |
| `tests/tvt_parity/test_local_media_diagnostics.py` | `c4dde0531f5b8555aaed21d3124a0247f5cf5eeca0e4e453c4b2582ae0ffb028` |
| `tests/contract/test_local_media_debug_runtime.py` | `02bf0a9b6d84628afb109b25786fe413372900039a0893488854d201f7dd1c3e` |

The runtime source closure includes the new module and focused tests. The root
must create new approvals/wrapper runtime hash after review; historical accepted
receipts and launchers are unchanged. No staging, commit or push was performed.

## Risks, priorities and open questions

The source gates establish bounded structural logging and unchanged focused HTTP
behavior. They do not establish real API file capture, corrected live playback,
twelve-camera acceptance or APK parity. The finite log cap can fill during a long
development run. Reopening/truncating/rotating a log is intentionally not provided
by this change; a new owned run obtains a fresh sink. Filesystem errors may omit
evidence, while original authentication and request results remain authoritative.

Next priority: independent source review, refreshed exact source closure, then a
controller-owned new run with the corrected frontend and optional debug flag.
Check actual mode/RPC progress and normal original-owner/DB/source/private cleanup.
Product question remaining: whether broader long-running production diagnostics
or mux-internal phase detail is desired. This implementation grants neither.

Update log: 2026-10-09 — bounded source implementation and 126 focused tests/static
gates completed; controller source review and actual file/browser acceptance open.

## Read-only follow-up: locating dedicated MAIN denial (2026-10-09)

The controller subsequently supplied run `1be34ba` evidence: the actual private
JSONL contains wall creation 200, substream start 200 (4250ms), focus reservation
200 (140ms), offer 200 (77ms), substream stop 200 (187ms), then MAIN start RPC
404 `LOCAL_DEVICE_DENIED` (141ms). Wall stop returned 404 and wall GET returned
200. No PLAYING request occurred between offer and stop. This confirms actual
API file capture in that supplied run; it does not identify the Core denial
branch. This author did not execute that run or read private run inputs.
The existing API logger independently passed C0/I0/M0 review per the current
canonical service report. Development source remained alive and frozen during
this follow-up; only read-only source inspection and this report update occurred.
Current source hashes were rechecked: service
`9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc`,
admission `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797`.
The runtime and both API hashes still match the frozen table above. Branch and
HEAD remain `codex/superlive-web-service` / `6436748`.

Inspection of `MuxMediaExecutor.start` (service source line 2191) establishes:
input/stop guard, ticket redemption, first `prepare_viewer`, stream dispatch,
`attach_dedicated`, executor current check and final public lease readback. The
dedicated method (line 1500) has these distinguishable boundaries:

| Proposed fixed phase | Existing operation or denial guard |
| --- | --- |
| `MAIN_SELECTION` | Second admission `prepare_viewer` |
| `MAIN_FOCUS_SELECT` | Pending FORWARD focus present, no existing dedicated entry, main stream |
| `MAIN_MASTER_MATCH` | Matching retained active master, former base viewer absent, selected channel matches focus |
| `MAIN_FOCUS_CURRENT` | Existing `current_focus` and focus expiry guard |
| `MAIN_CAPACITY` | Existing physical slot bound and original main reservation |
| `MAIN_PROVIDER_PREPARE` | Provider `prepare_dedicated` |
| `MAIN_RETAIN_LOCAL` | Existing attach-retirement/local-owner hook |
| `MAIN_REGISTER` | Admission `register_dedicated` |
| `MAIN_USE` | Admission `prepare_dedicated` (selection, committed use, credentials) |
| `MAIN_PRESTART_CURRENT` | Same selection, active original, focus current, retained dedicated, not stopping |
| `MAIN_PROVIDER_START` | Existing prepared original's `start` |
| `MAIN_POSTSTART_CURRENT` | Active, not stopping, focus unexpired and retained dedicated |
| `MAIN_ACTIVATE` | Admission `activate` |
| `MAIN_SETTLE` | Existing focus ATTACHED settlement |
| `MAIN_FINAL_CURRENT` | Admission current, not stopping, retained dedicated and active original |
| `START_FINAL_CURRENT` | Executor current after dedicated attachment |
| `START_VIEW` | Final public lease readback |

These constants are a proposal, not implemented fields. No predicate inside
these inspected start/dedicated/retain-focus methods requires PLAYING. The
presence of a pending focus reference contributes to retention. Consequently,
the missing PLAYING request alone does not demonstrate a timing fix or explain
which current/registration/use/local guard denied MAIN. The 141ms result is not
proof of a specific branch or of whether native preparation began.

The recommended smallest reliable port is an optional diagnostic callback on
`MuxMediaExecutor` (default `None`) and a private per-start trace passed as an
optional keyword to `attach_dedicated` (default `None`). Markers update bounded
in-memory phase state only; one closed terminal record is emitted after the
original success/failure and cleanup, outside coordinator locks. Capture the
failure phase before cleanup so retirement callbacks cannot overwrite it. Store
fixed code/status, known exception class labels and elapsed time, with no method
arguments, ticket/correlation/native identities, raw return values, credentials
or exception strings. The runtime alone supplies a bounded private sink with a
new fixed worker-side file such as `media-core-debug.jsonl` under the same owned
current-run evidence directory. Propagate independent API_DEBUG opt-in to the
worker explicitly. New approvals are required after source review and retirement
of the current development run.

Runtime-only wrappers can identify a failed admission/provider method, but cannot
distinguish local focus selection, master matching, prestart/poststart and final
denial guards inside `attach_dedicated`. Wrapping prepared originals or receipt
suppliers also expands the identity/custody review surface. Do not use native
TRACE/bootstrap changes or dynamic tracing. Do not rerun current/active predicates
for diagnostics, refactor their short-circuit evaluation, add SQL reads or flush
files while holding authority locks. Optional boolean facts should come only
from values already evaluated by the original logic; omitting them is the
minimal safe option.

Proposed causal verification, after retirement: reuse the existing inert
`forward_setup()` fixtures and inject failures independently at focus selection,
master matching, current-focus, dedicated register/use, prepared start, activation
and final-current. Establish RED missing phase evidence, then assert the exact
safe phase and unchanged original exception object/HTTP result and retirement
counts. Include default-off, callback `BaseException`, private-string rejection,
per-call concurrency isolation and record/byte caps. Preserve existing stop,
revocation, expiry and pending-focus/ack publication race tests. No new tests or
production source were executed or edited during this read-only proposal.

Update log: 2026-10-09 — controller-supplied actual JSONL outcome qualified;
dedicated MAIN denial remains unlocated; minimal Core trace ports proposed,
implementation and causal acceptance not claimed.

### Minimum-first decision: runtime-only structural exception frames

The controller selected a smaller first diagnostic step to preserve the reviewed
Core/native source hashes: structural exception-frame metadata is specifically
permitted under a closed whitelist. This supersedes the optional Core trace port
as the first implementation recommendation; that port remains a fallback.

Install one runtime-owned wrapper around the exact retained bound `executor.start`
immediately after constructing `MuxMediaExecutor` and before constructing
`LocalMediaWorker`. The wrapper calls the original exactly once with unchanged
arguments/cancellation/retirement callback, catches the same exception, reads
only approved structural metadata, isolates all diagnostic failures and uses
bare `raise`. Preserve the exact executor/coordinator/admission/provider objects;
do not wrap prepared originals, receipt issuers or native suppliers. No added
authority checks, process ownership or class-wide patches are needed.

Allow only fixed module/function labels selected from a source whitelist and
bounded source line integers, fixed public failure code/status and whitelisted
exception class. Do not output filenames/paths, source text, locals, arguments,
messages, repr, formatted tracebacks or arbitrary function/module names. Traverse
at most four exception objects and eight total traceback frames, rejecting
cycles. Access `__traceback__`, `__context__` and `__cause__` solely for that
bounded projection; discard frame/exception references after projection. A
known-source module map and strict record codec are required before any write.

Source viability: raw coordinator `raise _denied()` sites retain their exact
denial line in the exception traceback. Worker `start` normalizes inside its
exception handler (worker.py line 264); `from None` suppresses presentation but
does not erase Python's `__context__`. Capturing at executor entry avoids that
extra worker normalization layer. In contrast, admission `_boundary` catches
then raises its new failure *outside* the handler (local_admission.py line 66).
That original method/SQL exception context is lost. The proposed runtime wrapper
can still identify the caller operation from its source callsite and the
`checked` boundary, but cannot reconstruct an inner SQL cause that is absent.
This is a concrete diagnostic limit, not evidence of a SQL or timing defect.

An isolated `python -I -S -` semantic control used synthetic exceptions only and
confirmed both cases: outside-handler normalization has no context; inside
handler normalization retains context despite `from None`. Exit 0, two controls
passed. No application source body, database, SDK or browser was executed.

Proposed causal tests before implementation: exact coordinator denial frame,
admission normalized caller frame with lost inner context, worker preserved
context, unchanged exception identity and single original call, callback failure
isolation, successful return identity, forbidden filename/function/private-string
rejection, chain/frame/cycle bounds and concurrent record caps. Use synthetic or
existing inert fixture operations; actual failure classification still requires
a new controller-owned run after retirement/review/source-envelope refresh.

Update log: 2026-10-09 — runtime-only frame projection selected as minimum first
step; two isolated Python context controls passed; production source still frozen
and no frame logger implementation claimed.

## Implemented runtime-only exception projection and freeze (2026-10-09)

The controller confirmed run `1be34ba` retired before source changes: original
Node coordinator exit 1/reaped, Next exit 0, API and worker settled, context
removed and custody not retained. The exit 1 includes report-only approval drift
caused by the proposal append while that run was alive. Controller verification
found source bodies unchanged and owned DB cleanup/source equality. Preserve
that historical receipt as failed; the source logger review remains separate.
This author did not independently execute those retirement checks.

Current implementation adds `scripts/test-local-devices/core_debug.py` and
`tests/contract/test_local_media_core_debug.py`, changes the owned local-device
runtime and its debug wiring tests, and updates this report. The initial task's
borrowed-runtime filename was corrected by the controller; the borrowed
`scripts/test-tvt-account/runtime.py` is unchanged. Review baseline supplied by
the controller: tree `67dcbd2a74f8996c16909f42190242fcb4ed9bee`, HEAD `6436748`
with reviewed uncommitted Stage 1/2 and frontend changes. Core/admission/provider,
SQL, prepared originals, receipt suppliers, native bootstrap and API diagnostic
module are unchanged.

The new helper has a closed structural schema. It maps exact known source paths
to fixed module labels internally, accepts only explicit function allowlists,
and outputs bounded line integers. Paths, arbitrary names, source text, locals,
arguments, messages, repr and request/native/media data never enter the record.
Unknown frames are omitted and still count toward the inspection bound. At most
four exception objects and eight total frames are inspected; chain cycles and
bound exhaustion set a boolean truncation flag. Public failure code/status pairs
must match the existing table. Unknown exception types become `unexpected` /
`UNEXPECTED` / 500. A projected record is at most 2048 bytes; the synchronized
sink attempts at most 128 records and 65536 total bytes, including writer failures.
Only failures produce records. Success returns the original object unchanged.

With explicit debug opt-in, the worker's API_DEBUG flag survives child-environment
filtering. The owned context folder reaches shared composition. The exact retained
bound executor `start` is wrapped once before `LocalMediaWorker` construction; no
class-wide patch, alternate executor, native tracing or observer refactor is used.
The original call receives identical arguments, cancellation and retirement
callback. The wrapper emits the bounded projection, then uses bare raise with
the same exception object. Projection, callback, file setup/writing and diagnostic
clock failures are isolated. No frame or exception object is stored by the sink.

The runtime shares its existing private byte-writer implementation between two
closed filenames, preserving API behavior. The worker file is fixed to
`.superpowers/verification/local-device-browser-runtime/<owned-current-run>/media-core-debug.jsonl`.
It retains private ACL setup, exclusive creation, link guards, original file
identity, regular-file and byte bounds. Setup failure leaves the original bound
method intact. Exclusive creation prevents a second install from wrapping it
again. Default-off performs no helper loading, file creation or method change.
Both added helper/test paths are in the strict shared source closure.

### Fresh verification and limits

RED: six missing-helper assertions after converting an initial fixture setup
error into ordinary feature assertions; three missing runtime sink/worker-flag
assertions; an actual worker-to-composition test caught the missing owned-folder
argument; and a diagnostic-clock fault proved the original call could be blocked.
These controls passed after implementation/correction. Earlier KeyboardInterrupt
clock probes interrupted pytest and are not counted as completed tests.

Final focused command, exit 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py tests/contract/test_local_device_browser_fixture.py tests/tvt_parity/test_local_media_diagnostics.py tests/tvt_parity/test_local_media_mux_service.py -q
```

Result: **179 passed in 5.36s**. Coverage includes the actual inert coordinator
denial at `attach_dedicated` line 1509, admission context loss, inside-handler
context preservation, exact call/return/exception identity, callback/clock failure
isolation, closed private-field/function rejection, frame/chain/cycle bounds,
concurrent caps, fixed file wiring, default-off/setup failure, worker flag/folder
propagation and installation before media-worker construction. Existing mux
authority/retirement regressions passed. Tests replace external factories with
inert objects; no owned application/worker, DB, native SDK or browser was started.
Existing fixture tests include their established inert Node subprocess controls;
this is not actual media process acceptance.

Scoped Ruff check and format check passed for all four implementation/test files;
git diff whitespace check passed. Strict mypy passed for `core_debug.py` (one
typed helper). Initial Ruff style findings and mypy exception-field narrowing
were corrected. Runtime-wide strict typing and the general repository suite
were not run or claimed; scope remains focused/static. Private-file tests use
the real bounded byte writer with a substitute ACL callback, so fresh Windows
ACL/file capture remains a controller-owned actual gate.

### Frozen candidate hashes

| Path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_debug.py` | `582e511552961f1905ea42d3ed8472dc9153d0fa94028a3d9c0699fbc6e41a5b` |
| `scripts/test-local-devices/runtime.py` | `35c8a60453470cc72e25f9259a0c5c40ffb4a590a6fdbae9003f8ca1e17e8fc7` |
| `tests/contract/test_local_media_core_debug.py` | `d65d66412ce6d3f00524637e60fe1cbdd74e6cc0b46144a85160e08c022f9adc` |
| `tests/contract/test_local_media_debug_runtime.py` | `4937232a73af89bace8d58eaac03021d0942c57c4ef29f1ddeee33346bc525ff` |

Rechecked unchanged Core service `9d055101...`, admission `0a4162c6...` and API
diagnostic module `8580c141...` match their full hashes above. The earlier runtime
`4706807a...` table remains historical and does not approve this changed runtime.
No staging, commit, approval receipt edit or actual execution occurred.

Remaining next gate: independent scoped review, fresh immutable source envelope
and controller-owned reproduction. The admission normalizer's lost inner context
and the finite frame/record caps remain explicit limitations; no current-failure
cause or PLAYING/timing repair is inferred from source tests. Freeze this report
before creating the next source closure and do not append pinned reports while
its runtime is active. After normal retirement, record actual evidence and update
the report before the next approval. Broader Core phase callbacks remain a
fallback only if actual structural evidence cannot locate the denial.

Update log: 2026-10-09 — runtime-only structural capture implemented and frozen;
179 focused controls and scoped static gates passed; independent review and
actual reproduction pending.
