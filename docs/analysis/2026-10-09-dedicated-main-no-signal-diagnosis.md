# Dedicated MAIN: first-frame NO_SIGNAL diagnosis

Analysis date: **2026-10-09, Asia/Seoul**. Scope: the first actual MAIN startup
after reviewed R193, its native/IPC readiness path, and the minimum next
measurement. **The original startup phase defect is passed in this run. The
remaining cause is not established: MAIN receives an accepted open ACK but no
first keyframe is admitted before the existing first-frame deadline.**

## Authority and baseline

Read before analysis: shared analysis policy, worktree [AGENTS](../../AGENTS.md),
[service report](../service-analysis.md), Oct 9 startup diagnosis/fix/R0/R1 and
native-pin review, Core debug review, live codec/provider/session/acceptance
guides, and the selected APK research in the primary checkout. Systematic
debugging was used. The controller owns canonical service/handoff/AGENTS bridges;
this agent writes only this report. Read this report before first-frame/native
diagnostic changes and update it after source or actual evidence changes.

Implementation authority:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, freshly checked HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial Git status contains retained
Stage 1/2 modifications and untracked source/tests/reports; the primary checkout
does not contain this implementation. Controller run `e9eac3c8` used envelope
`1613ad74`, native receipt `18ccf5e5` and public LIVE v2 `0aec9097`. These identify
execution/source artifacts, not Git HEAD. Historical reviewed and failed reports
remain separate.

Fresh raw SHA256 readings:

| Source | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_live.py` | `e38c21e3b54109293add89c5602ab5650c19c77dddf6248c821b0da6045737b3` |
| `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py` | `32cd642a8e2ec74a7afefdaae14c365ad89a016db5ac21337e291bd5c4dae2cd` |
| `services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py` | `cba9407fcde2956a3dc48c0596bd2a74a51b101bfd9f4553c83a01f91170cdaf` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py` | `52109c4df410fbafc37170a78a2d5c76ce24870dfd0156b7a137ea54ce5aaf85` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py` | `cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `f48373ce7861106a72901165177fede2d3da31a0a7ff9d658a2c16d29398cf33` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ownership.py` | `2d097f9091be2d44856cd047cb6e5a94dd29362a067222ae3121b45a62a34f26` |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999` |

## Actual evidence and source conclusion

Controller-supplied evidence: low start/offer/PLAYING returned 200; reconnected
Chrome presented `352x240`, current time `16.191538` and 163 decoded frames.
Manual HIGH focus returned 200, source STOP ticket returned 404 with permitted
closed readback, and MAIN start returned `LOCAL_DEVICE_NO_SIGNAL` 504 after
14280 ms. The untruncated Core trace is `MuxMediaExecutor.start:2214` →
`DeviceEpochCoordinator.attach_dedicated:1573` → `PreparedDedicatedMain.start:1357`,
elapsed 14218 ms. The controller subsequently confirmed original retirement:
coordinator exit 0/reaped, API/worker settled, context removed, source unchanged,
known private occurrences zero and PostgreSQL alone running. This agent neither
operated that runtime nor inspected private inputs/logs/results.

The service presents authorized CCTV channels. Shared SUB uses its recorder mux;
dedicated MAIN owns a separate Windows process/Job and a legacy live IPC pipe.
SQL startup current, native open/readiness, activation, decoding and browser
delivery remain distinct. Source proves:

- `local_live_ipc.py:332` starts the 10-second first-frame deadline only after
  its independent codec accepts a matching successful 1281/1285 ACK. MAIN's
  serializer selects 1281, including peers whose capability is at least five.
- `_first_frame_current:397` can deny `no_signal` only with that deadline set,
  `ready == false`, and a fresh successful current/cancel/caller-deadline check.
  Thus this outcome proves setup/login/serial and selection validation, native
  open Send and matching parent ACK were reached. It does **not** prove a frame.
