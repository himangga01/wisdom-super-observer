# SuperLive Plus 1.18.1 — UI 기능·화면 목록 (APK 정적 조사)

조사일: 2026-09-27. 대상은 `com.tvt.superliveplus` 1.18.1의 **이미 추출된** APK다. 이 문서는 화면과 사용자 동선을 식별한다. 계정 로그인, 장치 접속, 구매, 알림 수신, 영상 재생의 실제 성공을 주장하지 않는다. 네트워크·JNI 세부 구조는 [정적 분석](../superlive-static-analysis.md)과 [TVT 호출 맵](../tvt-call-map.md)에 있다.

## 증거와 판정 기준

- `M:n` = `C:\wso-private\superliveplus\1.18.1-2026-09-27\apktool\AndroidManifest.xml`의 줄 번호. `J:경로:줄` = 같은 보관 위치의 `jadx-full/sources/` 아래 Java 파일. `R:경로` = `apktool/res/` 아래 리소스. 줄 번호는 이 추출본에만 유효하다.
- **동선 확인**: 클릭 리스너, 명시적 `Intent`, ARouter 호출 또는 Navigation 그래프에서 연결을 확인. **조건부**: 로그인·장치 기능·브랜드 플래그·권한·지역·상품 상태에 따라 노출. **선언만**: Activity/route/리소스는 있지만 시작점이나 성공 조건을 확인하지 못함. 정적 분석으로 실행 가능성과 서비스 결과를 확정할 수 없다.
- Manifest의 Activity 선언 513개(중복을 제거하면 498개). `com.tvt.*` 165개는 모두 JADX 소스가 있다. 이 중 5개는 타사 인증/WeChat 콜백, 1개는 Huawei push 진입 Activity이므로 나머지 제품 UI/진입점 선언은 159개다. `com.sdk.*` 8개는 QR/로컬 플레이어/로그 등 공용 SDK 화면이다. `cn.zone.*`, `org.*`, `com.zone/com.scope/com.area/com.wys.*`의 300개 선언은 아래의 의심스러운 별도 묶음이다. 기본 `res/layout` 965개와 `com/tvt` Java 2,187개, `@Route`가 있는 TVT Java 140개를 목록화한 뒤 주동선, 기능별 클래스, 메뉴 XML을 대조했다. 단, `@Route` 수는 화면 수와 같지 않다. 자료: `M:78-359,473-772`, `J:defpackage/ef2.java:464-524`, `R:layout/view_live_menu.xml`.

## 시작과 주 탐색

```text
MainActivity (런처/동의/딥링크) → GuideActivity(첫 실행 조건) → MainViewActivity
                                                        ↓
                 LiveViewLayout: 채널 목록 + 다중 영상 + 상단 검색/메뉴 + 하단 조작
                    ├─ 측면 메뉴: AI 검색, 원격/로컬 설정, 장치, 파일,
                    │            부가 서비스, 푸시 설정/메시지, Help, About
                    ├─ 하단: Talk, audio, 화면 분할, playback, more
                    ├─ 영상별 메뉴: 캡처/녹화/PTZ/품질/전체화면 등
                    └─ 조건부: Tyco 패널, 도어벨, 장치 방어 설정
```

런처는 `MainActivity`이며 가이드 표시 여부에 따라 `MainViewActivity` 또는 `GuideActivity`로 간다. 메인 Activity는 단순 컨테이너에 `LiveViewLayout`을 동적으로 붙인다. 측면 메뉴는 `ef2`의 `view_live_menu` 팝업이고, 하단은 `LiveOperateBarView`다. 근거: `M:78-100`, `J:com/tvt/launch/MainActivity.java:598-615,743-756`, `J:com/tvt/network/MainViewActivity.java:550-557,699-715`, `J:com/tvt/live/LiveViewLayout.java:1872-1909`, `J:defpackage/ef2.java:354-455,464-524`, `J:com/tvt/live/view/LiveOperateBarView.java:168-179,256-281`.

