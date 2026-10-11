# Selected APK features: source contracts and delivery research

Analysis date: **2026-10-08, Asia/Seoul**. This report is read-only planning
research for the remaining features selected by the user. It describes a concrete
implementation path; it is not an implementation or acceptance claim.

## 1. Scope, source baseline and evidence rules

Selected scope: recorder search/calendar/timeline/playback/seek/speed/backup;
snapshot/local recording/APK split layouts/paging/quality; PTZ/presets/device
configuration/defense/schedules/firmware; account security/sharing creation and
revocation/device addition and discovery; alarm inbox/push/media files. New audio,
Tyco, cloud-storage/payment and wider commercial domains are outside this selected
delivery unless a selected operation has an established dependency on them. The
user's principal anomaly-detection work is planned by the controller separately.
Preserving an already present audio track in an imported/exported file does not
authorize implementation of listen, Talk or new audio transport.

The implementation authority is the separate worktree:

`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`

- Branch: `codex/superlive-web-service`.
- HEAD read in this session: `6436748f37c799fd14ce03e1d72c86c79eda6b0f`.
- Initial status contained the reviewed uncommitted Stage1/2 implementation,
  including raw mux, admission, worker and browser paths. No source was changed.
  The 2026-10-08 original-plan audit reports 142 status entries; this research
  inspected the current status and uses that audit's count without recasting it
  as a count of individual files.
- The writable primary checkout is `main` at
  `211d1484aa16eb30f5d362758f149f98dec9dfdf`; it lacks the current media source.
  This report is saved there because the implementation worktree is read-only
  under the current filesystem permissions.
- APK reference: SuperLive Plus 1.18.1, versionCode20267, preserved base APK
  SHA256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.
  The preserved JADX/apktool tree was inspected for selected call sites. No APK
  library, SDK, device, browser, database or application server was executed.

Read before research: shared analysis policy, both AGENTS files, current service
report, original-plan audit, APK parity matrix, September27 W06–W08/W10–W15/W20/
W23–W25 plan, APK audits02/03/04/05/12/14, and existing security, directory,
operation and Windows transport references. Keep the active worktree's service
report as the source/runtime authority. Reuse this research before implementing
the selected domains and refresh affected claims after source or acceptance
changes. The controller owns the corresponding AGENTS bridge and integrated
design/plan updates; this agent writes only this report.

Evidence terms used here:

| Term | Meaning |
| --- | --- |
| Recovered contract | A reachable APK caller and/or serializer/native signature was recovered. An SDK route name alone is narrower evidence |
| Actual codec | Current project code serializes/parses a bounded byte or HTTP contract |
| Public flow | User can reach UI → BFF → API → protected worker/provider |
| Hardware/browser accepted | A dated saved execution receipt establishes the tested operation on an actual recorder/browser |
| Proposed | New interfaces, files, tests and ordering in this report; none are implemented by this research |

`J:` below refers to paths under the preserved private
`jadx-full/sources/`; `R:` refers to its apktool resources. `E:` is an arm64 ELF
export value, not a Windows address. `N:` in the established account/directory
documents includes the Ghidra image base0x100000. This report publishes identifiers
and field/signature descriptions only, with no APK implementation blocks,
credentials, raw QR, private addresses, tokens, keys, attachment URLs or media.

## 2. Purpose, architecture and current implementation

The selected work turns the existing store/connection/live surveillance slice
into a service that can review recorded evidence, save media, administer supported
devices and grants, and receive alarms. Present architecture is Next.js/React →
Next BFF → FastAPI → PostgreSQL authority/jobs/assets → mTLS TVT bridge → isolated
Windows native provider/media worker. Account HTTP and local recorder transport
are distinct upstream families. The chosen approach reuses those boundaries and
adds typed operation executors; it does not expose an arbitrary device-command
endpoint or invent HTTP URLs from Android `/sdk` dispatch names.

| Selected area | Recovered contract | Actual codec/private implementation | Public flow | Saved actual acceptance |
| --- | --- | --- | --- | --- |
| Live/multiview | APK live and eight layouts | Raw1281/1285, main/sub, shared recorder mux, admission/cleanup and WebRTC source exist | `/monitoring`, connection player, live-session/wall BFF/API | Earlier two-recorder continuous video and Stage1 nine substreams; Stage2 raw2/raw4 passed. Twelve-camera Chrome/APK comparison remains open |
| Recorder search/playback/backup | Reachable `NetClientProtocal` callers and JNI exports | No recorder search/playback byte codec/provider | Absent | None |
| Snapshot/local recording/files | Decoder capture and compressed-frame MP4 writer paths | Private JPEG/PNG/assets and decoded video primitives exist; no user media recorder/file workflow | Absent | None for selected save/album flows |
| PTZ/configuration/defense/firmware | Direct recorder XML/JNI paths plus separate account requests | No selected control/configuration executor | Absent | None |
| Account security | Eight fixed HTTP operations plus source avatar/QR/removal/provider contracts | Reviewed private `SecurityClient`, protocol/crypto/projection exist | Registration/recovery and read-only profile subsets exist; protected post-login writes are absent | Synthetic fixtures only; no actual selected account write accepted |
| Sharing | Concrete current share HTTP serializers/read models | Six directory read methods exist; no share writer | Sent/received read UI; no create/revoke flow | Synthetic directory; no actual share mutation/recipient comparison |
| Device addition/discovery | Local manual/QR and multicast discovery paths; special bind/transfer serializers | Serial/QR-image credential registration and device verification exist; LAN/IP executor absent | Existing `/connections` registration/verify | Actual8/4-channel verification; no discovery/cloud bind/transfer acceptance |
| Alarms/push | Reachable TVT socket/FCM/Push2/system inbox paths | Event reference models only | Absent | None |

Two source constraints require explicit new work:

1. `bridge/windows_socket.py:PrivateRequest` permits only `load`, `initialize`,
   `connect`, `handshake`, `inventory`, `live`. `WindowsSocketProvider.open_mux`
   adds shared live ownership; neither path provides recorded playback, PTZ,
   arbitrary API transport, discovery or alarm ingress. Inventory uses command2331;
   live codecs use1281/1285 and legacy close1282. These values must not be reused
   as guessed playback/control commands.
2. `contracts/tvt/media.py:MediaLease.consistent_scope_and_lifetime` requires
   `kind == "live"` for `LocalDeviceRef`. A `kind="playback"` declaration elsewhere
   does not create local playback support. Define a dedicated local playback
   request/lease/admission model and RPC family, with recording-read authority,
   before exposing it. Keep live slot/focus accounting scoped to live behavior.