- `pump:341` applies the deadline before accepting a parsed frame, and `:343`
  discards a non-keyframe before initial readiness. Invalid complete media,
  unsupported stream/route/format and parsed refusals use other failure paths.
  A valid partial envelope/fragment can remain incomplete until the timeout.
- `WindowsSocketProvider.run:1361` passes `live_selection`; the worker selects
  `LiveRemoteAuthority` and `drive` → `serve_live:1132`. Both legacy MAIN
  `NativeLocalLiveProvider.open_session:194` and dedicated MAIN use this same
  worker path, stream 1 request, command 1281, first/exclusive callback claim,
  `LiveCodec` and readiness policy. Dedicated differences are retained custody,
  generation/pipe ownership, Job/credit allocation and R193 startup current.
  No dedicated-only MAIN serializer or parser defect was found.
- `serve_live:1240` independently validates envelopes before forwarding the
  original envelope for parent parsing. Existing service `SafeResult` frame
  counters are not incremented here. Its final `result.json` is written after
  `drive` returns and service close; original retirement can win that write.
  Empty results are therefore insufficient evidence of the missing stage.

The existing APK codec reference maps keyframe to ep3 key marker 1 or y41 IP
marker raw 0x80, and MAIN to legacy 1281/stream 1. Historical native acceptance
also records one selected MAIN attempt that got ACK/heartbeats without media;
this shows the outcome is possible, **not** that it describes this channel/run.
Successful SUB playback cannot establish MAIN availability. An arbitrary latest
SDK generation or a timestamp alone cannot bind native evidence to this MAIN.

## Fresh inert control

Executed one stdin probe with `.venv/Scripts/python.exe -B -`; exit **0**, elapsed
**0.71 s**. Actual `LiveParentAuthority.pump/tick/_setup` and `LiveCodec` used
invented MAIN setup/ACK/media, a fake monotonic clock and an in-memory connection.
`multiprocessing.Pipe` was replaced with an assertion sentinel. No pipe, native
process/Job/DLL, SQL connection, staging file, browser, cache or bytecode was
created. This was a narrow causal control, not an optional suite or hardware test.

| Invented input after ACK at time 100 | Outcome |
| --- | --- |
| No media, time 110 | `no_signal`; no parsed media |
| Valid non-keyframe only, time 110 | `no_signal`; parsed media but not ready |
| First keyframe parsed at 109.9 | Ready; remains current at 111 |
| First keyframe parsed at 110 | `no_signal`; parsed media but not ready |
| No ACK, time 110 then caller expiry 120 | Still waiting then `deadline` |
| Current revoked at 110 | `denied`, with precedence over `no_signal` |

This proves public NO_SIGNAL cannot distinguish absent media, non-keyframes and
late first keyframe. The boolean `codec._last_index is not None` survives close
and reveals that some media parsed, but cannot distinguish the latter two cases.
`deny` closes the codec and erases partial assembly/format state, so useful
partial-state measurement must occur **before** the terminal deny.

## Minimum next measurement and decisions

Priority **P1**: one freshly reviewed, bounded diagnostic run of the same MAIN
transition. Retain the exact authority passed to this original native run; emit
one closed structural first-frame summary before its terminal deny. Proposed
fixed data, with no raw headers or identifiers:

| Boundary | Minimum structural evidence |
| --- | --- |
| Parent ACK/readiness | `open_ack`, `ready`, fixed MAIN/1281 branch, relative ACK/first-media/first-key milliseconds, parsed-media/key/non-key counts, first-key-at-or-after-cutoff boolean |
| Parent parser/IPC | Incoming envelope and decision counts, received byte/packet counts, partial-buffer/assembly byte counts and fragment-pending boolean, original current-call count/max elapsed milliseconds measured around existing calls |
| Same original worker | Open Send/accepted ACK booleans; post-ACK drained batch/byte counts; complete media/heartbeat/fragment counts; validated key/non-key counts; forwarded envelope counts; partial transport/codec bytes; callback failed/closed and queue byte/chunk counts; fixed last completed IPC purpose and existing IPC wait count/max milliseconds |

