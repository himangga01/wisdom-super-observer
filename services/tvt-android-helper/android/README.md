# Android load-only diagnostic

This private diagnostic packages the unchanged, accepted `NetClientProtocal` binary class and the accepted native libraries for `arm64-v8a` and `armeabi-v7a`. Its distinct package is `com.wso.tvt.loadprobe`, with minimum API 26 and target API 36. It requests no permissions, including no `INTERNET` permission. Its single exported activity has no intent filter and is intended for an explicitly scoped diagnostic launch.

The activity calls only `NetClientProtocal.loadOnAndroid()`, then compares the complete reflected inventory of 48 native methods and 12 callback methods, including modifiers, with the unchanged `tests/apk-descriptors.txt` asset. It never creates a native driver, invokes native methods or callbacks, accepts configuration or credentials, or reads intent extras. The UI and `WsoTvtLoadProbe` log tag contain fixed redacted results. Unsupported ABI, missing library and dependency/linkage failures remain failures.

## Build locally

Use PowerShell 7 from the repository root:

```powershell
pwsh -NoProfile -File ./services/tvt-android-helper/build-load-probe.ps1
```

The script uses only the existing JDK at `C:/Android/tools/jdk-21.0.12.1+1`, Android API jar at `C:/Android/platforms/android-36/android.jar`, and Build Tools at `C:/Android/build-tools/36.0.0`. It needs no Gradle, download, SDK installation, or global environment changes. Java sources compile for Java 8, and D8 targets minimum API 26.

Before and after packaging, the accepted 20-file helper receipt is checked. Only the staged native files in the ignored `build/native` directories are packaged, after their exact accepted sizes and SHA-256 values pass. The approved descriptor asset is copied unchanged. A fresh unique directory under ignored `build/load-probe-<id>` retains the APK, compiler/package/signature/alignment/manifest captures and `build-result.json`.

Each build generates a DEVELOPMENT signing key with a cryptographically generated password passed through the child process environment. No secret value is placed in command arguments, logs or source. The key is deleted after signing, including signing failure. The CLI build process is repeatable; signed APK bytes vary because each build uses a fresh development certificate and ZIP timestamps. Outputs are private and ignored by Git.

The build verifies APK signing and ZIP alignment, inspects the packaged manifest, and verifies the descriptor asset and both native entry hashes. It performs no ADB command, install, launch, or native startup. Any later device operation requires the separately approved device gate and must use the exact reviewed APK hash.

## Interpretation

An actual device `LOAD_ONLY_PASS` would establish that the library loaded on that Android runtime and the reflected inventory matched. It does **not** establish JNI binding invocation, native initialization/startup, callback forwarding, credentials, networking, context propagation, transport, or feature parity. A successful host build does not establish even device loading. Do not classify this diagnostic as service or feature acceptance.
