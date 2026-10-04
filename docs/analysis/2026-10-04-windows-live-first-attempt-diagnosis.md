# First continuous Windows live attempt: safe boundary diagnosis

Analysis date: **2026-10-04 (Asia/Seoul)**. Source baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, with concurrent uncommitted M3/M4
implementation changes. Root's frozen native receipt is identified here only by
the supplied prefix `79c9826...` (12 owned files / 14 dependencies); this report
does not independently establish its complete digest. The frozen native source,
tests and implementation report were not edited during the initial source-only
diagnosis; the later authorized correction after cleanup is recorded below.

Read [AGENTS.md](../../AGENTS.md), [the service report](../service-analysis.md),
[native session reference](../integrations/tvt-windows-live-session.md),
[native review](2026-10-04-windows-live-session-review.md), and
[historical capture/decode acceptance](../integrations/tvt-windows-live-acceptance.md)
before reuse. Root owns current service acceptance and the instruction bridge;
refresh this report after a discriminating observation or correction.

## Actual attempt evidence supplied by Root

Root reports that browser fixture run
`local-devices-2097208293564729805d4506a0fcd9b9` failed its first store1 channel
ordinal2 live request. Native generation `162b528ca33c45398e07e5488b129131`
reported accepted login/serial, 8 channels, 3/3 metadata replies, one live-open
attempt and accepted open ACK. It ended at live stage with failure `denied` and
ordinary received-byte counter10917. No continuous frame/session handoff or
browser playback is established from that receipt.

Those structural scalars were supplied by Root, not recovered here from private
device files. Root subsequently confirmed original runtime, Next and coordinator
exit0, media/API/worker settlement, private context removal, unchanged frozen
sources and zero known-private output hits. No source was edited before that
cleanup confirmation. Prior four-frame diagnostic acceptance on the same store
position remains historical evidence, not acceptance of this service attempt.

## Implemented boundaries and what the receipt establishes

The native worker's `serve_live` creates one first exclusive task from fresh
same-session metadata, publishes private setup, waits for its parent approval,
then performs live-open and source codec parsing. The parent verifies exact
private channel/raw/window/ordinal and callback generation, constructs its own
codec, and reconstructs typed frames from original bounded envelopes. Current
SQL admission is evaluated synchronously by the parent at these boundaries.

Actual live-open and its worker ACK establish that private setup approval and
the first live Send's authority check already passed. They do not establish
parent frame acceptance, first keyframe readiness, independent media authority
handoff, decoder delivery or Chrome playback.

The continuous helper does not increment the old diagnostic live frame/byte
counters. Therefore zeros in those fields cannot distinguish no media received
from a subsequent parent/frame/admission rejection. The ordinary counter10917
covers login/metadata accounting; it is not a continuous receive total.

`serve_live` maps both `AuthorityError` and `LiveDenied` to worker failure
`denied`. This collapses parent protocol rejection, external current failure,
cancel/expiry/pipe failure and worker callback/liveness fencing into one safe
value. `LiveParentAuthority.pump` separately collapses caught parser/predicate/
pipe errors to parent `protocol`; current callback errors are swallowed by
`ParentAuthority.check` and become `denied`. The earliest parent failure and
supplier exception category were not captured in the supplied actual evidence.

## Executed source-safe probes

Two direct `.venv/Scripts/python.exe` inline probes ran on the current source.
Both used invented bytes/events and existing inert test helpers; neither wrote
frozen files, loaded a vendor DLL, read device payloads/credentials, contacted
SQL/devices/network, or changed Git state.

1. Continuous **route0 plus fragmentation** was exercised through the real
   worker helper and both private IPC/source parsers, using the same qualified
   first-task route transformation as the existing diagnostic test. At the
   acceptance boundary: `open_ack=true`, `parent_failure=''`, `ready=true`,
   `queued_frames=1`, and parent/remote sequence27 matched. The probe then
   deliberately fenced/closed its in-process synthetic endpoints. This proves
   the tested route0/setup/sequence path can reach readiness; it is not real
   HEVC/device acceptance or an original-process retirement test.
2. A pass-through first-denial observer was exercised against an invented
   envelope before setup. It reported fixed reason `protocol`, allowlisted
   exception category `AuthorityError`, native source line298, no ACK/readiness
   and zero frames. The operation still returned false and stayed fenced.
   No exception text, traceback object, frame locals, body, selector or GUID was
   logged. This verifies that a caught exception's source line can be observed
   during `deny` without changing authorization behavior.

Source inspection also checked live route/ACK parsing, current admission and RPC
cancellation/deadline propagation. No concrete defect explaining the actual
failure was reproduced. The synthetic probe rules out a simple deterministic
route0/double-parser/setup sequence mismatch for its tested source shape; it
does not rule out actual media variants, callback overflow or service deadline/
SQL/cancellation conditions. No password/session/selector change is justified.

