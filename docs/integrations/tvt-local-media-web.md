# Local CCTV browser media integration

Date: 2026-10-04 Asia/Seoul. Source baseline: `211d1484aa16eb30f5d362758f149f98dec9dfdf` plus the current uncommitted M3/M4 changes. Read [the service report](../service-analysis.md), [media core](tvt-local-media-service.md), [native session](tvt-windows-live-session.md), [WebRTC](tvt-local-webrtc.md) and [decoder](tvt-windows-decode.md) before changes; update executed evidence in the canonical report afterward.

## Implemented composition

React `LocalLivePanel` opens an explicit selected verified local channel. The Next `/api/live-sessions` proxy enforces the current session, exact origin/CSRF, closed selectors, bounded JSON and25-second combined cancellation. FastAPI `/api/v1/tvt/live-sessions` authenticates before body processing, requires the OWNER tenant entrance and commits a purpose-bound SQL ticket before dispatch. Only the private mTLS worker receives that ticket and bounded signaling data. Device credentials, native indices/GUIDs and media bytes do not pass through these JSON routes.

| HTTP operation | Public input | Worker operation |
| --- | --- | --- |
| POST collection, tenant/connection query | store/device/channel UUIDs, expected generation/inventory revision, default stream | Start with opaque ticket |
| GET lease | tenant query | Scoped SQL view |
| POST lease/heartbeat | Empty object | Exact-session SQL renewal |
| POST lease/webrtc-offer | offer SDP and unique offer ID | One-use Offer ticket |
| POST lease/playing | Positive browser decoded-frame counter | One-use Playing ticket |
| POST lease/stop | Empty object | One-use Stop ticket, original pipeline retirement |

The private pipeline owns one fresh TVT process/socket/task and one decoder per lease. `NativeFrameAdapter` binds exact private generation/session/channel/task values, preserves source microsecond PTS, requires the initial supported keyframe and parameter sets, and validates a conservative single-primary-picture Annex B profile. Only already-decoded RGB frames may be replaced by newer frames for a slow or not-yet-ready browser. One RGB slot and one queued notification bound that backpressure; compressed frames are not arbitrarily dropped.

`LocalMediaWorker` owns a persistent media event-loop thread. Before allocating a decoder or peer, it registers a private retirement barrier with the core lease owner. SQL CLOSED and quota release require both original native closure and confirmed decoder/thread/peer closure. Cancellation of an RPC wait does not discard these original owners. A source/peer cleanup overrun remains pending and is retried against the same objects.

The WebRTC track converts validated RGB to VP8. Empty ICE-server configuration is the current local-test policy; no caller-provided network/file media URL is accepted. API and browser routes do not construct native providers or decrypt credentials.

## Playback state and limits

Encoder admission alone does not mark PLAYING. The browser's actual video-frame callback reports its first presented frame through the authenticated playing route. The worker also requires the original connected peer, at least one actual server-decoded frame, current authority and the native/format/timing proof. This client counter is scoped playback telemetry, not a cryptographic attestation or a new access grant. Root must independently observe actual browser frames/pixels for executed acceptance.

Default media TTL is30 seconds with10-second browser heartbeat. Native orphan expiry and the continuous decoder's at-most5-second inactivity fence are independent. Native capacity is two separate local live owners. Only the source-supported default stream is currently connected; broad quality selection, audio, playback, remote TURN deployment and general multiview capacity are later acceptance work. The initial AU profile rejects reordered source PTS and unsupported multi-picture or multi-slice framing rather than guessing.

## Verification record

Portable checks cover wrong public scope, unsafe counters, private-field rejection, reply correlation, exact auth/CSRF, no automatic retries, late start cancellation, delayed original-source cleanup, browser-receipt gating and SQL retirement ordering. Real inert WebRTC and Windows decoder evidence belong to their separate guides. Guarded media SQL acceptance uses a uniquely owned future database; previous13-case acceptance is historical before the new playing-purpose/barrier extension.

At this document's creation, actual CCTV-to-Chrome continuous playback has **not yet been executed** on this composite source. The owned HTTPS browser fixture is being extended to a separately approved v2 source snapshot. Existing8/4 inventory browser acceptance remains a distinct completed milestone. `MATCHED=0`; `release_ready=false`.

**Acceptance update — 2026-10-04.** Continuous CCTV-to-Chrome playback has since been executed on the real recorders: run `local-devices-06c7327498f845e787824d8dd019f081` (approval c2) played store 1 continuously for about five minutes and store 2 for 81.7 s concurrently, with stop/reopen, heartbeat/TTL renewal, confirmed cleanup and source stability; run `local-devices-6bfe84c4179f468c8335280eef4b69ce` (approval c3) re-checked the `object-fill` display, which the user visually accepted. Evidence: [liveness review](../analysis/2026-10-04-local-media-liveness-review.md) section 6. `MATCHED=0` and `release_ready=false` are unchanged.
