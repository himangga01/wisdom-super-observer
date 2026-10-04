# Private Windows NetSocket provider

Date: 2026-10-03 Asia/Seoul. Executable baseline
`756946ca73cff31d7ebb23141873088b470a96b4`; documentation HEAD
`36fc954e4754d69721596e190c35f9cf14de3e4c`. This implements an isolated private
transport candidate. Root's final Fix3 provider passed load/initialize and both
supplied-device connect/exact64-greeting probes after exact R90 admission. The
two store1 credential trials then remained nonterminal: the first stopped at a
2563 notification and the second at a 2561 startup frame. Neither established
accepted/rejected login; video remains unverified. `MATCHED=0`,
`release_ready=false`. The [canonical service report](../service-analysis.md)
remains the shared service authority; Root updates it after independent review.

The parent module `wso_tvt_bridge.windows_socket` validates source review,
fourteen exact package identities, ASCII absolute private storage, reparse
components and a protected current-user/SYSTEM-only full-control ACL. It starts
one `CREATE_NO_WINDOW` worker with private bounded duplicate-key-rejecting JSON
on stdin. Native stdout/stderr go to newly owned private files. No serial or
credential enters argv, environment or safe results. The separate worker loads
absolute `NetSocket.dll` using cdecl CDLL and flags `0x900`; it checks actual
mapped package module paths and identities, binds the fifteen accepted exports,
and constructs only the recovered physical observer object8/table16/slot+8.

The accepted ABI, login codec and inventory Root receipt SHA256 values are pinned
in the parent; their complete current own2/login3/inventory3 identities must match. Root must
create a private source-review JSON receipt with exactly `status`, `files`,
`dependencies`, `critical`, `important`, `minor`. Status is
`ACCEPTED_WINDOWS_NATIVE_PROVIDER_ROOT_REVIEW`, all three counts are integer0.
`files` maps exactly the four owned provider paths listed in `OWNED` to
`{"bytes":N,"sha256":"..."}` for the current bytes. `dependencies` maps the
three accepted ABI/login/inventory receipt paths plus `packages/core/src/wso_core/tvt/local_bootstrap.py`
and `packages/core/src/wso_core/tvt/device_qr.py`, plus the current R90 runtime Root
receipt path, to the same identity objects.
This receipt is a Root review gate, not an author READY document. It requires
protected current-user/SYSTEM ACL storage. Every execution rechecks the gate
in the parent and worker. Do not put private values in that receipt.

Current codec dependency is
`W04-local-n9000-login-field-reviewed-root-receipt.json`, exact SHA256
`03f6adbac6499d8a48bc9342c5a29dadc3ec0fd871eb042559f27c1ffb2d971e`.
It pins the approved startup and success-field semantics across module/test/document
identities. The older codec receipts remain historical; Root must rebind the private source receipt to the
new codec dependency and current provider4 before an actual continuation.

Python private usage is `WindowsSocketProvider().run(ProviderConfig(bundle,
staging, review_receipt, deadline_seconds), PrivateRequest(mode, country,
serial, username, password))`. Paths are `pathlib.Path`; bundle/staging must be
absolute ASCII. Root supplies a restrictive, protected staging directory outside
Git with inheritable current-user/SYSTEM full-control ACEs. Newly owned generation
directories/files protect that inherited DACL and verify it; they are retained,
never recursively cleaned up. Receipt/greeting/reply original file identities
are checked. Root controls storage retention after confirmed child completion.

CLI: run the installed module `python -m wso_tvt_bridge.windows_socket` with one
private stdin JSON object. Its exact top-level keys are `config` and `request`.
`config` contains `bundle`, `staging`, `review_receipt` strings and
`deadline_seconds` number1–120, and optional `runtime_receipt` private absolute
path. `request` contains `mode` and optional `country`,
`serial`, `username`, `password` strings, plus private boolean `metadata_read_opt_in`. `load` and `initialize` reject all
device fields. `connect` requires country and ASCII alphanumeric serial1–63;
`handshake` adds exactly supplied ordinary codec credentials, without password
defaults or retries. `inventory` additionally requires the exact private boolean
`metadata_read_opt_in=true`; absence, false, or a non-boolean is denied. Other
modes reject a true opt-in. This is an operator-authorized diagnostic read, not
the service actor/tenant policy. Use a private pipe rather than shell literals. The CLI emits
only the safe typed summary and will retain original child ownership until reap
and writer completion are confirmed. A pending original owner fences another
attempt on that provider. Root must use one retained provider per operator lane.

