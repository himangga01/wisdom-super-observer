# R201 fixed rejected mux command measurement

2026-10-10 22:58, Asia/Seoul. Worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with preserved uncommitted Stage1/2
and reviewed R193-R200. Baseline SHA256: codec
`07584407d8ec628eb0216a514b9f696ecde8f5af9ede51ce9f165cefd591af2b`,
runtime helper `9da4554fa730e0970f07686f6f04473a12046667f438c11919aa45d3d067981b`.

Read with [service report](../service-analysis.md),
[deep-read author report](2026-10-10-shared-read-deep-debug.md) and the cold
startup diagnosis before reuse; refresh after source review or owned replay.
Root owns canonical links, frozen combined closure, review and actual execution.

## Purpose and source change

The service streams authenticated recorder media through Core, original native
owners and media/API workers. Root supplies retired e0b6 deep READ_EXCEPTION at
codec `_parse:621`: rejection when command is not65537 or route is not0/2.
Root confirms original46651 exit0, source367 unchanged, private0 and context
removed. This author did not inspect private run files or reproduce that runtime.
The numeric command/route are still needed before selecting a repair.

Only the existing `_parse:621` rejection now raises
`UnsupportedMuxPacket(command, route)`. The diagnostic exception is an exact
`UnsupportedLive` subtype with the same inherited fixed message/base catches;
it retains only parsed uint32 command and byte route. Its constructor rejects
non-int/bool/out-of-range values. The class is appended to the module so existing
parser/deep-feed line references remain stable. All other rejections, wire
acceptance, bounds and authority callbacks remain unchanged. This does not
accept any new notification or packet variant.

Only runtime READ projection recognizes this exact subtype within the existing
maximum four-node cause/context traversal. Valid primitive attributes add
optional paired `wire_command`/`wire_route` fields. Exact types and ranges are
checked again; a subtype spoof, missing/malformed attributes or out-of-chain
facts are omitted. The closed byte codec requires both fields together, only on
VIEWER_READ_EXCEPTION, and rejects bool/negative/overflow. Other records and
HEARTBEAT retain their previous fields and behavior.

The exact active-reader code/source/frame eligibility, READ32 inspected frames/
eight deepest output frames, HEARTBEAT8, truncation, counters, 127 events plus
summary, 2,048-byte row/65,536-byte run caps and retained publisher custody remain.
Queue entries are validated canonical bytes, with no exception/frame references.
No frame locals, messages/repr, arbitrary types/IDs/paths, media bytes, credentials
or SQL facts are inspected/exported. No added SQL, authority, callback, IO or
cleanup call occurs. Original close/result/error semantics are preserved.

## Causal verification

RED: **14 failed**, before implementation. Actual codec feeds rejected synthetic
2561/2562/2563/0/uint32-max packets, then actual Core read catch reached cleanup,
but the pre-close event lacked command/route. Other controls showed the subtype
and fixed validation were absent. GREEN: R201/R200/heartbeat49 cases passed.

Final affected gate **173 passed in1.14s**, exit0:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_command_debug.py tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_live_mux.py -q -p no:cacheprovider --tb=short
```

The 14 new cases cover unchanged rejection/closed codec and pre-close numeric
queue evidence, target parse invalid-route branch, earlier preflight rejection
and malformed-short packet preservation, constructor bounds, closed schema,
forged subclasses/mutated/missing attributes, cycle/four-chain limits, and
HEARTBEAT exclusion. Existing codec tests cover supported packet behavior.
Synthetic command values are not evidence of the actual e0b6 opcode.

Two-source mypy passed. After that pytest run, import ordering and pairwise
iteration lint were corrected; final Ruff check/format-check passed:

```powershell
.venv/Scripts/python.exe -B -m ruff check packages/core/src/wso_core/tvt/local_live_mux.py scripts/test-local-devices/core_state_debug.py tests/contract/test_mux_command_debug.py
.venv/Scripts/python.exe -B -m ruff format --check packages/core/src/wso_core/tvt/local_live_mux.py scripts/test-local-devices/core_state_debug.py tests/contract/test_mux_command_debug.py
.venv/Scripts/python.exe -B -m mypy --follow-imports=silent packages/core/src/wso_core/tvt/local_live_mux.py scripts/test-local-devices/core_state_debug.py
```

## Frozen candidate and limits

| Source | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_live_mux.py` | `bbccd5496bf7866bc0990dc1cd56ced24a8662baf7bf580093c6a987d07fd5fd` |
| `scripts/test-local-devices/core_state_debug.py` | `67bef6eb988049bfc011f1d8a8ef233251db3e05eb25aa33b53f9b350a053e78` |
| `tests/contract/test_mux_command_debug.py` | `f3a8c6bf5572f066761fe3ab81207a75725dda3f6046448241c31459ce83cb97` |

No hardware/DB/browser, broad tests, native/provider/runtime wiring/private/
receipt/pin edits, commit or extra agent. Prior full7816 RED authority remains
Root-owned. Only the target parse rejection has typed facts; earlier unsupported
conditions remain generic. Chain/frame/queue bounds can omit evidence, and
R196's summary-write accounting limit remains unchanged.

Priority is narrow independent review, fresh metadata/closure and owned runtime
measurement. An APK/legacy notification interception gap is a separate hypothesis;
this author makes no actual opcode or benign-notification claim. No new product
decision is required for diagnostics. Stable shared playback/twelve-camera/APK
acceptance and any packet-policy repair remain open.

Update log: 2026-10-10, authored fixed numeric rejection evidence and causal
tests. Source verification does not establish actual repaired playback.