`OperationService` is also an internal primitive. Its current typed intents cover
payment, firmware, Tyco and delete. It has no public writer/readback implementation
for account profile/contact/password/share/settings. Add reviewed discriminated
intents and corresponding SQL canonicalization/admission/job handlers when
integrating these writes. Subclassing a Python model or labeling a profile change
as generic delete would bypass the intended domain contract.

## 3. Recorder search, playback and export: exact established boundaries

### 3.1 Reachable route and JNI signatures

The active APK device-media path is
`PlaybackViewLayout → fu3 subtype ku3/ew3 → NetClientProtocal → native task →
OnNetClientTaskData → task observer → packet parser → VideoManagerLayout.R0`.
The account SDK's `openPlaybackStream`, record-search and seek declarations lack
conventional exports in this APK, while `natOpenLiveVideo` is a zero-return stub.
Implement from the established active task family.

Exact Java native declarations in `J:com/tvt/network/NetClientProtocal.java`:

| Entry | Exact positional argument types → return | Source evidence/limits |
| --- | --- | --- |
| `PlaybackSearchRecChannel` | `(int,long,int,int,long) → int` | :209; wrapper:341–344. `ku3:7726` uses handle,-1L,0,current Unix seconds,callback context. `ew3:5287` uses a device-day start/end. The long selector/channel mask semantics need native decode |
| `PlaybackSearchRecDate` | `(int,long,short,short,int[],long) → int` | :211; wrapper:347–350; `ku3:4330`, `ew3:4574`. Caller uses offset0 and selected channel-array length; date-result packing needs decode |
| `PlaybackSearchLogRec` | `(int,int,int,long,short,short,long) → int` | :207; export present. Exact filter/time/channel semantics not proven by this declaration |
| `RequestPlaybackStream` | `(int,int,int,long,int,int,long) → int` | :225; wrapper:392–401 stores observer under returned task. `ku3:4720,5664`; `ew3:5054,5679`. Native serializer, stream/speed/mode values and result packet mapping remain unimplemented |
| `SearchKeyFrameByTimeTask` | `(int,int,int,int,int,int,long) → int` | :227; `ku3:5681`, `ew3:5693`; thumbnail/keyframe modes require individual mapping |
| `SendPlaybackIndex` | `(int,int) → boolean` | :414; `ku3:4565,4630`; `ew3:4974,5018`. Actual index domain and seek acknowledgment need decode |
| `ChangeToKeyFramePlay` / `ChangeToKeyFramePlayRewind` | `(int,long,int,boolean) → boolean` | :250/:252; `ku3:5842–5862`; renderer frame-speed control is a separate boundary |
| `JniClosePlayback` | `(int) → boolean` | :102; wrapper removes observer around close. Return alone is not proof of remote task retirement |

The saved media audit records exports `RequestPlaybackStream E:0x11e8f8`,
`JniClosePlayback0x11e648`, date0x11e980, channel0x11ea8c, log0x11e94c,
index0x11e92c, forward key-frame0x11e664, rewind0x11e690. The existing saved
Ghidra media pass did not decode those native bodies. Windows NetSocket is a raw
bounded send/callback transport, not an implementation of these Android JNI
functions. The next offline task follows each export into its serializer and
captures command ID, lengths, integer widths/endianness, timebase, channel/task
identity, request/reply/error classes and close semantics.

### 3.2 Proposed contracts and implementation files

Use `RecordRef` with an internal immutable record ID, exact scoped local device/
channel, source search revision, returned start/end UTC, original device time and
observed zone/offset. Do not invent an upstream record ID when a recorder returns
only time intervals; retain that source shape privately and derive a scoped local
reference. A local-day search requires explicit device-zone evidence and must
report an unknown zone rather than silently using the browser zone.

Proposed narrow ports:

- `RecordingPort.search_channels`, `search_dates`, `search_intervals`: bounded
  typed query/result, deadline, completeness/cursor and source observation.
- `PlaybackPort.open(ref, requested_time, mode)`: authorized lease plus initial
  source time/first-keyframe state. `seek(lease,target,control_epoch)` returns
  requested time, actual keyframe/source time and presented time separately.
- `PlaybackPort.set_rate`, `pause`, `step`, `close`: capability-driven controls.
  Recorder rate and decoder presentation rate are separate, measured fields.
  Do not use `HTMLVideoElement.playbackRate` as evidence that a live WebRTC track
  caused recorder speed or seek.
- `ExportPort.start(ref,range,asset_policy)` → durable job; status includes
  received source bytes/time interval, committed file bytes, validation state,
  cancellation and expiry. A native task ID or progress100 is not a completed file.

Proposed source paths (relative to the implementation worktree):

| Layer | Files to add/extend |
| --- | --- |
| Contracts | Add `packages/contracts/src/wso_contracts/tvt/{recording,local_playback,export}.py`; extend proto with an isolated recording/playback family; regenerate OpenAPI/TS |
| Raw codecs/core | Add `packages/core/src/wso_core/tvt/{local_recording,local_playback,recording_service,playback_admission}.py`; keep all proprietary wire data private |
| Windows bridge | Add `services/tvt-bridge/src/wso_tvt_bridge/{local_recording_provider,local_playback_provider,local_playback_ipc,local_playback_rpc}.py`; extend worker only through reviewed typed commands |
| Media | Add `services/tvt-media/src/wso_tvt_media/{playback,export,recording_sink}.py`; reuse decoder/identity/deadline/Job utilities and add timestamp reset/control epochs |
| API/BFF | Add `services/api/src/wso_api/tvt/{recording_service,recordings,playback,export_service}.py`; BFF routes under `/api/tvt/recordings`, `/api/tvt/playback`, `/api/tvt/exports`, with existing auth/CSRF/projection conventions |
| UI | Add `features/tvt/playback/{RecordingSearch,Calendar,Timeline,PlaybackPlayer,PlaybackControls,ExportDialog,ExportJobs}.tsx`; link chosen channel/date/incident time through internal IDs |

Proposed API operations: search channels/dates/intervals; create/read/heartbeat/
seek/rate/stop playback lease; create/read/cancel export; authorized asset download.
GET/POST selection and exact schemas are a later reviewed contract task, not
existing upstream endpoints. Every request resolves internal selectors against
current tenant, actor, store, connection generation, channel inventory and
recording permission (`rec.video` or explicitly decoded local permission).

Start with one recorder/channel and1x recorded video. Decode and implement the
full selected seek/speed set in subsequent tasks; unsupported native modes have
an explicit capability reason. Reverse/step/thumbnail behavior is not credited as
complete merely because its button is present. Excluded new audio does not become
an implicit completion requirement; record the selected video-only scope and
retain any known audio-track dependency as an explicit future question.

