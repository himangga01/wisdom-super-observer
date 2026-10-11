# Multi-view stage-1 actual evidence audit ? c12

Analysis date: **2026-10-06 (Asia/Seoul)**. Independent read-only audit after normal c12 retirement; no source changes, test reruns, SDK, SQL queries, browser or services executed. Baseline: HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, branch `codex/superlive-web-service`, reviewed uncommitted stage-1 implementation through R143. Shared policy, active AGENTS, canonical service report, R143 correction report and c12 execution protocol were read first. Root owns canonical service/liveness/AGENTS/ledger consolidation.

## Decision

**Nine real recorder substreams passed a common five-minute progress check, and c12 completed normal owned cleanup plus the repaired observation terminal/hash gate. Twelve simultaneous streams remain unaccepted.** This is bounded local recorder/Chrome evidence, not production capacity, full APK parity, release readiness or a universal timestamp proof. Prior failed c6?c11 runs and c10 exceptional cleanup remain historical outcomes.

The service supplies authenticated, scoped local recorder playback through SQL leases, original native source owners, bounded decoded-source stages and WebRTC peers. The stage-1 implementation includes main/sub selection, bounded concurrent sources, fair BUSY scheduling, dimension-epoch decoder retirement, raw-versus-presentation timestamp separation and an optional bounded observer. Source reviews establish those contracts; the actual outcomes below are narrower and come from saved c12 artifacts.

## Evidence baseline and provenance

Run: `local-devices-790c686c772b4fe29db973dce986901a`.

- Immutable146-source approval SHA256: `d6cdf6e25790d751a51d7d7f6ec2beee03a6d0253220ff59e96efa0c8ef3cf5b`.
- Native receipt SHA256: `0e7880d69bfec43f2286ec70fda044acb350d0fbc941e75661a485e955dac7d4`.
- R143 source review candidate: `cb0f0454363211d072522367be0bd4f58c16ade7`, independently reviewed C0/I0/M0 as recorded by Root; this audit did not repeat that review or its tests.
- Source-before/source-after JSON are equal across265 entries. At the initial independent audit readback, **all146 approval source pins matched current bytes**. Subsequent Root/auditor documentation updates happen after retirement and do not rewrite the run.
- The borrowed265-entry snapshot omits some media sources, so it is not by itself the complete source closure. The approved runtime verifies every approval pin before launch and again on final exit; retained runtime/coordinator exit0 supports completion of that full check. No module-loaded-code digest or per-branch timestamp execution telemetry was retained.

Artifacts were read from the active worktree with PowerShell login:false. Single JSON/NDJSON files were decoded using their actual BOM (UTF-8 or UTF-16). No raw logs, credential contents, private identifiers or native payloads were exported.

Primary locations:

- `.superpowers/verification/local-device-browser-runtime/<run>/`: media-observation.json, resources.json, coordinator-resources.json, source-before/after.json and the owned database receipt.
- `.superpowers/verification/local-device-browser-root/<run>/root-owner-receipt.json`: original coordinator terminal custody.
- `.superpowers/sdd/2026-10-05-multiview-stage1-plan/sizing-evidence/`: c12-five-minute-progress.json, c12-summary-initial.json, c12-summary-after-five-minutes.json, c12-summary-after-switch.json, c12-long-hold-final.json, c12-window1-final.json, c12-window2-before-stop.json, c12-sql9.json, c12-cpu9.json and c12-cleanup-before-shutdown.json.

## Actual video and timing

Nine presented substreams were established: store1 channels1?5 and store2 channels1?4. Initial saved summary at114.643 seconds has nine successful starts, nine presented starts, zero unpresented successful starts and nine live tiles. Store1 grid video is352?240 (five tiles); store2 is704?480 (four). The initial slice also contains10 BUSY429 and four protocol502 start responses; those failures cannot be relabeled NO_SIGNAL from these artifacts.