## Discriminating next observation

Root should independently review a bounded private pass-through observer before
one controlled authorized retry. Capture only the first failure, then discard
the instrumentation's temporary exception/callback references:

- Earliest parent failure reason, elapsed/remaining time and cancel/expired bits.
- Parent sequence, ACK/ready/handed-off bits, queue frame count and byte count.
- Current callback result or fixed allowlisted `LocalDeviceFailure` code/status;
  unknown exceptions receive a generic category. Rethrow unchanged and evaluate
  the supplier exactly once per original check; never retain it.
- During `deny('protocol')`, `sys.exception()` can identify an allowlisted
  exception category and the final traceback line in whitelisted native source
  files. Record no message, locals, exception/traceback object or private bytes.

This separates SQL/budget cancellation from parser/predicate/pipe rejection while
preserving fixed public failures. Device media must remain private and the
observer must not alter source frame validation, credentials, selectors, task
identity or admission. If parent failure is still absent, worker callback
failed/closed and fixed authority/liveness category would be the next narrow
boundary; do not infer it from diagnostic frame counters.

## Limits, priorities and open questions

Root's earliest actual parent denial is still unknown. Continuous native safety,
actual access-unit/PTS adapter acceptance, decode/browser delivery, orphan cleanup
and simultaneous two-device capacity remain unestablished for this attempt.
Priority is that safe first-denial observation, followed by a reproduced source
fix if the evidence requires one. Open product/runtime questions remain measured
startup budget, actual sustained rate/resource capacity and supported recorder
variants. This report provides no production enablement or release-ready claim.

Update log: **2026-10-04** — source-only first-attempt diagnosis; inert qualified
route0 readiness and safe denial-observer proof; no concrete cause or source fix.

## Later parent observation and inert callback pressure reproduction

Root supplied a later controlled observation from run
`local-devices-061e7103937847b38616a02a57f8d79a`, private `media-boundary.json`.
The first parent failure was `protocol`: `connection.poll` at source line270
raised `BrokenPipeError`. Setup and ACK were true, readiness/handoff false and
frame count zero. Cancel/expired were false. Native `run` took5234ms and current
checks ran440 times, with no false result or supplier error. These Root-observed
scalars show the child closed its pipe after ACK and before first-frame readiness;
the initial SQL/current/startup-deadline hypothesis is not supported for that run.
They still do not identify the child's first failure.

Readonly source inspection narrowed child `denied` to remote exchange
validation/I/O failure or live authority/liveness failure: callback failed/closed,
context mismatch or deadline. Source media parser errors ordinarily map to
`codec`, while its failed authority supplier can still produce `denied`.

A third source-safe inline probe reproduced a concrete callback pressure gap.
It sent an invented64KiB H264 keyframe in64-byte callback chunks every2ms,
after a separate ACK, through real `serve_live`/IPC code. The parent used the
supervisor's20ms pump cadence and a current callback returning true throughout.
Observed result: parent/worker ACK true; ready false; worker failure `denied`;
callback failed/closed true;255 retained chunks totaling16320 bytes;285 produced
chunks;138 current checks and zero false/errors. The worker and producer settled.
No real device/body/credential/SQL/network or frozen source was involved.

The continuous helper asks external authority before every callback **byte
chunk**, which makes dequeue throughput depend on the20ms parent pump cadence.
Its256-chunk cap can therefore be reached far below the1MiB byte cap and before
the first complete keyframe. The diagnostic helper dequeues locally at its faster
cadence. This is a reproduced source/input-shape gap, and its ACK/denied/not-ready
pattern agrees with Root's observation. **It is not yet proven to be the actual
recorder's cause**; the child callback/exception snapshot must distinguish it
from a remote exchange validation failure.

Recommended next observation: a Root-reviewed, explicit debug bootstrap after
original Job admission can install an exception trace only for exact live
`serve_live`/`exchange` functions. Record the first exception's fixed category
and whitelisted source line plus callback failed/closed/used/chunk-count/
context-matches-generation and remote sequence/deadline-remaining. Read no frame
locals, message/raw/request/setup/identity, exception text or payload. Create at
most one bounded protected private generation diagnostic file using existing ACL
helpers. This preserves frozen source and the public SafeResult schema. Root's
separate `-I -S` child cannot inherit a parent-only trace.

If that snapshot confirms chunk pressure, the narrow candidate correction is a
bounded FIFO coalescing dequeue for the live path after one current grant. Keep
the existing byte/chunk quotas and per-envelope/frame current checks, preserve
original bytes/order and source framing, and do not increase quotas or invent
payload/task data. A regression must reproduce this exact pressure and then
prove readiness with the bounded drain before a new reviewed actual attempt.
No implementation change or actual retry is authorized by this report alone.

