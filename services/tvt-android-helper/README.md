# APK-derived Android JNI helper source

Source baseline: SuperLive Plus 1.18.1 (version code 20267), APK SHA-256
`f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.
Contract: [`apk-derived-adapter-contracts.md`](../../docs/integrations/apk-derived-adapter-contracts.md).
This slice supplies Java 8 source and host verification. Android packaging, load,
network startup, device interoperability and secure worker RPC remain pending.

## Production boundary

`com.tvt.network.NetClientProtocal` preserves all 48 APK instance native methods
and all 12 callback descriptors, including static `LogPrintCallback`. Native logs
are discarded. Its constructor does not load native code. On Android,
`JniNativeDriver.createOnAndroid()` calls the explicit guarded
`System.loadLibrary("NetClientProtocal")` entry once. Host JVMs are rejected;
there is no production fallback or simulated success. Fakes are confined to tests.
Use one trusted helper classloader in one dedicated process: the controller's
process lease is scoped to that loaded class. Multiple independent classloaders
are outside this hosting contract.

Provide validated private `RuntimeConfig` with exactly the eight decoded keys.
`cliType`/`natServerPort` are integers; the other six are strings. Nullable
optional strings serialize as JSON null, matching the APK's `serializeNulls()`.
No token, NAT host, client version, account or device field has a default.
`DeviceCredential` keeps device-access token, raw expiry, timeout and device ID
private. Expiry units and freshness are supplied by the reviewed upstream
contract; this class does not guess or convert them.

The controller owns Init → Start → Connect → live task → task close → Disconnect
→ Stop → Quit. Init failure still requires Quit because native Init first retains
the Java object. Start failure also attempts Stop. Positive connection/task IDs
mean native allocation, not successful transport or usable media. Playback, Talk,
PTZ, encryption and media declarations are retained for exact ABI compatibility;
the controller currently routes live tasks only. Talk formatting/pacing,
encryption keys, decoded media and network commands have no guessed implementation.

## Lifecycle and private callbacks

Each controller has one immutable manager generation and session generation. It
admits only one session for its lifetime; create a new controller after successful
close. There is no reconnect or write retry. A callback observer captures those
generations, queues bounded private payloads and calls no user code on native
threads. `drain()` returns internal events to a trusted helper consumer. Exact
native identifiers, callback context and declared payload length are preserved;
copy only the validated prefix. Event/config/credential/driver/controller
representations contain no raw data. These objects must never be returned in
browser DTOs or logs. No public RPC or credential transport exists in this slice.

Task data remains streaming. A task-error callback immediately fences its task and
stores one zero-payload terminal record on the bounded task ownership slot,
independently of data queue count/bytes. It purges queued task data and rejects
duplicate errors or late data. `drain()` delivers that error once and closes the
native task on the host caller thread; native callbacks never call JNI cleanup.
Ownership is reserved before a native request so synchronous terminal callbacks
also survive queue pressure, then their native ID is checked against the return.
Terminal slots still count against resource capacity until drained or closed.
Explicit `cancel()` removes and closes an owned task idempotently;
`expire()` removes and closes deadlines measured in the injected monotonic clock's
units. The host should call expiry on its own bounded scheduler. Expired events
are rejected even before expiry runs. The caller supplies an absolute deadline.

Task callbacks must match both native task ID and the submitted nonzero context.
The APK discarded this native long context. Native echo correctness is still
runtime unverified: mismatches fail closed and never count as stream success.
Previously used task IDs are rejected for the entire manager lifetime. An active
ID collision retires both the new context and existing ownership, purges their
queued/terminal records, then closes the shared native ID once. The retired
contexts cannot dispatch or close it again. A fresh positive allocation that
reuses an already retired ID is rejected and that new allocation is closed.
This avoids silently attributing callbacks to recycled IDs. Connection callbacks lack
an equivalent context; one session per manager and generation fencing bound the
static attribution guarantee, but late-callback/global-reference release timing
requires Android runtime proof.

Limits are explicit: up to 4096 total task ownership slots (including pending
requests and terminal cleanup records), 4096 queued callbacks, 8 MiB per
callback and 16 MiB aggregate queued bytes. The queue also respects the smaller
configured count × payload bound. Lifetime task IDs are bounded to 16 × the
active-task limit; retire the manager when exhausted. Commands fail with fixed
private-free exceptions when another native operation is active. Native calls
execute outside state monitors, so synchronous callbacks and concurrent close
do not deadlock. Close fences delivery before waiting for an operation to finish.
It waits at most five seconds for an in-flight operation; a BUSY status retains
ownership and permits a subsequent cleanup attempt after that operation exits.
Native calls themselves cannot be timed out safely by Java: the dedicated host
process watchdog and process termination policy remain required runtime work.

Cleanup attempts every owned stage. Fixed status bits identify task close,
disconnect, stop, quit or busy failures without native text. Any native cleanup
failure quarantines the process lease even if Quit returns; controlled process
restart is required. A completed cleanup is idempotent and does not repeat JNI
calls. Actual native release remains unverified.

## Local host verification

Use an existing JDK; no global installation or Gradle/Maven/JUnit is needed:

```powershell
./verify-host.ps1 -JdkBin 'C:/Android/tools/jdk-21.0.12.1+1/bin'
```

This runs javac `--release 8 -Xlint:all,-options -Werror`, controller tests,
configuration serialization, every cleanup failure in a fresh JVM, exact
reflection descriptor/modifier comparison against a literal APK inventory,
callback forwarding, host loading rejection and `javap -p -s` inspection.
The excluded options warning category is JDK21's obsolete Java8 option warning;
source warnings still fail compilation. Host tests do not load the private
Android library, and do not prove Android or device execution.

## Private native packaging input

`stage-native.ps1 -ApkPath <private-base.apk> -Abi arm64-v8a` stages only the exact
chosen native library into ignored `build/native/<abi>/`. The script checks the
complete APK size/digest, exact unique ZIP path and bounded uncompressed size,
and complete native digest before writing. It never loads the binary. Native
binaries, APKs, compiled classes and private configuration stay outside source
control. Native identities:

| ABI | ZIP path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| arm64-v8a | `lib/arm64-v8a/libNetClientProtocal.so` | 3920784 | `c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717` |
| armeabi-v7a | `lib/armeabi-v7a/libNetClientProtocal.so` | 3018084 | `17d44c46654752f761d8117989c0101c7662fc494a8900ca2b307de1b234f23f` |

No packaging, load-only Android smoke, Init/Start/connect, account/device/network
execution or browser acceptance is included in this host-source slice.
