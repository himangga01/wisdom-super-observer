# R196 bounded inner heartbeat diagnostics

Analysis date: 2026-10-10 21:34, Asia/Seoul.

## Scope and baseline

The service connects authenticated web clients to privately registered TVT
recorders through Core admission/coordinator and original native/media owners.
This author task adds runtime-only evidence for the exception that initiates
the Core heartbeat fence. It does not fix the heartbeat or orphaned replacement
grant defect, establish playback acceptance, or settle the previous runtime.

Source authority is the implementation worktree on `codex/superlive-web-service`,
HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with preserved uncommitted
Stage1/2/R193/R194 changes. Parent supplied review-tree baseline:
`3f320722e4fa23856e5553f3e875d92e2adf5505`. This is a review-tree reference,
not the Git HEAD or a newly verified complete closure. Initial status had many
modified/untracked implementation and documentation paths; they were preserved.

Read before implementation: project AGENTS, shared analysis policy,
[canonical service report](../service-analysis.md), and the
[heartbeat exception proposal](2026-10-09-wall-heartbeat-refresh-exception-proposal.md).
The previous 340-path source approval remains historical. Root owns the new
immutable source closure, independent review, and canonical cross-link updates.

## Implemented behavior

Only `scripts/test-local-devices/core_state_debug.py` changes production code.
The existing `_fence` wrapper first checks the immediate caller against the
actual `DeviceEpochCoordinator.heartbeat` code object and exact Core source
path. On that caller only, `sys.exception()` obtains the handled original
exception before cleanup. A `HEARTBEAT_EXCEPTION` record is enqueued before the
existing `MASTER_FENCE` entry and original `_fence` invocation. The original
method runs once with identical args/kwargs, and its return/error is preserved.
If cleanup raises, that original cleanup error remains the propagated error.

The closed heartbeat event extends the existing schema with fixed `code`,
`status`, and `chain_count`. Frames contain only allowlisted module/function,
bounded line and chain ordinal. Public `LocalDeviceFailure` code/status pairs
require exact primitive types and membership in the existing fixed map;
unexpected/malformed failures become `UNEXPECTED`/500/`unexpected`.

The heartbeat traceback allowlist covers:

- Core: `heartbeat`, `_check_replacement`.
- Admission: `refresh_grant`, `_refresh_current_grant`, `_record`, `_observe`, `_sql`.
- Provider: `refresh_grants`, `authority_operation`, `replace_grant`, `heartbeat`.
- Mux IPC: `renew`, `_rpc`, `_check`, `heartbeat`.
- Admission boundary: `checked`.

Projection visits at most four exception-chain nodes and eight traceback frames
in total across those nodes. Unknown/helper frames consume that same frame
budget. Cause is preferred over context, suppressed context can remain visible,
and cycles/remaining nodes or frames set `truncated`. Original BaseException
descriptors bypass arbitrary subclass attribute hooks for traceback/cause/context.
Messages, repr, locals, arguments, arbitrary class names, IDs, source paths,
credentials, SQL rows and media are never exported. Exception/frame references
remain local to synchronous projection and never enter the retained queue.

The queue retains only closed-codec validated canonical ASCII JSON bytes. It
uses the original caps: at most 127 accepted event records plus one summary,
2,048 bytes per record, and 65,536 bytes total including reserved summary space.
The existing retained publisher, start/join custody, failure isolation,
native diagnostic budget and runtime default-off opt-in are unchanged. No
writer/file IO occurs in the hook or custodian locks. No additional authority,
SQL, supplier, refresh, cleanup or native protected callback invocation was added.
The old close/current callchain map now explicitly iterates its original
function map, so adding heartbeat-only source labels cannot break old records.

Counters remain shared with close/current events. Accepted/written/omitted/
diagnostic_failures/suppressed and the final summary are unchanged. Summary
`written` is the count before attempting the summary itself; a failure writing
that final record can only be seen in retained owner status. Queue saturation
may omit the heartbeat event; absence alone cannot rule out a heartbeat failure.
Projection failures increment diagnostics failures and preserve original cleanup.

## Verification and causal evidence

