# Local N9000 live wire codec

Analysis date: **2026-10-04, Asia/Seoul**. Root supplied original executable baseline
`756946ca73cff31d7ebb23141873088b470a96b4`, documentation HEAD
`36fc954e4754d69721596e190c35f9cf14de3e4c`; Git was not used for either task.
This follow-up starts from the three file identities in Root's qualified receipt
`2dd5afe51b3a1450b10b5bac4839b6486279cf0f3a1200b95aae9ab15c245df2`.
The original 217-entry packet and that receipt remain unchanged. Initial R96
execution scope remains **stream1**, subject to independent Root integration review.
This is an independent source implementation for a future Windows socket
provider integration. **MATCHED=0; release_ready=false.** No device, credential,
network, ADB, vendor binary, decoder or provider execution occurred.

Start later reviews with this guide and the
[local connection source analysis](tvt-local-device-connection-source.md).
Refresh affected source identities and verification outcomes before reuse.
Root owns the canonical service report and AGENTS entry point updates.

## Purpose and boundary

`packages/core/src/wso_core/tvt/local_live.py` provides exact live request
serialization and a bounded, private raw stream parser. It has no socket,
authentication, channel acquisition, permission resolver, decryption or decoding
implementation. Its only project import is the public `FrameTimestamp` value type
in unchanged `frames.py`, SHA-256
`e5cd9dc73c8a0602e83e958ff2f5b36971b894b224c63498f9b6227f94a31b9f`.
It does not import `local_n9000.py`, whose startup handling is being changed
independently. Its inspected snapshot is historical read context, not a frozen
integration requirement.

The default admitted media order is `gg0 -> wz0 -> yz0 -> ep3 -> y41 -> z41 -> compressed
bytes`. The explicit exclusive-first-task option also admits route0, with ep3
immediately after wz0 and no routing header. A raw-specific bounded field parser follows the exact APK readers and
complete X7 consumers. It does not call the post-native envelope parser or rewrite
wire magic to satisfy that parser. No arbitrary decoder callback is accepted.

## Exact source serializers

