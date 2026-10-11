# Independent local media pipeline and transport review

**Current scoped result: C0 / I0 / M0 after independently verified corrections.**
The initial findings below are preserved as historical evidence; read the dated
correction closeout for current source and execution limits.

Review date: **2026-10-04, Asia/Seoul**. Coordinator-supplied baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, active worktree plus uncommitted parallel changes.
Root was still editing the scoped glue/tests. This records the reviewed behavior
before corrections; it is not approval of the whole working tree.

Read before reuse and refresh after changes: [project instructions](../../AGENTS.md),
[canonical service analysis](../service-analysis.md),
[approved Phase 2/M3/M4 design](../integrations/tvt-local-service-integration.md),
[media guide](../integrations/tvt-local-webrtc.md),
[core guide](../integrations/tvt-local-media-service.md),
and the dated continuous section of [decoder guide](../integrations/tvt-windows-decode.md).
Shared Windows analysis policy applies. Existing actual inventory and bounded
frame/decode evidence do not establish continuous browser playback.

## Scope and implemented architecture

Reviewed only media `native_source.py`/`worker.py`, API `tvt/local_media.py`, bridge
`local_media_rpc.py`, narrow client/server/API-main/proto wiring and three new
source/worker/RPC-DTO test files. Core/native/WebRTC/decoder internals were read
only as previously reviewed interfaces. No Git, actual device, credentials,
private capture or database calls were performed.

The pipeline accepts exact private source identity, requires an initial key
picture with parameter sets and one supported primary Annex B NAL, retains
increasing original PTS, and opens one continuously renewed original decoder.
One original producer decodes every compressed picture in source order; only
decoded RGB may be replaced in a latest-frame slot. A private event loop owns
peer/signaling and retained cleanup tasks. Public HTTP/RPC carries scoped tickets,
bounded SDP and safe lease views, with no vendor credentials/frame bytes.

## Findings: C0 / I2 / M1

### I1 — encoder admission incorrectly advances public PLAYING

`worker.py`, `_prepare.delivered`, calls `executor.playing` from the WebRTC
`on_delivery` observer. That observer runs before the RTP encoder receives its
frame; it cannot prove encoding, transmission, browser receipt or rendering.
No browser frame observation participates in this transition. A subsequent
encoder/network failure or an unrendering browser can therefore coexist with
SQL PLAYING. This contradicts the reviewed observer meaning and approved M4
separation of codec/source proof from browser playback acceptance.

Root accepted the finding and proposed a session/CSRF-scoped browser first-frame
telemetry acknowledgement via a purpose-bound control, with worker checks of the
original connected peer and server decoded proof. This proposal was **not yet
implemented or verified** at this report's initial save. It must not grant new
access, and actual Root Chrome pixel/identity acceptance remains independent.

### I2 — stop retires SQL before the original decoder/peer settle

`worker.py.stop` calls `executor.stop` first, which confirms native close and marks
SQL CLOSED/releases capacity, then awaits `_close_entry` for the source/decoder/
peer. A concurrent state read can observe CLOSED while those original media
resources remain pending. Normal `NativeDecodedSource._run.finally` correctly
waits for decoder retirement before core close; this stop path bypasses that order.
Stop's eventual HTTP success waits for media cleanup, but the intermediate durable
terminal state is already incorrect.

Root accepted the finding and proposed an exact private per-lease retirement
barrier registered before resource creation, requiring native **and** original
decoder/peer cleanup before SQL CLOSED. Stop should authorize once, retire the
pipeline, then return its terminal receipt. These were proposed corrections at
initial save; no corrected source or new race execution is claimed here.

### M1 — NAL count guard applies after large allocation

`native_source.py`, `NativeFrameAdapter.packet`, creates
`list(re.finditer(..., data))` before testing `len(markers)>128`. A bounded 4 MiB
payload can contain hundreds of thousands of start codes and allocate that many
match objects in the media parent before denial. The decoder's Job memory bound
does not cover this allocation. The input byte bound is finite, but the advertised
128-marker bound does not constrain its temporary allocation.

Executed inert generator-count reproduction: a 6,000-byte payload containing
1,000 tiny NALs raised `MediaDenied` only after **all 1,000 matches** were consumed
and materialized. Stop collecting at the 129th marker and retain fixed denial;
add a regression that verifies the iterator is not exhausted beyond that bound.

## Other source conclusions and residual risks

- Adapter binding preserves original generation/session/channel/task and
  increasing device microsecond PTS. It rejects encryption context, format/scope
  changes, missing first-key parameter sets, malformed NAL headers and multiple
  primary pictures. Its initial single-slice profile is conservative and may
  reject other legitimate device profiles; actual per-device acceptance is needed.
