# Private Android local serial transport

Analysis/implementation date: 2026-10-03, Asia/Seoul. Root-supplied executable source baseline `756946ca73cff31d7ebb23141873088b470a96b4`, documentation HEAD `36fc954`; neither was rechecked with Git. This scoped port adds eight files. It is a host-tested private transport boundary: **MATCHED=0; release_ready=false**. No actual QR, device serial, password, account, phone, ADB, vendor network, native library execution or device acceptance was used.

The source contract is [the local device source report](tvt-local-device-connection-source.md), original `com/tvt/network/NatTraveral.java`, `network/a.java:210–381`, `m42.k:392–539`, and the W04 frozen native captures. The source review supports transport/auth direction; its media I1 concerns X7 DEX completeness and is not evidence of acceptance for this transport. This slice implements no device credential handshake, channels, live commands, media, decoder or full `cw3` application client.

## JNI identity and initialization

`com.tvt.network.NatTraveral` preserves all 18 original native declarations, including private `InitGlobal()I`, `Initialize()J`, `Destroy(J)I` and exact `GetVersionType`/`SetValue` descriptors. The status callback is `(JZILjava/lang/String;)V`, receive callback `(J[B)I`. Class inspection on the Windows host does not load a library. `JniLocalSerialDriver.createAndroid()` explicitly creates the one retained NatTraveral instance inside an Android ART/Dalvik process. Construction loads `NatTraveral`, calls `InitGlobal`, and invokes `Nat2EnablePrintLog(false)`; no creation retry is permitted after an uncertain bootstrap. The account `NetClientProtocal`/NativeDriver lifecycle is separate.

The inspected arm64 library is 4,199,472 bytes, SHA-256 `b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb`. The required deployment target is Windows-hosted Android with Bionic/JNI and a compatible ARM ABI; a physical phone is optional. This slice does not copy the library, change staging/manifest/build files, or verify its Android load. Root must stage and independently rehash that exact binary before the Windows-hosted Android probe.

`LogPrintCallback` discards strings without formatting. Owned callback maps are private and reject replacement. Java wrapper logs are absent. Disabling NAT2 print and discarding this callback **does not prove suppression of native `__android_log_print` calls**: reviewed native bodies contain direct SN/identity/connection logging. Windows-hosted Android execution requires an isolated private process and a reviewed log handling policy; those native messages must never enter public diagnostics or captured artifacts containing actual identifiers.

## Private configuration and authority

`LocalSerialConfig.operatorReviewed(...)` takes explicit serial, NAT1/NAT2 host/port, network flag, traversal mode, UPnP choice, Android private files path, platform, version, app name/model, buffer/queue caps and caller budget. Its name describes a trusted operator-supplied configuration contract. Construction performs structural validation; **it does not issue or verify current actor/store/channel/credential authority**. An eventual gateway must obtain that authority separately and must not accept browser-created grants or arbitrary browser paths/hosts. There are no regional host, port, app/version/model or files-path defaults.

| Admission | Implemented policy |
| --- | --- |
| Serial | ASCII alphanumeric, 1–63 UTF-8 bytes; lowercase ASCII becomes uppercase explicitly. This deliberate policy uses the native capacity and differs from the specific APK UI's narrower 30-character branch. No usernames/passwords exist in this object. |
| Strings | Nonempty, no NUL, no unpaired surrogate, no truncation; UTF-8 byte limits: NAT1 127, NAT2 63, platform 31, version/app/model 63, private path 255. |
| Private path | Absolute Android-style path; reject backslash, duplicate separator, `.`/`..` components. `path UTF8 bytes + serial bytes + 16 <= 255` is a conservative admission margin for the source's checked cache-path concatenation, not a claimed recovered suffix or a filesystem permission check. Root supplies the app-owned private directory. |
| Numeric values | Ports 1–65535; explicit 0/1 network/traversal modes; buffer 1–10,240, event cap 1–1,024, byte queue at least the buffer cap and at most 1,048,576; positive budget at most one hour. |

The JNI driver passes raw normalized SN into GetVersionType. Native NAT2 hashes it internally; it is never prehashed or replaced with `datoken`, USER/P2P tokens or a device password. The output is a local private exact `byte[66]`, untrusted opaque material that is never returned, logged, persisted or used as credentials. Its Java array is filled with zero after the call, which is only best effort and proves nothing about native/copy memory erasure.

## Manager state and protocol handoff

Public manager API is `LocalSerialTransport(driver,config)`, `discover()`, `openTransport()`, `state()`, `close()`. There is no public echo-handle DTO, raw socket command or authentication/live success status. The injectable LocalSerialDriver interface uses long handles internally to test the native boundary and is not a gateway/RPC API.

```text
NEW -> DISCOVERING -> DISCOVERED -> OPENING -> OPEN
                         unsupported/error/nonzero open -> FAILED
any retained generation -> CLOSING -> CLOSED (only proved cleanup)
                                  -> QUARANTINED (unknown/false cleanup)
recycled echo -> QUARANTINED without reassigning callbacks/native cleanup
```

`Initialize` admits any nonzero opaque long, including signed values. `discover()` preserves exact type 3/10001/20001 and other/error values plus private `GetErrorCode`; it does not translate failures into password labels. `openTransport()` performs SetConnectTraversalMode followed by SetValue. Only SetValue return zero selects transport OPEN. GetConnectType numeric 3 selects CALLBACK; all other selected values use POLL. Native symbolic enum names are not used to reinterpret this observed numeric branch. A connection callback or bytes do not promote to credential authentication.

