# Runtime-owned structural core debug source review

Review date: 2026-10-09 (Asia/Seoul).
Review scope: R192 runtime-only exception projection and the single development
launcher runtime-reference update. This is an independent SPEC and QUALITY review.

## Scope, authority and source baseline

Read before review: shared `C:/Users/강지혜/.agents/analysis-policy.md`, this
worktree's `AGENTS.md`, latest `docs/service-analysis.md`, Stage 2 execution
ledger, `docs/analysis/2026-10-09-live-api-debug-logging.md`, the prior API logger
review, and the historical development-launcher source review. The Superpowers
requesting-code-review/code-reviewer template and verification guidance were used.

Implementation authority:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, actual Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Fresh Git status confirms extensive
retained Stage 1/2 source, tests and reports, with the concurrent reviewed frontend
work. Those changes were present before this review and are not this scope.

Frozen BASE `67dcbd2a74f8996c16909f42190242fcb4ed9bee` and candidate
`225f9786f273fd6276ac3f1fed50835a912cf3bb` were independently confirmed as Git
**tree** objects, not commit HEAD values. Their full difference has ten files
because it includes concurrent documentation. The supplied scoped package
`task-1921-review-r0.diff` has five paths, 950 insertions and 46 deletions:
runtime, the new helper, two focused test files and the existing logger report.
Its raw SHA256 is
`59ede3bff98f053d28ea2d421b59227496eb04ab1496981fc227cd74fc5daa39`.
The raw manifest SHA256 is
`683747e16b59e64c5b8d9bd576525dd1786d923d78928c7a8404b69d4d4b436d`.

All five current raw hashes match the supplied freeze. For each path,
`git hash-object --path` also matches the candidate tree's blob, independently
confirming the working files correspond to the review candidate under Git's
configured text filters.

| Path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/runtime.py` | `35c8a60453470cc72e25f9259a0c5c40ffb4a590a6fdbae9003f8ca1e17e8fc7` |
| `scripts/test-local-devices/core_debug.py` | `582e511552961f1905ea42d3ed8472dc9153d0fa94028a3d9c0699fbc6e41a5b` |
| `tests/contract/test_local_media_core_debug.py` | `d65d66412ce6d3f00524637e60fe1cbdd74e6cc0b46144a85160e08c022f9adc` |
| `tests/contract/test_local_media_debug_runtime.py` | `4937232a73af89bace8d58eaac03021d0942c57c4ef29f1ddeee33346bc525ff` |
| `docs/analysis/2026-10-09-live-api-debug-logging.md` | `5d60d18598c6da22d31fbeb9f924ce1b2a3a2138f6e2e893bbfc6c2d0f5b6362` |

The scoped tree difference is empty for Core service/admission, API diagnostic
module, native bridge and media service source. Fresh raw protected hashes are:

| Protected source | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797` |
| `services/api/src/wso_api/tvt/local_media_diagnostics.py` | `8580c141a1f22f7eb33e4af18fcc68effd9e98c0ddb4a1343b0c4ee544e1b125` |
| `scripts/test-tvt-account/runtime.py` | `1d961908c917d66f2da4e111c4dd1eddf46d1c130d8a542957c92b3944a0ba97` |
| `scripts/test-local-devices/server.mjs` | `598280a1abcb095252e7755181559e52dda213ae1964dcde38e2a076197e6d72` |

The controller owns canonical AGENTS/service/handoff bridges, new immutable
approvals and actual execution. The only project file written by this reviewer
is this report; no source, index, HEAD/ref, DB, private input, native owner or
browser was edited or launched. Tests use temporary offline fixtures.

## Service purpose and implemented behavior

The local CCTV service separates browser/API control from the shared media
worker and its retained Core/admission/provider owners. The latest canonical
report supplies historical run `1be34ba`: wall, substream start, focus, offer and
substream stop returned 200, followed by MAIN start RPC 404
`LOCAL_DEVICE_DENIED`. No PLAYING request was observed between offer and stop.
The denial branch remains unlocated; missing PLAYING alone is not an established
cause. These real-run and retirement observations were supplied by the
controller, not executed by this reviewer. The historical development run
remains failed, with source-body equality and report-only approval drift.

R192 captures the original executor failure at the runtime boundary. It adds a
closed structural codec and a synchronized bounded byte sink in
`scripts/test-local-devices/core_debug.py`. Shared composition installs its
wrapper on the exact retained executor instance before constructing the media
worker. The worker receives the explicit debug opt-in and exact owned context
folder. The existing guarded private byte writer is shared by the API and Core
files through two fixed filenames. No Core phase port or authority behavior is
added.

