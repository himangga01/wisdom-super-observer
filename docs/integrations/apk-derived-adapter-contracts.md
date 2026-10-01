# APK-derived account and Android adapter contracts

Analysis date: 2026-10-02 (Asia/Seoul). Development authority: the user confirmed that no separate vendor SDK/API documentation exists and directed implementation from the analyzed SuperLive Plus APK. This document consolidates the accepted static account and native follow-ups into a sanitized engineering handoff. `SOURCE_DERIVED` describes evidence in prose, not a new machine-readable status. No account/device/network/Android execution or browser media acceptance occurred in those analyses; current G-P1 remote families remain BLOCKED and MATCHED remains 0.

The [implementation plan](../superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md), [bridge decision](tvt-bridge-decision.md) and [runtime contract](tvt-runtime-contracts.md) distinguish development from captured-runtime acceptance. The [2026-09-27 feasibility audit](apk-audit/11-protocol-feasibility.md) retains its historical findings with a dated correction. Missing remote fields are targeted APK decode work, never guessed constants. Vendor acquisition and runtime capture are not prerequisites for developing the decoded boundaries here.

## Source identities and address notation

| Artifact | Version/ABI | SHA-256 |
| --- | --- | --- |
| `com.tvt.superliveplus` base APK, 170,064,551 bytes | 1.18.1, version code 20267 | `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281` |
| `libProtoSDK.so`, 6,446,688 bytes | arm64-v8a | `b7731270d75573668cbb38a08b611a8ae2460e586181f475c4c4d7eb7cdf735b` |
| `libProtoSDK.so`, 4,784,388 bytes | armeabi-v7a | `716d8377f9293dfcdab81476a8b56e6eb756a75c2e5f13100805a972fe3739c4` |
| `libNetClientProtocal.so` | arm64-v8a | `c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717` |
| `libNetClientProtocal.so` | armeabi-v7a | `17d44c46654752f761d8117989c0101c7662fc494a8900ca2b307de1b234f23f` |

The accepted account report is 22,575 bytes, SHA-256 `02fd975ac432ab53eaea7e6737b5b94c2e2876d2187bfcc3f184779137fef724`; the native report is 30,118 bytes, SHA-256 `1849e96f480bd2e769f04f0d94c3ffb743d26b76a68af85a2a248ed1aef54f66`. These are source-report custody identities, not runtime fixture digests. Their substantive contracts are reproduced below; private reports and raw Ghidra listings are not needed to understand this document.

`J:path:line` means a Java path in the APK's JADX source tree. `N:address` means an arm64 Ghidra entry in `libProtoSDK.so` with image base `0x100000`; subtract that base for ELF `st_value`. `B:offset` means a raw file offset in that library. `E64`/`E32` below are ABI-specific ELF dynamic-symbol `st_value` addresses for `libNetClientProtocal.so`, not file offsets. ARM32 Thumb values may have their low bit set. Only selected arm64 bodies were decompiled; no arm32 body equivalence is claimed. [The native inventory](apk-audit/08-native-abi-jni.md) records binary/export identities.

## Account HTTP route C

Java `/sdk/*` names dispatch in process; native `/user/*` paths are distinct HTTP paths. `UserProtoAPI::userLogin N:0x329fd4` builds `/user/login B:0x5170b1` and queues it via `ProtoSdkManager::addHttpTask N:0x2d6804`. Normal `HttpsRequestTask::httpsTransTask N:0x2c85ec` uses the `libcurlTool` vtable slot `+0x50`, `JsonRawDataPosts N:0x2d5ec8`: POST JSON with the explicit header `Content-Type:application/json;charset=UTF-8`. This function sets no custom User-Agent; libcurl-generated headers are not fully enumerated. The service should retain normal TLS verification; the APK's disabled peer-verification setting is not a requirement to copy.

