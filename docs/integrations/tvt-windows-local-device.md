# Windows-hosted private local discovery/open

Date: 2026-10-03 (Asia/Seoul). Source baseline supplied by Root: `756946ca73cff31d7ebb23141873088b470a96b4`, documentation `36fc954`. This integration provides an executable private discovery/open path. **MATCHED=0; release_ready=false** until independent device acceptance. Root already executed the separate exact NatTraveral JNI bootstrap/allocation probes on ARM32/AOSP24 and ARM64/Google30; that evidence does not establish discovery, native cleanup, authentication or media.

The helper is a distinct development package `com.wso.tvt.localdevice`, Activity `com.wso.tvt.local.LocalDeviceProbeActivity`, min SDK23/target36. Its only permissions are `INTERNET` and `ACCESS_NETWORK_STATE`. Root authorized the second normal read-only permission because the initially requested INTERNET-only manifest prevented exact source runtime network observation. There is no service, receiver, provider, full APK Application, login, credential, send, configuration, script, decoder or media command.

## Build and reviewed source custody

Root executes the builder only after independent source acceptance:

```powershell
pwsh -NoProfile -File services/tvt-android-helper/build-local-device-probe.ps1 `
  -ApprovedApk <absolute-private-approved-apk> `
  -TransportReceipt <absolute-reviewed-transport8-receipt> `
  -BootstrapReceipt <absolute-reviewed-bootstrap3-receipt> `
  -DiscoveryReceipt <absolute-reviewed-discovery6-receipt>
```

Receipt statuses are respectively `ACCEPTED_LOCAL_SERIAL_TRANSPORT_ROOT_REVIEW`, `SOURCE_ACCEPTED_UNPUBLISHED`, and `ACCEPTED_WINDOWS_LOCAL_DEVICE_ROOT_REVIEW`. Discovery receipt additionally contains `dependencies={transport: accepted8.files, bootstrap: accepted3.files}`, copied by Root from the independently reviewed receipts. The controller requires those exact maps, current dependency hashes, build source hashes and the immutable discovery-receipt digest. Each receipt has `files` keyed by exactly the owned relative paths, with `bytes` and lowercase `sha256`. Receipts are independent Root inputs, never author attestations. New source six are the manifest, Activity, builder, controller, focused test, and this document; transport eight and bootstrap three remain unchanged. The builder verifies all receipts before tools/extraction and again after packaging. Only accepted NatTraveral, LocalSerialConfig, LocalSerialDriver, JniLocalSerialDriver, LocalSerialTransport and the new Activity enter the helper.

The approved whole APK is 170,064,551 bytes, SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. Native entries are only ARM32 `lib/armeabi-v7a/libNatTraveral.so` (3,198,404 bytes, `89e14fb830b9c86349a8b1a3e00622ba882bf0232cb58acb2bf61fb5535fd3f6`) and ARM64 `lib/arm64-v8a/libNatTraveral.so` (4,199,472 bytes, `b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb`). Duplicate ZIP entries and additional packaged native libraries fail admission. The exact manifest, signature, alignment, source snapshots, receipts, packaged inventory, native bytes/hash and APK bytes/hash are retained under unique ignored `.superpowers/runtime/windows-local-device-probe/build-<uuid>/` output. An ephemeral development key is deleted in `finally`; password values never enter receipts. The reviewed bounded builder child-owner pattern retains uncertain original child/pipe handles, stops the build, and waits passively for ownership completion. Builder performs no ADB, network or vendor/native execution.

## Private operator controller

`wso_tvt_bridge.windows_local_device` exposes:

```python
config = DeviceProbeConfig(
    adb=owned_existing_adb_exe,
    build_result=owned_build_result_json,
    review_receipt=independent_discovery6_receipt,
    image_purpose="development-debug",
    staging_root=existing_private_ascii_root,
    runtime_profile="aosp-arm-development",  # or google-translation-development
)
request = PrivateDeviceRequest(
    serial=authorized_raw_serial,
    country_code="KR",  # explicit policy, not inferred locale
    generation=unique_uuid_hex32,
    budget_millis=40000,
    greeting_millis=5000,
    greeting_bytes=10240,
)
result = run_device_probe(config, request)
```

