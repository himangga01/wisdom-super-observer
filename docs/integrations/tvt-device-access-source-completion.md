# TVT device access and native bootstrap source completion

Analysis date: 2026-10-03. Repository baseline supplied for this task: `756946ca73cff31d7ebb23141873088b470a96b4`. APK: SuperLive Plus 1.18.1, version code 20267, 170,064,551 bytes, SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. The saved September extraction and October 2 handset copy have the same complete APK identity; the evidence manifest records the actual checks. This is a targeted static handoff for the existing account worker and Android helper. No account, device, native library execution, server, database or browser acceptance was performed. MATCHED remains 0; release readiness remains false.

This document extends [the directory source](tvt-device-directory-source.md), [APK adapter contracts](apk-derived-adapter-contracts.md) and [the Android helper](../../services/tvt-android-helper/README.md). Its principal new findings are that device expiry is **absolute Unix seconds**, the selected arm64 JNI path narrows it to **unsigned 32 bits**, renewal is **native callback driven**, and account directory `sn` is passed unchanged as the connection device ID. These are source contracts, not successful interoperability observations.

## Evidence notation and scope

`J:path:line` refers to the original saved JADX source, relative to `jadx-full/sources/`. `P:address` is an arm64 Ghidra address in `libProtoSDK.so`; `N:address` is an arm64 Ghidra address in `libNetClientProtocal.so`. Both use image base `0x100000`; subtract it for an ELF virtual value, never for an APK ZIP offset. Fresh selected functions were read from the existing Ghidra project with `-readOnly -noanalysis`; full body text, instruction checks, command arguments, timestamps, native exits, errors, completeness checks and hashes are retained in the private W04 evidence packet. No full APK decompilation was repeated. Previously accepted packets remain unchanged.

| Selected library | arm64 bytes | SHA-256 |
| --- | ---: | --- |
| `libProtoSDK.so` | 6,446,688 | `b7731270d75573668cbb38a08b611a8ae2460e586181f475c4c4d7eb7cdf735b` |
| `libNetClientProtocal.so` | 3,920,784 | `c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717` |

ARM32 signatures/binary identities remain in [the ABI inventory](apk-audit/08-native-abi-jni.md). This pass does not infer ARM32 arithmetic or timing from arm64. JADX's historical full extraction had 391 errors; the exact selected paths and native corroboration, rather than a clean whole-extraction claim, support the conclusions below. Ghidra sometimes infers `void` for forwarding/return-register functions: narrow arguments and timer arithmetic were separately inspected at instruction level.

## Acquire a device credential through the USER session

`J:com/tvt/protocol_sdk/request/GetDeviceAccessTokenRequest.java:11–26` accepts Java `devId:string`. `TVTOpenSDK.java:245,1554–1559` supplies the native handle/callback routing. `DeviceProtoAPI::getDeviceAccessToken P:0x2f230c` rejects an empty selector before constructing one string member, `data.sn`, and queues **POST `/device/access-token/get`** through `ProtoSdkManager::addHttpTask P:0x2d6804`. The JSON key/path globals are resolved by the saved complete initializer evidence (`DAT_007473e0` → `sn`; `DAT_00747bc0` → route). Its returned native admission bit is not the credential result.

The existing ordinary account envelope applies:

```text
basic.ver   = "1.0"                        string
basic.id    = decimal task ID              string
basic.time  = Unix seconds                 number
basic.nonce = generated nonce              number
basic.token = current USER credential      string, present when nonempty
data.sn     = authorized opaque directory SN string
```

Evidence: `createBasicInfoJson P:0x2d057c`, `createPostJson P:0x2cc3f0`, the saved ordinary JSON POST transport and this operation's complete builder. This operation derives neither a password proof nor a new `basic.sign`. The generic builder can copy a supplied sign; no such sign producer is established for this call. Use the existing isolated, region-bound account worker and content type `application/json;charset=UTF-8`. No Authorization bearer header, P2P token or DEVICE token replaces `basic.token`.

