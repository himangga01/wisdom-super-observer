# Multi-view live (all stores, all cameras at once) — implementation plan

Date: 2026-10-04 (Asia/Seoul). Status: **proposed, awaiting user approval**.
Basis: [APK parity review §5](../../analysis/2026-10-04-apk-feature-parity-review.md)
(APK model and our limits with file:line evidence) and the
[liveness review](../../analysis/2026-10-04-local-media-liveness-review.md)
(measured single-stream behaviour, keepalive root cause, acceptance runs).

## Goal

The `/monitoring` wall shows every channel of every store live at the same
time (today: 8 + 4 = 12 channels on two recorders), the way the official app's
split view does, with the focused tile upgraded to the main stream.

## Why raising the caps is not enough

Today every tile is a separate device login, socket, native child, isolated
decoder and VP8 re-encode of a 1280×1936 HEVC **main** stream, capped at 2
native owners, 2 media sources, 4 leases per user and one lease per channel.
Twelve such pipelines would likely exceed the recorders' connection limits
(`maxConnNum`, unmeasured) and multiply server CPU (one stream measured at
~0.5–0.9 core in the runtime plus ~12% per decoder child). The official app
instead keeps **one connection per recorder carrying one task per channel**
and uses **sub streams in every split** (`cw3.jb`, `cw3.kb` command 1285,
`LiveViewLayout.Z1`).

## Phases (each ends with independent review, receipts where pinned, real-device acceptance and docs)

| Phase | Deliverable | Gate |
| --- | --- | --- |
| 0. Measure | Recorder limits (`maxConnNum`, `maxMainstreamNum`, `maxSubstreamNum`) read from device info; per-stream server cost (CPU, memory, SQL tx/s, WAL) for 1 and 2 streams (final-review I3). No behaviour change. | Numbers recorded in the liveness review. |
| 1. Sub stream | Open stream 2 on the existing session model: command 1281 stream 2 for peers < v5, 1285 XML open and its reply lifecycle for ≥ v5; codec/adapter accept the sub-stream format; contracts/SQL already allow `sub`. | New live-codec + native receipts; real sub-stream video in Chrome for both recorders. |
| 2. Per-device multiplexer | One long-lived native login per recorder carrying N channel tasks (task-fenced route instead of exclusive-first-task/route-0), shared 6 s keepalive, per-task frame routing into separate sources, per-task stop. | Native review + receipts; 4 then 8 + 4 tasks on the real recorders with stable keepalive and clean retirement. |
| 3. Viewer fan-out | Upstream registry per (device, channel, stream), reference-counted; per-viewer leases; one decode/encode per upstream relayed to many peers; migration 0014 replacing the one-active-lease-per-channel index with upstream + viewer leases and a raised per-user cap. | Guarded SQL suite; two viewers of one camera; capacity probe. |
| 4. Caps and scheduling | Lift worker/native caps to the Phase 0/2 measurements; queue instead of 429; publish the capacity to the wall scheduler (no UI change needed). | Sizing gate 1 / 4 / 9 / 16 tiles on the real recorders: CPU, memory, bandwidth, p50/p95 start latency, orphan duration. |
| 5. Production | Wire the media worker in `create_server_from_environment`; quarantine/orphan recovery on restart (final-review triage); TURN/relay policy; staff viewer role per store; deployment decision for the Windows-only bridge. | Production bootstrap review; remote-browser acceptance. |

## Decisions needed from the user

1. Approve this multi-phase backend program (it changes reviewed native code
   and needs several real-device acceptance runs).
2. Priority against the other missing APK areas (recorded playback, alarms/push,
   PTZ, audio/talk, snapshot/recording) — see the parity review §6.
3. Deployment topology for the Windows-only native bridge (on-site per store or
   central).

## Interim behaviour

Until Phase 4, the wall plays up to the current backend limit (2 streams) and
queues the rest with visible "재생 대기" tiles; the focused tile gets priority.

## Added from the real-device wall runs (2026-10-05)

- Store-1 channels 1 and 3 open but never send video. The server answers their
  start after ~13 s with HTTP 429, and the web proxy forwards only the status
  with a generic `LOCAL_DEVICE_UNAVAILABLE` code. Phase 1 should introduce a
  distinct "no signal" outcome end-to-end (native → executor → API → proxy →
  player) with a short first-frame bound, so the wall can show "영상 신호 없음"
  without retrying, and the proxy should forward the upstream error code.
- After a failed start the native provider refuses new live starts for a few
  seconds while the failed session retires (`ProviderBusy` → 429). Phase 4's
  queueing should replace that refusal with a bounded wait.
