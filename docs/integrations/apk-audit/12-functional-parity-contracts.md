# SuperLive Plus 1.18.1: 기능 동등성 계약과 실행 시험 목록

작성일: 2026-09-27. 범위는 설치된 `com.tvt.superliveplus` 1.18.1(20267)의 **정적 APK**와 [01~10 감사](README.md)다. 이 문서는 웹 구현의 완료 조건을 *사용자 동작 단위*로 정한다. 계정 로그인, 장치/패널 명령, 결제, 탈퇴는 실행하지 않았다. 따라서 아래의 성공/실패는 **시험할 관찰값**이지 이미 관찰한 서버 결과가 아니다. 원본은 저장소 밖 `C:\wso-private\superliveplus\1.18.1-2026-09-27`에 있다. 비밀값과 실장치 식별자는 기록하지 않는다.

## 읽는 법과 판정 규칙

`J:경로:줄`은 위 원본의 `jadx-full/sources/` 기준, `M:줄`은 `apktool/AndroidManifest.xml`, `R:경로`는 `apktool/res/` 기준이다. 아래의 `01`~`09`는 이 디렉터리의 번호별 보고서다. `C`는 UI 클릭/명령 호출 경로를 확인했으나 **계정·브랜드·모델·펌웨어·권한·상품 상태에 조건부**인 계약, `D`는 선언·리소스·JNI만 있어 해당 사용자 동선이나 성공 경로가 확인되지 않은 계약, `L`은 앱 로컬 작업이다. 이 표의 `C`조차 실제 성공을 뜻하지 않는다. 각 행의 `/sdk/*`는 앱 내부 JNI 요청 라우트이고 공개 REST URL이 아니다. [02](02-protocol-api.md)의 281개 요청 전체를 웹 API로 간주하지 않는다.

**시험 러너 계약.** 각 `Pxx.y`를 독립 시나리오로 실행한다. `(A)` 같은 기기/지역/브랜드·펌웨어의 Android 참조 앱, `(W)` 웹 후보를 별도 시험 계정 또는 초기화 가능한 동등 fixture에 연결한다. 시작 화면, 계정 상태, 장치 능력, 권한, 데이터(알람/녹화/파일), 시계·시간대와 네트워크 상태를 기록한다. 표의 `동작`을 두 클라이언트에서 수행하고 화면/라우팅, 결과 종류·식별자·순서·시각, 후속 재조회, 가능하면 감사 가능한 서버/장치 상태를 비교한다. `ok`는 성공 callback/토스트만으로는 통과하지 않고 **상태 변화 또는 실제 산출물**로 확인한다. `err`는 권한 거부, 잘못된 입력, 오프라인, 시간 초과/만료 등 표의 실패 fixture로 실행하고 메시지 종류, 상태 유지, 재시도 가능성을 비교한다. 정확한 문구·코드·응답 스키마는 정적 APK에서 정하지 않으며 참조 실행으로 golden trace를 만들어야 한다. `D`는 우선 런타임 도달성부터 측정하고, 도달 불가이면 웹에서 동작 구현이 아닌 미지원/비노출 계약으로 기록한다.

**fixture 표기.** `G`=게스트, `U`=일반 TVT 계정, `O`=장치 소유자, `R`=제한된 공유 수신자, `N`=오프라인/미지원 장치, `B`=해당 브랜드 플래그, `T`=Tyco 계정+패널, `V`=VAS 적격 계정/상품, `F`=저장·카메라·마이크·알림 권한. `U/O/R/T/V`의 실제 자격과 비밀은 별도 보관한다. `+`는 모든 조건 필요, `/`는 비교 fixture. 쓰기 시험은 소유한 초기화 가능한 장치/샌드박스에서만 실행한다. 결제·탈퇴·포맷·펌웨어 변경은 승인된 테스트 계정/장비와 테스트 결제 수단이 갖춰질 때만 실행한다. 미실행을 통과로 표시하지 않는다.

## 23개 기존 UI 영역과 조건부 거주자 관리의 원자적 계약 (77건)

표의 `관찰/오류`는 성공 시 확인할 값과 반드시 실행할 대표 실패 분기다. `효과`는 로컬(`local`), TVT 계정(`account`), 장치(`device`), 별도 Tyco(`tyco`), 외부 공급자(`external`) 경계다. `검증`은 위 러너에서 수행할 실제 assert를 간략히 적은 것이다.

### 1. 시작·온보딩

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P01.1 C G | 새 설치 첫 실행, 개인정보 동의/거절, 재실행 | 동의 문서/가이드와 권한 안내; 거절 시 진행 제한. 동의 상태 `local` | [01](01-ui-feature-inventory.md); `J:com/tvt/launch/MainActivity.java:115-133,311-332,598-615`; `GuideActivity.java:198-247` | 두 분기 후 재실행해 진입 화면과 동의 지속성 비교 |
| P01.2 C G/U | 알림·딥링크로 앱 열기 | 대상 화면 또는 로그인/유효하지 않은 링크 처리; `local` navigation | `J:com/tvt/launch/MainActivity.java:743-761`; `J:com/tvt/network/MainViewActivity.java:1178-1190` | 유효/만료 링크와 로그인 전후 목적지 비교 |

