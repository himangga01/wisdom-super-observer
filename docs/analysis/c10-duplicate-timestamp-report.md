# R142 duplicate derived timestamp repair — author freeze

Date: **2026-10-06 (Asia/Seoul)**. Status: **implemented and verified in the scoped source/local synthetic tests; frozen for independent review**. No repaired recorder/browser acceptance or new immutable execution approval is claimed.

## Baseline and authority

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`, branch `codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`. The authorized stage-1/R137–R140 changes were already uncommitted. The pre-change `native_source.py` SHA256 was `3f6fcf8976cfe5b27876ed7a46c4e00a863908051db79837a517f98779aec340`. Root owns concurrent frontend work and canonical service/AGENTS/ledger integration. Other writers' files were preserved.

Read the shared analysis policy, project instructions, canonical report, R140 report, current media/WebRTC guides and the [R142 read-only diagnosis](c10-duplicate-timestamp-diagnosis.md). The diagnosis remains unchanged at SHA256 `4b7a43a29279be30baf91ad73cc7fafd29195b527eeb6adcc836a9ebde66958f`; its provisional 12µs/zero-boundary discussion is historical. Root subsequently chose a universal **24µs** minimum and true later validation reasons for malformed equal-time candidates. That final rule, not the earlier proposal, controls this implementation.

Root reports original c10 resources retired exceptionally after an exact original worker-handle signal: worker/conhost exited, coordinator exited 1 and was reaped, private state was removed, source was unchanged and known private occurrences were zero. Its preserved SQL outcome is **67 leases: 66 CLOSED, 1 STOPPING with cleanup unconfirmed**. This is a failed historical acceptance/retirement outcome; this source change does not rewrite it or authorize guessing cleanup. Only PostgreSQL remained running according to Root. This author performed no SQL or process-retirement action.

## Purpose and causal evidence

The service carries an original authorized recorder stream through private IPC, source validation, an isolated decoder and the original WebRTC peer. Native wire identity/stream and strict frame-index ordering are independent of derived recorder time. The private codec converts source ticks to whole-millisecond-derived microseconds. The previous adapter additionally required those derived values to be strictly increasing, and forwarded them unchanged as decoder/presentation keys.

C10 established one qualified immediate failure: source 4, store 1/channel 3, `adapter/timestamp_invalid` at source-relative 1002342 ms, with `{kind: duplicate, delta_us: 0, delta_saturated: false}` and no observation failures. This demonstrates equality at that boundary. It does not demonstrate payload replay, equal original raw ticks, complete NAL validity of that rejected picture, Android native timing behavior, or the cause of c9's earlier unclassified failures. The retained diagnosis gives targeted APK Java evidence and its native-player limits. No additional APK/native audit was performed during implementation.

## Implemented behavior

Only production `services/tvt-media/src/wso_tvt_media/native_source.py` changed. The adapter keeps `_pts` as the last accepted **raw derived device timestamp**, and adds `_mapped_pts` as the last accepted **presentation timestamp**. The first accepted packet retains raw time exactly. Every later accepted candidate uses:

```text
mapped = max(raw, last_mapped + 24 microseconds)
```

Missing/non-integer/out-of-signed-int64/raw-regressing input still fails at the existing early timestamp guard. Equal raw time now proceeds to all existing frame, scope, identity, codec, dimensions, framing, picture and configuration checks; upstream selected-stream and native proof checks are unchanged. No new executor, native, permission, SQL or observer predicate call is introduced. Packet/proof construction and mapped-overflow checking precede the clock/ordinal state commit. An overflow rejects without clamping, resetting, wrapping or advancing either clock or the ordinal.

The mapped timestamp enters `ElementaryPacket`; original source timestamps/media remain untouched. Existing decoder parent/worker checks still require exact binding, unique/increasing pending timestamp keys, exact opaque timestamp/ordinal return proof and valid dimensions. Global source output PTS/ordinal and peer delivery checks remain strict across dimension epochs. No native ABI, decoder/core, peer/track production, pressure/queue, authority, original owner or predecessor-retirement logic changed. No encoded frame drop, byte digest, replay heuristic or decoder overlap was added.

The mapping applies to every accepted nondecreasing raw timestamp, including later increasing raw values still behind the presentation clock. A realistic test admits 100 pictures at raw 1,000,000µs, reaching mapped 1,002,376µs, then raw 1,001,000µs maps to 1,002,400µs. A subsequent raw 1,000,000µs still rejects as a raw regression of -1,000µs. Ordinary 100ms raw advances pass through unchanged when ahead of the presentation clock.

There are two intentional distinctions in failure evidence:

- Equal-time malformed/foreign candidates now report their actual later validation reason, such as `identity_changed`, `header_invalid` or `parameter_sets_missing`; equality itself is now a valid timing candidate. Missing/invalid/regressing raw values retain early priority.
- Mapped signed-int64 overflow reports the existing coarse `adapter/timestamp_invalid`; it does not fabricate a raw regression/duplicate diagnostic at a different boundary. R140 raw failure deltas still compare `_pts` only. Production observation callback/schema/default-off behavior is unchanged. Historical closed `duplicate` observation records remain supported, although an otherwise valid equality no longer emits a failure.

## Why the step is 24µs

Installed aiortc converts outgoing microseconds to the 90kHz video clock using `int(Fraction(pts * 9, 100))`. A 1µs adjustment can collapse to the same RTP timestamp. The widest interval mapped to one integer is around signed zero: its width is less than 22.23µs because integer conversion truncates toward zero. A 24µs separation exceeds that interval and all other approximately 11.12µs intervals, so converted integer timestamps strictly increase across all signs, before the transport's existing modular RTP representation.

Tests use the installed exact conversion for negative values, crossing zero, zero, positive epochs and large signed values. No float approximation, source clock reset or special signed-zero branch is used in production. A mapping offset may accumulate during an extended equality run; it consumes constant scalar state and remains bounded by signed-int64 rejection. This rule establishes clock separation, not an inferred recorder frame rate or a guarantee of arbitrary equality-run duration.

## Test changes and actual verification

The causal RED was written before production implementation. `pytest tests/tvt_parity/test_local_media_source.py -q --tb=short -k presentation_mapping` first produced **21 failures**: equal inputs were rejected, later validation reasons were masked, and two overflow cases lacked the new mapped-state field. After the minimal implementation the same selection produced **21 passes**. These are source tests using controlled private frame objects; they do not newly prove the unchanged native wire parser.

Added/expanded coverage includes equal-derived-time inputs with increasing frame indices; raw frame preservation; long equality followed by raw increase behind mapping; raw-regression diagnostics after mapping; signed-zero exact RTP conversion; overflow without state commit; malformed equal-time identity/scope/codec/dimension/header/framing/configuration failures; and default-off/callback-`KeyboardInterrupt` isolation. Existing up/down resolution, exact predecessor retirement on stop/revoke/resume and suppression of late old-epoch output now also run with equal raw timestamps.

Three obsolete equality-rejection expectations were narrowly updated: the direct source diagnostic case, the contract observation adapter case, and the native-adapter no-revival case. The latter now uses a true raw regression. The transition invalid-timestamp fixture likewise uses a regression. A new direct controller test retains compatibility for historical `duplicate,0,0` events. `observation.py` was not changed; only its focused contract test was adjusted, as reported to Root before editing.

Executed with the existing `.venv/Scripts/python.exe`:

| Gate | Actual result |
| --- | --- |
| Source/transition/pressure/observation selection below | **163 passed, 2 identity probes deselected, 33.83s** |
| Existing focused portable decoder boundary selection below | **12 passed, 60 deselected, 1.62s** |
| One actual synthetic same-peer VP8/RTP test below | **1 passed, 0.65s** |
| Ruff check, five changed Python paths | **All checks passed** |
| Ruff format check, same five paths | **5 files already formatted** |
| Strict mypy with silent imports, `native_source.py` | **Success, no issues in 1 source file** |

Commands:

```text
-m pytest tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_media_format_transition.py tests/tvt_parity/test_local_media_pressure.py tests/contract/test_local_media_observation.py -q --tb=short -k 'not live_self_identity_probe and not node_self_identity'
-m pytest tests/tvt_parity/test_windows_decode.py -q --tb=short -k 'continuous_pending_mapping or exact_output_schema or foreign_packet_binding or continuous_bad_input'
-m pytest tests/tvt_parity/test_local_webrtc.py::test_same_vp8_peer_presents_equal_raw_timestamps_as_distinct_rtp_frames -q --tb=short
-m mypy --follow-imports=silent services/tvt-media/src/wso_tvt_media/native_source.py
```

The one actual loopback test uses real aiortc VP8 encoding, SRTP transport and client decode. It obtains timestamps/ordinals/binding from the production adapter, then constructs synthetic RGB at that boundary; it does not decode recorder H264/HEVC. Four equal-raw inputs map to 1,000,000/1,000,024/1,000,048/1,000,072µs and are received on the same peer at relative 90kHz PTS **0/2/4/6**. Two later normal timestamps preserve delivery ordering. Original peer identity, delivery ordinals and peer/source closure are asserted. The test ran once and passed; no codec benchmark or extra actual codec run was performed.

The targeted portable decoder cases verify exact binding, pending-map bounds and response schema against unchanged production code. No Windows native decoder acceptance flag was enabled. Source tests use inert decoder owners. Ruff initially corrected one local import order and requested `pairwise` in a consecutive-value test; both were corrected before final gates. No post-verification Python changes were made.

No SDK, recorder, SQL, Chrome, service, native fixture, dependency, Git, receipt or approval operation occurred. No subagent was used. A first guide patch missed an existing Unicode heading and made no change; the corrected patch only inserts the dated sections, preserving prior evidence.

## Frozen authored files

Hashes are exact current on-disk bytes. The earlier diagnosis snapshot and existing pinned reports remain unchanged.

| Path | SHA256 |
| --- | --- |
| `services/tvt-media/src/wso_tvt_media/native_source.py` | `e72c3aa8d451971e26863cfc2fef79c31a2a69fce082a067780ff5d4a2c361cc` |
| `tests/tvt_parity/test_local_media_source.py` | `fb8f70c305c76f7a3a2629083cbc6de15ca88e4cd3a4d23b643594bd32bdf097` |
| `tests/tvt_parity/test_local_media_format_transition.py` | `77fe301023c7d7f432b0bd240dc5bfdf0ebe2c39364c96c42a16f4bb90182415` |
| `tests/tvt_parity/test_local_webrtc.py` | `28cabc23886bbf248391173712951edef69c9b5d284ee8218c86a0162259ebfc` |
| `tests/contract/test_local_media_observation.py` | `fc01d008d8ee0ab2d7b771580bfb06ba3511a97f430095d314576749b215762a` |
| `docs/integrations/tvt-local-media-service.md` | `c55ef0770702471fe96b2cf3d1189108c9658052dd266d357cf3798fec640b36` |
| `docs/integrations/tvt-local-webrtc.md` | `8587df4034a78a4905189e206da9527abe6384c6d6fd9efcb4ca07f8fba13940` |

## Remaining questions and next boundary

Independent review must assess the frozen narrow delta, especially validation-before-commit, raw versus mapped state and lifetime mapping across rotations. Root then handles the new source/approval closure and decides any bounded actual run. Source/synthetic success does not establish that the rejected c10 picture had valid remaining payload, fix c9's unknown subtypes, resolve the historical cleanup-unconfirmed lease, or achieve twelve-tile acceptance. Raw regressions and missing timestamps deliberately remain terminal. No further product question is silently resolved by this source gate; actual recorder stability remains an execution question.

Update log: **2026-10-06** — Root's final R142 24µs rule implemented, scoped TDD and one synthetic peer proof completed, guides updated and seven authored source/test/guide files frozen. Read this report before future mapping changes and update affected evidence afterward. Canonical overall status remains `docs/service-analysis.md`.