Modes are staged: `load` validates DLL attach/exports/layout only; `initialize`
calls Initial(0,0,NULL,0) and attempts Quit; `connect` sets NAT2, connects the raw
uppercased serial (DLL owns MD5), waits for output status1 AND CheckConnectState,
then reads the cached greeting once and admits exactly64 bytes through the
approved codec. RegisterNode precedes Start. `handshake` sends exactly one
LoginHandshake request, accepts callback chunks through N9000Stream and checks
the expected sequence/generation. Positive Send means enqueue observation;
missing reply is failure. Typed rejection/unsupported branches are safe statuses.
`reply_accepted`, `proof_verified` and `key_extracted` remain separate;
`authorized`, `live`, `quiescence_verified` are always false.

`select_trusted_nat2` uses the approved resource selector with an explicitly
synthetic context solely to extract NAT2. KR selects AP's
`cli-nat20.autonatap.com:7968`. The synthetic Android path/identity/network fields
are discarded and never reach Windows NAT. This does not recover Android
SINGLE_ID or actual saved preferences. Windows NAT generates its own identity.
There is no browser-controlled host, public route, database or authority grant.

Callbacks validate this/context/ID/generation, positive bounded length and pointer,
copy into a nonblocking bounded queue and return consumption. They perform no
native reentry, decoding, file write or wait. Queue overflow/foreign ownership
fences the connection. Native pointer validity remains unproved. The custom
destructor slot never frees or invokes a vendor destructor. DLLs, object/table/
callback/context and Send buffers are retained until helper process death.
Stop/Destroy/Quit are orderly attempts with no callback join claim. Parent hard
deadline ends the original process by its retained Popen handle, then confirms
reap and writer completion. Kill/reap uncertainty retains the original passive
owner; no process discovery/tree kill/repeated kill is used. The CLI waits on it.

Author checks use inert fake symbols/callbacks and an original Python sleep
child. The author executed no actual DLL load, Windows ACL API probe, device, network, private supplied
QR/password, ADB, browser or database ran. Frozen commands/results/readsets and
the complete absent-preimage diff are in the SDD's
`W04-windows-native-provider-report.md` and linked READY packet. Static types and
these checks establish source behavior only. MFC attach/service compatibility,
dependency loader side effects, native pointer bounds, actual ordered callbacks,
wire interoperability, identity/authority joins and live media require Root's
separate reviewed execution.

R90 permits exactly two Root-reviewed preloaded Microsoft runtimes through an
explicitly supplied private `runtime_receipt`, whose complete bytes must hash to
`77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d`:

| DLL | Version | Bytes | SHA256 |
| --- | --- | ---: | --- |
| vcruntime140.dll | 14.42.34438.0 | 120400 | 052ad6a20d375957e82aa6a3c441ea548d89be0981516ca7eb306e063d5027f4 |
| vcruntime140_1.dll | 14.42.34438.0 | 49776 | 6a99bc0128e0c7d6cbbf615fcc26909565e17d4ca3451b97f8987f9c6acbc6c8 |

Both map entries are required and restricted to exact receipt paths, metadata,
current file hashes and actual mapped absolute filenames. No installed
Python/global CRT ACL is changed. The original R85 receipt remains preserved
as historical evidence; it is superseded by R90 for current worker execution.
Original fourteen package files remain required; all other mapped DLLs must be
the exact package originals. Safe results disclose `runtime_substitutions`0–2,
`development_debug_only=true`, `production_ready=false`. No generic caller
override is accepted. Root checked26 referenced vendor imports on the first CRT
and the sole referenced import on the second CRT using existing handles without
vendor loading in those checks. Python MSC1943 versus runtime14.42
latest-toolset qualification remains unresolved; this is a development probe
exception, with actual compatibility and production acceptance still pending.

The receive caller now constructs `N9000Stream(greeting=greeting)` after exact64
greeting parsing and handles `LoginHandshake.accept_reply(...) -> LoginResult | None`.
None is an exact codec-validated flat startup shape with action0/sequence0/flags0/
encoding0:2561 opaque92,2562 source40 or2563 source36, while login remains pending.
The2561 body's schema remains unknown and is not interpreted. It continues the same
generation, sequence, original deadline, cumulative65536-byte ceiling and one
Send. Success is atomically sealed only for a non-None LoginResult. Failure
closes both stream and handshake; no password resend, arbitrary event callbacks,
recording-state/config changes or authority effects are introduced.

The approved codec preserves private `Packet.peer_version` and an accepted login
result's peer version. A notification does not pin the later login header version.
This provider does not expose those private packets/bodies through safe results.
New focused evidence is `W04-windows-provider-receive-adapter-report.md` in the
SDD; it is an independent caller task following codec source closure.