| 측면 메뉴 항목 | 클릭 후 화면/동작 | 상태·근거 |
| --- | --- | --- |
| AI/영상 검색 | `AISearchInputActivity` | 동선 확인. `J:defpackage/ef2.java:171-173,526-528` |
| 원격 설정 | `RemoteConfigActivity` → 장치별 `RemoteWebActivity` | 조건부: `GlobalUnit.j2`이면 노출. `J:defpackage/ef2.java:221-224,473-479,529-532`; `J:com/tvt/config/ui/RemoteConfigActivity.java:80` |
| 로컬 설정 | `LocalConfigActivity` | 동선 확인. `J:defpackage/ef2.java:194-197` |
| 장치 관리 | `LocalDeviceActivity` | 동선 확인. `J:defpackage/ef2.java:180-183` |
| 거주자 관리 | 웹 기반 household management | 기본 `gone`, `j` 성공 콜백으로 노출될 수 있어 조건부. `J:defpackage/ef2.java:100-113,226-232,480-485` |
| 파일 관리 | `FileManagerActivity` | 동선 확인. `J:defpackage/ef2.java:185-188` |
| 부가 서비스 | `ValueAddedServiceActivity` | 로그인 및 브랜드 모드에 좌우됨. `J:defpackage/ef2.java:234-246,303-314,486-487` |
| 푸시 설정/메시지 | `PushConfigMainActivity` / `PushMessageActivity` | 알림 권한 안내 후 설정. 일부 브랜드 모드에서 숨김. `J:defpackage/ef2.java:199-219,488-489,506-517` |
| Tyco, Help, About | Tyco 패널 / `HelpActivity` / `AboutActivity` | Tyco는 `GlobalUnit.a2`, Help는 `GlobalUnit.n0` 조건. `J:defpackage/ef2.java:175-177,190-191,490-502,533-539` |

## 사용자 기능 목록