The two fixed existing supervisor-owned targets are AOSP24/ARM32 at loopback `127.0.0.1:5039`, `emulator-5590`, and Google30/ARM64 at `127.0.0.1:5038`, `emulator-5580`. Controller requires exact SDK/advertised ARM profile, twice proves package absence, performs one non-replacing install, and validates the exact scoped package UID before private operations and cleanup. It owns neither the ADB server nor VM. There are no arbitrary endpoint, path, command or public raw/native-handle inputs. Existing Windows staging validation requires an explicit existing bounded ASCII `C:` root with no reparse ancestors; an isolated unique helper APK copy is hashed before/after copying. Current actor/store/channel/credential authority remains a separate Root responsibility. A private operator object establishes no public authorization grant.

Optional CLI is `python -m wso_tvt_bridge.windows_local_device --adb ... --build-result ... --review-receipt ... --staging-root ... --runtime-profile ...`. It reads only an exact bounded stdin object with six keys: `serial`, `country_code`, `generation`, `budget_millis`, `greeting_millis`, `greeting_bytes`. Runtime network type comes from the Activity context. No raw serial or credential is permitted in command arguments or environment. Direct API is preferred for Root private orchestration. Serial is ASCII alphanumeric1–63, explicitly uppercase-normalized; country is an explicit uppercase country code or empty source fallback, never region AP/EU. Bounds: budget1000–120000ms, greeting1–5000ms strictly less than budget, bytes1–10240. There are no automatic retries.

## Private Android schema and identity

The controller starts the context-only phase first. It invokes Activity with fixed `phase=context` and a nonsensitive generation UUID. Activity resolves its own canonical `getFilesDir`, persists/reads private `SINGLE_ID`, removes UUID hyphens, and writes bounded `files/context.json`:

```text
schemaVersion=1, version="local-device-1", generation=hex32,
privateFilesPath=owned Android files path,
singleId=32 hexadecimal characters, sourceNetworkType=0|2|3|4|5
```

A malformed existing SINGLE_ID fails context creation rather than supplying a phone model. It is a helper app-instance identity, not the original full APK identity or `Build.MODEL`. The host calls the accepted `TrustedAndroidRuntime` and `select_local_bootstrap(country_code=..., attempt_branch="initial")` factory on that exact matching-generation context. No saved-state/endpoint override is accepted. Profile source is documented in [bootstrap profile](tvt-local-bootstrap-profile.md).

Exact source runtime mapping comes from `GlobalUnit.h` importing **com.tvt.base.tool.NetworkUtils**, with the latter complete file frozen in the discovery evidence. NetworkUtils.c first tests Ethernet state CONNECTED or CONNECTING; otherwise it tests active NetworkInfo.isAvailable, Wi-Fi/type1, mobile/type0 and the exact source subtype/name table. Mapping is Ethernet5, Wi-Fi4, 2G2, 3G/4G/5G3, unknown/none0. Only source4 yields native networkFlag1. No DNS, ping, network modification or location API is used.

The host streams a bounded exact private `files/request.json` via fixed `exec-in run-as ... sh -c` with one script argv value, `umask 077; cat > files/request.json`, containing no literal wrapping quote characters. Content never enters argv, environment, logs, command receipts, or public JSON. Before launching the attempt, the host reads back the fixed private request under pre/post owned-UID checks and requires exact length, SHA-256 and byte equality with the original private packet. ADB exit0 alone is not delivery proof. Request fields are exactly `schemaVersion`, `version`, `generation`, `serial`, `countryCode`, `budgetMillis`, `greetingMillis`, `greetingBytes`, `profile`. Profile has the twelve accepted bootstrap keys. Duplicate keys, extra fields, arrays, noninteger numbers, invalid strings, generation mismatch, different app/file/SINGLE_ID/network identity, unsupported endpoints, region/country mismatch or native bounds reject before JNI. Activity verifies its current owned files path, SINGLE_ID and actual network type again immediately before bootstrap. Source country resource memberships are transcribed exactly from accepted bootstrap3.

