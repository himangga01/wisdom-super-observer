# SuperLive Plus 1.18.1 교차 검증과 기능 동등성 판정

검토일: 2026-09-27. 이 문서는 [기준선](00-coverage-baseline.md)과 [01~09 영역별 보고서](01-ui-feature-inventory.md)를 독립적으로 대조한 **정적 APK 감사의 QA 결과**다. 원본은 저장소 밖 `C:\wso-private\superliveplus\1.18.1-2026-09-27`에 있다. 앱 로그인, 카메라·패널 조작, 서버 응답, 방송/녹음, 결제·구매를 실행하지 않았다. 아래의 `추적`은 대표 호출 경로를 읽었다는 뜻이며, 패키지의 모든 분기나 기능 성공을 뜻하지 않는다.

## 독립 재집계와 증거 점검

| 항목 | 원본에서 재확인 | 판정 |
| --- | ---: | --- |
| `classes.dex`~`classes7.dex` | 7개 | 기준선과 일치 |
| JADX Java 산출 파일 / `com/tvt` / 최상위 `defpackage` | 19,116 / 2,187 / 3,249개 | 기준선과 일치. 산출 파일 수는 로드 클래스 수 12,623과 같은 개념이 아님 |
| `com/tvt` 최상위 디렉터리 | 52개 | 아래 52행에 모두 기재 |
| Manifest `<activity>` / 서로 다른 이름 | 513 / 498개 | [01](01-ui-feature-inventory.md)과 일치 |
| `com.tvt.*` Activity / 기본 `res/layout` XML | 165 / 965개 | [01](01-ui-feature-inventory.md)과 일치 |
| `*ActivityPage` 선언 / 서로 다른 이름 | 300 / 285개 | Manifest 중복 15건이 이 묶음에 속함. 의심스러운 제품 외 화면이라는 판단은 **추정**이며 실행 불가를 증명하지 않음 |
| 직접 `protocol_sdk/request/*.java` / `TVTOpenSDK.java` native 선언 | 281 / 299개 | [02](02-protocol-api.md)와 일치 |
| `.so` arm64 / armeabi-v7a | 13 / 12개 | [08](08-native-abi-jni.md)과 일치; `libmmkv.so`만 arm32 짝이 없음 |
| JADX 오류 총합 / `ERROR -   Method:` 목록 | 391 / 262건 | 전체 오류와 메서드 목록을 구분. `com.tvt` 목록 33건 중 생성 `R.*` 생성자 24건, 실질 메서드 9건 |

보고서 01~09의 명시적 `J:경로.java:줄` 인용 **583건**을 자동 검사한 결과 파일 누락과 파일 길이를 넘는 줄 번호는 0건이었다. 이는 *경로와 줄의 존재* 검사이며 각 문장의 의미를 자동 검증한 결과가 아니다. 선택한 주요 주장도 원문으로 대조했다: `VideoManagerLayout`의 8개 화면 분할 분기, `/sdk/getDeviceLocalStorageStatus` 라우트 덮어쓰기, 비어 있는 `VASSetInstSwitchRequest.execute`, 비어 있는 두 cloud callback, FCM 토큰 갱신 브로드캐스트, 9개 `com.tvt` 비생성 메서드 오류. [09](09-auth-network.md)의 Tyco cache `MMKV`/공유 설정 저장 분기, 암호화 유형일 때 최근 계정 목록의 첫 원소만 암호화하는 코드, Glide 전용 인증서 검증 우회 코드도 선택 대조했다. [02](02-protocol-api.md)의 278 JNI export와 [08](08-native-abi-jni.md)의 ELF 주소·해시·5개 무동작 NAT 함수는 담당 영역의 원본 바이너리 분석을 대조해 수록한 값이며, 이 QA가 3,515개 JNI export와 모든 ARM32 함수 본문을 재분해한 것은 아니다.

## 52개 `com/tvt` 상위 디렉터리 대조

표의 번호는 영역별 보고서 번호다. `추적`은 해당 영역의 대표 UI/호출 경로가 본문에서 따라가졌음을, `인덱스`는 주로 파일·화면·리소스 목록 수준임을 뜻한다. 일부 패키지는 다른 영역에도 걸친다. [09](09-auth-network.md)의 계정·네트워크·저장소 범위도 대조했다.