| Operation | Native path and entry | Decoded boundary / remaining work |
| --- | --- | --- |
| Image challenge | `/user/img-code/get`, `N:0x326248`, `B:0x518ae7` | Conditional `data.customerAppId`; `getIdCodeFromJson N:0x2d2440` reads `idCode`. Image payload/encoding and callback trace remain unfinished. |
| Image check | `/user/img-code/check`, `N:0x326754`, `B:0x516ea0` | `idCode`, `imgCode`, optional customer app ID. An empty Java standalone request does not establish the visible app's working check route. |
| Dynamic code | `/user/sms-code/get` or `/user/sms-code/no-token/get`, `N:0x3252d4` | Business types 1–5 use the first path; 11–16 use the second. Do not expose other values merely because a native default branch exists. Strings `loginName`, `lang`; numbers `loginType`, `businessType`; conditional image/customer strings. |
| Existence | `/user/info/phone/is-exist` or `/user/info/email/is-exist`, `N:0x326f50` | `mobile` or `email` plus optional customer app ID; exact `isExist` response nesting remains unfinished. |
| Login | `/user/login`, `N:0x329fd4` | Exact fields and proofs below. |
| Profile | `/user/info/get`, `N:0x3301dc`; `/user/info/update`, `N:0x33039c` | Get uses generic basic-only request. Update includes `nickName`, `name`, `address`, `type`; response model fields are not proof every response contains them. |
| Renewal | `/user/token/renewal`, `N:0x2cbbb8` | POST JSON, basic version `1.1` and current token; no fabricated empty `data`. Renewal trigger/expiry timing remains unfinished. |
| Logout | `/user/logout`, `N:0x32d6a8` → `setLoginStatus(false) N:0x2d9fd8` | Generic basic-only request; local Java token clearing does not prove server revocation or failure policy. |
| Register/recover | `/user/register N:0x327868`; `/user/info/password/reset N:0x32e530`; `/user/info/password/reset/request N:0x32f940` | JNI argument-to-field/encryption mapping remains targeted decode work; do not borrow login proof rules. |

`/user/info/login-type/list` and `/user/third-login` also exist as path constants, but full serializers are unfinished. Each completed branch remains runtime unverified until captured success/error/timeout and scoped readback evidence meets the existing runtime contract.

### Login serializer and credential proofs

`J:com/tvt/protocol_sdk/request/UserLoginRequest.java:11-67` passes `loginMode, account, password, imageCode, uuid, terminalId, doubleCheckCode, language, appVersion, country` to `J:com/tvt/protocol_sdk/TVTOpenSDK.java:686,3296-3302`. Native field names differ:

| JSON member | Type | Source / presence |
| --- | --- | --- |
| `basic.ver` | string | `1.1` for login |
| `basic.id` | string | Decimal task ID |
| `basic.time` | number | Unix seconds from `time(NULL)` |
| `basic.nonce` | number | Nine-digit generated decimal text converted to integer; leading zero is lost |
| `data.type` | number | Java `loginMode` |
| `data.userName`, `data.password`, `data.lang`, `data.uuid`, `data.appVersion`, `data.country` | strings | Account, password proof, language, UUID proof, app version, country; inserted even for empty inputs |
| `data.idCode`, `data.imgCode` | strings | Both only when input `imageCode` is nonempty; `idCode` comes from native verify state |
| `data.customerAppId`, `data.customerMark`, `data.terminalId`, `data.doubleCheckCode` | strings | Each only when its corresponding configuration/input is nonempty |

For password and UUID independently, native login computes lowercase hexadecimal:

```text
MD5_value = lowercaseHex(MD5(UTF8(value)))
proof = lowercaseHex(SHA512(UTF8(decimalNonce + "#" + decimalUnixTime
                               + "#" + account + "#" + MD5_value)))
```

`value` is separately the raw password or Java UUID input. Final `data.uuid` contains its proof rather than the raw UUID. Evidence: `userLogin N:0x329fd4`, nonce helper `N:0x34802c`, `MD5Tool::Md5EncodeToStr N:0x316fc0`, `Sha512EncodeToStr N:0x317114`, `%02x B:0x518dda`, JSON-key initialization `_INIT_8 N:0x292368`. JSON construction order is observed; a server requirement for member order is not established. The accepted report includes locally computed ASCII/UTF-8 vectors from invented inputs; they prove the decoded formula locally, not APK execution or server acceptance. Raw passwords, proofs and tokens stay out of logs, DTOs, browser storage and fixtures.

Login does not create `basic.sign`. `createPostJson N:0x2cc3f0` copies a nonempty preexisting sign but does not derive one; omit it for core login unless a separately decoded caller supplies it. Generic sign provenance remains unfinished for other operations. `createBasicInfoJson N:0x2d057c` uses default string version `1.0`, string decimal task ID, optional nonempty token, numeric time/nonce; profile get/logout use this basic-only builder. Renewal requests explicit version `1.1`. Operation JSON is appended only when nonempty, so basic-only requests need no invented empty `data` object. Task allocator and server tolerance for ID choices remain unverified.

### Host, response and session boundaries

