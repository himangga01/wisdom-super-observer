# Scoped local WebRTC media review

**Current scoped result: C0 / I0 / M0 after independently verified corrections.**
Initial minor findings below are retained as historical evidence.

Review date: **2026-10-04, Asia/Seoul**. Baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, active worktree under
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
The reviewed media package, guide and tests were untracked additions; other
agents were concurrently changing disjoint core, native, API and web files.
This is an independent media-slice review, not approval of the complete tree.

Read before reuse and update after changes: [project instructions](../../AGENTS.md),
[canonical service analysis](../service-analysis.md),
[approved Phase 2/M3/M4 integration](../integrations/tvt-local-service-integration.md),
and [media implementation guide](../integrations/tvt-local-webrtc.md).
The shared analysis policy was also read. Historical device/browser inventory
evidence in the service report does not establish this new video path.

## Scope, purpose and implemented structure

Reviewed only `services/tvt-media/pyproject.toml`, its four Python modules and
`tests/tvt_parity/test_local_webrtc.py`; read existing `windows_decode.py` for
`DecodeBinding`/`PrivateRGBFrame` contracts and installed pinned aiortc/aioice
source for the actual send path. No native DLL, credentials, database, API/RPC,
frontend or whole-branch audit was performed.

The implemented package accepts a trusted current-authority callback, an exact
private decode binding and an already decoded source. It validates bounded RGB
and source microsecond PTS, exposes one VP8 send-only peer, checks authority
around dequeue/conversion/admission and at the original DTLS send boundary,
and closes its original source and peer on denial, cancellation or expiry.
This is the M3 transport building block. Approved M4 additionally requires the
actual dedicated native session, source proof, decoder, service authority and
browser receive/render acceptance; those outcomes are outside this review.

## Findings: C0 / I0 / M2

### M1 — standalone SDP validation leaks parser exception classes

`services/tvt-media/src/wso_tvt_media/signaling.py:61` catches a subset of
aiortc parser failures. An inert bounded input with a value-less candidate
raises `AttributeError`; a format parameter for an unknown payload raises
`StopIteration`. Both should return the fixed `SignalingDenied` contract.

Reproduced with this base:

```python
base = ("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\na=rtcp-mux\r\na=rtpmap:96 VP8/90000\r\n")
validate_offer(base + "a=candidate\r\n")       # AttributeError
validate_offer(base + "a=fmtp:97 x=1\r\n")     # StopIteration
```

`LocalWebRtcSession.answer` currently catches these failures and closes before
returning a fixed denial, so this finding does not demonstrate authorization
bypass or private-detail disclosure through that session entry point. Normalize
these parser failures in `validate_offer` and add those two inert regression
cases so direct callers can rely on the documented exception contract.

### M2 — cleanup failure replaces signaling or cancellation outcomes

`services/tvt-media/src/wso_tvt_media/live.py:287–292` awaits public `close`
inside its exception handlers. That method correctly raises `MediaDenied` when
source disposal is uncertain, but its exception then replaces the intended
`SignalingDenied` and can replace the pending `CancelledError`.

Executed reproduction: an inert `FailingSource(BoundedDecodedSource)` awaits
`super().close()` then raises `ValueError("inert cleanup failure")`.
`await session.answer("v=0\r\n", "one")` yields **MediaDenied**, with the
original peer **closed**, rather than the fixed signaling exception.
Cancellation masking follows from the same awaited close path; that variant
was source-reviewed rather than separately executed.

Preserve the original signaling/cancellation result while retaining cleanup
uncertainty for later `close`/`wait_closed` calls. This finding concerns exception
semantics; disposal is still attempted and no private error text escapes.

## Positive source conclusions and residual risks

- Frame identity uses all fields of the existing exact immutable decode binding;
  dimensions, bytes, ordinal and signed microsecond timestamps have explicit
  bounds. RGB row padding is copied correctly into PyAV. Source PTS is retained;
  RTP conversion uses the expected 90 kHz clock with a randomized origin.
- The queue has bounded frames/bytes and permanently discards on overflow or
  observed revocation. Session fences are synchronous and irreversible; renewal
  checks existing authority and a maximum 30-second future monotonic deadline.
  The 50 ms idle monitor closes expired/fenced sources.
