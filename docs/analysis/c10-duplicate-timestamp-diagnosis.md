# C10 duplicate timestamp diagnosis and R142 proposal

Date: **2026-10-06 (Asia/Seoul)**. Status: **read-only diagnosis/proposal; no implementation or acceptance**. Root still owns original c10 retirement and the R142 decision. Existing source, tests, pinned reports, receipts and approvals were not changed.

## Baseline, purpose and observed boundary

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`, branch `codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, confirmed from the worktree HEAD/ref files without Git commands. Authorized stage-1/R137–R140 work is already uncommitted in this tree. Read the shared analysis policy, AGENTS, canonical service report, R140 report and relevant native codec/decoder guides first. Root owns canonical service/AGENTS/ledger integration; this new report and its local bridge are the only authored changes.

The service carries a validated original recorder stream through native IPC, a source adapter, an isolated decoder and the original WebRTC peer. The current adapter treats source timestamps as both source evidence and the strictly increasing decoder/presentation key.

Root reports c10 source attempt 4, store 1/channel 3, first failed `adapter/timestamp_invalid` at source-relative **1002342 ms**, with qualified R140 metadata `{kind: duplicate, delta_us: 0, delta_saturated: false}` and zero observation failures. Earlier quick five-stream/main-sub activity and ten rapid cycles had no timestamp failure; a later main focus held about306.8 s and returned to sub before this late failure. These timings establish sequence and the immediate equality boundary, not UI causation. C9's three coarse timestamp failures have no subtype evidence and must not be reclassified as duplicates.

R140 confirms equality of the current derived device timestamp and the prior accepted timestamp under the previously accepted original identity/context. The failing frame has not passed the adapter's later metadata/NAL validation, so this is not proof that it would decode. Neither raw tick equality, compressed payload equality, packet replay, B-frame behavior nor recorder clock adjustment was observed. C10 retirement was pending when this bounded analysis began; no completion or cleanup result is inferred here.

## Targeted APK evidence

Private reference: SuperLive Plus1.18.1 at `C:/wso-private/superliveplus/1.18.1-2026-09-27/jadx-full/sources/`. References below are class/method/line only; no decompiled source is copied into this report. JADX includes type-inference warnings in `VideoView.g3`, and native player internals were not inspected or executed.

| Location | Directly observed behavior | Limit |
| --- | --- | --- |
| `com/tvt/network/Frame.java:34`, `Frame.setInit` | Keeps device time and relative time in separate `m_lTime` and `m_lRelativeTime` fields, alongside frame index/stream identity and compressed bytes. | This Java holder does not impose strict timestamp ordering. The requested video frame is this `Frame` type, not a separately found `VideoFrame` class. |
| `com/tvt/video/VideoView.java:2803`, `g3`; especially2815–2824 and2863 | Ingress computes an absolute difference of nonzero relative times for its interval observation, updates the prior relative time, constructs `Frame`, then passes it to `GL2JNIView.l0`. It has no equality rejection at that timestamp observation. | This does not prove the unseen native player accepts every equal or regressing timestamp. |
| `com/tvt/video/GL2JNIView.java:544`, `l0`; `com/sdk/mediacodec/H264Decode.java:524` | Initializes/reuses its player and forwards the frame to native `NewPlayerDecodeOneFrame`. Java distinguishes decoder success/error, without a preceding timestamp-equality fence in this path. | Native pacing/reordering semantics remain opaque. |
| `H264Decode.java:190` onward, native callback dispatcher, events1/4/5/6/8/11; declarations near294/332/336 | Separates render requests, decoded packet observations, rendered timestamp pairs, frame interval, dropped-packet timestamp and wait/decode notifications. Render speed/wait controls are separate native interfaces. | These interfaces establish that ingress timestamps and player output/pacing are separate concepts, not a recovered native normalization formula. |
| `GL2JNIView.java:476`, `h`; `VideoView.java:3042`, `h`; `GL2JNIView.java:523`, `k` | Rendered timestamp pairs are forwarded to the view; render callback requests a draw rather than validating strictly increasing device timestamps. `VideoView.setWaitTime` at4407 separately forwards player wait control. | No actual Android execution or equivalent native player timing is claimed. |

Conclusion from these sources: the Java live path does not establish strictly increasing raw device timestamps as the live identity/order contract. It preserves two time fields and lets the native player manage playback. The c10 equality failure therefore justifies examining the web adapter assumption; APK source alone does not justify accepting regressions, missing timestamps or arbitrary media.

## Existing repository ordering and decoder contract