All commands used the existing `.venv/Scripts/python.exe -B`; tests used
`-p no:cacheprovider`. No dependency installation was needed.

1. Initial new-test run: seven failures/one pass. One failure was a test fixture
   expectation corrected from CLOSED to QUARANTINED: its fake original owner
   intentionally cannot settle cleanup. No production change was made for it.
2. Corrected causal RED: six failures/two passes. Actual Core heartbeat refresh
   tests failed because `HEARTBEAT_EXCEPTION` was missing before original fence;
   codec/projection tests failed because the feature was absent.
3. Initial GREEN: eight new tests passed. Existing diagnostic/runtime regression
   gate including those tests: 45 passed.
4. Added a preservation control for heartbeat-only mux IPC source labels.
   RED was `KeyError: mux_ipc` in the old close callchain; restricting its source
   map to original function labels made the same control GREEN.
5. Final affected gate: **198 passed in 2.87 seconds**, exit 0:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_media_mux_service.py tests/contract/test_final_mux_handoff_refresh.py -q -p no:cacheprovider --tb=short
```

The new file contains 23 cases. It covers actual coordinator heartbeat/cleanup,
public/unexpected/malformed failures, pre-fence queue ordering, original exception
and callback preservation, unrelated handled errors, original cleanup error,
diagnostic BaseException isolation, finite chains/cycles/unknown frames,
allowlisted exact source/function mapping, wrong-source omission, closed codec,
canonical-byte queue and shared event/byte/summary accounting. Provider/IPC
mapping controls compile closed inert functions with controlled traceback
filenames; they do not execute real provider/IPC/native operations.

Static checks passed:

```powershell
.venv/Scripts/python.exe -B -m ruff format --check scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_heartbeat_debug.py
.venv/Scripts/python.exe -B -m ruff check scripts/test-local-devices/core_state_debug.py scripts/test-local-devices/core_debug.py tests/contract/test_local_media_heartbeat_debug.py
.venv/Scripts/python.exe -B -m mypy --follow-imports=silent scripts/test-local-devices/core_state_debug.py
```

The first static pass caught inert-test exec lint and six descriptor typing
errors; fixed fixture-specific annotations and explicit native descriptor casts
passed the rerun. Mypy checks one changed source with imports followed silently,
not the entire workspace. Full project suite is deferred to Root's source gate.
No DB engine/connection, real recorder, SDK child, browser or listener was used
by this task. No commit, pin/receipt/credential/ignore-rule edit, source changes
outside ownership, or extra agent was made.

## Source hashes and handoff

SHA256 hashes of authored production/test files after the final gate:

| Path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `11834469b0ede78c6616aa1a8cdcf1fbcad11c41e32684485c25dd562fcad336` |
| `tests/contract/test_local_media_heartbeat_debug.py` | `063fe339cc97c075f081ff43b484b02a5b9ef03a18d58cd84b3bba731002acd4` |

Initial `core_state_debug.py` SHA256 was
`8ba3e0cc9013c6e783f2b14288d190a7904dc1b1a9d0762edfeda14aea33efed`.
Startup `core_debug.py` remains unchanged with SHA256
`582e511552961f1905ea42d3ed8472dc9153d0fa94028a3d9c0699fbc6e41a5b`.
Runtime wiring remains unchanged with SHA256
`2140c0352294f13e9ad387c8482c1d92451b8ad8e636ba3697981ba9f4960008`.

Priority: Root creates/reviews a new immutable closure and obtains a new owned
runtime trace. The actual historical heartbeat inner exception remains unknown.
After new evidence, distinguish the initiating refresh/replacement/IPC boundary
from later authority-denial consequences. The conditional replacement-retirement
defect remains a separate fix. Shutdown-loop counts were considered and explicitly
deferred by Root to preserve the narrow existing-hook task. No new product choice
is required for these default-off diagnostics; full service completion, stable
MAIN/return and twelve-camera acceptance remain open in the service report.

Update log: 2026-10-10, authored bounded runtime measurement, causal tests, final
affected verification and privacy/custody limits. Refresh this report after
independent review or actual owned runtime evidence.
