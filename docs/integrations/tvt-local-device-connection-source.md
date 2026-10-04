# TVT local serial and QR credential connection source

Analysis date: **2026-10-03, Asia/Seoul**. Root-supplied repository baseline: `756946ca73cff31d7ebb23141873088b470a96b4` (not reverified with Git). Approved SuperLive Plus 1.18.1 APK: 170,064,551 bytes, SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. **Static handoff only; MATCHED=0; release_ready=false.** No actual QR, serial, password, account, phone, network, database or native SDK execution was used.

## Resolved decision

The APK supports a local serial plus **device username/password** path without first obtaining a TVT USER token or `/device/access-token/get` result. Implement a separate `NatTraveral` transport and device protocol adapter. The existing `NetClientProtocal.ConnectDevByToken` helper cannot accept these inputs: a scanned serial is not a `datoken`, and a missing QR password is not evidence that an empty password succeeds.

The relevant original saved classes are `com/tvt/user/view/activity/QrcodeActivity`, `com/tvt/devicemanager/a` (LoginLayout), `com/tvt/dev_share/AddDeviceActivity`, and `defpackage/m42`. The requested name `AddDevQRScanActivity` does **not** occur in this extraction or manifest; it must not be cited as an inspected class. `SN_USER` is the task's QR classification, not a literal APK enum found here. The source below covers `<SN>`/`<sn>` plus `<user>` QR input and manual serial input.

`J:` paths below are relative to the original `jadx-full/sources/`. `N:` addresses are arm64 **libNatTraveral.so Ghidra addresses**, image base `0x100000`; subtract that base to compare ELF symbol values. Complete targeted native bodies and the original DEX instruction inventory are frozen in the W04 local QR evidence packet. The separate **Fix1** packet adds exact X7 code-item bytes and complete operands/control-flow metadata; it preserves the original packet unchanged. Existing source packets remain references, not fresh runtime evidence.

## QR and local device construction

| Boundary | Exact source and behavior |
| --- | --- |
| Local scan callback | `J:com/tvt/user/view/activity/QrcodeActivity.java:1122–1128,1247–1284`: the non-account-user branch calls `k2`, emitting callback type 7. Account-user scan routes differ. `com/tvt/devicemanager/a.java:2431–2444` maps type 7 to `O1`. |
| Extract serial/user | `a.java:2077–2174`: `O1` reads `<SN>…</SN>`, falls back to lowercase `<sn>`, reads `<user>`, and uses the app's default username only when that field is empty. It sets the password field to `""`. Optional `<ip>/<port>/<en>/<time>/<info>` belong to separate address/sharing branches. It does not derive a password from SN/user. |
| Serial normalization | `GlobalUnit.java:1713–1714` recognizes alphanumeric strings of length 1–128. UI submit paths uppercase recognized serials (`a.java:1740–1746,1750–1798,2340–2348`); the direct login branch separately rejects serial length above 30. These UI rules and native capacities are different constraints. Apply a deliberate input policy, record normalization, and never uppercase a username/password. |
| Device fields | `a.java:2222–2235` assigns `DeviceItem.k2(address)`, `m2(username)`, `i2(password)`, `F1(l92.a(password))`; `DeviceItem.java:393–395,609–611,777–779,846–848` expose the MD5 text, raw password and username. `a.java:2241–2252` sends the same values to `M1` for connection. |
| Password representation | `l92.java:10–30` returns **uppercase hex MD5** of nonempty input using Java default charset; null/empty input returns `""`, not MD5(empty). `a.L1:1756,1797` preserves password field text; other form-submit paths trim it. Choose the intended entry contract explicitly; do not apply blanket trimming. |
| Shared-device add | `AddDeviceActivity.java:89–125` can `continueAdd` while `isLogin` is false; its `addDevice` maps `AD/PT/DN/UN/PW`, treats `ETY != 0` as already supplied MD5 material, otherwise computes `l92.a(PW)`, and creates `m42`. This branch is corroborating evidence of local operation; it is not the parser for a bare SN/user QR. |
| Connection fields | `m42.java:839–898`: `f=DeviceItem.v0()` address, `g=x0()` username, `h=t0()` raw password, `x=U()` MD5 text, `n=e0()` server type. The alternate constructor's `B=l92.b(f)` is a local record identifier; the NAT call still receives `f`. |

