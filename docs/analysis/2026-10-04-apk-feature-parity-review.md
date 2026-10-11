# SuperLive Plus APK to web service: feature parity review

- **Analysis date:** 2026-10-04 (Asia/Seoul).
- **Latest scoped update:** 2026-10-06 (Asia/Seoul); HEAD6436748 plus uncommitted
  stage-1 changes, c9–c11 actual evidence and current source review. The original
  inventory and unrelated statuses remain dated2026-10-04; affected live rows
  below were refreshed. No APK side-by-side acceptance ran.
- **Requested by:** parent controller (read-only APK feature parity review).
- **Status of this file:** canonical APK feature parity matrix. Written by an independent read-only
  reviewer and adopted into the project by the controller on 2026-10-04 (section 9 steps 1-3 done;
  step 4 respected: the parity ledger is unchanged).

## 1. Purpose, scope and baselines

**Question answered:** "Are all features the APK supports implemented and complete in the web
service?" The answer is given as an evidence-based feature matrix, not an impression.

**Scope:** the user-facing features of SuperLive Plus 1.18.1 (Android), compared with the current web
service. The web service has a Next.js/React/Tailwind frontend, a Next BFF, FastAPI, PostgreSQL, an
mTLS TVT bridge, a Windows native TVT provider and a media worker. The following are excluded as
product features:

- the 300 suspicious `*ActivityPage` manifest entries, which audit 01 classifies as non-product;
- the 281 internal `/sdk/*` request classes, except where one of them is the only evidence for a
  user feature.

**Web source baseline:**

- Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
- Branch: `codex/superlive-web-service`.
- HEAD: `211d1484aa16eb30f5d362758f149f98dec9dfdf` (2026-10-04 14:52 +0900, "chore: reconcile pending
  source changes and ignore local artifacts").
- Initial working tree (unchanged by this review):
  - **24 modified tracked files** (+2,355 / −81 lines);
  - **39 untracked entries (45 files)**. These hold the uncommitted continuous-media slice: the
    live-session BFF/API, `services/tvt-media`, migration `0013`, the WebRTC path, the frontend live
    panel and player, tests, and 2026-10-04 reports.
- This review includes that uncommitted state. Per `AGENTS.md`, the primary `main` checkout
  (`C:/2026_project/wisdom-super-observer`) lacks this work and was not used as source evidence.

**APK baseline:**

- SuperLive Plus **1.18.1** (versionCode 20267). The base APK SHA-256 is
  `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`, as recorded in
  `docs/service-analysis.md`.
- A private decompiled copy is at `C:/wso-private/superliveplus/1.18.1-2026-09-27/` (apktool resources
  and manifest; jadx-full sources). It was only read. This report cites class, method and resource
  names. It contains no APK code, credentials, serials, tokens, SDP or media.

**Project evidence read first and reused:**

- `AGENTS.md`.
- `docs/service-analysis.md` (canonical; current through the 2026-10-04 post-reboot continuation).
- `docs/analysis/2026-10-04-reboot-handoff.md` and `docs/analysis/2026-10-04-local-media-liveness-review.md`.
- `docs/integrations/apk-audit/{README,01-ui-feature-inventory,03-media,12-functional-parity-contracts}.md`.
- `docs/integrations/tvt-parity-ledger.md` (the frozen 77 cases, `MATCHED=0`).
- `docs/integrations/{tvt-local-media-service,tvt-local-media-web,tvt-windows-live-session,tvt-local-device-browser-runtime,tvt-account-browser-fixture}.md`.
- `docs/superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md`.
- `docs/design/2026-09-30-dashboard-reference.md`.
- `SERVICE_PLAN.md` (edge-relay note: keep one camera connection and redistribute it).

The `.superpowers/verification/apk-{account-flows,device-directory,followup}` folders hold
native/Java decode captures for the account and directory protocol work. They are not feature
inventories or parity matrices, so they were not used for any status.

## 2. Method and status rules

1. **APK inventory.** The starting point was the existing audit: 23 UI areas plus conditional
   household management (audit 01), and the frozen 77 atomic contracts P01.1–P24.1 (audit 12 and the
   ledger).
   - Composite contracts were split into user-visible features.
   - The following were verified directly against the decompiled APK:
     - manifest activity names;
     - menu and tile layouts: `view_live_menu.xml`, `view_live_bottom_tab.xml`,
       `view_live_bottom_more_layout.xml`, `video_menu_view.xml`, `view_segmentation_item.xml`,
       `activity_local_config.xml`, `view_ptz_ctrl.xml`, `layout_fish_mode.xml`,
       `view_custom_rate.xml`, `playback_video_menu.xml`, `view_playback_bottom_tab.xml`,
       `view_playback_segmentation.xml`;
     - `strings.xml` and the 31 translated `values-*` locales;
     - the multi-view and stream code paths: `com.tvt.video.VideoManagerLayout`,
       `com.tvt.live.LiveViewLayout`, `com.tvt.live.a`, `defpackage/fu3`, `defpackage/cw3`,
       `com.tvt.network.GlobalUnit`, `com.tvt.devicemanager.LocalDeviceActivity` and
       `com.tvt.config.ui.LocalConfigActivity`.
   - Features missing from earlier rows were added: IP/DDNS add, 32-device auto-connect, user
     log/bug report, and 31-locale UI.
2. **Web evidence.** Every Next route under `apps/web/src/app/**` was enumerated, along with its
   feature components, BFF proxies, FastAPI routers, and the core, bridge and media modules and
   migrations. There are 32 TVT API routes: account 6, account flows 8, directory 6, local devices 3,
   live sessions 6 and startup 3. There are also 6 connection routes. Each APK feature was traced to
   a **user-reachable** path (UI → BFF → API → backend).
3. **Executed evidence.** For each feature, the strongest dated execution record in the canonical
   report or the documents it links was used. Nothing was rerun.
4. **Status (exactly one per row):**
   - `ACCEPTED_REAL`: user-reachable, and a recorded acceptance exists against **real recorders in a
     real browser (Chrome)**.
   - `IMPLEMENTED_UNACCEPTED`: a user-reachable path exists, but the evidence is limited to
     unit/integration tests, synthetic upstreams, fixtures or component tests.
   - `PARTIAL`: only some sub-capabilities exist; the notes name them.
   - `MISSING`: no user-reachable path. Private adapters or codecs with no API/UI wiring
     ("adapter-only") count as `MISSING`. `(D)` marks APK contracts that audit 12 records as
     declaration-only, meaning reachability inside the APK itself is unproven.
   - `NOT_APPLICABLE`: handset-only or operator-level behaviour that a browser cannot, or should
     not, replicate. Each case is justified in its row.
5. **`ACCEPTED_REAL` is not the project's `MATCHED`.** No APK side-by-side comparison has run for
   any case. The ledger stays at `MATCHED=0` of 77 and `release_ready=false`.
6. **Rows are unweighted groupings.** The counts are not a completion percentage. The canonical
   report also states that no defensible completion percentage exists.

**Path legend:**

| Prefix | Path |
| --- | --- |
| `web/` | `apps/web/src/` |
| `api/` | `services/api/src/wso_api/` |
| `core/` | `packages/core/src/wso_core/` |
| `contracts/` | `packages/contracts/src/wso_contracts/` |
| `bridge/` | `services/tvt-bridge/src/wso_tvt_bridge/` |
| `media/` | `services/tvt-media/src/wso_tvt_media/` |
| `mig/` | `infra/migrations/versions/` |

P-IDs refer to the contracts in audit 12.

## 3. Summary

### 3.1 Counts by status (141 APK features)

| Status | Rows | Share of all rows | Share of the 137 applicable rows |
| --- | ---: | ---: | ---: |
| `ACCEPTED_REAL` | 2 | 1.4% | 1.5% |
| `IMPLEMENTED_UNACCEPTED` | 12 | 8.5% | 8.8% |
| `PARTIAL` | 14 | 9.9% | 10.2% |
| `MISSING` | 109 | 77.3% | 79.6% |
| `NOT_APPLICABLE` | 4 | 2.8% | — |

- Two `MISSING` rows are APK declaration-only `(D)`: AC-08 and FL-05.
- About 25 rows are brand-, region-, entitlement- or capability-gated in the APK: AC-06/07/14,
  DC-12, PT-04/05/08/09/10, all CL, all TY, AI-06/07, DB-02..04 and HA-06. Their applicability
  needs the still-unmeasured support matrix (ledger candidates M01–M06).

### 3.2 Counts by area

| Area | Rows | ACCEPTED_REAL | IMPLEMENTED_UNACCEPTED | PARTIAL | MISSING | NOT_APPLICABLE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ST Startup and onboarding | 4 | 0 | 1 | 0 | 3 | 0 |
| AC Account and security | 18 | 0 | 7 | 1 | 10 | 0 |
| DV Devices: list, add, manage | 15 | 1 | 3 | 4 | 7 | 0 |
| SH Sharing and friends | 6 | 0 | 1 | 0 | 5 | 0 |
| LV Live view | 17 | 1 | 0 | 6 | 10 | 0 |
| PT PTZ and camera controls | 11 | 0 | 0 | 0 | 11 | 0 |
| PB Playback and backup | 9 | 0 | 0 | 0 | 9 | 0 |
| AI Smart search, face, plate | 8 | 0 | 0 | 0 | 8 | 0 |
| AL Alarms and push | 5 | 0 | 0 | 0 | 5 | 0 |
| DC Device information and configuration | 13 | 0 | 0 | 2 | 11 | 0 |
| DB Doorbell | 4 | 0 | 0 | 0 | 3 | 1 |
| CL Cloud storage, VAS, payment | 5 | 0 | 0 | 0 | 5 | 0 |
| FL Local files and album | 5 | 0 | 0 | 0 | 5 | 0 |
| LS Local settings | 10 | 0 | 0 | 1 | 6 | 3 |
| TY Tyco alarm panel | 5 | 0 | 0 | 0 | 5 | 0 |
| HA Help, About and miscellaneous | 6 | 0 | 0 | 0 | 6 | 0 |
| **Total** | **141** | **2** | **12** | **14** | **109** | **4** |

### 3.3 Verdict

**No. The web service does not implement the APK's feature set, and most of what exists is
unaccepted.**

- **Accepted (2 of 141).** Both were accepted on the two real recorders in real Chrome:
  - device verification with channel-roster readback (8 and 4 channels);
  - single-channel continuous live video: main stream, video only, two channels on two recorders,
    OWNER only, in the owned test runtime.
- **Implemented but unaccepted (12).** These were exercised only against synthetic upstreams,
  fixtures or unit tests:
  - TVT cloud-account login, image/second code, registration, recovery, profile and logout;
  - cloud device, channel and share reads;
  - the serial-number device registration form;
  - the consent gate.
- **Partial (14), missing (109), not applicable (4).**

Entire APK domains are absent:

- recorded playback and backup;
- multi-split live and quality selection;
- audio listen and two-way talk;
- PTZ and camera actuators;
- snapshot, local recording and the album;
- alarms and push;
- device configuration;
- sharing writes;
- AI, face and plate search;
- cloud storage, VAS and payment;
- doorbell;
- Tyco.

The project's own formal gate still reads `MATCHED=0` of 77 and `release_ready=false`. Today's
service is a carefully guarded vertical slice (account, directory reads and one live tile per
connection). It is not an APK-complete replacement.

An "all stores, all cameras" dashboard is blocked by the current limits (section 5):

- two native live sessions, and two media sources per worker;
- four leases per user;
- one active lease per channel for all users;
- one fresh device login per tile;
- main stream only;
- OWNER-only viewing;
- no production wiring of the media worker.

### 3.4 What the web service provides today (orientation)

**`/tvt` shell** (`web/app/tvt/[[...path]]/page.tsx`, `web/features/tvt/shell/TvtShell.tsx`):

- consent gate;
- Settings: locale and time zone;
- Account: login, register, recover, profile, refresh, logout;
- Devices: six cloud-directory reads, including sent and received shares.

The menu admits exactly three local routes: `core/tvt/startup.py:60,103-115` and
`web/features/tvt/shell/FeatureMenu.tsx`.

**`/connections`** (OWNER only):

- `TVT_DEVICE` registration: serial, country, user, password, and QR picture decoding;
- edit, disconnect and delete;
- device verification and the saved channel list;
- **one live player per connection card** (`web/features/connections/{connection-form,connections-view,local-device-inventory,local-live-panel}.tsx`).

**`/stores`:** store list and detail (name, status, time zone). There is no camera content.

**Web-only features with no APK counterpart:** multi-tenant organizations and stores, and generic
jobs and assets. These are outside the matrix.

## 4. Feature matrix

| Area | APK feature | APK evidence (class / resource; P-ID) | Web evidence (file refs) | Status | Notes / gap |
| --- | --- | --- | --- | --- | --- |
| ST Startup | ST-01 Privacy/terms consent (accept/decline) with policy documents | `com.tvt.launch.MainActivity` consent flow; `com.tvt.web.WebActivity`; P01.1 | `web/features/tvt/shell/ConsentGate.tsx`; `api/tvt/startup.py:119,128` (`/bootstrap`, `/consent`); `web/app/tvt/policies/[locale]/[kind]/page.tsx` (terms + privacy, en and zh-Hans) | IMPLEMENTED_UNACCEPTED | Consent is persisted per tenant and version. It was exercised only in synthetic-account browser CI and fixtures. The APK loads region/brand H5 policies; the web bundles four static documents. |
| ST Startup | ST-02 First-run guide pages and permission education | `com.tvt.launch.GuideActivity`; P01.1 | — | MISSING | No onboarding. Browser camera/microphone/notification permission UX is not designed (plan W12). |
| ST Startup | ST-03 Open from notification or deep link to the target screen (alarm detail, doorbell call) | `MainActivity` deep-link branch; `com.tvt.network.MainViewActivity` push/invite routing; P01.2 | `web/features/tvt/shell/DeepLinkResolver.tsx` only allow-lists `/tvt`, `/tvt/settings`, `/tvt/account`, `/tvt/devices` | MISSING | The resolver is a route guard. No alarm or doorbell deep links exist, because push and alarms are absent. |
| ST Startup | ST-04 Start-screen (launch page) setting | `com.tvt.config.ui.LaunchSettingActivity`; `activity_local_config.xml` `cl_launch_setting`; P20.1 | — | MISSING | — |
| AC Account | AC-01 Email and password login to the TVT cloud account | `com.tvt.login.view.activity.LoginByMailActivity`; `UserLoginRequest`; P02.1 | `web/features/tvt/account/LoginForm.tsx`; `api/tvt/account.py:173` `/login`; `core/tvt/account_client.py`; `tests/tvt_parity/e2e/login.spec.ts` | IMPLEMENTED_UNACCEPTED | Passed synthetic-account Chrome desktop and mobile CI (GitHub run 37083395314 at `756946c`) against a decoded-protocol HTTPS fixture. Never run against a real TVT account or compared with the APK. |
| AC Account | AC-02 Phone login with country code | `LoginByPhoneActivity`; P02.1 | `LoginForm.tsx` + `web/features/tvt/account/countries.json` (196 source countries); `tests/tvt_parity/test_phone_login_binding.py` | IMPLEMENTED_UNACCEPTED | Source-derived binding. The browser fixture asserts the email path only. |
| AC Account | AC-03 Image captcha and second verification code at login | `LoginVerityCodeActivity`; P02.1 | `api/tvt/account.py:187,204` (`/challenges/image`, `/challenges/image/check`); `LoginForm.tsx` (`image_code`, `second_code`) | IMPLEMENTED_UNACCEPTED | Tested with a synthetic PNG challenge only. |
| AC Account | AC-04 Register by email or phone with a verification code | `MailRegisterActivity`, `PhoneRegisterActivity`, `RegisterVerifyCodeActivity`; P02.2 | `web/features/tvt/account/{RegisterForm,AccountFlowForm}.tsx`; `api/tvt/account_flows.py:118-260` (start, state, existence, image, issue-code, register, cancel) | IMPLEMENTED_UNACCEPTED | Synthetic-upstream API, RPC and SQL evidence only. No real account was created. |
| AC Account | AC-05 Password recovery by email or phone | `FindPasswordByMailActivity`, `FindPasswordByPhoneActivity`, `FindPwdVerifyCodeActivity`; P02.3 | `RecoverForm.tsx`; `api/tvt/account_flows.py:240` `/recover` | IMPLEMENTED_UNACCEPTED | Same limits as AC-04. |
| AC Account | AC-06 Third-party login and account relation (Facebook, Google, WeChat) | `com.tvt.third_party_auth.platform.{FacebookActivity,GooglePlusActivity,WeChatActivity}`; `ThirdRelationByMailActivity`, `ThirdRelationByPhoneActivity`; P02.4 | — | MISSING | Region- and brand-gated in the APK. Needs OAuth redirect and state design. |
| AC Account | AC-07 Vimar IT20 web login | `IT20WebLoginActivity`; P02.4 | — | MISSING | Brand-gated. |
| AC Account | AC-08 Web QR-login approval | `/sdk/sendUUIDForWebLogin` and `/sdk/sendAuthForWebLogin` request classes; P02.5 (D) | — | MISSING | APK reachability is unproven. This could become a reviewed exclusion. |
| AC Account | AC-09 View profile (user name, nickname, email, phone, address, avatar presence) | `com.tvt.user.view.activity.UserManagerActivity`; P16.1 | `web/features/tvt/account/Profile.tsx`; `api/tvt/account.py:222` `/{identity_id}/me` | IMPLEMENTED_UNACCEPTED | Read-only. The avatar is reported as present or absent; no image is shown. |
| AC Account | AC-10 Edit nickname and upload avatar | `UserManagerActivity` (`/sdk/setUserInfo`, `/sdk/UserUploadHeadImg`); P16.1 | Adapter only: `core/tvt/security_client.py:144` `update_profile` | MISSING | No RPC, API or UI. The private adapter is not wired (no reference in `services/api` or `bridge`). |
| AC Account | AC-11 Bind or change phone and email with codes | `BindPhoneByLoginActivity`, `ModifyPhoneActivity`, `InputNewPhoneActivity`, `NewPhoneVerifyCodeActivity`, `BindMailByLoginActivity`, `ModifyMailActivity`, `NewMailVerifyCodeActivity`; P16.1 | Adapter only: `security_client.py:162,180,198,216,252` | MISSING | Same as AC-10. |
| AC Account | AC-12 Change password | `ModifyPasswordByMailActivity`, `ModifyPasswordByPhoneActivity`, `SafeSettingActivity`; P16.2 | Adapter only: `security_client.py:271` `update_password` | MISSING | Same as AC-10. |
| AC Account | AC-13 Personal user QR code | `UserQrcodeActivity`, `QrcodeActivity`; P16.1 | — | MISSING | — |
| AC Account | AC-14 Bind or unbind third-party and LINE accounts | `BindThirdPartyActivity`, `LineBindWebActivity`; P16.3 | — | MISSING | Brand- and region-gated. |
| AC Account | AC-15 Change account type; installer information and user binding | `ChangeAccountTypeActivity`, `InstallerInfoActivity`, `InstallerBindUserActivity`; P16.2 | `Profile.tsx` shows `account_type` read-only | MISSING | — |
| AC Account | AC-16 Delete account (verification code, confirm, result) | `RemoveAccountActivity`, `RemoveAccountByMailVerifyCodeActivity`, `RemoveAccountByPhoneVerifyCodeActivity`, `RemoveAccountOkActivity`, `RemoveAccountFailedActivity`; P16.4 | — | MISSING | Irreversible. Needs the W15 confirmation and unknown-outcome design. |
| AC Account | AC-17 Logout | `SafeSettingActivity` and menu header; P16.2 | `Profile.tsx`; `api/tvt/account.py:263` `/logout` | IMPLEMENTED_UNACCEPTED | Synthetic CI only. |
| AC Account | AC-18 Session and token renewal | Automatic account token renewal (audit 09); P16.2 | `api/tvt/account.py:239` `/refresh`; manual "TVT 세션 갱신" button in `Profile.tsx` | PARTIAL | Renewal is manual only, with no automatic background renewal. The P2P/DEVICE token lifecycle is not implemented (canonical W05 row). |
| DV Devices | DV-01 Cloud-account device list | `com.tvt.devicemanager.LocalDeviceActivity` (account devices); `activity_local_device.xml`; P10.3/P11.1 | `web/features/tvt/devices/{DirectoryPage,DeviceList}.tsx`; `api/tvt/devices.py:280` | IMPLEMENTED_UNACCEPTED | Ran in real Chrome through Next, API, SQL and mTLS (run `472e59554d25…`, 04:13–04:18 KST) with an **invented identity and synthetic upstream**. The UI asks for page number and page size instead of an APK-like list. |
| DV Devices | DV-02 Cloud channel list, device detail and channel detail | `DeviceInfoActivity`; `information.DeviceCommonInfoActivity`, `information.DeviceChannelInfoActivity`; P11.1 | `ChannelList.tsx`, `DeviceDetail.tsx`; `api/tvt/devices.py:289,300,311` | IMPLEMENTED_UNACCEPTED | Same synthetic limit. These observations grant no commands. |
| DV Devices | DV-03 Add device by serial number (SN/P2P) with device username and password | `LocalDeviceActivity` manual add; string `Add_device_Invalid_SN`; P10.1 | `web/features/connections/connection-form.tsx:214-226` (`TVT_DEVICE`: serial, country, username, password); `api/connections/router.py:207`; `core/tvt/local_credentials.py` | IMPLEMENTED_UNACCEPTED | Encrypted-credential SQL acceptance passed 3/3 (2026-10-04 02:45 and 02:54 KST), plus a component Chrome test. The real-device runs used connections that the fixture created through `ConnectionService`. Typing a real device into the browser form is not recorded. |
| DV Devices | DV-04 Device login and channel roster (verify device; saved channel readback) | `com.tvt.devicelogin.DeviceLoginActivity`; `defpackage/cw3` login and metadata; P10.1/P11.1 | `web/features/connections/local-device-inventory.tsx`; `api/tvt/local_devices.py:157,225,232`; `bridge/local_inventory_provider.py`; `bridge/windows_socket.py` | **ACCEPTED_REAL** | Real Chrome over trusted HTTPS against two real recorders: **8 and 4 channels**, with saved readback after a page reload (2026-10-04 07:50–07:53 KST, run `local-devices-9e7306d5…`). OWNER only. Channel labels are fixed to "Channel N", so real names are hidden (`web/lib/tvt/local-device-api.ts:5`). Verification is refused while any live session is active (`bridge/windows_socket.py:1032-1033`). |
| DV Devices | DV-05 Add device by QR (camera scan or choose a QR picture) | `com.sdk.qrcode.CaptureActivity`, `CaptureNewActivity`, `intf.ScanQrcodeActivity`; string `DeviceManager_Choose_Qrcode_Image`; P10.1 | `web/lib/tvt/device-qr-image.ts` (jsQR on a chosen image); `connection-form.tsx:223-226` | PARTIAL | Only the choose-picture path exists. There is no live camera scan through `getUserMedia`. The Chrome acceptance used an inert PNG in a component fixture, not a real device QR through the full service. |
| DV Devices | DV-06 Add device by IP/DDNS and port | strings `Add_device_Hold_IP_Or_DDNS`, `DeviceManager_IP`; P10.1 | — (`core/tvt/local_credentials.py` keys are serial, country, username, password) | MISSING | No direct IP, LAN or port-forward path. |
| DV Devices | DV-07 LAN device search | `com.tvt.devicemanager.DeviceManagerSearchLocalActivity`; P10.1 | — | MISSING | Browsers cannot multicast. This needs an on-site gateway (plan W12). |
| DV Devices | DV-08 Bind, register or transfer a device on the cloud account | `/sdk/deviceBind`, `/sdk/deviceRegister`, `/sdk/deviceTransfer`; P10.2 | — | MISSING | Local SN connections are separate from account-bound devices. |
| DV Devices | DV-09 Edit device (rename; re-enter login credentials) | `LocalDeviceActivity`; `/sdk/deviceReName`; `DeviceLoginActivity`; P10.3 | `web/features/connections/connections-view.tsx:288-297` ("수정" → PATCH); `api/connections/router.py:214` | PARTIAL | Local connection alias and credential replacement only. No cloud rename and no channel rename. Not accepted in a browser against real devices. |
| DV Devices | DV-10 Remove device locally or unbind from the account | `LocalDeviceActivity` delete; `/sdk/deviceUnBind`; P10.3 | `connections-view.tsx:300-319` (disconnect/delete); `api/connections/router.py:225,236` | PARTIAL | Local connection delete and disconnect only. Cloud unbind is missing. |
| DV Devices | DV-11 Sort or reorder the device list | `LocalDeviceActivity` sort; P10.3 | — | MISSING | — |
| DV Devices | DV-12 Favorites and device groups (add or remove channels; edit group) | `com.tvt.config.ui.FavoriteEditActivity`; `rl_fav_item`; `/sdk/AddDeviceToFavoritesGroup`, `/sdk/DeleteDeviceFromFavoritesGroup`; P06.1 | — | MISSING | This is also the APK's container for opening many cameras together (section 5). |
| DV Devices | DV-13 Device online, offline and connection status | `com.tvt.live.view.ServerListViewLayout2`; P03.1 | Cloud: raw `onlineStatus` in `DeviceDetail.tsx`. Local: `inventory_state`, shown alongside a separate connection status | PARTIAL | The two status displays are inconsistent (connection NOT_VERIFIED vs inventory AVAILABLE; canonical report UI follow-up). There is no live presence polling. |
| DV Devices | DV-14 Show the device QR code | `com.tvt.devicemanager.DeviceQrcodeActivity`; P17.6 | — | MISSING | — |
| DV Devices | DV-15 Auto-connect devices at startup (up to 32) | `ConnectStatus.isConnectAutomatic`; `GlobalUnit.c` = 32; `LocalDeviceActivity.b3`; string `Add_Device_Too_More`; `sw_auto_conn`; P20.1 | — | MISSING | The web opens a device session only on explicit action. There is no persistent per-device connection. |
| SH Sharing | SH-01 Sent and received share lists, including share fields | `com.tvt.user.view.activity.ShareManagerActivity`, `SendShareDetailActivity`, `ReceiveShareNVRDetailActivity`, `ReceiveShareIPCDetailActivity`; P17.2/P17.3 (P17.5 D) | `web/features/tvt/devices/Shares.tsx`; `api/tvt/devices.py:322,331` | IMPLEMENTED_UNACCEPTED | Read-only, from a synthetic-upstream Chrome run only. |
| SH Sharing | SH-02 Create a share (account, devices, channels, permissions) | `NewShareActivity`, `ShareInputAccountActivity`, `ShareSelectDeviceActivity`, `SharePermissionSelectActivity`, `ShareIPCActivity`; P17.2 | — | MISSING | — |
| SH Sharing | SH-03 Accept or batch-accept received shares | `/sdk/acceptShared`, `/sdk/batcjAcceptShared`, `/sdk/batcjAcceptDeviceShared`; P17.3 | — | MISSING | — |
| SH Sharing | SH-04 Edit share permissions, remove channels, revoke a share | `SharePermissionEditActivity`, `SendShareDetailEditActivity`, `ModifyShareDevActivity`, `ShareDevPermissionListActivity`; P17.4 | — | MISSING | — |
| SH Sharing | SH-05 Generate or scan a share QR; add a shared device | `com.tvt.dev_share.{ShareQrcodeActivity,GenerateQRCodeActivity,AddDeviceActivity,SelectDeviceActivity}`; P17.6 | — | MISSING | — |
| SH Sharing | SH-06 Friends (search, apply, accept) and friend groups | `/sdk/searchMyFriendByLoginName`, `/sdk/sendApplyForAddFriends`, `/sdk/agreeApplyToNewFriendWithApplyId`, group routes; P17.1 | — | MISSING | — |
| LV Live | LV-01 Single-channel live video | `com.tvt.live.LiveViewLayout`, `com.tvt.video.VideoView`; `defpackage/cw3` (`jb`; keepalive `fu3.N1` → `cw3.v5`); P03.1 | `web/features/connections/local-live-panel.tsx`; `web/lib/tvt/local-live-{player,api,proxy}.ts`; `web/app/api/live-sessions/[[...segments]]/route.ts`; `api/tvt/local_media.py:209-313`; `core/tvt/local_media_{admission,service}.py`; `bridge/local_live_{provider,ipc}.py`, `bridge/local_media_rpc.py`; `media/{native_source,live,worker}.py`; `mig/0013_tvt_local_media_leases.py` | **ACCEPTED_REAL** | Real Chrome against real recorders (run `local-devices-06c7327498f8…`, 2026-10-04): store 1 channel 2 played continuously for about 5 minutes; store 2 channel 1 played 81.7 s at the same time; about 10 fps with server-confirmed PLAYING. Stop and reopen worked, and every lease closed with confirmed cleanup. Limits: main stream only; video only (HEVC decoded and re-encoded to VP8); OWNER only; local SN devices only; reachable only from the `/connections` OWNER page; runs only in the owned test runtime, not the production bootstrap. |
| LV Live | LV-02 Live for cloud-account (directory) devices | `LiveViewLayout` streams every logged-in device, including account devices; P03.1 | — | MISSING | Directory devices have no media path. Only `TVT_DEVICE` connections can stream. |
| LV Live | LV-03 Concurrent live from several devices and channels | `LiveViewLayout` + `VideoManagerLayout`; P04.1 | `/monitoring`; `web/features/monitoring/live-wall.tsx`; `web/lib/tvt/live-wall-scheduler.ts`; `bridge/windows_socket.py`; `media/worker.py`; `mig/0015_tvt_local_media_capacity.py` | PARTIAL | Updated2026-10-06: native/media/wall caps16, SQL actor16/global64, serial starts and bounded per-target BUSY waits. c9/c11/c12 rendered nine substreams across two stores; c12 verified a common300.849s progress window and ended a1091.280s live test with nine progressing videos. All twelve did not open; per-tile recorder logins encounter BUSY and occasional pre-login connection/greeting errors. c11 normal cleanup confirmed all201 leases but observation failed; repaired c12 confirmed all90 leases and COMPLETE observation with zero errors/omissions. One recorder connection carrying multiple tasks, viewer fan-out and production wiring remain absent. |
| LV Live | LV-04 Multi-split layouts 1/2/4/6/8/9/13/16 | `VideoManagerLayout`; `view_segmentation_item.xml`; P04.1 | `/monitoring`; `live-wall.tsx`, `live-tile.tsx` | PARTIAL | Updated2026-10-06: responsive automatic/2-column/3-column/4-column grids, store filter and single-channel focus are implemented; a real12-tile surface with nine playing channels was observed. Exact APK split presets, paging and complete12-channel simultaneous acceptance remain absent. |
| LV Live | LV-05 Tile gestures (swap, drag to close, double-tap to maximize, swipe to switch channel or page) | `VideoManagerLayout` gesture handlers (single- and two-finger slide, exchange, delete, double click); P04.1 | — | MISSING | — |
| LV Live | LV-06 Channel selection and switching | `ServerListViewLayout2`; `com.tvt.live.popup.DeviceListPopWindow`; P03.1 | Channel `<select>` in `local-live-panel.tsx` (stops, then starts) | PARTIAL | Switching works only by restarting the stream. Two channels are accepted on real devices. An earlier bounded capture on store 1 position 1 was heartbeat-only and is unresolved. No swipe switching. |
| LV Live | LV-07 Stream and quality selection (main/sub; Full HD/HD/SD/Low presets) and automatic sub-stream in split view | `LiveViewLayout.Z1`; `cw3.jb/kb`; persisted `CodeStreamType`; P03.2 | `local-live-panel.tsx`; `local-live-api.ts`; `live-wall.tsx`; `core/tvt/local_live.py`; `bridge/local_live_provider.py`, `local_live_ipc.py`, `windows_socket_worker.py` | PARTIAL | Updated2026-10-06: main/sub selection is wired end to end; split tiles request sub, focus stops sub then requests main, returning closes main before sub. c9/c10 actual switching worked; c11 showed352x240 and704x480 substreams.1285 modern and1281 legacy sub opens and bounded refusal handling are source-tested. APK named quality presets/custom bitrate/adaptive policy and formal APK comparison remain missing. |
| LV Live | LV-08 Custom stream parameters (resolution, frame rate, bitrate) | `view_custom_rate.xml`; `ku3` `ChangeLiveStream`; P03.2 | — | MISSING | — |
| LV Live | LV-09 Full screen | `video_menu_view.xml` `menu_full_screen`; P03.2 | — (`controls={false}`, no fullscreen action) | MISSING | The browser Fullscreen API is not used. |
| LV Live | LV-10 Digital zoom (pinch or two-finger scale) | `VideoView` two-finger scale gesture; `GL2JNIView` scale enable | — | MISSING | — |
| LV Live | LV-11 Original scale vs stretch to fill | `activity_local_config.xml` `sw_original_scale` ("Original Scale Display Video"); `GlobalUnit.h0`; P20.1 | `local-live-panel.tsx:40` (`object-fill` in a 16:9 box) | PARTIAL | The default stretch matches the APK default and the user accepted it visually (ruling R112; run `local-devices-6bfe84c4…`). The original-scale toggle is missing. |
| LV Live | LV-12 Snapshot (selected tile or all tiles) | `video_menu_view.xml` capture; `VideoManagerLayout` capture; `GL2JNIView` JPEG capture; P05.1 | — | MISSING | — |
| LV Live | LV-13 Local recording to MP4 | `VideoView` + `com.sdk.mediacodec.H264Decode` MP4 recorder; `iv_record_src`; P05.1 | — | MISSING | — |
| LV Live | LV-14 Live audio (listen) | `com.tvt.live.a` (LiveAudioManager); `view_live_bottom_tab.xml` `iv_bottom_audio`; P04.2 | — (video-only `recvonly` transceiver, `web/lib/tvt/local-live-player.ts:25`; native audio unsupported) | MISSING | — |
| LV Live | LV-15 Two-way talk | `com.tvt.live.LiveTalkManager`; `iv_bottom_talk`; P04.2 | — | MISSING | Needs microphone capture, an uplink codec and a device talk session. |
| LV Live | LV-16 Per-tile state (connecting, offline, no permission, retry) | `VideoView` state overlays; P03.1 | `live-wall.tsx`, `live-tile.tsx`, `live-wall-scheduler.ts`; `local-live-panel.tsx` | PARTIAL | Updated2026-10-06: queued/start/negotiating/live/failure states, bounded phase clocks, BUSY per-target3/6/12/15s parks, manual retry and terminal NO_SIGNAL without retry exist. c11 showed BUSY waits while other-recorder channels progressed. Real denied/offline/expiry variants and the full APK state mapping are not independently accepted. Store1 channels1/3 supply valid substream placeholder frames and must not be forced into NO_SIGNAL. |
| LV Live | LV-17 Jump from a live tile to playback of the same channel | `view_live_bottom_tab.xml` `iv_bottom_playback`; `LiveOperateBarView`; P07.1 | — | MISSING | Playback is absent. |
| PT PTZ | PT-01 PTZ pan and tilt (buttons and gestures) | `video_menu_view.xml` `menu_pan_title_control`; PTZ commands in `cw3` / `ew3`; P05.2 | — | MISSING | — |
| PT PTZ | PT-02 Zoom, focus, iris and PTZ speed | `view_ptz_ctrl.xml` (`tv_zoom`, `tv_focus`, `tv_iris`, `sb_speed`); P05.2 | — | MISSING | — |
| PT PTZ | PT-03 PTZ presets and cruise | strings `LiveView_Ptz_Cruise`, `Live_NoPreset`, `Live_NoCruise`; P05.2 | — | MISSING | — |
| PT PTZ | PT-04 Fisheye dewarp modes | `layout_fish_mode.xml` (original, ball, cylinder, square, sphere, VR, cruise); `GL2JNIView`; P05.3 | — | MISSING | Capability-gated. |
| PT PTZ | PT-05 Motorized lens adjustment | `layout_lens_adjustment.xml`; `menu_lens_adjust`; P05.3 | — | MISSING | Capability-gated. |
| PT PTZ | PT-06 White-light or illuminator control | `menu_light_operation`; P06.2 | — | MISSING | — |
| PT PTZ | PT-07 Manual alarm output, light alarm, audio (siren) alarm | `menu_manual_alarm`, `menu_light_alarm`, `menu_audio_alarm`; `view_live_bottom_more_layout.xml`; `defpackage/dj2`; P06.2 | — | MISSING | — |
| PT PTZ | PT-08 Wiper | `rl_wiper_item`; wiper commands in `cw3`; P06.2 | — | MISSING | Capability-gated. |
| PT PTZ | PT-09 Access control (door unlock) | `menu_access_control`; P06.2 | — | MISSING | A safety-sensitive write (W15). |
| PT PTZ | PT-10 AI mode switch and RS485 | `rl_ai_mode_item`, `rl_rs485`; P06.2 | — | MISSING | Capability-gated. |
| PT PTZ | PT-11 Custom alarm sound clips (WAV upload, select, preview, delete) | `audio_alarm_view.xml`; `defpackage/dl`; P06.3 | — | MISSING | — |
| PB Playback | PB-01 Recording search by date (calendar marks recorded days) | `com.tvt.playback.PlaybackActivity`; `view_playback_calender.xml`; record-date search in `cw3`; P07.1 | — | MISSING | — |
| PB Playback | PB-02 Timeline playback and seek | `com.tvt.playback.view.PlaybackViewLayout`, `PlaybackTimeBar`; P07.1 | — | MISSING | — |
| PB Playback | PB-03 Speed, pause, step and rewind | `view_playback_speed.xml`; key-frame and rewind calls (audit 03); P07.1 | — | MISSING | — |
| PB Playback | PB-04 Playback split 1/4/9/16 and multiple channels | `view_playback_segmentation.xml`; `playback_operation_mode`; P07.1 | — | MISSING | — |
| PB Playback | PB-05 Event-type filter, event list, weekly view | `view_playback_event.xml`, `view_playback_week_layout.xml`; P07.1 | — | MISSING | — |
| PB Playback | PB-06 Playback audio | `view_playback_bottom_tab.xml` `playback_operation_audio`; P07.1 | — | MISSING | — |
| PB Playback | PB-07 Snapshot and clip recording during playback | `playback_video_menu.xml` `playback_capture_src`, `playback_record_src`; P05.1/P07.1 | — | MISSING | — |
| PB Playback | PB-08 Back up or download a time range to MP4 with progress | `com.tvt.backup.BackupFileManager`; `view_playback_backup_time.xml`; `playback_download_src`; P07.2 | Generic job and asset infrastructure only (`api/jobs`, `api/assets`) | MISSING | No recorder export path. |
| PB Playback | PB-09 Stream selection and fisheye during playback | `playback_menu_code`, `playback_menu_fish_eye`; P07.1 | — | MISSING | — |
| AI Search | AI-01 AI text or voice search with device and time filters, plus translation | `com.tvt.ai.search.{AISearchInputActivity,AITextSearchFilterActivity,AISearchDeviceFilterActivity,AISearchTimeSelectActivity}`; `com.tvt.speechrecognitionsdk.SpeechRecognitionService`; P08.1/P08.2 | — | MISSING | Recorder-capability-gated. |
| AI Search | AI-02 Attribute and target search (person, vehicle, animal, object) | `AIAttributeSearchActivity`, `AITargetSearchConditionActivity`; P08.3 | — | MISSING | — |
| AI Search | AI-03 Picture (image similarity) search | `AIPicSearchListActivity`, `AIImageSearchTargetSelectActivity`, `AIPicDetailActivity`; P08.3 | — | MISSING | — |
| AI Search | AI-04 Result list and detail with jump to playback | `AISearchListActivity`, `AIDetailActivity`, `AISearchEditActivity`; P08.1 | — | MISSING | — |
| AI Search | AI-05 Search history and recommendations | `AISearchInputActivity`; P08.4 | — | MISSING | — |
| AI Search | AI-06 Face library: enrol faces and groups; face recognition search | `com.tvt.search.FaceRecognitionActivity`, `AddFaceActivity`; `rl_veriface_item`, `rl_face_manager_item`; P09.1 | — | MISSING | Biometric data; needs a privacy review. |
| AI Search | AI-07 License-plate library and search | `AddLicensePlateActivity`, `SearchActivity`; `rl_plate_item`; P09.2 | — | MISSING | — |
| AI Search | AI-08 Event, name and image search entries in live "more" | `rl_event_search_item`, `rl_name_search_item`, `rl_img_search_item`, `rl_search`; P09.2 | — | MISSING | — |
| AL Alarms | AL-01 Alarm and system message lists; unread count; read and delete | `com.tvt.push.PushMessageActivity`; `push_message.xml`; P14.1 (P14.3 D) | — | MISSING | — |
| AL Alarms | AL-02 Alarm detail (snapshot, face, plate, doorbell) with jump to live or playback | `PushMessageActivity` detail branch; P14.2 | — | MISSING | — |
| AL Alarms | AL-03 Real-time alarm delivery (FCM, TVT push socket, Huawei) → notifications | `com.tvt.push.MyFirebaseMessagingService`, `com.tvt.push.tvt.PushMessageSocket`, `HuaweiPushMessageActivity`, `NotifyService`, `PushNotifyService`; P14.1 | — | MISSING | The web needs server-side event ingress plus Web Push and a service worker. |
| AL Alarms | AL-04 Push configuration (global and per device; Push1, Push2, IPC; alarm types; schedules; live "notify" quick switch) | `com.tvt.pushconfig.{PushConfigMainActivity,PushConfigDetailActivity,Push2ConfigDetailActivity,IpcPushConfigActivity,BindIPCPush2ConfigDetailActivity}`; `rl_notify_tip_item`; P15.1 | — | MISSING | — |
| AL Alarms | AL-05 Push token registration and refresh | `/sdk/sendNotificationToken`; `MyFirebaseMessagingService`; P15.2 | — | MISSING | — |
| DC Device config | DC-01 Device basic information (model, firmware version, online time) | `com.tvt.device.ui.information.DeviceCommonInfoActivity`; `view_device_information.xml`; P11.1 | Cloud: `DeviceDetail.tsx` (name, model, version, status, times; synthetic upstream). Local: nothing beyond the channel count | PARTIAL | The accepted local recorders show no model or firmware. |
| DC Device config | DC-02 Channel information (names, status) | `information.DeviceChannelInfoActivity`; P11.1 | Cloud channel detail (synthetic). Local labels are fixed to "Channel N" | PARTIAL | — |
| DC Device config | DC-03 Recording schedule and timed recording | `com.tvt.devicemanager.ScheduleSettingActivity`, `ScheduleTimeRecordingActivity`; `activity_schedule_setting.xml`; P11.2 | — | MISSING | — |
| DC Device config | DC-04 Alarm, sensor, PIR, line-crossing and perimeter switches; alarm information | `DeviceInfoActivity`; `information.DeviceAlarmInfoActivity`; P11.2 | — | MISSING | — |
| DC Device config | DC-05 Disk and SD status, SD format, loop recording | `com.tvt.devicemanager.DeviceSDCardActivity`; P11.2/P11.4 | — | MISSING | Format is destructive (W15). |
| DC Device config | DC-06 Network and Wi-Fi settings | `DeviceInfoActivity` Wi-Fi branch; P11.2 | — | MISSING | — |
| DC Device config | DC-07 Change device password or device users | `com.tvt.device.ui.ModifyDevicePassActivity`; P11.3 | — | MISSING | — |
| DC Device config | DC-08 Firmware upgrade check and upgrade | `information.DeviceCloudUpgradeActivity`; P11.3 | — | MISSING | — |
| DC Device config | DC-09 Power mode and diagnosis mode | `information.PowerSettingActivity`, `information.DeviceDiagnosisModeActivity`; P11.3 | — | MISSING | — |
| DC Device config | DC-10 Reboot | `/sdk/DeviceReboot`; P11.4 | — | MISSING | — |
| DC Device config | DC-11 Cloud-storage encryption settings | `com.tvt.device.ui.CloudStorageEncryptActivity`, `CloudStorageModifyActivity` | — | MISSING | — |
| DC Device config | DC-12 Remote configuration through device web pages (motion detection, image and encoding, OSD, recording, network, users) | `com.tvt.config.ui.RemoteConfigActivity`, `RemoteWebActivity` (WebView JS bridge); P21.1 | — | MISSING | Gated by a brand flag. The delivered H5 behaviour cannot be known statically. |
| DC Device config | DC-13 Defense (arming) configuration | `com.tvt.live.{DevDefenseCfgActivity,DevDefenseAddActivity,DevDefenseDetailCfgActivity}`; P13.1 | — | MISSING | — |
| DB Doorbell | DB-01 Doorbell and IPC Wi-Fi provisioning (soft-AP connect, Wi-Fi QR, bind) | `com.tvt.devicemanager.doorbell.AddDoorBellDeviceActivity`; `WifiConfig{Reset,Input,Connect,HandConnect,BindDevice}Activity`; `com.tvt.wifi_config.WIFIQRCodeBean`; local-config `WIFI_Config` (camera permission); P12.1 | — | NOT_APPLICABLE | The client must join the camera's soft-AP or show a Wi-Fi QR to the camera. A browser cannot switch the host's Wi-Fi or open the local provisioning socket. This needs a phone or an on-site gateway (plan W12). The later account-bind step is covered by DV-08. |
| DB Doorbell | DB-02 Doorbell video call (incoming invite; answer, reject, hang up) | `doorbell.DoorbellVideoTalkActivity`; `MainViewActivity` invite routing; P12.2 | — | MISSING | Needs push plus two-way audio. |
| DB Doorbell | DB-03 Doorbell settings (wired or wireless chime, do-not-disturb, ring, time zone, push, leave-word audio) | `doorbell.chime.*`, `doorbell.timezone.DoorBellTimeZoneActivity`, `DoorBellPushActivity`, `doorbell.leavewordaudio.LeaveWordAudioActivity`; P12.3 | — | MISSING | — |
| DB Doorbell | DB-04 Doorbell activation and device information | `DoorBellActiveDeviceActivity`, `DoorBellDeviceInfoActivity`; P12.4 | — | MISSING | — |
| CL Cloud and VAS | CL-01 Cloud recording list by channel and date; cloud player | `com.tvt.cloudstorage.CloudStorageActivity`, `CloudPlayerActivity`; P18.1/P18.8 | — | MISSING | Entitlement-gated. |
| CL Cloud and VAS | CL-02 Cloud recording download queue and delete | `CloudDownloadActivity`; `defpackage/lo`; P18.2/P18.9 | — | MISSING | — |
| CL Cloud and VAS | CL-03 VAS catalog, eligible devices, service detail | `com.tvt.valueaddedservice.{ValueAddedServiceActivity,VASDeviceListActivity,VASServiceDetailActivity}`; P18.3 (P18.7 D) | — | MISSING | — |
| CL Cloud and VAS | CL-04 VAS purchase, renewal and auto-renew; payment; purchase records | `VASBuyRecordActivity`; `/sdk/applyVASService`, `/sdk/renewalVASService`, `/sdk/payVasInfo`; P18.4 (P18.6 D) | — | MISSING | External payment and merchant configuration. |
| CL Cloud and VAS | CL-05 Cloud recording settings (motion, AI, sensor switches) | `VASCloudStoreSettingActivity`; P18.5 | — | MISSING | — |
| FL Files | FL-01 Album of snapshots and recordings by date; file search | `com.tvt.filemanager.FileManagerActivity`, `SearchFileActivity`; P19.1 | — (the asset API handles private images but is not wired to TVT) | MISSING | — |
| FL Files | FL-02 Image viewer and local video player | `BigImageActivity`, `photo.BigImageActivity`; `com.sdk.player.local.LocalPlayerActivity`; P19.1 | — | MISSING | — |
| FL Files | FL-03 Delete selected files | `FileManagerActivity`; P19.2 | — | MISSING | — |
| FL Files | FL-04 Share an image to another app | `BigImageActivity` share; P19.4 | — | MISSING | The Web Share API is the browser equivalent. |
| FL Files | FL-05 Cloud-to-local file sync | `com.tvt.file_sdk.FileSyncSDK`; P19.3 (D) | — | MISSING | Declaration-only in the APK. |
| LS Local settings | LS-01 Resolution adaption (switch to low resolution when video stutters) | `sw_resolution`; string `Guide_Video_NetWork_Adapter_Description`; P20.1 | — | MISSING | Depends on sub-stream support (LV-07). |
| LS Local settings | LS-02 Snapshot count and split-mode snapshot | `cl_snap_number`, `sw_split_mode_snap` ("Split Snap"); P20.2 | — | MISSING | — |
| LS Local settings | LS-03 Reserved disk space and cyclic recording | `cl_record_reserve` ("Reserved Disk Space (MB)"), `sw_recycle_record`; P20.2 | — | MISSING | Plan W20 keeps browser captures in IndexedDB, so retention still applies. |
| LS Local settings | LS-04 Screen-rotation correction and landscape mode | `sw_correct` ("Screen Rotation Correction"), `sw_landscape`; P20.1 | — | NOT_APPLICABLE | This handles handset orientation-sensor behaviour. Browser layouts are responsive. |
| LS Local settings | LS-05 OSD display toggle | `sw_osd`; P20.1 | — | MISSING | — |
| LS Local settings | LS-06 PTZ direction inversion and gesture prompts | `sw_ptz_dir`, `sw_ptz_diverse`; P20.1 | — | MISSING | Depends on PTZ. |
| LS Local settings | LS-07 Server domain setting | `cl_ip_config` (strings `Domain`, `Modify_Domian_Info`) | Operator-managed startup profile (`core/tvt/startup.py`) | NOT_APPLICABLE | In a hosted multi-tenant service, upstream endpoints are deployment configuration, not an end-user switch. |
| LS Local settings | LS-08 Cache cleanup | `cl_cache_config`, `tv_cleanup` | — | NOT_APPLICABLE | This manages the handset app cache. The browser owns its HTTP cache and storage. |
| LS Local settings | LS-09 Push permission, push-notify switch, alarm pre-playback time | `cl_push_permission`, `sw_push_notify`, `cl_push_lead_time` (`LocalConfig_Pre_Playback_Time`); P20.2 | — | MISSING | Depends on alarms and playback. |
| LS Local settings | LS-10 Language and time zone (multi-language UI) | Default resources plus 31 translated `values-*` locales; the app follows the system locale | `TvtShell.tsx` Settings; `api/tvt/startup.py:138` `/preferences` | PARTIAL | The locale and time-zone preference is stored and used for date formatting. UI strings are hard-coded Korean, and policies exist in en and zh-Hans only. |
| TY Tyco | TY-01 Tyco account login and registration; panel add, login, list, unlink | `com.tvt.tyco.ui.activity.{login.SelectLoginWayActivity,login.LoginActivity,register.RegisterActivity,register.RegisterVerityActivity,register.SetPasswordActivity,panel.AddPanelActivity,panel.PanelLoginActivity,panel.PanelListActivity,account.TycoAccountActivity}`; P22.1 | — | MISSING | Brand flag (`GlobalUnit.a2`). |
| TY Tyco | TY-02 Panel home (status, zones, devices, users, events, troubles) | `panel.PanelMainActivity`; `navigation/tyco_panel_navigation.xml`; `menu/tyco_bottom_nav_menu.xml`; P22.2 | — | MISSING | — |
| TY Tyco | TY-03 Arm and disarm (full or partition); user codes and time | `PanelHomeViewModel`; P22.3 | — | MISSING | — |
| TY Tyco | TY-04 Home-automation outputs (on, off, timer) | `PanelOutputViewModel`; P22.4 | — | MISSING | — |
| TY Tyco | TY-05 Tyco notification options, email and push token | `NotificationViewModel`; P22.5 | — | MISSING | — |
| HA Help/About | HA-01 Help | `com.tvt.help.HelpActivity`; P23.1 | — | MISSING | Brand flag. |
| HA Help/About | HA-02 About (version, policy and AI-consent pages, new-app notice) | `com.tvt.about.AboutActivity`; `com.tvt.web.{WebActivity,TitleWebActivity}`; `cl_new_app_notify`; P23.1 | Policies only (see ST-01) | MISSING | No About or version screen. |
| HA Help/About | HA-03 Experience (demo) mode | `com.tvt.experience.ExperienceActivity`; P23.3 | — | MISSING | — |
| HA Help/About | HA-04 Hidden debug configuration screens | `com.tvt.about.DebugConfigActivity`, `DebugConfigActivity2`; P23.2 | — | MISSING | Probably a product-owner `NOT_APPLICABLE` ruling, but none has been made. Audit 12 still lists these as parity targets. |
| HA Help/About | HA-05 User log and bug-report export | `com.sdk.bugreport.{UserLogActivity,LogAnalysisActivity,LogQRCodeActivity}` | — | MISSING | Reachability was not traced in this review. |
| HA Help/About | HA-06 Household and resident management (conditional H5) | `defpackage/ef2` `cl_resident_manager`; P24.1 | — | MISSING | Shown only when the resident total is above 0. |

## 5. Multi-camera dashboard ("all stores, all cameras at once")

### 5.1 What the APK does

This section is static evidence; the class, method and resource names are from the decompiled 1.18.1.

**Layout capacity**

- `com.tvt.video.VideoManagerLayout` preallocates **16 `VideoView` slots** (`e1()` sizes the array
  from a field initialized to 16).
- It lays out display modes **1, 2** (picture-in-picture), **4, 6, 8, 9, 13 and 16**.
- The split picker is `res/layout/view_segmentation_item.xml` (`iv_mode_1/4/9/16`,
  `iv_mode_2/6/8/13`), handled by `defpackage/a63` and opened from the bottom bar
  (`iv_bottom_display`).
- A tile is bound to a (device address, channel) pair (`VideoManagerLayout.L0`), so one layout can
  mix channels from several recorders.
- Channels beyond the visible tiles are reached by **two-finger paging**. Tiles can be swapped,
  dragged out to close, or double-tapped to show a single tile.
- Playback offers 1, 4, 9 and 16 splits (`view_playback_segmentation.xml`).
- Favorites groups (`FavoriteEditActivity`) are the APK's container for "open this set of cameras".

**Stream policy: sub stream in every split**

- The user's main/sub preference is persisted as `CodeStreamType` and held in `GlobalUnit.N`.
- That preference only applies in single-window display: `LiveViewLayout.Z1()` requires display
  mode 1.
- In every multi-window layout the open request sets "main=false", which means the sub stream. This
  holds on the per-tile open (`F3`), on the batch open of several channels, and in the live audio
  manager (`com.tvt.live.a`).
- The quality presets refine this: strings `LiveView_Ultra_Clear` … `LiveView_Lowest_QCIF_Clearance`
  and `LiveView_Clarity_Custom`, with layouts `view_screen_rate.xml` and `view_custom_rate.xml`.
- So does the local "Resolution Adaption" switch (`sw_resolution`), which drops to low resolution
  when video is not smooth.

**Wire protocol (the N9000 path our two recorders use)**

- `cw3.jb()` opens **each channel as its own task GUID on the device's existing connection**. It
  selects stream index 1 (main) or 2 (sub).
- For peers with protocol version 5 or later, `cw3.kb()` sends a sub-stream open as command
  **1285** (`NET_PROTOCOL_H.CMD_REQUEST_DATA_FF`), with an XML body requesting stream type 2.
- The ProtoSDK device classes (`ku3`, `ew3`) instead pass a stream parameter to
  `NetClientProtocal.RequestLiveStreamTask` and can change it in place (`ChangeLiveStream`).

**Connection model**

- There is **one long-lived connection per device** (an `fu3` subclass).
- Several channels open in one call, using a channel bitmask or a list (`fu3.I5` and `fu3.J5`, each
  calling `cw3.jb` per channel).
- One 6-second keepalive runs per connection (`fu3.N1` → `cw3.v5()`, as recorded in the canonical
  report).
- **Up to 32 devices are auto-connected.** `GlobalUnit.c` is 32. Above that,
  `LocalDeviceActivity.b3` and the `Add_Device_Too_More` string warn the user and switch
  auto-connect off.

**Net effect**

- A 16-tile view of a 16-channel NVR uses **one device connection carrying 16 sub-stream tasks**,
  decoded on the handset (`com.sdk.mediacodec.H264Decode`, MediaCodec hardware or software).
- Two stores with 8 + 4 channels would use **2 connections and 12 sub-stream tasks** on one 16-split
  screen.
- The APK enforces no stream limit beyond the 16 visible tiles. Static analysis does not establish
  the actual handset or recorder capacity.
- Recorders advertise `maxConnNum`, `maxMainstreamNum` and `maxSubstreamNum`. These field names
  already appear in our cloud projection (`core/tvt/directory_projection.py:160-165`), but the local
  live path does not use them.

### 5.2 Historical stack limits — 2026-10-04 (superseded for changed layers)

| Layer | Limit | Evidence | Effect on a dashboard |
| --- | --- | --- | --- |
| SQL lease | One non-closed lease per (connection, channel), **across all users** | `mig/0013_tvt_local_media_leases.py:37-38` (unique index while not STOPPING/CLOSED); `:128` (capacity check) | A second viewer of the same camera (another user, tab or dashboard) is rejected. There is no fan-out. |
| SQL lease | 32 outstanding leases globally | `mig/0013…:129` | Hard ceiling for the whole deployment, including STOPPING and quarantined rows. |
| SQL lease | 4 outstanding leases per tenant and actor | `mig/0013…:130` | One user can never see more than 4 tiles. |
| SQL authorization | Lease issuance requires the tenant OWNER role | `mig/0013…:114` + `mig/0002_connections.py:84-92` (`role='OWNER'`) | Staff and store-manager viewers cannot watch. The player lives only on the OWNER `/connections` page. |
| SQL lease | TTL of 5–30 s; browser heartbeat every 10 s; control cap of 4 per lease | `core/tvt/local_media_admission.py:38-42`; `mig/0013…:115,238`; `web/lib/tvt/local-live-player.ts:29` | Each tile adds steady heartbeat traffic and SQL load. |
| SQL pool | Media admission pool of 4 + overflow 4; 50 ms permit heartbeat per stream (ruling R107) | `core/tvt/local_media_admission.py:139-146`; `docs/analysis/2026-10-04-local-media-liveness-review.md` | Authority checks scale linearly with tiles. Earlier `NullPool` p95 latency was about 125 ms. |
| Native provider | **At most 2** healthy live owners per process | `bridge/windows_socket.py:977` (`MAX_SERVICE_LIVE_SESSIONS = 2`), enforced at `:1030-1031` | A third tile gets `LOCAL_DEVICE_BUSY`/429. |
| Native provider | A process-wide attempt lock, acquired without blocking for service calls | `bridge/windows_socket.py:976,980-987,1010` | Starting tiles at nearly the same time returns 429. This was observed: the second of two near-simultaneous starts failed. The client does not retry. |
| Native provider | Device verification is refused while any live owner is pending | `bridge/windows_socket.py:1032-1033` | The dashboard cannot refresh an inventory while it is streaming. |
| Native session model | **Every lease is a fresh device login, socket, process and Job with an exclusive first task on stream 1.** No socket is shared. | `bridge/local_live_ipc.py:249-254` (`stream=1`, `exclusive_first_task=True`); `core/tvt/local_live.py:214-216` (an exclusive task requires stream 1); route-0 binding at `:458`; `docs/integrations/tvt-windows-live-session.md:15-21` | 12 tiles would mean 12 device logins and 12 child processes. That contradicts the APK model (one connection with N tasks) and plan section 4 line 119 ("one long-lived device connection … do not connect on every tile render"). It also risks hitting the recorder's `maxConnNum`. |
| Stream | **Main stream only** | `bridge/local_live_provider.py:39,52,203-204`; `web/lib/tvt/local-live-api.ts:46`. The contract, SQL and codec already admit sub (`contracts/tvt/local_media.py:18`, `mig/0013…:28,115`, `core/tvt/local_live.py:300-309`), but 1285 replies are not handled (`core/tvt/local_live.py:452`). | Every tile would be a 1280×1936 HEVC main stream at about 10 fps (observed on these recorders), where the APK would use sub streams. |
| Media worker | **At most 2** concurrent sources | `media/worker.py:115,145` (`len(self._sources) >= 2`) | Second independent ceiling of 2. |
| Media pipeline | Per-stream isolated HEVC → RGB decoder process, then aiortc **VP8 re-encode**; ingress FIFO of 16 frames / 4 MiB | `media/native_source.py:326-327,339,372-377`; `media/live.py:207-212` | Server CPU grows with tiles × viewers. Indicative only, not a capacity measurement: with 2 streams the runtime used about 0.5–0.9 of one core, plus about 12% per decoder child and about 4% per native child (liveness review). |
| Signaling | `RTCPeerConnection({iceServers: []})` and no TURN | `web/lib/tvt/local-live-player.ts:10` | Only localhost or same-LAN browsers can play. A remote dashboard would fail ICE. |
| UI | One `<video>` per connection card, with no grid, layouts, paging or retry | `web/features/connections/local-live-panel.tsx:37-41`; `web/features/connections/connections-view.tsx:286` | There is no dashboard surface. `/stores/[storeId]` shows only name, status and time zone. |
| Bootstrap | **The production bridge factory does not wire the media worker** | `bridge/server.py:540,637-651` (`create_server_from_environment` passes no `local_media_worker`). Only the test runtime does: `scripts/test-local-devices/runtime.py:739-787`. The worker is accepted at `bridge/server.py:434,495-498`. | Live video exists only inside the owned test runtime. |
| Device scope | Live is available only for `TVT_DEVICE` (SN plus device credentials) connections | `api/tvt/local_media.py` routes take `connection_id`; the directory reads in `api/tvt/devices.py` have no media path | Cloud-account devices, which the APK shows in its device list, cannot be put on a dashboard. |

### 5.2.1 Current stage-1 limits and execution — 2026-10-06

The table above is retained historical evidence. Current changed limits are:

| Layer | Current implemented behavior | Executed evidence and remaining limits |
| --- | --- | --- |
| SQL | Migration0014 nonlocking hot-path observe,100ms start-anchored cache;0015 actor16/global64 |47 guarded SQL tests passed; c9 stable1/4/8-stream windows19.500–22.065,18.861–21.084,19.538–20.850tx/s/live. No twelve-stream sample. |
| Pool/startup |8+8 pool, at most eight long startups reserving remaining pool slots | Real SQL contention regression passed; finite short-query stalls remain possible. |
| Native/media/wall |16 sources/owners, serial starts,10s bounded original-custody wait | Real maximum nine playing sources, not a measured universal recorder cap. |
| Stream/UI | End-to-end main/sub; split=sub, focus=main then return=sub; responsive monitoring wall | Actual c9/c10 switching and c11 nine substreams. Exact APK layouts/presets are incomplete. |
| Decoder/ingress | Same-owner bounded same-codec rotation,16frames/4MiB producer credit, original retirement before successor | c9 actual rotations and4/8 healthy streams; R142 raw/mapped timestamp repair is reviewed. c11 long-hold evidence was lost to writer capacity; repaired c12 completed1091s with no recorded timestamp/queue/format first failure, without per-branch equality telemetry. |
| Startup refusal | Exact proven post-reap login BUSY maps429; per-target bounded retry does not starve another recorder | c11 second recorder reached all four channels while first-recorder BUSY targets waited. Two actual502 responses occurred before login at connect/greeting, not incorrectly recovered BUSY. |
| Session model | One login/process/Job per tile; no per-device multiplexer | Twelve simultaneously live tiles remain unaccepted. APK uses one login with multiple channel tasks. |
| Unchanged scope | OWNER/local devices only, no viewer fan-out, no TURN or production media bootstrap | Source/runtime tests and local Chrome playback do not establish production or APK parity. |

### 5.3 Historical consequence for "2 stores × 12 cameras" and beyond

| Aspect | APK | Today |
| --- | --- | --- |
| Device connections | 2 connections | — |
| Streams | 12 sub-stream tasks | **at most 2** concurrent tiles in the whole deployment (2 native owners, 2 media sources) |
| Layout | 16-split (or 9-split plus paging) | no grid |
| Per-user ceiling | — | 4 leases per user, even if the native and worker caps were raised |
| Other viewers | — | a second viewer of the same camera is refused |
| Staff access | — | staff cannot view |
| Quality | sub streams | main streams only |
| Remote browsers | — | not supported (no TURN) |
| Simultaneous starts | — | 429 |
| Production | — | live media is not wired |

Raising the numeric caps alone would not reach APK parity:

- 12 per-tile device logins would probably exceed recorder connection limits. `maxConnNum` for these
  two recorders is unmeasured.
- 12 main-stream decode and VP8 re-encode pipelines would multiply server CPU. A dashboard with N
  viewers would multiply that again, because there is no fan-out.

### 5.4 Changes needed for a dashboard

These are design direction only. Nothing below is implemented, and the order is the suggested order.

1. **Per-device session multiplexer.**
   - One long-lived native login per recorder, carrying N channel tasks with one shared 6 s
     keepalive, as in the APK and plan section 4.
   - Retire the exclusive-first-task and route-0 binding for that mode. It needs a task-fenced route
     (route 2) or an equivalent per-task binding, followed by a new codec and native review.
2. **Sub-stream support.**
   - Stream 2 through 1281 for peers below version 5, and the 1285 XML open with its reply lifecycle
     for version 5 and later.
   - Automatic policy: sub stream in any split, main stream on focus, single tile or full screen
     (matches `LiveViewLayout.Z1`).
   - Expose the quality presets and use the recorder's `maxSubstreamNum` and `maxMainstreamNum`
     limits.
3. **Separate the upstream from viewers.**
   - Lease viewers per (viewer, tile).
   - Share one upstream per (device, channel, stream) through reference counting and a WebRTC fan-out.
   - Replace the per-channel unique active-lease index (`mig/0013…:37-38,128`) with a per-upstream
     record plus per-viewer leases.
4. **Media cost.**
   - Measure decode and encode cost per sub-stream tile.
   - Evaluate passthrough for H.264 sub streams, and limit transcoding to HEVC or main streams.
   - Lift `media/worker.py:115,145` and `bridge/windows_socket.py:977` to measured values.
   - Make the attempt lock queue instead of returning 429.
5. **Capacity gates.**
   - Execute the plan's W08 sizing gate (1, 4, 9 and 16 tiles) on the actual recorders.
   - Record CPU, memory, bandwidth, p50/p95 latency and orphan duration before choosing caps.
6. **Dashboard UI.**
   - Layouts 1, 4, 9 and 16 with paging.
   - A store or favorites grouping (DV-12).
   - Per-tile states, retry and backoff, and full screen and zoom on focus.
7. **Authorization.**
   - A viewer role for staff (today live issuance is OWNER only), scoped per store.
8. **Production and remote access.**
   - Wire the media worker into `create_server_from_environment`.
   - Add quarantine and orphan recovery on restart.
   - Add a TURN or relay policy.
   - Decide where the Windows-only native bridge runs (on-site per store or central).

## 6. Prioritized gaps

### P0: blocks the stated goals (APK-equivalent core surveillance and an all-cameras dashboard) or any production use

1. **Multi-view live and capacity** (LV-03/04/05/07, LS-01).
   - Today: at most 2 tiles; main stream only; one device login per tile; 1 viewer per channel;
     4 tiles per user.
   - Needed: section 5.4 items 1 to 6.
   - Rationale: this is the APK's default home screen and the user's next goal.
2. **Production enablement of live video** (LV-01 limits).
   - The media worker is missing from the production factory.
   - There is no TURN or remote access.
   - Quarantined leases hold capacity across restarts.
   - The 429 on simultaneous starts is not retried.
   - Rationale: the only accepted live path exists only in the owned test runtime on localhost.
3. **Recorded playback and export** (PB-01..09, LV-17).
   - Calendar and record-day search, timeline and seek, speed, playback split, event filter, and
     time-range download.
   - Rationale: playback is the APK's second core function and the follow-up for every alarm.
     Nothing is implemented beyond generic job and asset primitives.

### P1: core APK functions users rely on daily

4. **Alarms and push** (AL-01..05, ST-03, LS-09).
   - Event ingress (an equivalent of the TVT push socket or FCM), message list and detail with jumps
     to live and playback, Web Push and a service worker, and push configuration.
5. **Audio listen and two-way talk** (LV-14/15).
   - The pipeline is video-only (`recvonly`), and native audio is unsupported.
6. **PTZ and camera actuators** (PT-01..03, then PT-06/07).
   - Pan, tilt, zoom, focus, iris, presets and cruise; light, siren and manual alarm.
   - Requires authoritative readback and W15 safeguards.
7. **Snapshot, local recording and the album** (LV-12/13, PB-07, FL-01..04).
   - Browser-local captures (IndexedDB, as the plan intends) or server assets, plus download and
     share.
8. **Cloud-account parity** (LV-02, DV-08, and the 12 `IMPLEMENTED_UNACCEPTED` rows).
   - Devices from the TVT account cannot stream.
   - Login, registration, recovery, profile, the directory and share reads have never run against a
     real TVT account or beside the APK. Until they do, `MATCHED` cannot move above 0.
9. **Device management completeness** (DV-06, DV-09..15).
   - IP/DDNS add, cloud bind and unbind, rename, sorting, favorites and groups.
   - One unified device status, and channel names and model/firmware for local recorders (DC-01/02).
10. **Account security writes** (AC-10..12, AC-16).
    - Private adapters already exist (`core/tvt/security_client.py`) but have no RPC, API or UI.
11. **Live viewing controls** (LV-08..11, LV-16).
    - Quality and custom stream settings, full screen, digital zoom, an original-scale toggle, and
      distinct tile states.
12. **Sharing writes** (SH-02..06).
    - Create, accept, edit and revoke shares, share QR codes, and friends.
13. **Device configuration basics** (DC-03..05, DC-07, DC-10, DC-12).
    - Record schedule, motion and alarm switches, HDD or SD status, password, reboot, and remote
      configuration, with W15 confirmation for destructive actions.

### P2: conditional, brand-gated or lower frequency

14. AI, face and plate search and libraries (AI-01..08): recorder-capability-gated, and biometric
    data needs a privacy review.
15. Cloud storage, VAS and payment (CL-01..05): entitlement-gated, with external payment and merchant
    configuration.
16. Doorbell call and settings (DB-02..04): device-dependent, and requires push plus talk first.
17. Tyco panel (TY-01..05): brand flag.
18. Third-party, IT20 and LINE login and binding; user QR; account type; installer (AC-06/07/13/14/15):
    region- and brand-gated.
19. Help, About, Experience, debug screens, user log, household H5 (HA-01..06) and the guide and
    launch setting (ST-02/04).
20. Remaining local settings (LS-02/03/05/06), capability-gated camera features (PT-04/05/08/09/10/11)
    and defense configuration (DC-06/08/09/11/13).
21. UI localization to the APK's 31 translated locales (LS-10).

## 7. Risks and open product questions

- **Recorder limits are unmeasured.** The real `maxConnNum`, `maxSubstreamNum`, sub-stream
  resolution and codec, and the per-connection task limits of the two recorders are not known. The
  dashboard design depends on them.
- **Browser codec path.** HEVC playback in browsers is limited, so the current design transcodes to
  VP8 on the server. Whether the sub streams are H.264 (passthrough-capable) is unknown. Server cost
  per tile per viewer is the main scaling risk.
- **Deployment of the native bridge.** It requires Windows (recovered AMD64 DLLs). Placement (an
  on-site box per store or central) and vendor rights were already release questions in the
  canonical report.
- **Viewer model.** Should staff see all stores? Today live is OWNER only, and the connection page
  is OWNER only.
- **Rulings needed per brand and region.** Possible `NOT_APPLICABLE` rulings for this deployment:
  debug screens, Tyco, IT20, VAS and payment, household H5. A ruling must be made per support-matrix
  row, as ledger comparison rule v0 requires. It cannot be inferred.
- **Cloud vs local devices.** Is live parity needed for cloud-account devices, or does local
  SN-based registration satisfy the intended users?
- **Safety.** Unlock, siren, format, firmware, reboot and payment must keep the W15 confirmation,
  readback and unknown-outcome rules. A toast is not acceptance.

## 8. Verification performed in this review, and its limits

**Commands run.** All were read-only, in Git Bash, against the worktree and the private
decompilation:

- `git rev-parse HEAD`, `git branch --show-current`, `git status --short`,
  `git status --short --untracked-files=all`, `git diff --shortstat`, `git log -1`.
  - Result: HEAD `211d1484…`; branch `codex/superlive-web-service`; 24 modified files
    (+2,355 / −81); 39 untracked entries (45 files).
- `find`, `ls`, `grep -n`, `sed -n` and `wc -l` over:
  - `apps/web/src/**`, `services/api/src/wso_api/**`, `packages/core/src/wso_core/tvt/**`,
    `packages/contracts/src/wso_contracts/tvt/**`, `services/tvt-bridge/src/wso_tvt_bridge/**`,
    `services/tvt-media/src/wso_tvt_media/**`, `infra/migrations/versions/{0002,0013}*`,
    `scripts/test-local-devices/runtime.py`, and the documents listed in section 1;
  - for the APK: `apktool/AndroidManifest.xml`, `apktool/res/layout/*.xml`,
    `apktool/res/values*/strings.xml`, and `jadx-full/sources/com/tvt/**` and
    `defpackage/{fu3,cw3}.java` (class, method and resource confirmation only).

**Not done:**

- No tests, builds, servers, browsers, database, device or network contact.
- No repository file was modified, created, staged or deleted.

**Limits:**

- **Statuses come from recorded evidence.** They depend on the canonical report and its linked
  documents as of 2026-10-04 and were not re-executed. `ACCEPTED_REAL` here means a recorded
  real-browser, real-recorder acceptance. It is not an independently re-verified result, and not a
  `MATCHED` APK comparison.
- **The APK inventory was reused, not re-derived.** It comes from the 2026-09-27 audit (01, 03, 12,
  14) and was spot-verified rather than exhaustively rebuilt.
  - JADX reported 391 errors, and names are obfuscated.
  - The 300 `*ActivityPage` entries are excluded.
  - Brand, region, model and firmware gating cannot be resolved statically.
  - APK runtime behaviour, such as handset tile capacity and real sub-stream switching, is inferred
    from code.
- **Row granularity is this review's grouping.** Counts are unweighted. A different split would
  change the numbers, but not the conclusion.
- **The CPU figures in section 5 are an indication only.** They are single-run observations from the
  liveness review, not a capacity measurement.

## 9. Handoff and integration note

Under the shared analysis policy, a durable project report and an `AGENTS.md` entry are expected.
Because this review was explicitly read-only, neither was written. The parent should:

1. Copy this file into the active worktree as `docs/analysis/2026-10-04-apk-feature-parity-review.md`,
   or another path the parent chooses.
2. Add a short bullet to the worktree `AGENTS.md`: "APK feature parity matrix (141 features,
   statuses, multi-view limits): `docs/analysis/2026-10-04-apk-feature-parity-review.md`. Read before
   planning feature work; refresh statuses after each acceptance."
