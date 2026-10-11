# Immutable local live multiplex codec

Analysis and implementation date: **2026-10-06, Asia/Seoul**. Task 1 of the
approved Stage 2 plan (`122796f6`), approved design SHA-256
`036908e32cbb72024e340d8a3fc3e298838e69e1c19db14427a2fafbad5e53ee`.
Baseline: HEAD `6436748` plus retained, reviewed Stage 1 changes through R143;
Root supplied source tree `220d6d03ee4cce02f9a4f14757c4677e0c34a134`.
These four Task 1 files are new, uncommitted work. This is an offline source
implementation, awaiting independent review; it is not native or twelve-camera
acceptance. Reuse this guide with [service analysis](../service-analysis.md),
[legacy live codec](tvt-local-live-codec.md) and the approved Stage 2 design.
Root owns canonical report and AGENTS handoff updates.

## Purpose and architecture

`local_live_mux.py` provides a separate `MultiplexLiveCodec` for one retained
original session/generation. Every registered base slot is stream 2 and has one
immutable channel/task pair for that epoch. No channel/task/number is reused,
including after tombstoning. Sixteen registered physical slots is a local cap;
cross-original, viewer and SQL admission caps belong to later tasks.

`local_media_mux_types.py` supplies immutable private epoch, slot, ingress and
validated-frame values; purpose/scope/grant/reservation/cleanup values; and the
original-budget, recorder, viewer and media-executor Protocols needed downstream.
Runtime imports are stdlib plus the existing pure wire codec and its timestamp
value. Contract/service types appear only under TYPE_CHECKING. Native bootstrap
does not acquire SQL, Pydantic, contracts or bridge dependencies.

The existing `LiveCodec` is unchanged. Its exclusive-first-task fence remains
strict. The mux reader has its own slot state and media parser; it does not call
legacy `_media`, rewrite envelopes, manufacture wire task fields or reset legacy
capture counters to simulate a continuous transport.

## Targeted APK source facts

Read-only reference: retained 1.18.1 JADX, dated 2026-09-27, under the approved
private APK evidence location. No vendor sources/binaries are copied into this
repository. APK/DEX identity and complete X7 disassembly evidence remain in the
legacy guide; this task reused that evidence and did not repeat full DEX recovery.

| Source | Confirmed fact and implementation consequence |
| --- | --- |
| `fu3.I5/J5:2714–2718`; `cw3.I5/J5:3922–3970` | Base methods are empty interfaces; concrete methods iterate channels through `jb` on the same client. This supports multiple tasks on a connection, not a wire incarnation fence or unlimited capacity. |
| `cw3.jb:2512–2588` | Maintains the channel/task map; normal APK replacement closes/reopens tasks. Mux deliberately excludes that replacement lifecycle. Stream 2 selects `kb` when peer R3 >= 5; otherwise legacy 1281/ll2. |
| `cw3.kb:6641–6685` | Creates the task, writes yz0 and the 1285 XML with channel GUID/task/chNo/audio 0/streamType 2. R3 is distinct from greeting/login version. |
| `cw3.Z9:5136–5145,5187–5211` | Class 3 dispatches to m8. Class-2 legacy 1281 has no status-body requirement. 1285 oz0 code 0x20000060 is an adaptation warning, not refusal. |
| `cw3.m8:6969–7122` | Refusal low 28 bits identify the failed 1281/1285 command. yz0 task correlates the pending task; oz0 at payload offset 72 supplies busy/denied/other code. Sequence is not its correlation rule. |
| `cw3.Z9:5338–5345`; `cw3.s7:3094–3104`; retained X7 complete evidence | Route 0 starts ep3 after wz0, route 2 adds yz0; ep3 channel is the dispatch identity. s7 finds inventory by channel GUID. X7 consumes raw ep3/y41/z41 video fields and preserves source timestamps. |

Task 1 preserves those source distinctions. Success ACK requires one pending
connection command and its exact increasing sequence; class 3 refusal requires
the pending command and task. A valid refusal fences the epoch with the existing
safe `LiveRefused` reason. Unknown/uncorrelated control, duplicate ACK, wrong
generation, route 1, unknown channel, wrong stream, route-2 foreign task or
malformed envelope fences the entire codec. Routing echoes are not authority.

For **route 0**, there is no wire task. The identity attached to the private
frame is explicitly the immutable registered original-slot assertion, enabled
only after that slot's accepted open ACK. For route 2, the actual retained task
field must also match. Registration or ACK does not grant viewer publication.
The `authorize(slot)` callback must check current channel control/retention;
viewer permission is independently required at later publication boundaries.

## Ingress, clocks and bounds

Ingress spans are positive unsigned 64-bit ordinals assigned by the future
native owner before application-visible copies. A chunk carries its original
first/last span. The parser tracks retained byte segments, including partial
outer headers, envelopes and ordered og0 fragments. A completed frame includes
the earliest original input span and latest contributing span. When one chunk
contains multiple packets, its whole span is conservatively retained for each
affected packet; no cut is moved forward by splitting/copying bytes.