Use fixed command categories and match/validation booleans rather than source
header values. Every count needs a hard bound/saturation rule. Root owns the
debug transport and exact original run/generation/file binding; do not discover
results by directory recency. Record the parent snapshot before close clears
state, and ensure worker progress survives original retirement through a
separately approved bounded diagnostic channel. Extra authority calls, a second
codec, altered callbacks, changed deadlines/guards or result-file polling as
control would change the experiment and are not proposed.

Interpretation: worker and parent see only ACK/heartbeats with advancing IPC
progress → recorder sent no accepted video in this interval; validated video but
zero keyframes → first-key availability; worker forwards keyframe before cutoff
but parent parses it at/after cutoff → IPC/current scheduling delay; retained
partial data → incomplete receive/assembly. Worker/parent discrepancies select
the failing boundary before any production repair. A zero parent-media count
alone does not prove recorder absence. No timer increase or codec guard widening
is supported by current evidence.

Open questions: what MAIN video/first-key data this original receives; whether
IPC/current latency consumes its interval; whether partial framing stalls. No new
product decision is required for this measurement. MAIN decoding/browser
acceptance, multichannel duration/performance, twelve-camera and APK equality
remain open. R193 source C0/I0/M0 and owned SQL eight-case acceptance remain
qualified prior evidence and are not reopened by this different outcome.

Update log: 2026-10-09 — exact readiness boundary traced; six no-OS-resource
causal controls passed; minimum same-original telemetry contract recorded.
No production/test/index/native/DB/browser/private-input edit or execution.
All eight source hashes were re-read after the probe and report write and match
the baseline table. The saved report was verified to exist; completion
verification concerns this diagnosis, not repaired MAIN acceptance.

## R194 actual parent measurement after retirement — 2026-10-09

This dated append preserves the earlier source/control conclusions and historical
`de49cf4a` report identity. Controller run `6d2c380f`, under fresh R194 source
`05ed91b9` / native `0fb88c6a`, returned MAIN NO_SIGNAL 504 after **14187 ms**.
Its validated typed parent record has ACK true/command1281 at3875ms, absent
first-frame/key times, zero parsed frames/non-keyframes/keyframes, four parsed
codec packets/388received bytes, and zero partial/assembly/fragment/FIFO state.
IPC processed399messages/399decisions/four envelopes/40093bytes, nextsequence400,
lastcompletedpurposeframe;1398original enclosing authority checks had a16ms
maximum. `worker_observed` remains false. These are Root-supplied actual facts;
this diagnosis agent did not inspect private runtime data or operate hardware.

For this attempt, observed parent non-key/late-key and retained parent partial
assembly are excluded. Worker callback/drain/forwarding and recorder absence are
still unmeasured; packet counts alone do not establish their categories. Root
confirmed normal original retirement: exit0/reaped, API/worker/context/source/
private gates normal, PostgreSQL alone running. No MAIN playback is accepted.

Root selected the existing sole legacy MAIN service path as the next bounded
availability comparison before worker IPC changes. It keeps the common native
worker,1281/stream1 codec and first-key guard, and needs a fresh schema2 current
source approval plus a nonshared launcher. Success would establish current MAIN
availability under those service conditions, not alone prove coexistence caused
the shared failure. Exact dedicated MAIN without its retained master/focus is
not an admissible comparison under current guards. See the separate
[worker evidence and legacy-control proposal](2026-10-09-dedicated-main-worker-evidence-proposal.md)
for source evidence, exact metadata scope and remaining measurement limits.

Update log: 2026-10-09 R194 — actual zero-parent-media summary and normal
retirement appended only after the controller released the active freeze;
historical report/source/receipt outcomes preserved. Sole legacy MAIN remains
proposed and unexecuted by this agent.