## Attempt and status limits

Activity runs one retained JniLocalSerialDriver and accepted LocalSerialTransport generation: allocation → discover → supported type3/10001/20001 → open → bounded initial transport receive → close. Unsupported types remain private error evidence; type3,10001,20001 retain distinct numeric protocol meanings. The selected JNI callback can allocate a Java array before downstream queue bounds apply; isolated guest/process memory supervision remains Root-owned. Exact callback queue/generation and poll-vs-callback behavior comes from accepted transport8; no fabricated callbacks or open/auth status conversion is added.

Native deadlines can block inside vendor code. The Activity starts a monotonic `elapsedRealtime` watchdog before native bootstrap, with hard deadline `budgetMillis + 5000` for cleanup allowance. On expiration it starts an independent best-effort safe pending-cleanup receipt writer and immediately kills **only its own `Process.myPid()`**. The watchdog never waits for a file write or output lock; the last persisted stage may therefore precede the deadline. It never asserts native cleanup from process termination. A complete quarantined result leaves the watchdog active until this same hard deadline; Root may force-stop the owned package earlier after copying the private capture. Production Jni driver returns unproved cleanup, so expected terminal cleanup is `quarantined`, not `closed`. No echo handle, callback detail or opaque66 bytes leave the helper.

Bounded `files/result.json` contains exact schema/version/generation, safe stage/failure/type/native error, `transportOpen`, `greetingBytes`, `cleanup`, `authenticated=false`, `live=false`. Stages distinguish validation/bootstrap/discovery/open/greeting/cleanup/complete/deadline. Successful GetVersionType, open return0, connection callback and received bytes each remain below authentication. Raw bytes go only to bounded app-private `greeting.bin` and the explicit private host `device-<generation>/greeting.bin`, with matching count validation. Bytes may be partial greeting, combined initial transport packets or malformed input: no N9000 parse/auth acceptance is claimed here. The separately reviewed N9000 codec can later consume a verified complete64-byte greeting privately under Root control.

## Cleanup, privacy and verification

Root must supply isolated supervisor-owned guests and an existing Windows staging/private root with ACL limited to the current operator and SYSTEM. Python `mkdir(mode=0o700)` is not a Windows ACL enforcement mechanism. Raw requests/context/greetings are copied only beneath that explicit root and retained for Root's private follow-on protocol work. The controller removes only the known staged APK and empty unique staging directory after package absence is proved. UID changes, unreaped commands, failed force-stop/uninstall, unexpected files or changed path identity retain uncertain custody; no recursive deletes, PID/tree killing or unrelated package cleanup occur. Native direct logging can contain identifiers despite disabled wrapper logs, so native logs stay within the isolated guest; controller never forwards or clears logcat.

Focused offline checks use invented data, inert Android/JNI boundaries, the real Java transport, synthetic direct child processes, real private-file staging, and package/UID fixtures. These verify strict admission, exact regional/network/runtime mapping, fragmented bytes without sends/auth/live, root-review and private-stream custody, bounds, package ownership and failed cleanup. The author did not run Android SDK build tools, vendor JNI/native code, ADB, a real network, device, QR, password, browser, database or Git. Root independently reviews source, builds the helper, runs actual authorized serial discovery/open, and evaluates private protocol/greeting evidence. Real-device authentication, channel authorization, live decode and two-store release acceptance remain unexecuted.


## Fix1 host ownership update — 2026-10-03

Independent review found that the first controller retained uncertain child/pipe custody only on a local runner. A default API return could lose that owner, and the CLI could exit while daemon pipe threads remained unfinished. The Fix1 controller uses a process-lifetime supervisor: one default attempt owns a lease; an unresolved original runner stays retained after the bounded API return, and subsequent default attempts return `failure="host_owner_pending"`, `host_ownership="retained"` before any build or device command. Confirmed original child and all drain/feed thread completion releases the fence. This fence is within one Python process; the Root operator must keep separate CLI/orchestrator instances serialized.