Java defaults to `https://m.svcld.com` (`J:com/tvt/protocol_sdk/BaseReqType.java:4-13`); regional configuration builds `https://app-api20.<regional-domain>` (`J:com/tvt/other/CustomPath.java:398-508`) and passes the selected host into native startup (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:2481-2499`). Keep region/session host resolution configurable.

`parseReDirectUrl N:0x2ca898` reads `data.chain`, `data.domain`, `data.dcIp` fallback `data.ip`, numeric `data.dcPort` fallback `data.port`, and `data.httpPrefix`; a nonempty domain/IP builds `<httpPrefix><domain-or-IP>[:port]/mobile_v1.0`. The service binds allowed schemes/hosts to configured regions rather than trusting an arbitrary response destination. `chain` meaning and complete redirect retry/failure policy remain undecoded. A configured URL-replacement branch uses GET, multipart uses a separate POST slot; neither overrides normal account POST JSON.

Response parsing separates HTTP status, `basic.msgcode` and Java callback error. `getMsgCode N:0x2cffd0` reads the numeric message code; native transport branches on 200 and 404/DC, and one failure synthesizes `basic.msgcode=900004` with null data. These branches do not define all server error meanings. `getTokenFromJson N:0x2d2cd0` requires nonempty `data.token` for native login state and extracts separate P2P `data.p2pId`, fallback `data.tid`. Account, P2P and device-access tokens remain distinct vault references/session fields; no token values appear here. Renewal scheduling, device-token acquisition/expiry and revocation require their own decode/acceptance.

## Managed Android device/media route B

Use the chosen packaged `libNetClientProtocal.so` on Android with the exact binary class `com.tvt.network.NetClientProtocal`. The 48 conventional JNI exports and app call sites establish this helper boundary. The separate `NatTraveral` socket surface does not replace it. Five zero-return TVTOpenSDK NAT exports and 31 signatures without conventional exports are not an executable transport; no reviewed `JNI_OnLoad` registration makes them one.

`J:com/tvt/network/NetClientProtocal.java:19,27-54,82-99,115-171,312-314,378-404,434-474` establishes the wrapper. `J:com/tvt/launch/LaunchApplication.java:432-465,580-602` calls GlobalInit then Start. GlobalInit serializes with Gson `serializeNulls()` through `J:defpackage/ye1.java:7-25`, then invokes `Init(json)`. Config keys are exactly `cliType`, `clientToken`, `customerId`, `ispCode`, `natServerAddress`, `natServerPort`, `svnCodeId`, `szClientVer`; runtime tokens/hosts/device IDs are injected, never constants. `ConnectNatServer` is a separate login-dependent action.

| Instance native method descriptor | E64 | E32 |
| --- | --- | --- |
| `Init(Ljava/lang/String;)Z` | `0x11dc14` | `0xcf471` |
| `Start()Z` / `Stop()V` / `Quit()V` | `0x11e09c` / `0x11e0b4` / `0x11e02c` | `0xcf739` / `0xcf743` / `0xcf6e9` |
| `ConnectDevByToken(Ljava/lang/String;JILjava/lang/String;)I` | `0x11e0b8` | `0xcf749` |
| `RequestLiveStreamTask(IIIIJ)I` / `JniCloseLiveStream(I)Z` | `0x11e22c` / `0x11e254` | `0xcf811` / `0xcf841` |
| `RequestPlaybackStream(IIIJIIJ)I` / `JniClosePlayback(I)Z` | `0x11e8f8` / `0x11e648` | `0xcfc6d` / `0xcfab9` |
| `RequestLiveTalkBack(IIIIJ)I` / `SendLiveTalkBackData(II[BILjava/lang/String;)Z` / `JniCloseLiveTalkBack(I)Z` | `0x11e4c8` / `0x11e50c` / `0x11e4f0` | `0xcf9cd` / `0xcfa09` / `0xcf9fd` |

Also retain exact `ConnectNatServer(Ljava/lang/String;)Z`, `Disconnect(I)V`, `SendPlaybackIndex(II)Z` declarations. The original DEX descriptors were instruction-level checked in the accepted native follow-up; only arm64 bodies were decompiled.

Native Init retains a global reference to the supplied instance; callbacks resolve methods on that live object's actual class, not a speculative wrapper. Provide `OnNetClientConnect(III[BI)V`, `OnNetClientDisconnect(I)V`, `OnNetClientTaskData(I[BIJ)V`, `OnNetClientTaskErr(IIJ)V`, `OnSwitchConnect(II)V`, `OnRenewDaToken(I)V`, `OnConnectNatServer(Z)V`, `OnDisConnectNatServer()V`, `OnRecvNatServerTransData([BI)V`, `OnNetClientNotifyData(I[BI)V`, `OnNetClientSubscribeData(IIII[BI)V`, and static `LogPrintCallback(Ljava/lang/String;)V`. Preserve declarations even when the first slice only forwards connection/task events.

`ConnectDevByToken` delegates through E64 `0x120d5c`, connection manager `0x1196d0/0x12452c`, node `0x12632c`, `Net_Comm_ConnectByToken 0x10e3e0`, wrapper `0x132088`, then `NAT_CLIENT_ConnectDev`. Java registers only positive connection handles (`J:defpackage/ku3.java:2154-2169`). `ProcConnect 0x1264b4` obtains an encryption key/NAT2 token and performs N9000 account authorization; exact handshake/key lifetime remains opaque. Live/playback task managers `0x1213f0/0x1215f0` resolve the connection and invoke node virtual methods; Talk send `0x122eb4` resolves a live task back to its connection. Task IDs alone do not prove stream success.

Observer init `0x11fa28` retains the JVM/instance; task callback `0x1200e0` attaches native threads as needed, copies bytes to Java `byte[]`, calls `(I[BIJ)V`, releases local references and detaches. Callback bytes are post-native processing, not proven socket packets. Keep callbacks keyed by session generation/connection/task; reject late delivery across teardown. Load once per chosen ABI, retain the same instance through Quit, check Init/Start/connect results, close live/playback/Talk tasks, disconnect, Stop then Quit, and clear maps. Quit releases the global reference. APK observer auto-destroy decompilation must not substitute for explicit helper lifecycle.

Both binaries list Android system dependencies `liblog`, `libm`, `libdl`, `libc`. This does not rule out later dynamic loads or API assumptions. A minimal mirror avoids dragging in obfuscated Java dependencies while retaining exact declarations/callback/config semantics. Actual Android load/classloader/API/dependency/concurrency, headless hosting/restart/update/capacity and binary-use terms remain acceptance gates. Network-bearing Init/Start/connect runtime acceptance uses its scoped authorization. Never load these JNI libraries on Linux or treat generic RTSP as an equivalent device adapter.

## Bounded post-native 44/24-byte parser

Offsets below are bytes relative to one callback envelope, not ELF/file/socket offsets. Instruction-level DEX checks resolved JADX read ambiguity. `J:defpackage/ep3.java:20-91`, `y41.java:11-64`, `lk2.java:17-43`, `u41.java:15-51`, `z41.java:8-52`, `x41.java:10-68` and `ku3.java:2176-2595` establish field order and app usage.

| 44-byte envelope | Offset | Field / interpretation |
| --- | --- | --- |
| Magic | 0–3 | u32 LE; app writer emits `SHFL`, reader does not validate it. Bounded format accepts `SHFL`; other magic is unsupported opaque input. No live callback has confirmed this magic. |
| Version/flags | 4–5 | Raw u16 LE; meaning opaque |
| Kind/key marker | 6, 7 | Raw u8; app uses marker 1 as one keyframe indication |
| GUID | 8–23 | Original 16 bytes; do not reformat identity |
| Body length | 24–27 | Signed i32 LE; must be nonnegative and bounded |
| Envelope time | 28–35 | Raw 64-bit FILETIME-style LE |
| Frame index / other value | 36–39 / 40–43 | Signed i32 LE; other value remains opaque |

| 24-byte inner frame, begins at envelope byte 44 | Relative offset | Field |
| --- | --- | --- |
| Frame type / extension length / IP frame type / reserved | 0 / 1 / 2 / 3 | Java signed bytes for first three; preserve raw values. Extension 128–255 becomes negative and is unsupported; IP type can be `-128`. |
| Payload length | 4–7 | Signed i32 LE, nonnegative and bounded |
| Device / ECM timestamps | 8–15 / 16–23 | Raw FILETIME-style ticks |

Keep raw ticks and separately derive Unix microseconds at millisecond resolution using `((ticks // 10000) - 11644473600000) * 1000` within validated range. Clock origin/range still needs a real frame. The frame writer emits one-byte fields `a,b,d,c`, whereas the reader reads `a,b,c,d`; no symmetric encoder is implied.

Extension starts at callback byte 68; payload at `68 + extension_length`:

| Extension | Relative offsets | Boundary |
| --- | --- | --- |
| Video base | 0/1 raw u8; 2–3 u16 LE; 4–7 fourcc u32 LE; 8–9 width i16 LE; 10–11 height i16 LE | 12-byte base; positive bounded dimensions. Known `H264`, `H265`, `HEVC` are candidates; unknown fourcc is unsupported instead of copying the app's every-other-value H.265 assumption. |
| Video encrypted fields | 12–15 unsigned CRC32 LE; 16 encryption flag; optional 17–43 opaque tail | Reject length 13–16; length ≥17 contains fields. Preserve partial reserved tails pending fixtures; 44-byte form has the full 27-byte tail. |
| Audio base | 0/1 raw u8; 2–3 codec i16 LE; 4–5 and 6–7 opaque i16 LE; 8–11 rate i32 LE | Both 12 and 44-byte forms exist in the app writer; preserve optional tail. App uses rate for codecs 9/10; do not assign universal meaning to other fields. |

Require at least 68 bytes and a configured maximum callback size; `body_length >= 24`, `44 + body_length <= callback_length`, signed `0 <= extension_length <= 127`, nonnegative payload length and checked `24 + extension_length + payload_length <= body_length`. Check every slice. Video extensions 1–11 and 13–16 reject; extension zero means unknown codec/dimensions; audio needs at least its 12-byte base when present. Return consumed length, payload, original GUID, raw unknown fields/timestamps, codec markers and parsed metadata. Preserve remaining body bytes as opaque extra records; the app aligns video payload to four bytes, which does not define all extra record formats.

The original Java prefix-read pattern really exists in bytecode and advances within the same array; later short reads are unchecked. Use explicit checked slices rather than reproduce it. For encryption flag 1, `J:defpackage/ku3.java:3673-3705` decrypts the first 128 payload bytes through `OpensslSDK.AESDecryptECBWithoutMD5`, checks the returned length is 128, then validates CRC32 over the decryptor's actual returned bytes. The app can continue with the encrypted prefix after failure; the service must mark it encrypted/undecoded and withhold it from plaintext decode. Short payloads or unsupported flags reject. A later helper may use the packaged crypto method with a session-local key and return only status/plaintext after success; no key crosses the public boundary.

These fields permit a bounded parser with synthetic complete/truncated/overflow inputs now. They do not establish Annex B/AVCC, audio packaging, browser codec support, task continuity or raw device wire framing. Talk's 640-byte input chunk branches and selected encoder output/pacing remain targeted bytecode/runtime work; playback seek/index/error and close require actual comparison.

## Foundation composition and remaining work

Implement account HTTP and Android helper ports separately, with scoped fake-worker/parser development before real acceptance. Public API uses the common nested `{error:{code,message,details?},request_id}` envelope. W02/T04 must add protected delegated capability checks at issue, redeem and use with the real actor, current membership/grant/store/share/channel/action and connection version; preserve legacy OWNER handling without OWNER or NULL-channel domain bypass. Worker handle redemption commits before bounded callback execution.

Use fixed `TVT_ACCOUNT_OPERATION`/TENANT, `TVT_DEVICE_OPERATION`/STORE and `TYCO_OPERATION`/TENANT kinds with checked domain enqueue/read/cancel/claim/step/use, retaining all legacy kinds. Actor-key uniqueness and server-derived cross-actor business holds are separate. Once dispatch is possible, timeout/revoke/cancel/new keys retain durable UNKNOWN_OUTCOME until fenced definitive readback resolves it. Provenance establishes integrity only; positive TVT bytes and trusted EVIDENCE/media/cloud ingress need reviewed admission through all existing AssetStore metadata/ticket/redeem/read/worker routes, with no OWNER fallback or second store.

Targeted decode work remains: unfinished register/recovery/provider and generic-sign callers, image payload/error mappings/renewal/DC branches; NAT_CLIENT/N9000 challenge/key/transport internals and node virtual control/task frames; unknown parser flags/extra records, real codec packaging/encryption, Talk output/pacing. Complete source decoding before implementing an undefined field. W01 then records actual scoped success/denial/offline/timeout/readback and runtime lifecycle evidence in the unchanged handoff schema.

Independent W02 contracts/adapter development proceeds while T05A full14 runs. Foundation/security/runtime/storage and production enablement gates remain required. Source/decompiler errors, incomplete call graphs and absent actual runtime observations limit every conclusion here; no implementation completion, G-P1 PASS, captured-runtime promotion or parity acceptance is claimed by this document.