| 영역 | 고유 화면·행위 | 판정·증거 |
| --- | --- | --- |
| 시작·온보딩 | 시작 화면, 개인정보 문서 WebView, 첫 실행 가이드, 언어/권한 처리, 알림·딥링크 진입 | 동선 확인/조건부. `J:com/tvt/launch/MainActivity.java:598-615,743-761`, `J:com/tvt/launch/GuideActivity.java:198-247,326-330`; `M:78-100` |
| 로그인·가입·복구 | 이메일/전화 로그인, 확인 코드, 가입, 비밀번호 찾기, 제3자 계정 연계, IT20 웹 로그인 | 메뉴 헤더에서 로그인 유형에 따라 분기. 개별 등록·복구 화면은 각 로그인 흐름에 속함. `J:com/tvt/user/view/activity/UserFragment.java:550-567`, `J:defpackage/ef2.java:234-246`; `M:149-200,255-256` |
| 라이브 영상 | 장치/채널 목록, 여러 영상 타일, 채널 선택·닫기, stream 품질/해상도, 전체화면·회전, 온라인/오프라인 안내 | 핵심 동선 확인; 실제 프레임은 미검증. `J:com/tvt/network/MainViewActivity.java:699-715`, `J:com/tvt/live/LiveViewLayout.java:2097,2581-2624`, `J:com/tvt/live/view/ServerListViewLayout2.java:461-468,542-550`; `R:layout/view_live_layout.xml` |
| 라이브 조작 | 듣기/양방향 Talk, 1·2·4·6·8·9·13·16 분할, 선택 채널 playback, '더보기' | 동선 확인. Talk은 선택 채널/기기 유형에 따름. `J:com/tvt/live/view/LiveOperateBarView.java:168-179,284-347`, `J:defpackage/a63.java:138-145`; `R:layout/view_live_bottom_tab.xml` |
| 영상별 도구 | 스냅샷, 로컬 녹화, PTZ/pan-tilt, 화질, 어안, 렌즈 조절, 조명/경보, 출입 제어, 전체화면 | UI 리소스 및 영상 메뉴 확인; 카메라 능력·권한별 노출. `R:layout/video_menu_view.xml`, `J:com/tvt/live/LiveViewLayout.java:2579-2624` |
| 라이브 '더보기' | 즐겨찾기, 수동/소리/조명 경보, 와이퍼, AI 모드, AI/사진/이름/이벤트 검색, 얼굴·번호판 등록/관리, RS485 | 클릭과 세부 화면 연결 확인; `dj2.D()` 등 장치 능력에 따라 항목을 감춤. `J:defpackage/dj2.java:154-280,283-293,340-370,455-594`; `R:layout/view_live_bottom_more_layout.xml` |
| 재생 | 선택 채널 녹화 검색, 달력·시간축, 이벤트/주간/속도, 백업·다운로드, 캡처/로컬 녹화 | 라이브·푸시 상세에서 진입 확인. `J:com/tvt/live/view/LiveOperateBarView.java:295-313`, `J:com/tvt/playback/PlaybackActivity.java:28,196-228`, `J:com/tvt/playback/view/PlaybackViewLayout.java:4852-5057`; `R:layout/view_playback_layout.xml`, `R:layout/view_playback_calender.xml`, `R:layout/view_playback_backup_time.xml` |
| 지능형 검색 | 텍스트/음성, 이벤트, 얼굴·신체·차량 대상, 속성·장치·시간 필터, 사진 기반 검색, 결과 목록·상세 | 메뉴와 라이브 더보기에서 진입. 대상·장치 능력별. `J:com/tvt/ai/search/AISearchInputActivity.java:548-559,1245,1801`, `J:defpackage/dj2.java:464-479`, `J:com/tvt/ai/search/AISearchListActivity.java:56`, `J:com/tvt/ai/search/AIPicSearchListActivity.java:45`; `R:layout/activity_ai_search_input.xml` |
| 기존 얼굴/번호판 검색 | 얼굴 인식 등록·검색, 번호판 추가, 일반 `SearchActivity`의 검색 유형 | 라이브 더보기에서 호출 확인. `J:defpackage/dj2.java:346-354,489-491,557-585`; `J:com/tvt/search/SearchActivity.java:207` |
| 장치 목록·추가 | 장치 목록, QR 스캔/기기 QR 표시, 수동 입력, LAN 검색, 공유 장치 선택, 정렬·삭제, 장치 로그인 | 측면 메뉴에서 진입. `J:com/tvt/devicemanager/LocalDeviceActivity.java:1798-1826,2425-2451,2535-2567`, `J:com/tvt/network/MainViewActivity.java:671-674`; `R:layout/activity_local_device.xml` |
| 장치 정보·설정 | 기본 정보, 채널·알람·녹화·네트워크·사용자·디스크, Wi-Fi/SD 카드, 클라우드 암호화, 암호 변경, 펌웨어 업그레이드, 전원/진단 모드, 센서·PIR·라인/주변경계 스위치 | 장치 목록 → 상세 동선 확인; 장치 종류·권한별 UI. `J:com/tvt/devicemanager/LocalDeviceActivity.java:1798-1811`, `J:com/tvt/devicemanager/DeviceInfoActivity.java:350-561,1715-1772,2130`; `R:layout/view_device_information.xml` |
| 도어벨 | 도어벨 추가/활성화, Wi-Fi 초기화·입력·연결·바인드, 비디오 통화, push, 시간대, 유무선 차임·방해 금지·벨소리/시간, 남길 음성 | 장치 정보의 도어벨 분기와 push 호출 경로 확인; 장치 의존. `J:com/tvt/devicemanager/DeviceInfoActivity.java:364-381,1451`, `J:com/tvt/devicemanager/doorbell/DoorbellVideoTalkActivity.java:364-366,665`, `J:com/tvt/network/MainViewActivity.java:1178-1190` |
| 경계/방어 설정 | 장치별 방어 구성·추가·상세, 녹화 일정·시간 | Activity/route와 장치 설정 연결 후보. 기능 노출은 장치별 조건. `J:com/tvt/live/DevDefenseCfgActivity.java:30`, `J:com/tvt/live/DevDefenseAddActivity.java:37`, `J:com/tvt/devicemanager/ScheduleSettingActivity.java:53`, `J:com/tvt/devicemanager/DeviceInfoActivity.java:464-594` |
| 푸시 메시지 | 알람/시스템 메시지 탭, 미읽음 수, 읽음·삭제, 알람 상세의 사진/얼굴/번호판/도어벨 정보, live·playback 이동 | 메뉴 동선 확인. 실제 FCM 수신은 미검증. `J:defpackage/ef2.java:199-203,326-340`, `J:com/tvt/push/PushMessageActivity.java:280-295,1797-1815,1881-1930,2057-2065,2075-2082,2219`; `R:layout/push_message.xml` |
| 푸시 설정 | 기기별 알림, 알람 유형/스위치, IPC/Push2 상세, 권한 안내 | 메뉴 동선 확인; 장치·알림 권한 조건. `J:defpackage/ef2.java:212-219`, `J:com/tvt/pushconfig/PushConfigMainActivity.java:572,914`; `M:231-234,264` |
| 사용자·보안 | 프로필 사진/닉네임, 사용자 QR, 전화·이메일 바인드/변경, 비밀번호 변경, 제3자/LINE 바인드, 계정 종류 변경·탈퇴, 로그아웃 | 로그인 헤더 → `UserManagerActivity` → 보안 화면. 일부 하위 Activity는 선언/route만 확인. `J:com/tvt/user/view/activity/UserFragment.java:550-567`, `J:com/tvt/user/view/activity/UserManagerActivity.java:387-440,634-677,903`, `J:com/tvt/user/view/activity/SafeSettingActivity.java:67-104,301-322`; `R:layout/activity_account_manager.xml` |
| 장치 공유 | 보낸/받은 공유 관리, 계정 선택, 기기/채널/권한 선택·수정, IPC/NVR 상세, QR 생성·스캔, 공유 기기 추가 | 장치 메뉴와 공유 관리자에서 동선 확인; 로그인/권한 조건. `J:com/tvt/devicemanager/LocalDeviceActivity.java:1923,2110-2164,2399,2435-2439`, `J:com/tvt/user/view/activity/ShareManagerActivity.java:47-59`; `R:layout/item_my_share.xml` |
| 클라우드·유료 서비스 | 클라우드 녹화 목록/플레이어/다운로드·삭제, 저장소 암호화, VAS 서비스·기기·상품 상세·구매 기록·설정 | 메뉴 진입은 로그인 조건. 결제/재생 성공 미확인. `J:defpackage/ef2.java:234-246`, `J:com/tvt/valueaddedservice/ValueAddedServiceActivity.java:164`, `J:com/tvt/cloudstorage/CloudStorageActivity.java:1250-1256,1621-1625`; `M:227-245` |
| 로컬 파일 | 캡처·녹화 파일 목록, 검색, 큰 이미지 보기, 로컬 플레이어 | 메뉴에서 진입. Android 저장소 의존. `J:defpackage/ef2.java:185-188`, `J:com/tvt/filemanager/FileManagerActivity.java:188,225-231,408,426`; `M:140-142,292` |
| 로컬 설정 | 자동 연결, 가로 화면/회전 보정, 영상 자동 적응·OSD, PTZ 제스처/방향, 스냅샷 장수·분할, 녹화 순환·보존, 알림·선행 시간, 즐겨찾기·시작 화면·캐시·Wi-Fi/도메인 | 메뉴 동선과 옵션 클릭 확인. `J:com/tvt/config/ui/LocalConfigActivity.java:1038-1207`; `R:layout/activity_local_config.xml` |
| 원격 설정 | 장치 목록 → 장치 웹 구성 | 브랜드 플래그·장치 접속 조건. `J:defpackage/ef2.java:221-224,473-479`, `J:com/tvt/config/ui/RemoteConfigActivity.java:80,200-201` |
| Tyco 경보 패널 | 패널 로그인/가입·목록·추가, 홈/장치/출력/이벤트/설정, 구역·고장·알림·계정·경보·시간 | `GlobalUnit.a2`가 켜져야 메뉴/퀵 버튼 노출. `J:defpackage/ef2.java:490-496`, `J:com/tvt/live/LiveViewLayout.java:1891-1910`, `J:com/tvt/tyco/ui/activity/panel/PanelMainActivity.java:20-48`; `R:menu/tyco_bottom_nav_menu.xml`, `R:navigation/tyco_panel_navigation.xml` |
| 도움·정보 | Help, About, 개인정보/약관 웹, 체험/새 앱 안내, 숨겨진 debug 설정 | Help는 브랜드 플래그 조건, debug는 반복 조작/저장 설정 조건. `J:defpackage/ef2.java:175-191,497-502`, `J:com/tvt/about/AboutActivity.java:49-105`, `J:com/tvt/live/LiveViewLayout.java:4322-4332`; `R:layout/view_live_menu.xml` |

