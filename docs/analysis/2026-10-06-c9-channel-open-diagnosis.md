# c9 channel-open failure diagnosis

Analysis date:2026-10-06 Asia/Seoul. Read-only inspection during active c9 run
`local-devices-e4c7006dd9664ef7a7d63e0bc4a5fa94`; immutable127-source approval
`bd378ec383f962fbfb82fed314a227c2ec55980b63c4b09b98ddae9b57cba10c`.
Source baseline is the reviewed R137/R138 stage-1 worktree at HEAD6436748.
No pinned source, existing report, test, runtime script, receipt or approval was
edited. No SDK, RPC, SQL, Chrome, device call, test run or Git command occurred.
This newly created report is outside that immutable source closure. Root owns
canonical service/ledger/instruction updates after original runtime retirement.

## Conclusion and evidence

The eight inspected failures are **native login-handshake rejection with code
0x20000030**, before inventory lookup, channel selection or live-open. The APK's
login failure branch recognizes that same code as busy. The current service
loses this native outcome and exposes generic protocol502 instead. These facts
do not establish an exact five-connection recorder limit or prove that twelve
concurrent tiles are attainable with one login per tile.

Safe current-run media observation contains17 starts:9 OPEN_RETURNED and8
OPEN_FAILED. Failed ordinals8–13 and16–17 all have executor_start/protocol_invalid
as first failure, no native_return or later milestones, and elapsed times1233,
1141,906,1218,1092,1327,1093,953ms respectively. Root reported these correspond
to store1 channels6/7/8, including a channel6 retry after an original successful
channel was stopped and30s elapsed. Established streams did not fail at the
source format or queue guard in the inspected snapshot.

The existing private staging directory is
`C:/wso-private/windows-tvt-sdk-20261003/service-inventory-runs`.
Inspection selected the latest25 result files, parsed only nonempty files at
most65536 bytes, and exported a fixed projection of stage/failure/code,
booleans and counts. No private generation, device/session/channel/task
identifier, credential, serial, raw media or native exception text was exported.
Eight child result.json files in the c9 failure interval all contain:

| Safe field | Value |
| --- | --- |
| stage | handshake |
| failure | rejected |
| native_error | 536870960 / 0x20000030 |
| reply_accepted | false |
| inventory_queries_sent / inventory_replies | 0 / 0 |
| channel_count / channels_complete | 0 / false |
| serial_matched / permissions_complete | false / false |
| live_open_attempts / live_open_ack | 0 / false |

Their creation times, ascending UTC:
16:22:50.430,16:22:54.743,16:23:01.978,16:23:14.953,16:23:31.228,
16:23:47.398,16:26:51.017,16:26:55.195 on2026-10-05
(2026-10-06 Asia/Seoul). Every child result has an existing same-generation
live-owner.json with stage=validated, failure=denied, native_error=0 and
reaped=true. Same-generation comparisons were performed privately and only
their true/false outcomes were exposed. Child reaped=false is the child-written
pre-parent-cleanup result; the matching parent owner result supplies actual
reaped=true for each failed original.

The two earlier current-run inventory result files at16:18:10.038 and
16:18:12.401 UTC are complete/none, reply accepted, three queries/three replies,
with complete8- and4-channel inventories and matched serials. Those inventory
facts do not grant live authority, but the failed originals never reached their
own inventory phase at all. An absent selected channel or live media parser
rejection is therefore not the initiating failure in these eight child results.

The eight staging results' time interval, count and ordering match the current
run's eight failures. The optional public-safe observation intentionally has no
native generation field; an exact child-generation→observation-ordinal binding
is not exported. Individual chronological ordinal mapping is consequently a
correlation, while the child→parent same-generation comparison is exact.

## Source mechanism

The local video service creates one original native login/session per admitted
tile, obtains same-session inventory/live authority, then hands that owner to
the source/decoder/peer. Stage1 retains this one-login-per-tile architecture;
connection multiplexing belongs to Stage2.

1. `packages/core/src/wso_core/tvt/local_n9000.py`, LoginHandshake.accept_reply,
   checks original generation, pending sequence/base login command and reply
   class. A class3 failure must have the exact268-byte rejection body and bounded
   message length before `LoginRejected(body_code)` is raised. The inspected
   child receipts are structured results of that path, not guessed from a
   failure-looking field in a successful reply.
