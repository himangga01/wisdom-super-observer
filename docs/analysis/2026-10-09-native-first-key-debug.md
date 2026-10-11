# R194 native first-key diagnostics

Analysis date: **2026-10-09, Asia/Seoul**. Scope: bounded optional diagnostics
on the exact dedicated MAIN parent authority and original prepared startup.
**Source implemented and inert controls passed; source review, runtime wiring,
fresh approval receipts and actual recorder execution remain controller gates.**

## Authority and baseline

Read before work: shared `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
[AGENTS.md](../../AGENTS.md), the last 250 lines of the canonical
[service analysis](../service-analysis.md), the
[NO_SIGNAL diagnosis](2026-10-09-dedicated-main-no-signal-diagnosis.md), R193
[startup author report](2026-10-09-dedicated-main-startup-fix.md),
[R0 review](2026-10-09-dedicated-main-startup-review.md),
[R1 fixture review](2026-10-09-dedicated-main-startup-review-r1.md), and
[native pin review](2026-10-09-dedicated-main-native-pin-review.md).
The diagnosis raw SHA256 freshly matched
`de49cf4a96545224e6e2a15224b522bdfed93c36e64cf9c399c3ad48a976aa36`.
Debugging, test-driven development and verification skills were applied.

Implementation authority is
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, freshly checked HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial Git status contained extensive
retained Stage 1/2 modifications and untracked source/tests/reports. The primary
checkout does not contain that implementation. This agent owns only the two
parent/provider files, new helper, focused test and this author report.
Controller owns AGENTS/service bridges and acceptance/receipt refresh; the
runtime owner has a disjoint `runtime.py`/Core diagnostic scope.

Controller evidence from retired e9: MAIN RPC returned NO_SIGNAL after about
14 seconds; the existing parent accepted a matching 1281 ACK before its
10-second first-key deadline. ACK-only, non-keyframe and late-keyframe paths
shared this outcome. R193 source C0/I0/M0 and owned SQL eight-case acceptance
remain prior evidence; this author ran neither hardware nor PostgreSQL.
Controller confirms all original runs retired and only PostgreSQL remains.

## Purpose, implementation and contract

The service presents authorized recorder channels in Chrome. Dedicated MAIN
retains a separate original native owner, custodian and legacy IPC parent.
Worker validation and parent validation are distinct boundaries. This change
measures only the state already held by that exact parent; it adds no worker
protocol, native callback, secondary codec or authority query.

`NativeLocalMuxProvider` gains one keyword argument:

```python
first_key_debug: Callable[[NativeFirstKeyRecord], None] | None = None
```

`PreparedDedicatedMain.start` creates a default-off
`LiveParentAuthority(..., diagnostics=callback_is_present)` and emits one
record in its outer `finally`, after original run or failed-start cleanup
attempt and after exiting `custodian.constructing()`. It uses the original
authority object and never wraps prepared owners, suppliers or issuers.
The callback executes outside authority/custodian locks; `BaseException`
is isolated. Repeated native close does not emit another record. Failure
cleanup can retain uncertain custody under existing rules; emission itself
does not certify cleanup completed or issue a receipt.

`LiveParentAuthority.deny` captures the first immutable primitive snapshot
before readiness/FIFO/codec state is cleared. Startup success captures the
first snapshot before callback delivery. Subsequent close preserves the
first terminal snapshot. Completion of an already executing authority check
may amend only its numeric timing/count fields after deny; it never reads
cleared codec state. Parent instrumentation reads buffer lengths, existing
codec counters and structural fragment integers without reading/copying
their media bytes, headers or identity fields.

| Fixed record group | Implemented meaning |
| --- | --- |
| ACK/readiness | Accepted open ACK boolean, command 0/1281/1285, parent ready and fixed parent outcome enum. |
| Relative timing | ACK, first parsed frame and first parsed key milliseconds relative to this authority's construction; absent values are NULL. `first_key_late` compares the diagnostic observation with the existing first-key cutoff. |
| Parsed media | Parsed frame/non-key/key counts increment before the original first-frame check, so a key parsed at the cutoff is visible even though the original denies it. These count parent parser results, not decoded/browser frames. |
| IPC progress | Received message/envelope/byte counts, successful decision count, next existing IPC sequence and last completed fixed purpose/category. |
| Codec structure | Existing cumulative received bytes/parsed packets, current partial buffer and assembly lengths, fragment pending/count/next/total byte bounds. Packet count includes codec ACK/heartbeat packets. |
| Parent retention | Current queued frame count and retained bytes before terminal clear. |
| Existing check latency | `authority_check_calls` and `authority_check_elapsed_max_ms` measure the enclosing original `ParentAuthority.check`, including its guards and terminal deny work. They are not exact supplier-only/SQL timing. |
| Worker qualification | `worker_observed` is always false and rejected by the encoder if changed to true. No worker counters are inferred. |

The enabled check implementation delegates the exact original
`super().check(current)` once. It mirrors no authority guards, wraps no supplier
and issues no extra current call. Diagnostic clock failure still runs that
original call and preserves its return or exception. Default-off delegates
directly to the original check and creates no tracker/record. Existing first-key
deadline, ordering, code/status mapping, cancellation, startup predicate,
postactivation authority, BUSY exact-receipt readback and original retirement
behavior remain present.

The frozen helper import/API for the runtime owner:

```python
from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

