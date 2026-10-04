# Windows local NAT development probe

Date: 2026-10-03 (Asia/Seoul). Executable baseline supplied by root: `756946ca73cff31d7ebb23141873088b470a96b4`; documentation HEAD supplied by root: `36fc954`. This six-file slice is a source implementation and offline verification packet. Root owns actual build, installation, and native execution after independent review. **MATCHED=0; release_ready=false.**

The distinct, debuggable package `com.wso.tvt.localprobe` has one explicit activity, no permissions (including no INTERNET), and no service, receiver, provider, or intent filter. It cannot connect real CCTV. It accepts no serial, account, password, profile, or command input. It loads only `libNatTraveral.so`, reflects the independent literal 18 native declarations and three callback identities, creates the Android JNI driver once, allocates at most one echo, removes callbacks, and requests interrupt/destroy. No discovery, open, send, receive, authentication, channel, or media operation runs. Native cleanup remains unproved even when JNI calls return.

## Root build interface

Run with existing PowerShell 7. All paths are explicit local inputs; no install, ADB, native execution, network, or SDK download occurs during build.

```powershell
& '<existing-pwsh.exe>' -NoProfile -File services/tvt-android-helper/build-local-load-probe.ps1 `
  -ApprovedApk C:/wso-private/superliveplus/1.18.1-2026-10-02-handset/base.apk `
  -TransportReceipt '<absolute-repo>/.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-local-serial-transport-Fix1-reviewed-root-receipt.json' `
  -JdkRoot C:/Android/tools/jdk-21.0.12.1+1 `
  -BuildTools C:/Android/build-tools/36.0.0 `
  -AndroidJar C:/Android/platforms/android-36/android.jar
```

The receipt must be independently supplied by root with status `ACCEPTED_LOCAL_SERIAL_TRANSPORT_ROOT_REVIEW` and a `files` object mapping the exact eight local transport paths to `{bytes, sha256}`. These paths are NatTraveral, LocalSerialConfig, LocalSerialDriver, JniLocalSerialDriver, LocalSerialTransport, LocalSerialTransportTest, verify-local-host.ps1, and tvt-local-serial-transport.md. Their exact relative paths are enumerated in the builder. Missing approval or differing source bytes blocks before tool execution. The author cannot substitute readiness for acceptance. Accepted receipt and source hashes are rechecked after build.

The whole private APK must be exactly 170064551 bytes / SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. Only these two unique ZIP entries are extracted to a unique ignored owned directory:

| APK entry | Bytes | SHA-256 |
| --- | ---: | --- |
| lib/arm64-v8a/libNatTraveral.so | 4199472 | b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb |
| lib/armeabi-v7a/libNatTraveral.so | 3198404 | 89e14fb830b9c86349a8b1a3e00622ba882bf0232cb58acb2bf61fb5535fd3f6 |

The builder rejects duplicate ZIP names, caps entries at 20000, checks exact native sizes/content, copies the four accepted wrapper/config/interface/driver classes and probe into immutable build inputs, compiles Java 8, runs D8, links the diagnostic manifest, aligns, and signs. The complete original APK/client and LocalSerialTransport manager are not packaged. The ephemeral development signing password is supplied only through child environment; its exact key file is deleted after signing. Signature, alignment, signed manifest, native entry inventory, and source custody are checked before writing `build-result.json` under `.superpowers/runtime/windows-local-native-probe/build-<unique-id>`.

Each build stage retains complete child argv, UTC start/end, nullable exit, child-start state, exact child/owner PIDs, timeout/kill/reaped/pipe/capture/ownership flags, and bounded private partial stdout/stderr captures (65536 bytes per pipe). Direct process completion has a 180-second deadline, one retained-handle kill attempt, up to5 seconds to observe reap, and a separate2-second pipe-completion deadline. Asynchronous drains keep consuming beyond the retained cap; truncated output fails the stage. Start failure also produces a structured receipt and empty private captures. A stage with timeout, nonzero exit, output truncation or incomplete evidence fails before any next build stage. Exit is null when unavailable. No process-tree, name or port kill occurs.

Unconfirmed process or inherited-pipe completion retains the original Process object and both drain objects. A script-level passive custody guard keeps the build owner alive after that failure until the exact child and pipes finish; it writes an ownership follow-up receipt and releases the original handle only then. It never retries kill or continues the build. Root must supervise this potentially waiting owner rather than interpreting a failed-stage receipt as termination proof. Partial captures can be updated when passive completion is finally observed. The original failed-stage outcome remains retained, and no success build result is emitted.

Build result schema version 1 includes `status=BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED`, `package`, absolute `apk`, `apkBytes`, `apkSha256`, `developmentOnly`, `signatureVerified`, `manifestVerified`, `nativeVerified`, `sourceHashes`, `transportReceiptSha256`, `nativeEntries`, `packagedEntries`, `captures`, `developmentKeyDeleted`, `deviceExecution=NOT_EXECUTED`, `MATCHED=0`, and `release_ready=false`. The controller validates these safe admission fields and independently rehashes the APK. Metadata must come from the reviewed builder in operator-owned storage; a caller-authored JSON assertion is not independent acceptance.

## Windows controller interface

There are exactly two fixed development profiles. Caller-defined host, port, and serial are rejected.

| `--runtime-profile` | Host | ADB server | Emulator |
| --- | --- | ---: | --- |
| google-translation-development | 127.0.0.1 | 5038 | emulator-5580 |
| aosp-arm-development | 127.0.0.1 | 5039 | emulator-5590 |

```powershell
& '<existing-python.exe>' -m wso_tvt_bridge.windows_android_probe `
  --adb C:/Android/platform-tools/adb.exe `
  --build-result '<absolute-owned-build>/build-result.json' `
  --staging-root C:/Android/owned/wso-local-native-probe-staging-20261003 `
  --image-purpose development-debug `
  --runtime-profile google-translation-development `
  --result '<new-absolute-private-result.json>'