NAT2 connection status is bounded private branch metadata during DISCOVERING/DISCOVERED; discovery's returned type/error decides its outcome, permitting the independent NAT1 path. During OPENING, a negative NAT2 status is retained as a pending failure until GetConnectType selects the mode. It is terminal for selected CALLBACK transport and leaves selected POLL transport open. After OPEN, negative NAT2 status is terminal only for CALLBACK mode; POLL status remains metadata. A later positive status cannot revive a failed generation. Queue overflow still fails closed independently of these status semantics. This follows retained `m42.d:97–107`, native `GetDeviceType:415–483`, and `network/a:71–86,233–247`.

The next N9000 adapter belongs in `com.wso.tvt.local` and uses package-only `send(bytes,length)`, `receive(bytes,length)`, `pollEvent()`, `receiveMode()` and `lastNativeError()`. Events copy bytes at ingress and again at consumption; status strings are discarded. Framing/auth/live adapters must independently enforce current actor/store/channel/credential authority, checked packet lengths, protocol negotiation, an explicit read-only command allowlist, authentication evidence, channel GUID mapping, and decoded-frame acceptance. Do not instantiate full decompiled `cw3`, whose initialization has configuration/script side effects.

Send/receive require `0 < length <= actual buffer length <= configured buffer cap`. Oversized positive native results are rejected; zero receive is no-data, negatives are private transport failure. Partial send counts are returned so the adapter can send only the remaining suffix under its budget. Poll bytes and callback bytes share bounded event/byte queues. Callback data arriving synchronously during OPENING is retained within those bounds; if GetConnectType subsequently selects polling, pending callback data is discarded. No parser/media claims attach to these bytes. Queue overflow transitions to FAILED and admits no further callbacks. Oversized/wrong-echo/null/empty callbacks return zero.

## Ownership, cancellation and process limits

One static manager lease owns the native global profile at a time. Each manager is a single generation; there is no reopen/reconnect method. Driver calls run outside the callback/state monitor. Callback closures verify exact echo/generation and current state, so a fetched callback still drops after close. Successfully retired echo IDs remain in bounded process history (at most 1,024): a reused echo is refused because native callbacks carry no generation tag. No new manager can claim a quarantined process.

Close retires the generation and clears the private queue first, removes owned callbacks, then requests Interrupt. Outstanding calls retain their original handle. Destroy occurs only after in-flight calls drain and callback removal is proved. A bind racing close triggers callback removal again after the bind returns. Cleanup operations are serialized on a separate cleanup monitor; unknown/false/throwing cleanup keeps the original echo/driver/config/process lease and enters QUARANTINED. An allocation that throws before returning a handle also quarantines the process: Java cannot prove that no native allocation occurred. A reused echo is quarantined without interrupt/destroy because a historical callback could otherwise identify an unrelated allocation. Cleanup is never retried against a possibly recycled address.

The original Destroy JNI capture `0x225f4c` shows Stop, removal from the socket set and DecRef followed by return zero. That integer alone does not establish asynchronous completion, callback drainage or allocator reuse safety; the selected Interrupt completion semantics are also unproved. The JNI driver therefore requests cleanup and returns **false** for completion proof. Real JNI sessions always require process replacement after close; CLOSED in host tests represents only a synthetic driver that explicitly proves its cleanup contract. Process replacement/termination, private log policy and runtime cleanup acceptance belong to root's Windows-hosted Android host/probe gate; a physical phone is optional.

The monotonic budget starts at manager construction and is checked before/after operations, callback admission and event consumption. The private hosting caller must independently schedule cancellation/close and a process watchdog. A synchronous blocked JNI call or blocked Interrupt/Destroy cannot be hard-terminated by these Java checks. Native receive allocates its Java array before this queue sees it: Java caps do not bound native preallocation or prove memory containment. Android isolation, hard process termination, memory limits and replacement remain required hosting work.

## Executed verification and remaining gates

Run PowerShell 7 `services/tvt-android-helper/verify-local-host.ps1 -JdkBin C:/Android/tools/jdk-21.0.12.1+1/bin -CaptureDirectory <private-evidence-directory>`. The helper uses a unique build directory, explicit six source inputs, hidden Java processes, Java 8 target, strict lint, and complete per-command argv/time/exit/stdout/stderr receipts. It does not run the older helper suite.

The scoped host suite checks independent literal JNI descriptors, host load guard, configuration bounds, callback copying/caps, status/open separation, polling, partial send/native lengths, unsupported discovery, signed handles, synchronous callback/close reentry, blocked-discovery cancellation, late/recycled callbacks, deadline before allocation, close during binding, synchronous opening data, and unproved/removal-failed cleanup/unknown allocation. Causal RED receipts demonstrate missing implementation and four concrete lifecycle failures before their fixes. See the W04-local-serial-transport report/evidence packet for exact results and hashes.

Fix1 adds negative NAT2 cases during supported discovery, OPENING with either selected mode, and established POLL/CALLBACK operation. Every test worker uses a FutureTask, and join transfers its exact failure to the main test thread. The focused worker-failure regression verifies that an assertion cannot be lost after thread termination. Original review/evidence receipts remain preserved; Fix1 has its own preimages, RED/GREEN captures and manifest.

Remaining acceptance: independent root source/custody review; compatible ARM library packaging/load on Windows-hosted Android; reviewed region/build/private-path profile; private process watchdog/logging/cleanup; explicit device passwords and current store/channel authority; actual two-device discovery; negotiated credential handshake; channels; read-only live/media parsing; codec decode and a first usable frame; two-store isolation. None has executed in this slice. A physical phone is optional. SDK source availability and passing synthetic host checks do not establish actual connection, authentication or live video.
