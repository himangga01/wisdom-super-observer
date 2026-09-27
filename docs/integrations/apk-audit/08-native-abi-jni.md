# SuperLive Plus 1.18.1 native ABI and JNI coverage

This chapter audits the libraries packaged in the base APK at `C:\wso-private\superliveplus\1.18.1-2026-09-27`. It extends the [coverage baseline](00-coverage-baseline.md), [protocol inventory](02-protocol-api.md), and [media trace](03-media.md). It is static evidence: a Java call, load instruction, ELF symbol, or decompiled body does not establish a successful device or service operation. No account, device, or service was contacted.

`J:path:line` means a line in `jadx-full/sources`; `E64:lib.so@0x...` and `E32:lib.so@0x...` are **ABI-specific ELF `.dynsym` `st_value` addresses**, not APK file offsets. For ARM32 Thumb functions the low bit in `st_value` is set; disassembly starts at `st_value & ~1`. Saved arm64 Ghidra listings use an image base of `0x100000`, so subtract that base to compare a Ghidra address with an E64 value. Hashes below are SHA-256 of the extracted `apktool/lib/<ABI>` files, with byte sizes, and distinguish the exact binaries being compared.

## Packaged binaries

There are **13 arm64** and **12 armeabi-v7a** `.so` files. The sole missing arm32 counterpart is `libmmkv.so`.

| Library | arm64 bytes / SHA-256 | armeabi-v7a bytes / SHA-256 |
| --- | --- | --- |
| `libAudioCodec.so` | 250608 / `4afa8d3e261eb481a488b9d3a6f8d76be54bb7b7260fb56528a61505e8bf9e58` | 135476 / `885b028ebeda788b21f56f3d6912f3f77aeee02debc2525bc74a2290a3ba323a` |
| `libaudioNoise_reduction.so` | 117496 / `03566d2805133830920370c3e85f8edca8db69c0bee96a85c9a2ff05e6a80b75` | 73908 / `07fb1086c66db9c50e17e1ad49519da3baaf4dd6cac9e38a0639e0ad2cb39285` |
| `libc++_shared.so` | 1253544 / `cd61762848882a16c8244c964a6f396c0caa0b440588a210ce9cc4ab0e6d9f0c` | 850380 / `e7e20f6e0f3f181e853cea50373ecee2ccfe95c668dce72d0999b2469c92d0e1` |
| `libCloudStorage.so` | 7365952 / `b3623d519eb752a56e7ac35b0942bccf96e2314d3d08c46307f8aba70a2b7434` | 5178484 / `7a98a53cfdb126eb9d23fb11a8bc7465bcf6121e2f80b75c6a4f831535a6589e` |
| `libFaceDetected.so` | 108664 / `8c81b67d46754e68b979ea88aa62ce53b765e8bda8be305db2c0c0a6a4612ffd` | 67292 / `a085cafdcade7b0aec90f13aa0c8c47678de1f049c563b5d5984d6c659f0c58e` |
| `libH264Decode.so` | 8020456 / `1e7a94dcf8c9ccda33f35d9f7073b249ea44ca61de806b04b64856bf7e5e7002` | 7249544 / `6e8f266418145b6fa1c713ccd47e2f825e7803d385a6b81be81d55d83a795b84` |
| `libmmkv.so` | 717088 / `a3fea0fdcf78bda2c615d94b7131e4d53c6a4c3232963732ccc74b307298fd46` | absent |
| `libnative-crash-lib.so` | 312064 / `ccd3eac58454ea30019c08fb230d213e8d8cfd25381f1b258d93ffe6a1fbbf25` | 176312 / `0934d84f44bcad280275a144279286b25569a6decc44bde6c6b08f38b80cd877` |
| `libNatTraveral.so` | 4199472 / `b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb` | 3198404 / `89e14fb830b9c86349a8b1a3e00622ba882bf0232cb58acb2bf61fb5535fd3f6` |
| `libNetClientProtocal.so` | 3920784 / `c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717` | 3018084 / `17d44c46654752f761d8117989c0101c7662fc494a8900ca2b307de1b234f23f` |
| `libopencv_java4.so` | 23465088 / `144bbc9ad0b0bac4ba58f7d53198aead64379e5314f68200968c703d2c1c14ab` | 15622192 / `933fe7879c07fe603ce5e0f6a04298fa4b07e553c6dc83744a2779161d47e773` |
| `libOpensslSDK.so` | 2216384 / `f75b496cd491fe03233934f75e84bbf119f39754320ec1d1f13c1104fc973d34` | 1870836 / `7c169032ebd54b0f93b29a91182dcaa83c8c0bb6be9547796e7872fb196eafb4` |
| `libProtoSDK.so` | 6446688 / `b7731270d75573668cbb38a08b611a8ae2460e586181f475c4c4d7eb7cdf735b` | 4784388 / `716d8377f9293dfcdab81476a8b56e6eb756a75c2e5f13100805a972fe3739c4` |