## Manifest 화면 대조표

아래는 `com.tvt.*` Activity 165개의 **누락 없는 이름 목록**이다. 같은 접두사는 표 머리의 패키지 뒤에 붙는다. 이름이 있다는 사실만으로 화면이 일반 사용자에게 도달 가능하다는 뜻은 아니다. `M:78,101-286,329-359`와 각 Java 클래스 선언/`@Route`가 기본 증거이며 위 표에 실제 호출 지점을 따로 적었다.

| 패키지 접두사 | 수 | Activity 단순 이름 |
| --- | ---: | --- |
| `com.tvt.launch` | 2 | `MainActivity`, `GuideActivity` |
| `com.tvt.network` | 1 | `MainViewActivity` |
| `com.tvt.login.view.activity` | 12 | `LoginVerityCodeActivity`, `PhoneRegisterActivity`, `MailRegisterActivity`, `FindPasswordByPhoneActivity`, `RegisterVerifyCodeActivity`, `FindPwdVerifyCodeActivity`, `FindPasswordByMailActivity`, `ThirdRelationByPhoneActivity`, `ThirdRelationByMailActivity`, `LoginByMailActivity`, `LoginByPhoneActivity`, `IT20WebLoginActivity` |
| `com.tvt.user.view.activity` 계정/보안 | 23 | `UserManagerActivity`, `SafeSettingActivity`, `BindPhoneByLoginActivity`, `ModifyPhoneActivity`, `InputNewPhoneActivity`, `InputNewEmailActivity`, `NewPhoneVerifyCodeActivity`, `BindMailByLoginActivity`, `BindMailVerifyCodeByLoginActivity`, `BindPhoneVerifyCodeByLoginActivity`, `ModifyMailActivity`, `NewMailVerifyCodeActivity`, `RemoveAccountActivity`, `RemoveAccountOkActivity`, `BindThirdPartyActivity`, `QrcodeActivity`, `ModifyPasswordByMailActivity`, `ModifyPasswordByPhoneActivity`, `RemoveAccountByMailVerifyCodeActivity`, `RemoveAccountByPhoneVerifyCodeActivity`, `RemoveAccountFailedActivity`, `UserQrcodeActivity`, `LineBindWebActivity` |
| `com.tvt.user.view.activity` 공유/기타 | 21 | `ReceiveShareNVRDetailActivity`, `ReceiveShareNVRDetailEditActivity`, `ShareManagerActivity`, `NewShareActivity`, `ReceiveShareIPCDetailActivity`, `SendShareDetailEditActivity`, `SendShareDetailActivity`, `ModifyShareDevActivity`, `ShareDevBasicInfoActivity`, `ShareDevChlInfoActivity`, `ShareDevInfoActivity`, `ShareInputAccountActivity`, `ShareSelectDeviceActivity`, `SharePermissionEditActivity`, `ShareIPCActivity`, `SharePermissionSelectActivity`, `ShareDevPermissionListActivity`, `ChangeAccountTypeActivity`, `InstallerInfoActivity`, `InstallerBindUserActivity`, `EventAttributeActivity` |
| `com.tvt.devicemanager` 직접 | 8 | `DeviceQrcodeActivity`, `LocalDeviceActivity`, `DeviceInfoActivity`, `DeviceManagerSearchLocalActivity`, `DeviceSDCardActivity`, `ScheduleTimeRecordingActivity`, `ScheduleSettingActivity`, `doorbell.AddDoorBellDeviceActivity` |
| `com.tvt.devicemanager.doorbell` 및 하위 | 17 | `WifiConfigResetActivity`, `WifiConfigConnectActivity`, `WifiConfigHandConnectActivity`, `WifiConfigInputActivity`, `WifiConfigBindDeviceActivity`, `DoorBellDeviceInfoActivity`, `DoorBellPushActivity`, `DoorbellVideoTalkActivity`, `DoorBellActiveDeviceActivity`, `timezone.DoorBellTimeZoneActivity`, `chime.WiredChimeActivity`, `leavewordaudio.LeaveWordAudioActivity`, `chime.WirelessChimeActivity`, `chime.WirelessChimeNoDisturbActivity`, `chime.WirelessChimeRingActivity`, `chime.ChimeTimeActivity`, `chime.ChimeTipActivity` |
| `com.tvt.device.ui` 및 `.information` | 10 | `SafeCodeTipActivity`, `information.DeviceCommonInfoActivity`, `information.DeviceChannelInfoActivity`, `information.DeviceAlarmInfoActivity`, `ModifyDevicePassActivity`, `CloudStorageEncryptActivity`, `CloudStorageModifyActivity`, `information.DeviceCloudUpgradeActivity`, `information.PowerSettingActivity`, `information.DeviceDiagnosisModeActivity` |
| `com.tvt.config.ui` | 5 | `LaunchSettingActivity`, `RemoteWebActivity`, `RemoteConfigActivity`, `LocalConfigActivity`, `FavoriteEditActivity` |
| `com.tvt.devicelogin` | 1 | `DeviceLoginActivity` |
| `com.tvt.dev_share` | 4 | `SelectDeviceActivity`, `ShareQrcodeActivity`, `AddDeviceActivity`, `GenerateQRCodeActivity` |
| `com.tvt.live` | 3 | `DevDefenseDetailCfgActivity`, `DevDefenseCfgActivity`, `DevDefenseAddActivity` |
| `com.tvt.playback` | 1 | `PlaybackActivity` |
| `com.tvt.search` | 4 | `FaceRecognitionActivity`, `SearchActivity`, `AddLicensePlateActivity`, `AddFaceActivity` |
| `com.tvt.ai.search` | 12 | `AISearchInputActivity`, `AIDetailActivity`, `AIPicDetailActivity`, `AISearchListActivity`, `AITextSearchFilterActivity`, `AISearchDeviceFilterActivity`, `AISearchTimeSelectActivity`, `AIImageSearchTargetSelectActivity`, `AIPicSearchListActivity`, `AIAttributeSearchActivity`, `AISearchEditActivity`, `AITargetSearchConditionActivity` |
| `com.tvt.push` / `com.tvt.pushconfig` | 7 | `PushMessageActivity`, `HuaweiPushMessageActivity`(push 진입), `PushConfigMainActivity`, `PushConfigDetailActivity`, `Push2ConfigDetailActivity`, `BindIPCPush2ConfigDetailActivity`, `IpcPushConfigActivity` |
| `com.tvt.filemanager` / `.photo` | 4 | `FileManagerActivity`, `SearchFileActivity`, `BigImageActivity`, `photo.BigImageActivity` |
| `com.tvt.cloudstorage` / `.valueaddedservice` | 8 | `CloudStorageActivity`, `CloudPlayerActivity`, `CloudDownloadActivity`, `ValueAddedServiceActivity`, `VASDeviceListActivity`, `VASServiceDetailActivity`, `VASBuyRecordActivity`, `VASCloudStoreSettingActivity` |
| `com.tvt.tyco.ui.activity` | 10 | `login.SelectLoginWayActivity`, `login.LoginActivity`, `panel.AddPanelActivity`, `panel.PanelMainActivity`, `panel.PanelLoginActivity`, `panel.PanelListActivity`, `register.SetPasswordActivity`, `register.RegisterVerityActivity`, `register.RegisterActivity`, `account.TycoAccountActivity` |
| `com.tvt.about` / `.experience` / `.help` / `.web` | 7 | `AboutActivity`, `DebugConfigActivity`, `DebugConfigActivity2`, `experience.ExperienceActivity`, `help.HelpActivity`, `web.TitleWebActivity`, `web.WebActivity` |
| `com.tvt.third_party_auth.platform` / 두 `wxapi` | 5 | `FacebookActivity`, `GooglePlusActivity`, `WeChatActivity`, `com.tvt.superliveplus.wxapi.WXEntryActivity`, `com.tvt.supercamplus.wxapi.WXEntryActivity` (인증 콜백) |

