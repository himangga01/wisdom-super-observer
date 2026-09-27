# SuperLive Plus 1.18.1 — reachability and route-gap follow-up

Date: 2026-09-27. This is a **read-only static** follow-up for the same extracted base APK described in [the audit index](README.md). `J:path:line` refers to `C:\wso-private\superliveplus\1.18.1-2026-09-27\jadx-full\sources\`; `M:line` refers to that extraction's `apktool/AndroidManifest.xml`. No login, device command, network capture, purchase, or Android runtime test was performed. An app call site establishes a potential user path, **not** a successful server/device outcome. Searches for absent call sites cannot rule out reflection, native initiation, or downloaded HTML/JavaScript.

## Decisions that change the parity inventory

| Contract or gap | Static result | Consequence for the parity plan |
| --- | --- | --- |
| **P13.1 defense configuration** | **Conditional UI entry path found.** A protection-settings click reaches the live-view callback, which checks the selected device and navigates to the defense screen. The defense screen links to add and detail screens. | Reclassify the entry path from declaration-only to conditional; keep successful reads/writes unverified. Test the model/permission gates and each add/edit/readback action. |
| **P23.2 debug / P23.3 Experience** | **About-screen entry paths found.** Repeated logo taps expose two debug links; About also wires an Experience link. | Treat each as a separate conditional UI contract, subject to brand/local-setting gates. Do not equate debug tooling with ordinary end-user parity without a scope decision. |
| **P18.6–P18.9 alternate cloud routes** | **Mixed status.** Three named routes have app-layer call sites; one switch executor is empty. Two of the called routes encounter empty `TVTOpenSDK` callbacks, and `GetCloudVideoList` has app callback handling but no matching named `TVTOpenSDK` reply method found. | Test each route separately. A caller is evidence for a reachable attempt, while each successful response remains a runtime question. Do not discard the cloud download route as unused or count an empty callback as success. |
| **P24.1 resident/household management** | **New conditional user-visible branch.** The logged-in side menu queries resident-manager state, shows the entry when `total > 0`, and opens a remote household-management H5 path. | Add a page/action capture gate. The original 69-case denominator could not cover this branch; the revised contract inventory has 74 rows after splitting cloud and About paths. |
| **Device-record information route** | The `DeviceRecordInfoActivity` annotation duplicates the channel-info route, but the generated ARouter map resolves that route to `DeviceChannelInfoActivity`, which alone is in the manifest. | Do not count record-info as a second reachable screen from the annotation. Compare the actual channel-info UI; investigate any separate record-info entry only if runtime or another explicit intent reveals one. |

## Follow-up on the seven originally declared-only P contracts

### P02.5 — web QR authorization

`SendUUIDForWebLoginRequest` and `SendAuthForWebLoginRequest` dispatch to `sendUUIDforWebQrcodeLogin` and `sendAuthorizationforWebQrcodeLogin` respectively (`J:com/tvt/protocol_sdk/request/SendUUIDForWebLoginRequest.java:10-25`; `J:com/tvt/protocol_sdk/request/SendAuthForWebLoginRequest.java:10-30`). Both routes are registered and have reply hooks (`J:com/tvt/protocol_sdk/TVTRequesterImpl_Group_sdk.java:376,407`; `J:com/tvt/protocol_sdk/TVTOpenSDK.java:2927,3040`). A source search for these route names and callback names outside `com.tvt.protocol_sdk` found no UI/presenter call site. **Retain `DECLARED` for entry reachability.**

Runtime question: does scanning a web-login QR or another brand-specific entry issue either request? If so, record UUID expiry, explicit approval/denial, callback, account state, and the complete UI path. The request classes alone do not establish a usable web QR feature.

### P13.1 — defense list/add/detail

`ServerListViewLayout2` builds a protect view with a clickable protection control (`J:com/tvt/live/view/ServerListViewLayout2.java:541-565,625-627`). It shows that control only under selected-device checks, including `DeviceItem.R()`, `DeviceItem.D()`, and `c0().s3()` (`J:com/tvt/live/view/ServerListViewLayout2.java:1235-1266`). The callback in `LiveViewLayout.q` reports no-data, invalid-parameter, remote-control-permission, and configuration-permission errors, then navigates to `/home/DevDefenseCfgAct` (`J:com/tvt/live/LiveViewLayout.java:4354-4378`). That Activity links to add and detail routes (`J:com/tvt/live/DevDefenseCfgActivity.java:233,333`); the three Activities are in the manifest (`M:243-245`). **The entry is conditional, not declaration-only.**

Runtime questions: which device types/firmware expose the protect view, what does each `ir0.a.o` result mean on supported and restricted accounts, and do add/edit actions persist remotely? Recording-schedule controls elsewhere do not by themselves prove the defense subflow.

### P14.3 — generic account alarm list/count routes

The generic `/sdk/getDeviceAlarm*` requests are registered and have native reply methods (`J:com/tvt/protocol_sdk/TVTRequesterImpl_Group_sdk.java:320,347,404,537`; `J:com/tvt/protocol_sdk/TVTOpenSDK.java:1568-1604`). The [alarm audit](04-alarms-push.md) found no direct application call site for those four generic list/latest/count/unread routes. The visible inbox instead uses a persisted local push list, Push2 history/detail, and system-message requests (`J:com/tvt/push/PushMessageActivity.java:280-295,780-790,955-999`; `J:defpackage/da3.java:273-385`; see [04](04-alarms-push.md#message-data-ui-and-routing)). **Retain `DECLARED` for the generic routes while keeping the reachable inbox in P14.1–P14.2.**

Runtime question: does any less visible account/brand screen issue a generic route, or do observed alarm pages use only the push/cache paths? Trace callback keys before counting a generic route as part of inbox parity.

### P17.5 — alternate shared-list query

The `getSharedListToAccount` request is registered (`J:com/tvt/protocol_sdk/TVTRequesterImpl_Group_sdk.java:492`), but its reply method sends the callback under `Protocol_Type.DeleteShared` (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:2280-2285`). A source search found no app-layer call to this route outside `com.tvt.protocol_sdk`. There are separate app calls for sent and received lists through `GetSharedListToOther` and `GetSharedListFromOther` (`J:defpackage/gk2.java:172-180,215-225`), plus a target-user list call (`J:defpackage/jx3.java:103`). **Retain `DECLARED` for this alternate route; do not infer that the visible sharing lists are broken.**