Current startup caller evidence is `W04-windows-provider-startup-adapter-report.md`
in the SDD. Worker API/semantics stay unchanged from the accepted receive adapter;
the new codec pin permits only its reviewed exact startup shapes. Public unit
tests use marked isolated synthetic receipt/14-file metadata fixtures and assert
real product path/hash pins separately. They do not require ignored approval
packets or publish SDK binaries/actual approvals, skip checks, or claim native
source admission. Root alone rebinds protected real receipts after review before
one authorized device attempt.

Separate Root R86 evidence at `2026-10-03T08:24:14Z` records a device-free hidden
original child load/attach success: mapped13 package DLLs plus the fixed R85 CRT,
all15 exports found, exit0/reaped, stdout0/stderr0. It used the accepted ABI2
directly and did not execute these four provider files, Initial, observer setup,
serial, login or media. It establishes a narrow DLL attach probe; this provider's
source review and actual execution remain required.

Fix1 retains an owner before Popen and permits a missing writer during setup.
Poll/kill/wait/writer join/stdin close/output close interruptions preserve the
same original owner and fence subsequent attempts. An outer CLI finally keeps
passive custody even on KeyboardInterrupt/SystemExit. No PID/name/tree discovery
or repeated kill is introduced. A start attempt with unproved thread completion
stays fenced; a joined writer must also have its original stdin pipe closed.

Callback failure, success sealing and ordinary close now use a single first
terminal claim. CPython3.12's GIL and fixed built-in string-key dict.setdefault
make that claim indivisible; the production layout gate requires this runtime.
The worker seals admission and commits success under the queue lock without
native, capture or codec work inside it. Callback lock contention latches failure
without waiting. A failure before the seal wins; callbacks after sealing consume
zero and cannot change that completed decision. This is an application state
boundary, with no native callback-quiescence or hard GIL scheduling claim.
`received_bytes` counts admitted stream bytes0–65536, excluding an overflow chunk,
so a receive-limit failure remains a valid safe receipt instead of becoming deadline.

The original attempt2 record actually contains3 failed/46 passed, including
`owner.finish(2)` returning false for an inert child. Its phase/cause is unknown
from those logs; the later49-pass record does not establish a cause. The original
packet/report remain immutable history; this paragraph and the SDD
`W04-windows-native-provider-Fix1-report.md` correct the earlier2/47 statement.
Fix1 scoped causal evidence is separate from that original packet. Root's separate
R87 direct ABI Initial(true)/Quit-returned child0/reaped also precedes provider
acceptance. Root's later safe summary classifies stdout106/stderr222 bytes and a
UTF16 log4cxx initialization request; its known private-value scan passed and raw
logs were not publicly forwarded. No NAT, serial, observer, login or media ran.

Fix3 follows Root's actual provider mode-load failure after clean Fix2 source
closure. All parent admission boundaries passed; the worker architecture/system/
crypto import sequence had already mapped CPython's vcruntime140_1.dll. The
worker correctly rejected it under the prior single-runtime rule. R90 explicitly
admits those two exact Microsoft runtime identities. Parent source review now
pins the original R90 SDD receipt rather than R85; Root must rebind its private
source/runtime receipts to these current four files before retrying. This source
correction does not itself establish actual provider load or runtime qualification.


## Same-session diagnostic inventory continuation (2026-10-03)

The current provider4 source adds private `inventory` mode. Its independent author
packet is `W04-windows-inventory-session-report.md` and the accompanying evidence
folder in the SDD. Root must review these exact four file identities and refresh
the protected source receipt before execution. The additional inventory dependency
is `W04-local-inventory-xml-Fix3-Fix1-reviewed-root-receipt.json`, SHA256
`2b8b158ef441ec374dc237c21157562c4fe02ce8fdcd76dadfe78cf8df686e9e`.
The current inventory module identity is
`e1761218b3f6fdaee672d40cb38c363b1c2b6d5f923a08d5bc4631361dd8597d`.
Every accepted dependency's complete file map is checked in both parent and worker.

`PrivateRequest("inventory", country, serial, username, password,
metadata_read_opt_in=True)` permits exactly BASIC, CHANNELS, USER and PERMISSIONS
from the reviewed `InventorySession.build_query`. There is one pending query;
sequences are 2, 3, 4 and 5 after login sequence1. No alternate credential or
login resend occurs. The exact accepted private LoginResult, original callback
generation, original native handle, requested serial/username, greeting security
and accepted peer version bind the session. Login acceptance becomes historical
safe evidence before metadata reads and is retained if a later read fails.
The callback's first terminal success remains unsealed until complete metadata
projection. No public RPC, durable enrollment, vault, tenant grant, channel command,
live stream or production readiness is implemented by this opt-in.