This codec does not create admission cuts or discard pre-cut viewer media.
Tasks 2/3 preserve callback/IPC provenance and establish cuts, and Task 8 must
require the key picture and required parameter sets entirely after the cut.
Returned-but-uncommitted batches remain subject to those checks. Ordinals prove
local ingress ordering only; opaque SDK/network/device capture age is unknown.

`SlotMediaClock` accepts signed 64-bit raw device microseconds, requires raw
nondecrease and strict signed 32-bit wire frame-index increase, maps presentation
time to `max(raw, previous_mapped + 24)`, and increments a checked unsigned
64-bit slot ordinal. Overflow or regression permanently fails the clock and
codec. Slot format/order/time survive viewer parking because parking does not
replace or reset this codec. Every parked frame must still be fed/validated;
later adapters reuse the sealed mapped time/ordinal rather than remapping it.

Bounds: each input chunk and ordinary outer envelope <= 1 MiB, one fragment
assembly <= 1 MiB minus outer header, <= 256 fragments, and <= 4096 retained
input-span segments. Fragment headers retain at most 8192 bytes. Input buffer
and assembly each have independent bounded retention; completed results are
bounded by the current input plus a prior partial assembly. There is no capture
lifetime limit of 32 MiB or 4096 packets. Cumulative received bytes and packet
counts are checked unsigned 64-bit values and never silently reset. The inert
4200-picture run exceeds both old capture defaults and finishes with empty
input/assembly buffers. Downstream encoded/global/callback credit accounting is
still required by later tasks; these parser bounds do not replace it.

## Pure capabilities and remaining integration obligations

Values have private reprs, reject serialization and remain immutable. Mux wire
frame/ACK constructors require the private wire seal; grant/custody values have
distinct domain seals and retain a private issuer token. Caller bools or an
arbitrary object cannot substitute for a seal. SQL native_generation UUID is
separate from wire generation int. Master login fields never add channel/live
permission. Viewer and epoch cleanup receipts are different classes; settled
flags alone cannot construct either public capability.

These are internal Python capabilities, not a sandbox against arbitrary code
executing in-process. Task 4 must retain exact budget/original owner identities;
Task 5 must mint grants only after SQL admission and verify exact grant type,
issuer token, scope and expiry. Task 3 must enforce TRANSPORT (epoch only), slot
control/retention (exact slot), and VIEWER (slot plus registration) envelopes.
Never use subclass acceptance or a generic True across those purposes.
`NOT_CREATED` requires the registered constructor's no-original/partial-owner
settlement proof; Task 1 implements no such native custody assertion. Likewise,
a ViewerCleanupReceipt cannot release a parked physical original.

Priority before enabling: independent Task 1 review; callback/IPC and cut proof;
SQL mint/current/cleanup and original custody; per-channel backpressure and
retention; then the approved owned-recorder/Chrome acceptance. No new product
question is introduced here. Recorder support, actual twelve-stream resource
headroom, main/sub coexistence and real original retirement remain execution
gates, not conclusions from APK iteration or inert packets.

## Verification and update log

- Watched RED before production files: `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_live_mux.py -q`: **18 failed**, 0.25s, explicit assertion that the immutable mux implementation did not exist. All failures were tests, not collection errors.
- First GREEN: new plus unchanged legacy codec tests: **154 passed**, 0.21s.
- Final focused command: `.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_live_mux.py tests/tvt_parity/test_local_live.py -q`: **182 passed**, 0.23s (46 mux, 136 legacy).
- Ruff check of both new production paths and the new test: **all checks passed**.
- `.venv/Scripts/python.exe -m mypy --follow-imports=silent packages/core/src/wso_core/tvt/local_live_mux.py packages/core/src/wso_core/tvt/local_media_mux_types.py`: **no issues in 2 source files**.
- Isolated `.venv/Scripts/python.exe -I -S -` imported both modules with only `packages/core/src` prepended, asserted no SQLAlchemy/Pydantic/contracts/bridge modules or site-packages modules: **passed**.
- Initial scoped static checks caught incorrect TYPE_CHECKING import locations, one local variable narrowing issue, import order and test literal style; all corrected before final gates.
- 2026-10-06: Task 1 source/tests completed and frozen for Root's fresh independent review. No full suite, SDK/DLL, SQL, camera, decoder, Chrome, process/Job retirement or resource-sizing execution occurred. Existing native qualification receipts are not refreshed by this work.

Initial Task 1 source SHA-256 (historical reviewed baseline before R147/R148):