`J:defpackage/yr0.java:26–28,50–61` constructs the request only while Android's `isLogin` flag is true. A false flag exits without an explicit completion in this method. The service must instead return a bounded session-unavailable result. The native builder itself is not proof of authorization checks: require current USER session, current actor/device/channel grants and scope before issue and use.

The result path is `yr0` → `q63.b` → `DeviceAccessTokenBean` → `ku3.f.onSuccess`. `J:com/tvt/server/NVMSAccount/bean/DeviceAccessTokenBean.java:6–13` declares **both `datoken` and `exp` as Strings**. `q63.java:41–74` reads `data` as JSON text with an `array` fallback and deserializes with Gson. This declaration does not prove the server always emits a quoted JSON string for `exp`; no response was captured. Preserve the original scalar privately, accept only explicitly supported integral number/decimal-string forms in the service decoder, and reject arrays, objects, booleans, fractions, overflow and missing fields. Treat any accepted numeric form as a deliberate decoder compatibility rule until runtime shape is observed.

Success must require acceptable HTTP status, business code 200 and valid nonempty token/expiry. `J:defpackage/bm3.java:18–40,57–62`, `qo3.java:31–33`, `vm3.java:19–20` establish the business decision. `q63.java:41–74,111–157` distinguishes transport codes, business codes and network normalization. Codes 7000, 7003, 10002, 11101, 7004, 7009, 7088, 7089 and 7090 dispatch global event 65634 instead of the ordinary local failure callback; null/reactive failures use -100. These are source routing categories, not a complete device-access authorization dictionary. Keep actual numeric failures private, route session-invalid outcomes through serialized USER recovery, and never turn malformed success or timeout into a credential.

## Expiry, connection budget and renewal

### Exact arm64 time contract

`J:defpackage/ku3.java:2154–2172` parses `exp` using `Long.parseLong` and calls `ConnectDevByToken(datoken, exp, 30, f5, observer)`. JNI `N:0x21e0b8` forwards expiry through `w1` (`N:0x21e11c`), narrowing the Java long to unsigned 32 bits. `CConnectNodeByToken::Connect N:0x22632c` stores that expiry at node offset `0x80` and passes the separate timeout to `Net_Comm_ConnectByToken`. Renewal JNI `N:0x21e19c` likewise uses an unsigned 32-bit expiry. Do not silently reproduce truncation: validate `1 <= expiry_epoch_seconds <= 4294967295` before either call.

`CConnectNodeByToken::CheckRenewDaToken N:0x226a60` compares that stored value with `CPFTime::GetTime`. `CPFTime::CPFTime N:0x256368` obtains `gettimeofday().tv_sec`; `GetTime N:0x256a50` returns it. Thus `exp` is used as an **absolute Unix epoch second timestamp**, not milliseconds or a duration. The renewal predicate is exactly:

```text
expiry != 0 AND now_seconds < expiry AND expiry - now_seconds < 300
```

At exactly 300 seconds remaining, or at/after expiry, this predicate does not request renewal. A clock change can alter that window. This proves the APK client's interpretation; server issuance accuracy, clock skew tolerance, revocation and effective token usability still require runtime observations.

`CConnectManger::CheckRenewDaTokenProc N:0x22572c` only scans when `((uint32)(tick_now - previous_tick) >> 4) > 0x752`, equivalent to at least **30,000 tick milliseconds** elapsed. `CPFHelper::GetTickCount N:0x252740` computes monotonic `clock_gettime(1)` seconds × 1000 + nanoseconds / 1,000,000; instructions preserve the result even though the decompiler infers a void return. The scan snapshots connection references, invokes each node's renewal virtual method and releases the references. `Start N:0x224350` creates the native thread; callback `SendThread(void*) N:0x2243c8` invokes its send-work method and then the renewal scan. The 30-second gate is a **minimum scan interval**, not proof of exact wall-clock callback cadence: the generic thread scheduler and load were not executed or fully decoded.