The drive owner serializes query construction, reply parsing and publication.
Its diagnostic supplier admits only the retained callback generation and context,
exact opt-in, an open first-terminal latch and the unexpired original deadline.
`InventorySession` checks that supplier on entry and after XML parsing. The worker
checks it again immediately before Send and under the callback lock immediately
before final projection/sealing; that locked work performs no native, codec or
capture calls. Callback failure/close wins before sealing. A completed safe
projection contains counts and booleans only, with fixed `identity_available`.
Partial/failed results withhold serial/channel/user/permission projection and use
fixed `unavailable`; `inventory_replies` still reports committed reply progress.
`authorized`, `live`, `production_ready`, and `quiescence_verified` remain false.

`inventory_queries_sent` counts metadata native Send **invocation attempts**, including
an uncertain or failed invocation (0–4); `inventory_replies` counts successfully
committed InventorySession replies (0–4), so a final publication fence can leave4
historical replies without completeness. Existing `send_count` remains the native
return from the sole initial login Send. In inventory mode every Send must report
the complete requested wire length; partial/zero/negative/throwing Send is terminal
without retry. `received_bytes` remains cumulative admitted callback stream bytes
for the entire login-plus-inventory attempt (0–65536), excluding an overflow chunk.
Channel projection uses the codec's default256 ceiling. The parent rejects extra
JSON keys, type substitutions, out-of-range counts, and inconsistent completion.

A bounded ordinary-envelope buffer retains bytes across the phase change, including
partial XML and additional packets in the same callback chunk. It strips only
exact heartbeat8 envelopes. Before login, complete ordinary frames go through the
accepted N9000 startup/login parser. After login, exact2331 replies go directly to
InventorySession; XML is never fed into the login-only parser. Notifications outside the exact Fix2 set below
following login, protocol fragment envelopes, unsupported encryption/tails/groups/
channels and malformed identity/XML are terminal. Ordinary transport fragmentation
is supported; the protocol's special fragment envelope is unsupported in inventory
mode. Unexpected buffered/queued trailing data at final publication is rejected,
including an incomplete trailing envelope. Complete heartbeat8 envelopes already
in the framing buffer are consumed; newly queued trailing chunks fail closed.
Raw greeting and cumulative reply bytes remain in the unique protected generation
folder's bounded private captures. No body, serial, name, GUID, group, session or
key enters safe JSON, public logs or repr.

## Direct Windows interpreter and original Job custody

Windows venv `Scripts/python.exe` may redirect to a second interpreter process.
The provider now reads the existing trusted infrastructure venv's `pyvenv.cfg`,
requires its `home` to match the running interpreter's `sys.base_prefix` and
`sys._base_executable`, and launches that base `python.exe` directly. Only the
project `.venv` or fixed `.superpowers/runtime/windows-media-decode/venv` is admitted.
Duplicate cfg fields, a foreign base, system-site enablement and reparse paths fail.
These are trusted local infrastructure choices, never private-request paths.

The parent retains a ChildOwner before process creation and owns a Job before
Popen. The Job has `KILL_ON_JOB_CLOSE` and `ACTIVE_PROCESS=1`; no breakaway option
is enabled. The stdlib-only `-I -S` bootstrap blocks for explicit private stdin
admission. The parent assigns and verifies the original Popen process handle in
that exact Job before it releases the marker/packet. The bootstrap checks current
Job membership before adding the two fixed application source directories and
trusted venv site-packages; it never runs `.pth` or `sitecustomize`. Application,
cryptography and vendor imports therefore follow admission. The worker also
checks the explicit packet admission and Job membership before vendor loading.
The parent supplies its original monotonic deadline through private stdin, so
imports/validation/native loading do not restart the attempt's clock.

Timeout/close kills the originally retained Popen, confirms reap, closes the
original Job, joins the writer and closes captured streams. Failed/interrupting
cleanup retains the same owner and fences another attempt. No PID lookup,
name/port discovery, descendant adoption or discovered-process kill is used.
The source still claims no native callback quiescence. Historical reaped results
from redirector-based execution do not establish this new custody behavior.
Current author evidence uses only direct CPython and kernel Job APIs: interpreter
PID equals Popen PID, a child creation attempt is rejected by the one-process Job,
and owned cleanup releases the original process/Job/streams. EOF before admission
exits the real bootstrap without application imports. Vendor compatibility under
the stricter process limit remains a separate Root execution question.