The approved SuperLive Plus 1.18.1 APK SHA-256 is
`f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.
Its `classes5.dex` SHA-256 is
`abcb01e8f6319f2f9c24a6559999baa324b5fc90ad4ee248eb7b699644addcc5`.
These identities were freshly checked against the approved October 2 APK.
The September 27 JADX classes are the source reference for this identical DEX.

| Layer | Wire layout and source |
| --- | --- |
| gg0 | 8 bytes: little-endian int magic 825307441, signed int inner byte length. `cw3.m7:6940–6965`. |
| wz0 | 16 bytes: LE short **3**, byte **2**, byte **1**, LE int command, sequence, body length. Body length excludes yz0's 72 bytes; outer length includes all actual bytes. |
| xz0 | 52 bytes: request GUID16, logged-in session `e3` GUID16, channel GUID16, byte2, three zero bytes. |
| yz0 | xz0 + task GUID16 + action byte1(open)/2(close) + three zero bytes =72. |
| ll2 | channel GUID16 + nl2 reserved52 + LE int stream1/2 + channel-number byte + audio byte0 + reserved2 =76. |

GUID input is **GUid.l wire bytes**, equivalent to Python UUID `bytes_le`:
Data1 low32 LE, Data2 signed-short bits LE, Data3 signed-short bits LE,
Data4 eight unchanged bytes. XML uses uppercase `GUid.c` formatting with braces.
Java byte casts preserve the low8 bits. The helper deliberately accepts channel
number 0–255, refusing broader signed-int values rather than silently truncating.
This channel number is `r7 -> iz0.r`, not the public one-based channel position.
All four GUIDs must be nonzero, exactly16 immutable bytes; this is helper policy.

`H5 -> jb` (`cw3:2511–2588,3875`) uses command1281 to open and1282 to close.
Its `z3=true` selects stream1, false selects stream2. For **open only**, when
`R3>=5` and `z3=false`, `kb` (`cw3:6641–6688`) selects **command1285**, with:

```xml
<?xml version='1.0' encoding='utf-8'?><request version='1.0' systemType='NVMS-9000' clientType='SYS'><destId>{CHANNEL-GUID}</destId><taskId>{TASK-GUID}</taskId><chNo>NUMBER</chNo><audio>0</audio><streamType>2</streamType></request>
```

The string is ASCII and thus byte-identical under the selected Android UTF-8
default. Close always uses the legacy1282/ll2 form with the original task/stream.
Peer **R3** controls this selection. Greeting **Q4**, logged-in **S4**, and the
outgoing constant version3 are distinct; callers must not substitute one for
another. `peer_capability` is admitted as positive signed-short 1–32767.
Sequence is an integer 0–2147483647; bool and numeric coercion are refused.

## Receive subset and control responses

`cw3.h4:6358–6428` supports partial ordinary frames and og0 fragments. The
helper supports both with explicit quota, length and ordering checks. A fragment
outer length is signed -1; its six LE signed ints are group, count, total inner
length, one-based index, fragment length, tag. Group/count/total/tag must remain
stable, indexes must be contiguous, and the final sum must equal total. No
interleaving with ordinary packets or another fragment sequence is allowed.
Zero outer length is a counted heartbeat. Every malformed or unsupported
received variant permanently fences the task and clears buffered bytes.

The default admitted **media** routing header is wz0 byte2 followed by yz0. Z9 selects
52 bytes for route1 and72 for route2 before X7; its default offset is0. Routes0/1
lack a wire task GUID: source channel dispatch alone cannot distinguish a delayed
old task from a replacement task on the same channel. Route1 remains unsupported;
route0 requires the explicit narrow first-task contract below and is otherwise unsupported.
Route2 must carry the exact retained task GUID. Actual channel association is
**ep3.e -> cw3.s7 -> iz0.a**, not the routing header's channel echo. The requested
channel must match ep3.e. The original transport owner/generation binds the session;
the current authority callback must verify that binding for the immutable identity.

For these selected consumers, Z9/X7 ignores routing session/channel/request echoes,
routing action/reserved fields, and wz0 version/encoding/declared-body length.
They are preserved privately for media, never treated as status, current authority
or identity evidence. Outer gg0 actual length and raw ep3/y41 lengths still bound
every read/allocation. A stale ignored wz0 length neither allocates memory nor
overrides the actual outer frame boundary.

**Success response command prefixes are 0x10000000.** Exact
`ServerNVMSHeader.a:2701` returns2 for that range; 0x20000000 returns3 and goes
to the error path. The helper accepts `0x10000501/0x10000502` acknowledgements
only for the one pending1281/1282 command, exact sequence and original connection
generation. The acknowledged action comes from the command and must match the
pending open/close state. Duplicate, wrong-sequence, wrong-command, wrong-generation,
error and unprefixed responses fail closed. Source Z9's legacy ACK branches consume
no body or routing fields at all. Therefore ACK route byte, echoes, embedded action,
version, encoding, declared length and actual opaque body are ignored after outer
length/quota validation. Body contents cannot manufacture a success status. The
owner must allocate sequences uniquely across its outstanding/replaced tasks; the
codec has no cross-codec sequence registry. ACK handling never rebinds a task.
**An acknowledgement grants no authority and is not frame or decode acceptance.**

1285 replies use `oz0` in Z9, including error536871008; they are explicitly
unsupported by this minimal receiver. Both request forms are byte-proven, but
a complete stream2/capability>=5 control lifecycle remains an integration gap.
The provider must not silently discard this failure. Stream1's legacy request
remains source-selected even when R3>=5.

## Proven X7 branch and deliberate limits

Complete X7 code item SHA-256:
`b4d4c6d589dd5c4e4d425d73014ecdf3e97a98ba98db94dd151b01323510c8a3`.
The review read all2,337 code units, all1,208 instructions, branches and both
typed try handlers from the W04 Fix1 complete disassembly. A fresh check matched
every instruction byte/offset/boundary and branch target to the approved DEX.

| X7 offsets | Selected behavior |
| --- | --- |
| 0000–0048 | ep3(44), then y41(24), following the routing header selected by Z9. |
| 0051/0054 ->071e | ep3 kind1/2 selects live video. Require the requested stream to match. |
| 0723–072e | y41 frame type0 only; ep3 GUID resolves channel. Helper requires its exact channel GUID. |
| 0767–081f | Positive extension length selects z41; format and dimensions update channel context. |
| 082e–0850 | Copy exactly y41 real payload length after the extension. |
| 0853–086f | Nonzero z41 encryption flag branches through ga. Helper rejects all nonzero flags, including short prefixes; no decrypt fallback. |
| 0870–087e | Key frame if ep3 key marker1, otherwise y41 IP marker signed -128 (raw0x80). |
| 0880–08a4 | Round payload size up to4; any residual metadata would enter Y7. Helper rejects residual metadata. |
| 08a5–08de | Publish compressed payload with device and ECMS timestamps, dimensions, frame index and source frame markers. |

Kinds6/8 (audio/talk), kind7 (playback), nonzero live frame type, unknown codecs,
negative signed extension lengths, encrypted prefixes and Y7 extras are not
implemented. Positive signed dimensions and known H264/H265/HEVC fourccs are
required. The APK treats non-H264 as another codec class; the helper rejects
unknown fourccs. A first frame needs an explicit valid format; later unextended
frames inherit only this task's validated format. Raw extension bytes, including
fourcc and reserved tail, remain available through a private wrapper.

There is **no SHFL gate** in the raw parser. Complete X7 never reads ep3.a
(magic), ep3.b (version), ep3.i or y41.d. h4 reads gg0.b and does not inspect
gg0.a. Arbitrary values in those opaque fields are retained as received, without
rewriting them or calling them verified protocol constants. Source-reader byte
agreement alone is not the basis: the complete field consumers and selected
dispatcher branches establish their non-use. Actual wire magic remains unobserved.
Frame indexes must strictly increase in the signed-int domain; wrap, reset,
duplicate or reordering fails closed. Raw timestamp ticks are preserved;
unsupported negative Java-long time ranges have no derived Unix timestamp.

## Receive predicate audit

This covers every receive guard. Source describes consumed fields; owner denotes
isolation/authority policy; bounds denotes helper resource/framing policy; subset
denotes unimplemented behavior. Removed predicates are not vendor requirements.

| Rule | Source or policy basis and disposition |
| --- | --- |
| Open/closing state, no recursive feed, exact integer generation | Owner; same serialized original connection, no reopen after close/failure. |
| Immutable bytes; input+partial buffer, received lifetime and packet/heartbeat quotas | Retained bounds; no coercion, silent reset or unbounded allocation. |
| gg0 length0/-1/ordinary; ordinary minimum16, configured maximum, partial waits | Source h4 framing plus bounds; other negative/oversized lengths reject. |
| gg0 magic | Removed: h4 consumes gg0.b but never gg0.a. Outgoing constant unchanged. |
| og0 count/index/total/length bounds; stable group/count/total/tag; contiguous order; exact final sum; no interleaving | Source assembly fields plus stronger retained bounds/owner policy. Group/tag consistency and strict ordering are helper checks, not claimed APK checks. |
| Inner header minimum16 | Bounds and exact wz0 structure size. |
| ACK success class/command | Source ServerNVMSHeader.a and Z9; only0x10000501/502. Error/body bytes never become a success status. |
| ACK pending command/action state, exact sequence, no duplicate | Retained owner policy explicitly required by Root. Generation checked before parsing. |
| ACK route2, echoed GUID/action/reserved zeros, empty body, positive version, encoding1, declared-length equality | Removed: selected Z9 ACK branches consume none. Actual outer framing/quota bounds remain. |
| Media command65537 | Selected Z9 dispatcher; other commands/prefix variants,1285 replies and playback remain unsupported subset. |
| Default media route2,72 routing bytes, exact yz0 task | Owner task fence at source-backed field offset; unchanged. X7 does not itself compare the task. Route1 remains unsupported. Route0 only under the explicit exclusive-first-task/accepted-open-ACK contract below. |
| Routing session/channel/request echoes, action/reserved fields | Removed/ignored: selected Z9/X7 do not read them. Original owner/generation binds session, yz0 binds task, ep3.e binds actual channel. |
| Media wz0 version/encoding/declared length | Removed: encoding never passed by h4; selected Z9 branch ignores version and body length. No read/allocation depends on those ignored values. |
| ep3 kind equals requested stream1/2; y41 type0 | Source0051/0054->071e and0723; exact requested stream is owner scope. |
| ep3.e equals requested channel | Source0728->s7 matches iz0.a; owner restricts to the authorized request. |
| Minimum68 ep3+y41 bytes; signed body>=24; exact actual body span; nonnegative payload; extension+payload within span | Bounds around exact source field readers. Full body equality and no extra envelopes remain helper policy. |
| ep3 magic/version/other value; y41 reserved | Removed/opaque: no corresponding X7 reads. Original68 bytes retained; source version metadata is signed-short. |
| Signed-positive extension<=127; length12 or>=17; declared span in bounds | Source signed byte and z41 base/conditional fields; truncated Java reads are rejected. |
| Encryption flag0; known H264/H265/HEVC; positive dimensions | Source nonzero encryption branch unsupported; known-format/dimension whitelist remains helper subset. |
| First explicit format; task-local carryover thereafter | Source live format context plus isolation; no guessed default or cross-task reuse. |
| Residual no greater than four-byte alignment | Source0880–089a Y7 boundary; additional metadata unsupported. Padding retained privately. |
| Strict signed frame-index increase | Retained stale/order policy; X7 forwards but does not enforce it. Wrap/reset unsupported. |
| Current read+live authority before media return; callback-close fence | Owner policy; parser/ACK/login never supplies authority. |

Outgoing constructor/request bounds are unchanged helper policy: positive
signed-short R3, stream1/2, channel0–255, nonzero immutable GUIDs, positive generation,
nonnegative signed-int sequence, packet maximum, one lifecycle and current authority.

## Owner integration contract

### Explicit taskless first-task option

`LiveCodec(..., stream=1, exclusive_first_task=True)` is an **owner assertion**, not
proof produced by the parser. The owner must retain a fresh original socket and
generation with exactly one first task/open, never replace/reuse that task or
connection, and close after its bounded four-frame attempt. Literal bool is required;
the default isFalse. True with stream2 is unsupported. Creating another codec with
the same old socket/generation cannot be detected locally and violates this contract.

Only after this codec accepts the exact pending1281 success ACK (same command,
open state, sequence and external generation) may route0/65537 enter X7's source
offset0 path. Sequence0 on subsequent media is not an ACK and is not a task ID.
The original immutable task/session identity stays attached as **owner context**;
no wire task is claimed or synthesized. The actual ep3 channel, stream1, generation,
all raw bounds and current read+live authority checks still apply. Duplicate open
or reopen attempts on the opted-in codec fail closed. Close clears the opt-in.
Route2's exact wire-task check and default strict behavior are unchanged.

Source basis: h4 assembles og0 fragments then dispatches the unchanged wz0 route;
Z9 initializes i7=0 and only adjusts it for routes1/2 before X7. X7 reads ep3/y41
at that offset and resolves ep3.e through s7. H5->jb allocates a new task GUID and
the app can replace tasks; that general replacement flow does **not** justify
taskless association. Fresh exclusive first-task lifecycle, matching prior ACK,
and current original-owner identity/authority are the explicit alternative binding.
There is no server/cloud/transport/login-derived authority grant.

`source_header` for route0 is the exact16-byte wz0 header; route2 retains wz0+yz0.
No incoming byte is rewritten and no fabricated routing header is inserted.
The owner/integrator must independently review this change, then replay its saved
capture offline with zero sends before any new device attempt. This source author
read no private capture and made no network/device call.

1. Retain the existing original native/socket owner and serialize all operations
   with authority changes and media delivery. This class is not a transport mux
   and does not install thread locks, receive loops or callbacks.
2. Establish current read AND live authority for the exact device/channel,
   external generation, session and task. Login, inventory, transport connection
   and acknowledgements are insufficient. Pass an authority callback that checks
   the current owner state every time; it must return literal `True` to admit.
3. Construct `LiveIdentity(generation=..., session=..., channel=..., task=...)`
   using private exact wire GUIDs and a fresh task. Create `LiveCodec` with
   current peer R3, source channel number and chosen stream. Supply a fresh
   request GUID and current owner sequence to `open`.
4. Send `PrivateLiveBytes.private_bytes()` only on that owner's transport.
   The bytes must come from the original connection whose generation and session
   the identity names. Never relabel another socket's bytes with this generation.
   Demultiplex unrelated commands in the owner; this parser accepts only its
   explicit live subset. Feed immutable bytes with the exact generation.
5. `feed` checks current authority immediately before returning any private
   media batch. Callback failure or callback-triggered close discards it.
   This return is the codec's publication boundary. If delivery/decode is queued
   or occurs later, the owner must recheck current authority immediately before
   that later publication while retaining original-owner serialization.
6. `close_request` fences media before returning source1282 bytes. `close()`
   fences without needing authority or emitting bytes, including denied/revoked
   cleanup. Close/failed tasks cannot reopen. Discard retained frames and replace
   the task/generation for the next session.

Private identity, wire and frame objects use slots, fixed private reprs,
immutable fields (except parser state), no dataclass conversion, no `__dict__`,
and refusal of pickle. JSON refuses them by default. Explicit private accessors
are for trusted transport/media code; this is not protection from arbitrary
Python introspection. Never log exceptions with locals, raw bytes, identities,
callbacks or debug dumps. Fixed typed errors suppress wrapped exception causes.
Only `LiveSummary` counts, codec and dimensions are intended for generic output.
`source_header` retains exact wz0+yz0 bytes for route2 or wz0 alone for opted-in route0,
`source_envelope` exact ep3+y41,
`source_extension` and `source_padding` retain their original bytes, and
`source_outer_headers` retains the ordinary8-byte header or all ordered32-byte
fragment headers. These fields are private wrappers, not generic output fields.

Default bounds:1MiB per outgoing packet/incoming buffer/reassembled packet,
32MiB received lifetime bytes,4,096 ordinary packets/heartbeats and256 fragments
per assembly. A feed chunk plus retained partial input must fit the buffer bound;
the owner must size its reads accordingly. Lifetime quotas end the parser rather
than silently reset. These are helper policy limits, not vendor wire constants.
Retained raw fragment headers add at most32 times the configured fragment-count
limit; payload, assembly and returned private copies mean these are wire-byte
limits rather than an exact process RSS limit.
The owner must impose connection-wide aggregate quotas across codecs, elapsed
deadlines, cancellation, task uniqueness and isolated stores/devices.

## Verification and next acceptance

Current tests cover request selection/widths, both stream selectors, partial and
multiple frames, ordered fragments, invalid lengths, quotas, source control
classes, wrong generation/task/actual ep3 channel, revocation and close during
publication, stale indexes, format carryover/isolation and private exports.
The historical57-test coverage also included conservative routing-session echo
rejection. In the source-fidelity87-test coverage, wire session echoes are intentionally
ignored; current original-session binding remains the original owner's authority
callback obligation, not a wire-echo rejection assertion.
The original recorded new-file run was57 passed. The source-fidelity follow-up
records87 targeted tests, including9 explicit M1 boundary cases, corrected ACK/
opaque-field behavior, retained task/channel/generation/current-authority fences,
raw truncation/length/extension checks and private raw-field preservation. No
broad old suite was replayed. Final exact check outcomes are bound in the new READY.
The subsequent taskless-first change adds16 focused cases. Its final targeted run
passes41 cases with62 deselected; the87-test source-fidelity result remains historical,
not a claim that the expanded whole file was replayed. Ruff and strict mypy pass.

An inert JDK21 oracle compiled exact copied APK structure classes, with four
small dependency stubs and no cw3/application/native initialization. Forty full
request packets match Python byte-for-byte, including channel byte boundaries
127/128/255, both capability branches, both streams and close. Exact
ep3/y41/z41 readers match payload, dimensions, index and timestamps. The control
classifier is the exact copied method; selected X7 key/alignment gates are
explicit transcriptions, not execution of the entire X7 method.

Original evidence lives in ignored `W08-local-live-wire-evidence`. The new
`W08-local-live-source-fidelity-evidence` holds the follow-up readset, oracle,
receipts, exact preimages/delta and current3. Root must review the corrected
receive policy and remaining1285/taskless-route limits before integration.
Priorities remain actual current permissions, response shape, media/decode
acceptance, connection-level quotas and provider integration. No test here proves
device compatibility or usable decoded frames.

The new oracle compiles exact selected Z9 ACK/live-dispatch branches and copied
gg0/wz0/ep3/y41/z41 readers: four opaque ACK cases, route offsets0/52/72 and two
raw magic/version/header variants match Python. Complete X7 consumer non-use is
verified against the approved DEX/readset separately. The entire X7 application
method and vendor code are not executed by this oracle.

The historical review I1 remains: early original exploratory reads existed only
in the tool transcript, and the first two original Java runs reused nested
receipt names. Outer results survive but cannot reconstruct the missing earlier
nested argv/timing/output custody. New receipts do **not** repair that history.
Root's original acceptance was explicitly qualified, not full deliverable custody
compliance. Preserve the original217-entry evidence and qualified2dd5 receipt.
This follow-up has a separate packet with command capture in place before tests;
its initial brief bootstrap read remains in the tool transcript. M1 is addressed
by explicit changed group/tag, short final sum, heartbeat exhaustion and partial
fragment header/payload fixtures before receive admission was changed.

No Annex B framing, complete access-unit boundary or decoder PTS choice is proved
for actual CCTV here. X7 publishes payload plus device and ECMS timestamps; these
are retained separately. A decoder requiring one complete access unit and an exact
PTS needs a separate source/actual integration decision. Do not silently select a
timestamp or equate a parsed payload with decoder-ready video.

Update log:2026-10-03 — original source implementation and qualified review.
2026-10-04 — source-fidelity audit, M1 tests, opaque ACK/magic handling, raw-specific
reader and retained owner/task/channel/authority fences; later M2 summary correction.
2026-10-04 — explicit exclusive-first-task route0 option after matching open ACK;
focused synthetic checks only, independent review and owner offline replay pending.