- `packages/core/src/wso_core/tvt/local_live.py:87` derives Unix microseconds by first truncating raw ticks to whole milliseconds, then multiplying by1000. Equal derived timestamps do not necessarily imply equal raw ticks. This is an existing codec conversion, not a newly proposed rewrite.
- The same parser at575 rejects a frame index less than or equal to the previously accepted index before constructing the private frame. Native identity, selected stream/media kind, sequence and original task checks remain independent. Thus wire frame order already has its own evidence; the timestamp is not an identity field.
- `native_source.py:163` currently rejects missing/non-integer/out-of-int64 or `timestamp <= prior` before later frame validation. At284–305 it commits that timestamp/ordinal and places the same timestamp into `ElementaryPacket`.
- `windows_decode.py:572–607` requires bounded timestamps, increasing ordinals, exact binding and unique/increasing continuous packet timestamps; its pending mapping is keyed by timestamp. The worker independently checks these conditions at `windows_decode_worker.py:139–173`, uses microsecond packet PTS and exact opaque `(timestamp, ordinal)`, and validates returned frame mapping. These are essential decoder correlation checks and should stay intact.
- `native_source.py:494–502` enforces global output PTS/ordinal across decoder epochs. `live.py:143–152` separately requires increasing delivered frame PTS/ordinal. `codec.py:75` sets the outgoing video PTS with a1/1000000 time base. None of these boundaries needs raw equality to become a permitted duplicate presentation key.

An exact old wire frame replay with a repeated frame index is already rejected by the private codec. Distinct increasing frame indices with byte-identical encoded bytes are a different question: the current evidence does not distinguish them, and payload equality by itself is not a proven replay test. No frame hashing, arbitrary encoded drop, source clock reset or replay heuristic is proposed.

## Minimal R142 candidate, pending Root's decision

Keep a private `last_raw_pts` and a separate lifetime `last_mapped_pts` in the original adapter. Preserve the early missing/type/int64/raw-regression guard, changing only equality from immediate rejection into a candidate for full validation. At the existing admission boundary, after unchanged proof/scope/identity/selected-kind/codec/dimensions/framing/NAL/configuration checks, assign a strictly increasing presentation timestamp and commit both clocks and the ordinal together. Failed validation must not advance any of them.

Root's candidate uses a minimum12µs presentation step to account for the existing90kHz RTP clock, rather than only the decoder's microsecond uniqueness:

```text
reject if raw is missing, invalid, or raw < last_raw
validate the complete candidate under the original scope and media guards
mapped = raw                              # first accepted packet
mapped = max(raw, last_mapped + 12)        # every later accepted packet
reject if mapped is outside signed int64
reject if its converted RTP tick does not increase (signed-zero caveat below)
commit raw, mapped and the next ordinal only after admission succeeds
```

This formula must apply to every accepted nondecreasing raw timestamp, not just equal pairs. Example: raw `[1000,1000,1000,1001]` needs mapped `[1000,1012,1024,1036]`; forwarding the final increasing raw value unchanged would regress presentation time. Real derived values are millisecond multiples, so a sufficiently long equality run can create the same issue before the next raw millisecond advances. The raw-regression decision must always compare raw to previous raw, never to the mapped clock. Ordinary100ms source advances pass through unchanged once the raw clock is ahead; an equality run creates only the necessary bounded-per-packet presentation offset, without assuming a recorder frame rate.

Use the mapped timestamp in `ElementaryPacket` and leave parent/worker pending-map uniqueness, opaque return proof, increasing PTS/ordinal, exact binding and original decoder retirement unchanged. Keep raw values in the original private source frame and scalar comparison state only; R140 failed-raw delta must remain relative to prior raw, not mapped PTS. Mapping spans dimension epochs without reset. No changed native packet/DTS/identity, new decoder, overlapping ownership, arbitrary encoded drop, observer authority or additional executor query is needed.

Guard priority needs explicit care: missing/invalid/raw-regression failure still occurs at the current early timestamp boundary. Equality becomes the sole candidate path that reaches later guards. A malformed or foreign equal-time candidate must still reject before mapping/state commit; it is not accepted because equality was observed. If Root requires the exact former first-failure reason for equal-time malformed inputs, retain the pending equality classification and project the original timestamp failure on rejection, without skipping later validation. Do not silently claim all old failure reasons remain identical when deliberately deferring equality.

### Concrete presentation-clock limit to resolve

Read-only inspection of installed aiortc found `codecs/vpx.py:245` converts video PTS to a90kHz RTP clock using `mediastreams.py:14–24`. Its conversion truncates the rational value to an integer. Therefore mapped microsecond PTS1,000,000 and1,000,001 are strictly increasing for the current decoder/source/track guards but both convert to RTP timestamp90,000. No codec execution was needed for this arithmetic observation.

The earlier `+1` microsecond candidate repairs only source/decoder uniqueness and is superseded in this proposal by Root's minimum12µs step. For nonnegative PTS, the exact conversion is `floor(pts * 9/100)`. Adding12µs advances the rational value by1.08 ticks, so the converted integer must advance by at least one tick. Example mapped `[1000000,1000012,1000024]` converts to `[90000,90001,90002]`. No float arithmetic is needed for this proof.

Signed zero crossing requires an explicit final rule because installed conversion uses `int(Fraction)` and truncates negative values toward zero: `-6µs` and `+6µs` both convert to0. Minimum12 alone is therefore not a universal signed-int64 guarantee. The conservative proposal rejects any non-increasing converted tick before committing state; Root may instead explicitly choose a bounded additional tick adjustment at this boundary. Ordinary positive recorder epochs are unaffected. Retain raw rejection and int64 overflow checks for the chosen rule. This is a concrete existing downstream constraint, not a broader native audit or a decoder-contract change. Source arithmetic still does not establish healthy actual VP8/browser delivery without the focused same-peer proof below.