The `30` connection argument is independently a **seconds budget**. It reaches `CTNATClientPeerManager::Connect N:0x233c80` and `CTNATClientPeer::Connect N:0x265d6c`, which stores `timeout * 1000` and a monotonic millisecond start. `IsConnectTimeout N:0x26772c` checks elapsed milliseconds against that budget and also treats tick wrap (`now < start`) as timed out. This budget is not HTTP request timeout, credential TTL, first-frame deadline or an end-to-end gateway SLA.

### Actual refresh path and failure handling

1. The node renewal callback reaches `CNetClientProtocalSdkObserver::OnRenewDaToken N:0x220290` and Java `OnRenewDaToken(int connection)`. `J:com/tvt/network/NetClientProtocal.java:193–198` resolves the connection observer and calls `h()`.
2. `J:defpackage/ku3.java:7329–7331` calls `qa(f5, true)`; `qa:3769–3773` repeats the same access-token acquisition. This is a new USER-authenticated request for the same device, not USER token renewal.
3. `ku3.f:390–430` resets its failure counter on success, requires a nonempty `datoken`, stores the bean, and for renewal requires non-null expiry and a positive connection handle. It calls `renewDaToken(connection, token, parsed-expiry)` inside an exception catch. The app ignores that return value.
4. Java `renewDaToken:450–457` returns 1 for empty token, 2 for nonpositive expiry; otherwise calls native `RenewDaToken(I,String,J)I`. Native `N:0x21e19c` returns a boolean admission bit. Consequently **1 is ambiguous across the Java guard and native result**: validate inputs first and retain the branch context.
5. `CConnectManger::RenewDaToken N:0x2246d4` queues `Net_Comm_QueryDevInfoByToken(new-token,30,observer)`, records query ID → (connection,expiry), and returns 1. It does not establish completed renewal. `OnQueryDevInfo N:0x224c00` requires parsed `devInfo.daToken`, resolves/removes the query mapping and invokes the connection renewal virtual method. `CConnectNode::RenewDaToken N:0x226138` stores expiry when its protocol object exists and invokes protocol slot `+0x18` with the derived token and length. This internal `devInfo.daToken` is distinct from the account HTTP field `datoken`; preserve native processing.

Ordinary acquisition failures increment `d6`; counts below 3 schedule another request after **1000 ms**, while the third failure resets the counter and calls `j4(false,-1)` (`ku3:390–402`; `mc3.java:23–32,79–80` uses `SystemClock.sleep`). Thus the observed chain has at most three failed attempts with two delays. This is not a total elapsed-time bound; the selected reactive request path adds no proven response timeout. Missing/empty successful tokens call `j4(false,-6)` immediately. Parse exceptions are caught/logged in the APK but do not establish a terminal gateway result. No Java expiry timer appears in this selected flow: `c6`/`b6` record HTTP acquisition duration (`ku3:415–417,3771`), not expiry or refresh scheduling.

Other implemented Java consumers use the same native expiry contract but differ in local retry behavior:

| Consumer | Renewal entry and connection input | Local acquisition failure |
| --- | --- | --- |
| IPC `ku3` | `h:7329` → `qa(f5,true)`; connect `fa:2167` | Three failed attempts, two 1000 ms delays as above. |
| NVMS `ew3` | `h:7055–7056` → `ra(n4,true)` (`:4506–4509`); connect `ga:3491`; `L1:5273` assigns the same supplied device ID | Same counter/delay pattern at `:361–399`. |
| Doorbell `iu3` | `h:5541–5542` → `N9(R4,true)` (`:2227–2230`); connect `C9:1115`; `L1:1886` assigns the supplied device ID | `:365–368` immediately calls `j4(false,-1)`; this handler has no three-attempt retry loop. Renewal response guards and native call are at `:373–395`. |

These are local handler policies; they do not prove the absence of higher-level reconnects. Keep a deliberate gateway retry policy rather than assuming IPC retries apply to every device kind.