References: [Python venv configuration](https://docs.python.org/3.12/library/venv.html),
[isolated and no-site startup](https://docs.python.org/3.12/using/cmdline.html),
[Windows Job ownership](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
and [Job process/kill-on-close limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information).

Source/inert checks do not establish device interoperability, tenant authorization,
metadata completeness on either real device, media or decoder acceptance.
`MATCHED=0`, `release_ready=false`. The canonical service report remains Root's
actual execution authority; this owned guide and the packet record this source
change without rewriting historical review packets.

## Fix1 final metadata Send admission (2026-10-04)

Independent review I1 found that the last metadata guard preceded ctypes buffer
allocation. The correction adds a final current-generation/deadline/callback
check after both buffers are allocated and retained, immediately before the
metadata invocation counter and native Send. Expiry, callback failure or context
revocation during either allocation now leaves both the metadata Send count and
the native Send count unchanged. The native call remains outside the callback
lock. Six focused regression cases fail without this guard and pass with it;
the exact guard-removal mutation also fails all six. The original84-artifact
packet and its51-test final/121-test intermediate evidence remain historical.
Current correction evidence is `W04-windows-inventory-session-Fix1-report.md`
and its separate Fix1 packet in the SDD. Actual device execution still requires
Root's independent review and protected dependency/source receipt admission.


## Fix2 diagnostic notification dispatch (2026-10-04)

Root's accepted Fix1 execution reached an accepted login and one metadata Send,
then stopped at flat2561/body92. Root supplied only sanitized header/result facts;
this author did not access the private capture or execute a device operation.
The current worker admits exactly command2561/body92,2562/body40 and2563/body36
while the original InventorySession query is awaiting its reply. Each complete
ordinary frame is validated by the already accepted greeting-bound N9000Stream:
action0, sequence0, flags0, encoding0, exact inner/outer length and admitted
positive signed-short peer version. The worker rechecks current callback
generation/context/deadline after validation and discards the event. It does not
call the closed LoginHandshake or InventorySession.accept_reply for these events.
No query Send/reply counter, metadata object, deadline, command authorization,
channel state, notification callback or pending query is changed by a discard.
Received event bytes still count toward the same cumulative65536 ceiling.

This policy reuses the complete29-key Z9 classification and exact startup/default/
error paths in the accepted codec source evidence. Command2561 is absent from the
source switch and returns with no effects; its92-byte body is opaque and its bound
is observed, not an invented source schema. Command2562 parses source ml2/body40
and performs a channel-relative application callback;2563 parses il2/body36 and
changes a list/O8/application callback. Those application effects are intentionally
suppressed in this diagnostic-only path. No media or live grant follows them.
All other source command families and adjacent unknown defaults remain unsupported;
wrong shape, action/reply/failure variants and malformed notification headers are
unsupported. Genuine2331 reply/error parsing remains solely the inventory codec's
contract. Special protocol fragment envelopes remain unsupported. Existing final
publication/trailing-data checks remain: the discard policy applies while a query
is pending, not to unconsumed data after the final metadata reply.

Fix2 evidence is `W04-windows-inventory-session-Fix2-report.md` and its separate
packet in the SDD. Synthetic split/coalesced/handoff, complete-family exclusion,
malformed/current-generation/deadline/cap cases and causal parser/guard mutations
verify this source boundary. Dependency pins, API, opt-in and original process/Job
custody remain unchanged. Root must review current provider4 and bind a new
protected source receipt before another actual continuation. MATCHED0 and
release_ready=false remain; real metadata/join/media acceptance is not supplied by
this source correction.


## XML Fix3 accepted dependency rebind (2026-10-04)

The provider now pins the separately accepted inventory XML Fix3/Fix1 receipt
and complete inventory3 identities shown above. The worker, diagnostic API,
notification dispatch, read guards and original process/Job custody are unchanged.
Inert provider replies now follow the reviewed source shape for all four reads:
bounded opaque prefix before the first XML declaration, passive response attrs,
types/catalog/supplemental fields, escaped text and nested permission selectors.
All values remain invented. Complete-success fixtures include a matching synthetic
binary channel/serial tail; detail-only replies do not create an absent roster.
The no-tail fixture stays incomplete after BASIC/CHANNELS/USER and cannot send the
permission query. No authority or live flag follows either outcome.

The separate packet is `W04-windows-inventory-session-XMLFix3-rebind-report.md`
and its READY/evidence in the SDD. Root/native integration owns the protected
minimal execution receipt, private staging and any subsequent actual device work.
The same saved BASIC offline replay reported by Root is separate evidence and
was not opened or executed by this author. No live extension is added here.

## Bounded same-owner live proof (2026-10-04)

Private `live` mode requires both exact booleans `metadata_read_opt_in=true` and
`live_read_opt_in=true`, a private `store_ref` (ASCII identifier1–64), and an
actual inventory `channel_position`1–256. Existing country/serial/credential
bounds remain. Credentials and bindings stay on private stdin; neither opt-in
is a SaaS actor/tenant grant. No public API, player, decoder, PTZ, talk, audio or
configuration operation is added. Safe authorized/live/production_ready and
quiescence_verified remain false.

Complete accepted e8/i9/Q7/G consumers and actual H5 callers were inspected.
Missing or genuinely empty authGroupId has no DOM firstChild, so e8 omits i9.
The provider preserves exact accepted USER provenance: whitespace, comments and
empty CDATA cannot be conflated with that branch. A bounded second DOM/lexical
pass runs only after the same XML reply passed InventorySession validation.
Three reads may set `metadata_branch_complete=true`, with
`permissions_availability=not_requested_no_group`, permissions_complete=false
and inventory_complete=false. Serial/complete roster/current observed user are
still required. The four-read branch retains observed permissions and
inventory_complete=true. Incomplete/no-tail roster cannot enter either live path.

G's upstream predicate is username/admin-name match OR !Z3 OR actual channel X3
membership populated by @lp. Z3 starts false, i9 sets false and Q7 sets true.
Actual inspected G callers are VideoView.h2 display handling and lb4 talk
eligibility; the H5 caller LiveViewLayout.F3 instead checks DeviceItem.H()/l(),
whose upstream remote-view bool/mask defaults are true/-1. This source behavior
is compatibility provenance, not a direct H5 or SaaS authorization claim. The
provider does not synthesize those DeviceItem defaults or copy Q7's system-field
presence expansion. Its separate current operator read+live gate additionally
binds original store/serial/login/session/generation, complete actual selected
channel and fresh task. Group-present paths require current complete permission
metadata and actual selected-channel @lp; admin-only group cases are denied as a
conservative subset. No-group is admitted only with the
proven missing/empty provenance under explicit current operator opt-ins.

The qualified live dependency is
`W08-local-live-taskless-first-qualified-reviewed-root-receipt.json`, SHA256
`8039ff625abdb21c34214014af129286ee8becc3ed102986920b7289a1ae0b75`.
It has C0/I1 historical/M0, open blocking source findings0: historical I1 remains
qualified. Parent/worker gates require that exact status/hash, all live3 and its
unchanged frames.py dependency. Other accepted source/runtime pins remain.
The Root protected source receipt dependencies now additionally include this live
receipt and frames.py. Decoder6f3b source remains separate and is never imported
or spawned inside the TVT worker's single-process Job.

LiveCodec emits stream1 command1281 once and at most one source1282 close.
Fresh task/open/close request GUIDs and unique sequences6/7 bind one actual
selected GUID; the raw index uses the proven Java low-byte mapping after a
bounded−128..255 check. Capability is accepted LoginResult.peer_version (R3),
from successful wz0→h4/Z9→ub(s), never greeting Q4/capability. Fresh guards run
after all send buffers/retention and immediately before Send. Unknown/partial Send
is never retried. Close is attempted only when the codec still admits it and
current admission remains; a fenced/uncertain task falls back to original native
Stop/Destroy/Quit and parent process reap. A close Send is enqueue evidence;
close ACK/quiescence are not claimed.

A bounded mux retains ordinary and fragmented live envelopes, including split/
coalesced packets near the1MiB cap. Accepted LiveCodec enforces fragment order,
task, actual ep3 channel, stream, format, index and encryption fences. Exact known
flat2561/2562/2563 notifications are validated separately and cannot become ACKs
or frames; fragment interleaving is not skipped. Original deadline is never reset.
Caps:64 validated media frames while waiting for key,4MiB cumulative compressed
payload including pre-key frames,8MiB raw live bytes,512 mux envelopes,1MiB packet/
buffer,64 fragments per assembly, and4 retained frames. Metadata still has65536
bytes and at most4 queries. After first source-validated key, capture retains up
to4 ordered frames; no key request, resend, extradata or payload conversion occurs.

Protected generation files:

- `live-open.bin` / `live-close.bin`: exact source request bytes when admitted.
- `live-receive.bin`: bounded unvalidated original transport bytes for diagnosis,
  including pre-key/unsupported material; never a decoder-ready artifact by itself.
- `live-000.bin` through `live-003.bin`: exact validated compressed payloads.
- Corresponding `.json`: schema1 binding, ordinal/index/key, codec/dimensions,
  encrypted=false plus source flag/format provenance, payload bytes/hash, exact
  source header/envelope/extension/padding/outer-header hex, source_context and
  device/ecm/envelope `{ticks,unix_microseconds}`. No clock is selected as PTS.
- `live-capture.json`: schema1 binding/source receipt identities, metadata/group/
  eligibility provenance, operator opt-ins, capture admission, ordered frame file
  identities, key-wait counts, capture-scope outcome and cleanup requirements.
- `live-owner.json`: safe final parent result written only after original owner
  confirms child reap, Job release and stream closure. `result.json` is the worker
  result and does not itself prove parent reap.

Each private capture checks current authority before and after its write; after
parse, the exact original identity is checked again. A revocation can leave a
private orphan payload, but withholds its metadata/index publication. Manifest
outcome `frames_captured_close_sent` is capture scope; terminal state/reap comes
from the parent result. After close, captured data is historical and requires
separate authorized offline read/decode. No AnnexB, complete access-unit boundary,
usable decoded frame, decoder PTS or persistent-live authority is claimed. The
separate Root/native owner validates those facts and performs actual S1/S2 proof.

New implementation/evidence authority: `W08-windows-live-integration-report.md`
and its separate packet in the SDD. Exact source methods were exercised with
inert DOM/container stubs in a JDK oracle; the full app/SDK was not executed.
Current source/inert acceptance remains MATCHED0/release_ready=false.


## W08 live Fix1 admin-only group restriction (2026-10-04)

Independent review I1 found that immutable USER metadata retains default_admin
and normalized admin_name separately, losing e8's ordered writes to raw H4.
Default-admin followed by foreign adminName, or whitespace/firstChild variants,
cannot establish the source final admin match from those normalized fields.
The group-present live branch now requires actual selected-GUID @lp only.
Admin-only group cases, including a normalized matching name, are explicitly
outside this conservative diagnostic subset and denied before open. No ordered
admin parser, new protocol, metadata fields or source-module change is added.
The exact missing/empty legacy branch, current operator opt-ins and original
identity/channel/session/generation guards remain unchanged. Source G and H5
caller facts above remain source description, not an admin grant in this provider.

Scoped evidence is `W08-windows-live-integration-Fix1-report.md` and its separate
minimal packet. Original W08 101-artifact packet/review remains historical;
no broad historical/source oracle replay is part of this correction.

## Exclusive first-task route0 rebind (2026-10-04)

The current qualified live receipt above adds `exclusive_first_task=False` by
default. This provider enables True only inside its fresh original process/socket/
callback generation, first-and-only stream1 live path. A non-resetting callback
claim denies a second/replacement live codec on that owner. The drive path creates
one codec/open and always retires the native connection; a new codec on a reused
connection is not an approved way to establish freshness. No public request flag
can enable this receive policy.

Route0 media is admitted only after the exact pending1281 ACK. Actual ep3 channel,
stream/type/format/index, current operator/generation, quotas and capture guards
remain. Default codec behavior stays strict, route1 is unsupported, and route2
still requires its exact wire task. Capture metadata adds media_route,
wire_task_present, wire_task_guid_le (null for route0) and task_correlation.
The binding's task_guid_provenance is local_owner_generated: route0's local owner
task is not fabricated or described as a received wire task. Exact original
route0 source_header bytes remain16 bytes; no yz0 routing header is inserted.

Evidence: `W08-windows-live-taskless-first-rebind-report.md` and its minimal packet.
Native owner supplied sanitized actual S2/offline-replay facts; this author did not
read or replay actual media or issue a device Send. Root review/protected receipt
closure is still required before actual capture. Historical live I1 remains
qualified; no AnnexB/AU/PTS/decode or public authority claim is added here.


## M1 private inventory service port (2026-10-04)

`local_inventory_config.load_local_inventory_provider()` is the worker-only deployment entry point. It returns `None` unless Windows, exact `WSO_TVT_WINDOWS_LOCAL_INVENTORY_ENABLED=1`, and all four trusted path variables are supplied: `WSO_TVT_WINDOWS_LOCAL_INVENTORY_BUNDLE`, `WSO_TVT_WINDOWS_LOCAL_INVENTORY_STAGING`, `WSO_TVT_WINDOWS_LOCAL_INVENTORY_SOURCE_REVIEW`, and `WSO_TVT_WINDOWS_LOCAL_INVENTORY_RUNTIME_REVIEW`. The paths enter existing private ACL, original-file, bundle, exact source receipt and accepted runtime gates at execution. Loader construction never loads a vendor library. No public request chooses paths. A missing provider remains unavailable; an inert provider is not a production fallback.

`NativeLocalInventoryProvider.verify(credentials, *, deadline_monotonic, current, cancel)` implements the stable core port. It accepts one absolute deadline no later than 20 seconds from admission. The same deadline covers source checks, process bootstrap, connection, login, metadata and publication. Initial `current()` precedes credential use. The original child receives one private duplex pipe HANDLE duplicated directly into the retained Popen handle after Job admission. Bounded JSON byte messages carry generation, strictly increasing sequence and purpose; no callback or credential is pickled. The parent evaluates the supplied callback synchronously on the original verify caller thread for each request. The child requests current admission after all ctypes buffers are prepared and immediately before each login/metadata Send; it also checks before connection, during metadata consumption and after observation serialization before publication. The existing child generation/deadline/native-context guards still apply. No SQL/native call runs under the native callback seal lock.

The parent checks cancellation/deadline/revocation while waiting. A retained watchdog checks cancellation and the unchanged absolute deadline and stops only the originally held process; it never calls SQL. A late True, False, exception, wrong generation/sequence, malformed response or broken channel cannot grant Send/publication. SQL `current()` must itself be bounded by its caller contract: Python cannot preempt an arbitrary blocked callback, although the watchdog retires the original child at deadline while that caller is blocked. This is a fresh-check boundary, not an atomic transaction between SQL and a native instruction.

The private export is generated from the retained accepted LoginResult/InventorySession on the original connection. It carries actual GUID/raw index/window index/ordinal/kind rows, serial-match and complete-branch facts, exact missing/empty/value USER provenance, permission availability and source proof status. It omits serial, credentials, names, keys, native handles and media. Counts are only cross-checked against the structural receipt. The exact missing/empty three-read branch remains accepted; lossy/unsupported USER shapes and incomplete tails remain failures. No group/admin permission or security0 proof is fabricated.

The service mode creates no greeting/reply/live capture or native stdout/stderr file. Its real observation travels only over the private pipe and becomes the immutable core type after confirmed original child/Job/writer/streams/IPC/watchdog retirement and one final caller current/cancel/deadline check. The structural result file is insufficient to reconstruct an observation. A success leaves only provider configuration on the reusable adapter; transient immutable Python strings cannot promise immediate physical zeroization. No continuous session or live authority is returned.

If retirement is uncertain, the same ChildOwner remains in `windows_socket.PENDING_OWNERS` and new attempts are fenced. `owner.finish(timeout)` retries cleanup on retained originals and sets `confirmed` only after all resources close; `owner.passive_wait()` cooperatively retains custody until confirmation. Hosting shutdown must retain its worker/custodian, callback resources and private folder while any original remains unconfirmed. No PID lookup, replacement child or repeated kill is used. The service attempt lock fails busy rather than waiting beyond its budget.

M1 expands exact source admission from provider4 to owned8 (three private modules and their focused test added). The direct receipt dependencies additionally bind core `local_credentials.py`, `local_service.py`, and contracts `local_device.py`. Existing ABI/login/inventory/qualified-live/runtime pins stay unchanged. The old `187373...` provider receipt cannot admit these changed files. A newly reviewed protected six-key Root source receipt is required before actual execution; runtime receipt remains `77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d`.

Verification packet: `M1-native-inventory-service-port-evidence`; report: `M1-native-inventory-service-port-report.md` under the current implementation-plan SDD directory. Focused tests use actual source metadata serialization/parsing with inert native calls, plus real Windows stdlib child/Job/HANDLE IPC and original retirement. Author tests do not exercise the vendor SDK, supplied credentials, devices, SQL OWNER integration or HTTP/browser flow; Root performs that separate acceptance after independent review.


### M1 post-publication Windows pipe completion correction (2026-10-04)

Root actual M1 reached accepted eight-channel metadata, but the parent rejected a completed private publication before accepting the structural receipt. A real inert Windows child reproduced the exact ordering: publish, close authority pipe, delay receipt. `PipeConnection._poll` calls `PeekNamedPipe`; this raises `BrokenPipeError` with Windows error109 after the peer closes. The previous EOF handler covered only `recv_bytes`, so the parent incorrectly recorded a protocol failure after accepting the observation.

The scoped correction recognizes only error109 from the poll call on Windows, only after `_done` with an already accepted observation. It marks that pipe closed while continuing the unchanged structural-receipt wait and current/cancel/absolute-deadline/final-cleanup gates. Before-publication closure, other errors, recv/partial failures and extra messages remain protocol failures. No observation or SafeResult is synthesized. Evidence: `M1-native-inventory-postpublication-evidence`; actual Root execution of the corrected source requires a new independent review and protected source receipt. This correction has only inert/kernel verification at author handoff.