`m42.d:270–335` selects account classes only for server types 11–14. Type 11 is `ew3`, 12/13 `iu3`, and 14 `ku3` (`:342–351`). Those use `L1`, account access tokens and `NetClientProtocal` (`ku3:2167,5075`; `ew3:3491,5269`; `iu3:1115,1878`). For other types, an address without `.` or `:` goes to **`m42.k`**. The IP/domain path uses a separate HTTP/type discovery and socket route; this handoff does not invent an IP/RTSP address from a serial.

## Exact native transport port

Preserve the package/class name `com.tvt.network.NatTraveral` and its Java declarations (`J:com/tvt/network/NatTraveral.java`). Its library is **`libNatTraveral.so`**, not `libProtoSDK.so` and not `libNetClientProtocal.so`. The latter remains the separate account-token implementation.

```text
one retained NatTraveral instance: load library -> InitGlobal()
Initialize() -> long echoHandle (nonzero allocation only)
register connection callback for echoHandle
GetVersionType(echoHandle, serial,
    nat1Host, nat1Port, nat2Host, nat2Port, new byte[66],
    networkFlag, traversalMode, disableUPnP,
    privateFilesPath, platform, appVersion, appName, runtimeSingleId)
    -> device type; GetErrorCode(echoHandle) separately
choose protocol: 3 -> hu3, 10001 -> nu3, 20001 -> cw3
SetConnectTraversalMode(echoHandle, mode)
SetValue(echoHandle, serial, nat1Host, nat1Port, mode) -> 0 for open transport
GetConnectType: 3 -> callback receive; other selected types -> RecvData loop
device greeting -> device credential handshake -> authorized channel records
framed live request -> response/data parsing -> bounded compressed media
close live protocol task -> Interrupt/DestroyEchoClient -> discard generation
```