- A session accepts one bounded offer. Video recv-only, RTCP mux and VP8 are
  required; audio/data/multiple media descriptions are rejected. No public ICE
  server mutation is exposed; peer configuration has an empty ICE server list.
  Candidate addressing remains the intentionally supported bounded ICE surface.
- In installed aiortc 1.15.0, both ordinary RTP after the encoder executor await
  and retransmission enter the hooked original `_send_rtp`. Its UDP send path
  has no intervening yielding operation before `sendto`. The hook therefore
  checks current authority after asynchronous encoding and before these sends.
  This conclusion is source-backed; the existing test calls the hook directly,
  rather than forcing a real delayed encoder or NACK retransmission race.
- Close shields original-owner disposal, stops the track, clears the source and
  attempts peer close even if source close fails. Three-second asyncio deadlines
  are cooperative cancellation bounds, not proof of forcibly reaping an
  uncooperative native process. The trusted source must confirm its original
  process/decoder disposal or raise; integrated ownership acceptance is pending.
- `on_delivery` runs before the frame is handed to the RTP encoder. It proves
  encoder admission only; it cannot establish encoding success, network receipt,
  browser rendering, camera identity or PLAYING acceptance.

Priorities after the two corrections: retain the pinned private-hook regression
gate, compose exact current SQL authority and source ownership, then execute M4
device/browser acceptance. Open product questions remain production TURN policy,
measured encoding/slow-consumer capacity and the accepted native orphan bound.
No new product decision is needed for these two exception corrections.

## Verification and limits

Fresh reviewer execution in the integrated workspace:

```powershell
$env:PYTHONPATH='packages/core/src;services/tvt-media/src'
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_webrtc.py --tb=short
```

**19 passed, zero skipped, 0.87 seconds.** Additional direct inert Python
reproductions produced `AttributeError`, `StopIteration`, and cleanup-masked
`MediaDenied` as recorded above. No production vendor SDK or private input was
used. Ruff/mypy passes are author-reported and were not rerun by this reviewer.

The fresh suite includes actual local aiortc VP8 encode/ICE/DTLS/SRTP/decode and
source-relative PTS spacing. It does not prove Chrome playback, high-resolution
performance, packet-loss recovery, current SQL authorization, real source
identity, native lifetime, full-project checks or release readiness.

Reviewed SHA-256 source identity (before corrections):

| File | SHA-256 |
| --- | --- |
| `pyproject.toml` | `06774a81c78a4da3fb7b105a1d4ce8986d32c4ac7de3ac88144b9d8f06e27b34` |
| `codec.py` | `a43f3aeaece2ee3d976571d68b3f535d5c4e565fa64c8c7d2cbe220eaab651c6` |
| `signaling.py` | `fdb9f0cd645012d2e096c770a1ba43d1c32729cfbc71932c3df4f01a7fccad33` |
| `live.py` | `bad583893b84cfe3bfa48120218484d821ee1156d8163f767731acecf2baa889` |
| `__init__.py` | `aff3a7a77a35e69ff8aa2b80d93edd486053634f746c25a970059389bb9df6f7` |
| `test_local_webrtc.py` | `be41b8fbf4199531e64c458a2fe1cdd1c4d204e741adb5cdee969bc8f6bd64f6` |

Update log: 2026-10-04 — independent scoped initial review, fresh 19-case
execution and three exception reproductions; C0/I0/M2 before correction. No
application source edits, Git mutation or real-device acceptance occurred.

### Independent correction closeout — 2026-10-04

Both initial minor findings are **closed; current scoped outcome C0/I0/M0**.
The changed parser handler catches `AttributeError` and `StopIteration`.
Both answer exception handlers suppress only cleanup `MediaDenied`, preserving
the fixed signaling denial or caller cancellation while `wait_closed`/`close`
retain disposal uncertainty. Four added regression cases assert those outcomes.

Reviewer read the changed source and all four regressions, then ran the combined
portable contracts/core/WebRTC command in the workspace: **153 passed, zero
skipped, 0.96 seconds**, including all **23 WebRTC cases**. This independently
confirms the author's separately recorded 23-case correction result. Initial
source hashes and findings above remain historical evidence; they do not identify
the corrected source. Native/SQL/device/browser verification limits are unchanged.
