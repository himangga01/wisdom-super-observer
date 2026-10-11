# R199 initiating shared read exception diagnostics

Analysis date: 2026-10-10 22:11, Asia/Seoul. Worktree:
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`,
with preserved uncommitted Stage1/2 and reviewed R193-R197 changes. Author
baseline `core_state_debug.py` SHA256:
`11834469b0ede78c6616aa1a8cdcf1fbcad11c41e32684485c25dd562fcad336`.
R198 native/provider authoring is concurrent and disjoint. Root owns the fresh
combined snapshot, independent review, AGENTS/service links and actual replay.

Read before reuse with the [service report](../service-analysis.md),
[R196 author report](2026-10-10-heartbeat-inner-debug.md),
[R196 review](2026-10-10-heartbeat-inner-debug-review.md), and
[cold SUB diagnosis](2026-10-10-cold-sub-startup-diagnosis.md). Refresh after
review/source changes or owned runtime execution; preserve retired0601 history.

## Purpose and implementation

The service streams authenticated recorder media through Core, original native
owners and media/API workers. Two retired0601 cold SUB attempts reached frame
input but not decode. Existing VIEWER_CLOSE measured cleanup's origin; the
initiating read exception remained unlogged. These are historical canonical
findings, not an author replay. R199 adds default-off runtime measurement only.

The existing `_close_viewer` hook scans at most eight synchronous caller frames,
including unknown/helper frames. It requires the exact actual
`MuxMediaExecutor.read_mux_frames.__code__` and normalized Core source path.
Before original cleanup, `sys.exception()` supplies the handled exception.
Its bounded **own** traceback must contain the same active reader frame.
This extra identity check prevents unrelated held exceptions during normal Stop,
including Stop nested inside an active read, from becoming read failures.

The new fixed `VIEWER_READ_EXCEPTION` event precedes original VIEWER_CLOSE and
cleanup. Its code/status/type, frames/chain/truncation, non-atomic pre-close
state, elapsed time and counters use R196's checked encoding. Shared projection
uses separate closed heartbeat/read function maps; heartbeat behavior and old
close/current mapping remain preserved. Read mappings cover Core read/limits/
current/lease; provider read/current/matches/serialized IO/authority/heartbeat;
parent pump/read/check/RPC/fail/accept/operation; and codec feed/drain/check/
slot/authority/delivery/preflight/parse/media validation paths.

Projection inspects at most four exception-chain nodes and eight traceback
frames total across them. Unknown frames consume that budget. Cause is preferred
to context; cycles and unvisited frames/nodes mark truncation. Public failures
require exact primitive LocalDeviceFailure code/status from the existing fixed
map; other failures become UNEXPECTED/500/unexpected. Original BaseException
descriptors avoid arbitrary subclass traceback/cause/context hooks.

The queue retains only validated canonical ASCII JSON bytes, never exception,
traceback or frame references. It keeps the existing 127 events plus one final
summary, 2,048 bytes per row and 65,536-byte total cap. No filesystem IO is added
to the hook or custodian locks. Original `_close_viewer` runs once with unchanged
args/kwargs/result/error, including original cleanup errors; diagnostic failures
increment existing failure accounting and do not alter cleanup. No extra SQL,
authority, supplier, frame-read/release, protected callback or cleanup call is
made. Runtime opt-in, NativeSink behavior and retained publisher custody are
unchanged. Only runtime helper and one new test file change source.

## Executed verification

Causal RED: **5 failed, 4 passed**, before implementation. Actual Core read catch
failed because the queue began with VIEWER_CLOSE instead of the initiating
exception; projection cases failed because the new helper was absent. GREEN:
new nine cases plus the existing 23 heartbeat cases passed. Final affected gate:
**69 passed in 1.00 seconds, exit 0**:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py -q -p no:cacheprovider --tb=short
```

New controls exercise actual Core read catch with inert original ports for
public/unexpected failures and invalid returned batch; pre-close ordering,
original error/callback preservation, normal Stop under held exceptions outside
and inside read, diagnostic projection/capture failure, original cleanup error,
finite chain/unknown-frame limits, closed read-specific codec and byte-only queue.
Existing tests verify heartbeat behavior, queue/summary accounting and publisher
custody. No real native/provider operation is inferred from these controls.

Static gates passed:

```powershell
.venv/Scripts/python.exe -B -m ruff format scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_read_debug.py
.venv/Scripts/python.exe -B -m ruff check scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_read_debug.py
.venv/Scripts/python.exe -B -m mypy --follow-imports=silent scripts/test-local-devices/core_state_debug.py
```

Mypy checks the changed helper with imports followed silently. Full suite was
not repeated: Root retains the prior 7,816-case RED/257 failure-error authority.
No hardware, SDK child, DB, browser, listener, private/context/receipt/pin edit,
commit, extra agent, native/Core/provider/runtime wiring edit occurred.

## Hashes, limits and continuation

| Authored source | Final SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `7e4fdde538d47ff3d5dbb75b8efc5c4c95b872735eaa392904d06a135c385aaf` |
| `tests/contract/test_local_media_read_debug.py` | `70cb67c4954674f3f4a1d5acdcc8730d8b0b931de6d940df9c29d64b9709e03a` |

The finalized R196 source hash above is historical baseline, superseded by this
new candidate. Read R196's summary caveat: written excludes the summary's own
attempt, whose write failure is visible only in owner status. Queue saturation
can omit an event; caller/traceback budgets can prevent positive identification
or omit deep frames. Missing evidence cannot rule out an initiating read fault.
If the active handled failure is batch-release failure, its finite context may
contain the earlier read error. No messages, repr, locals, arguments, arbitrary
types/IDs/paths, credentials, SQL rows or media are exported.

Priority is independent combined source review and a fresh immutable owned
runtime trace. Actual cold SUB initiating error, exact native terminal cause,
stable shared playback and twelve-camera/APK acceptance remain open. No new
product decision is required for this measurement. R198's retained consumer is
a separate source repair and is not claimed to fix cold active-reader failure.

Update log: 2026-10-10, authored pre-close runtime measurement, causal TDD,
affected/static verification and frozen candidate source hashes. Source approval
does not establish actual playback or runtime retirement.