| `com/tvt` 디렉터리 | Java 파일 | 주 보고서 | QA 깊이/잔여점 |
| --- | ---: | --- | --- |
| `about` | 3 | 01, 07 | 추적: 정보·웹 진입 |
| `ai` | 106 | 01, 07 | 추적: 검색·필터·번역; coroutine 1개 오류 |
| `audio` | 2 | 06 | 추적: 관련 오디오 보조 경로 |
| `backup` | 4 | 03, 06 | 추적: 장치·클라우드 영상 내보내기 |
| `base` | 90 | 01 | 인덱스: 공용 UI·DB·생성 리소스, 분기 전수 검토 아님 |
| `calendar` | 3 | 01, 03 | 인덱스: 날짜 UI 보조 |
| `cloudstorage` | 105 | 01, 03, 07, 08 | 추적: 클라우드 목록·플레이어·JNI; native 내부 미해석 |
| `config` | 14 | 01, 05, 07 | 추적: 로컬·원격 구성/WebView |
| `configure` | 86 | 05, 07 | 추적: 주요 장치 XML 명령·모델; 모든 펌웨어 유형 미검증 |
| `dev_share` | 14 | 01, 05, 08 | 추적: 공유 QR·암호화 경계 |
| `device` | 44 | 01, 05 | 추적: 장치 정보·관리 UI |
| `devicelogin` | 1 | 01, 09 | 추적: 로그인 화면 진입 |
| `devicemanager` | 65 | 01, 05, 06 | 추적: 장치/도어벨 설정 |
| `dialog` | 7 | 01 | 인덱스: 공용 대화상자 |
| `expandablegridview` | 3 | 01 | 인덱스: UI 위젯 |
| `experience` | 1 | 01 | 추적: 체험 화면 진입 |
| `file_sdk` | 15 | 07, 08 | 추적: JNI 선언·초기화; 앱의 실제 동기화 시작점 미확인 |
| `filemanager` | 12 | 01, 03, 07 | 추적: 로컬 사진/영상 파일 |
| `help` | 1 | 01 | 추적: 도움말 진입 |
| `launch` | 3 | 01, 04, 09 | 추적: 시작·초기화·푸시 토큰 |
| `live` | 41 | 01, 03, 05, 06 | 추적: 라이브·조작·Talk; 실프레임/장치 결과 미검증 |
| `login` | 33 | 01, 09 | 추적: 계정 로그인·복구 화면 |
| `network` | 28 | 03, 04, 05, 06, 08, 09 | 추적: device task·JNI·callback; wire 내부 제한 |
| `network_android` | 21 | — | 인덱스: 생성된 `R.*` 클래스만 확인; 연결 구현으로 세지 않음 |
| `opensslsdk` | 3 | 08, 09 | 추적: JNI 표면; 키 관리·native 내부 미해석 |
| `other` | 16 | 01, 05, 09 | 추적: `DeviceItem` 등 공용 장치 모델 일부 |
| `photo` | 1 | 01 | 인덱스: 이미지 뷰 |
| `playback` | 13 | 01, 03, 06 | 추적: 재생 UI·검색·audio 상태 |
| `protocol_sdk` | 323 | 02, 04, 07, 08, 09 | 전수 목록: request 281·route·native 선언; 응답 스키마/서버 성공 아님 |
| `push` | 81 | 01, 04 | 추적: 수신·캐시·알림·상세; 1개 주요 메서드 미복원 |
| `pushconfig` | 17 | 01, 04 | 추적: 장치별 푸시 선택 UI |
| `resources` | 18 | 01 | 인덱스: 리소스 지원 코드 |
| `router` | 1 | 01, 07 | 추적: 화면 라우팅 |
| `search` | 25 | 01, 07, 08 | 추적: 구형 검색·얼굴/번호판; 2개 메서드 오류 |
| `server` | 38 | 03, 05, 09 | 인덱스/선택: NVMS header·response bean·UI adapter; 네트워크 본체 아님 |
| `serverlistsync` | 2 | 08, 09 | 추적: `ProtoSDK` JNI 경계 |
| `skin` | 28 | 01 | 인덱스: 스타일/스킨 코드 |
| `speechrecognitionsdk` | 7 | 06, 07 | 추적: Android SpeechRecognizer 입력 |
| `supercamplus` | 1 | 01, 09 | 인덱스: 제3자 인증 콜백 Activity |
| `superliveplus` | 445 | 01, 09 | 인덱스: 주로 생성 `R`·data binding과 콜백; 전 기능 445개 아님 |
| `third_login` | 23 | 09 | 인덱스: login/bind bean 2개와 생성 `R.*` 21개; OAuth 실행 경로는 다른 패키지 |
| `third_party_auth` | 17 | 01, 09 | 추적: 인증 callback/UI |
| `timelib` | 3 | 01, 03 | 인덱스: 시간 UI 지원 |
| `tyco` | 218 | 01, 04, 05, 07, 09 | 추적: 패널 REST/화면; coroutine 6개 오류, 계정/패널 결과 미검증 |
| `user` | 134 | 01, 09 | 추적: 사용자·공유·보안 화면 |
| `valueaddedservice` | 35 | 01, 07 | 추적: 상품·유료 서비스 UI; 결제 미검증 |
| `video` | 5 | 03, 06 | 추적: 8개 분할·frame/audio 수신·렌더링 경계 |
| `view` | 6 | 01 | 인덱스: 공용 위젯 |
| `web` | 4 | 01, 07 | 추적: 일반 WebView 진입; 원격 HTML 미확보 |
| `weeklib` | 10 | 01, 03 | 인덱스: 주간/일정 UI 지원 |
| `wifi_config` | 1 | 05 | 추적: Wi-Fi 구성 지원 |
| `wvjsbridge` | 10 | 05, 07 | 추적: WebView·JS bridge; 동적 페이지 내용 미확보 |
| **별도 `defpackage`** | **3,249** | 01~09 | 핵심 난독화 세션·장치·UI helper만 선택 추적. 모든 클래스/분기 의미를 복원하지 못함 |