## Loads and Java/JNI reconciliation

The count is of generated Java `native` **declarations**, including overloads; JNI export counts are of defined `.dynsym` names beginning `Java_`. A match below is a conventional name match, not a test of parameter marshalling or execution. The JNI **name sets are identical across both packaged ABIs** for all 12 paired libraries. A zero in the JNI column does not imply there is no native interface: MMKV uses registration during `JNI_OnLoad`.

| Library | Load path or dependency | Java declarations mapped to this library | JNI exports per ABI | Reconciliation |
| --- | --- | ---: | ---: | --- |
| `libAudioCodec.so` | Direct `J:com/sdk/mediacodec/AudioCodec.java:12` | 17 | 20 | All 17 names present; two export names and one extra signature variant lack Java declarations. |
| `libaudioNoise_reduction.so` | `DT_NEEDED` from `libH264Decode.so` in both ABIs; no Java load | 0 | 1 | `Java_com_sdk_test_1jni_MainActivity_stringFromJNI` has no packaged Java class. H264 imports `CreateANRHandle` and `DestroyANRHandle`; an active reduction algorithm path is unproven. |
| `libc++_shared.so` | `DT_NEEDED` from H264, audio-noise, and OpenCV in both ABIs | 0 | 0 | C++ runtime, no app JNI mapping. |
| `libCloudStorage.so` | Direct `J:com/tvt/cloudstorage/CloudStorageSDK.java:95` | 18 | 18 | All declarations have exports in both ABIs. |
| `libFaceDetected.so` | No Java load or `org.opencv.facedetect.DetectionBasedTracker` class in the generated sources | 0 | 6 | Six orphan `DetectionBasedTracker` JNI exports. Both binaries need `libopencv_java3.so`, which is absent from both APK ABI directories. |
| `libH264Decode.so` | Direct `J:com/sdk/mediacodec/H264Decode.java:79` | 117: 76 H264 + 41 `org.libsdl.app` | 124 | Seven exported `H264Decode` legacy names have no declarations; all 117 current names are present. SDL's own generic loader asks for unbundled `SDL2`/`main` (`J:org/libsdl/app/SDLActivity.java:628-649`), so the SDL exports do not establish an active SDL application. |
| `libmmkv.so` | Direct `J:com/tencent/mmkv/MMKV.java:441` on the 64-bit path | 82 | 0 | `JNI_OnLoad` dynamic registration evidence, detailed below. No arm32 binary; Java uses a non-MMKV fallback for the observed 32-bit Tyco cache path. |
| `libnative-crash-lib.so` | Direct `J:com/sdk/crashsdk/NativeCrashMonitor.java:25` | 2 | 3 | `nativeCrashInit` and `nativeSetup` match; `nativeCrashCreate` has no Java declaration and a zero-sized dynamic symbol, so its body is not established. |
| `libNatTraveral.so` | Direct `J:com/tvt/network/NatTraveral.java:26` | 18 | 18 | All names present. |
| `libNetClientProtocal.so` | Direct through constant `TAG = "NetClientProtocal"`, `J:com/tvt/network/NetClientProtocal.java:19,83` | 48 | 48 | All names present. |
| `libopencv_java4.so` | Indirect `J:org/opencv/android/StaticHelper.java:13,27`, called by `org.opencv.android.b` | 55 | 2962 | All 55 packaged OpenCV Java declarations have name matches. The other **2897 exports at name level** belong to the broader native API absent from these generated Java classes; this is not 2897 app call sites. |
| `libOpensslSDK.so` | Direct `J:com/tvt/opensslsdk/OpensslSDK.java:8` | 14 | 14 | All names present. |
| `libProtoSDK.so` | Direct in `TVTOpenSDK.java:41`, `FileSyncSDK.java:21`, `ServerListSyncSDK.java:11` | 321: 299 + 8 + 14 | 301 | **31 TVTOpenSDK signatures** lack a conventional export; 12 exports lack a Java declaration. The two `sendCmdToPTZ` declarations share one short export, leaving overload binding unresolved. |