The manager/node code does not prove in-flight renewal deduplication or a terminal renewal acknowledgment. Repeated native scans can ask again while expiry remains in the window. The service should serialize renewal per session generation/connection/device, impose its own total deadline and bounded retry budget, recheck grants before dispatch/use, reject late results, and fence media when usable credentials expire. These are service policies, not extra APK guarantees. A renewal admission bit must not advance public state to renewed/connected.

## Eight bootstrap inputs and the P2P boundary

`J:com/tvt/launch/LaunchApplication.java:449–465` constructs the config, calls `GlobalInit`, then `Start`. `NetClientProtocal.java:27–54,312–314` and `defpackage/ye1.java:7–25` fix the eight JSON keys and Gson `serializeNulls()` behavior. The saved native init parser reads those same keys. Private startup configuration must preserve types and the distinction between absent, empty and null; successful acceptance of every null/empty combination is unproved.

| JSON key | Type | Source provenance and implementation input |
| --- | --- | --- |
| `cliType` | integer | Explicit application client-kind literal assigned at `LaunchApplication:461`; carry as reviewed private build configuration, not inferred from a browser user agent. |
| `clientToken` | string | `TVTOpenSDK.readKeyValue("keychain_p2p_token")`, `LaunchApplication:457`. Comes from the managed account's P2P state; not USER or DEVICE credential. |
| `customerId` | string | Explicit application/OEM literal at `LaunchApplication:459`; source is the launch config, not directory owner ID. |
| `ispCode` | string | Explicit empty application value at `LaunchApplication:458`; do not invent an ISP from network location. |
| `natServerAddress` | string | `BaseReqType.BaseNatClient`, `LaunchApplication:455`; mutable selected application/region configuration, described below. |
| `natServerPort` | integer | `BaseReqType.BaseNatPort`, `LaunchApplication:456`; resolve alongside the address, validate 1–65535. |
| `svnCodeId` | string | Explicit application build literal at `LaunchApplication:460`; not the repository commit. |
| `szClientVer` | string | `BuildConfig.VERSION_NAME`, `LaunchApplication:462`; application version provenance must be explicit. |

### Bootstrap memory boundary before Init

The current `RuntimeConfig.java:14–24` applies the same **4096 Java UTF-16 code-unit allowance** to every string. This does not protect native initialization. `CNetComWrapper::ParseP2P2InitJson N:0x230da8` parses JSON and copies each nonempty decoded string with **`memcpy(destination, decoded_bytes, decoded_length)` without a destination-capacity check or a destination NUL write**. Clearing the temporary source string after copying is not destination termination. The later 63-byte `ConnectNatServer` copy is a different operation and cannot protect the earlier Init call.

All offsets below are **bytes from the `_tag_nat_client_cfg&` destination**, not ELF addresses. Primary references are the complete saved `native-followup-transport.txt:154–381` body. Adjacent write offsets establish separation between writes; they do not establish C array declarations, padding ownership, initialization or a field's accepted server length.

| Field | Directly observed write and primary line | Inferred separation / conditional service bound |
| --- | --- | --- |
| `natServerAddress` | Unchecked string copy at `+0x00`, line 217 | Next scalar begins at `+0x40`: 64 bytes before overlap. A candidate payload ceiling is 63 bytes **only with a proven remaining NUL byte**. |
| `natServerPort` | 16-bit store at `+0x40`, line 233 | Integer must remain within the validated port range before narrowing. |
| `clientToken` | Unchecked string copy at `+0x42`, line 250 | Next string begins at `+0x82`: 64-byte gap; conditional payload ceiling 63 bytes. This is Init evidence, independent of the later NAT-connect bound. |
| `ispCode` | Unchecked string copy at `+0x82`, line 275 | Next string at `+0xc2`: 64-byte gap; conditional payload ceiling 63 bytes. |
| `customerId` | Unchecked string copy at `+0xc2`, line 300 | Next string at `+0xe2`: 32-byte gap; conditional payload ceiling 31 bytes. |
| `svnCodeId` | Unchecked string copy at `+0xe2`, line 325 | Next scalar at `+0x104`: 34-byte gap. This may include alignment padding; do not infer a 34-byte array. A proposed conservative payload ceiling is 31 bytes, subject to confirming field storage/termination. |
| `cliType` | 32-bit store at `+0x104`, line 341 | Preserve the reviewed integer client-kind configuration. |
| `szClientVer` | Unchecked string copy at `+0x108`, line 364 | No next field/end-capacity is established in this parser. **No generic numeric maximum or terminator guarantee is proved.** |