이 표는 **파일의 존재와 기능별 대표 경로 조사 범위**를 공개한다. 52개 디렉터리나 19,116개 Java 파일을 행별로 나열했다는 사실은 모든 메서드를 해석했다는 뜻이 아니다. `com/tvt` 바깥의 Google/Android/기타 라이브러리 코드는 기능 의존·진입점 중심으로만 보았고, 300개 의심 ActivityPage는 별도 선언 묶음으로 취급했다.

## 보고서 사이 불일치와 수정 상태

| 항목 | 교차 검증 | 상태 |
| --- | --- | --- |
| 다중 화면 모드 | [01](01-ui-feature-inventory.md)의 1/2/4/6/8/9/13/16 UI 목록을 `VideoManagerLayout.java`의 동일한 8개 layout 분기와 대조했다. [03](03-media.md)의 5개 모드 누락은 담당자가 8개로 수정했다. | 해결 |
| 오디오 JNI 주소 | live `OpenLiveAudio`/`CloseLiveAudio`는 `0x11e400`/`0x11e41c`; playback은 `0x11e438`/`0x11e454`. [03](03-media.md)과 [06](06-audio-talk.md)의 현행 값이 일치하도록 수정됐다. | 해결 |
| JADX 오류 수 표현 | 391은 전체 오류, 262는 로그의 Method 항목, 그중 9개가 비생성 `com.tvt` 메서드다. [01](01-ui-feature-inventory.md)의 `391 메서드 오류` 표현은 수정됐다. | 해결 |
| FCM token 갱신 | [04](04-alarms-push.md)의 불일치 지적을 원문으로 확인. `onNewToken`은 action 없는 `Intent`에 extras를 넣고 플랫폼 `sendBroadcast(intent, "refresh_token")`을 호출한다. 수신자는 `LocalBroadcastManager`에 `refresh_token` action을 등록하며 action null을 거부한다. 따라서 **그 특정 수신 경로**는 코드상 연결되지 않는다. 다른 토큰 등록 경로가 전부 실패한다는 뜻은 아니다. | 근거 확인, 실제 전달 경로 미검증 |
| SDK route/JNI | `/sdk/getDeviceLocalStorageStatus` 등록이 뒤의 HDD alarm request로 덮이고, `VASSetInstSwitchRequest.execute`와 cloud 두 callback이 빈 본문임을 원문에서 확인했다. | 코드 결함/공백으로 유지 |
| 계정·전송 경계 | [09](09-auth-network.md)의 `/sdk/*`는 내부 dispatch ID이며 공개 REST endpoint가 아니라는 설명이 [02](02-protocol-api.md)의 native-forwarding 구조와 일치한다. Tyco REST는 별도 Retrofit client이며 Android `.so`를 브라우저에 가져올 수 없다. | 범위 일치; wire/서버 동작 미검증 |

