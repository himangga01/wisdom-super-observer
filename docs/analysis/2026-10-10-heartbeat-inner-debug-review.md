# R196 inner heartbeat diagnostic review

Analysis date: 2026-10-10, Asia/Seoul. Independent SPEC and QUALITY review.

## Verdict and scope

**SPEC: PASS. QUALITY: PASS. Findings: C0/I0/M0.** This verdict approves the
frozen runtime diagnostic source scope. It does not establish the historical
initiating heartbeat exception, repair of grant retirement, original runtime
cleanup, or real MAIN/SUB/twelve-camera playback acceptance.

The service connects authenticated browser clients to registered TVT recorders
through Core admission/coordinator, original native owners, and media/API
workers. R196 measures the handled maintenance exception before the existing
Core fence cleans up; it changes no authority or playback policy.

Worktree: `codex/superlive-web-service`, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial Git status contained extensive
pre-existing modified/untracked Stage1/2 and R193/R194 source and reports. This
review preserved them. The exact two-path review diff uses base tree
`3f320722e4fa23856e5553f3e875d92e2adf5505` and candidate tree
`712b1b5bde076923110410e43137b2a038dbcafa`; these are review references, not a
new branch HEAD or complete production closure.

Read the project AGENTS, shared analysis policy, canonical service report,
[heartbeat proposal](2026-10-09-wall-heartbeat-refresh-exception-proposal.md),
task brief, exact frozen diff/hash manifest, existing state diagnostic source,
actual Core heartbeat, runtime opt-in wiring, and finalized
[author report](2026-10-10-heartbeat-inner-debug.md) plus local execution handoff.

## Requirements checked

| Requirement | Source and independent evidence |
| --- | --- |
| Pre-fence measurement only for actual heartbeat caller | `core_state_debug.py:733` compares the immediate caller's code object with actual `DeviceEpochCoordinator.heartbeat.__code__` and its exact normalized Core source path. Actual heartbeat has its single fence call inside the refresh catch; `sys.exception()` reads that handled failure before original cleanup. An unrelated handled error produces no heartbeat event. |
| Preserve original call and exceptions | `core_state_debug.py:770` still calls the captured original once with unchanged args/kwargs. New projection/capture failure is isolated. Tests establish original refresh-error identity, cleanup-error identity, pre-fence ordering, and unchanged protected binding/receipt callback identities. |
| Add no authority/native IO or lock-held writer work | The addition reads traceback/code objects and retained primitive state, then enqueues checked bytes. It adds no SQL, refresh, supplier, cleanup or protected provider call. Writer work remains exclusively in existing publication, outside sink queue and coordinator/admission state locks. Actual heartbeat invokes its fence after exiting its state lock. |
| Finite safe projection | `core_state_debug.py:267` visits at most four chain nodes and eight total traceback frames. Unknown frames consume the same budget, cycles/remaining frames or nodes mark truncation, and native BaseException descriptors avoid arbitrary subclass traceback/cause/context hooks. Only fixed module/function/line/chain and validated public code/status or UNEXPECTED/500 are returned. |
| Closed canonical-byte queue and original custody | `checked_record` validates exact fields, primitive types, public code/status pairs, frame allowlists/ordinals and 2,048-byte output. Capture retains only ASCII JSON bytes. Existing 127 events plus summary, 65,536-byte cap, retained publisher start/join and failure/omission counters remain intact. No exception/frame enters the queue. |
| Preserve old source-map behavior | `project_callchain` maps only original `FUNCTIONS` labels. Adding heartbeat-only `mux_ipc`/`local_admission` source labels cannot trigger a lookup failure in old close/current tracing. The dedicated inert preservation control passes. |
| Preserve existing default-off runtime behavior | Runtime configuration still returns no diagnostic owner unless the existing debug opt-in is enabled. Runtime wiring and startup diagnostic source are outside this two-path diff. |

No material defect or unresolved source requirement was identified. New tests
exercise actual Core heartbeat with inert admission/provider ports, including
public, unexpected and malformed failures. Provider/IPC allowlist controls use
closed compiled inert functions with controlled traceback filenames. They verify
projection, not real provider/native authority execution.

## Verification

Reviewer independently executed:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py -q -p no:cacheprovider --tb=short
```

Result: **60 passed in 0.80 seconds, exit 0**. This is the affected diagnostic/
runtime gate; no broader optional test was run. The author separately reports
198 affected cases and Ruff/mypy passing, plus causal RED then GREEN. Those
historical author executions were read, not replayed or relabeled as reviewer
executions. The reviewer did not alter source to reproduce RED.

Git HEAD/status and `Get-FileHash -Algorithm SHA256` were checked independently.
Current source and finalized reports match the supplied frozen hashes:

| Artifact | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `11834469b0ede78c6616aa1a8cdcf1fbcad11c41e32684485c25dd562fcad336` |
| `tests/contract/test_local_media_heartbeat_debug.py` | `063fe339cc97c075f081ff43b484b02a5b9ef03a18d58cd84b3bba731002acd4` |
| Portable author report | `d944ebfbf0dcd628a1fa6edb322a8534ce07be0853febc94273d441d738b9767` |
| Local author handoff | `b9ded6f82f5fa5b764fe2a06c500bab3f636990c950c04bd0889c901b8e3618d` |
| `task-196-review-r0.diff` | `5974c13bb712e0be382d96626137b0ab807625ef780bcb3f8ae16a128d1d1d55` |
| `task-196-frozen-hashes-r0.json` | `410dbf29259c13590b687f2cfa0a83ac607a9596eb8a93f5eff8b2f08080c0c0` |

## Limits, risks and continuation

Queue saturation may omit the heartbeat event. Unknown/helper frames can exhaust
the shared eight-frame budget before an inner allowlisted frame, with honest
truncation. Cause is preferred to context; suppressed context may still be
projected safely. Missing event/frame evidence cannot rule out an initiating
failure. Non-atomic state snapshots are explicitly labeled. The final summary's
written count excludes its own attempted write; a failure writing that summary
is visible in retained owner status. These are documented diagnostic limits,
not source defects within the required finite measurement contract.

No private runtime data, credentials, frame payloads or arbitrary exception text
were inspected/exported. No real DB, SDK child, recorder, browser, listener or
native hardware operation was invoked. No source/pin/receipt/ignore change,
commit, extra agent, process termination or broad test was made. The only file
written by this reviewer is this portable review.

Root owns AGENTS/service cross-links and the new immutable closure. Parent
instructs that actual execution follows the separately reviewed R197 shutdown
fix and chain reissue. Then record the owned runtime heartbeat trace, distinguish
the initiating exception from consequent denial, and update the canonical
service evidence. Conditional replacement-grant retirement repair remains
separate. No new product choice is needed for default-off measurement; stable
shared playback, full duration, twelve-camera acceptance and APK comparison
remain open product/acceptance questions in the canonical service report.

Update log: 2026-10-10, frozen R196 SPEC+QUALITY review, independent 60-case
verification and source/report hash checks; C0/I0/M0. Read this report with the
author/proposal before future tracing changes and refresh after new source or
actual owned runtime evidence.