```

Choose `aosp-arm-development` only for root's separate ARM guest route. The Google translation image is licensed for development/debugging; neither profile permits production use. The AOSP fallback is an old Android image whose old security patch and actual boot outcome belong to the runtime owner. No physical phone prerequisite exists. The controller refuses non-Windows execution and requires an existing explicit adb.exe, a new result path, and the development label before device side effects.

`--staging-root` is required, with no inferred default or browser/environment input. A trusted operator must precreate a private ASCII directory on this Windows C: drive (path length at most120 characters), preserving exclusive custody and current-user/SYSTEM ACLs. The controller validates existence, type, every ancestor against reparse points, and root filesystem identity before device commands. It creates only one unique `probe-<UUID>/probe.apk` child under that explicitly supplied root after package absence admission. The accepted build APK remains the authority: source size/SHA are verified before and after a bounded copy, and staged size/SHA plus directory/file identities are verified before installation and after it returns. Copying does not issue artifact approval. The original approved path may contain Korean characters; the fixed install argv receives only the verified ASCII staged path.

Root's actual Windows/API24 investigation found the Unicode worktree path and its slash variant fail an ADB push to `/data/local/tmp/./.`. The same signed bytes installed from an owned ASCII path, with stdout exactly `Performing Push Install\r\nSuccess\r\n`, and root confirmed UID-guarded removal. The controller admits only `Success` with an optional line ending, or the exact `Performing Push Install` preamble followed by one `Success` line (LF/CRLF supported). Failure, unknown/duplicate/ambiguous lines, unsupported preambles and leading blank/space lines never establish install success. Package ownership still requires the exact UID query after a valid successful install.

After a failure-free probe and confirmed package absence, staging cleanup first rechecks root/directory/file identities and the accepted staged hash, requires exactly the fixed APK entry, then unlinks only that file and removes only its empty owned directory. No recursive delete/move or sibling/extra-file cleanup occurs. Failed or uncertain runs retain their staged artifact/directory for operator supervision. The safe host result adds `staging_directory` and `staging_cleanup` (not_created/removed/retained_failed/retained_uncertain); unknown ownership, changed bytes or extra entries never become successful cleanup. Exit0 also requires staging_cleanup=removed. Private root ACLs and absence of concurrent privileged filesystem/package mutations remain operator assumptions.

Every child uses fixed argv with `-H 127.0.0.1 -P <profile-port> -s <profile-serial>`. The installed ADB's remote-host behavior refuses local server start, as documented in the existing Windows runtime report; this controller issues no server/VM lifecycle commands. The external supervisor must keep the owned server and VM running. The child environment contains only Windows process essentials; credentials, caller ADB selectors, and profiles are not forwarded.

Preflight requires boot completion, guest API at least23, an ARM ABI, and exact package absence, rechecked immediately before the single install without replacement. Every ownership query uses the fixed `shell dumpsys package com.wso.tvt.localprobe` command with at most65536 private output bytes. Root's read-only API24 evidence confirms this command's package/UID block and explicit absent-package response; the API24 guest rejects the former `cmd package list packages -U` command despite exit0. The parser accepts only the explicit `Dexopt state:` / `Unable to find package: com.wso.tvt.localprobe` absence response. An installed response requires exactly one fixed package marker directly in `Packages:` and exactly one direct `userId` in that package block. UID fields in a later shared-user section are ignored. Empty output, unsupported/error text, duplicate/unrelated/malformed package blocks, missing/duplicate scoped UIDs or output overflow are failures and never imply absence.

The other supported absence grammar comes from root's23759-byte Google30 capture: exactly ordered Queries, Package Changes, Dexopt state, Compiler stats, APEX session state, Active APEX packages, Inactive APEX packages and Factory APEX packages sections. Dexopt and Compiler each require exactly one explicit absence for the fixed probe; APEX sections must have the captured empty bodies, and no Package/userId/pkg/applicationInfo identity marker or error text may contradict absence. Queries and package-change metadata may include historical package names; history is not an installed package marker. Unknown/duplicate sections, misplaced absence, a different package, error output or contradictory identity fails closed. This is section parsing for the two captured runtime profiles, never broad substring-to-absence admission. Root's current read-only captures establish command shapes; the author performs only offline shape checks.

An existing probe package prevents ownership claim. After successful install, the exact package UID is recorded. Only that invocation's package may be force-stopped/uninstalled, and UID/package identity is rechecked before each destructive command; identity changes, lost subprocess handles, command deadlines, and failed cleanup preserve an uncertain result. There is no PID/tree/port kill, default server5037, phone selection, logcat capture/clear, trust installation, or browser/security bypass. UID checks bound accidental ownership drift; they do not establish exclusion against a concurrent privileged package manager actor. Use a supervisor-owned isolated guest without concurrent package mutations.

Each launched child handle is retained. Two asynchronous pipe readers privately drain bounded4096-byte output (the fixed package inspection alone allows65536 bytes), discard stderr, enforce deadlines, and kill only the directly retained child on timeout. Stderr remains capped at4096 bytes even for package inspection. Raw child/native text is never copied into safe controller results. Result polling reads only `exec-out run-as com.wso.tvt.localprobe cat files/probe-result.json`. The command budget defaults to15 seconds (max30); the result budget defaults to45 seconds (max120), plus a bounded current command and cleanup. A child reaped after timeout does not prove that an Android/JNI process stopped.

## API23 diagnostic compatibility amendment

Root amended the original minAPI26 brief to permit this no-network diagnostic on the API25 ARM fallback. The manifest and D8 min API are23; target API remains36. The causal offline test first rejected API25 because minSDK was26, then passed after this amendment. A separate test rejects guest API22 before install. Full service/runtime acceptance is unchanged.

The probe's Android references are Activity lifecycle/private-files/finish and Bundle (available before23), plus Process.is64Bit (API23, supplied by root's amendment). Java references are Thread, reflection, collections, File/FileOutputStream/FileDescriptor.sync/File.renameTo (available before23), and StandardCharsets (API19). The four packaged helper classes use ConcurrentHashMap, Arrays, StandardCharsets, and TimeUnit, with Java8 lambdas handled by D8's min23 desugaring. No java.nio.file, API26 file API, or manager class is required. This is a source/reference audit and invented-stub compilation; root must verify actual D8/build/runtime compatibility. It is not execution evidence on API23/25.

## Result and lifecycle meanings

The app writes at most4096 bytes to app-private `files/probe-result.json` with a synced temporary file and rename. Exact keys: `schemaVersion=1`, `version=local-nat-probe-1`, `abi` (arm64-v8a/armeabi-v7a/unknown), `is64bit`, `stage`, `failure`, `loaded`, `descriptorsMatched`, `bootstrapped`, `allocationObserved`, `callbacksRemoved`, `interruptRequested`, `destroyRequested`, `cleanupProven=false`. ABI is the package's ARM ABI chosen from process bitness, rather than host x86 architecture. Stages are created/reflection/load/bootstrap/allocate/remove_callbacks/interrupt/destroy/complete. Failures are none/linkage/reflection/security/runtime/allocation_zero/io/unknown. Successful operation flags are set only after calls return. Exceptions retain the failing stage; no exception text, stack, handle, pointer, native detail, path contents, Android logs, or device information is persisted.

The host result has `schema_version=1`, `purpose=development-debug`, `runtime_profile`, generic `failure`, `package_owned`, `package_cleanup` (not_owned/confirmed_absent/uncertain), `native_cleanup=unproved`, sanitized `device`, `matched=0`, `release_ready=false`. The private result file contains this result plus command argv/times/exit/timeout/reaped/overflow receipts, without raw child captures. Exit0 requires a complete failure-free diagnostic and confirmed package absence. A failed native stage yields `probe_failed` with the original safe stage/category preserved; missing/malformed/bounded-output violations are separately classified. Probe and host schema reject arbitrary fields and success substitution.

| Evidence | Meaning |
| --- | --- |
| VM boot | Android guest operates; no library acceptance |
| loaded | Exact packaged ELF load returned; no JNI bootstrap claim |
| bootstrapped | Driver creation returned after InitGlobal/log-disable calls; no device connection |
| allocationObserved | One nonzero echo returned; the value stays private |
| destroyRequested / cleanupProven=false | Synchronous cleanup requests returned; asynchronous native completion remains unproved |
| package_cleanup=confirmed_absent | Owned package removed; VM/native resource reclamation is a separate runtime gate |
| Authentication / channel / usable frame | Not implemented or executed in this diagnostic |

Direct native Android logging is not proved suppressed by Nat2EnablePrintLog(false) or wrapper callback discard. The controller reads no Android logs; root owns private native log handling and process/VM replacement acceptance. Pending gates remain independent six-file source review, exact reviewed build, actual library/JNI execution, isolation/cleanup, authorized device discovery/authentication, channel selection, decoding and usable-frame acceptance. Offline tests use invented child/Java/ZIP data and do not count as CCTV or production acceptance.