## 도달성·Android 전용 경계와 남은 공백

1. **기능 게이트**: 메뉴 XML에 있어도 `ef2`가 거주자 관리 항목을 기본 숨김 처리하고, 원격 설정·VAS·푸시·파일·Help를 플래그별로 감춘다. Tyco도 별도 플래그가 필요하다. 로그인 전 VAS는 로그인 화면으로 우회한다. 따라서 위 목록 전체를 기본 홈에 동시에 노출되는 기능으로 해석하면 안 된다. `J:defpackage/ef2.java:234-246,303-322,464-524`; `J:com/tvt/live/LiveViewLayout.java:1891-1910`.
2. **별도 의심 묶음**: 300개의 `*ActivityPage`는 실제 Manifest와 `classes3.dex`에 있지만 TVT 기능의 증거로 채택하지 않았다. 예를 들어 `cn.zone.similarity.TalkSearchActivityPage`는 `Hello` 출력·빈 반복·인위적 시간 분기와 `activity_talk_search_act_page` 레이아웃으로 이뤄지고, 해당 이름의 코드 참조는 동명 샘플 클래스들뿐이다. 이 묶음은 일반 메뉴/ARouter/Navigation 동선을 찾지 못했다. '절대 실행 불가'라고 단정하지 않고 **선언만, 제품 기능 아님으로 추정**한다. `J:cn/zone/similarity/TalkSearchActivityPage.java:1-105`; `M:473-772`; `R:layout/activity_talk_search_act_page.xml`.
3. **Android 전용**: QR 스캔/카메라, 음성 입력·Talk/녹음, 로컬 파일·갤러리, 위치·Wi-Fi 탐색, Bluetooth, FCM/Huawei push, 알림 권한/전체화면 통화 알림, Activity 방향 전환·백그라운드 정리, WebView/제3자 인증 콜백은 Android 플랫폼과 권한에 묶인다. Manifest의 권한 선언만으로 사용자 승인이나 장치 지원을 알 수 없다. `M:3-31,48-69`, `J:com/tvt/live/LiveViewLayout.java:237-266,5244-5256`, `J:com/tvt/playback/PlaybackActivity.java:183-228`, `J:com/tvt/network/MainViewActivity.java:1697-1709`.
4. **정적 조사 한계**: JADX 전체 로그에 오류 391건이 기록돼 있고, 그중 `ERROR -   Method:` 목록 항목은 262개다. UI 관련 미해석 지점은 재생 시간축 터치(`J:com/tvt/playback/view/PlaybackTimeBar.java:1183`), 푸시 데이터 처리 일부(`J:com/tvt/push/PushMessageDataUtil.java:501`), 공유 계정 입력 콜백(`J:com/tvt/user/view/activity/ShareInputAccountActivity.java:693`), AI 작업 순서 및 Tyco ViewModel 일부(`J:com/tvt/ai/search/task/SequentialTaskManager.java:87-162`)다. 해당 동작의 세부 분기·오류 처리는 확정하지 않았다. `DeviceRecordInfoActivity`는 `@Route(path="/device/DeviceChannelInfoActivity")`로 소스에 보이나 Manifest의 동명 Activity 선언은 없고, `DeviceChannelInfoActivity` 선언도 따로 있어 라우트 충돌/도달성 확인이 필요하다. `J:com/tvt/device/ui/information/DeviceRecordInfoActivity.java:45`; `M:103-110`.
5. **실행 검증 미수행**: 메뉴 노출 조합, 로그인/장치 유형별 화면, 웹 페이지 내용, push→알람 상세, 결제, 저장소 접근, 도어벨 통화, Tyco 패널, 영상·오디오·playback 결과는 실제 기기·서비스에 대한 허가된 동작 검증이 필요하다. 이 조사는 APK 정적 자료만 사용했다.
