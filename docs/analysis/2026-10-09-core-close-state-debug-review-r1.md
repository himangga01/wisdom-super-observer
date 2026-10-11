# R194 Core close-state diagnostics: I1 source re-review R1

Analysis date: **2026-10-09, Asia/Seoul**. Independent scoped SPEC and QUALITY
re-review of the single R0 important finding.

**Verdict: C0 / I0 / M0. R0 I1 is resolved.** The acquired original publisher
thread remains in UNKNOWN custody before bootstrap identity is available.
Settlement and final flush require its positive original join and false
liveness. No new finding was identified in the three-path correction.
The accepted R0 assessment outside I1 remains qualified source evidence;
actual recorder/Chrome behavior is not established by this re-review.

## Authority, scope and frozen baseline

Read before review: shared `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
[AGENTS.md](../../AGENTS.md), current canonical
[service report](../service-analysis.md), the frozen
[R0 runtime review](2026-10-09-core-close-state-debug-review.md), and the appended
R1 section of the [author report](2026-10-09-core-close-state-debug.md).
The verification-before-completion workflow continued from R0. Read R0/R1 and
the author report before reusing this publisher; refresh affected evidence after
source changes or actual acceptance. The controller owns canonical bridges,
source/native closures and execution; this reviewer writes only this report.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Actual HEAD freshly remained `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, branch
`codex/superlive-web-service` previously verified in R0. Retained Stage 1/2/R193
working-tree changes remain the implementation baseline. Scoped status showed
the helper, its test, author report and R0 review remain untracked as before;
no source/test/index/HEAD edit was made by this reviewer.

Frozen package in
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/`:

- BASE snapshot tree `d3a54afefbf2664b1833edd9c4c034be4cbb22a2`.
- R1 candidate snapshot tree `31d57e085bf9976c315cfa678c38f195781b3d58`.
- `task-1942-review-r1.diff`, SHA256
  `a8e3ed324771fa5a69290c8cf86a0d30ab6d666d320f474362a1345891843cf3`.
- `task-1942-frozen-hashes-r1.json`, SHA256
  `d992bff6d28da7bb4f9763a45745fff20ca1c4c4d7087a27a7f38405b25a7d6c`.

The assigned delta is three paths, 157 insertions and four deletions. These
snapshot trees are not actual HEAD mutations. Fresh raw hashes and normalized
candidate blob contents matched all three paths:

| Path | R1 SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `8ba3e0cc9013c6e783f2b14288d190a7904dc1b1a9d0762edfeda14aea33efed` |
| `tests/contract/test_local_media_core_state_debug.py` | `c3bad0c0324658eb16e623ebfc7368f390e815e574755f852fa1f0052176b9dd` |
| `docs/analysis/2026-10-09-core-close-state-debug.md` | `470daf455e4f12909f4202f70b7235c2bcf0ea16c3460404410337c9b6a10416` |

Eleven retained raw pins independently matched: runtime `2140c035…`, runtime
tests `b3da8447…`, Core `9d055101…`, R193 admission `7e31d5cd…`, native helper
`106dde95…`, IPC `8571477a…`, provider `bbddd3e4…`, native tests `bf5c4bcc…`,
native review `89822cab…`, R0 runtime review `f875e419…` and R194 launcher
`307634df…`. Complete unchanged source hashes are recorded in R0 and the native
authority reports. R0 review remains exactly
`f875e419a0bb01141efcf3f8f65f5701d290d6c61a553c05ce7995bcc618c4de`;
the historical finding and evidence were not rewritten.

## Service purpose, correction and exact findings

The service supplies authorized local CCTV channels to Chrome. Core closes
original shared viewers before scheduled worker/peer retirement; R194 hooks
capture that synchronous decision and optional parent MAIN first-key state.
One runtime publisher drains bounded diagnostic bytes outside authority locks.
R1 changes only its thread startup/retirement accounting and final status.

| I1 requirement | R1 source and verification |
| --- | --- |
| Preserve ambiguous acquired startup | `start()` retains the original Thread, records `_start_attempted=True` and fixed `UNKNOWN` before invoking original start. Successful return becomes `RETURNED`; interrupted attempted start stays `UNKNOWN`. |
| Do not use absent identity/not-alive as non-acquisition proof | `close()` returns false immediately when an attempted original still has no identity. It does no final publish or summary in that window, and retains the same original object. |
| Require positive exact-original retirement | Once identity exists, the original join must return normally; its existing startup Event check remains in force. Live or exceptional joins retain custody. Only successful join plus false liveness becomes `RETIRED`, permitting final flush and `_final=True`. |
| Report qualified custody | Existing final-worker status gains only a boolean attempt flag and fixed `NOT_ATTEMPTED`/`UNKNOWN`/`RETURNED`/`RETIRED` outcome. The codecs and JSONL fields are unchanged. No private value enters these fields. |
| Preserve unaffected behavior | Independent AST comparison found changes only in helper `__init__`, `start`, `close` and `status`. Every other helper function, codec, wrapper, queue/budget and native drain body is identical to R0. All prior tests are identical; one causal test was appended. |

The new causal test uses a real Python Thread, delays its bootstrap before
identity publication, and interrupts the original startup Event wait after
platform acquisition. It confirms false close, UNKNOWN status, same retained
original and zero writes. Its `finally` restores the Event wait, releases the
barrier and joins the exact original even if the custody assertion fails.
After that original retires, close returns true with `RETIRED` and exactly one
summary. This directly covers R0's demonstrated failure window rather than
merely raising after `Thread.start()` has completed.

**Exact findings: none. C0 / I0 / M0.** The sole R0 I1 is resolved. No authority,
SQL, supplier, cleanup, timer, native callback or additional start operation was
introduced. Runtime default-off installation, before-monitor hook ordering,
normal server/native-before-publisher disposal, native callback wiring and the
two literal launcher reference check remain the separately verified R0 bytes.

## Fresh verification and actual limits

Executed with bytecode and pytest cache writes disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py::test_acquired_thread_without_bootstrap_identity_is_not_reported_retired tests/contract/test_local_media_core_state_debug.py::test_publisher_retains_thread_when_start_raises_after_acquisition_and_join_is_uncertain tests/contract/test_local_media_core_state_debug.py::test_publisher_is_retained_joined_and_file_io_never_runs_on_hook_thread tests/contract/test_local_media_core_state_runtime.py::test_worker_retains_publisher_until_server_native_and_admission_disposal -q -p no:cacheprovider
git diff --check d3a54afefbf2664b1833edd9c4c034be4cbb22a2 31d57e085bf9976c315cfa678c38f195781b3d58 -- scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_core_state_debug.py docs/analysis/2026-10-09-core-close-state-debug.md
```