Across the generated source, there are **693** native declarations in **25** files. **579** declarations have a name-level match to a packaged JNI export in each ABI. Of the other **114**, **82** are MMKV dynamic-registration candidates, **31** are unresolved `TVTOpenSDK` signatures, and **one** is `com.google.android.gms.tasks.NativeOnCompleteListener.nativeOnComplete`, for which this APK has no conventional export; its Play-services context does not identify an APK library. Each paired ABI has **3515** `Java_` exports; **2926** have no name-level declaration in the generated Java. Large OpenCV export surface accounts for 2897 of these. Name-level matching can map several overloaded exports to one declaration, so these two totals must not be subtracted as though they were one-to-one signature counts.

The 31 unresolved `TVTOpenSDK` signatures cover **25 distinct names**: `closePlayback`, `closePlaybackStream`, `closeRealPlayStream`, `connectDevice`, `disConnectDevice`, `getConnectStatus`, `getDeviceRecordChl`, `getDeviceRecordDate`, `getDeviceRecordLog`, `getPlaybackRecordChl`, `getPlaybackRecordDate`, `getPlaybackRecordLog`, `openPlayback`, `openPlaybackStream`, `openRealPlayStream`, `playbackAudioSwitch`, `realPlayAudioSwitch`, `registerDevStatusNotify`, `seekPlayback`, `seekPlaybackStream`, `sendCmdToGetKeyFrame`, `sendCmdToPlaybackAllFrame`, `sendCmdToPlaybackByFrameIndex`, `sendCmdToPlaybackKeyFrame`, and `sendCmdToSnapShot`. See the signature-level [protocol table](02-protocol-api.md#native-declaration-and-jni-export-inventory). No saved Ghidra evidence establishes dynamic registration for these 25 names. The 12 excess `libProtoSDK.so` exports are 11 legacy `TVTOpenSDK` names listed in the [protocol inventory](02-protocol-api.md#exported-jni-names-without-a-java-declaration), plus `ServerListSyncSDK.GetLastErr` (`E64:libProtoSDK.so@0x2b5798`, `E32:libProtoSDK.so@0x1e3937`).

Other excess names are `AudioCodec.G711_EncodeOneAudio(byte[],int,int)` (a mangled long export; Java declares only the two-argument form), `G711_EncodeOneAudioEx`, and `G711_DncodeOneAudioEx`; `H264Decode.DecodeOneARGBFrame`, `DecodeOneRGBFrame`, `GetDecodeResult`, `GetStepHandle`, `YUV2RGB`, `H2Save`, and `RGB2Save`; `nativeCrashCreate`; the six FaceDetected entries; and the audio-noise sample JNI entry. The OpenCV 2897 count is deliberately a **name-level** excess count: its overloaded long-name exports require signature matching before claiming an exact count of unusable overloads.

### Dynamic registration and ABI-specific holes

`libmmkv.so` has no conventional `Java_` exports, but its arm64 binary contains `com/tencent/mmkv/MMKV`, all **82** Java native method names as NUL-terminated strings, and `JNI_OnLoad` at `E64:libmmkv.so@0x448e0` (956 bytes). In that body, the instruction at `0x44a18` loads a JNIEnv function-table entry at `0x6b8`, the JNI `RegisterNatives` slot, followed by an indirect call at `0x44a1c`. This is direct evidence of a registration mechanism, although this audit has not individually validated all 82 registered signatures/pointers. `J:defpackage/zm1.java:22` initializes MMKV; `J:defpackage/kw.java:44-52,60-66` selects MMKV in a 64-bit process and a preferences fallback in a 32-bit process. Other MMKV users and process modes were not runtime-tested.

The FaceDetected dependency is a separate packaging gap: both `libFaceDetected.so` copies specify `DT_NEEDED: libopencv_java3.so`, while only `libopencv_java4.so` is packaged. No `FaceDetected` load string occurs in other packaged arm64 libraries or the generated Java sources. The app's visible face-search camera path instead checks `org.opencv.android.b.b()` and calls `FaceDetectorYN`/`CascadeClassifier` through OpenCV 4 (`J:com/tvt/search/view/d.java:85,160-186,236-242`; `J:org/opencv/android/StaticHelper.java:13-27`). This establishes a distinct reachable Java path; it does not prove camera permission, model loading, or face-detection results.

## Verified entry examples and active Java paths

These examples anchor the less-covered libraries to **both** binaries. An address is an entry point, not a claim that its body was decompiled.

| Boundary and Java evidence | E64 | E32 | What the Java path establishes |
| --- | --- | --- | --- |
| `CloudStorageSDK.PlayCreate` (`J:com/tvt/cloudstorage/CloudStorageSDK.java:120,169-177`) | `libCloudStorage.so@0x1f28ec` | `libCloudStorage.so@0x1775e9` | `CloudPlayerActivity.java:2664-2685` and `com/tvt/backup/b.java:369-394` create cloud playback/download tasks, seek, and register callbacks. Cloud packet transport/decryption internals are opaque here. |
| `CloudStorageSDK.DownloadPic` (`CloudStorageSDK.java:102,138-141`) | `libCloudStorage.so@0x1f2a70` | `libCloudStorage.so@0x1776c9` | `CloudPlayerActivity.java:1201-1206` requests a cloud picture task. A successful image result remains unverified. |
| `AudioCodec.G711_Initialize` (`J:com/sdk/mediacodec/AudioCodec.java:18-24`) | `libAudioCodec.so@0x140f4` | `libAudioCodec.so@0xb939` | `cw3.java:411-412`, `ku3.java:2365`, and `com/tvt/backup/a.java:211-214` construct G.711/ADPCM codec wrappers; the Java wrapper chooses G.711, ADPCM, or G.726 methods by its mode. Actual stream codec selection is a runtime question. |
| `OpensslSDK.AESDecryptECBWithoutMD5` (`J:com/tvt/opensslsdk/OpensslSDK.java:28`) | `libOpensslSDK.so@0x91fa4` | `libOpensslSDK.so@0x5a065` | Account packet paths call decrypt and CRC (`J:defpackage/ku3.java:3686-3691`; `ew3.java:4456-4461`); share-device QR paths call AES/CRC (`J:com/tvt/dev_share/ShareDeviceUtils.java:97-138`). Neither key derivation nor protocol security is established by the wrapper. |
| `NativeCrashMonitor.nativeCrashInit` (`J:com/sdk/crashsdk/NativeCrashMonitor.java:90-106`) | `libnative-crash-lib.so@0x20970` | `libnative-crash-lib.so@0x14015` | Application startup calls `qe0.a.d(this)` (`J:com/tvt/launch/LaunchApplication.java:387`), which constructs and initializes the monitor (`J:defpackage/qe0.java:120-128`). Crash interception/reporting behavior is not decompiled or tested. |
| `FaceDetectorYN.create_11` (`J:org/opencv/objdetect/FaceDetectorYN.java:23`) | `libopencv_java4.so@0x71c4d4` | `libopencv_java4.so@0x47e995` | The search camera view passes an embedded model buffer and input size to the OpenCV 4 wrapper (`J:com/tvt/search/view/d.java:153-165`). This is separate from the orphan `libFaceDetected.so`. |

`libaudioNoise_reduction.so` has no app Java call site. Its role is narrower but verifiable: H264 has `DT_NEEDED: libaudioNoise_reduction.so`, and its undefined symbol table imports `CreateANRHandle` and `DestroyANRHandle` from exports in that library. This establishes a native link relationship, not whether noise reduction runs on a particular media session. `libc++_shared.so` is a linked runtime dependency, not an app JNI entry surface.

## Confirmed stubs and body coverage

The five `TVTOpenSDK` NAT entries below are **zero-return stubs in both ABIs**. Arm64 disassembly is `mov w0, wzr; ret` (8 bytes); ARM32 Thumb is `movs r0, #0; bx lr` (4 bytes). Ghidra independently decompiled the arm64 bodies in `ghidra-paths.txt` and `ghidra-proto-more.txt`. Their Java routes therefore cannot be treated as implemented transport merely because the JNI symbol exists.

| Stub | E64 `libProtoSDK.so` | E32 `libProtoSDK.so` |
| --- | --- | --- |
| `natConnectDevice` | `0x280004` | `0x1c3d85` |
| `natDisConnectDevice` | `0x28000c` | `0x1c3d89` |
| `natOpenLiveVideo` | `0x280014` | `0x1c3d8d` |
| `natCloseLiveVideo` | `0x28001c` | `0x1c3d91` |
| `natLiveAudioSwitch` | `0x280024` | `0x1c3d95` |

The excess `TVTOpenSDK.tokenLogin` entry is also a bare return (`E64:libProtoSDK.so@0x272aa0`, `E32:libProtoSDK.so@0x1bc069`); it has no packaged Java declaration and does **not** set a defined return value. Short entries in other libraries were checked before labeling stubs: for example, `CloudStorageSDK.Stop` at E64 `0x1f2834` and `OSSResetTokenInfo` at `0x1f2bd8` are branch trampolines, not one-instruction no-ops. Tiny NetClient and ServerListSync entries likewise branch to implementations.

The saved Ghidra text contains **37 successfully decompiled selected functions** across **four arm64 libraries**: 14 in ProtoSDK (`ghidra-paths.txt`, `ghidra-proto-more.txt`), 11 in NetClientProtocal (`ghidra-net-paths.txt`), 7 in NatTraveral (`ghidra-nat-paths.txt`), and 5 in H264Decode (`ghidra-decode-paths.txt`, including `JNI_OnLoad`). That is **36 JNI entry bodies plus one `JNI_OnLoad`**, not comprehensive native-code coverage. These saved bodies cover selected login/callback/NAT stub, connection/live/talkback, NAT traversal, and decoder initialization/frame paths; the protocol and media reports give their call details. **No saved Ghidra bodies** cover CloudStorage, AudioCodec, OpensslSDK, FaceDetected, audioNoise_reduction, MMKV, native-crash-lib, OpenCV, or the C++ runtime. MMKV registration and the stubs above have separate ELF/disassembly checks in this chapter. All arm32 behavior beyond the explicit symbol/short-stub checks remains opaque; equal JNI name sets do not imply identical implementations.

The most material remaining native gaps are CloudStorage task, token, and decrypt internals; audio codec and noise-reduction processing; OpenSSL wrapper semantics; crash-monitor behavior; MMKV's full registration table and storage behavior; OpenCV face model execution; and the unresolved `TVTOpenSDK` methods. Device, account, server, camera, and media outcomes require separately authorized runtime observation. This audit makes no web-service equivalence claim.

## Reproduction notes

Enumerate `apktool/lib/{arm64-v8a,armeabi-v7a}/*.so`; hash the complete file bytes; parse each `.dynsym` for **defined** `Java_*` and `JNI_OnLoad` symbols and `.dynamic` for `DT_NEEDED`. Extract `native` declarations and `System.loadLibrary` calls from all 19,116 generated Java files; mangle package/class/method names using JNI's `_1` escape for underscores and compare short names and overload suffixes. Inspect the 25 declaration-bearing files, especially the three `libProtoSDK.so` wrappers. Cross-check `libmmkv.so`'s `JNI_OnLoad`, 82 method strings and registration call; decode short functions in both ABIs before calling them stubs. The private scratch inventory `native_audit.py`/`native_audit.json` beside the APK records the raw comparison but is not part of this repository. JADX's **391** reported errors and decompiler type warnings still limit call-site completeness; declarations, exports, decompiled bodies, and runtime results remain separate evidence levels.