Runtime question: is `getSharedListToAccount` ever invoked by a conditional share/friend screen? If invoked, does the mismatched callback label prevent or alter delivery? Compare the visible sent/received/target-user list outcomes through their actual routes.

### P18.6–P18.9 — four alternate cloud/VAS paths

- **P18.6** `/sdk/setVasInstSwitch` is registered, but `VASSetInstSwitchRequest.execute` has an empty body (`J:com/tvt/protocol_sdk/TVTRequesterImpl_Group_sdk.java:547`; `J:com/tvt/protocol_sdk/request/VASSetInstSwitchRequest.java:10-27`). No app-layer call was found in the source search. Its successful switch action remains declaration-only.
- **P18.7** `/sdk/deviceCloudStorageIsValid` has an app-model request (`J:defpackage/he1.java:164-203`), and its executor invokes `RequestCallback.deviceCloudStorageIsValid` (`J:com/tvt/protocol_sdk/request/DeviceCloudStorageIsValidRequest.java:8-13`), whose `TVTOpenSDK` implementation is empty; a separate named reply method exists (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:1080-1085`). No visible UI invocation was established in this pass, so retain declared-only entry status with a potential app-model path.
- **P18.8** `/sdk/getValidCloudStorageChlList` is reached through `CloudStorageActivity`'s presenter (`J:com/tvt/cloudstorage/CloudStorageActivity.java:690`; `J:defpackage/w60.java:334-336`; `J:defpackage/l60.java:378-389`), but the corresponding `TVTOpenSDK` callback implementation is empty; a named reply hook exists (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:2468-2473`). Its observed success is unresolved.
- **P18.9** `/sdk/GetCloudVideoList` is called by the cloud download helper and another app model (`J:defpackage/lo.java:313-339`; `J:defpackage/l60.java:275-296`). The download callback parses a `RecordVideoListBean` and produces OSS/object references or an error (`J:defpackage/lo.java:228-269`). A source search found no matching named `GetCloudVideoListReply` in `TVTOpenSDK`; that absence is a dispatch question, not proof that downloads fail.

Runtime questions: which of these calls fire from a cloud-entitled screen, which callback actually completes, and what timeout/error or alternate path appears when the empty Java implementations are hit? Test each route separately; cloud eligibility, list, playback, and download may use different working edges.

### P19.3 — FileSyncSDK cloud/local synchronization