Every unresolved original child and its original pipe/feed threads also have a non-daemon passive completion monitor. It observes only the retained process handle and thread completion, performs no PID lookup, replacement, pipe closure, kill retry or unrelated process action, and holds normal Python shutdown until completion. If monitor creation/start fails, the current API stack performs that same passive original-handle wait before returning; this exceptional handoff failure can exceed the usual bounded return budget. Original bounded command receipts retain `reaped=false`, timeout/kill flags and `ownershipRetained=true`; later `ownerReaped`, `ownerPipesCompleted`, `ownerExit` and completion time fields supplement that observation. Process/pipe handles, private stdin and raw stdout/stderr do not enter the private safe receipt history. `host_ownership="retained"` on a returned result describes the bounded return; subsequent natural completion does not rewrite that result or prove native/device cleanup.

Root's private Python orchestrator should use the stable passive API in its exit path:

```python
from wso_tvt_bridge.windows_local_device import run_device_probe, wait_for_default_ownership

try:
    result = run_device_probe(config, private_request)
    save_safe_operator_result(result)
finally:
    wait_for_default_ownership()
```

The CLI flushes the safe bounded result and invokes this same passive wait in `finally` before returning or propagating a print/return exception. An explicitly injected `PrivateRunner` has `wait_for_ownership()` for its original owners. A truly unfinished child/pipe can keep these waits alive indefinitely; the method makes no additional kill attempt and cannot claim completion merely because the original timeout elapsed. Normal interpreter shutdown is covered by the non-daemon owner; forced termination of the operator process and independent concurrent operator processes remain Root supervisor responsibilities.

Eight new inert causal cases demonstrate original-owner retention for an unkillable fake child, an exited child with unfinished stdout, unfinished private input feeding, both CLI lifetime modes, and normal API interpreter exit without an explicit wait, and failed monitor-thread admission. The initial five cases failed against the original source. Natural-release events complete only the original fixture handles, preserve initial receipt fields, prove passive completion, unblock later default API admission, and verify no repeated kill or private-value receipt output. This update changes only the controller, focused test and this document; the distinct Android manifest/Activity, builder, accepted transport/bootstrap and original evidence remain unchanged. Actual Android packaging, ADB/vendor/network/device discovery, authentication and media acceptance remain Root's independent gates.


## Fix2 acquired-child setup ownership update — 2026-10-03

Fix1 review kept I1 open because the initial stdout/stderr/feed worker constructors and starts occurred before the retained receipt/monitor path. Fix2 prepares an ownership obligation and safe receipt before calling Popen, binds the returned original child directly to that already-retained obligation, and protects every subsequent setup/wait/finalization path with interruption-aware custody. A failed post-spawn worker admission can no longer release the default lease with an empty receipt or unfenced original child. Stable `wait_for_default_ownership()` and the normal CLI finally path remain the Root integration interfaces.

Construction candidates are separate from proved-started I/O workers. CPython3.12's actual Thread.start admission event (`_started`) is the local proof; its full installed source is frozen in the Fix2 readset. Only admitted original workers enter the join set. A start interrupted after admission preserves that worker; a start interrupted without admission proof remains explicitly uncertain until that same original candidate supplies proof. The owner never starts/restarts a candidate itself or joins an unstarted candidate. An unresolved admission therefore keeps the default fence and normal interpreter/CLI lifetime alive rather than guessing that no worker exists.

Root authorized one first bounded termination attempt against the retained original Popen when post-spawn setup fails. `killAttempted` is set before that call; an exception or interruption cannot permit a retry, PID rediscovery or replacement-process kill. A proved-unadmitted original stdin is closed to provide EOF; a possibly started feeder is never raced by this abort. After a failed bounded kill/reap, a non-daemon owner observes only the same child, original streams and admitted workers. Initial admission exceptions and interruptions retain their safe phase/failure/started-worker receipts. Interruptions can still propagate to the caller after custody is established.

