# SuperLive Plus 1.18.1 핵심 연동 경로 정적 분석

분석일: 2026-09-27. 범위: 사용자가 USB 디버깅을 승인한 Android 기기에 설치된 `com.tvt.superliveplus`의 APK와 포함된 네이티브 라이브러리 중 **서비스 연동에 우선 필요한 로그인·채널·영상·알람·Talk 경로**. 이 문서는 구현 계획의 T00A 산출물이지 APK 전체 기능의 전수 분석이 아니다. 전체 기능 감사는 [별도 기준선](apk-audit/00-coverage-baseline.md)과 기능별 보고서에서 진행한다. 실제 TVT 계정·DVR 접속 성공이나 프레임·알람 수신을 뜻하지 않는다. 핵심 경로는 [TVT 호출 맵](tvt-call-map.md)에 있다.

## ApkAnalysisManifest

| 항목 | 확인 결과 |
| --- | --- |
| 앱 | SuperLive Plus, package `com.tvt.superliveplus`, `versionName=1.18.1`, `versionCode=20267` |
| 설치 범위 | `adb shell pm path`에서 기본 APK 1개, split APK 없음 |
| 기기 범위 | Android 16, `arm64-v8a` Samsung 휴대폰. 기기 일련번호는 보관·기록하지 않음 |
| SDK 범위 | `minSdk=24`, `targetSdk=35`; Manifest의 `android:debuggable=false` |
| 기본 APK | 170,064,551 bytes; SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281` |
| DEX | `classes.dex`부터 `classes7.dex`까지 7개. 주요 `com.tvt` 래퍼는 `classes4.dex`~`classes6.dex`에 있음 |
| ABI | `arm64-v8a` 13개 `.so`, `armeabi-v7a` 12개 `.so`. `libmmkv.so`는 이 APK에서 arm64에만 있음 |
| 도구 | ADB 37.0.1, JADX CLI 1.5.6, Apktool 3.0.3, Ghidra 12.1.4, Temurin JDK 21.0.12.1+1 |
| 원본 보관 | APK, 추출 ELF/DEX, JADX·Apktool 결과, Ghidra 프로젝트와 로그는 Git 작업공간 밖 `C:\wso-private\superliveplus\1.18.1-2026-09-27`에 보관 |

선택한 arm64 라이브러리의 SHA-256은 아래와 같다. JNI 오프셋은 같은 해시의 바이너리에서만 유효하다.

| 라이브러리 | SHA-256 |
| --- | --- |
| `libProtoSDK.so` | `b7731270d75573668cbb38a08b611a8ae2460e586181f475c4c4d7eb7cdf735b` |
| `libNetClientProtocal.so` | `c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717` |
| `libNatTraveral.so` | `b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb` |
| `libH264Decode.so` | `1e7a94dcf8c9ccda33f35d9f7073b249ea44ca61de806b04b64856bf7e5e7002` |
| `libAudioCodec.so` | `4afa8d3e261eb481a488b9d3a6f8d76be54bb7b7260fb56528a61505e8bf9e58` |

ABI별 파일 목록: `libAudioCodec.so`, `libCloudStorage.so`, `libFaceDetected.so`, `libH264Decode.so`, `libNatTraveral.so`, `libNetClientProtocal.so`, `libOpensslSDK.so`, `libProtoSDK.so`, `libaudioNoise_reduction.so`, `libc++_shared.so`, `libnative-crash-lib.so`, `libopencv_java4.so`; arm64에만 `libmmkv.so` 추가. 철자는 APK에 기록된 그대로다.

## 분석 절차와 증거 위치

1. ADB에서 설치 패키지 경로·버전·ABI를 확인하고 기본 APK를 복사했다. 원본 해시를 다시 계산했다. 휴대폰의 앱 데이터, 로그인 토큰 및 일련번호는 추출하지 않았다.
2. Apktool로 Manifest/리소스를 해석했고, JADX CLI로 Java/Kotlin 선언과 호출 지점을 읽었다. 주요 래퍼 파일은 `com/tvt/protocol_sdk/TVTOpenSDK.java`, `com/tvt/network/{NetClientProtocal,NatTraveral,Frame}.java`, `com/sdk/mediacodec/{H264Decode,AudioCodec}.java`다. JADX 전체 실행은 외부 Kotlin·코루틴 등에서 391개 메서드 오류를 냈으므로, 본 문서에는 실제로 읽힌 경로만 근거로 사용한다.
3. Windows에 binutils가 없어 ELF64 `.dynsym`을 직접 읽는 파서로 JNI 내보내기·오프셋을 조사하고 Ghidra headless에서 arm64의 `libProtoSDK.so`, `libNetClientProtocal.so`, `libNatTraveral.so`, `libH264Decode.so`의 함수 참조와 문자열을 분석했다. 핵심 JNI 의사코드는 외부 보관 위치의 `ghidra-paths.txt`, `ghidra-proto-more.txt`, `ghidra-net-paths.txt`, `ghidra-nat-paths.txt`, `ghidra-decode-paths.txt`에 있다. 네 라이브러리의 분석·저장은 성공했으며 Ghidra 예외 처리기/역어셈블러 경고도 로그에 남았다. 함수 주소는 ELF `st_value`이며 이 Ghidra 프로젝트의 로드 주소에는 `0x100000`이 더해져 표시된다.
4. 증거 표기 `J:<경로>:<줄>`은 위 외부 보관 위치의 `jadx-full/sources` 아래 파일, `G:<심볼>@<오프셋>`은 Ghidra 프로젝트와 `ghidra-paths.txt`, `E:<심볼>@<오프셋>`은 ELF 동적 심볼을 뜻한다. 생성된 Java 줄 번호는 이 도구 버전의 산출물에 한정된다.

Manifest에는 `INTERNET`, `RECORD_AUDIO`, `CAMERA`, `POST_NOTIFICATIONS` 권한 및 FCM 수신 컴포넌트가 있다. 권한 선언만으로 해당 기능의 동작은 입증되지 않는다.

## 확인된 구조

- 계정/목록/알람 요청: `TVTOpenSDK.request(route, JSON, callback)`가 UUID로 콜백을 등록하고 `TVTRequesterImpl`의 요청 클래스를 호출한다. `UserLoginRequest`, `GetAccountChannelListRequest`, `GetDeviceAlarmListPageRequest`가 JSON을 필드로 분해해 `TVTOpenSDK`의 JNI 메서드로 넘긴다. 네이티브 `userLogin`, `getAccountChannelList`, `getDeviceAlarmListPage`는 각 `*Reply` 이름과 `HttpTransCallback`을 사용한다. `TVTOpenSDK.getCallback`은 UUID 항목을 제거한 뒤 `TVTOpenCallback.reply(route, response)`를 호출한다. 근거: `J:com/tvt/protocol_sdk/TVTOpenSDK.java:2797`, `J:com/tvt/protocol_sdk/request/UserLoginRequest.java:60`, `J:com/tvt/protocol_sdk/request/GetAccountChannelListRequest.java:28`, `J:com/tvt/protocol_sdk/request/GetDeviceAlarmListPageRequest.java:42`, `G:Java_com_tvt_protocol_1sdk_TVTOpenSDK_userLogin@0x2810a8` 등.
- 네이티브 SDK 생명주기: `TVTOpenSDK.init`는 설정된 HTTP/NAT 주소로 `startProtoManagerServer`를 호출하고 `registerCallback`을 설치한다. `destroy`는 `stopProtoManagerServer`를 호출한다. `startProtoManagerServer`의 Ghidra 호출 목록에는 `Init`, 로그 콜백 설치 및 SDK 싱글턴 접근이 있다. 근거: `J:com/tvt/protocol_sdk/TVTOpenSDK.java:2475-2496`, `J:com/tvt/protocol_sdk/TVTOpenSDK.java:1046`, `G:Java_com_tvt_protocol_1sdk_TVTOpenSDK_startProtoManagerServer@0x270ea0`.
- 전송 경로는 복수다. `TVTOpenSDK`의 `natConnectDevice`, `natDisConnectDevice`, `natOpenLiveVideo`, `natCloseLiveVideo`, `natLiveAudioSwitch`는 이 `libProtoSDK.so`에서 각각 즉시 `0`을 반환하는 짧은 구현으로 확인했다. 내보낸 `tokenLogin` 심볼도 본문이 비어 있고 이 Java 클래스에서 대응 선언을 찾지 못했다. 해당 선언이나 라우트 문자열만으로 NAT 영상·토큰 로그인 지원을 주장할 수 없다. 별도 `NetClientProtocal` 래퍼는 토큰으로 연결하고 live task ID를 반환하며, 앱의 `ServerIPCAccount`/`ServerNVMSAccount` 클래스에서 실제 호출 지점이 확인된다. 근거: `G:Java_com_tvt_protocol_1sdk_TVTOpenSDK_natConnectDevice@0x280004`, `G:Java_com_tvt_protocol_1sdk_TVTOpenSDK_natOpenLiveVideo@0x280014`, `G:Java_com_tvt_protocol_1sdk_TVTOpenSDK_natLiveAudioSwitch@0x280024`, `J:defpackage/ku3.java:2167,4053,8121`.
- Ghidra에서 `NetClientProtocal.ConnectDevByToken`은 `Net_Client_Protocal_ConnectDevByToken`, live 시작/종료는 `Net_Client_Protocal_RequestLiveStream`/`Close_LiveStream`, Talk 시작/송신/종료는 각 `Net_Client_Protocal_*TalkBack*`로 이어진다. Talk 송신 JNI는 Java 배열에서 지정 길이만큼 별도 네이티브 버퍼로 복사해 호출한 뒤 해제한다. 근거: `G:Java_com_tvt_network_NetClientProtocal_ConnectDevByToken@0x11e0b8`, `G:Java_com_tvt_network_NetClientProtocal_RequestLiveStreamTask@0x11e22c`, `G:Java_com_tvt_network_NetClientProtocal_SendLiveTalkBackData@0x11e50c`.
- 영상 프레임 경계: `NetClientProtocal.OnNetClientTaskData`가 task ID로 `ku3.c` observer에 `byte[]`를 전달한다. 해당 observer는 수신 버퍼를 복사하고 live task 종류에서는 `g8`로 패킷을 해석해 `ov3.onVideoData`를 호출한다. `LiveViewLayout.onVideoData`는 라이브 스트림 ID 조건에서 `VideoManagerLayout.R0`로 전달한다. 그 뒤 `VideoView.g3`가 채널·서버·스트림 ID를 확인하고 `Frame.setInit`으로 `byte[]`를 새 버퍼에 복사한다. `GL2JNIView`는 `H264Decode.NewPlayerInitialize` 및 `NewPlayerDecodeOneFrame(Frame)`을 호출한다. `H264Decode.checkMediaCodecSupport`는 인코딩 타입 0/1을 각각 H.264/H.265로 해석한다. 근거: `J:com/tvt/network/NetClientProtocal.java:159-168`, `J:defpackage/ku3.java:6592-6641,2176-2595`, `J:com/tvt/live/LiveViewLayout.java:4250-4260`, `J:com/tvt/video/VideoManagerLayout.java:557-577`, `J:com/tvt/video/VideoView.java:2804-2830`, `J:com/tvt/network/Frame.java:33-55`, `J:com/tvt/video/GL2JNIView.java:561-586`, `J:com/sdk/mediacodec/H264Decode.java:353-362`.
- Ghidra에서 `H264Decode.NewPlayerDecodeOneFrame`은 Java `Frame`을 `VideoPacketInfoObjectTo`로 변환하고 `CAppPlayerDecoder::pushAvPacket`에 넘긴다. 큐 삽입 실패 시 네이티브 할당을 해제한다. `NewPlayerDestroy`는 디코더를 해제한다. 이 라이브러리의 `JNI_OnLoad`는 `av_jni_set_java_vm`과 `SDL_JNI_OnLoad`를 호출한다. 조사한 핵심 Java native 메서드는 내보낸 `Java_*` JNI 심볼과 직접 대응하며, `TVTOpenSDK.registerCallback`은 앱 응답 콜백 등록으로 `RegisterNatives`와 다른 함수다. 근거: `G:Java_com_sdk_mediacodec_H264Decode_NewPlayerDecodeOneFrame@0x126388`, `G:Java_com_sdk_mediacodec_H264Decode_NewPlayerDestroy@0x126478`, `G:JNI_OnLoad@0x13dbe4`.
- 양방향 음성: `LiveTalkManager`가 시작/중지를 `DeviceItem.c0().t5`로 전달한다. `ku3.t5`는 `RequestLiveTalkBack`으로 task ID를 얻고 중지 시 `CloseLiveTalkBack`을 호출한다. 오디오 버퍼는 인코딩 후 `SendLiveTalkBackData(taskId, audioType, byte[], length, channelUid)`에 전달된다. 근거: `J:com/tvt/live/LiveTalkManager.java:151-185`, `J:defpackage/ku3.java:8087-8126,8260-8279`.

## 한계와 후속 검증

- Ghidra의 위 `TVTOpenSDK.nat*` 함수는 반환값 0인 구현으로 확인됐지만, 앱의 모든 장치 유형·연결 모드가 같은 경로를 사용하는지는 정적 분석만으로 알 수 없다. T31은 `NetClientProtocal` 경로를 우선 관찰해야 한다.
- 실제 로그인 성공, NAT에서 LAN/P2P/relay 선택, 토큰 갱신·만료, 채널 번호와 UID 대응, 압축 프레임 수신/재접속, 알람 push와 목록 응답, Talk 권한·오디오 포맷·중지는 실기기와 승인된 TVT/DVR 계정으로 검증해야 한다.
- `TVTNatCallback.notify` 및 `natTransCallback` 선언은 확인되지만, 이 APK의 해석된 Java 코드에서 `setTvtNatCallback` 호출은 확인되지 않았다. 등록 여부와 콜백 스레드/소유권은 미확정이다.
- 이 보고서의 **T00A 핵심 경로 정적 범위**는 완료됐다. 이는 APK 전체 기능 감사의 완료를 뜻하지 않는다. G10 `runtime_status=pending`이며, 런타임 상태를 정적 증거로 완료 처리하지 않는다.
