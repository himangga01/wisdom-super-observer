# R200 bounded deep shared-read exception projection

Analysis date: 2026-10-10 22:43, Asia/Seoul. Implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`,
with preserved uncommitted Stage1/2 and reviewed R193-R199 source. Helper baseline
SHA256 `7e4fdde538d47ff3d5dbb75b8efc5c4c95b872735eaa392904d06a135c385aaf`;
read-test baseline `70cb67c4954674f3f4a1d5acdcc8730d8b0b931de6d940df9c29d64b9709e03a`.

Read before reuse with the [service report](../service-analysis.md),
[R199 author report](2026-10-10-shared-read-inner-debug.md),
[R199 review](2026-10-10-shared-read-inner-debug-review.md), and
[cold SUB diagnosis](2026-10-10-cold-sub-startup-diagnosis.md). Root owns
canonical links, combined review and fresh execution. Refresh after source
review or actual owned measurement, preserving original runtime evidence.

## Evidence and change

The service supplies authenticated TVT media through Core, native owners and
media/API workers. Root supplied run05f2 READ_EXCEPTION: Core read2452/provider
read1244/parent pump1356/fail786, then context pump1345/codec feed332 with
truncated=true. `feed332` calls `_feed`; its rejecting condition was omitted.
This author did not inspect private run files. Root subsequently confirmed
normal original retirement: coordinator0/reaped, context removed, source
unchanged/private0 and original42986 exit0. Source edits began only after that
explicit confirmation. Retirement evidence remains Root-owned.

Only the runtime helper and existing read test change. READ projection now
inspects at most **32 traceback frames total across up to four chain nodes**.
Unknown/helper frames consume that same finite budget. Output retains at most
eight allowlisted primitive frames: the most recent/deepest tail of bounded
outer-to-inner traversal across chains. Dropping an earlier selected frame sets
truncated=true, as do exhausted inspection/chain bounds or cycles. Thus output
reduction is honest even when all 32 inspected frames have been fully visited.

Exact active-reader eligibility remains independent of output selection: the
eight-caller scan must find actual Core read code/source, and the exception's
own traceback must contain that same active frame. It stays eligible even if
the outer reader's exported frame is displaced by deeper selected frames.
HEARTBEAT continues its existing eight-traceback-frame inspection and output.

Read codec mapping preserves `_feed`/`_deliver` and adds actual helper names
`_move_fragment`, `_peek_span`, `_consume_span`, `_count`, `accept` on the exact
mux-codec source, plus `_integer`, `_guid`, `_raw_timestamp` on exact
`packages/core/src/wso_core/tvt/local_live.py`. Existing close/current maps stay
separate. Fields and closed codec remain unchanged: checked public code/status
or UNEXPECTED, fixed module/function/line/chain and truncation. No messages,
repr, locals, args, arbitrary types/IDs/paths, private media or credentials.

The retained queue still stores only validated canonical bytes, with unchanged
127 events plus summary/2,048-byte rows/65,536-byte run cap, failure/omission
counters, publisher ownership and startup/join custody. No SQL, authority,
callback, native IO, frame processing or cleanup invocation was added. Original
close/error/result semantics and default-off runtime wiring are unchanged.
Background consumer exception tracing is deferred: an original native fence
wrapper would exceed this existing runtime-hook ownership. No BG event is claimed.

## Causal verification

New RED: **2 failed, 10 passed** before production changes. Actual Core read,
an inert handle with 12 unknown wrappers, and actual `MultiplexLiveCodec.feed`
generation rejection reached `_feed:351`; the old projection exported only Core
read and omitted that rejecting line. Another control showed the old selection
kept seven shallow allowlisted recursive frames and lost the deepest raise.

GREEN captures actual `_feed:351`, chain1, before original viewer close; retained
output selects the deepest eight and marks output reduction. A separate actual
codec leaf behind 40 unknown wrappers remains omitted with truncation, proving
the finite READ bound. Existing READ unknown-frame test uses depth40 instead
of12 to exercise the updated bound. Original-reader, normal Stop, cleanup/fault,
privacy, heartbeat and queue/publisher controls remain green.

Final affected gate: **72 passed in 0.98 seconds**, exit0:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py -q -p no:cacheprovider --tb=short
```

One test-import ordering warning was corrected after that run; final Ruff
check/format-check passed. One-helper mypy passed:

```powershell
.venv/Scripts/python.exe -B -m ruff check scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_read_debug.py
.venv/Scripts/python.exe -B -m ruff format --check scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_read_debug.py
.venv/Scripts/python.exe -B -m mypy --follow-imports=silent scripts/test-local-devices/core_state_debug.py
```

## Final hashes and limits

| Source | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `9da4554fa730e0970f07686f6f04473a12046667f438c11919aa45d3d067981b` |
| `tests/contract/test_local_media_read_debug.py` | `384f4536b9813c90746a9f58b02f32db19856d99236faffaea436841b938906d` |

Unknown or earlier frames can still be absent; eight output rows represent the
tail of the inspected traversal, not an unbounded traceback or guaranteed root
cause. Per-chain/global inspection and queue saturation can omit deeper evidence.
R196's summary-write accounting caveat remains unchanged. Positive original
reader identity does not establish real admission, codec or hardware acceptance.

No native/Core/provider/runtime.py/receipt/pin/private/context modification,
DB/hardware/browser operation, broad test, commit or extra agent was performed.
Root retains broad7816 RED authority. Priority is narrow source review, fresh
immutable closure and actual replay to locate the rejecting codec condition.
Stable shared playback, native background failure attribution, twelve-camera
and APK acceptance remain open. No new product decision is needed here.

Update log: 2026-10-10, bounded READ inspection/output repair with causal tests.
This is source evidence, not an actual repaired-playback claim.