Java provenance is `m42.java:392–539`, inherited `fu3.K1:764–788`, and `com/tvt/network/a.java:210–260`. `m42.k` passes platform `"AND"`, `GlobalUnit.t0 + "." + GlobalUnit.s0`, app-name transformation `GlobalUnit.d`, and private app instance identity `GlobalUnit.O(context)`, backed by `SINGLE_ID` or UUID text with hyphens removed (`GlobalUnit.java:603–775`, `m42.java:441`). This Fix2 provenance follows the accepted [bootstrap profile](tvt-local-bootstrap-profile.md#exact-build-and-runtime-identity); the helper field label `model` is positional schema terminology. Use the reviewed build profile and trusted runtime identity. Existing handles are interrupted and the app sleeps 20 ms before replacement. Invalid/unsupported type outcomes destroy the echo client; device types 9/10 take a special app failure path. Preserve returned type/error privately rather than relabeling every failure as a password error.

Native `InitGlobal N:0x22777c` retains the Java callback instance, initializes the NAT subsystem and registers callbacks; its return zero is not a connected state. `Initialize N:0x225b28` allocates the echo object; constructor `N:0x224a30` initializes a connection manager with a nominal 30-second setting. `GetVersionType N:0x2263e8/0x2250ec` configures and starts that manager. `DevConnManager::GetDeviceType N:0x223e80` races NAT1/NAT2 type discovery and checks `time()` elapsed **greater than** that setting; NAT2 receives setting minus two (`N:0x223cb8`, nominal 28). These are wall-clock source limits, not a reliable end-to-end or first-frame deadline. Add a monotonic service deadline and cancellation fencing.

### Bootstrap and identity are concrete

`GlobalUnit.V0/Z0` hold NAT1/NAT2 address profiles. `CustomPath.java:173–300,397–478` selects the current package's `R.xml.custom` fields, chooses a region from `AreasDomain.json` and saved RootDomain, and constructs NAT2 from the selected region/port; `supportOnlyNat` and debug/saved configuration can override it. `GlobalUnitItem.java:1175–1228` loads saved address overrides. `m42.k:400–442` splits the selected host/port with fallback literals 80 and 9998. Those are code fallbacks, not evidence for a device's service port. Supply the explicit reviewed regional profile to the helper; do not assume static `GlobalUnit` initializers describe the running profile.

The local NAT2 startup does **not** read the account P2P credential: `DevConnManager::Start N:0x2239cc` calls `NatClientTool::ConnectNatSever N:0x25b158` with host, port and client version. The latter zero-initializes the native config, copies host/version, writes port and client type 4, and calls `NAT_CLIENT_Start`. Thus client-token fields remain zero in this selected path. `startNatTransServer N:0x25b000` calls `NAT_CLIENT_Init` and installs notifiers. Its process-global started flag means different profiles cannot be casually interleaved within one native singleton.

`NatClientTool::ConnectDeviceBySN N:0x25b450` hashes the supplied SN internally before `NAT_CLIENT_ConnectDev`; `CHashOpenSSL::Encrypt N:0x28a0e8` selects MD5, and `CoverOutput N:0x28a72c` mode 1 emits uppercase hexadecimal (32 bytes). This internal NAT identity is not a device-access token or password proof. Pass the normalized serial to `GetVersionType`; **do not prehash it**. No `/device/access-token/get`, USER token, credential expiry or DEVICE-token renewal is established in this local path. It still depends on vendor traversal infrastructure for remote serial discovery; standalone credentials do not mean offline connection.

### JNI bounds and callbacks

`jstringTostring N:0x225808` calls `String.getBytes("utf-8")`, allocates length+1 and NUL-terminates. Reject embedded NUL and malformed Unicode before JNI; check UTF-8 bytes, not Java character count. `GetVersionType N:0x2250ec` zeroes its 0x324-byte config before bounded copies:

| Input | Native copy / admission bound |
| --- | --- |
| Serial | 64-byte field, copy at most 63; reject longer rather than allow silent truncation. The particular UI branch's 30-character rule is narrower. |
| NAT1 host | 128-byte field, copy 127; subsequent selected NAT1 config also copies 127. |
| NAT2 host | Initial 128-byte field/copy 127, but `ConnectNatSever` later copies **63** into zeroed 64-byte storage. Effective bound 63. |
| Platform | 32-byte field/copy 31; NAT1 manager uses its own fixed Android platform literal. |
| Version, app name, native model / runtime SINGLE_ID | Each 64-byte field/copy 63. NAT2 version copy is also 63 into zeroed 64 bytes. |
| Private path | 256-byte field/copy 255. Check composed cache path separately: NAT1 `GetDeviceType N:0x229d94` constructs a 256-byte path with checked concatenation including SN. |
| Ports | Narrowed to 16 bits; helper should require 1–65535 before narrowing. |
| Version result buffer | JNI allocates and copies **66 bytes** unconditionally. Supply exactly byte[66]. The inspected inner function does not populate its output pointer; regard contents as untrusted/uninitialized opaque bytes, never a returned credential or public diagnostic. |

These are local-library bounds; the account helper's 32-byte device ID and eight-field JSON Init constraints do not apply here. The decompiler misinfers the native `StartConnect` prototype (`N:0x225064`) and omits unused arguments; implement the **Java JNI signature** `SetValue(long,String,String,int,int)` rather than reproducing decompiler pointer casts.

`Nat2ConnStatusCallback` is `(JZILjava/lang/String;)V` (`N:0x227150`), and `Nat2RecvDataCallback` is `(J[B)I` (`N:0x226eac`). Native receive allocates the Java array from the native length with no selected upper bound; a Java queue bound protects downstream processing, not that initial allocation. Keep the native process isolated and apply connection/queue/memory limits. These callbacks deliver raw transport data, not `NetClientProtocal.OnNetClientTaskData` frames. Callback type 3 is the selected NAT2 callback transport; enum constants in `NatTraveral` have different labels, so retain observed numeric meaning from `network/a.k`.

For polling, `network/a.r:303–381` uses a **10,240-byte** scratch array, caps receive length by the remaining protocol buffer, handles positive bytes, zero/no data and negative failures, and has selected five-second no-first-data/stall branches. JNI `RecvData N:0x225df0` allocates from the passed length and writes the returned count into the caller array; `SendData N:0x225ca0` forwards the passed length without a Java-array-length check. Require `0 < length <= array.length <= configured cap`, validate returns, handle partial sends, and disallow negative allocation sizes. `SetValue==0`, a connection callback, or 64 greeting bytes each precede successful device authentication.

## Device protocol authentication and live handoff

For `20001`, `cw3` is the manual NVMS/N9000 implementation. Its constructor (`:397–412`) receives username, password and the distinct uppercase-MD5 text. `h4:6358–6434` waits for a 64-byte device greeting, calls `c8:2018–2045`, consumes it and calls `P3:4238–4248` → `X9`. `ok2.java:25–67` reads greeting version/security/challenge fields; validate the full greeting before reading any field. `qa:3025` means `I4 >= 1`; `ra:7470` means `I4 >= 2`.

| Negotiated branch | Exact source contract |
| --- | --- |
| Protocol version below 11 | `cw3.X9:4997–5053`, `lz0.java`: command 257 with 236-byte login struct; username/password areas are 64 bytes each. Security disabled copies password bytes. Security enabled sends raw SHA-1 bytes of `uppercaseMD5(password) + eight-digit zero-padded decimal device challenge`; a random eight-digit nonzero-digit client nonce is stored in the request. `ra` additionally XOR-obfuscates username with the unpadded challenge text (`ka:6629`). |
| Version 11 or later, ordinary credentials | `cw3.ya:8178–8286`: command 261, RSA keypair from `OpensslSDK.getRsaPEMKeyArry`, username and 64-byte password/proof fields plus public-key extension. Security enabled uses raw SHA-512 of `uppercaseMD5(password) + "#" + decimal long(deviceChallenge)`; security disabled copies raw password. The dynamic/share branch `S4` instead uses the separate `T4/U4` input and `SHA512(rawPassword + "#" + T4)`; it is not SN/user QR login. |
| Reply | `cw3.Z9:5148–5187`: 257 reply checks `SHA1(md5Text + decimal clientNonce)` when security is enabled (`j7:2476–2485`), takes returned IDs and key bytes; 261 reply decrypts the returned key using the retained RSA private key. `L4` is the private transport key. No account `datoken`/`exp` is returned here. |
| Older DVR type 3 | `hu3.java:107–115,319–320,820–864`: `ig0` command-257 login contains ISO-8859-1 username/password arrays of 36 bytes including explicit terminator; require at most 35 representable bytes. No account credential request is called. |
| IPC type 10001 | `nu3.java:244–254,1345–1347,1563–1669,3144–3167`: `su3` command-257 login has ISO-8859-1 username/password arrays of 32 bytes with terminators (max 31). Greeting controls additional challenge XOR. Its loop is decompiler-sensitive; preserve full source and verify bytecode before reproducing that branch. It also has a separate Basic-auth HTTP request builder (`:365–379`), not evidence of an RTSP URL. |

For the 64-byte N9000 arrays, reject encoded overflow and choose an explicit maximum/termination policy; copying 64 bytes is observed, but a device's accepted username/password maximum is not proven. Treat missing password as a pending private credential input, with empty allowed only when explicitly supplied as the intended credential. Never try common/default passwords or retry a rejected password automatically. Device lockout/error replies must terminate the attempt.

The next required N9000 ports are concrete:

1. **Framing and greeting:** `gg0` is an 8-byte little-endian outer header; `wz0` is a 16-byte inner header. `cw3.m7:6940–6965` writes outer magic 825307441, outer length = 16 + actual body length, command, sequence and body. `h4` handles partial/fragmented data (`og0` for fragmentation). Enforce checked lengths and a configured total bound before copying or allocating, and avoid the APK parser's in-place input reads and unbounded fragmentation allocations.
2. **Channel acquisition:** successful login → `B8:456–494`; it validates returned serial when present and parses `ServerNVMSHeader.i` channel GUID/type/index records. `ca:6085–6138` sorts by record index (`cw3.b:285–294`) and assigns public local channel positions from **1**. `r:7439` translates position to GUID; GUID and position are not interchangeable. Device-authority XML calls (`e8/i9`) and final `xa:3274–3294` establish app login/authorization state. The complete app initialization issues many unrelated commands; select only required read-only queries.
3. **Open/close live:** `H5:3875` → `jb:2511–2588` writes command **1281 open / 1282 close** with task GUID, logged-in session ID `e3`, channel GUID, `yz0` + `ll2`; source stream selector is 1 or 2. Newer capability `R3 >= 5` selects `kb:6641` instead. `Z9:5188–5200` acknowledges open/close separately from media. Port both negotiated request forms or reject unsupported capability explicitly.
4. **Media:** `Z9:5338` routes stream data command 65537 to `X7`. Original JADX fails this 2,337-code-unit method. The original `dex-media.stdout` is an **instruction inventory**, not complete control-flow evidence: it omits jump destinations and exception metadata. Fix1 `X7-complete.stdout` supplies widths, registers, literals, resolved references, relative/absolute branch targets, instruction bytes and try/handler tables for `Lcw3;->X7(ZIILcom/tvt/server/utils/GUid;)V`. It reads `ep3/y41/z41` and emits `ov3.onVideoDataFormatHead` (DEX `07d1`) and `ov3.onVideoData` (`08de`). Treat the raw socket framing and task/session fields first; the existing post-native `frames.py` is not a raw `NatTraveral` socket parser.
5. **Encryption differences:** X7 DEX `0853–086b` routes encrypted prefix bytes to `cw3.ga:2361–2394`, using `L4` with `OpensslSDK.aes128_decrypt_string_by_key` and Base64 conversion. `J:com/tvt/server/header/nvms/ServerNVMSHeader.java:571–574` fixes flag 1 and a **128-byte** prefix; require at least that payload size and exactly 128 returned bytes. Fix1 resolves branches `0853`, `0857` and `0865` to `086f`: a missing extension, zero flag or **null decrypt result** bypasses replacement and continues at `0870`. Thus null decrypt does not itself terminate this APK path. The method's CRC argument is unused, and its exception path can return intermediate bytes. This differs from the account `ku3.pa` CRC gate. Implement failure as rejection and require independent integrity evidence before claiming verified plaintext. Do not silently reuse the account decrypt contract.

Fix1 custody: `classes5.dex` is 6,023,784 bytes, SHA-256 `abcb01e8f6319f2f9c24a6559999baa324b5fc90ad4ee248eb7b699644addcc5`, identical to the original manifest. The exact X7 `code_item` occupies DEX file bytes `[0x2009a0,0x201c0f)`, 4,719 bytes, SHA-256 `b4d4c6d589dd5c4e4d425d73014ecdf3e97a98ba98db94dd151b01323510c8a3`. Its 1,208 instructions cover 2,337 code units with 195 offset instructions, no switch/array payloads, and two typed `java.lang.Exception` handlers: protected `[053f,0543)` → `0544`, and `[089a,089e)` → `089f`. There are no catch-all handlers. Addresses in these ranges are code units relative to the instruction array at file offset `0x2009b0`; range ends are exclusive. Branch destinations, instruction boundaries and raw/decoded exception metadata are checked against the preserved bytes. The two try ranges protect `Y7` extension parsing, not the decrypt call at `0861`. The raw code item, source/method identity, exact commands and verification are in `W04-local-QR-connection-source-Fix1-evidence`; this capture closes the omitted-control-flow evidence gap but does not implement or execute X7. Original failed JADX/compile logs, original report/manifests/READY and 59 frozen sources retain their historical identities. Fresh private known18 scanning of Fix1 is a root acceptance step; this source pass did not read credential files or claim a fresh scan.

A decoder/relay must then confirm actual codec, framing, timestamps and a first usable decoded frame. Neither an open acknowledgment nor a callback containing bytes satisfies live acceptance. `libH264Decode.so` plus its dependencies is an available Android decoder path, but no decoder was executed here.

## Implementation path and remaining acceptance

Extend the existing Android helper with a **separate LocalSerialDriver** exposing allocate/discover/openTransport/send/receive/interrupt/destroy and the two exact callbacks above. Keep device credentials in a private scoped input distinct from `DeviceCredential(datoken, expiry, deviceId)`. Add a bounded N9000 codec/state machine with only greeting/login, required read-only device/channel/permission queries and live open/close. Dispatch other discovered types to their own codecs or explicit unsupported states; do not force every recorder through `ku3`.

Do not instantiate the complete decompiled `cw3` application client: `b8 → d9 → e9/f9` (`cw3:2007–2008,2082–2197`) includes conditional device configuration/script operations outside read-only live scope. A command allowlist is necessary for this concrete source behavior. Suppress native/Java raw logging: the selected native functions log SN, derived NAT identity and connection data.

`services/tvt-android-helper/src/main/java/com/wso/tvt/NativeDriver.java` and `JniNativeDriver.java` currently expose only the token-based route. `stage-native.ps1` only stages `libNetClientProtocal.so`. Add verified NatTraveral packaging and a distinct lifecycle; its `DestroyEchoClient` removes callback maps then calls native Destroy (`NatTraveral.java:54–60`, `N:0x225f4c`). It has no account helper `Stop/Quit` lifecycle. Retain one callback instance/process lease and serialize or isolate native global bootstrap; fence every echo/task/session generation and late callback.

| Host/library fact | Concrete consequence |
| --- | --- |
| arm64 NatTraveral | 4,199,472 bytes; SHA-256 `b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb`. This is the inspected native ABI. |
| armeabi-v7a NatTraveral | 3,198,404 bytes; SHA-256 `89e14fb830b9c86349a8b1a3e00622ba882bf0232cb58acb2bf61fb5535fd3f6`. JNI names match, but this pass does not establish identical internals. |
| Android runtime | NatTraveral in both ABIs declares `liblog.so`, `libm.so`, `libdl.so`, `libc.so` dependencies. Use a matching ARM Android process with Bionic/JNI. Windows/x86 Java cannot load this ARM Android ELF; neither can ordinary Linux glibc Python. An ARM-capable Android device/VM is a runtime option; x86 emulation/translation compatibility remains unverified. |
| Crypto/decoder | Stage exact ABI copies of `libOpensslSDK.so` for the selected native crypto wrappers and, only if using its decoder, `libH264Decode.so`, `libaudioNoise_reduction.so`, `libc++_shared.so`. Identities/dependencies are frozen and detailed in [the ABI inventory](apk-audit/08-native-abi-jni.md). Do not require a new vendor SDK to implement the observed interface. |

Resolved: the local route, credential separation, SDK/library, JNI arguments/callbacks, source bootstrap, identity transform, initial bounds and negotiated protocol families. Still unexecuted: actual device type/security version, supplied credential validity, current region/bootstrap reachability, device permission/channel records, successful authentication, live payload, decode and two-store isolation. Remaining source work for production is the bounded implementation of the exact packet serializers/parsers and negotiated live variants, including review of the DEX media branch; source availability is not runtime acceptance. No guessed RTSP URL, device port, account-token extraction, or successful empty-password assumption is part of this handoff.