## Strengths and requirements assessment

- **Exact call and ownership:** `runtime.py:328` retains `executor.start` as a
  bound original and changes only that instance's callable. Composition at
  `runtime.py:953` keeps the same admission, coordinator, executor, source and
  worker owners and installs the wrapper before worker construction.
  `core_debug.py:187` calls the original exactly once, passes the same arguments
  and keyword values, returns the same result, and uses bare `raise` at line 211
  for the original exception. The diff introduces no authority rechecks, SQL
  reads, alternate owners, prepared-original wrappers, supplier changes or
  bootstrap/native tracing changes.
- **Optional failure isolation:** clock acquisition and failure projection,
  callback and bounded sink operations catch `BaseException`. Optional Core
  setup catches `BaseException` before a successful assignment. Setup failure
  preserves the original bound method. Invalid explicit debug values remain the
  previously reviewed configuration error; the flag validator is unchanged.
- **Privacy:** `core_debug.py:15` maps six exact source paths internally to
  fixed module labels. Only the explicit per-module function allowlists can
  appear in records. The codec at line 75 requires exact dictionaries and
  primitive types, bounded source lines and fixed public failure code/status
  pairs. Known `LocalDeviceFailure` is the only named exception class;
  other types become `unexpected`. No filenames, source, frame locals,
  call arguments, messages, repr, formatted traceback, arbitrary class names,
  identifiers, tokens, credentials, SQL or media enter serialized output.
  The sink stores bytes and numeric counters, never exception or frame objects.
- **Traversal and output bounds:** the projection at `core_debug.py:120`
  inspects at most four exception objects and eight total traceback frames.
  Unknown frames consume the same inspection budget. Exception identity cycles
  terminate with `truncated=true`; bounded exhaustion is also explicit.
  The exact schema permits at most eight projected frames and 2048 bytes per
  record. The sink at line 216 serializes writes and reserves count/bytes before
  calling the writer, including failed attempts, allowing at most 128 attempts
  and 65536 attempted bytes.
- **Fixed file custody:** `runtime.py:252` restricts filenames to
  `media-api-debug.jsonl` and `media-core-debug.jsonl`. The Core target derives
  solely from the current owned context under the established evidence root.
  The extracted writer preserves the existing private-directory ACL helper,
  absolute context/run-name/parent and link guards, exclusive creation, regular
  file check, original device/inode identity and actual 65536-byte bound.
  Descriptors close in `finally`. The per-run exclusive file prevents repeated
  configuration from wrapping the executor again in the actual composition.
- **Independent opt-in:** the explicit API_DEBUG flag works with OBSERVE absent
  and is forwarded to the worker. Default-off avoids helper loading, file
  creation and callable replacement. Existing observation opt-in can still
  enable debugging, as already specified by the API logger; explicit debug
  does not create or reset a formal observer.
- **Useful causal controls:** the new tests exercise the real inert coordinator
  denial at `attach_dedicated` line 1509, original call/result/exception identity,
  failed clocks and callbacks, inside-handler context retention, outside-handler
  admission normalization, chain/cycle/frame bounds, forbidden private fields
  and function names, concurrent caps and actual temporary file wiring. Runtime
  controls cover worker flag/context propagation and installation order.

## Development launcher reference update

Fresh hashes were independently checked in the ignored execution workspace:

| Artifact | SHA256 |
| --- | --- |
| Previously reviewed `run-media-development-20261009.py` | `c03895ff3105d7d411fd8a92921f9609a9be1f3087e992bfc3485964cb05fdf1` |
| Fresh `run-media-development-r192-20261009.py` | `7550ad67bac19eff2965927a55627fe6319e5dfdaff3cbbeba489405e13f7ec4` |
| Unchanged original `run-media-browser-stage2-owned.py` | `5c980d3f2769c258c6374b9caa1bf411820437ae95029bb0f9cdd4c76ca3c1fe` |

`git diff --no-index` shows only `RUNTIME_SHA` changing from the historical
`4706807a...` to current `35c8a604...`. A raw-byte comparison independently
confirms replacing exactly that old hash once produces the entire fresh file.
The new reference agrees with the frozen runtime hash. No launcher behavior or
original acceptance helper changes accompany this delta. Exit 1 from the diff
command denotes the displayed difference, not an execution failure. The prior
development review's explicit development duration, original-owner/source/private
gates, absent formal observer and default-profile Chrome limitations continue
to apply. This check grants no actual startup or browser acceptance.