sink = NativeFirstKeySink()  # only under the runtime diagnostic flag
provider = NativeLocalMuxProvider(..., first_key_debug=sink)
lines: tuple[bytes, ...] = sink.drain()  # outside lifecycle/authority locks
dropped: int = sink.dropped
```

`NativeFirstKeyRecord` is a frozen slots dataclass. `encode_first_key_record`
accepts only its exact type, validates each primitive before JSON encoding,
and emits one ASCII newline-terminated fixed JSON event `native_first_key`,
version 1, at most 2048 bytes. No dictionary, arbitrary string, bool-as-number,
negative/oversized number or observed-worker claim is accepted. Strings are
closed enums; ACK commands are closed. Counts, sizes and relative milliseconds
saturate at **2^31-1**. No raw media, credentials, GUID/registration/session/
generation, arbitrary exception/message/header, filename or absolute wall time
is retained/emitted. The tracker retains only primitive values and its record;
its temporary snapshot argument does not retain the authority or codec.

`NativeFirstKeySink` stores only canonical bytes under a short private lock,
at most **128 records and 64 KiB**. Overflow drops new records and increments
a saturated dropped count. `drain()` returns/clears the byte queue under that
lock; file I/O belongs to the separate runtime publisher. The callback contract
and raw source hashes were sent to the runtime owner after source freeze.

## Fresh verification

Causal RED before production changes:

```powershell
& .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/contract/test_native_first_key_debug.py -k original_parent_readiness
```

Exit 1: **five intended failures**, because `diagnostics` was absent from the
actual parent constructor; four deselected. New tests then drove the real parent
setup/pump/check/parser path with invented ACK/media/fragments, an in-memory
connection and fake monotonic clock. The prepared tests use actual R193 fake-SQL
composition and actual custody/legacy-pipe methods with the pipe constructor
replaced by two in-memory connections. No pipe, process, Job, DLL or DB connection
is created. Initial test-only fixture mistakes (ACK declared size and the
20-second request-budget maximum) were corrected; they demonstrated no product
defect. Synthetic custody now uses the real retained legacy-pipe method rather
than an unretained owner-service assignment.

Final executed commands:

```powershell
& .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/contract/test_native_first_key_debug.py tests/contract/test_dedicated_main_startup_authority.py
& .venv/Scripts/python.exe -B -m ruff check services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py tests/contract/test_native_first_key_debug.py
& .venv/Scripts/python.exe -B -m ruff format --check services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py tests/contract/test_native_first_key_debug.py
& .venv/Scripts/python.exe -B -m mypy --follow-imports=silent services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py
git diff --check -- services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py
```

- **39 passed**, no failures/skips, pytest **0.20 s**: 15 new first-key/closed
  record controls plus 24 existing R193 authority/BUSY controls.
- New controls distinguish ACK-only/non-key/late-key/ready/denied, preserve
  partial+fragment state across close, check closed primitive privacy, immutable
  records and saturation, enforce count/byte queue bounds, and verify default-off
  behavior with identical existing current calls/progress.
- Actual prepared source controls verify exactly one callback outside authority
  and custodian locks after run/failed cleanup, same original `KeyboardInterrupt`
  identity despite a diagnostic `SystemExit`, unchanged NO_SIGNAL 504 and no
  callback after repeated close. Diagnostic snapshot and clock `BaseException`
  faults preserve original deny/check behavior.
- **Ruff four paths, format four paths and strict mypy three paths passed**;
  scoped diff whitespace check passed. Explicit S110 suppression is restricted
  to diagnostic faults whose exception text must not be logged.
- No database, native SDK, native/OS original, browser, live input, staging,
  commit/index/reset/push or broad suite was run. Python bytecode and pytest
  cache writes were disabled. Runtime wiring and publisher I/O are not claimed
  by these tests.

## Frozen source and retained protected hashes

| Changed/new path | SHA256 |
| --- | --- |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py` | `106dde9503a1207640fbb88b7322f404440e3787aabdd645268f0fa772359b47` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py` | `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339` |
| `tests/contract/test_native_first_key_debug.py` | `bf5c4bcc635215c0afc99deecb319d840c0be0a0b677158bd285a74da9b42ba9` |

Pre-change IPC was `52109c4df410fbafc37170a78a2d5c76ce24870dfd0156b7a137ea54ce5aaf85`;
pre-change provider was `f48373ce7861106a72901165177fede2d3da31a0a7ff9d658a2c16d29398cf33`.
Fresh protected raw hashes still match the NO_SIGNAL diagnosis baseline:
codec `e38c21e3b54109293add89c5602ab5650c19c77dddf6248c821b0da6045737b3`,
Windows provider `32cd642a8e2ec74a7afefdaae14c365ad89a016db5ac21337e291bd5c4dae2cd`,
worker `cba9407fcde2956a3dc48c0596bd2a74a51b101bfd9f4553c83a01f91170cdaf`,
legacy live provider `cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c`,
ownership `2d097f9091be2d44856cd047cb6e5a94dd29362a067222ae3121b45a62a34f26`,
R193 admission `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999`.
No runtime, receipt, bootstrap or SQL file was edited by this agent.

## Interpretation, risks and remaining gates

Priority P1: scoped combined diagnostic source review, fresh public/native
LIVE pins and immutable runtime envelope, then one bounded original recorder
MAIN reproduction with normal original cleanup. This instrumentation is not a
playback fix and does not authorize changed execution under old receipts.
The helper is imported by parent IPC; the controller must include its bytes in
the refreshed source/native bootstrap closure without loosening that closure.

ACK with zero parent media can establish only this parent's observations. It
cannot establish recorder silence or worker callback/forwarding absence.
Non-keyframes identify lack of an admitted first key among parsed parent data;
late key and check timing help locate scheduling delay but do not measure exact
worker arrival. Retained partial data supports incomplete parent assembly.
Malformed input may make the unchanged codec close itself inside `feed` before
parent deny, so its cleared partial state is unavailable in that failure path.
An already parsed later item in one feed tuple that the original loop never
visits is not counted. Relative times are rounded/saturated observations, not
changes to cutoff comparisons; instrumentation itself adds bounded work.

Open measurement questions: which media/fragment/key/progress/check pattern the
actual MAIN parent sees, and whether parent-only evidence selects a further
worker measurement. No product decision is needed for this user-requested log
measurement. Real repaired MAIN/Chrome, SUB liveness, return/reconnect, sustained
multichannel/twelve-camera performance and APK parity remain separate open gates.

Update log: 2026-10-09 — R194 optional parent-first-key record/sink/callback
implemented, causal RED/GREEN and 39 focused/static checks passed, API frozen
for disjoint runtime wiring. Source review and actual hardware remain unexecuted
by this author; controller owns canonical report/AGENTS updates.