### 2. 로그인·가입·복구

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P02.1 C G/U | 전화·메일 로그인, 보안 추가 코드 입력 | 프로필/장치 목록 진입 또는 자격/2차 검증 오류; `account` 세션, P2P 토큰은 별개 | [09](09-auth-network.md); `J:com/tvt/protocol_sdk/request/UserLoginRequest.java:11-67`; `J:defpackage/wf2.java:100-125` | 정상·오류·만료 계정으로 재실행 후 프로필과 세션 접근을 대조 |
| P02.2 C G | 이미지/동적 코드 요청 → 전화·메일 가입 | 코드 만료·중복 계정 오류 또는 신규 계정; `account` | `J:com/tvt/protocol_sdk/Protocol_Type.java:25-27,111-126,159-161`; `J:com/tvt/protocol_sdk/request/UserRegisterWithAccountRequest.java:11-55` | 유효/오류 코드로 가입 후 로그인·계정 조회 |
| P02.3 C G | 비밀번호 찾기/재설정 | 코드 검증 오류 또는 새 비밀번호로 로그인; `account` credential 변경 | `J:com/tvt/protocol_sdk/request/FindPasswordPasswordWithAccountRequest.java:11-45`; [02](02-protocol-api.md#authentication-and-account-47-classes) | 옛/새 비밀번호 각각 로그인 시도, 기존 세션 처리 비교 |
| P02.4 C G+B | WeChat/Facebook/GooglePlus 또는 Vimar IT20 선택 | 공급자 redirect/callback 후 로그인·연계 필요 또는 취소/지역 비노출; `external`+`account` | `J:defpackage/ed4.java:150-190`; `J:com/tvt/protocol_sdk/request/ThirdLoginRequest.java:11-42`; `J:com/tvt/login/view/activity/IT20WebLoginActivity.java:88-115`; [09](09-auth-network.md) | 실제 노출 provider별 취소/성공/잘못된 state·code를 비교; 단순 콜백 Activity 존재는 불합격 |
| P02.5 D U | 웹 QR UUID 전송/승인 화면의 실제 진입 확인 | 승인/거절 결과 또는 미도달; `account` | [09](09-auth-network.md); `/sdk/sendUUIDForWebLogin`, `/sdk/sendAuthForWebLogin` [02](02-protocol-api.md#authentication-and-account-47-classes) | 참조 앱에서 진입점 발견 후 유효·만료 UUID 및 거절 시험; 없으면 선언 전용으로 기록 |

### 3. 라이브 영상

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P03.1 C O/R/N | 장치/채널 선택·닫기, 오프라인 장치 열기 | 지정 채널의 실제 프레임/상태 또는 오프라인·권한 오류; `device` 세션 | `J:com/tvt/live/LiveViewLayout.java:2097,2581-2624`; `J:defpackage/ku3.java:4036-4061`; [03](03-media.md) | 프레임의 장치/채널 일치, 초기화/종료 후 연결 해제, R/N 오류 비교 |
| P03.2 C O | 화질/stream 변경, 전체화면·회전 | 선택 stream의 프레임·표시 변경 또는 능력 오류; `device`+`local` | `J:com/tvt/live/LiveViewLayout.java:1651,1719-1725,2617-2621`; `J:defpackage/ku3.java:5460-5476` | 해상도/bitrate/화면 표시, 재연결 후 선택 상태 비교 |

### 4. 라이브 조작

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P04.1 C O | 1/2/4/6/8/9/13/16 분할 전환, 타일 교체 | 채널별 프레임·선택 상태, 지원 수 제한 또는 성능 오류; `local`+`device` | `J:com/tvt/video/VideoManagerLayout.java:107-127,1263-1364`; `J:com/tvt/live/view/LiveOperateBarView.java:168-179` | 8개 모드 각각 타일 배치/스트림 identity와 닫힌 task 수 비교 |
| P04.2 C O/R/N+F | 듣기와 Talk 시작/중지 | 수신 소리와 원격 송신 음성 또는 권한·offline·지원 불가; `device`+마이크 | `J:com/tvt/live/a.java:48-94`; `J:com/tvt/live/LiveTalkManager.java:133-175,382-455`; [06](06-audio-talk.md) | 녹음 권한 거부/허용, 양 방향 실제 음성, 중지 후 마이크·task 해제 확인 |

### 5. 영상별 도구

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P05.1 C O+F | 스냅샷·라이브 MP4 시작/중지 | 새 이미지/재생 가능한 파일 또는 저장소·frame 오류; `local` | `J:com/tvt/video/VideoManagerLayout.java:1460-1517`; `J:com/tvt/video/VideoView.java:1303-1404,3294-3344`; [03](03-media.md) | 실제 파일 존재·디코딩·시간/채널과 파일 관리자 재조회 비교 |
| P05.2 C O/R/N | PTZ 연속 이동→stop, 줌/초점/iris, preset·cruise | 물리 위치 변화와 정지 또는 권한/능력/오프라인 오류; `device` | `J:defpackage/cw3.java:8319-8359`; `J:defpackage/ew3.java:5982,7628`; [05](05-device-controls.md) | 안전 범위에서 명령·stop 후 영상 위치/장치 상태 측정; SDK 즉시 `ok`만으로 불합격 |
| P05.3 C O | 어안 dewarp·이미지/렌즈 설정·flip | 렌더링 전후 차이 또는 저장된 장치 설정; 미지원 옵션 비노출; `local`/`device` 구분 | `J:com/tvt/video/GL2JNIView.java:290-313`; `J:defpackage/hz1.java:361-401,466-480`; [05](05-device-controls.md) | 어안은 화면 픽셀, 렌즈/색상은 재조회와 영상 변화를 각각 비교 |

### 6. 라이브 ‘더보기’

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P06.1 C O/R | 즐겨찾기 추가/해제, 목록 재정렬 | 즐겨찾기와 계정/로컬 저장 위치에 맞는 재시작 지속성; `account`/`local` | `J:defpackage/dj2.java:154-280`; `/sdk/AddDeviceToFavoritesGroup`, `/sdk/DeleteDeviceFromFavoritesGroup` [02](02-protocol-api.md#devices-groups-and-configuration-71-classes) | 추가/삭제 후 재조회·다른 로그인 세션의 노출 비교 |
| P06.2 C O/N | 수동 경보·소리/조명·와이퍼·출입 제어, AI 모드/RS485 | 해당 기기 actuator/모드 변화 또는 안전한 미지원·오프라인 오류; `device` | `J:defpackage/dj2.java:258-293,455-594`; `J:defpackage/cw3.java:3908,6937`; `J:defpackage/ew3.java:5359`; [05](05-device-controls.md) | 장치별 능력 표시→동작→독립 센서/설정 재조회; 노출만으로 통과 금지 |
| P06.3 C O/N | 사용자 경보음 WAV 선택·검증·업로드·선택·미리 듣기·삭제 | PCM 8 kHz 조건, 클립 목록/선택 상태와 실제 장치 스피커 출력 또는 형식·용량·권한·장치 오류; `local` 파일→`device` 저장 | `J:defpackage/dl.java:185-255,642-760,795-843`; `J:defpackage/pv4.java:29-79`; [06](06-audio-talk.md) | 허용/거부 WAV, 중복 업로드, 저장 후 재조회, 미리 듣기·원격 출력·삭제를 각각 비교; 실제 출력은 별도 승인된 장치에서만 확인 |

### 7. 재생·백업

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P07.1 C O/R/N | 채널·일자·시간 검색, 재생/seek/속도/소리 | 맞는 시각 프레임·오디오 또는 녹화 없음/권한·offline 오류; `device` | `J:com/tvt/playback/view/PlaybackViewLayout.java:4852-5057`; `J:defpackage/ku3.java:4330-4333,5637-5685`; [03](03-media.md) | 알려진 녹화 구간 전/중/후, 시간대·seek·종료 결과 비교 |
| P07.2 C O+F | 기간 선택 백업·다운로드 | 진행률→재생 가능한 MP4 또는 중단·공간 부족·재시도; `device`→`local` | `J:com/tvt/backup/BackupFileManager.java:352-379,511-560`; `J:com/tvt/backup/a.java:156-255` | 파일 내용·길이·채널 및 취소 후 잔여 task/파일 비교 |

### 8. 지능형 검색

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P08.1 C O/N | 텍스트 입력·번역, 장치/시간 필터 검색 | 서버 번역/녹화기 결과, 빈 결과·지원 불가 오류; `account` translation + `device` search | `J:com/tvt/ai/search/model/AISearchModel.java:596-639,709-726`; `J:defpackage/cw3.java:4863-4893`; [07](07-ai-cloud-services.md) | 동일 corpus/언어/시간으로 순서·썸네일·상세를 비교; 번역과 검색 경계 각각 기록 |
| P08.2 C O+F | 음성 입력·검색 | 인식 문구가 검색 입력에 반영 또는 마이크/인식 서비스 오류; `local` speech→`device` search | `J:com/tvt/ai/search/AISearchInputActivity.java:1519-1600`; `J:com/tvt/speechrecognitionsdk/SpeechRecognitionService.java:339-382,442-579` | 고정 발화/권한 거부·서비스 부재 fixture로 입력 값과 후속 결과 비교 |
| P08.3 C O/N | 사람·차·동물·물품/이벤트 속성, 사진 crop·유사도 검색 | 필터와 대상 검색 결과 또는 미지원/빈 결과; `device` | `J:com/tvt/ai/search/AIAttributeSearchActivity.java:543-648`; `AIPicSearchModel.java:517-553,620-635`; `J:defpackage/cw3.java:4944-4987,5529-5555` | 알려진 대상의 고정 이미지로 일치율·결과 링크 비교 |
| P08.4 C U | AI 텍스트 검색 기록·추천 노출과 과거 항목 재선택 | 입력 화면의 목록/순서, 선택 시 입력·검색 효과 또는 빈 기록/삭제·비노출 상태; `local`/`account` 지속 범위는 런타임 확인 | `J:com/tvt/ai/search/AISearchInputActivity.java:734-745,1256`; [07](07-ai-cloud-services.md) | 새 입력 전후, 재시작·다른 로그인/단말에서 기록·추천·선택 결과를 비교하고 저장 범위를 확정 |

### 9. 기존 얼굴·번호판 검색/등록

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P09.1 C O/N+F | 얼굴 사진 선택·로컬 얼굴 감지→그룹/신원 등록 | 감지 crop, 녹화기 등록 ID 또는 미감지·지원 불가 오류; `local` OpenCV + `device` 생체정보 쓰기 | `J:com/tvt/search/view/d.java:106-169,302-313`; `J:defpackage/ac.java:558-590`; `J:defpackage/cw3.java:6684-6685` | 동의된 테스트 얼굴로 감지·등록 재조회·삭제 가능성 확인; 현지 감지를 얼굴 인식으로 계산하지 않음 |
| P09.2 C O/N | 번호판 라이브러리·차량/소유자 추가, 기존 검색 | 새 항목/검색 결과 또는 기기 미지원·중복 오류; `device` 개인정보 쓰기 | `J:com/tvt/search/AddLicensePlateActivity.java:30-70`; `J:defpackage/cw3.java:7719-7721,8000-8002,8089-8091`; [07](07-ai-cloud-services.md) | 테스트 번호판 등록→조회/검색→삭제 및 입력 검증 비교 |

### 10. 장치 목록·추가/제거

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P10.1 C G/U/O+F | QR 스캔/수동 입력/LAN 검색으로 장치 발견·로컬 추가 | 식별/로그인/중복·권한 오류, 항목 생성; `local` discovery/목록 | `J:com/tvt/devicemanager/LocalDeviceActivity.java:2052-2055,2106-2164,2425-2451`; [05](05-device-controls.md) | 알려진 QR/수동/SN·LAN 실패 fixture 각각 검색→목록 재조회 |
| P10.2 C U/O | 소유 장치 bind·등록/transfer, 공유 장치 수락 | 소유권/접근권 변화 또는 이미 묶임·코드 오류; `account` | `/sdk/deviceBind`, `/sdk/deviceRegister`, `/sdk/deviceTransfer` [02](02-protocol-api.md#devices-groups-and-configuration-71-classes); `J:com/tvt/devicemanager/LocalDeviceActivity.java:2093-2164` | 제2 세션의 소유권·채널 접근 재조회; 로컬 추가와 계정 bind 구분 |
| P10.3 C O | 목록 정렬·그룹/이름 수정, 로컬 제거 vs 계정 unbind | 목록/그룹 변경, 계정 소유권 유지 또는 해제; `local`/`account` | `J:com/tvt/devicemanager/LocalDeviceActivity.java:2348-2390`; `/sdk/deviceUnBind`, `/sdk/deviceReName`, group routes [02](02-protocol-api.md#devices-groups-and-configuration-71-classes) | 각 제거 동작 후 앱 재시작·제2 세션·서버 목록 비교해 범위를 식별 |

### 11. 장치 정보·설정

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P11.1 C O/R/N | 기본/채널/녹화/알람/네트워크/디스크 상태 열기 | 장치 측정값 또는 접속·권한 오류; `device` read | `J:com/tvt/device/ui/information/DeviceCommonInfoActivity.java:342-397,451-494`; `DeviceChannelInfoActivity.java:247-319`; [05](05-device-controls.md) | 알려진 상태 변경 전후 재조회, R의 가려진 항목 비교 |
| P11.2 C O/N | SD loop·녹화 일정·PIR/라인/경계/네트워크 스위치 | 재조회한 설정 변화 또는 능력/권한 오류; `device` write | `J:com/tvt/devicemanager/DeviceSDCardActivity.java:382-394`; `ScheduleSettingActivity.java:934-951`; `DeviceInfoActivity.java:267-337,465-599` | 쓰기→재조회→앱 재시작 후 지속성, 실패 시 원값 유지 |
| P11.3 C O | 장치 암호·전원/진단·시간·펌웨어 확인/업그레이드 | 재인증/새 모드·업그레이드 상태 또는 불일치/지원 불가; `device` write | `J:com/tvt/device/ui/ModifyDevicePassActivity.java:571-579,817-863`; `PowerSettingActivity.java:65-80`; `DeviceCloudUpgradeActivity.java:404-423,820-950` | 승인된 테스트 장치에서 읽기→쓰기→새 자격/상태·복구 확인; 업데이트는 별도 통제 |
| P11.4 C O | SD 포맷·재부팅 | 명시적 확인 후 저장소 비움/재부팅, 취소 시 무변화; `device` destructive | `J:com/tvt/devicemanager/DeviceSDCardActivity.java:64-76,398-407`; `/sdk/DeviceReboot`, `/sdk/DeviceFormatLocalStorage` [02](02-protocol-api.md) | 시험 장비에서만 확인/취소 각각 실행, 완료 후 독립 상태 재조회 |

### 12. 도어벨

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P12.1 C O+F | Wi-Fi reset/input/AP 연결→설정 전송→bind | 온라인 도어벨/계정 항목 또는 AP·암호·TCP·bind 실패; `local` Wi-Fi/TCP→`device`→`account` | `J:com/tvt/devicemanager/doorbell/WifiConfigInputActivity.java:66,95-111`; `WifiConfigConnectActivity.java:197-335`; `J:defpackage/jx0.java:152-190,461-465`; [05](05-device-controls.md) | 단계별 실패를 주입하고 실제 네트워크 접속·계정 bind·재시작 후 재발견 확인 |
| P12.2 C O+F | 초인종 invite 수신→수락/거절/종료 | call 화면·양방향 음성/영상 또는 만료·권한 오류; `device`+push+마이크 | `J:com/tvt/network/MainViewActivity.java:1178-1194`; `J:com/tvt/devicemanager/doorbell/DoorbellVideoTalkActivity.java:469-509`; [06](06-audio-talk.md) | invite 상태별 상대쪽 연결/Bye·Reject·task 해제와 60초 만료 비교 |
| P12.3 C O | push·시간대·유무선 차임·방해 금지·leave-word 선택 | 장치 설정 재조회 또는 미지원/오프라인 오류; `device` | `J:com/tvt/devicemanager/DeviceInfoActivity.java:365-381,1172`; `J:com/tvt/devicemanager/doorbell/leavewordaudio/LeaveWordAudioActivity.java:209-303`; [06](06-audio-talk.md) | 실제 차임/저장 clip ID·push/시간대 설정을 읽기→쓰기→재조회 |
| P12.4 C O | 도어벨 활성화와 Wi-Fi 재설정 | 활성 상태/연결 복구 또는 이미 활성·암호 오류; `device`+`account` | `J:com/tvt/devicemanager/DeviceInfoActivity.java:364-381,1451`; [01](01-ui-feature-inventory.md#사용자-기능-목록); [05](05-device-controls.md#qr-wi-fi-firmware-and-other-hardware-controls) | 활성 전후 장치 목록·push/통화 가능 여부와 재프로비저닝 실패 복구 비교 |

### 13. 경계/방어 설정

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P13.1 C O/N | 보호 설정 클릭→방어 목록/추가/상세, 녹화 일정 편집 | 장치/권한 게이트를 통과하면 설정과 저장 결과; 미지원·권한 오류이면 비노출/설명 가능한 오류; `device` | `J:com/tvt/live/view/ServerListViewLayout2.java:541-565,1235-1266`; `J:com/tvt/live/LiveViewLayout.java:4354-4378`; `J:com/tvt/live/DevDefenseCfgActivity.java:233,333`; [14](14-reachability-and-route-gaps.md) | 지원·미지원 모델에서 보호 설정 노출/오류→추가·수정·재조회; 클릭 경로는 정적 확인됐으나 저장 성공은 참조 실행으로 확인 |

### 14. 푸시 메시지

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P14.1 C U/O+F | 알람/시스템 메시지 수신·탭, 오프라인 뒤 재접속 | 알림/목록/미읽음·중복 처리 또는 권한 거부·누락; `account` push+`local` cache | `J:com/tvt/push/MyFirebaseMessagingService.java:33-99`; `J:com/tvt/push/tvt/PushMessageSocket.java:97-201`; `J:com/tvt/push/PushMessageActivity.java:280-295`; [04](04-alarms-push.md) | 같은 event ID를 live/offline/Push2 경로로 보내 목록 ID·순서·알림 클릭 비교 |
| P14.2 C O/R | 상세 사진/얼굴·번호판 보기→live/playback, 읽음/삭제 | 정확한 장치·시각 영상과 read/delete 상태 또는 미디어/권한 오류; `local`/`account` 경계별 | `J:com/tvt/push/PushMessageActivity.java:1466-1600,1874-1932,2078-2087,2175-2300`; [04](04-alarms-push.md) | 알려진 알람 ID로 상세→재생 앞당김 시각→재조회; 로컬 삭제와 서버 상태 구분 |
| P14.3 D U | `/sdk/getDeviceAlarm*` 범용 페이지/카운트 UI 도달성 | 직접 UI 없음이면 declared-only; `account` | [04](04-alarms-push.md#native-device-callback-boundary-and-gaps); [02](02-protocol-api.md#alarm-events-and-push-32-classes) | 참조 UI 호출 trace에서 route 사용 여부 확인; 사용되지 않으면 목록 parity에 강제하지 않음 |

### 15. 푸시 설정

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P15.1 C U/O+F | 전역·기기별 Push1/Push2/IPC·이벤트/스케줄 스위치 변경 | 서버 재조회와 실제 알림 변화 또는 브랜드/권한/지원 오류; `account` | `J:com/tvt/pushconfig/PushConfigMainActivity.java:339-408,670-750`; `Push2ConfigDetailActivity.java:883-937`; [04](04-alarms-push.md) | 스위치 저장→새 세션 재조회→해당 이벤트 발생/비발생 비교 |
| P15.2 C U+F | 새 push token 등록·refresh | 서버가 새 endpoint에 알림 전달 또는 전달 실패; `account`+browser push | `/sdk/sendNotificationToken` [02](02-protocol-api.md#alarm-events-and-push-32-classes); `J:com/tvt/push/MyFirebaseMessagingService.java:153-163`; [04](04-alarms-push.md) | 초기/회전 token 각각 실제 배달·기존 token 만료 확인; APK refresh broadcast 불일치 때문에 단순 저장은 불합격 |

### 16. 사용자·보안

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P16.1 C U | 프로필·아바타·QR, 전화/메일 바인드·변경 | 새 값/QR 또는 코드·중복 오류; `account` | `J:com/tvt/user/view/activity/UserManagerActivity.java:387-440,634-677`; `/sdk/setUserInfo`, `/sdk/UserUploadHeadImg`, `/sdk/modifyPhone`, `/sdk/modifyEmail` [02](02-protocol-api.md#authentication-and-account-47-classes) | 쓰기 후 제2 세션 프로필 재조회, QR 재스캔/만료 확인 |
| P16.2 C U | 비밀번호 변경·계정 종류 변경·로그아웃 | 재인증/종류별 권한 또는 변경 오류; token 무효화 `account`+`local` | `J:com/tvt/user/view/activity/SafeSettingActivity.java:67-104,301-349`; `J:defpackage/go4.java:407-437`; [09](09-auth-network.md) | 성공 뒤 이전 token/비밀번호 거부, 타 세션·P2P 세션 처리 비교 |
| P16.3 C U | 제3자/LINE 바인드·해제 | 연계 상태 변화, 이미 연결/redirect 오류; `external`+`account` | `/sdk/userLoginedBindThird`, `/sdk/userLoginedUnBindThird`, `/sdk/linkExternalApp`, `/sdk/unLinkExternalApp` [02](02-protocol-api.md#authentication-and-account-47-classes); [09](09-auth-network.md) | 공급자별 callback 검증, 바인드→재조회→해제 후 로그인 능력 비교 |
| P16.4 C U | 계정 탈퇴: 본인 확인 코드→확인/취소 | 성공/실패 화면, 재로그인 차단·token 삭제 또는 잘못된 코드/보류; `account` irreversible | `J:com/tvt/protocol_sdk/request/UserUnRegisterRequest.java:11-38`; `J:com/tvt/user/view/activity/RemoveAccountActivity.java:184-199`; `RemoveAccountOkActivity.java:21-31`; [09](09-auth-network.md) | 탈퇴 전 취소 무변화, 테스트 계정 성공 후 로그인/공유/장치 소유권 결과와 세션 해제 확인 |

### 17. 장치 공유·친구

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P17.1 C O/U | 계정/친구 검색·신청·수락, 그룹 만들기/편집 | 친구·그룹 목록 변화 또는 대상 없음/중복/거절; `account` | `J:com/tvt/user/view/activity/ShareManagerActivity.java:47-59`; `/sdk/searchMyFriendByLoginName`, `/sdk/sendApplyForAddFriends`, `/sdk/agreeApplyToNewFriendWithApplyId`, group routes [02](02-protocol-api.md#sharing-and-friends-51-classes) | 두 계정에서 신청→수락→그룹/친구 목록 재조회·거절 비교 |
| P17.2 C O/U | 장치/채널/권한 선택→계정 또는 친구에게 공유 | 발신·수신 목록, 제한된 접근 또는 계정 없음/권한 거부; `account` | `J:com/tvt/devicemanager/LocalDeviceActivity.java:1923,2110-2164,2399`; `/sdk/shareChl`, `/sdk/SharedCameraChlsToFriend`, `/sdk/sharedChlsToFriend` [02](02-protocol-api.md#sharing-and-friends-51-classes) | owner/recipient 두 세션에서 channel/permission matrix를 조회하고 금지된 live/playback/PTZ를 거부 확인 |
| P17.3 C U/R | 받은 공유 수락·일괄 수락·QR 스캔 | 공유 장치가 보이거나 만료/이미 수락/소유자 취소 오류; `account` | `/sdk/acceptShared`, `/sdk/batcjAcceptShared`, `/sdk/batcjAcceptDeviceShared` [02](02-protocol-api.md#sharing-and-friends-51-classes); `J:com/tvt/devicemanager/LocalDeviceActivity.java:2435-2439` | 수락 전후 수신 목록/채널 접근, 중복 수락과 거부 응답 비교 |
| P17.4 C O/R | 공유 권한 수정·채널 제거·전체 취소 | 수신자의 실제 접근 즉시 축소 또는 소유권/네트워크 오류; `account` | `/sdk/setSharedChlPermission`, `/sdk/removeShareChlByChlID`, `/sdk/removeShareChlByShareID`, `/sdk/deleteShared` [02](02-protocol-api.md#sharing-and-friends-51-classes) | 열린 수신 세션 포함 재조회 및 금지 조작 재시도; 발신/수신 화면 동기화 확인 |
| P17.5 D O | `getSharedListToAccount` 등 대체 조회 라우트/공유 권한 후보 UI | reply 이름 불일치 또는 미도달; `account` | [02](02-protocol-api.md#specific-gaps-and-interpretation): `getSharedListToAccount` reply가 `/sdk/deleteShared`, `searchMyFriendByRemark` matching reply 없음 | 호출 trace와 callback key 검증; 정상 목록이 온다는 가정 없이 다른 도달 경로 사용 여부 판정 |
| P17.6 C O/R+F | 공유 QR 생성/표시·스캔, IPC/NVR 상세 및 채널별 편집 | QR의 지정 권한/기기와 수신 상세 또는 만료·무효 QR 오류; `account`+`local` 카메라 | `J:com/tvt/devicemanager/LocalDeviceActivity.java:1923,2399,2435-2439`; `J:com/tvt/user/view/activity/ShareManagerActivity.java:47-59`; `R:layout/item_my_share.xml`; [01](01-ui-feature-inventory.md#사용자-기능-목록) | QR 값은 기록하지 않고 소유자→수신자 스캔 뒤 장치/채널/권한 재조회, QR 재사용·만료 비교 |

### 18. 클라우드 녹화·VAS·결제

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P18.1 C U/V/O | 클라우드 채널/날짜/기록 조회→재생·seek | 맞는 영상 또는 구독 없음/객체·복호화 오류; `account`+cloud native | `J:com/tvt/cloudstorage/CloudStorageActivity.java:240-392,495-568`; `CloudPlayerActivity.java:2654-2685,3690-3726`; [07](07-ai-cloud-services.md) | 같은 record ID/시각 프레임, 만료 OSS token·암호화 key 오류와 재발급 확인 |
| P18.2 C V/O+F | cloud MP4 다운로드·재시도·취소, 기록 삭제 | 한 active task의 진행률·재생 파일/목록 제거 또는 공간/토큰/삭제 실패; `local`+`account` | `J:defpackage/lo.java:228-270,313-339,518-603`; `/sdk/RemoveCloudRecord` [02](02-protocol-api.md#cloud-storage-and-records-39-classes); [03](03-media.md) | 100개 queue 경계·동시성, 파일 무결성, 취소/재개와 삭제 뒤 서버 재조회 |
| P18.3 C G/U/V+B | VAS 메뉴→서비스/적격 장치/채널/상품 상세 | 로그인 우회, 적격/무료/유료/비지원 표시; `account` | `J:defpackage/ef2.java:234-245,303-312`; `J:com/tvt/valueaddedservice/VASServiceDetailActivity.java:259-280,533-592`; [07](07-ai-cloud-services.md) | 게스트/비적격/적격·브랜드별 카탈로그/가격/기간·선택 가능 여부 비교 |
| P18.4 C V | 신청·갱신·자동 갱신 선택·결제 H5→구매기록·서비스 상태 | order ID, pay URL, 결제/취소/중복 처리와 갱신 설정·활성 기간; `account`+`external` 결제 | `/sdk/applyVASService`, `/sdk/renewalVASService`, `/sdk/payVasInfo`, `/sdk/getVASApplyRecordList`; `J:com/tvt/valueaddedservice/VASServiceDetailActivity.java:259-280,723-785` | 테스트 상품/결제에서 신청→결제 callback→상태·기록·자동 갱신 재조회; 성공 toast만으론 불합격 |
| P18.5 C V/O | cloud 녹화 motion/AI/sensor·암호화 설정, on/off | 각 이벤트 녹화와 저장 설정 변화 또는 비적격 오류; `account`+`device` | `J:com/tvt/valueaddedservice/VASCloudStoreSettingActivity.java:111-174,190-236,326-444`; `/sdk/SetCloudRecordSwitch`, `/sdk/setOnOffDeviceConfig` [02](02-protocol-api.md) | 세 스위치 각각 저장→재조회→유발 event 기록 확인; APK `swSensorOpen` 참조 중복을 별도 비교 |
| P18.6 D V | `/sdk/setVasInstSwitch` 서비스 스위치 대체 경로 | executor가 비어 있어 변경 성공 미입증; `account` 후보 | `J:com/tvt/protocol_sdk/request/VASSetInstSwitchRequest.java:10-27`; [14](14-reachability-and-route-gaps.md) | UI 호출 유무를 추적하고 스위치 상태 재조회; 선언만으로 성공 처리 금지 |
| P18.7 D V/O | `/sdk/deviceCloudStorageIsValid` 적격성 대체 경로 | 앱 모델 호출은 있으나 SDK callback 본문이 비어 있어 결과 미입증; `account` 후보 | `J:defpackage/he1.java:164-203`; `J:com/tvt/protocol_sdk/TVTOpenSDK.java:1080-1085`; [14](14-reachability-and-route-gaps.md) | 실제 UI 호출·callback/timeout을 캡처하고 다른 적격성 경로와 비교 |
| P18.8 C V/O | `/sdk/getValidCloudStorageChlList` 클라우드 채널 조회 | 클라우드 화면 호출 경로가 있으나 SDK callback 본문이 비어 있어 목록 성공 미입증; `account` | `J:com/tvt/cloudstorage/CloudStorageActivity.java:690`; `J:defpackage/w60.java:334-336`; `J:defpackage/l60.java:378-389`; `J:com/tvt/protocol_sdk/TVTOpenSDK.java:2468-2473`; [14](14-reachability-and-route-gaps.md) | 적격 장치의 UI 호출→응답/timeout→실제 채널 목록을 참조 앱에서 기록 |
| P18.9 C V/O | `/sdk/GetCloudVideoList` 클라우드 영상 목록·다운로드 준비 | 다운로드 경로가 호출하나 matching native reply 메서드는 미확인; OSS/object 목록 또는 오류; `account`+cloud | `J:defpackage/lo.java:228-269,313-339`; `J:defpackage/l60.java:275-296`; [14](14-reachability-and-route-gaps.md) | 다운로드 UI에서 호출·callback·timeout과 파일 결과를 별도로 캡처; request와 parser 존재만으로 성공 판정 금지 |

### 19. 로컬 파일

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P19.1 C U/O+F | 스냅샷·녹화 목록/날짜 검색→이미지·동영상 열기 | 저장된 파일과 메타데이터 또는 권한/손상 파일 오류; `local` | `J:defpackage/tr3.java:144-185,287-320,483-496`; `J:com/tvt/filemanager/FileManagerActivity.java:175-188,250-268`; [03](03-media.md) | `.avi/.bmp/.png/.mp4` fixture로 정렬/검색/재생, 새 파일 즉시 반영 비교 |
| P19.2 C U/O+F | 선택 파일 삭제, 저장 공간 부족/보존 주기 | 지정 파일만 제거 또는 실패; `local` | `J:com/tvt/filemanager/FileManagerActivity.java:386-399`; `J:com/tvt/config/ui/LocalConfigActivity.java:1038-1207` | 삭제 취소/확인, 원본·목록·스토리지 상태 재조회; 보존 조건 경계 테스트 |
| P19.3 D U | `FileSyncSDK`의 cloud↔local sync UI 도달성 | SDK 초기화만 확인, 사용자 시작점 미확인; 외부 sync 미입증 | `J:com/tvt/file_sdk/FileSyncSDK.java:20-76,115-127`; `J:com/tvt/launch/LaunchApplication.java:600`; [07](07-ai-cloud-services.md#file-sdk-and-cloud-service-boundary) | 참조 앱 UI·runtime call trace에서 시작점 확인 전에는 로컬 파일 관리와 합치지 않음 |
| P19.4 C U | 로컬 이미지 보기에서 공유 선택·전달 | Android 공유 대상 선택/취소와 선택한 원본 이미지 전달 또는 권한·대상 없음 오류; `local` | `J:com/tvt/filemanager/BigImageActivity.java:349-361,456-467`; [03](03-media.md) | 동일 이미지의 MIME·내용/파일명, 취소, 대상 앱 부재·권한 거부를 비교; 웹 대상 공유 기능은 지원 브라우저별로 검증 |

### 20. 로컬 설정

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P20.1 L U/O | 자동 접속, 시작 화면, 회전, OSD/화질 적응, PTZ 제스처·방향 변경 | 화면·조작 방식 변화, 잘못된 값 거부; `local` | `J:com/tvt/config/ui/LocalConfigActivity.java:489-711,929-1010,1038-1093`; [05](05-device-controls.md) | 각 토글 저장→재시작·새 세션에서 표시/동작 비교; 장치 설정 쓰기로 오인하지 않음 |
| P20.2 L U/O+F | 캡처 장수/분할, 녹화 순환·보존, 알림 선행 시간·캐시 | 다음 산출물/알람 재생 구간에 반영; `local` | `J:com/tvt/config/ui/LocalConfigActivity.java:1097-1207`; `J:com/tvt/push/PushMessageActivity.java:2255-2300` | 설정 전후 동일 입력으로 파일 수·보존·playback 시작 시각 비교 |

### 21. 원격 설정

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P21.1 C O/N+B | 브랜드 메뉴→장치 선택→원격 웹 설정 읽기/쓰기 | 페이지/설정 재조회 또는 연결·권한·페이지 로드 오류; `device` via WebView JS bridge | `J:defpackage/ef2.java:221-224,473-479`; `J:com/tvt/config/ui/RemoteWebActivity.java:385-423,798-888,1132-1150`; [05](05-device-controls.md) | 실제 내려온 페이지/JS 명령 trace를 저장, 같은 항목 읽기→쓰기→장치 재조회; Java만으로 페이지 기능 추정 금지 |

### 22. Tyco 경보 패널

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P22.1 C T+B | 별도 Tyco 가입/로그인·패널 추가/로그인/목록/해제 | 패널 목록·session, 잘못된 암호/만료/비브랜드 비노출; `tyco` REST | `J:defpackage/ef2.java:490-516`; `J:defpackage/ki.java:470-602`; `J:com/tvt/tyco/ui/activity/panel/PanelMainActivity.java:20-48`; [07](07-ai-cloud-services.md) | TVT 로그인과 독립된 세션·cookie/token 만료, 패널 unlink 뒤 목록 비교 |
| P22.2 C T | 홈 status, 구역·장치·사용자·이벤트/고장/알람 열기 | REST 데이터·진행 task 또는 패널 오프라인/권한 오류; `tyco` | `J:defpackage/ki.java:478,504,531-535,590-602`; [04](04-alarms-push.md#separate-tyco-panel-alarm-notification-plane) | 알려진 패널 이벤트·구역 상태로 각 탭 재조회, pagination·timestamp 비교 |
| P22.3 C T | 전체/구역 arm·disarm, 사용자 코드·이름·시간 설정 | panel/task 완료 후 실제 상태 또는 코드·권한 오류; `tyco` write | `J:defpackage/ki.java:485-511,542,578,586-588`; `J:com/tvt/tyco/ui/fragment/home/PanelHomeViewModel.java:418,1170`; [07](07-ai-cloud-services.md) | 안전한 시험 패널에서 POST→process_status→독립 panel status 및 이벤트 비교 |
| P22.4 C T | home automation output on/off·timer | relay 실제 상태/타이머 종료 또는 task 실패; `tyco` write | `J:com/tvt/tyco/ui/fragment/output/PanelOutputViewModel.java:98-117,338-369`; `J:defpackage/ki.java:473-475,507-509`; [05](05-device-controls.md) | 물리 출력/상태 재조회, timer 후 복귀; coroutine 복원 오류 때문에 task 완료까지 검사 |
| P22.5 C T+F | Tyco 알림 옵션·email·token 등록→알람 수신 | 선택 이벤트만 통지 또는 token/권한 실패; `tyco` REST + push | `J:defpackage/ki.java:482,491-493,550-563`; `J:com/tvt/tyco/ui/fragment/notification/NotificationViewModel.java:35-43,413-447`; [04](04-alarms-push.md) | 5개 필터별 test event와 email/push 수신, token 회전 후 배달 비교 |

### 23. 도움·정보·웹 문서

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P23.1 C G/U+B | Help/About, 약관·개인정보·AI 동의·새 앱/체험 웹 열기 | 해당 지역·브랜드 페이지 또는 URL/네트워크 오류; `external` content | `J:com/tvt/about/AboutActivity.java:49-105`; `J:com/tvt/web/WebActivity.java:139-164`; `J:com/tvt/ai/search/AISearchInputActivity.java:527-535`; [07](07-ai-cloud-services.md) | 실제 URL/redirect/문서 버전·뒤로가기, 비노출 브랜드 비교; APK에 HTML이 없으므로 캡처 필요 |
| P23.2 C U | About 로고 반복 탭→숨겨진 두 debug 화면 | 저장된 진입 플래그·화면 및 변경 효과 또는 브랜드/설정 비노출; `local` | `J:com/tvt/about/AboutActivity.java:55-79,199-222,260-267`; `M:136-137`; [14](14-reachability-and-route-gaps.md) | 깨끗한 설치에서 활성 탭 수·설정 지속성·각 조작 결과를 확인하고, 접근 가능한 모든 진단 조작의 효과와 오류도 동등성 대상으로 기록 |
| P23.3 C U | About 체험 항목→Experience 화면 | 체험 화면/진입 오류 또는 브랜드 비노출; `local`+외부 콘텐츠 가능 | `J:com/tvt/about/AboutActivity.java:88-90,157-164`; `M:114`; [14](14-reachability-and-route-gaps.md) | 실제 노출 브랜드에서 열기·뒤로가기·내용/링크와 비노출 조건 비교 |

### 24. 조건부 거주자·세대 관리

| ID·상태·fixture | 동작 | 관찰/오류 · 효과 | APK 근거 | 검증 |
| --- | --- | --- | --- | --- |
| P24.1 C U | 로그인 후 resident 상태 조회→메뉴 노출→세대 관리 H5 열기 | `total > 0`일 때만 메뉴와 실제 페이지·권한별 내용 또는 0/오류/페이지 로드 실패; `account`+`external` 웹 콘텐츠. H5 내부 행위는 미확보 | `J:defpackage/ef2.java:96-113,226-231,249-255,480-485`; `J:defpackage/he1.java:527-563`; [14](14-reachability-and-route-gaps.md) | 같은 계정/브랜드/지역에서 `total=0`과 양수, 로그인 전후 메뉴·URL·리다이렉트·페이지 동작을 비교; 내려온 H5의 각 읽기/쓰기는 별도 계약으로 추가하고 실제 효과를 확인 |

## 요청·플랫폼 범위 연결과 공통 실패 계약

| 분류 | 인벤토리 | 이 문서의 실행 계약 | 남은 범위 |
| --- | ---: | --- | --- |
| TVT 계정/인증 | 47 request classes | P02, P16, P22.1의 **TVT와 Tyco 분리** | [02](02-protocol-api.md#authentication-and-account-47-classes)의 각 route는 사용 여부·응답 확인 필요 |
| 장치/그룹/구성 | 71 | P03, P05~06, P10~13, P21 | UI 호출과 직접 `fu3` 장치 XML, JNI 요청은 별개 |
| 공유/친구 | 51 | P17 | 구형/대체 목록 route와 reply mismatch 개별 판정 |
| 알람/푸시 | 32 | P14~15, P22.5 | FCM/TVT socket/Push2/Tyco는 다른 전달 plane |
| 클라우드/저장/VAS | 39 | P18~19, P11.4 | 빈 executor/callback, route 충돌과 결제 결과 확인 |
| 미디어/장치 session | 25 | P03~09, P12 | `/sdk` NAT 0 반환 stub 및 JNI export 없는 경로 대신 실제 `NetClientProtocal` 사용 여부 확인 |
| 기타 서비스 | 16 | P08 번역, P23, P24.1 등 | 라우트별 UI 도달성과 서버 응답 따로 확인 |
| **합계** | **281** | 23개 기존 UI 영역과 조건부 거주자 관리의 77개 작업/오류/효과 계약 | 281개가 모두 사용자 기능이거나 정상 동작한다는 뜻은 아님 |

모든 쓰기 계약은 `거부된 권한 → 상태 불변`, `오프라인/timeout → 성공 표시 없음`, `중복 재시도 → 중복 주문·공유·파일 없음`, `세션 만료 → 인증 갱신/로그인`, `브랜드/모델 미지원 → UI 비노출 또는 설명 가능한 오류`, `취소 → 외부 부작용 없음`을 공통 negative fixture로 돌린다. 브라우저 카메라/마이크·Web Push·파일 저장·Wi-Fi/LAN 탐색·Bluetooth·백그라운드 도어벨 통화는 Android API와 동일하다고 가정하지 말고 P10/P12/P14/P19에서 실제 브라우저 권한과 가능한 대체 경로를 별도 기록한다. [01](01-ui-feature-inventory.md#도달성android-전용-경계와-남은-공백), [09](09-auth-network.md#web-service-parity-gates).

## 동등성 완료를 막는 현재 공백

1. **서버/장치 oracle 부재.** 23 UI 영역과 281 요청의 이름·대표 호출 경로는 확인했지만 실제 TVT/클라우드/결제/패널 응답, 기기별 기능 플래그, 지역·브랜드 조합은 기록되지 않았다. `ok`/`err` golden trace가 없으면 위 계약은 *미검증*이다.
2. **브라우저 연결 수단 미확정.** `NetClientProtocal`, `ProtoSDK`, `CloudStorageSDK`, 디코더와 로컬 Wi-Fi 프로비저닝은 Android 네이티브/플랫폼 경계다. 공급사의 지원되는 웹 SDK/API 또는 승인된 서버 gateway, 프로토콜·계약상 사용 권한, 보안 세션 설계가 필요하다. [08](08-native-abi-jni.md), [09](09-auth-network.md).
3. **확인된 코드 공백.** `/sdk/getDeviceLocalStorageStatus` route가 HDD alarm request로 덮인다. `CheckImgVerifyCodeRequest`와 `VASSetInstSwitchRequest`는 빈 executor이고, cloud 유효성/채널 callback 두 개가 비어 있다. 공유 조회 한 건은 `deleteShared`로 답하고, 일부 VAS/CloudVideo reply가 없다. NAT live/audio entry는 0 반환 stub이다. 이 선언들은 직접적인 parity 근거가 아니다. [02](02-protocol-api.md#specific-gaps-and-interpretation), [10](10-completeness-review.md#보고서-사이-불일치와-수정-상태).
4. **웹 콘텐츠와 복원 한계.** 결제/원격 설정/정책 HTML은 APK 밖에서 갱신된다. `SequentialTaskManager`, legacy search, Tyco timer/output callback 등 9개 실질 `com.tvt` 메서드는 JADX에서 완전히 복원되지 않았다. 300개 별도 `*ActivityPage` 선언은 제품 UI 도달성이 확인되지 않았다. [07](07-ai-cloud-services.md), [10](10-completeness-review.md).
5. **외부 계정·결제·개인정보 시험 준비.** 소유/수신 두 TVT 계정, 지원·미지원 장치/도어벨, Tyco 패널, AI 녹화 샘플, 클라우드/VAS 테스트 상품, 승인된 결제 수단, 개인정보/생체정보 테스트 데이터가 있어야 P09/P16~18/P22를 실행할 수 있다. account removal과 firmware/format 시험은 재설정 가능한 대상이 필요하다.

**판정 방식:** 행별로 `not run / unsupported by reference / blocked by fixture / mismatch / pass`를 기록하고, pass에는 참조 앱과 웹의 동일 조건 trace 및 후속 상태 확인을 붙인다. `D` 행의 미도달은 기능 성공이 아니다. 모든 필수 행과 실제 노출된 조건부 분기의 pass가 모이기 전에는 “100% 기능 동등”이라 부를 근거가 없다.