The candidate ceilings above are conservative implementation proposals derived from observed gaps, **not verified native capacities/maxima or proof of memory safety**. Even a value exactly filling a gap can lack termination without crossing the next write. Native destination zero-initialization, declared member capacities and downstream reads must establish that the reserved terminator byte is valid; a length check alone cannot supply it. The trailing version storage and termination are explicitly unresolved. Reuse selected saved constructor/Init/consumer source to close this boundary before admitting arbitrary version/configuration inputs; no SDK or runtime experiment is required for that source work.

The next helper implementation must validate **each** bootstrap string before serialization and before native Init: reject embedded U+0000/decoded NUL, reject invalid/unpaired surrogates, and measure bytes of the decoded native representation, not Java `length()` or escaped JSON length. Escaping a NUL as `\u0000` does not make it acceptable. Non-ASCII byte expansion and JNI/JSON conversion must be accounted for; until that conversion is pinned, restrict the private configuration profile to approved ASCII values with explicit per-field byte limits. Do not truncate inputs or silently substitute an empty value. Null/empty optional fields need a separately validated policy; serialization of null does not prove native acceptance or reset semantics.

For `szClientVer` and any field whose capacity/termination remains unresolved, use only a finite, exact, source-reviewed private build/configuration value set while completing the storage trace; reject arbitrary runtime-supplied alternatives. A static-value allowlist cannot replace verified storage/termination bounds for dynamic credentials such as `clientToken`; keep those inputs unadmitted to Init until that boundary is established. Such a value allowlist is a conservative admission policy, not a claim that allocation or termination has been proved. Native startup stays unaccepted until those storage facts are resolved. Credential acquisition and gateway state/port development can proceed independently.

Implementation fixtures must cover every field independently: candidate ceiling minus one, ceiling and ceiling plus one; raw adjacent-write gaps (64 bytes for host/token/ISP, 32 for customer, and the ambiguous 32–34 build-code range); multibyte inputs with fewer Java characters but excess decoded bytes; embedded/escaped NUL at beginning/middle/end; paired/unpaired surrogates; and missing/null/empty values. An invalid config must record **zero native Init calls**. For version, test exact approved values and rejection of every unapproved mutation/long input without inventing a numeric native maximum. Add integer port/narrowing edges and immutable validated-config reuse checks. These host-side boundary fixtures are separate from the existing deviceID 32-byte/device-token 4095-byte/NAT-connect-token 63-byte fixtures and do not establish native acceptance.

No native/OEM constants, credentials or host defaults are supplied by this public document. The exact assignments are retained in private source snapshots; the worker configuration supplies approved values. There is no requirement to obtain a missing SDK/manual to implement this boundary.

`J:com/tvt/other/CustomPath.java:398–508` reads selected `AppInfomation` configuration, assigns `strNat2Address`/`protoSdkUrl`, has a regional NAT hostname composition branch, supports an application address override, and splits the resulting address/port into `BaseReqType`. XML parsing includes `nat2` and `nat2Port` (`CustomPath:225,298`). `BaseReqType.java:7–8` also contains startup fallbacks. Preserve the selected account region and configuration provenance; never substitute the HTTP host for NAT or bake the saved fallback into the service. A malformed split in the APK can yield an empty host; the gateway should reject it.