## Issues

### Critical

None established.

### Important

None established.

### Minor

None established.

No material privacy or control-flow change beyond the authorized diagnostic
wrapper was found in the frozen scope. No correction is required by this review.

## Fresh verification

Independent reviewer commands used `PYTHONDONTWRITEBYTECODE=1`; pytest's cache
provider and Ruff's cache were disabled. All commands completed.

```powershell
.venv/Scripts/python.exe -m pytest tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_media_diagnostics.py -q -p no:cacheprovider
```

Result: **26 passed in 0.68s**, exit 0. This includes the new Core/runtime
controls and the prior API logger controls, appropriate to the writer extraction.
The fresh result confirms original failure preservation, privacy bounds, bounded
concurrency, file wiring and independent/default-off flags in offline fixtures.

```powershell
.venv/Scripts/python.exe -m ruff check --no-cache scripts/test-local-devices/core_debug.py scripts/test-local-devices/runtime.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py
.venv/Scripts/python.exe -m ruff format --check --no-cache scripts/test-local-devices/core_debug.py scripts/test-local-devices/runtime.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py
```

Results: **All checks passed** and **4 files already formatted**, both exit 0.
Scoped `git diff --check` between BASE/candidate also exited 0 with no output.
Read-only status/HEAD/tree/diff, SHA256 and candidate-blob checks passed as
described above. No frozen source/report changed during these checks.

The author's 179 focused passes, causal RED controls and strict helper mypy are
recorded author evidence. This reviewer did not recreate those historical RED
runs or rerun the 179 selection or mypy. No broad test suite was necessary for
the remaining review scope, and none is claimed.

## Risks, actual limits and priorities

The admission `_boundary` raises its replacement outside its handler
(`local_admission.py:66`); lost inner exception context cannot be reconstructed
by this logger. Capturing before the worker's separate normalization avoids its
extra boundary but does not restore absent SQL causes. Total frame bounds can
omit a deeper source frame. Finite record/byte caps and isolated filesystem
failures can omit later evidence. A missing row or empty/truncated frame list
does not establish that no failure occurred or identify its cause.

Temporary file controls substitute the private-directory ACL callback. They
confirm guarded file wiring, not an independently executed real Windows ACL
receipt. No real application/worker, DB fixture, SDK, recorder, browser, private
input or network acceptance was started by this reviewer. Controller-supplied
retirement and PostgreSQL-only status were not independently reproduced here.
The 404 cause and whether actual structural frames suffice remain open.

Priority: preserve these frozen bytes, bridge this review into the canonical
AGENTS/service/handoff workflow, then obtain a fresh immutable source envelope
and controller-owned reproduction. Record current-run file/ACL evidence and
original-owner retirement separately. Do not append any pinned report while
that runtime is active; update reports only after retirement and before the
next closure. No PLAYING or timing workaround follows from this review.

## Declined to judge

- Real MAIN-denial cause and a playback repair: actual failure reproduction is
  controller-owned; structural logger source/tests do not locate that run's guard.
- Core/admission/SQL/native/prepared/supplier ownership redesign: these bodies
  are protected and unchanged; introducing such changes is outside R192.
- Full frontend behavior, broader Stage 1/2 composition and APK parity: separate
  reviewed work and unexecuted acceptance gates outside this five-path package.
- Full launcher behavior, isolated helper Chrome, formal observer deadlines and
  acceptance helper compatibility: the authorized launcher delta is one runtime
  reference; their historical review and explicit limitations remain authority.
- Production log rotation, correlation and broader phase diagnostics: not part
  of this current-run bounded diagnostic request; a later product decision.
- Actual Windows ACL/process/DB/SDK/recorder/Chrome and twelve-camera acceptance:
  offline source review cannot grant those execution outcomes.

## Assessment

**SPEC: compliant. QUALITY: approved. C0 / I0 / M0.**

**Ready for the controller's fresh closure/run gate: yes.** The exact retained
start wrapper preserves original call/result/failure behavior and serializes
only closed bounded metadata; its integration and unchanged writer controls
passed independent focused verification. This verdict approves the scoped
source and launcher reference, not actual playback, normal run retirement,
twelve-camera acceptance, commit, merge or publication.

Update log: 2026-10-09 — independent frozen five-path and one-reference review
completed; 26 focused controls and scoped static checks passed; no actionable
finding. This report is final for the candidate and must remain frozen through
any runtime that pins it.
