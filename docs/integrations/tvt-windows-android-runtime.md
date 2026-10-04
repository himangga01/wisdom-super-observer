# TVT Windows Android development runtime

Verified on 2026-10-03. A Windows-hosted official Android Emulator now boots Android 11 and advertises ARM32 and ARM64 translation. This provides a development environment for the source-reviewed TVT helper without requiring a physical phone.

## Verified environment

| Item | Observed value |
| --- | --- |
| Host | Windows 11 Pro, 10.0.26200, AMD Ryzen 5 7500F, approximately 16 GB physical RAM |
| SDK | `C:/Android` |
| Existing JDK | `C:/Android/tools/jdk-21.0.12.1+1` |
| Emulator | 37.2.12.0, official stable build 16428233 |
| Image | `system-images;android-30;google_apis;x86_64`, revision 16 |
| Acceleration | `WHPX(10.0.26200) is installed and usable`; QEMU reports operational WHPX |
| AVD | `wso_w04_api30_20261003` |
| Owned storage | `C:/Android/owned/wso-w04-20261003` |
| Resource configuration | 2 guest CPU cores, 2048 MB guest RAM, 720 × 1280, software GPU |
| ADB server | `127.0.0.1:5038` |
| Emulator serial | `emulator-5580` |
| Emulator console / transport | 5580 / 5581, observed IPv4 and IPv6 loopback bindings |

Guest evidence: `sys.boot_completed=1`, release `11`, SDK `30`, `ro.product.cpu.abilist=x86_64,x86,arm64-v8a,armeabi-v7a,armeabi`, `ro.dalvik.vm.native.bridge=libndk_translation.so`, and `ro.enable.native.bridge.exec=1`. Both `/system/lib/libndk_translation.so` and `/system/lib64/libndk_translation.so` exist. The engine reports `Boot completed in 36757 ms`. Guest fingerprint is `google/sdk_gphone_x86_64/generic_x86_64_arm64:11/RSR1.240422.006/12134477:userdebug/dev-keys`.

## Local launch and control

The ignored task supervisor is `.superpowers/runtime/windows-android/supervise.ps1` in the project checkout. It creates an isolated loopback ADB server, launches the owned AVD hidden, retains the original emulator process handle, writes `control.json`, and waits for `stop.request`. It refuses to start when an owned port is already occupied. Run it with the existing PowerShell executable and `-NoProfile -File`, using `Start-Process -WindowStyle Hidden` for background execution. Do not launch another instance while this one is running. `control.json` records the exact current process IDs, timestamps, arguments, ports, and cleanup request path.

The emulator command used is:

```powershell
& 'C:/Android/emulator/emulator.exe' -avd wso_w04_api30_20261003 -datadir C:/Android/owned/wso-w04-20261003/data -ports 5580,5581 -no-window -no-audio -no-snapshot -no-boot-anim -accel on -gpu software -cores 2 -memory 2048 -camera-back none -camera-front none -no-metrics -verbose
```

Before launch, the supervisor sets `ANDROID_HOME` and `ANDROID_SDK_ROOT` to `C:/Android`, `ANDROID_USER_HOME` to the owned `home` folder, `ANDROID_AVD_HOME` to the owned `avd` folder, and `ANDROID_ADB_SERVER_PORT=5038` in its own process environment. It starts ADB using `adb -L tcp:localhost:5038 start-server`, then sets `ADB_SERVER_SOCKET=tcp:127.0.0.1:5038`. The literal `localhost` in the ADB start command is necessary: this installed ADB treats `127.0.0.1` as a remote start target and refuses it. All observed listener addresses are still loopback.

The engine uses userdata/cache/encryption images in the owned AVD directory despite the requested `-datadir` argument. The actual QEMU arguments are recorded in `emulator.stdout.log`; all mutable disk paths remain under the owned storage root. An additional ephemeral QEMU listener was observed at port 51281, also on loopback. No host redirection or public gRPC listener was requested.