`LaunchApplication` calls only `FileSyncSDK.Init()` during startup (`J:com/tvt/launch/LaunchApplication.java:600`). `FileSyncSDK` declares upload, download, compare, delete, and stop native operations, with its `start()` dispatching by type 4096–4099 (`J:com/tvt/file_sdk/FileSyncSDK.java:20-43,115-127`). A source search found no `new FileSyncSDK` or app-layer `start()` call outside the SDK file. The ordinary file manager has its own visible local list/player path ([01](01-ui-feature-inventory.md#사용자-기능-목록)). **Retain `DECLARED` for user-started synchronization; initialization is not a sync outcome.**

Runtime question: can a user or server event start FileSync through reflection/native code or a remote page, and are cloud files exposed through a separate screen? If no entry appears in the supported matrix, keep it outside local-file P19.1–P19.2 success claims.

### P23.2 debug and P23.3 Experience

`AboutActivity` decrements a persisted `ShowDebugConfig` counter on logo clicks and then reveals two debug rows and saves `DebugConfig=true` (`J:com/tvt/about/AboutActivity.java:59-79,199-222,260-267`). Those rows navigate to `DebugConfigActivity` and `DebugConfigActivity2` (`J:com/tvt/about/AboutActivity.java:55-56,104-105`). This is **P23.2**. About separately wires `clUserExperience` to `ExperienceActivity` (`J:com/tvt/about/AboutActivity.java:88-90,157-164`), now **P23.3**. All three destinations are manifest-declared (`M:114,136-137`). **Both entry paths are conditional reachable UI; actual settings/actions and brand visibility remain unverified.**

Runtime questions: how many taps are needed from clean storage, do brand flags hide or disable the logo/Experience row, what do the debug controls change, and should those controls count as user product behavior or diagnostic-only scope? A hidden route name alone is insufficient, but the click path here is stronger than a declaration.

## P24.1 — conditional household management

The side menu initially hides `cl_resident_manager`; when logged in it calls `GetResidentManagerState` (`J:defpackage/ef2.java:249-255,480-485`). The presenter requests that route, reads a response `total`, and returns true only when it is positive (`J:defpackage/he1.java:527-563`). A true result shows the menu row (`J:defpackage/ef2.java:96-113`); the row's click opens a server-hosted `/plusapp/#/household/management` page (`J:defpackage/ef2.java:142-148,226-231,386-393`). Resident device/building/room request classes also exist (`J:com/tvt/protocol_sdk/Protocol_Type.java:127-130` and [02](02-protocol-api.md#other-services-16-classes)), but their names do not describe the downloaded page's actions.

Runtime questions: which account, region, brand, and resident data make `total > 0`; what pages, reads, writes, permissions, and errors exist in the delivered H5 bundle; and which account/device effects persist? P24.1 covers discovery and entry; the H5 inventory may require additional atomic cases for each observed action. The APK cannot supply the current remote HTML by itself.

## Other route defects and working alternatives

### Image verification is not a standalone working request

`CheckImgVerifyCodeRequest.execute` is empty (`J:com/tvt/protocol_sdk/request/CheckImgVerifyCodeRequest.java:9-20`). The image **fetch** path is separate and called by several account models, for example `GetImgVerifyCode` in `J:defpackage/ws.java:131-136`; `GetImgVerifyCodeRequest` invokes the native callback (`J:com/tvt/protocol_sdk/request/GetImgVerifyCodeRequest.java:9-16`). A phone dynamic-code request then sends the entered `imgCode` as part of `GetDynamicCodeWithAccount` (`J:defpackage/ws.java:192-199,207-211`). This is a concrete alternate validation edge for that flow, not proof of successful registration or every account mode.

Runtime question: does the server reject an incorrect/expired image code during dynamic-code issuance, and do phone, email, registration, and recovery all use this same edge? Do not implement or test an independent successful `/sdk/checkImgVerifyCode` call merely because it is registered.

### Device information annotation collision

Both `DeviceRecordInfoActivity` and `DeviceChannelInfoActivity` carry `@Route(path = "/device/DeviceChannelInfoActivity")` (`J:com/tvt/device/ui/information/DeviceRecordInfoActivity.java:44-47`; `J:com/tvt/device/ui/information/DeviceChannelInfoActivity.java:44-47`). The generated route map points that path to **DeviceChannelInfoActivity** (`J:com/alibaba/android/arouter/routes/ARouter$$Group$$device.java:80`); `DeviceInfoActivity` invokes that path (`J:com/tvt/devicemanager/DeviceInfoActivity.java:1462`), and only `DeviceChannelInfoActivity` has a manifest Activity entry (`M:109`). No explicit record-info entry was found in the inspected source. Thus the duplicate annotation should not create a second parity screen by itself.

Runtime question: does any direct/reflective intent reach the record-info class, or does the channel-info UI cover the available channel/record information? Verify the route destination once on an authorized fixture before assigning separate cases.

## Evidence still needed before a `MATCHED` outcome

This source pass changes **entry-path classifications**, not server success. The priority runtime captures are: defense capability/permission branches, hidden About behavior, each called cloud route's callback/timeout, resident H5 content and effects, and the image-code validation edge. Keep the remaining declared-only QR, generic alarm-list, alternate share-list, and FileSync paths unproven unless a real entry/call trace is observed. Do not use route registration, a native declaration, or the presence of an Activity as the observation oracle.