Both commands exited **0**. Pytest: **4 passed in 0.19 s**, no failures/skips.
These cover acquired pre-bootstrap uncertainty, known-start/uncertain join,
normal joined publisher and original worker-disposal ordering. The real Python
threads are released and joined. No native child/SDK or database is involved.

An independent `.venv/Scripts/python.exe -B -` stdin check exited **0**: three
R1 raw/candidate blob matches, eleven unchanged pins, exact unchanged helper
AST outside the four named methods, exact prior test AST plus the one new
causal test, and unchanged R0 author-history prefix all passed.

The author's causal RED on R0 and **62 scoped passes in 1.26 s**, Ruff/format on
two changed Python files and helper mypy are author evidence. R0's reviewer
61-test/preservation/privacy/native-bound results remain dated prior evidence;
this narrow R1 did not rerun those unchanged scopes or a broad suite.

Only this report was written. No source/test/index/HEAD mutation, database/SQL,
native child/Job, SDK, recorder, browser, private input/approval, launcher run,
staging, commit, push or nested agent was used. No new Windows ACL, parent MAIN,
SUB liveness, Chrome, twelve-camera or APK acceptance is claimed.

## Remaining qualifications and next gate

An interrupted attempted start that never publishes identity remains UNKNOWN
indefinitely; this intentionally delays retirement rather than guessing
non-acquisition. A blocking writer or uncertain join can also delay retained
cleanup. This source correction removes the demonstrated premature settlement;
it does not guarantee that every diagnostic fault permits immediate shutdown.
Finite projection/budget/omission and parent-only measurement qualifications
from R0 and the native report continue to apply.

Priority P1: the controller records this R1 acceptance, refreshes the affected
public/native/source closures and immutable runtime authority, then performs the
authorized bounded original-recorder measurement with normal retirement.
Actual first SUB Core close origin and MAIN first-key/IPC cause remain unresolved.
No TTL or authority policy change is selected by this re-review.

Update log: 2026-10-09 — scoped R1 C0/I0/M0; I1 resolved with acquired real-Thread
causal control, three other targeted custody/order controls, exact frozen hashes
and unchanged-body checks. R0 preserved. Freeze this report after its final
hash is supplied; actual source/native closure and hardware gates remain
controller-owned.
