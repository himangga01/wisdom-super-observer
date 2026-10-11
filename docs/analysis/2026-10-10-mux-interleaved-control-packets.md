# Interleaved N9000 notifications: full live path versus mux

Analysis date: 2026-10-10, Asia/Seoul. Implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`
plus retained Stage1/2/R193-R200 changes. The tree was already modified. Root
reports actual e0b6 runtime retirement is in progress. Existing active pins and
reports remain frozen; this investigation writes only this new report.

Read before reuse with [service analysis](../service-analysis.md),
[earlier codec comparison](2026-10-10-mux-parser-failure-candidates.md),
[N9000/APK source guide](../integrations/tvt-local-n9000-codec.md), and
[live codec guide](../integrations/tvt-local-live-codec.md).
Root owns AGENTS/service reconciliation after original retirement. Update
after fixed header evidence, reviewed implementation or actual acceptance.

## Finding and current actual boundary

**A full source-path compatibility gap is confirmed for three recognized
ordinary notifications. Actual attribution still requires command/route and
shape evidence.** Root's deep e0b6 READ trace reaches codec `_feed445`,
`_deliver542`, `_parse621`, where the command/route unsupported guard raises.
This selects `command != 65537 or route not in (0,2)` after ACK/refusal handling;
it does not select timestamp regression or raw-memory capacity.

The service streams privately registered recorder media through authenticated
Core/native/media owners. Legacy single live preserves a greeting-bound N9000
parser for control notifications while a separate LiveCodec consumes media.
Mux closes that N9000 parser after login/inventory setup and sends retained raw
ingress to MultiplexLiveCodec, which lacks the notification branch.

The prior report correctly compared the two **codec classes** rejecting
unsupported commands. It did not cover the extra notification intercept in
the complete legacy worker. The new whole-path controls resolve that narrower
comparison; prior report evidence remains preserved as history.

## Implemented source evidence

- `windows_socket_worker.py:1243-1253` extracts an ordinary envelope's command.
  For exact commands2561/2562/2563 and `fragmented=false`, actual `serve_live`
  calls the original `stream.feed(raw)`, requires exactly one notification,
  and continues without forwarding it to LiveCodec or parent media authority.
  Original `authority.require("frame")` precedes dequeue (`:1237`).
- Original legacy login/inventory passes its same greeting-bound `stream` to
  `serve_live` (`:1973-1982`). The test helper's default unbound N9000Stream is
  a narrower fixture and cannot demonstrate production notification admission.
- Shared mux setup validates original login/inventory and binds its epoch,
  clears credential references, then calls `stream.close(); stream=None`
  (`:1889-1912`) before native mux service. Its raw dispatcher does not perform
  legacy notification validation. Original bytes reach mux `_parse621`.
- `local_n9000.py:177-240` defines the exact accepted ordinary control shape;
  `_drain:318-398` additionally validates outer framing and actual body length.
  A greeting-bound stream permits positive signed-short peer versions; its
  unbound version3/login-only profile rejects these unsolicited notifications.

## Recovered protocol and exact existing scope

The canonical N9000 guide records dated APK1.18.1 recovery and independent
primitive-reader oracles. No private APK body was reopened in this session.

| Exact command | Actual body bytes | Existing source meaning and validation limit |
| --- | ---: | --- |
| 2561 / 0xA01 | 92 | APK Z9 has no matching switch/body parser and returns without effects.92 is a previously root-observed strict opaque bound, not a recovered schema. |
| 2562 / 0xA02 | 40 | ml2 reader consumes GUID16 plus six signed32 fields. APK uses a field for a channel-relative callback; existing diagnostic receiver suppresses effects. |
| 2563 / 0xA03 | 36 | il2 reader consumes two GUIDs and signed32 recording state; existing diagnostic receiver suppresses recording-state callbacks/effects. |

For this bounded supported family, preserve all existing checks:

1. Exact command, with action nibble0. Reply/error prefixes are not equivalent.
2. Sequence0, route/flags0 and encoding0.
3. Peer version1..32767 in the already authenticated, greeting-bound profile.
   It is not required to equal greeting version or outgoing version3.
4. Ordinary outer magic825307441; actual outer length16+body; declared body
   length equals actual body and exact family bound above. No trailing body.
5. Existing original transport generation/current/cancel/budget checks. A state
   notification grants no slot/viewer permission and renews no deadline.

The stream parser independently supports ordered fragmented notifications, but
the complete legacy live intercept explicitly excludes them. Do not broaden
mux fragment admission merely from the lower parser's standalone capabilities.
Unknown command families and malformed recognized controls remain failures.

## Executed full-path controls

Actual `windows_socket_worker.serve_live` was invoked using the established
inert native surface/authority/callback and invented clock from the keepalive
fixture, but with its parser factory bound to an explicit synthetic Greeting.
The application function was not replaced. For each family, input was a valid
open ACK, exact ordinary notification, then valid media in one retained chunk.
Current actual MultiplexLiveCodec was compared with the same notification after
its own exact accepted ACK. No native process, DLL, DB, browser or device ran.

Results through `.venv/Scripts/python.exe -B -`, final complete run exit0:

| Control | Result |
| --- | --- |
| 2561,92 ordinary bytes after ACK | Legacy validates/skips control and forwards exactly ACK+media; mux raises UnsupportedLive. |
| 2562,40 ordinary bytes after ACK | Same confirmed full-path difference. |
| 2563,36 ordinary bytes after ACK | Same confirmed full-path difference. |
| Eleven malformed variants for each family,33 total | N9000Stream rejects all: sequence, flags, encoding, version0/32768, declared mismatch, short/long body, reply/error prefix and wrong magic. |
| Valid two-part fragmented2563 | Bare N9000Stream accepts; actual legacy serve_live forwards first partial fragment, then returns codec failure at completed unsupported notification. It never applies the ordinary notification skip. |

Three fixture corrections preceded the final complete run: the mutation helper
initially reused its command parameter, a media fragment helper could not split
a short notification, and the fragment expectation omitted the legitimately
forwarded first partial fragment. Corrected controls used a valid26+26-byte
split and asserted the actual forwarding/terminal behavior. These preliminary
fixture failures are not application acceptance or production regressions.

## Proposed narrow validation/consume behavior

Root is adding a fixed unsupported-command/route measurement. First establish
the actual rejected command and route. If it selects2561/2562/2563 at route0,
capture/check only additional fixed primitive header/body-length facts needed
to prove the exact existing shape. Do not infer shape from command alone.
Command65537 with route1 or an unknown command needs separate source evidence.

Conditional minimal fix boundary: validate the exact ordinary control family
inside the existing mux framing/dispatch path, using one shared pure primitive
shape validator derived from the accepted N9000 checks. Do not introduce a
second media framer, invent a greeting or route/session field, or decode/copy
private state bodies for diagnostics. Original mux setup already establishes
authenticated original lifetime; controls cannot mutate that authority.

After positive shape validation, consume this one complete original envelope
and its original ingress spans, count it under existing received/packet budgets,
and continue to the next packet. Produce no MuxAcknowledgement or frame, reserve
no encoded media credit, change no slot format/clock/ACK/task/grant/cut, execute
no recording/channel callback, and reset no expiry or pressure clock. Bounded
control flooding still consumes the original budget and finite storage.

The internal dispatch outcome must distinguish **consumed control** from
`None`, which `_feed` currently interprets as blocked/backpressure and leaves
the head retained. Returning None for a validated notification would stall and
repeat it. An internal sentinel or explicit classification can represent
consumption without changing the public frame/ACK tuple protocol. Preserve
one-item credit-mode media handoff and original raw/fragment accounting.

Do not drop raw chunks by command: chunks may include partial controls, media,
multiple packets and pre-cut data. Do not clear parser storage or relabel
ordinals, refund viewer-owned frames, skip unknown routes/commands or run state
effects inferred from notification GUIDs. Original transport checks before and
after pump remain required; controls are connection-level events, not synthetic
channel authority. Fragmented recognized controls retain the current failure
scope unless separately justified and reviewed.

## Limits and continuation

Source hashes observed after the final control invocation are below. Root's
diagnostic author is changing the codec concurrently; these are current
inspection hashes, not a claim that they equal the active frozen runtime tree.

| Source | SHA256 |
| --- | --- |
| local_n9000.py | d53238cf2d6eda58995d1dc0c427ca28d226f7c44b730f85411d3c4b6bd509f4 |
| local_live_mux.py | bbccd5496bf7866bc0990dc1cd56ced24a8662baf7bf580093c6a987d07fd5fd |
| windows_socket_worker.py | d5c581950c4f6f1132506e48d6331fe845f66be6f6ad4235f06a98c438de159b |

Source comparison proves a known interleaved control family is handled by the
full legacy path and rejected by mux. It does not prove e0b6 received that
family or those lengths. The actual command/route is pending Root's fixed
projection, and no code change or repaired playback is claimed here. Source
review, fresh immutable closure, cold SUB/parked MAIN replay and normal original
cleanup remain necessary acceptance stages. The private state bodies are not
exported. Root is retiring the original runtime; this agent performed no
runtime/process/DB operation and changed no active pin or previous report.

Update log: 2026-10-10 initial full-path source diagnosis and37-case control set
(three ordinary family comparisons,33 shape negatives,one fragment scope).
Conditional mux/legacy integration gap proven; actual attribution and fix await
the exact fixed header evidence.