Update log: **2026-10-04** — Root's second parent observation eliminates current/
startup deadline for that run; inert small-chunk pressure reproduces a matching
failure shape. Actual child cause and any source correction remain pending.

## Confirmed boundary and source correction — later 2026-10-04

Root subsequently reports that the actual child diagnostic confirmed callback
chunk saturation, rather than SQL authority or expiry, and that all three failed
actual runs were cleanly retired. This is coordinator-supplied evidence; the
independent correction reviewer made no SDK/device/DB/private-capture calls and
did not inspect actual payloads or recover the private diagnostic artifact.
The failed runs above remain failed execution outcomes; they are not converted
to acceptance by the source correction.

The native author added `CallbackOwner.take_live_batch` solely to continuous
`serve_live`: drain the existing bounded FIFO snapshot, preserve exact bytes/order
and accounting, and join outside the callback lock. Byte/chunk caps and later
source-envelope/frame current checks remain. Capture/inventory single-chunk
dequeue is unchanged. Independent bounded rereview returned **C0/I0/M0** and
fresh targeted regressions passed **two cases, 21 deselected, 3.08 seconds**,
including the exact invented 64 KiB / 64-byte / 2 ms producer / 20 ms parent
pressure shape reaching readiness with no remaining callback bytes/chunks.
See [the dated native correction review](2026-10-04-windows-live-session-review.md).

Priority is now the final corrected source receipt and Root's ordinary authorized
SDK retry, followed by actual decoded/browser/identity/lifetime acceptance. The
inert correction does not prove actual recorder throughput, continuous playback,
orphan safety, multi-device capacity or release readiness.

## Actual child cause and bounded correction

Root subsequently supplied protected child-observer facts for native generation
`c936cccfed5040c990ff9f97bf4e34d2`: `serve_live` line1055 raised `LiveDenied`;
callback failed/closed true;255 chunks/287643 bytes retained; context matched its
generation and local authorization stayed true; remote closed/expired false;
remote sequence205. Parent handoff was true at6125ms with464 current checks, then
the parent saw the closed pipe. These attributed Root facts confirm actual
callback **chunk-count** saturation below the byte cap, not SQL revocation or a
remote deadline. Prior before-first-frame attempts remain separate evidence.

After Root confirmed the run's original owners settled and the source window
was released, the continuous helper was changed to `take_live_batch()`. Under
the existing callback lock it drains one bounded FIFO queue snapshot and updates
byte accounting; joining occurs after lock release. Only the continuous live
path uses it. The diagnostic/inventory dequeue, callback256-chunk/1MiB cap and
per-envelope/frame authority checks remain. No bytes, frames, selectors or tasks
are rewritten/dropped and no quotas are increased.

TDD evidence: the new FIFO test failed because the batch method was absent;
the causal64-byte callback test failed at ACK/not-ready before the fix. After
correction both pass. The latter runs real inert helper/IPC behavior with an
invented64KiB keyframe,2ms callback segmentation and20ms parent pump. The exact
payload returns, produced byte count equals the original envelope length, and
callback used-byte/chunk counts finish at zero. Frame decode is not claimed.

Fresh `.venv/Scripts/python.exe -m pytest -q tests/contract/test_windows_socket.py
tests/contract/test_local_inventory_provider.py
tests/contract/test_local_live_provider.py --tb=short`: **346 passed in13.51s**,
zero failures/skips/warnings; the live file now has23 cases. Scoped Ruff on the
changed worker/test, strict mypy on all four native source modules and scoped
`git diff --check` passed. Root reports independent FIFO delta review **C0/I0/M0**
and both new regressions passed. Corrected-source rebinding and actual Chrome
acceptance are Root's next gates. This correction itself used no SDK, real
payload/credential, SQL/device/network call or Git commit.

Update log: **2026-10-04** — actual Root child observer confirms quota cause;
bounded live FIFO coalescing implemented after full cleanup, preserving source
bytes/order/caps; corrected actual acceptance pending.

## Follow-up after the post-reboot corrections — 2026-10-04

The queue-saturation and close-cancellation failures recorded above did not
recur in run `local-devices-30b1015b9f664d85908abc5400de9f2e` after the
liveness corrections (pooled media SQL, authority heartbeat, non-terminal
staleness, separate ingress/decoder owners, retained close tasks). Real video
played in Chrome for both stores, including concurrently, with clean stop,
reopen and runtime retirement. A different, later failure appeared: every
session stopped delivering frames 29–30 s after native open because the native
live loop never sends the N9000 keepalive that the official client sends every
6 s. Evidence, the refuted alternatives and ruling R111 are in the
[liveness review](2026-10-04-local-media-liveness-review.md), section 6.