| Measure | Verified saved evidence | Limit |
| --- | --- | --- |
| Common continuous-progress window |300.849 seconds on all nine channels. Individual video-time increases approximately300.852 seconds. | A bounded common window; not every second of the later hold. |
| Total video-frame counter increase |3008?3009 per channel. | totalVideoFrames includes dropped frames; these are not all presented frames. |
| Dropped counter increase |0?187 per channel in that window. | Counts show nonzero drops; no claim of zero-loss rendering. |
| Initial API start latency | Nine samples, p50=2.555s,p95=3.035s. | Observed successful-start slice only, not all attempts or deployment guarantees. |
| Initial first-presented latency | Nine samples, p50=3.025s,p95=3.391s. | Observer-defined first-presented boundary; not native first packet. |
| After-five-minute summary | Elapsed461.607s, nine live/presented sources,373 heartbeat200 responses, no failed-heartbeat response class in that saved window. | Aggregate responses do not reconstruct individual timing gaps. |
| Later hold snapshot | Elapsed1091.28s, nine unpaused video tiles and three inactive tiles. | Focus/remount resets HTML video clocks; currentTime values are not original source ages. |

A normal main-focus handoff returned kind1 HEVC metadata1280?1936, followed by return to the352?240 substream grid. The final observer has exactly **one main OPEN_RETURNED** and two main OPEN_FAILED attempts. SQL issued three main leases, all later CLOSED/confirmed. The main peer's first terminal observation is connection_closed after2.703s. This supports a bounded focus/return case; it is not long main-stream stability.

The saved controller reports ten rapid focus/return click pairs and the final nine-substream grid. It does **not** establish ten successful main opens. After-switch summary has12 successful presented starts cumulatively, three stop200 responses, one playing FETCH_FAILED and17 start FETCH_FAILED entries. These are consistent with cancellations during rapid switching; an exact per-click transport-cause assignment was not independently reconstructed. Twelve successful starts over time are not twelve simultaneous peers.

Observer windows are explicitly separate. c12-window1-final.json has elapsed752.379s; the renewed window's before-stop summary has its own elapsed349.991s and315 heartbeat200 responses, with no new successful start. Root reports replacement near controller elapsed735s. These clocks/windows are not concatenated into a single latency sample or represented as gap-free client telemetry. The long-hold snapshot and complete source summary add evidence without inventing observations during any boundary gap.

## Complete source observation and R143 acceptance

The pinned helper's `complete_observation(summary, terminal)` was executed once as a read-only JSON check and returned **true**.

| Gate | Actual result |
| --- | --- |
| Summary | schema2,stop_requested=true,90 native attempts,90 source attempts,12 peer rows. |
| Terminal | schema1,COMPLETE,writer_settled=true. |
| Failures and omissions | observation_failures0,omitted_attempts0,omitted_source_attempts0,omitted_peers0; source format-history omissions sum0. |
| Canonical SHA256 | `ccd899a5be25a7d53776cc8131948a0cfe0924460df526d7175fb3d197975ff2`; matches independent terminal. |
| Saved byte size |45,511 compact bytes. The identical value under the old indent2/newline writer is71,089 bytes, above65,536. |
| Dimension transitions |15 started,15 decoder_rotated and15 output_verified events in total. |

This is actual acceptance of R143's corrected publication composition for this run: the legal snapshot that exceeds the former format/budget completes, and its independently retained terminal certifies the final snapshot. It does not revalidate the1MiB maximum synthetic envelope on real devices or repair c11's immutable failed terminal.

All90 source first-failure rows aggregate to70 executor_start/busy,8 executor_start/protocol_invalid,11 peer/close_scheduled and1 peer_connection/connection_closed. No first-failure row names timestamp, queue or format rejection. Because first-failure is sticky, this is not a universal assertion that no later diagnostic event could occur after its recorded close boundary.

The12 peer rows represent nine initial streams plus three replacement/switch peers. Their terminal close classifications are compatible with normal final Stop and earlier focus/negotiation cancellation. The word ?first_failure? in the schema must not turn those expected close observations into twelve source bugs. The exact deeper cause of every close is not asserted. The eight c12 protocol-invalid starts remain **unresolved in this audit**; c11's independently diagnosed connect/greeting causes cannot be transferred to these eight results without c12 original-native evidence review.

R142 source bytes and longer-lived source observations support operation under the mapped-clock implementation, with no recorded timestamp first failure. They do not prove that a particular equal-raw timestamp branch was exercised; there is no branch-specific telemetry. R137 transition counters give direct execution evidence for fifteen verified rotations while retaining their bounded/custody qualifications.

## Stable-load SQL and original-process measurements

Six consecutive10-second SQL samples cover60 seconds. Every sample reports nine PLAYING leases and sampled_workload_stable=true, with10 owned measurement queries per sample. The workload sampler's observed gap/bracket bounds are retained in the saved records. These are measured rates including the measurement's contribution; the browser common-progress evidence independently supports nine-channel activity, but the files do not provide a single synchronized SQL/browser clock interval.

