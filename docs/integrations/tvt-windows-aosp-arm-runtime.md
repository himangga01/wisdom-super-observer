# Windows AOSP ARM runtime

Analysis date: 2026-10-03. Source baseline at investigation start: `36fc954e4754d69721596e190c35f9cf14de3e4c`. Canonical execution report: `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-windows-aosp-arm-runtime-report.md`.

An official **default/AOSP Android 7.0 API 24 ARM32 guest booted on this Windows x86_64 host**, using the installed Android Emulator 37.2.12 Windows `qemu-system-armel-headless.exe` engine. The proof uses full ARM CPU emulation, software graphics, one guest CPU and 1024 MB guest RAM. Guest boot completion, Android services, ARM ABI and a disabled native bridge were verified. ARM64 attempts failed and are retained in the report.

This establishes a Windows ARM32 Android runtime. TVT native loading, authentication, device access, media/video throughput, unattended recovery and production licensing remain separate acceptance gates. No TVT library, helper or APK was executed by this environment task. An APK minimum API of 21 does not establish a particular ELF library's API 24 compatibility.

## Exact verified environment

| Item | Evidence |
|---|---|
| Host | Windows x86_64, AMD Ryzen 5 7500F |
| Emulator | Existing 37.2.12, build 16428233 |
| Engine | `C:/Android/emulator/qemu/windows-x86_64/qemu-system-armel-headless.exe` |
| Official image | `system-images;android-24;default;armeabi-v7a`, revision 7 |
| Guest build | Android 7.0, `NYC/3245079`, image build 2016-09-02; security patch 2016-09-06 |
| Guest kernel | Linux 3.10.0+, `armv7l` |
| Guest ABIs | `armeabi-v7a,armeabi`; no ARM64 ABI |
| Guest bridge | `ro.dalvik.vm.native.bridge=0`; checked Houdini/NDK translation library globs absent |
| Boot observation | `sys.boot_completed=1` twice; `init.svc.bootanim=stopped`, `zygote32` running; activity/package services present |
| Timing | Verified 2026-10-03 03:55:35 UTC, about 169 seconds after launch; a single boot observation, not a performance benchmark |
| Owned ADB | `127.0.0.1:5039`, process 30316 at proof time |
| Owned guest controls | Console 5590 / ADB device 5591, IPv4 and IPv6 loopback only, engine process 31792 |
| Original supervisor | Process 24196; retains original foreground ADB and engine `Process` objects/handles |

The top-level `emulator.exe` rejects ARM targets on this host. The packaged ARM engine was invoked directly through its own Android AVD parser with the official image's `kernel-ranchu`. Reference AOSP engine source defines ARM/Cortex-A15/Ranchu handling. Actual kernel boot and an ELF32 `EM_ARM=40` guest libc read validate the image/engine combination. The host engine PE machine is AMD64 `0x8664`. Acceleration was disabled; generated QEMU arguments select Cortex-A15/Ranchu without an x86 hypervisor accelerator.

## Ownership and control

Owned files are under `C:/Android/owned/wso-w04-aosp-arm-20261003`; isolated AVD and user homes are there. Command lines, complete engine logs, property reads, hashes, NOTICE files, attempt receipts and process observations are retained in ignored `.superpowers/runtime/windows-aosp-arm/`.

The successful guest remains running for a separately reviewed probe. To stop it, write `.superpowers/runtime/windows-aosp-arm/stop.request` in this checkout. The original supervisor verifies the exact AVD identity, requests `adb -H 127.0.0.1 -P 5039 -s emulator-5590 emu kill`, and after a bounded wait terminates only its retained original engine handle if necessary. Its original ADB handle is also stopped. It never discovers a process to terminate by name, port or PID lookup. The 900-second boot budget was cleared only after the recorded boot acceptance; subsequent cooperative stop remains available.

The older Google API 30 VM on 5038/5580/5581 was observed running during this proof and was not controlled by this task. Product source, Git state, AGENTS, database, browser and existing source packets were not changed by this environment task.

## Provenance and permissions

The image came from the [official default image repository](https://dl.google.com/android/repository/sys-img/android/sys-img2-3.xml). The retained [API 24 official archive](https://dl.google.com/android/repository/sys-img/android/armeabi-v7a-24_r07.zip) is 283,677,512 bytes, SHA-1 `3454546b4eed2d6c3dd06d47757d6da9f4176033`, SHA-256 `42690977fe4b97b0643da11a2b42742b2e3d5b8849dcdd6893e0b92d6618c91d`. Its SHA-1 exactly matches repository metadata. Installed image files and component notices were independently hashed.

SDK Manager supplied `n` to additional terms. The existing `android-sdk-license` file SHA-256 stayed `70fd2713ca385fd6b14c1d5577ce8349996699186a3a216e9643a09098c26dca`. No administrator feature, driver, reboot, global environment or host security change was made.

The [SDK terms, section 3.5](https://developer.android.com/studio/terms), distinguish components governed by open-source licenses. The emulator notices identify QEMU GPL terms and other component licenses; its CSV maps 46 notice entries to the ARM headless engines, including a `CC-PDDC OR UNKNOWN` libselinux label. Microsoft runtime redistributables have their own notice entry. The supplied system-image NOTICE is retained. This inventory does not establish that every downloaded component is covered by the same license, corresponding-source compliance for a redistributed build, or permission to operate/distribute the complete TVT service.

## Remaining gates

- Review whether Android API 24 and its old security baseline are acceptable for the intended server deployment.
- Inspect the selected TVT ELF's actual ABI, Android symbol/API and dependency requirements; then authorize and execute a bounded native load probe separately.
- Resolve ARM64 guest ART crashes if ARM64 is required. API 25 ARM64 reached ADB but repeatedly crashed zygote64; API 26 failed before kernel boot on incompatible HDA/PCI configuration.
- Verify real device authentication, media/video behavior, performance, isolation, recovery and service integration.
- Complete component-specific licensing and TVT permission evidence before claiming production use is cleared.