## Proposed causal RED and verification cases — not executed

1. Two otherwise valid pictures with increasing wire frame indices and equal derived raw PTS currently fail at the adapter. Proposed RED expects both admitted with original binding, ordered ordinals, unchanged raw evidence and distinct mapped timestamps.
2. Equality runs followed by a small raw increase must preserve mapped strictness and raw-regression detection; include the counterexample above and realistic millisecond-aligned sequences.
3. Negative raw delta, missing/non-integer/out-of-int64 timestamps, foreign identity/stream/scope, malformed NAL/configuration and invalid dimension changes still reject. No rejected candidate advances clock/ordinal or creates successor resources.
4. Equal-time configured pictures during up/down dimension rotation retain lifetime clock/ordinal and the exact predecessor-retirement/epoch fence; late old output stays suppressed.
5. At signed int64 upper bound, any required12µs mapped increment fails closed without wrap, clock reset or partial state commit. Preserve current ordinal bounds.
6. Feed mapped packets through inert exact decoder response checks: timestamp-key uniqueness, same binding, exact opaque timestamp/ordinal and strictly increasing source/track delivery remain enforced. A forged/missing/duplicate decoder mapping still fails.
7. Exercise the actual installed90kHz conversion without a codec process:1µs ties, minimum12µs separation, short equality bursts, cumulative equality offset, positive/negative/zero boundary and overflow. Then one approved focused synthetic same-peer case should deliver the equal-raw sequence through the real codec/RTP path and verify received frame advancement and original peer/owner retention. These are future tests, not a benchmark or execution permission in this task. Do not label strict decoder PTS as strict RTP clock without this evidence.
8. Default-off observations remain optional and isolated; raw failure diagnostics compare raw values and callback faults cannot alter mapping/admission/custody. Existing bounded source/transition/pressure/owner tests stay applicable.

No tests, probes, decoder processes, benchmarks, SDK/RPC/SQL/Chrome calls or network research ran in this task. This is a proposal, not a causal RED execution record. Only targeted local reads, searches and file hashes were executed. A speculative `VideoFrame.java` lookup did not exist; the actual APK type used by the inspected path is `Frame.java`.

## Read baseline hashes

| File | SHA256 |
| --- | --- |
| `services/tvt-media/src/wso_tvt_media/native_source.py` | `3f6fcf8976cfe5b27876ed7a46c4e00a863908051db79837a517f98779aec340` |
| `packages/core/src/wso_core/tvt/local_live.py` | `e38c21e3b54109293add89c5602ab5650c19c77dddf6248c821b0da6045737b3` |
| `packages/core/src/wso_core/tvt/windows_decode.py` | `44251c4b675e8150ad6df630b872d832fe30361604b103e2407b226b133662ae` |
| `packages/core/src/wso_core/tvt/windows_decode_worker.py` | `77b5b1b555a9833bd1e2179531e0b32928677ba976ed948b7ae5a4155e0c9cc5` |
| `services/tvt-media/src/wso_tvt_media/live.py` | `0bae72e08bdb5829e23be43f3ece6b19c1be5fbacad6c35e9d43d970f8a2d85d` |
| `services/tvt-media/src/wso_tvt_media/codec.py` | `a43f3aeaece2ee3d976571d68b3f535d5c4e565fa64c8c7d2cbe220eaab651c6` |
| APK `com/tvt/video/VideoView.java` | `847520f26a64e700c5936eda9f7399b2a914f65105d0742b0b44ece5d8df4c56` |
| APK `com/tvt/video/GL2JNIView.java` | `f3a7db63e4dea10fe85ff79fda763930ee043b6aa205f371a23591ce00436f18` |
| APK `com/tvt/network/Frame.java` | `77476f161ecf9f9ed0bb36f548c8c516243cdd5ca30f51a8042f3d4b5b06ffd6` |
| APK `com/sdk/mediacodec/H264Decode.java` | `c18de775272714e933d06d31f13a9de57b676adf9616a6a1ed64868518500e51` |

## Priorities and open decision

Complete original c10 retirement first. Root must choose the R142 presentation clock rule, including90kHz quantization and equality failure-priority semantics, before any source change. The resulting small adapter change then requires causal source tests and independent review before a new immutable approval and bounded actual diagnostic. Neither this proposal nor APK source proves repaired playback, c9 failure subtypes or twelve-tile acceptance. Normal NO_SIGNAL semantics and selected kind2 behavior are unchanged.

Update log: **2026-10-06** — New read-only c10 duplicate-boundary diagnosis, targeted APK comparison and R142 mapping/test proposal recorded. Reuse before implementation and update with the actual chosen rule, source evidence and execution limits afterward. Overall execution authority remains `docs/service-analysis.md`.