2. `services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py`, drive,
   catches LoginRejected/InventoryRejected and retains failure=rejected and
   error.code. At this point stage=handshake proves inventory never started.
   main finally closes the private service pipe before writing result.json.
3. `LiveParentAuthority.pump` turns an unhandled pipe EOF/error into its fixed
   protocol denial. `WindowsSocketProvider.run` checks service.tick before
   parsing result.json; on false it assigns generic denied and breaks, then
   retires the original owner. The matching inspected parent results all show
   exactly this information loss: validated/denied/code0 despite a child
   handshake/rejected/code0x20000030 result. Parent custody is reaped, but the
   child refusal is not propagated to its returned SafeResult.
4. `NativeLocalLiveProvider.open_session` currently ignores the SafeResult
   returned by native.run. Missing handoff with an unrecognized parent reason,
   or a provider exception, becomes LOCAL_DEVICE_PROTOCOL_INVALID/502. Merely
   capturing that return would not fix these inspected failures because the
   returned parent result already lost the native code.

The retained APK evidence was checked against the actual local JADX source:
SuperLive Plus1.18.1 `defpackage/cw3.java`, m8 lines6974–7014. The login command
family257/258/261 routes code536870960 to its busy result18. Earlier bounded
research in `.superpowers/sdd/2026-10-05-multiview-stage1-plan/apk-substream-notes.md`
records that login mapping and separately distinguishes live-open refusal.
The current LiveRefused busy branch already maps live-open0x20000030 to429;
that does not currently cover login rejection before setup.

## Minimal repair proposal, not implemented

No additional device reproduction or trace flag is needed to identify the
current stage/code. Preserve the existing exact, bounded child SafeResult after
confirmed original retirement instead of losing it to the earlier pipe-closure
boundary. A narrow implementation can re-read the original result.json using
the retained directory/file identities and expected generation, existing size
bound and parse_result validation, only after the original owner is confirmed
reaped. Original cancellation, expiry, current-authority denial and uncertain
custody must keep precedence; missing/truncated/substituted/foreign receipts
must never create BUSY or success.

Then the live provider can map only proven handshake/rejected/0x20000030 to
LOCAL_DEVICE_BUSY/429, preserving the established busy scheduling policy and
requiring no new login/retry/multiplexer. Do not map all protocol errors,
arbitrary rejected codes or generic denied to BUSY. Readonly/source evidence
does not authorize changing user-visible handling of other native codes.

Focused proof for a later authorized fix should use an inert original child that
closes its service pipe and publishes its matching busy result before parent
retirement; verify only exact busy maps429, ordinary/unknown rejection remains
denied, authority/cancel/deadline wins, and unconfirmed/foreign/substituted result
custody cannot be reused. This is a proposal awaiting Root's ruling and actual
c9 retirement. No production change or test was made in this analysis.

## Limits, priorities and open questions

Priority is exact login-BUSY propagation after owned cleanup, followed by scoped
native review, new protected receipt/approval and bounded acceptance under Root.
No extra closed-enum observation is required for the already proven failure;
if future evidence is absent, observe only fixed native stage/failure and a
recognized busy classification after validating the exact original result.

The recorder's precise session/connection ceiling, other clients, retained
device-side sessions and why the post-stop retry remained busy are unmeasured.
The failed login never selected channel6, so the evidence does not imply those
channel GUIDs are absent or invalid. It also does not establish a permanent
channel6–8 limitation. Placeholder video on other channels must not be counted
as a no-signal outcome without an actual failed signal gate.

c9 was still running during this analysis; global shutdown/cleanup and final
eight/nine/twelve-tile acceptance belong to Root's later terminal evidence.
This report records existing source behavior and actual saved failure results,
not a repaired outcome, completed runtime or new performance measurement.

Update log:2026-10-06 — Created from immutable c9 safe observation, whitelisted
existing private result projections, exact child/owner generation comparisons,
source control flow and retained APK login mapping; no pinned/runtime mutation.
