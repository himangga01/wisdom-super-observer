# SuperLive Plus 1.18.1 APK 조사 총괄

조사일: 2026-09-27. 대상: 연결된 Android 기기에 설치된 `com.tvt.superliveplus` 1.18.1(20267)의 base APK 1개. 이 디렉터리는 **10명 서브에이전트의 영역별 정적 조사와 독립 교차 검증**을 묶는다. 원본 APK, 추출 Java/리소스, 네이티브 바이너리, 임시 분석 자료는 저장소 밖 `C:\wso-private\superliveplus\1.18.1-2026-09-27`에 있으며, 계정·장치 비밀값은 보고서에 기록하지 않았다. 서비스 구현이나 장치 설정 변경은 하지 않았다.

## 판정

앱의 화면·요청·JNI/ELF 표면을 **전수 목록화하고 주요 Java 호출 경로를 심층 추적**했다. 이 자료는 서비스의 기능 명세와 시험 항목을 만드는 데 사용할 수 있다. **APK만으로 웹서비스가 100% 동일하게 동작한다고 증명할 수는 없다.** 난독화·디컴파일 오류·미해석 네이티브 본문 외에도 서버 권한, 장치 모델/펌웨어, 유료 상품, WebView 콘텐츠와 실제 계정 응답이 필요하다. 단계별 근거와 남은 공백은 [독립 QA](10-completeness-review.md)에 있다.

`TVTOpenSDK`는 이 APK의 `com.tvt.protocol_sdk` Java 요청 라우터와 `libProtoSDK.so` 사이의 JNI 진입점이다. 이것이 외부 배포용 공식 SDK인지는 확인되지 않았다. [웹 자료 대조](00-tvtopensdk-web-check.md)에는 TVT 공식 SDK 안내 및 별개의 공개 `NET_SDK_*` 프로젝트와의 차이를 기록했다. `/sdk/...`는 앱 내부 라우트 이름이며, 그대로 호출할 수 있는 공개 REST URL이라는 근거가 아니다.

## 조사 규모

| 표면 | 재집계 결과 | 의미 |
| --- | ---: | --- |
| DEX / JADX Java 산출물 | 7 / 19,116 | 코드 추출 범위 |
| `com/tvt` / 최상위 `defpackage` Java | 2,187 / 3,249 | 제품 코드와 난독화 코드 |
| Manifest Activity 선언 / 고유 이름 | 513 / 498 | 선언 수는 실행 가능 기능 수와 다름 |
| TVT SDK 요청 클래스 / `TVTOpenSDK` native 선언 | 281 / 299 | 라우트·JNI 표면 |
| Android `.so` | arm64 13 / arm32 12 | 25개 바이너리, ABI 대조 |
| JADX 전체 오류 / Method 목록 항목 | 391 / 262 | 분석 신뢰도 제한 |

원본 수량, APK 해시, 검증 기준은 [기준선](00-coverage-baseline.md), 실제 불일치·오류·증거 확인 범위는 [독립 QA](10-completeness-review.md)를 따른다.

## 영역별 결과

| 담당 | 보고서 | 핵심 범위 |
| --- | --- | --- |
| 1 화면·메뉴 | [01](01-ui-feature-inventory.md) | Manifest 165개 TVT Activity, 화면 진입, 23개 사용자 기능 영역, 조건부 노출 |
| 2 TVT 요청 | [02](02-protocol-api.md) | 281개 요청 클래스, 라우트·입력·callback, 299개 native 선언, JNI export 차이 |
| 3 영상·저장 | [03](03-media.md) | 라이브, 8개 화면 분할, 재생, 로컬/클라우드 녹화와 다운로드, frame 경계 |
| 4 알람·푸시 | [04](04-alarms-push.md) | FCM·TVT socket, 알람 유형·저장·상세·설정, Tyco 알람 |
| 5 장치 제어 | [05](05-device-controls.md) | PTZ·어안·렌즈, 장치 추가/공유, 원격 설정, Wi-Fi·펌웨어·출입 제어 |
| 6 음성 | [06](06-audio-talk.md) | 듣기, Talk, 도어벨 통화, 음성 경보 클립, speech recognition |
| 7 AI·클라우드 | [07](07-ai-cloud-services.md) | AI/이미지 검색, 얼굴·번호판, 클라우드·VAS, Tyco, 파일 SDK·웹 페이지 |
| 8 네이티브 | [08](08-native-abi-jni.md) | 두 ABI 25개 `.so`, Java/JNI 대조, 스텁·누락·미해석 본문 |
| 9 인증·망 | [09](09-auth-network.md) | 로그인·토큰, 지역별 서버, 제3자 인증, 저장·TLS·개인정보 경계 |
| 10 독립 QA | [10](10-completeness-review.md) | 수량·인용 재검사, 52개 TVT 디렉터리 매트릭스, 보고서 충돌 교정 |

## 계획서 작성을 위한 추가 검증

| 보고서 | 계획서에 반영한 내용 |
| --- | --- |
| [11 프로토콜 실현성](11-protocol-feasibility.md) | 내부 SDK/네이티브 경계, NAT 스텁, 공급사 SDK·브리지 선정 기준 |
| [12 기능별 계약](12-functional-parity-contracts.md) | 화면 행동·오류·부작용을 원자적 P ID로 추적하는 대조 기준 |
| [13 웹 플랫폼 경계](13-web-platform-constraints.md) | FE·BE·현장 게이트웨이 역할 및 단말 OS 동작 검증 조건 |
| [14 도달성 재검사](14-reachability-and-route-gaps.md) | 방어 설정, About 디버그/체험, 클라우드 경로, 거주자 관리 H5의 추가 근거 |

구현 순서, 인터페이스, 테스트, 출하 판정은 [웹 기능 동등성 구현 계획서](../../superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md)에 연결한다.

## 웹서비스 설계에 바로 쓰이는 결론

1. **기능 목록은 마련됐다.** 로그인·장치 관리·라이브·재생·Talk·PTZ·알람·AI 검색·클라우드·Tyco를 각각 계정/기기/권한 조건과 함께 명세화해야 한다. 화면이나 라우트 선언만 있는 항목은 성공 기능으로 세지 않는다.
2. **네이티브 장치 연결이 최대 불확실성이다.** `NetClientProtocal`, `NatTraveral`, `ProtoSDK`의 Android `.so`를 브라우저가 직접 실행할 수 없다. 공개 웹 API/정식 SDK 또는 별도 서버 게이트웨이 가능성을 실제 TVT 계정·장치로 검증해야 한다.
3. **일부 선언은 동작 구현이 아니다.** `/sdk/getDeviceLocalStorageStatus` 라우트 중복, 비어 있는 요청·callback 본문, 두 ABI에서 확인된 NAT 0 반환 스텁, 25개 이름의 미해결 `TVTOpenSDK` native 연결은 [프로토콜](02-protocol-api.md)과 [네이티브](08-native-abi-jni.md) 보고서에 분리돼 있다.
4. **외부·기기 상태를 확인해야 한다.** AI 검색은 주로 녹화기 명령, 클라우드/VAS는 별도 계정 서비스, Tyco는 별도 REST 서비스다. 유료 상품·모델 기능·실제 푸시·영상·음성·녹화 응답은 이 정적 조사에서 검증되지 않았다.

다음 검증 단계는 각 기능의 실제 계정·장치 조건에서 성공/실패 응답을 기록하고, 네이티브 프로토콜 또는 공급사 웹 SDK의 사용 가능 범위를 확인하는 것이다. 이 정적 조사 결과가 서비스 구현 승인이나 100% 동등성 보장은 아니다.
