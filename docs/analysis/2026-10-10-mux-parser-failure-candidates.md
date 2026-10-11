# Mux feed rejection candidates after R199 actual trace

Analysis date: 2026-10-10, Asia/Seoul. Implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`,
with existing uncommitted Stage1/2/R193-R199. Root reports run05f2 under the
361-path R198/R199 closure retired normally. R200 deep trace is authored
concurrently by another agent. This read-only investigation changes only this
new report. No parser, helper, runtime, receipt, pin or prior report was edited.

Read before reuse with [service analysis](../service-analysis.md),
[cold SUB diagnosis](2026-10-10-cold-sub-startup-diagnosis.md),
[mux codec guide](../integrations/tvt-local-live-mux-codec.md), and
[legacy codec/APK guide](../integrations/tvt-local-live-codec.md).
Root owns AGENTS/service cross-links. Refresh after the actual R200 inner line
or a reviewed targeted change, preserving the conditional character of these
findings.

## Current causal boundary

The authenticated TVT service uses one shared original recorder transport and
mux codec for SUB slots, with per-slot cuts/credits and viewer-local decoders.
Dedicated MAIN has a separate native session. Root's actual R199 trace is
Core read_mux_frames2452/provider read_frames1244/IPC pump1356/_fail786, with
context pump1345/codec feed332. The service report confirms that feed332 merely
delegates to `_feed`; bounded traceback inspection truncated its inner branch.

**The actual inner line remains pending. No compatibility defect is selected.**
`feed` covers framing, slot/media checks, clock validation, authority callbacks
and encoded/scratch credit callbacks. Valid wire can fail from an authority
callback within feed. The outer trace alone is insufficient to call the event
a malformed or unsupported recorder packet.

## Source comparison and targeted controls

Existing APK evidence in the two integration guides supplies gg0/wz0/yz0/ep3/
y41/z41 layout, h4 ordered fragments, Z9 media/control dispatch and X7 fields.
This investigation reused those dated recoveries; it did not reopen private
APK binaries, consult native results by recency or establish an executed Android
serializer. The supported subset and original authority obligations remain.

Nine actual-source inert controls ran through Python `-B`, exit 0. Pure codec
controls used current synthetic fixture bytes; one used actual IPC parent/pump,
original callback RAM and fake original child owner. No DLL, recorder, DB,
browser, real process or broad suite ran. One first fixture invocation failed
before exercising application code because the synthetic ACK helper needed
`declared=0` for an empty body; the corrected complete comparisons passed.

| Concrete input/control | Legacy codec | Mux codec | Interpretation |
| --- | --- | --- | --- |
| Strict frame-index increase, raw device time regresses | accepts frame | SlotMediaClock raises LiveError | A mux clock gate exists here; the legacy downstream adapter can impose its own time checks. This is not proof of accepted legacy playback. |
| Near-limit ordered fragments, ordinary packet 1,048,529 bytes | accepts frame | credit mode direct feed rejects | Mux includes fragment headers and assembly/input in one raw budget. Intentional conservative bound, not permission to widen it. |
| Same large fragment through actual parent pump | not run | fails at pump1341, callback remains live | Production splits raw input to remaining capacity. Three pumps after second ingress reach zero capacity, rather than this test's direct feed length guard. |
| Unsupported ordinary notification command 65538 | UnsupportedLive | UnsupportedLive | No mux-specific dispatch difference established. |
| Standalone zero-length outer heartbeat | accepts | accepts | Both count/consume it without frame publication. |
| Heartbeat between ordered fragments | LiveError | LiveError | Both forbid ordinary packet interleaving during assembly. |
| Opaque version/encoding/declared-body header fields | accepts | accepts | Neither gates these ignored fields or outer magic. |
| Media for foreign channel | LiveError | UnsupportedLive | Both reject; error subclass difference does not grant channel authority. |
| Valid media, authorize callback becomes false | not run | LiveDenied inside feed | Feed failure need not be a wire-compatibility failure. |

Source branches for the next trace:

- `_feed:348-363`: exact generation, preserved ingress order and current input
  capacity. Owner-assigned ordinals remain monotonic; callback/IPC splitting
  preserves spans. Do not reassign them to pass a gate.
- `_feed:400-431`: fragment count/total/index/length, group/tag/order and final
  assembly sum. Neither codec allows unrelated ordinary messages between
  fragments. The mux length-plus-header bound is conservative storage policy.
- `_deliver:523-542`: preflight, authority before/after encoded reserve, checked
  bool reservation and parsing. `_move_fragment:475-502` calls scratch reserve/
  release; their original transport/host accounting can fail inside feed.
- `_preflight:548-577` and `_media:646-680`: registered active channel, routes
  0/2, route-2 task, stream2, live video frame type0, actual body/payload lengths,
  extensions, fourcc/dimensions/encryption and alignment padding. The legacy
  media reader checks equivalent fields for its selected stream/task/channel.
- `_parse:586-619`: pending original ACK sequence/command and task-correlated
  refusal. Post-ACK duplicate/control notification remains unsupported. The
  existing legacy supports close ACK1282 for its closing task; mux intentionally
  parks and never closes/reuses immutable upstream slots, so accepting close
  ACK in an active mux would need a separately established owner transition.
- `_parse:625-635`: registered active slot, exact task and SlotMediaClock. Clock
  requires nondecreasing raw time and strictly increasing signed frame index;
  both codecs require frame-index increase, while legacy codec alone does not
  enforce the mux's raw-time order. No clock reset on format rotation or park
  is authorized by the existing design.

## What the controls narrow

No difference was found in selected opaque header acceptance, normal heartbeat,
media offsets or unknown notification handling. Unknown channel/task/stream,
audio/playback/encryption and unsupported control commands fail the supported
subset intentionally. An actual deeper line plus narrowly projected wire
metadata is required before interpreting a rejected variant as APK parity work.

The direct fragment boundary exposes a real difference in admitted storage,
already documented by `test_credit_fragment_and_input_share_one_raw_budget`.
Actual parent pump first applies `take=min(len(raw), codec.input_capacity)`.
The inert production case fails with context pump1341/_fail786 and no callback
failure, whereas run05f2's recorded context reaches feed332. **This specific
fragment-capacity reproduction is therefore less consistent with the measured
feed failure path.** It is not an actual-cause reproduction. Parent cleanup
returned global credit usage to its initial value.

Clock regression is a concrete feed-internal difference, but no run05f2 raw
timestamp/index observation was inspected. Authority/reserve failure can also
originate inside feed. These candidates remain unordered until the deep trace.

## Minimum next evidence and repair boundaries

R200 should preserve enough inspected context depth to retain exact `_feed`,
`_deliver`, `_preflight`, `_parse`, `_media`, SlotMediaClock.accept and original
authority/credit callbacks, while keeping finite output/chain/inspection limits.
An exact file/function/line can select a targeted inert failing control without
exporting frame bytes, timestamps, GUIDs, exception locals or arbitrary text.

If that line still combines fields, a reviewed closed primitive probe may
project only its decision category: generation/ingress/capacity, fragment
ordering/length, control vs media, slot active/found, route/task/stream/video,
extension/encryption/format/padding, clock order, authority or credit callback.
Use finite allowed enums/counts/bools, existing original execution and bounded
publisher. No second parser, extra authority query or diagnostic reservation.

The next fix must follow the actual selected branch. Do not ignore unknown
packets, enlarge receive/host bounds, reset clocks, relax task/channel matches,
accept late ACKs or reclassify arbitrary errors to bypass the observed failure.
Cold SUB/format and parked MAIN actual playback remain open acceptance gates.
Normal retirement of a failed run does not establish a repaired stream.

## Exact inspected source and limits

| Source | SHA256 |
| --- | --- |
| local_live_mux.py | 07584407d8ec628eb0216a514b9f696ecde8f5af9ede51ce9f165cefd591af2b |
| local_live.py | e38c21e3b54109293add89c5602ab5650c19c77dddf6248c821b0da6045737b3 |

Verification comprised source/report reads and inline actual-source inert
controls via `.venv/Scripts/python.exe -B -`. Production authority callbacks
were fakes for comparison; the parent-pump control retained actual callback/
codec/credit logic with a fake original owner, normally closed the inert parent
and joined its Python watchdog. No private input, native file by recency, DB,
hardware, process operation, source change, commit or additional agent was used.
The actual inner condition and repair remain pending R200 execution evidence.

Update log: 2026-10-10 initial candidate preparation. Two deliberate codec-level
differences and matching selected branches characterized; actual parent fragment
boundary differs from the supplied feed failure trace. No cause or fix claimed.