Once the original child exit and all started-worker completion are proved, original unadmitted output streams are released as unread. `ownerWorkersCompleted` and `ownerStreamsReleased` record that resource completion; `ownerPipesCompleted=false` and `ownerUnadmittedStreams` prevent claiming an unstarted output was drained. `captureIncomplete` also remains true for setup failure even when a fully admitted worker set later finishes. Failed stream release or observation keeps custody, with no close/kill retry. OS ownership completion continues to prove neither native quiescence nor authentication/media success.

Current focused Fix2 coverage consists of constructor/start/after-admission interruption cases for all three I/O streams, exact partial-worker retention, safe original receipts and default fence, normal API interpreter/CLI exit for all three failed starts, and a before-admission interruption retaining its uncertain original candidate. Only directly affected prior monitor-start and unfinished-feed checks are repeated. Source review, accepted build/Android operation and actual GetVersionType protocol-family acceptance remain Root gates. Root separately reported Windows ABI initialization/quit and two direct store transport/greeting observations; this author neither executed nor converted those separate results into local-helper type, credential, authentication or media acceptance.


## Fix3 Google30 historical package absence update — 2026-10-03

Root's first actual Google30 integration attempt stopped before staging/install/private device input because the new controller's blanket old-package substring guard rejected a legitimate Package Changes history entry for the separately removed diagnostic package. The frozen23851-byte owned dumpsys output contains one `seq=362, package=com.wso.tvt.localprobe` history row, no old/new scoped Package header, and two exact `com.wso.tvt.localdevice` absence lines. This is package-inspection evidence; it contains no device serial or credential input and proves no discovery/authentication.

The new controller's `parse_local_device_uid` exempts only an exact indented `seq=<decimal>, package=com.wso.tvt.localprobe` row inside the exact Package Changes section. Old package references in other sections, scoped headers/absence lines, malformed rows or suffix names still reject. The accepted existing custody module remains byte-identical: its exact section/absence/header/UID/contradiction grammar still validates the output after the one fixed new-package spelling substitution. Wrong/duplicate scoped packages, duplicate UID, incomplete/misplaced absences and identity contradictions remain errors. The controller catches invalid output as `package_identity`; no package ownership or cleanup permission follows from a history row.

Narrow causal tests use the full frozen real absence output and invented signed-helper/device-input fixtures. They prove legitimate history reaches real owned staging/copy and the simulated install/UID/cleanup lifecycle, and check strict negative identity/grammar cases. Author performs no ADB/build/SDK/native/network/device/secret read. Root must independently review the changed source six, issue an updated receipt, recreate accepted build custody, and retry the actual owned runtime. The prior built new APK was not installed; source/helper/device-type and credential/media acceptance remain separate gates.

## Fix4 Activity launch and private readiness update — 2026-10-03

After Fix3 acceptance, Root's two Google30 attempts installed the owned helper and established its UID, then timed out at the context phase's `am start -W`. The second safe command history records 30.016 seconds, a timed-out but reaped original child, no private stdin command, confirmed package absence and removed staging. The Activity's context branch writes its private context and immediately calls `finish()`. Waiting for UI launch/draw completion is therefore an unsuitable readiness condition. Root's separately successful Windows primitive transport/greeting observations for both stores remain independent of this Android helper's pending GetVersionType observation.

Both fixed Activity launches now use `am start -n` with the same literal component, phase and generation. This schedules the Activity without waiting for a drawn window. The existing child runner still waits for and owns the original ADB command, bounds its pipes, and rejects child timeout, unreaped ownership and output overflow. Launch stdout never establishes helper readiness.

The context phase has one monotonic 5-second observation deadline starting before its launch UID check; the attempt phase has one `budgetMillis + 10000` millisecond deadline starting before its launch UID check. Each readiness UID/read/launch command receives at most the smaller of `command_seconds` and the remaining phase time. A late successful command cannot satisfy readiness, and each polling sleep is capped by the same remaining time. The attempt allowance comprises the existing native budget, 5-second native cleanup allowance and 5-second host observation allowance. The Activity/native watchdog is unchanged. Cleanup and retained child/stream completion keep their existing independent custody rules; these phase deadlines are not promises of a strict total API return time.