## 남은 분석 공백과 판정

1. **정적 복원 한계**: `com.tvt` 비생성 메서드 9개에 AI 작업 순서·구형 검색·Tyco timer/출력 callback이 포함된다. `PushMessageDataUtil.n()` 같은 소스 본문도 실패하거나 불완전하다. 난독화된 `defpackage` 3,249개 전체와 300개 의심 ActivityPage의 실행 도달성은 전수 증명되지 않았다.
2. **네이티브 본문**: [08](08-native-abi-jni.md)은 모든 라이브러리/두 ABI의 파일·symbol 표면을 대조했지만, 저장된 Ghidra 성공 디컴파일은 arm64 4개 라이브러리의 **37개 선택 함수**(JNI 36 + `JNI_OnLoad` 1)에 한정된다. `CloudStorage`, `AudioCodec`, `OpensslSDK`, OpenCV, MMKV, arm32 내부 대부분은 미해석이다. `TVTOpenSDK` 25개 native 이름/31개 선언 서명은 전통적 export가 없고 dynamic registration도 입증되지 않았다. 5개 NAT entry는 양 ABI의 0 반환 stub이다. route나 export 수를 동작 가능 수로 해석할 수 없다.
3. **서버·기기·Android 경계**: 실제 계정 권한, 모델/펌웨어 기능 플래그, 로그인·토큰, 녹화·오디오·push·AI 검색·클라우드·Tyco·결제 응답, WebView로 내려오는 페이지와 사용자 승인 권한은 APK에 고정돼 있지 않다. [09](09-auth-network.md)는 TVT 계정·P2P·장치 토큰이 다른 값을 갖고 지역/패키지별 host가 달라질 수 있음을 확인했다. 안드로이드 전용 인터페이스(마이크, 푸시, 카메라, 백그라운드 통화)에는 웹 대체 설계와 브라우저 제약 검증이 추가로 필요하다.
4. **외부 SDK 이용 가능성**: [공개 자료 대조](00-tvtopensdk-web-check.md)에서 공식 `TVTOpenSDK` API/재배포 문서는 확인되지 않았다. TVT 장치 SDK 문의 안내나 제3자 `NET_SDK_*` 코드는 APK의 Java/JNI `TVTOpenSDK`와 같은 배포물이라는 근거가 아니다. 서비스가 이 SDK를 합법적으로 직접 사용하거나 같은 프로토콜로 서버를 운영할 수 있는지는 별도 확인 사항이다.

**판정**: 이 결과는 화면·요청·JNI 표면과 주요 기능 경로를 광범위하게 목록화한 **정적 전수 인벤토리 및 선택 경로 심층 분석**으로 사용할 수 있다. 기능명 발견만으로 APK의 모든 분기, 모든 기기별 기능 또는 웹서비스 100% 동일 기능을 증명하지 않는다. 현재 근거로는 100% 웹 동등성의 가능·불가능을 단정할 수 없으며, **기능별 구현 근거와 실제 장비·계정·서버 응답을 연결한 검증**이 필요하다. 웹 재현의 첫 단위는 계정/장치 목록, 실시간 영상, 재생, PTZ, Talk, 알람, AI/클라우드처럼 사용자에게 보이는 기능별 계약과 성공/오류 응답을 확인하는 것이다. 이 문서는 구현 승인이나 서비스 배포 판정이 아니다.
