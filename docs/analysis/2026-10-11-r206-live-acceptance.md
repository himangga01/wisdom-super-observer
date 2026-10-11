# R206 live replay: old cancellation removed, replacement admission denied

2026-10-11, Asia/Seoul. Baseline HEAD6436748 plus retained reviewed Stage1/2/R193-R206 work. Service provides local recorder live playback with shared SUB transport and separately owned MAIN. Source gate and actual acceptance remain distinct.

Read AGENTS, service-analysis, stale-forward-focus-cancellation and attached-focus-cleanup-fix/review before reuse. Actual run6db9d55ab7c347ccb63f2f1209404cfb used the reviewed LIVEv12/native44956/source431 envelope936280c4. Original execution95525 was retained. Trusted Chrome owner login and store1 real8 inventory passed. CDP Network was enabled before playback; successive request/response projections had no truncation. No headers, bodies, identifiers or credentials are saved in this report.

LOW1280x720 rendered21.804833s/218frames; HIGH1280x1936 rendered25.462499s/259frames. Both dropped0. RETURN sequence was focus200, MAINstop200, replacement SUB start404, wallstop200, new RETURNsettle200. The obsolete FORWARD settlement request was absent. API bounded log distinguishes start/rpc LOCAL_DEVICE_DENIED404 (62ms); Core executor_start trace reaches coordinator.attach through checked66. No inner refresh failure was recorded. New failure precedes SUB frames; five-minute, stress, reconnect and store2 gates were not executed.

Normal shutdown passed: original coordinator exit0/reaped, state/context removed, API/worker settledtrue, media observation COMPLETE/writer_settledtrue, source431 unchanged and known private occurrences0. Owned DB receipt reports cleanup and source-content equality. No exceptional termination was used. Historical5dd exit97/1 and missing final Job receipt remain FAILED evidence. HistoricalR203 late-slot denial remains separate/unresolved.

Read return-slot-binding-causal-map for the source gap selected by subsequent Core and real ownedSQL RED: retained physical slot reuse skipped per-new-lease SQL slot association. This replay establishes the attached-only FE repair reaches replacement start and normal cleanup; it does not establish accepted RETURN playback. Broader pytest7816/runtime-mypy151/twelve-camera/APK/publication gates remain open. Update after fresh reviewed replay.

Update log: Oct11 saved exact R206 phase and normal retirement outcomes after source pins released.