3. Cross-link it from `docs/service-analysis.md`, under priorities or evidence references.
4. Leave `docs/integrations/tvt-parity-ledger.md` unchanged. `MATCHED=0` and `release_ready=false`
   still hold, and this review grants no `MATCHED` or `NOT_APPLICABLE` status under the ledger's
   rules.

## 10. Update log

- **2026-10-04 (Asia/Seoul):** initial read-only review.
  - 141-row matrix, traced to P01.1–P24.1.
  - APK multi-view, stream and connection-model behaviour verified from the decompiled 1.18.1.
  - Current worktree limits recorded with file:line references.
  - Prioritized gaps P0/P1/P2.
  - No execution or repository changes.
- **2026-10-04 (Asia/Seoul):** adopted into `docs/analysis/`, registered in `AGENTS.md` and cross-linked from
  `docs/service-analysis.md` by the controller; content unchanged from the reviewer's deliverable.

- **2026-10-06 (Asia/Seoul):** scoped stage-1 update at HEAD6436748 plus
  uncommitted reviewed changes. LV-03/04/07/16 and current limits refreshed from
  source and c9/c10/c11 receipts; LV-04/07 change MISSING to PARTIAL (two rows).
  Counts are now2 accepted/12 implemented-unaccepted/14 partial/109 missing/4
  not applicable. Original inventory and unrelated rows are historical; no
  full re-inventory, production acceptance or APK MATCHED claim. Canonical
  service report records failed12-tile gate, c10 exceptional retirement and
  c11 normal resource cleanup with FAILED observation publication.

- **2026-10-06 (Asia/Seoul), c12 actual refresh:** common five-minute nine-stream
  progress, main/sub return, ten rapid click pairs and90CLOSED/confirmed leases;
  repaired observer COMPLETE/hash/zeroerrors+omissions. Source statuses/counts
  remain unchanged: LV-03/04/07/16 stillPARTIAL and12tile gate stillopen. See
  [independent acceptance audit](2026-10-06-multiview-stage1-acceptance.md).
