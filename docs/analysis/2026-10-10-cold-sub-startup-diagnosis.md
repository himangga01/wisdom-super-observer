# Cold SUB startup: initiating read exception boundary

Analysis date: 2026-10-10, Asia/Seoul. Source authority: implementation worktree
`codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained Stage1/2/R193/R194 and
R196/R197. The initial tree is modified. Run `0601a12a2c004191aa9ab215a13a1988`
is retired; R198 authoring proceeds concurrently. This investigation changes
only this new report and does not edit the author's native/provider sources.

Read before reuse with [service analysis](../service-analysis.md),
[parked ingress diagnosis](2026-10-10-parked-ingress-causal-diagnosis.md),
[R196 diagnostic review](2026-10-10-heartbeat-inner-debug-review.md), and
[R197 retirement review](2026-10-10-replacement-transport-retirement-review.md).
Root owns AGENTS/service cross-links. Update after a reviewed read-exception
probe, new source evidence or actual acceptance, preserving run0601 history.

## Finding and actual evidence

**Cold SUB first fails within active frame reading; the initiating read error
is unlogged.** The recorded authority renewal failure is downstream of viewer
close. A parked-only consumer cannot be claimed to repair this active-reader
failure. It addresses a separately proven conditional source mechanism.

The service streams authenticated recorder media through Core admission/native
owners and viewer-local compressed ingress/decoder/authority threads. Shared
SUB reads pass through MuxSourceFactory, MuxFrameSource, MuxMediaExecutor,
MuxSlotViewer and the original mux IPC parent. MAIN uses a separate native
session while retaining the base epoch.

Direct safe projection of run0601 `media-observation.json` gives:

| Source attempt | Recorded milestones, milliseconds since source creation | First recorded failure |
| --- | --- | --- |
| 1, SUB | first_adapter_packet 4171; no decoded/binding milestone | authority_renew / denied at 5327 |
| 2, SUB | first_adapter_packet 3328; format transition started once; no decoded/binding milestone | authority_renew / **failure** at 4062 |
| 3, SUB bootstrap | first_adapter_packet 3202; first_decoded_frame 4640; binding_ready 7187; peer_created 7202 | peer / explicit_close at 7468 |
| 4, MAIN | first_adapter_packet 5203; first_decoded_frame and binding_ready 6766; peer_connected 7093 | source_current / denied at 12718 |

Source2's saved reason is `failure`, not `denied`. Observer omissions and
observation_failures are zero; stop_requested is true. Root supplies the first
SUB HTTP 503 latency of 6843 ms; this analysis did not join API identifiers.

Safe Core-state projection shows first two VIEWER_CLOSE entries with master
ACTIVE/refreshing=false and caller frames `MuxMediaExecutor.close:2555` and
`MuxSourceFactory.read:52`. The first is followed by COORDINATOR_CURRENT false
through `_lease/lease/NativeDecodedSource._renew`, with viewer stopping/closing
and master STOPPING. No GRANT_CURRENT false precedes these viewer closes.
`read_mux_frames` is omitted by the current function whitelist; the close-entry
event emits exception=none because it does not inspect the active exception.

The later MAIN renewal has separate measured evidence: HEARTBEAT_EXCEPTION
projects Core heartbeat1834/provider replace799/IPC renew990/_rpc975, with
context `_rpc957` at original pipe.send_bytes. That distinguishes SQL refresh
success followed by native transport renewal failure in the MAIN interval.
It does not establish the earlier cold SUB read exception or native terminal
reason. No SDK result was selected by filename recency.

## Exact source path and masking

`MuxSourceFactory.read:52` calls actual `read_mux_frames`. Its catch
(`local_media_mux_service.py:2473-2479`) closes the lease before rethrowing.
The protected try can fail in distinct ways:

1. Original viewer read raises from current/binding checks, serialized IO,
   native heartbeat, parent pump or parent read (`:2452`; provider `:1047-1074`).
2. Returned read exhausts the two-second operation budget before Core's final
   checks (`:2457`). The original supplier/IPC expiry can also fail inside read.
3. Core's post-read current check denies (`:2458-2459`).
4. Returned tuple, frame type, slot, ingress cut or byte budget fails validation
   (`:2460-2471`). Returned frames remain charged until original release.

The catch first releases a returned batch, then calls close in finally. If
release itself raises, its exception can become active at close; its context
chain can still contain the initiating read exception. Probe this finite chain
before original retirement hides the decision. `_read_limits`, initial `_lease`
and missing-viewer failures occur outside this catch; they do not explain this
particular observed close-origin path by themselves.

NativeDecodedSource's separate authority thread renews every 50 ms. Once read
closes the viewer, `_renew` can fail and publish OBSERVE's first_failure before
the ingress thread escapes the close/cleanup path. Therefore OBSERVE's first
published failure is not necessarily the first causal exception.

Parent pump pressure remains relevant during active reads: bounded encoded
credits, returned-but-unreleased batches, decoder startup/format rotation and
queued source packets can block codec reserve. The parent uses its original
five-second pressure deadline and can fence in `_check`; callback queue bounds
still apply. The second attempt's recorded transition began but never verified
output. None of these facts identifies pressure as the initiating actual cause.

## Executed actual-source inert control

An inline control called actual `MuxMediaExecutor.read_mux_frames` with an
inert coordinator/viewer handle, fake monotonic clock and an observing fake
close port. It constructed no executor monitor, process, DB, SDK or browser.
Initial lease authority was stubbed solely to reach the protected read branch.
Results, Python `-B`, exit 0:

| Controlled initiating branch | Active exception at close | Close calls | Returned batch release calls |
| --- | --- | ---: | ---: |
| Original viewer throws exact LocalDeviceFailure | protocol_invalid 502, same original error object | 1 | 0 |
| Viewer returns empty tuple after 2000-ms budget | deadline_exceeded 504 | 1 | 1 |
| Viewer returns empty tuple; post-read current false | denied 404 | 1 | 1 |

These controls prove three different initiating errors reach the same current
close origin and are accessible via `sys.exception()` there. They do not prove
any particular branch executed on run0601 or test authentic admission/cleanup.

## Minimum proposed runtime-only probe

Reuse the existing `_close_viewer` wrapper and retained bounded publisher.
On VIEWER_CLOSE entry, inspect a finite synchronous caller stack for the exact
original `MuxMediaExecutor.read_mux_frames.__code__` with the exact owned source
path. `MuxMediaExecutor.close` sits between it and `_close_viewer`, so checking
only the immediate caller is insufficient. Only that positive code/path match
may project `sys.exception()` into a new fixed READ_EXCEPTION event before the
original close. Traverse the same finite cause/context and traceback budgets
used by R196; explicitly preserve inspection/omission limits.

Whitelist only required exact file/function pairs: Core read_mux_frames,
remaining budget/current/release/close; provider read_frames/current/_matches/
authority_operation/heartbeat and serialized IO; parent pump/read_frames/
_check/_rpc/_fail plus exact codec reserve/feed/drain; admission original
current/checked and mux source read. Emit checked LocalDeviceFailure code/status
or UNEXPECTED and fixed module/function/line/chain indices. Emit no locals,
messages, arbitrary class names, arguments, identities, SQL, bytes or paths.
Convert immediately to checked primitives/bytes and retain no exception/frame.

Invoke the original close exactly once and preserve its return/exception and
all original release/current/refresh calls. The probe must not recheck authority,
pull frames, acquire callback locks or join/clean resources for diagnosis. A
separate publisher records omitted/failed projections as already designed.
Source review and a fresh immutable closure precede changed actual execution.

## R198 consumer risks and verification limits

- Active SUB readers and the retained base consumer must serialize on the same
  exact original master IO barrier. Avoid a new lower-layer concurrent pump:
  parent nonblocking operation/control admission can fail on contention.
- Preserve two-second viewer read budgets and original pressure deadlines.
  A long consumer drain holding the barrier can turn a healthy read into a
  deadline failure. Bounded iterations and fair handoff need explicit tests.
- Read grant snapshots after acquiring the original refresh barrier; preserve
  old-cut frame rejection and returned-batch credits until consumer release.
  Added pumping must not refund an outstanding viewer batch or restart its
  provenance. Transition/decoder pressure remains an active-reader condition.
- New callback telemetry must not acquire/hold an additional callback lock.
  Native `_data` uses nonblocking lock admission and latches terminal failure
  on contention; an extra diagnostic lock can create the fault it measures.
  Prefer already latched primitive metadata and explicitly non-atomic snapshots
  outside callback critical sections, with bounded omission accounting.

The exact callback/codec/budget failure is open. Priorities are the positive
initiating READ_EXCEPTION trace, typed original native terminal evidence, then
bounded cold SUB/transition and parked MAIN acceptance with normal original
cleanup. Queue growth, decoder slowdown and SQL failure remain hypotheses until
the new trace distinguishes them; no timeout or authority relaxation follows
from these saved timings.

Source/report reads, fixed OBSERVE/Core projections, source hash comparison and
three inert Core controls were the only verification. No production source,
private device input, SDK result, DB, browser, real process, pinned report or
runtime state was changed. Current Core/provider/IPC raw hashes matched run0601
source-before at inspection:

| Source | SHA256 |
| --- | --- |
| local_media_mux_service.py | 9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc |
| local_live_mux_provider.py | bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339 |
| local_live_mux_ipc.py | 5d9209d36d4db81773fbacfa475df36318b93469cca246f277aad459060321b8 |

Current inspected native_source.py was `85b1c119...`, mux_source.py `d83bee16...`
and core_state_debug.py `11834469...`. Their paths were absent from this specific
source-before JSON; this analysis does not infer their historical runtime
closure from those current hashes. R198 concurrent source changes after these
reads require the author's new baseline, review and closure.

Update log: 2026-10-10 initial cold SUB read-boundary diagnosis. Conditional
multi-cause masking is source/inert proven; actual initiating cold read exception
and repaired shared playback remain unmeasured.