Login parsing `getTokenFromJson P:0x2d2cd0` extracts USER `data.token` separately from P2P `data.p2pId` with `data.tid` fallback; the accepted callback path applies separate `setProtoToken` and `setP2PToken` state. `LaunchApplication.ConnectNatServer:432–437` requires `isLogin`, reads `keychain_p2p_token` again and invokes `ConnectNatServer(String)Z`. This allows current P2P state to differ from initial config. USER token renewal notification `/user/token/renewal` explicitly disconnects NAT then reconnects (`LaunchApplication:412–418`); foreground also reconnects in its guarded branch (`:725–728`). DEVICE renewal does not substitute for these actions.

JNI `ConnectNatServer N:0x21dfb0` rejects an empty converted token, then calls `Net_Client_Protocal_ConnectNatServer N:0x220cb8` → manager `N:0x224310` → NAT manager `N:0x236908`. The latter copies at most 63 bytes into client-token storage and starts the NAT command manager. The boolean return is startup admission; `OnConnectNatServer(Z)V` and `OnDisConnectNatServer()V` are separate callbacks. The APK application's handlers at `LaunchApplication:469–474` are empty, so they establish neither retry policy nor a required successful-NAT-before-device ordering. Gateway states should distinguish initialization, NAT admission, NAT callback outcome, device allocation, device callback outcome and first usable media.

## Opaque directory SN to native device ID

The bound-device list path is exact:

```text
GetDeviceListBean.RecordsBean.sn
  -> ru0.java:2067–2069 -> DeviceItem.X0(sn) -> mDataId
  -> DeviceItem.t() -> m42.B
  -> m42:305 or 333 -> server.L1(..., B, ...)
  -> ku3.L1:5075–5085 -> f5
  -> qa(f5, ...) -> GetDeviceAccessToken.devId -> HTTP data.sn
  -> fa:2167 -> ConnectDevByToken(..., f5, observer)
```

`J:com/tvt/other/DeviceItem.java:433–435,773–775` and `defpackage/m42.java:839–898` complete the mapping. The same `sn` is also assigned to display/serial fields; there is **no decode, hash, decryption, snPlain substitution or channel-index substitution** in this selected bound-device route. Other manual/LAN/share constructor branches must be mapped independently; the alternate `m42` constructors can derive an ID via `l92.b`, which is not permission to transform directory SN.

Native wrapper `CNetComWrapper::ConnectByToken N:0x232088` copies the device-access token into a 4096-byte area with a 4095-byte copy limit and copies the device ID with a **32-byte** limit before `NAT_CLIENT_ConnectDev`. This is an observed implementation bound, not a server field maximum. Reject embedded NUL and oversized encoded credentials/IDs instead of silently truncating. In particular the existing helper's 4096-Java-character device-ID allowance is broader than this native copy. Keep opaque SN unchanged and require a proven supported encoded length; a longer selector needs explicit unsupported handling or further native-path evidence. ASCII IDs avoid JNI string-encoding ambiguity; non-ASCII acceptance remains unverified.

## Implement the next device/gateway slice

The current helper has exact JNI declarations/callbacks and a tested source lifecycle, but `NativeDriver`/`JniNativeDriver` only expose init, start, device connect, live open/close, disconnect, stop and quit. NAT connect/disconnect and DEVICE renewal declarations alone do not make them available through that controller. `DeviceCredential` currently accepts positive long expiry and broad string lengths; update its private contract using the arm64 bounds above. `RuntimeConfig` also needs the per-field pre-Init encoded-byte/NUL/termination boundary above; its generic 4096-character check permits writes across native bootstrap fields. These are concrete implementation gaps, not requests for another vendor SDK.

Implement three private ports in the existing composition:

| Port | Private input/output | Required state/bounds |
| --- | --- | --- |
| Device credential acquisition | Current USER session reference + authorized opaque SN → DEVICE credential reference, parsed expiry epoch seconds and acquisition generation | Account transport's host/TLS/response bounds; nonempty token, integer uint32 expiry, finite overall deadline; no raw token in DTO/log. |
| Native bootstrap/NAT | Eight-field config validated per encoded field before Init, with a source-reviewed profile for unresolved capacity/termination; current P2P reference; separate NAT connect/disconnect events | Reject config overflow/NUL before any Init call; same retained JNI instance/process lease; native startup result separate from callback; account/P2P rotation reconnects NAT under generation fencing. |
| Device connect/refresh | Credential reference, exact SN, timeout seconds; native renewal request and private refresh admission result | Same actor/device/session/connection generation; callback queue schedules worker activity off the JNI callback thread; one refresh in flight, total deadline, expiry fence and late-result rejection. |

Use an explicit `expiry_epoch_seconds` type beside a separate monotonic operation deadline and `connect_timeout_seconds`. Require configured skew/remaining-life policy before connect; do not rename expiry to TTL. Use byte bounds compatible with native copies and guard `timeout_seconds * 1000` against uint32 overflow. Make account-token invalidation stop dependent acquisition and P2P/device admission. Distinguish HTTP acquisition failure, native allocation failure, native device authorization failure, renewal admission, renewal usability and media timeout.

Positive connection/task handles establish allocation only. The app only registers positive connection handles (`NetClientProtocal:466–474`); its connection callback routes 200 to connected state/key acquisition, 202 to local failure -5 and other values to -1 (`ku3:7235–7263`). These local mappings are not a universal network error dictionary. `ProcConnect N:0x2264b4` still performs NAT2 token/key and N9000 account authorization before successful connection reporting. Task creation then needs callback data and successful bounded frame parsing/decoding; none of those outcomes follows from NAT startup or token acquisition. Keep the existing close tasks → disconnect → Stop → Quit lifecycle and generation fencing.

Meaningful local verification for the implementation is now possible: response success/missing/invalid-expiry and session failure fixtures; unchanged SN mapping; 32/4095/63-byte boundaries and NUL rejection; uint32 expiry edge cases; expiry-window edges at 300,299,1,0 seconds; distinct epoch/monotonic clocks; duplicate/late renewal callbacks; admission versus completion; grant loss and teardown during refresh; native callback allocation before first data. Synthetic fixtures verify adapter policy only. Do not count them as device parity.

## Remaining runtime and source boundaries

| Unresolved fact | Exact next evidence needed |
| --- | --- |
| Actual access-token response types, lifetime and authorization errors | Redacted status/type/length/timestamp metadata for one allowed success, denial and expired USER session; retain secrets only in private storage. |
| End-to-end renewal completion, failed query cleanup and token revocation | Trace `OnRenewDaToken` → account fetch → native query/admission → continued authorized device use, plus failed query/expiry/teardown. The decoded node protocol virtual method and full query-failure cleanup remain source work. |
| Scheduler cadence and clock behavior | Observe scan/callback timing and clock skew in an isolated Android helper; the source establishes threshold arithmetic, not a callback SLA. |
| Bootstrap field storage, startup acceptance and P2P rotation | First trace native destination initialization, field capacities and termination, especially `szClientVer` at `+0x108`; the parser proves unchecked offsets only. Then observe exact selected region/config provenance, Init/Start/NAT callbacks and USER-renewal NAT reconnect. Null/empty acceptance and reconnect order under concurrency remain unexecuted. |
| Non-ASCII/long opaque SN and arm32 equivalence | Inspect the selected ABI/string conversion and device identity behavior; do not infer from the broad Java string limit or arm64 alone. |
| Native authorization and first usable media | Allowed device connection callback, N9000/key lifecycle, first bounded callback/frame, offline/timeout and teardown. Full LAN/P2P/relay wire protocol remains outside this handoff. |

These remaining facts limit runtime acceptance. They do not block source implementation of credential acquisition, explicit bootstrap, callback-driven refresh and scoped gateway state handling. No public report value contains a credential, serial, encryption key or private native constant.