| Path | SHA-256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_live_mux.py` | `7e4b977e36cd970ee8aa3d5cef2fa06c8e3b176663eceb3b453da48d740f0bae` |
| `packages/core/src/wso_core/tvt/local_media_mux_types.py` | `e9132f593b72f538a729a5f872fe45d51a1afb87a923da1f9b70ba2299d16bb8` |
| `tests/tvt_parity/test_local_live_mux.py` | `d348642d705ba80a1a74ebe27e851ea1d168a5ac5648e9cb82f0ec6cdcc199b4` |
| Existing unchanged `packages/core/src/wso_core/tvt/local_live.py` | `e38c21e3b54109293add89c5602ab5650c19c77dddf6248c821b0da6045737b3` |

## R147/R148 — admission before frame allocation (2026-10-06)

Task 3 integration identified that a coalesced callback could contain more
than sixteen tiny pictures: checking credit after the old multi-result `feed`
would allocate all those frames first. Root authorized this narrow correction
to the previously C0/I0/M0 reviewed Task 1 codec. Core types, native callback,
IPC and worker files are outside this correction's ownership.

Constructor additions, all optional:

```python
reserve: Callable[[MuxSlotIdentity, int], bool] | None = None
reserve_scratch: Callable[[int], bool] | None = None
release_scratch: Callable[[int], None] | None = None
```

Without `reserve`, feed preserves the original multi-result behavior and its
historical parser budgets. With `reserve`, `feed(chunk, generation=...)` and
`drain(generation=...)` return at most one genuine frame or ACK. `drain` retries
retained input without inventing an ingress span or increasing received bytes.
`pending_bytes` is the exact sum of input, fragment assembly and retained outer
header byte lengths. `input_capacity` is the remaining shared 1 MiB raw budget
(zero after close). `blocked` signals a denied frame or transfer-scratch claim.

Complete media is classified by real slot/channel/stream/task and raw framing
bounds before the callback. The callback receives **len(raw inner packet) plus
len(all original outer headers)**. This accounts for the payload, routing and
media headers, extension and padding subsequently retained in the frame. The
codec uses memoryviews and individual field copies after credit; it does not
make a whole-envelope copy before credit. Slot authority runs before and after
the reservation, then again before returning. Reentry, close or denial fences.

False retains the exact original raw head, complete fragment assembly and
ingress provenance; no frame object, format, clock, slot ordinal or parsed-packet
counter advances. Input byte counters still count newly accepted ingress.
ACKs do not claim encoded-picture credit. A successful claim may precede a later
parse/authority failure: **Task 3's exact pending ledger must refund it on any
feed/drain exception and transfer it only with the returned frame**. This was
explicitly agreed with the Task 3 implementer; coupled execution is that task's
verification, not claimed by this codec-only report.

R148 explicitly counts the transient duplicate during fragment transfer.
Before extending assembly or outer headers, the paired scratch callbacks reserve
the exact fragment payload length plus its 32-byte original header. No slices
copy that source: extends read memoryviews. Old input is consumed before refund.
If transfer fails, raw storage is cleared before refund. False leaves the head
unchanged and blocked for later drain; no hidden second raw head or FIFO exists.
Credit mode without scratch hooks fences on fragment transfer. Logical retained
raw data remains <=1 MiB; explicitly reserved temporary transfer scratch is
<=1 MiB, giving a bounded raw-transfer peak <=2 MiB per original. These are byte
payload accounting bounds, not Python interpreter/object allocator overhead.

The scratch owner must check original transport authority around host admission
and count these bytes against the shared 1 GiB host ledger. Incomplete fragments
need not expose a complete channel, so codec slot authority cannot replace that
transport check. The raw callback 256-chunk/1 MiB budget, parser raw budget,
transient scratch, classified per-slot 16-picture/4 MiB budget and IPC conversion
storage remain separate charges. Pending pressure deadlines, cancellation and
release of returned frames are Task 3 responsibilities. This codec never calls
unknown raw chunks sixteen semantic pictures.

Focused correction evidence:

- Eight causal credit tests failed before the constructor/API existed (0.21s).
- Drain's new internal sentinel initially let public `feed(None)` through;
  a focused test failed (0.15s), then the public exact-type fence restored it.
- Two R148 scratch tests failed before scratch hooks/mandatory fragment charging
  (0.16s). The test observes the actual assembly `extend` with an outstanding
  exact scratch claim, including a >1 MiB transfer peak bounded by 2 MiB.
- An injected transfer failure exposed refund before raw storage discard:
  focused RED (0.15s), then close-before-refund GREEN.
- Final new+legacy codec selection: **194 passed in 0.31s** (58 mux, 136 legacy).
  Scoped Ruff passed; scoped mypy reported no issues in the changed codec.
- Intermediate 189-pass/1-failure was a fixture building an oversized chunk
  outside the codec; corrected to exercise the aggregate raw-budget fence.
  Later initial Ruff flagged one unused suppression, removed without behavior
  change. No remaining known focused failure.

This correction adds no native, SQL, browser, actual memory/RSS sizing or recorder
acceptance. It awaits Root's fresh scoped review and Task 3 composition evidence.
The local handoff is `task-1-credit-fix-report.md` in the Stage 2 execution ledger
directory; it records the corrected source hashes and exact commands.
