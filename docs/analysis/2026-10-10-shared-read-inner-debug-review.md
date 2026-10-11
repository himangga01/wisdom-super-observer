# R199 shared read inner diagnostic review

2026-10-10, Asia/Seoul. Independent **SPEC PASS, QUALITY PASS; C0/I0/M0**.
This verdict covers the frozen runtime measurement source and focused inert
tests. It does not establish the actual cold SUB initiating exception or
repaired shared playback.

## Scope and baseline

The service delivers authenticated TVT video through Core admission/coordinator,
original native owners and media/API workers. This change observes an initiating
shared read exception before existing viewer cleanup removes its authority.

Worktree: `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, preserving extensive uncommitted
Stage1/2/R193-R197 source/reports. Exact two-path diff uses base review tree
`b829c5d5aaba3072f88df56b6fa3c47b4b817caa` and candidate tree
`df40fadb871a44c789ded968528fb21153ae180d`; these are comparison references,
not a new branch commit. Baseline helper SHA was `11834469...`.

Read shared analysis policy, current AGENTS/service retired0601 evidence,
[R196 review](2026-10-10-heartbeat-inner-debug-review.md), exact R199 brief/diff/
hash manifest, actual Core read/close path, finalized
[author report](2026-10-10-shared-read-inner-debug.md) and local handoff, and
[cold SUB diagnosis](2026-10-10-cold-sub-startup-diagnosis.md). R198 native/provider
authoring is concurrent and disjoint; its behavior was not evaluated or changed.

## Requirement and quality findings

- The existing `_close_viewer` wrapper scans at most eight synchronous callers,
  including unknown/helper frames. It requires the actual
  `MuxMediaExecutor.read_mux_frames.__code__` and exact normalized Core path.
  `sys.exception()` is measured before original cleanup. Projection additionally
  requires that same active reader frame in the handled exception's own
  traceback, excluding unrelated held errors during normal Stop, including
  Stop nested inside an active read.
- The wrapper queues fixed `VIEWER_READ_EXCEPTION` before original VIEWER_CLOSE
  and invokes the captured close once with unchanged args/kwargs/result/error.
  Original read and cleanup exception identities, callback identities and
  diagnostic failure isolation are verified by controls. No extra read/release,
  SQL, authority, supplier or cleanup operation is added.
- Shared projection preserves four-chain/eight-total-traceback-frame limits,
  cause/context handling, cycle/truncation reporting and native BaseException
  descriptor access. Only fixed public code/status or UNEXPECTED/500 and
  allowlisted module/function/line/chain primitives escape projection.
  Heartbeat and read allowlists remain separate; old close/current source
  mapping is preserved.
- The closed event codec validates the failure fields, exact primitive types,
  frame allowlist/ordinal, bounded state/counters and 2,048-byte canonical ASCII
  JSON. The queue retains bytes only, never exception/frame references. Existing
  127 events plus summary, 65,536-byte cap, omission/failure counters, publisher
  thread custody and default-off runtime wiring remain unchanged. The hook
  performs no writer/filesystem IO or custodian-lock acquisition for measurement.

No material defect was identified. Tests exercise actual Core read catch with
inert original ports, including public/unexpected/invalid-batch failures,
pre-close ordering, normal Stop exclusion, projection/capture faults and cleanup
errors. These controls establish runtime hook semantics, not native behavior.

## Fresh verification and frozen source

Reviewer executed:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py -q -p no:cacheprovider --tb=short
```

**69 passed in 0.98 seconds, exit 0.** This includes all 23 R196 heartbeat cases
and the nine new read cases. The author's RED5/4, GREEN, Ruff and one-helper mypy
results were read as author evidence; they were not independently replayed.
No full suite was repeated. The prior 7,816-case broad RED and 257 failure/error
cases remain qualified canonical evidence; this review does not supersede them.

Independent raw SHA256 checks matched the frozen manifest:

| Path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `7e4fdde538d47ff3d5dbb75b8efc5c4c95b872735eaa392904d06a135c385aaf` |
| `tests/contract/test_local_media_read_debug.py` | `70cb67c4954674f3f4a1d5acdcc8730d8b0b931de6d940df9c29d64b9709e03a` |

## Limits and continuation

Finite caller/traceback budgets can prevent positive identification or omit
deep frames; queue saturation can omit an event. Missing evidence cannot rule
out a read fault. State is explicitly non-atomic. The existing final-summary
written count excludes its own attempted write; its failure is visible in owner
status. If batch release raises during the read catch, that active exception is
projected and its bounded context may carry the earlier read failure.

No private/context/credential/receipt data, hardware, SDK child, DB, browser or
process action was used. No source/native/provider/Core/runtime/pin/ignore edit,
commit, extra agent or optional broad test was made. Only this portable review
was written; Root owns AGENTS/service cross-links and fresh combined closure.

Priority is Root's immutable approval and owned trace, then causal interpretation
of cold SUB/transition/parked MAIN and normal original retirement. Actual cold
read cause, native terminal cause, stable duration, twelve-camera load and APK
comparison remain open. No new product choice is needed for default-off tracing.

Update log: 2026-10-10, frozen R199 SPEC+QUALITY review and independent 69-case
verification C0/I0/M0. Read with the author/diagnosis before trace changes and
refresh after new source or actual owned runtime evidence.