- Compressed frames are not dropped to catch up. The latest decoded RGB slot and
  one pending notification avoid queued RGB growth, while decoder/native/source
  owners remain retained until confirmation. Slow production or an empty/erroring
  native read ends the source; actual sustained rates/backpressure remain untested.
- HTTP authenticates before reading bounded JSON, applies exact-origin CSRF to
  POST, binds tenant/session/control purposes, validates returned start scope,
  watches disconnect cancellation and uses the existing no-store/Vary-Cookie
  middleware and fixed errors. RPC reuses strict context, unknown-field rejection,
  mTLS SAN admission, bounded/correlated DTOs, cancellation registry and deadlines.
  This source review does not establish actual HTTP-to-SQL-to-native playback.
- Source authority and the first `playing` SQL call run synchronously on the
  media event loop. SQL latency can delay peer progress; the two-source cap is an
  implementation ceiling, not measured multiview performance. Cleanup tasks may
  remain pending until original decoder/native owners confirm; false/timeout must
  preserve those owners and not become release acceptance.

Priorities: correct durable retirement and playback semantics, then bound NAL
collection and rerun their targeted regressions. Open questions remain supported
source profiles, browser telemetry semantics, production TURN, and measured
native/decode/encode capacity. Actual authorized Chrome playback, identity,
revoke/expiry/stop/reconnect and orphan-resource acceptance remain the M4 gate.

## Verification and limits

Fresh reviewer executions:

```powershell
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_media_worker.py tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_media_rpc_api.py --tb=short
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_device_rpc_api.py --tb=short
```

Results: **12 passed in 1.64 seconds** for new scoped glue/DTO cases and **32 passed
in 5.70 seconds** for existing local-device RPC/API regression. The marker-count
reproduction above is separate. One initial filename guess selected no tests;
the established filename was then resolved and run as recorded.

Mypy passes are Root-reported, not independently rerun here. This scope does not
prove a real camera, complete pipeline loopback, continuous Chrome receive/render,
SQL/native lifetime barriers, cancellation races, production capacity, full-suite
or release readiness. The two important findings are source-backed and accepted
by Root; their proposed fixes still require independent correction review.

Update log: 2026-10-04 — scoped initial pipeline/HTTP/RPC review, fresh 12+32
portable regression passes and bounded NAL iterator reproduction; C0/I2/M1 before
correction. Separate core and continuous decoder reviews now record C0/I0/M0
after their narrowly verified corrections.

### Independent correction closeout — 2026-10-04: C0 / I0 / M0

All three initial findings are closed within the reviewed correction delta:

- **I1:** encoder admission no longer calls `playing`. The browser reports its
  positive `requestVideoFrameCallback` presented counter through a strict bounded
  `LocalLiveStartedRequest` and session/CSRF-bound `/playing` route. Its separate
  one-use `playing` control ticket retains exact lease authority through RPC.
  Worker requires the original peer to be connected, actual produced RGB, current
  source authority and validated native AU/codec/timing proof before core PLAYING.
  The report is authorized browser telemetry, not a new access grant or independent
  proof of truthful client rendering. Actual Root Chrome pixels/identity remain
  the acceptance gate.
- **I2:** an exact private retirement barrier is registered before source creation;
  the source enters the owned map before its producer starts. The callback only
  schedules/checks original retirement and never blocks core cleanup. Its event
  is set after source close joins the original producer/confirmed decoder and peer
  disposal. Core combines that event with native confirmation before SQL CLOSED.
  Stop redeems once, awaits whole-entry retirement, then uses `finish_stop` for the
  terminal receipt. Source finally no longer waits for SQL retirement, avoiding
  circular ownership. Uncertain cleanup retains the original maps/tasks/barrier.
- **M1:** `islice(..., 129)` bounds marker materialization before the 128-marker
  denial check. Its regression confirms exactly 129 matches consumed from the
  same 1,000-marker inert input.

Reviewer read the matching media/core/contracts/SQL-control/API/RPC/browser-ack
delta and executed the three scoped glue files: **15 passed, zero skipped,
1.84 seconds**. Narrow new core retirement/attachment/finish-stop/playing-control
selection: **eight passed, 14 deselected, 0.41 seconds**. The blocked-source stop
case retains STOPPING and zero terminal closes until original media retirement;
PLAYING requires browser report plus connected/decoded checks; cancellation
retains pending source cleanup. No broad suite or real-source run was repeated.

Root reported fresh actual SQL run `628390264af04a5d8c2f9b49d555d4cc`:
**15 passed, zero skipped/errors**, owned cleanup/source preservation and zero
known private-value hits. This coordinator result adds barrier and playing-control
purpose/replay cases; this reviewer did not execute the database. Root's frontend
15-case pass is likewise attributed, with TypeScript verification pending at this
handoff. No real CCTV/Chrome/continuous-runtime or release gate advances solely
from these corrections. Initial source findings above remain historical evidence.