Each successful private file read now has matching owned-UID observations before and after it. Context admission requires the exact current generation/schema/path/SINGLE_ID/network mapping through the existing parser and accepted resource factory before the host saves context/request or sends private stdin. Missing/empty, partial, stale-generation and invalid-schema snapshots are not admitted; polling continues only within the original phase deadline. Context expiration is `context_deadline`; result expiration is `helper_deadline`. A child that actually times out retains `child_timeout` as distinct host-command evidence. UID mismatch remains immediate `package_identity` and grants no cleanup authority over the changed package.

Result observations likewise pass the exact generation/schema and safe-status parser before updating `device`; only valid `complete` or `deadline` stages finish observation. Valid intermediate progress does not reset the deadline. Raw context, request, SINGLE_ID and greeting remain private; the fixed stdin request write, regional bootstrap factory and public API signatures are unchanged. Invalid raw snapshots and launch output are never echoed in errors or safe receipts.

Fix4 focused host verification passed 39 tests (56 deselected), including 16 readiness scenarios covering context finish/no drawn window, attempt launch, delayed creation, stale/partial/invalid snapshots, context/result deadlines, intermediate progress, UID replacement during reads and late successful reads. Fifteen isolated cases first failed against the frozen Fix3 controller; delayed file creation already passed. Ruff and strict controller mypy passed. Tests use invented artifacts and Android command responses with actual local staging/private file operations; one existing synthetic Python child check verifies private stdin/capture custody. No Android build, ADB, JDK, vendor code, network, device, credential, database, browser or Git operation was executed by the Fix4 author. Root owns independent review, a refreshed source receipt/build binding and the actual retry. Helper type/authentication/media and release acceptance remain unverified by these host tests.

## Fix5 exact private request delivery update — 2026-10-03

Root's next actual Google30 run passed asynchronous context readiness, then completed the attempt with `failure=io`, type0 and no open/greeting. Root's bounded UID-lane observation found context present but request missing: the read command returned exit0 with a missing-file diagnostic. The host's intended private request existed locally. No username/password was sent. The safe history confirms the exec-in argv contained literal single quotes around the entire script and that exit0 was accepted without controller readback. The author read only that safe history; actual private request/context values were not read.

The controller's fixed request writer now supplies the script directly as one argv value. `PrivateRunner` uses `Popen(..., shell=False)`, so shell syntax wrappers must not be embedded into that value. The fixed package and file path remain literals; the request stays on bounded private stdin. After the write command finishes, the controller reads exactly `files/request.json` with CAP4096, checks the original package UID both before and after reading, and compares length, SHA-256 and all bytes privately against the packet produced from the accepted context/factory. Missing-file diagnostics, empty/partial/changed content and stale generation cannot establish delivery. Mismatch yields safe `request_delivery` and prevents attempt launch. Child failures/overflow and UID replacement retain their existing distinct failure and cleanup rules. There is one write/readback and no automatic resend. Public APIs, Activity watchdog, source factory, custody classes and accepted dependencies remain unchanged.

Fix5 verification passed 49 focused host tests (56 deselected), Ruff and strict controller mypy. Ten new scenarios cover delivery, missing file despite exit0, partial bytes, same-length alteration, stale generation, diagnostic readback, UID replacement after write/during read, overflow and nonzero read exit. Nine cases first failed on Fix4; UID replacement after write was already rejected. The successful path uses a real retained Python child to carry Windows argv/private stdin, with a limited POSIX lexical model of outer exec-service argument escaping and inner `sh -c` tokenization. It writes invented bytes to an owned local fixture file; it does not run ADB or an Android/POSIX shell. This checks the quoted-script failure and exact readback gate under the modeled boundary. Actual exec-service delivery, helper GetVersionType and later protocol/auth/media acceptance remain Root's review/build/retry gates.