| Metric | Observed range |
| --- | ---: |
| Owned SQL transactions/s |177.5?187.1 |
| Reported SQL transactions/s per live stream |19.722?20.789 |
| Cluster WAL bytes/s |1801.6?5707.2 |

WAL is cluster-wide, not isolated media WAL or a per-stream rate. The measurement is nine-stream local load, not a capacity extrapolation to twelve or sixteen.

Five CPU samples are complete: expected_root_count7, no missing roles, no observation failures and no unsampled CPU rows. Families were recomputed by exact root role plus its hyphen-prefixed descendants (`worker`, `worker-*`; `chrome`, `chrome-*`), preserving original process-family membership supplied by the reviewed observer.

| Family | Sum CPU % of one core | Current private memory MiB |
| --- | ---: | ---: |
| Worker family |114.457?121.497 |728.1?734.3 |
| Chrome family |10.932?14.024 |627.4?642.6 |

These are sums of surviving observed process rates measured over **individual process windows**, as the saved cpu_sum_kind explicitly states; they are not one common family sampling interval, whole-machine utilization or synchronized peaks. Private bytes are current-sample totals, not peak memory or working set. The reported logical-core count is12. No new sampling or benchmark was performed by this audit.

## Original cleanup and preservation

The saved pre-shutdown SQL report independently reads issued90 and all_closed_confirmed=true: main3 and sub87, both CLOSED with unconfirmed0. The owned database receipt records cleanup=true, equal source-before/source-after content and preserved parent objects. No new SQL query was issued here.

Resources independently report apiSettled=true,workerSettled=true,contextRemoved=true,sourceUnchanged=true. Coordinator resources report runtimeExit0,nextExit0,stateRemoved=true,custodyRetained=false,failureReported=false. The original coordinator root receipt reports exit0,reaped=true,ready_seen=true,state_removed=true,known_private_occurrences0 and no reporting failure. Empty stdout/stderr were not used to infer success; the retained terminal receipts provide it.

**Chrome custody qualification:** Root observed the original retained Chrome launch supervisor completion directly in its tool receipt (exec session17811, completion chunk68882d): chrome_exit0 and original_process_reaped=true. The original launcher does not persist a final receipt file; private owner identity was removed with its context. This auditor did not receive that original tool event independently and did not rediscover a PID or infer reaping from process absence. Any later c12-chrome-root-tool-receipt.json is a clearly attributed Root transcription of that event, not a new independent process measurement.

Normal c12 cleanup and database/source preservation are accepted within those evidence boundaries. They do not rewrite c10's historical unconfirmed STOPPING lease or imply production deployment.

## Remaining risks, priorities and open product questions

1. Twelve simultaneous five-minute streams are not accepted. Three requested store1 targets remained unavailable/inactive; successful source count and BUSY repetitions are not proof of a recorder's hard connection cap.
2. Eight protocol-invalid c12 startup outcomes need their own original-result projection if a correction is pursued. Do not reuse c11 causes, map generic502 to BUSY or fabricate a decoder fault.
3. The initial latency results are conditional on successful starts and one machine/network/recorder setup. Stable-load SQL/CPU data has the timing and measurement-overhead limits above.
4. Main/sub return works in the bounded observed case; rapid clicks are cancellation stress evidence, not ten successful main handoffs. Product expectations for persistently unavailable tiles remain an explicit question.
5. Nine-stream five-minute acceptance and R143 publication acceptance do not establish APK MATCHED status, full parity, production readiness, audio/playback/PTZ support or sixteen-stream measured capacity.

No expensive unchanged run is recommended solely to repeat these accepted facts. Root should preserve this run and decide the next targeted missing-capacity/native evidence question separately.

## Audit verification and update log

Read-only verification used direct JSON structural projections, canonical SHA256 and raw approval comparisons, the existing pure complete_observation gate, row aggregation, saved browser frame/time differences, six SQL rows, five original-family CPU rows and retained cleanup/database receipts. No test suite was rerun and no source behavior was changed. This portable report and a dated R143 outcome addendum are the only authored updates; Root registers this canonical supplementary path in AGENTS and the main service report.

2026-10-06 ? independently audited normally retired c12: common five-minute nine-stream progress, conditional latency/load metrics, actual compact snapshot COMPLETE, approved source boundaries and normal cleanup; recorded incomplete twelve-stream acceptance and original Chrome/tool-receipt qualification.