Export backup follows the APK's `BackupFileManager.F4 → RequestPlaybackStream →
backup/a → compressed-frame MP4 writer` path, rather than screen recording. The
preserved H264Decode writer signatures are `Mp4RecorderStartReord(String,int,int,
int,long,int) → long`, `StopReord(long) → boolean`, video `(long,byte[],int,boolean,
long) → int`, audio `(long,byte[],int,long) → int` (:498–504). Their native muxer
internals remain undecoded. Implement a reviewed project-owned muxer using
validated compressed packets/source timestamps and codec extradata; do not load
Android decoder libraries as Windows DLLs.

FFmpeg seeks may land on an earlier seek point; transcoding can discard the
pre-target span, while stream copy preserves it. Therefore export metadata must
record actual source range and any transformation. MP4 fragmentation can reduce
interruption loss, but final playable-file validation remains mandatory.
[FFmpeg seek documentation](https://ffmpeg.org/ffmpeg.html#Main-options),
[FFmpeg MOV/MP4 muxer](https://ffmpeg.org/ffmpeg-formats.html#mov_002c-mp4_002c-ismv).

## 4. Snapshot, local recording, layouts/paging and quality

### 4.1 Source-derived behavior

- Visible snapshot is local: `VideoManagerLayout:1460–1517 → VideoView →
  GL2JNIView → H264Decode.NewPlayerCaptureJpeg/NewPlayerCaptureLastFrame`.
  `SnapLivePictureTask` is exported but the established audit found no reachable
  button caller. Use the already authorized decoded frame; no new device command
  is needed for an ordinary visible snapshot.
- Local recording queues received compressed frames, starts at a keyframe and
  restarts on format/dimension changes (`VideoView:1303–1404,3294–3344`). It is
  distinct from recorder backup. A user request must specify channel, stream,
  location, maximum bytes/duration and retention.
- APK layout modes are exactly **1,2,4,6,8,9,13,16**, with16 preallocated views.
  The asymmetric6/8/13 geometry and tile replacement must follow the recovered
  `VideoManagerLayout:1263–1364`/segmentation resources. They do not prove16
  simultaneous streams. Current measured acceptance only establishes9.
- New scoped paging evidence: `VideoManagerLayout:680–712` uses single-finger
  fling for single-view channel switching and two-finger fling for `gs4.v`.
  `LiveViewLayout.v:4954ff` wraps channel sequences for a single device and pages
  nonempty favorite groups for multiple devices. It is not simply an arbitrary
  all-device list cut into equal-size pages. Its JADX duplicated-code warning and
  complete single-channel `LiveViewLayout.E:1603ff` branch need a DEX-backed
  behavior fixture before claiming exact APK paging parity.
- Quality is capability-derived: `LiveViewLayout.getVideoEncodeInfoList:1242–
  1318` offers Low Clearance/Very Clear when encode info is absent or the special
  model branch applies; otherwise returned encode entries plus Very Clear and
  conditionally Custom. Selection persists `CodeStreamType` (`T1:2579–2625`).
  Custom exposes resolution/FPS/bitrate in `R:layout/view_custom_rate.xml`.
  Actual `ChangeLiveStream(int,int,int,String,String,int,int,int,int) → boolean`
  carries task/format information; its field meaning must be recovered from
  `ku3:5460–5476` and native body. Main/sub selection alone is not the complete
  named-quality/custom contract.

### 4.2 Proposed delivery

Add a bounded snapshot port on the current decoded-source owner. It must copy a
frame under the existing RGB credit ledger, bind frame timestamp/channel/stream/
format epoch, encode and save through the asset owner, release credit, then
publish an authorized asset reference. Simultaneous all-visible capture resolves
each tile independently. A no-frame/stale-frame result is a failure or explicit
stale result with captured time, never a newly dated old frame.

For MP4 local recording, add an encoded-frame sink after validated source
demultiplexing and before decoder conversion. This is a proposed change: the
current `MuxFrameSource` deliberately transfers the exact batch and its credit
once, so a new sink needs reviewed reference/credit lifetime and a separate
bounded recording budget. A second uncharged queue or competing destructive
reader could break live playback. A format transition closes/validates the prior
part and begins a new keyframe-based part with a manifest; whether the user sees
one normalized MP4 or multiple parts is a product decision that must be recorded.

Browser-only recording can use the received MediaStream when the concrete client
supports a tested MIME/container, but the resulting container must be identified
truthfully. `MediaRecorder.isTypeSupported` does not guarantee successful encoding
under resource pressure. Prefer the server/gateway MP4 sink for APK-like MP4;
browser-only capture is separately labeled and accepted.
[W3C MediaStream Recording](https://www.w3.org/TR/mediastream-recording/).

Proposed files: media `{snapshot,recording_sink}.py`; core `media_assets.py`;
contracts `media_asset.py`; API `asset_service.py`; BFF fixed `/api/tvt/assets`
routes; UI `live/{SnapshotControl,LocalRecorder,QualityControl}.tsx`; extend the
existing monitoring scheduler/wall with `LiveLayoutPolicy` and `LivePagingPolicy`
after the live gate. Persist layout, page/group and requested stream profile
separately from backend leases. Paging retires hidden tiles with confirmed
settlement before replacement; focus return and recording tile replacement retain
the existing lifecycle contract. Layout16 remains capacity-limited until measured.

## 5. PTZ, presets, configuration, defense, schedules and firmware

### 5.1 Concrete source boundaries and missing bytes

| Selected operation | Recovered entry/fields | Current boundary and next decode |
| --- | --- | --- |
| PTZ movement/stop/zoom/focus/iris | `NetClientProtocal.SendPTZCtlCmd(int,int,int,int,int) → int`; wrappers:406–411; `ku3:6090,8047`, `ew3:5982,7628`. Numeric map in `cw3:8319–8359` to StopAction, directions, Near/Far, ZoomIn/Out, IrisOpen/Close | No project executor. Freeze command/speed/channel/task packing and error/stop acknowledgment from native. Movement and renderer dewarp remain separate |
| 3D PTZ | `RequestPTZ3DControl(int,int,int,int,int) → boolean`; `ku3:5262`, `ew3:5370` | Coordinate ranges, frame/aspect mapping and model support unmeasured |
| Presets/cruise reads and commands | `GetPTZInfo(int,int,int,long) → int`, wrapper `(int,short,int,observer,Object)`; query modes3/8. Direct names `queryChlPresetList`, `queryChlCruiseList`, `goToPtzPreset`, `runPtzCruise`, `stopPtzCruise` | Model-specific response decode and typed readback needed. Account alternatives below are separate credential/transport family |
| Account preset requests | `/sdk/DeviceGetPTZPresetList`: devId,chlId; add:devId,chlId,prsetName,presetIndex; delete:devId,chlId,presetIndex | Matching JNI exports exist. Exact HTTP serializer/reply body needs targeted `libProtoSDK` decode; keep misspelled source `prsetName` as input evidence, not a guessed HTTP field |
| Account generic PTZ | `/sdk/sendCmdToPTZ`: loginId,chlIndex,cmdType,presetIndex. Native overloaded `(long,String,int,int,int,int) → boolean` and `(long,String,String,int,int,int,int) → void` | One short JNI export, UUID forwarding/callback ambiguity and immediate simulated success. Do not use this as physical movement acknowledgment |
| Device information | Direct names `queryBasicCfg`, `queryChlStatus`, `queryRecordDistributeInfo`, `queryAlarmStatus`, `queryNetStatus`, `queryNetPortCfg`, `queryDiskStatus`, `queryDiskDetailInfo`, `queryTimeCfg`, `queryNodeEncodeInfo` | Extend typed read provider after tracing exact caller XML and reply parser; list/detail capability alone is not current device state |
| Defense | UI `/home/DevDefenseCfgAct` → `/home/DevDefenseAddCfgAct`/detail. New scoped trace: `ir0.v → fu3.x4`; `ir0.e/w → fu3.V1(dg0)`. `ku3/ew3` map to `querySystemDisArmParam` config8256 and `editSystemDisArmParam` config8257 | Generic `RequestApiTransport(int,byte[],int,long) → int` supplies transport. Decode `fu3.d2/dg0`, command wrapper, source permission gates and readback; account-bound branch instead uses requestGet/SetDeviceArm |
| Account arm/switch | `/sdk/requestGetDeviceArm` md5SN; setter md5SN,armStatus. `/sdk/getOnOffDeviceConfig` devSN,devModelNameArray,chlModelNameArray; setter raw JSON | Do not equate md5SN with internal connection UUID. Exact native serializer/model/action semantics not yet frozen |
| IPC recording schedule | `ScheduleTimeRecordingActivity → fu3.q3/w6`. New scoped `ku3:q3` uses `GetStorageConfig`16401; `w6(boolean,List<gq3>)` uses `SetStorageConfig`16402 | Source XML config1.7/storage/switch; schedule has maxTimeSpan100,maxYearlyDay31; each weekly period start/end/day from gq3. Freeze empty-list defaults, week grammar, bounds, time zone and reply parse before writes |
| Firmware | `/sdk/DeviceFirmwareCheckUpdate` devId, JNI `(long,String,String) → void`; manual update same. Direct recorder commands `queryCloudUpgradeCfg`, `checkVersion`, `getCloudUpgradeInfo`, `cloudUpgrade`, `cloudUpgradeNode` | Multiple distinct paths. Decode serializer/status/package-origin/hash/signature/version and reconnect semantics. A request named manual-update does not imply a browser-uploaded firmware file |

The Windows raw ABI already provides isolated `Send` and bounded callback ownership,
so these operations need additional private packet codecs/executors rather than a
vendor-manual prerequisite. Native Send's positive return is not reliable full
enqueue or delivery proof; require correlated protocol result and fresh device
readback. Stop/Destroy/UnRegisterNode do not establish in-process callback join;
retain original callback objects and bounded process retirement.

### 5.2 Proposed protected control ports

Add `ControlCapabilityObservation` scoped to device/channel/model/firmware/
connection and grant revisions. `DeviceCommand` is a closed discriminated union
for selected PTZ, preset, defense, schedule and settings operations. Add dedicated
`local_control.py`, `local_settings.py` raw codecs; bridge `local_control_provider.py`
and bounded RPC; core `control_service.py`/`settings_service.py`; API
`controls.py`/`settings.py`; BFF `/api/tvt/controls`/`settings`; UI
`controls/{PtzPad,PresetEditor,DefenseSettings,RecordingSchedule,DeviceConfig}.tsx`.

PTZ start creates a short actor/channel-bound motion session with watchdog-stop.
Pointer release, lost focus, touch cancellation, denied lease and deadline all
request stop; the server remains the final stop owner. Do not funnel rapid press/
release into the firmware job lifecycle. Preset create/delete, persistent
configuration and schedules have durable intents, expected revision/preimage,
one admitted writer and fresh independent readback. A conflicting external edit
must produce a conflict rather than overwriting from a stale form.

Firmware has its own concrete `FirmwareExecutor` and `FirmwareReadback` using
the existing FirmwareIntent engine. Read-only check/current-version/status can
be implemented first. A manual-upgrade UI becomes available only for a fully
decoded supported model/path, with power/storage/compatibility and package
validation. No firmware/share/delete command is executed by this research;
actual firmware, account removal, format/restart or ownership transfer tests
require separately scoped disposable-target authorization. This is the existing
W15 requirement, not a new global permission barrier to code planning.

Remote device settings, if selected within configuration, need typed reconstructed
commands from the captured prompt schema and exact page contract. An arbitrary
WebView URL/JavaScript proxy must not gain a device session. Dynamic served page
content is a specific later evidence task; it does not block the decoded direct
configuration branches above.

## 6. Account security, sharing, device addition and discovery

### 6.1 Security already decoded, still unwired

The existing private adapter takes current USER scope/token, deadline and
correlation ID. Fixed operations and exact wire fields are:

| Private method | HTTP POST operation path | `data` |
| --- | --- | --- |
| `update_profile` | `/user/info/update` | nickName,name:"",address:""; positive signed type only |
| `bind_phone`, `bind_email` | `/user/info/phone/bind`, `/user/info/email/bind` | mobile/dynamicCode; email/dynamicCode |
| `change_phone` | `/user/info/phone/update` | oldMobileCode,newMobile,newMobileCode |
| `change_email` | `/user/info/email/update` | oldEmailCode,newEmail,newEmailCode |
| `login_types` | `/user/info/login-type/list` | basic-only; required typed list, missing data is not empty list |
| `issue_code` | `/user/sms-code/get` | loginName,loginType,businessType,lang; source-bound image/config branches |
| `update_password` | `/user/info/password/update` | loginType,dynamicCode,encrypted newPassword |

Existing authority:
`tvt-security-private-adapter.md`, `tvt-account-security-source-completion.md`,
`security_{protocol,client,crypto,projection}.py`. Password key state depends on
private accepted login/renewal sid/tokenId, generation and key lineage; it is not
derived from USER-token text. Preserve `UNKNOWN_OUTCOME` after possible dispatch
and never replay automatically. Purposes PASSWORD1, REMOVAL2, EMAIL3, PHONE4 and
CURRENT/OLD/NEW stages bind to identity/account and one-use flow state. Profile
readback proves profile fields; it cannot prove changed-password login or
server-wide session revocation.

Add protected key capture/vault/admission and flow persistence only after checking
the latest source/state of the existing SID acquisition work. Add typed security
RPC/worker/API/BFF/UI and definitive readback to the current adapter. Proposed
files: core `security_service.py`/`security_admission.py`; bridge
`security_rpc.py`/worker ports; API `security.py`; BFF `/api/tvt/security`; UI
`account/{ProfileEditor,ContactChange,PasswordChange,SecurityStatus}.tsx`.
Add new SQL role/admission/flow/intent generation checks and generated contracts.

Selected complete account-security scope may also include avatar, personal QR,
provider linking/account type/removal. These remain distinct sub-slices: avatar
source is multipart `/user/info/avatar/update` with text `requestData` and file
part `file`; personal USER QR is reachable while web-login QR remains declared;
provider bind/unbind is conditional on configured web registration and accepted
TVT code contract; account removal `/user/unregister` needs its dedicated intent
and definitive reconciliation. Do not implement Android app IDs in browser OAuth
or mark an irreversible account absence from a timeout. The existing completion
document supplies their exact source handoff without requiring vendor manuals.

Additional recovered security fields, for selected conditional sub-slices:

| Sub-slice | Exact recovered request/model | Qualification |
| --- | --- | --- |
| Personal USER QR | Basic-only POST `/resource/user/qrcode/info/get`; result `UserQrcodeSignBean.userSign`; displayed QR has type userInfo and data email,phone,nick,userSign | Reachable source screen; no token/expiry field is established. Require nonempty admitted sign before usable display and keep raw payload private |
| Logged-in provider bind/unbind | `/user/info/third/bind`: code,loginType,appId; `/user/info/third/unbind`: loginType; native provider range3–7 | Conditional configured web registration/code acceptance; login-type readback required |
| Account removal | `/user/unregister`: loginType,dynamicCode; source type0 plus empty-code selects its distinct no-params variant | Purpose-bound flow, dedicated irreversible intent and definitive permitted readback; no executed absence or device/share aftermath proof |
| Web-login QR declarations | `/user/qr-code/scan`: qrcode; `/user/qr-code/login`: qrcode,allowed | UI reachability remains declared. No UUID issuance, polling, TTL or login-token model may be invented from these two serializers |

The fields above are identifiers/schema descriptions, not sample QR/account data.

### 6.2 Current share serializers

These are actual recovered HTTP paths, distinct from `/sdk` Java routes. They
reuse ordinary managed USER `basic.token` envelope and configured fixed origin:

| Operation | Concrete POST path/fields | Required result |
| --- | --- | --- |
| Share to account (`ShareChlRequest`) | `/resource/channel/share`: loginName; shareList[{sn,chlIndex,auth[]}]; devShareList[{sn,auth[]}] | Owner sent list plus recipient received/channel access. Constructor accountType is not forwarded by native serializer |
| Target shareability | `/resource/channel/share-able/list`: snList[],targetUserName | Freeze remaining response consumer and candidate shape; it does not itself grant the writer |
| Accept | `/resource/channel/share/accept`: id or ids[] or snList[], as distinct request variants | Per-ID/per-device readback, including partial batch results |
| Revoke/delete | `/resource/channel/share/delete`: ids[] | Owner/recipient share lists and blocked recipient actions/active leases |

Preserve exact permission verbs `live.video`, `live.audio`, `rec.video`,
`rec.audio`, `ptz`, `talk`, `alert`, `arm`, `config`; old `live`/`rec` are separate
decoded compatibility cases. Unknown/pending/missing auth stays denied. Share
capability does not grant execution and grouped child rows do not union sibling
permissions. The old `/device/camera/share-authority/set` uses string
`id,authoritys,scheduleType`, whose grammar remains undecoded; do not use the new
auth array there. Alternate getSharedListToAccount's DeleteShared reply-label
mismatch does not invalidate the working current sent/received list family.

Proposed modules: private `share_protocol.py`/`share_client.py` beside the current
directory client; core `share_service.py`/`share_admission.py`; API `shares.py`;
RPC typed share family; BFF `/api/tvt/shares`; UI
`devices/{ShareManager,ShareEditor,ShareReadback}.tsx`. New create/revoke intents
bind identity, target account, exact channel and permission sets, preimage and
business fingerprint. Keep grants fenced in REVOKING/UNKNOWN_OUTCOME until
definitive owner/recipient readback. Recipient live/playback/control permission
changes must invalidate current leases/generations, including shared live viewer
attachments. Two authorized test accounts are an acceptance dependency, not a
reason to block serialization/UI code work.

### 6.3 Device addition and LAN discovery

Local serial/QR-image credentials and actual inventory verification already exist.
Extend that enrollment authority for IP/DDNS/manual addresses with host/port
canonicalization, network policy, current device login and no secret projection.
Local credential addition, local removal and account bind/unbind/transfer are
different effects. Current special bind `/device/bind` and transfer `/device/move`
need the remaining precise MD5/SHA512/AES/sign derivation in the established
directory handoff before dispatch; generic plaintext JSON is not compatible.
The inspected arm64 `deviceRegister` JNI does not dispatch; do not advertise its
declaration as a working remote registration path.

New scoped discovery evidence:

- `DeviceManagerSearchLocalActivity:184–195` creates `zv3`, starts it and subscribes
  to DeviceItem results; UI refresh timeout is60000ms.
- `zv3` creates a configured multicast socket on UDP23456, sets TTL4 and sends
  every10000ms. `pj2.a()` declares140-byte requests; request identity consists of
  four-character magic `MHED`, command65546, mode1, configured customer ID and a
  fresh6-byte nonce. `pj2.c()` is the exact serializer to freeze with synthetic
  golden bytes; no hardcoded device credentials are part of discovery.
- `qj2` parses the main response into address/port, serial/name/model/version/
  customer identity. The APK applies OEM black/white-list filtering. A second
  `eb4/db4` reader is declared, but its socket activation is not established by
  the scoped constructor/start path and must not be reported as active support.
- The nonce-matching loop in `zv3.e` is suspicious JADX reconstruction; inspect
  original DEX before implementing it. Use actual datagram length and bounded
  result counts rather than copying the source's1024-byte backing-array parsing.

Proposed local gateway `DiscoveryPort.start(network_scope,deadline)` returns a
short-lived job/candidate set; each result is untrusted until explicitly selected
and authenticated through existing verification. Add core
`local_discovery.py`, bridge `local_discovery_provider.py`, API
`discovery_service.py`, BFF `/api/tvt/discovery`, UI `devices/{AddDevice,LanDiscovery,
QrFlow}.tsx`. This executor must run on the permitted store network; a hosted
browser does not operate Android multicast/Wi-Fi APIs. QR live-camera scanning is
a browser permission/input enhancement to the existing image-input path. QR10
encrypted local credential import requires its separate key/CRC/scrlen decode and
private vault policy; never log or publish decrypted PW.

## 7. Alarm inbox, push and media files

### 7.1 Recovered reachable alarm transport and request boundary

The visible APK alarm tab is local push cache plus Push2 history/detail; system
messages use a separate service list. Generic getDeviceAlarmList/latest/count/
unread routes remain declared for this UI. Device login/status callbacks are not
alarm ingress. Implement the reachable path first.

| Reachable operation | Exact SDK input/boundary | Remaining codec work |
| --- | --- | --- |
| Push2 history | `/sdk/getUserDeviceEventMessageList`: md5SN,lastId,lastTime,pageSize; native `(long,String,String,String,int,int) → void` | Decode native HTTP serializer, lastId/time integer/string meanings and `Push2EventInfoListBean` ordering/paging; source `da3:273–385,577–583` |
| Push2 detail | `/sdk/getDevicePush2DetailMessage`: raw JSON; native `(long,String,String) → void` | Trace lazy `detailRequestFlag` caller and exact JSON/attachment/model fields |
| Push2 config/read/edit/delete | getDevicePush2Config(md5SN); editDevicePush2Config/deleteDevicePush2Message(postJson) | Native functions/replies exist; raw postJson is not a reviewed public command schema |
| System messages | `/sdk/GetServiceMsgList`: msgType,startTime,endTime,pageNum,pageSize; GetServiceMsgType/GetUnReadServiceMsgNum basic-only; SetServiceMsgListStatus msgIdList,status | Decode exact native paths and typed response; source `fc3:61–68,112–127` |
| Global push | `/sdk/GetMsgPushSwitch` basic-only; SetMsgPushSwitch isOpen,schedule; native getter `(long,String)` and setter `(long,String,boolean,String)` | Source schedule request exists, but server enforcement unknown |
| Token registration | `/sdk/sendNotificationToken`: tokenID,appID,pushType,dataMessageTypes; native `(long,String,String,String,int,List<String>)` | Android FCM token/app registration is not a Web Push subscription. Decode/authenticate a server-supported ingress registration path |
| TVT socket | `j` discovers SDNS/TPNS, initializes `PushMessageSocket`, registers app token, requests offline batches, parses framed XML and ACKs IDs/types | Frame/header/registration/heartbeat/SDNS/auth/native algorithms need offline extraction and bounded server worker; never persistent raw socket in service worker |

FCM and TVT socket are two inbound planes; Push2 history is catch-up/readback,
not proof of live ingress. The APK's FCM refresh actionless platform broadcast
cannot reach its LocalBroadcastManager receiver as written. Porting that broken
branch is not an acceptable registration implementation. Unknown subtype remains
visible safely;58 legacy strings and68 Push2 constants are a client taxonomy,
not68 independently supported outcomes. Generic device-alarm list routes and
their read/delete status must not be substituted for local inbox state.

### 7.2 Proposed durable event and browser delivery design

Add one normalized event journal used by vendor alarms and, through a separate
producer/provenance, the controller's anomaly events. Deduplicate by scoped stable
source ID and source provenance, never just timestamp. Persist event, authorized
recipient state and existing outbox in one transaction; after commit deliver to
foreground UI and Web Push. Vendor alarm ingestion is a concrete server worker
family; browser push is the downstream delivery channel and cannot stand in for
missing upstream ingress. A temporary history-only inbox must explicitly report
that live alarm delivery remains incomplete.

Extend `contracts/tvt/event.py` or add local-device event references, since its
current `TvtEvent.device` is account `DeviceRef` only. Proposed files follow W13:
`services/tvt-events/src/wso_tvt_events/{ingest,dedupe,delivery,subscriptions}.py`,
core/API `event_service.py`; migration for event journal/per-recipient state/
subscriptions; BFF `/api/tvt/events`/`push-subscriptions`; public `tvt-sw.js`; UI
`events/{EventInbox,EventDetail,PushSettings}.tsx`.

Store encrypted subscription endpoint/key material, rotate/revoke per actor,
and authorize detail/image/live/playback again on notification navigation. Push
payload contains only an opaque event ID and permitted generic text. Web Push
can wake a service worker for inactive web applications; subscriptions can expire
or rotate and delivery is subject to restrictions. Measure foreground/background/
closed-tab behavior on the chosen browsers; server acceptance or subscription
creation is not notification/display receipt.
[W3C Push API](https://www.w3.org/TR/push-api/).

### 7.3 Media file workflow

Reuse the existing private AssetStore rather than creating a second unencrypted
video store. General video containers/large multipart or streamed output,
thumbnail/probe/transcode jobs, range download, retention and user file index are
new work; existing JPEG/PNG upload metadata is insufficient. Server-backed media
has a mandatory asset FK and authorization/provenance. Browser-only files have
opaque local ID plus IndexedDB metadata/blob and no server asset FK. Metadata
records owner, source, channel/time, MIME/container, byte size, content hash,
location, retention and conversion relation. Browser-profile availability is
visible to the user.

Proposed API `asset_service.py`, UI
`files/{FileManager,FileSearch,ImageViewer,LocalPlayer,ShareImage,DeleteFiles}.tsx`,
platform `file_store.ts`, fixed BFF assets routes. Original file download and
converted preview have distinct MIME/name/hash. BMP/PNG/MP4/AVI import and corrupt
media error behavior need explicit test fixtures; neither a filename extension
nor upload200 proves decode support. Existing APK-private storage requires a
user-selected export/import path; declared-only FileSync startup is not a file
migration implementation.

Image share uses actual File bytes when `canShare({files})` accepts them and the
user invokes sharing; file sharing requires transient activation. Unsupported
clients use an explicitly labeled download/send flow and must verify recipient
bytes before equivalence. Cancellation is not deletion or success.
[W3C Web Share API](https://www.w3.org/TR/web-share/#sharing-a-file).

## 8. Staged tasks and dependency contracts

The controller's anomaly priority may consume evidence/playback/event interfaces
early. The selected APK domains are delivered after the current live gate,
in slices that can independently pass source and actual acceptance.

| Stage | Concrete tasks and frozen output | Dependency/acceptance gate |
| --- | --- | --- |
| S0 live gate | Fresh bounded12-camera Chrome run, common300s,1/4/12 sizing, focus/return/Stop/reattach/format/lifecycle; retire owned prior context from its existing marker | Current Stage2 source/raw2/raw4 is retained. Old Chrome exit0/reap already exists; do not repeat obsolete user-close request. Hardware/browser gate is controller-owned |
| S1 read/decode contracts | Recorder search/playback native decode; PTZ/config byte map; Push2/socket decode; discovery DEX and golden bytes. Freeze per-operation input/result/error/capability matrix | Exact source IDs + original bytes; invented fixtures establish serializer/parser behavior, never actual completion. No unavailable vendor manual prerequisite |
| S2 evidence/media vertical slice | Snapshot asset save/list; one-channel1x recorder calendar/timeline/playback; precise seek; backup MP4 job/file download | Current channel/grant/device-clock/model observation and independent recorded-frame/file validation; decoder/browser/time acceptance |
| S3 complete selected media | Supported speed/step modes; local compressed-frame MP4 recording/format parts;8 layouts/paging/quality; complete album/search/share/delete/storage recovery | Source-mapped rate/quality/layout semantics; measured capacity remains visible; cannot assume16 accepted from12 gate |
| S4 security/sharing/enrollment | Existing8 security methods protected end-to-end plus required selected avatar/QR/etc; current share create/accept/revoke and recipient fences; local IP/DDNS/LAN add | USER key lineage and typed intents; exact recipient/channel/action readback; approved disposable-share tests. Bind/transfer waits only its targeted crypto decode |
| S5 device controls | Info/config reads, bounded PTZ-stop, presets; defense and schedule writes/readback; firmware checks/status then concrete approved update/reconcile path | Supported device/capability and current permissions; persistent setting/readback; physical motion/stop; scoped firmware execution |
| S6 alarms/push | Concrete upstream socket/Push2 ingress, durable inbox, system tab, detail/read/delete/navigation, subscriptions and closed-tab push | Stable event identity/provenance, outbox crash recovery, real alarm and notification receipt/lag, grant revocation |
| S7 selected parity/release | APK/web same-state comparisons for every selected P row; browser/model/role negative variants; immutable package and restore/rollback | W23 continuous security controls; W24 actual comparisons; W25 staged deployment. Global77-case100% parity remains a separate broader scope |

Before an implementer starts each task, freeze these ports together:

1. **Authority:** allowed action, actor/store/identity/connection/channel and all
   relevant revisions, current credential kind and capability observation. Saved
   ID, inventory or UI visibility alone grants no new operation.
2. **Transport:** private input, fixed origin/network, deadline, positive/negative/
   malformed result, callback/task generation, cancellation/close and worker Job
   custody. A new executor must not weaken current live cleanup or credit limits.
3. **Persistence:** resource provenance, one owner, operation/job/idempotency key,
   deterministic business intent, expected preimage, unknown-outcome hold and
   authoritative readback. Add new SQL kinds/constraints deliberately.
4. **Public contract:** generated OpenAPI/TS/proto, sanitized bounded errors and
   states, BFF auth/CSRF/cancellation behavior and user-reachable feature menu.
5. **Acceptance:** source baseline, current model/firmware/role/browser matrix,
   setup/action/readback timing, artifact digests and cleanup/source/privacy proof.

## 9. Meaningful verification and actual acceptance

The following tests are proposed for implementation; none were run here:

| Area | Necessary automated tests | Actual comparison evidence required |
| --- | --- | --- |
| Search/calendar | Golden decoded packets, malformed/truncated/oversize, wrong task/channel, incomplete pages, empty day, timezone/DST/day boundaries, denied rec permission | Known recorded interval before/during/after; APK/web channel/date counts and source time/zone match |
| Playback/seek/speed | Separate live/playback authority, seek epoch flush, stale callbacks and old queued frames, keyframe alignment, rate-mode mapping, replay/reconnect/cancel/expiry/resource limits | Requested/keyframe/decoded/presented timestamps; measured source-time-to-wall-time speed; ten scoped seeks including bounds/errors; remote task and original decoder/peer cleanup |
| Export/local record | Invalid range, keyframe start, codec/extradata, format rotation parts, interrupted writer, disk full, quota, cancellation, duplicate job, lease revocation | File exists with final hash/size, ffprobe/independent decode and browser playback, actual first/last source frame/channel/duration; transformed bytes compare decoded content within declared tolerance |
| Snapshot/layouts/quality | No frame/stale frame, exact frame identity, charged RGB copy, simultaneous capture failures,8-mode geometry, paging order/wrap/group, focus-return/hidden lease settlement | Saved image pixels/time/channel match; presented requested quality dimensions/FPS/bitrate; supported layouts/capacity measured with channel identities and no orphan tasks |
| Account security | Stage/purpose/code binding, key lineage/token generations, old/new contact codes, revoked callback, malformed acknowledgement, uncertainty/no replay, typed profile/login-type readback | Prepared-account field readback in second session, new-login viability and old-password/token behavior measured separately; no actual irreversible removal without scope |
| Sharing | SQL canonical intent/hold, channels/verbs, batch partial result, revoked recipient, expiry, open lease during revoke, lost acknowledgment and reconciliation | Owner/recipient lists, allowed/forbidden live/record/PTZ/config actions; actual propagation time and active-recipient cutoff |
| Discovery/enrollment |140-byte golden request, nonce replay/mismatch, actual datagram length, parser bounds/invalid UTF8, spoofed/duplicate result, wrong network/customer, cancellation | Selected network actual devices discovered; authenticated8/4/etc inventory matched to selected result; duplicate and absent-gateway errors; no unselected side effect |
| PTZ/settings/firmware | Command/range types, press/release/watchdog-stop, stale capabilities/preimage, wrong channel, unsupported model, XML parser bounds, schedule rollover, uncertain write no repeat | Visible physical movement and stop, preset reload, settings/defense/schedule fresh readback after reopen/restart; supported firmware version/status/reconnect only for approved target |
| Alarm/push | Live/offline/history duplicate identity, unknown subtype, per-user read/delete, revoked grant, outbox crash-after-commit, subscription rotation/revoke, attachment denial/expiry | One consented actual alarm: source receipt→journal→recipient→push display/tap/detail→right channel/playback lead-in. Lag p50/p95/max and duplicate/loss counts by browser state |
| Files/security/release | RLS/non-owner/wrong actor, signed range download, MIME spoof/corrupt import, retention/quota, real File sharing cancellation, secret scans, API contract generation, upgrade/rollback | Original and preview digests, recipient-visible bytes, browser profile/location behavior; selected parity cases on deployed staging and exact source/cleanup receipts |

Use the project's existing meaningful unit/contract/integration/web gates for
changed files, disposable owned PostgreSQL role/migration tests where new SQL is
added, and exact source/worker receipts before native tests. Extend the original
plan's named test families (`test_recording_search`, `test_playback_export`,
`test_local_assets`, `test_device_commands`, `test_devices_shares`,
`test_alarm_pipeline`, `test_sensitive_operations`, `test_security_recovery`) only
with cases covering real new contracts/failure risks. Static reviews, fake packets
or placeholder UI cannot close actual feature/parity rows.

Acceptance budgets for new seek, export, PTZ stop and alarm delivery must be set
from source/reference observations and product requirements before the run.
Record numerical results; do not invent APK timing promises. The existing300s
live interval is a retained project gate. Source speed, quality preset and exact
seek/keyframe results can differ by firmware and must appear in the supported
matrix with measured tolerances. HLS fallback is a planned codec path: FFmpeg HLS
segments need correct keyframe boundaries; mark independent segments only when
that property holds, with authenticated playlist/segment access and expiry.
[FFmpeg HLS muxer documentation](https://ffmpeg.org/ffmpeg-formats.html#hls).

## 10. Targeted offline decode backlog and open product decisions

| Missing fact | Exact next source action | Output needed for implementation |
| --- | --- | --- |
| Recorder wire/time/filter/rate | Follow media exports listed in3.1 and `ku3/ew3` task/result parsers; extract relevant ServerNVMSHeader structures; inspect original instructions when JADX types are ambiguous | Per-operation request/reply/error/close bytes, timestamp unit/zone, channel mask, rate/keyframe/control semantics with invented golden fixtures |
| Device command/config response | Trace RequestApiTransport native packing plus `cw3/ew3/ku3` request builders and result dispatch; PTZ command/speed map and `fu3.d2/dg0` defense; q3/w6/gq3/o84 schedule | Typed exact payload/result/readback, allowed ranges and empty-list behavior; source permission/capability branches |
| Firmware path | Full DeviceCloudUpgradeActivity and ew3 query/check/node flow; corresponding ProtoSDK native serializers and version/status consumers | Exact model/version/origin/hash/signature/readiness/progress/reboot/reconcile semantics; no guessed package-upload flow |
| Discovery packet/Dex behavior | `pj2/qj2/lk2`, original zv3.e DEX, secondary eb4/db4 activation and GlobalUnit configured group/OEM selection | Bounded140-byte request and actual-length reply grammar, nonce/customer filters, secondary-path applicability, cancellation/network scope |
| Quality and paging | Full bw/encode mapping, ku3 ChangeLiveStream and its native body; LiveViewLayout E/v and VideoManager layouts, original DEX for warned branches |8 geometry fixtures, per-mode/channel/favorite paging rules, named/custom profile fields/ranges and requested-versus-presented state |
| Shareability/old permission grammar | GetSharedListByTargetUser response consumer; old infoDic→authoritys/scheduleType and batch result models | Safe editor bounds/readback and separate old/new schema; current new create/delete remains implementable independently |
| Bind/transfer | Existing directory W bodies0x2e7698/0x2ea0ec and FUN0x3172d8; source original instructions/crypto vectors | Exact encrypted/signed bytes, targetType mapping and owner/bind-status readback; local registration proceeds independently |
| Alarm live/history | PushMessageSocket/j framing, SDNS registration/offline ACK; native Push2/system/switch request bodies; da3, Push2 detail beans and DEX-failed cache method | Fixed upstream paths/frame schema/auth, stable IDs, paging/catch-up/read-delete semantics, bounded attachment model |
| Remaining security subflows | Reuse completed post-login source and current SID acquisition state; personal QR/provider/removal/multipart consumers | Protected key lineage, typed per-operation flow/readback and configured browser provider availability |

Open product decisions: supported browser/OS versions and local gateway network;
which recorder model/firmware/roles are in the selected first release; device time
zone proof and daylight-saving semantics; video-only recording scope; recording
length/storage/retention and part-versus-normalized-file behavior; requested speed
modes and timing tolerances; exact selected account/provider/removal branches;
prepared recipient/disposable target availability for real mutation tests; push
latency and background delivery expectations. These decisions govern acceptance
and exposure. They do not require waiting for unavailable vendor documents or
fabricating success for undecoded branches.

## 11. Verification performed and limitations

Performed only read operations: `git status --short`, `git rev-parse HEAD`, branch
name; `rg --files`/`rg -n`; UTF8 reads of canonical project/source evidence and
scoped preserved APK classes/resources; selected SHA256 reads; official W3C/
FFmpeg documentation browsing. A mistyped nonexistent security-document path and
several guessed APK filenames/locale paths were corrected by file/path discovery;
no missing-file result is treated as missing functionality. Some broad read
outputs were truncated, so exact follow-up excerpts underpin the claims above.

Selected source correspondence hashes read today:

| File | SHA256 |
| --- | --- |
| `apk-audit/03-media.md` | `e05f7dd8b557e01847658296aca4b7cc5db7e127646b6fc96d767fdf77b249fe` |
| `apk-audit/04-alarms-push.md` | `841dc97ec6d9f79b5f0e08b8cf1f40da6c3cef61c6b1bc951d8f5058fd09a4b9` |
| `tvt-device-directory-source.md` | `196173419e7ccb2355d11fa32e72d14a930ea9330821e57f1ddacb1f08524140` |
| `tvt-security-private-adapter.md` | `e7c6a470e5bd141e7401c8acae27659e5fdabc4e7741120edf1e6f6874b772a2` |
| `bridge/windows_socket.py` | `1ad25ee670dde8397872dc38f3909baca1bac53a8b304f118d6786161fe375fb` |
| `contracts/tvt/media.py` | `0b7f67cfaefadd7b14e0bfdab571801fa5cc54615fb1624eaa2758408f57f4ef` |

No source tests, native load, DLL/SDK call, actual credential access, DB operation,
device command, event registration, browser/process management, dependency change,
Git write, commit/push/integration or deployment occurred. Historical acceptance
is cited from reports rather than rerun. The global parity ledger remains77 cases,
MATCHED0 and release_ready=false; this selected research does not reclassify it
or the141-row matrix. Proposed files and APIs above are implementation targets.

Reference authorities relative to the implementation worktree:

- `docs/service-analysis.md`, `docs/analysis/2026-10-04-apk-feature-parity-review.md`,
  and the current Stage2 execution/acceptance ledgers.
- `docs/superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md`.
- `docs/integrations/apk-audit/{02-protocol-api,03-media,04-alarms-push,
  05-device-controls,12-functional-parity-contracts,14-reachability-and-route-gaps}.md`.
- `docs/integrations/{tvt-windows-socket-abi,tvt-local-live-codec,
  tvt-local-live-mux-codec,tvt-device-directory-source,
  tvt-account-security-source-completion,tvt-security-private-adapter,
  tvt-operation-engine}.md`.
- Current source: `packages/contracts/src/wso_contracts/tvt/{media,event,operation}.py`,
  `packages/core/src/wso_core/tvt/{local_live,local_live_mux,security_client,
  security_protocol,operations}.py`, bridge Windows socket/worker/provider and
  media native_source/mux_source, registered API/RPC and public shell.

Update log: 2026-10-08 — researched the user-selected APK domains against current
worktree source and established handoffs; recovered scoped JNI signatures, paging,
quality, defense/schedule and multicast discovery evidence; separated current
codecs/public flows/historical acceptance; recorded staged files/interfaces/tests
and precise remaining offline decode tasks without executing devices or writes.