Use explicit ADB host, server port, and serial for every device command:

```powershell
& 'C:/Android/platform-tools/adb.exe' -H 127.0.0.1 -P 5038 -s emulator-5580 shell getprop sys.boot_completed
& 'C:/Android/platform-tools/adb.exe' -H 127.0.0.1 -P 5038 -s emulator-5580 shell getprop ro.product.cpu.abilist
```

To request cleanup, create the supervisor's `stop.request` file in the ignored runtime folder. It verifies the owned AVD name before issuing the targeted emulator stop command; its retained original process handle bounds fallback termination to the owned process tree. It stops only the ADB server whose port owner still matches its recorded PID. Wait for `control.json` to record `status=stopped`. For a subsequent launch, remove only the owned stop request after confirming shutdown. Never stop the default ADB server or terminate processes by name. The pre-existing ADB PID 22104 on port 5037 was left running.

## Installation provenance and licensing

Installed with the existing `sdkmanager.bat`, child-local `JAVA_HOME`, and the previously accepted `android-sdk-license`. The invocation supplied `n` to any new prompt, never an automatic acceptance. The license file SHA-256 remained `70FD2713CA385FD6B14C1D5577CE8349996699186A3A216E9643A09098C26DCA`. No Windows feature change, administrator driver installation, restart, firmware change, or host security change was performed. The read-only Windows optional-feature query required elevation; the emulator's successful acceleration check supplies direct WHPX evidence.

| Official archive | Size in repository metadata | Official SHA-1 |
| --- | --- | --- |
| [emulator-windows_x64-16428233.zip](https://dl.google.com/android/repository/emulator-windows_x64-16428233.zip) | 455342868 bytes | `488ed747e82de7e9bb5247becd1ac043c7e5e85d` |
| [x86_64-30_r16.zip](https://dl.google.com/android/repository/sys-img/google_apis/x86_64-30_r16.zip) | 1438186618 bytes | `6ae21030eaadc041078444d3798e4b399f3e787d` |

Repository metadata and selected packages are preserved in the ignored runtime directory. SDK Manager completed installation with exit 0. Download archives were not retained or independently rehashed; `installed-file-manifest.json` contains independently calculated SHA-256 values for installed engine, image, package metadata, and AVD configuration files.

Google's [ARM translation announcement](https://android-developers.googleblog.com/2020/03/run-arm-apps-on-android-emulator.html) limits this translation technology to application development and debugging and prohibits provision of commercial hosted services. Therefore this VM is a development validation route. A production hosted provider requires an independently permitted runtime or vendor Windows SDK; boot success establishes no production licensing or operational acceptance. The [emulator release notes](https://developer.android.com/studio/releases/emulator) document API 30 x86_64 ARM32/ARM64 support and known ARMv7 compatibility limits; [hardware acceleration guidance](https://developer.android.com/studio/run/emulator-acceleration) documents WHPX and software GPU modes.

## Verification boundaries

This setup verifies an actual Android boot, ARM ABI advertisement, native bridge configuration/file presence, and loopback host listeners. No SuperLivePlus APK was installed or started, and no vendor `.so`, source-reviewed helper probe, account login, QR credential, SID acquisition, device authentication, video, audio, or production performance test was executed by this setup task. A separately reviewed helper binary and exact hash must precede vendor library loading. `MATCHED=0` and release readiness remain false.

Logs contain nonfatal Vulkan/Steam manifest warnings and an AVD Manager `devices.xml` warning. The selected image and headless guest boot nevertheless completed. These logs are retained for diagnosing graphics or native execution issues; successful boot alone does not resolve library compatibility or media behavior.

The detailed setup report and READY marker are `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-windows-android-runtime-report.md` and `W04-windows-android-runtime-READY.json`. Runtime evidence is under `.superpowers/runtime/windows-android`.
