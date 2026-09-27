# SuperLive Plus 1.18.1 protocol API surface (static audit)

This inventory covers the APK’s `com.tvt.protocol_sdk` request router, `TVTOpenSDK` Java/JNI boundary, and both packaged `libProtoSDK.so` ABIs. It is static evidence only: a route, declaration, or exported symbol does not establish a successful network call. No account, device, or service was contacted. Whether this APK-internal wrapper is a publicly distributed SDK is unverified; see the separate [public-source check](00-tvtopensdk-web-check.md). The similarly named public `NET_SDK_*` project is not evidence for this API.

## Evidence and counting rules

- `J:` paths below are relative to `C:\wso-private\superliveplus\1.18.1-2026-09-27\jadx-full\sources`; `E64:` and `E32:` offsets are ELF dynamic-symbol `st_value` in `apktool/lib/{arm64-v8a,armeabi-v7a}/libProtoSDK.so`. The extracted arm64 copy was also inspected. Source line numbers are JADX 1.5.6 output locations.
- The inventory includes every direct `.java` file in `com/tvt/protocol_sdk/request`, every `map.put` in `TVTRequesterImpl_Group_sdk.java`, every `native` declaration in `TVTOpenSDK.java`, and every matching `Java_com_tvt_protocol_1sdk_TVTOpenSDK_*` dynamic export. A class may exist without a route; an export may exist without a Java declaration.
- “Input keys” lists `@SerializedName` declarations; `raw JSON/string` means the executor forwards the request body without a declared model. Symbolic annotations are shown verbatim with their Java field names. This is an input declaration inventory, not validation or a complete response schema.
- “JSON reply” means the named `*Reply` method calls `callback(getCallback(uuid), response, route)`. That invokes `TVTOpenCallback.reply(response, route)`; native response bodies remain opaque in this layer. “No matching reply method” does not prove that no native response exists elsewhere.

| Coverage measure | Count |
| --- | ---: |
| Route constants | 284 |
| Request class files | 281 |
| Request classes with `@cb4` route annotation | 278 |
| Declared `@SerializedName` input fields | 563 |
| Router registrations | 278 |
| Distinct registered paths | 277 |
| Effective registered classes after collision | 277 |
| Unregistered request classes | 3 |
| `RequestCallback` signatures / distinct names | 288 / 279 |
| Distinct callback names used by request classes | 272 |
| Native declarations | 299 |
| Distinct native names | 292 |
| Arm64 TVTOpenSDK JNI exports | 278 |
| Arm32 TVTOpenSDK JNI exports | 278 |
| Declared names with conventional export | 267 |
| Declared names without conventional export | 25 |
| Native declaration signatures without conventional export | 31 |
| Exports without Java declaration | 11 |

### Dispatch and result contract

`TVTOpenSDK.request(route, json, callback)` creates a UUID, stores the callback, resolves `/sdk` through `TVTRequesterImpl_Root_protocol_sdk` and `TVTRequesterImpl_Group_sdk`, sets itself as `RequestCallback`, then queues `BaseRequest.execute` on `TVTThreadPool` (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:2797`; `BaseRequest.java:11`; `TVTRequesterImpl_Root_protocol_sdk.java:10`). Executors deserialize with Gson or forward the raw body. The Java callback generally forwards to a native method with `mSDKHandle` and the UUID. A native `*Reply(uuid, json)` removes the callback before delivering `reply(json, route)` (`TVTOpenSDK.java:99,2797`). The callback map has no timeout or recovery path in this wrapper; missing reply paths can retain entries until explicitly cleared.

`ProtocolGsonUtils.simulateResponseMsgForSuccess/Failed` constructs `{basic:{msgcode:200/-1},message:...}` for local logout simulation (`J:com/tvt/protocol_sdk/ProtocolGsonUtils.java:61-88`; `TVTOpenSDK.java:3280-3295`). It does **not** establish that every native/cloud reply uses that exact schema. Java response models and per-route success/error semantics are not declared in this package. Synchronous JNI return values in the media/session requests are generally discarded by request executors, so the route callback contract cannot be inferred from the native return type alone.

### Other callback surfaces

- `TVTNatCallback.notify(String, byte[], int)` receives only packets accepted by `TVTOpenSDK.isPlayerCmd` through `natTransCallback`; `notifyEx(String, String)` is called by `registerResponse`. A setter exists at `TVTOpenSDK.java:3174`, but the decoded Java call sites do not establish that the app installs it (`J:com/tvt/protocol_sdk/TVTNatCallback.java:4-6`; `TVTOpenSDK.java:503-507,2699-2704`). The five NAT JNI entry points listed below are zero-return stubs in arm64.
- `TVTProtocolHttpLogCallback.log(String)` is optional and reached through `LogPrintCallback`; `AntiSecurityCallback` supplies preference encryption/decryption hooks during initialization and key-value access (`J:com/tvt/protocol_sdk/TVTProtocolHttpLogCallback.java:4`; `AntiSecurityCallback.java:4-8`; `TVTOpenSDK.java:47-53,2475-2498`). These do not return per-request results.
- `devStatusCallback` and `streamCallback` are empty Java methods (`TVTOpenSDK.java:1050,3250`), and `registerDevStatusNotify` lacks a conventional JNI export. Their declarations alone do not establish a push/status stream.

## Request and route inventory

Rows use the actual route spelling and case from `Protocol_Type.java`/the generated router. `Dispatch` is the `RequestCallback` method called by the request executor; if known, its native callee follows `→`. The `State` column reflects the static Java/JNI mapping, not runtime availability. Duplicate and aliases remain visible.

### Authentication and account (47 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/GetUserPrivateData` | `GetUserPrivateDataRequest` `:8` | none declared | `getUserPrivateData` → `getUserPrivateData` | JSON reply | routed |
| `/sdk/RegisterMobile` | `RegisterMobileRequest` `:11` | cpuCore, firmver, hwModel, mcc, memory, type, uuid, vendorId, ClientCookie.VERSION_ATTR→version | `registerMobile` → `registerMobile` | JSON reply | routed |
| `/sdk/SetUserPrivateData` | `SetUserPrivateDataRequest` `:10` | privateDataJson | `setUserPrivateData` → `setUserPrivateData` | JSON reply | routed |
| `/sdk/UnBindWx` | `userLoginedUnBindWxRequest` `:9` | none declared | `userLoginedUnBindWX` → `userLoginedUnBindWX` | JSON reply | routed |
| `/sdk/UserUploadHeadImg` | `UserUploadHeadImgRequest` `:10` | imgFilePath | `userUploadHeadImg` → `userUploadHeadImg` | JSON reply | routed |
| `/sdk/bindMailByLogined` | `BindMailByLoginedRequest` `:12` | code, mail | `bindMailByLogined` → `bindMailByLogined` | JSON reply | routed |
| `/sdk/bindPhoneByLogined` | `BindPhoneByLoginedRequest` `:12` | code, HintConstants.AUTOFILL_HINT_PHONE→phone | `bindPhoneByLogined` → `bindPhoneByLogined` | JSON reply | routed |
| `/sdk/bindWX` | `BindWxRequest` `:10` | none declared | `bindWx` → `bindWx` | JSON reply | routed |
| `/sdk/checkImgVerifyCode` | `CheckImgVerifyCodeRequest` `:9` | img | — | no matching reply method | empty executor |
| `/sdk/checkIsBindAccount` | `CheckIsBindAccountRequest` `:9` | none declared | `checkIsBindAccount` → `checkIsBindAccount` | JSON reply | routed |
| `/sdk/checkIsMobileBind` | `CheckIsMobileBindRequest` `:10` | uuid | `checkIsMobileBind` → `checkIsMobileBind` | JSON reply | routed |
| `/sdk/checkMobile1IsExist` | `CheckAccountIsRegisterRequest` `:11` | account, accountType | `checkAccountIsRegister` → `checkAccountIsRegister` | JSON reply | routed |
| `/sdk/findPasswordPasswordUpdate` | `FindPasswordPasswordWithAccountRequest` `:12` | account, dynamicCode, lang, HintConstants.AUTOFILL_HINT_NEW_PASSWORD→newPassword | `findPasswordPasswordWithAccount` → `findPasswordPasswordWithAccount` | JSON reply | routed |
| `/sdk/getDynamicCodeWithAccount` | `GetDynamicCodeWithAccountRequest` `:11` | account, accountType, businessType, imageCode, language | `getDynamicCodeWithAccount` → `getDynamicCodeWithAccount` | JSON reply | routed |
| `/sdk/getExternalAppOauth` | `GetExternalAppOauthRequest` `:8` | raw JSON/string | `getExternalAppOauth` → `getExternalAppOauth` | JSON reply | routed |
| `/sdk/getImgVerifyCode` | `GetImgVerifyCodeRequest` `:9` | none declared | `getImgVerifyCode` → `getImgVerifyCode` | JSON reply | routed |
| `/sdk/getMobileBindInfoList` | `GetMobileBindInfoListRequest` `:8` | none declared | `getMobileBindInfoList` → `getMobileBindInfoList` | JSON reply | routed |
| `/sdk/getMobileBindSwitch` | `GetMobileBindSwitchRequest` `:8` | none declared | `getMobileBindSwitch` → `getMobileBindSwitch` | JSON reply | routed |
| `/sdk/getRegisterDynamicCodeWithAccount` | `GetRegisterDynamicCodeWithAccountRequest` `:11` | accountType, imageCode, mobile | `getRegisterDynamicCodeWithAccount` → `getRegisterDynamicCodeWithAccount` | JSON reply | routed |
| `/sdk/getUserAppDataVersion` | `GetUserAppDataVersionRequest` `:8` | none declared | `getUserAppDataVersion` → `getUserAppDataVersion` | JSON reply | routed |
| `/sdk/getUserAppData` | `GetUserAppDataRequest` `:8` | none declared | `getUserAppData` → `getUserAppData` | JSON reply | routed |
| `/sdk/getUserInfo` | `GetUserInfoRequest` `:9` | none declared | `getUserInfo` → `getUserInfo` | JSON reply | routed |
| `/sdk/getUserPropertiesWithWords` | `GetUserPropertiesWithWords` `:9` | propertyNameList, propertyName, propertyValue (declared; raw body forwarded) | `getUserPropertiesWithWords` → `getUserPropertiesWithWords` | JSON reply | routed |
| `/sdk/getUserQrcodeInfo` | `GetUserQrcodeInfoRequest` `:9` | postJson (declared; raw body forwarded) | `getUserQrcodeInfo` → `getUserQrcodeInfo` | JSON reply | routed |
| `/sdk/linkExternalApp` | `LinkExternalAppInfoRequest` `:8` | raw JSON/string | `linkExternalApp` → `linkExternalApp` | JSON reply | routed |
| `/sdk/modifyEmail` | `ModifyEmailRequest` `:11` | newEmail, newVerifyCode, oldVerifyCode | `modifyEmail` → `modifyEmail` | JSON reply | routed |
| `/sdk/modifyPhone` | `ModifyPhoneRequest` `:11` | newPhone, newVerifyCode, oldVerifyCode | `modifyPhone` → `modifyPhone` | JSON reply | routed |
| `/sdk/removeMobileBindListList` | `RemoveMobileBindListListRequest` `:11` | uuidList | `removeMobileBindListList` → `removeMobileBindListList` | JSON reply | routed |
| `/sdk/sendAuthForWebLogin` | `SendAuthForWebLoginRequest` `:10` | allowed, uuid | `sendAuthorizationforWebQrcodeLogin` → `sendAuthorizationforWebQrcodeLogin` | JSON reply | routed |
| `/sdk/sendUUIDForWebLogin` | `SendUUIDForWebLoginRequest` `:10` | uuid | `sendUUIDforWebQrcodeLogin` → `sendUUIDforWebQrcodeLogin` | JSON reply | routed |
| `/sdk/setLanguage` | `SetLanguageRequest` `:10` | lang | `setLanguage` → `setLanguage` | JSON reply | routed |
| `/sdk/setMobileBindSwitch` | `SetMobileBindSwitchRequest` `:10` | isOpen | `setMobileBindSwitch` → `setMobileBindSwitch` | JSON reply | routed |
| `/sdk/setMobileIsBind` | `SetMobileIsBindRequest` `:10` | dynamicCode, uuid, verifyType | `setMobileIsBind` → `setMobileIsBind` | JSON reply | routed |
| `/sdk/setUserAppData` | `SetUserAppDataRequest` `:11` | data, ClientCookie.VERSION_ATTR→version | `setUserAppData` → `setUserAppData` | JSON reply | routed |
| `/sdk/setUserInfo` | `SetUserInfoRequest` `:11` | accoutType, address, email, mobile, name, nickName, userName | `setUserInfo` → `setUserInfo` | JSON reply | routed |
| `/sdk/thirdLogin` | `ThirdLoginRequest` `:10` | lang, redirectUri, thirdAppId, thirdCode, thirdType | `thirdLogin` → `thirdLogin` | JSON reply | routed |
| `/sdk/unLinkExternalApp` | `UnLinkExternalAppInfoRequest` `:8` | raw JSON/string | `unLinkExternalApp` → `unLinkExternalApp` | JSON reply | routed |
| `/sdk/userLogOut` | `UserLogOutRequest` `:9` | none declared | `userLogOut` → `userLogOut` | JSON reply | routed |
| `/sdk/userLogin` | `UserLoginRequest` `:11` | account, appVersion, country, doubleCheckCode, imageCode, language, loginMode, password, terminalId, uuid | `userLogin` → `userLogin` | JSON reply | routed |
| `/sdk/userLoginedBindThird` | `UserLoginBindThirdRequest` `:10` | thirdAppId, thirdCode, thirdType | `userLoginedBindThird` → `userLoginedBindThird` | JSON reply | routed |
| `/sdk/userLoginedUnBindThird` | `UserLoginUnBindThirdRequest` `:10` | thirdType | `userLoginedUnBindThird` → `userLoginedUnBindThird` | JSON reply | routed |
| `/sdk/userPasswordUpdate` | `UserPasswordUpdateRequest` `:12` | accountType, dynamicCode, HintConstants.AUTOFILL_HINT_NEW_PASSWORD→newPassword | `modifyPassword` → `modifyPassword` | JSON reply | routed |
| `/sdk/userRegisterWithAccount` | `UserRegisterWithAccountRequest` `:11` | account, country, dynamicCode, lang, loginType, password, terminalId | `userRegisterWithAccount` → `userRegisterWithAccount` | JSON reply | routed |
| `/sdk/userThirdBindAccount` | `UserThirdBindAccountRequest` `:10` | account, dynamicCode, errMsg, lang, terminalId, thirdAppId, thirdCode, thirdType | `userThirdBindAccount` → `userThirdBindAccount` | JSON reply | routed |
| `/sdk/userUnRegister` | `UserUnRegisterRequest` `:11` | accountType, dynamicCode | `userUnRegister` → `userUnRegisterNoParams` | JSON reply | routed |
| `/sdk/wxBindMobile` | `WxBindMobileRequest` `:11` | dynamicCode, language, mobile, wxCode | `wxBindMobile` → `wxBindMobile` | JSON reply | routed |
| `/sdk/wxLoginWithWxCode` | `WxLoginRequest` `:11` | language, wxCode | `wxLoginWithWxCode` → `wxLoginWithWxCode` | JSON reply | routed |

### Devices, groups and configuration (71 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/AddDeviceToFavoritesGroup` | `AddDeviceToFavoritesGroupRequest` `:11` | chlIds | `addDeviceToFavoritesGroup` → `addDeviceToFavoritesGroup` | JSON reply | routed |
| `/sdk/DeleteDeviceFromFavoritesGroup` | `DeleteDeviceFromFravoritesGroupRequest` `:11` | chlIds | `deleteDeviceFromFavoritesGroup` → `deleteDeviceFromFavoritesGroup` | JSON reply | routed |
| `/sdk/DeviceChlReName` | `DeviceChlReNameRequest` `:10` | chlId, newName | `deviceChlReName` → `deviceChlReName` | JSON reply | routed |
| `/sdk/DeviceFirmwareCheckUpdate` | `DeviceFirmwareCheckUpdateRequest` `:11` | devId | `deviceFirmwareCheckUpdate` → `deviceFirmwareCheckUpdate` | JSON reply | routed |
| `/sdk/DeviceFirmwareManualUpdate` | `DeviceFirmwareManualUpdateRequest` `:11` | devId | `deviceFirmwareManualUpdate` → `deviceFirmwareManualUpdate` | JSON reply | routed |
| `/sdk/DeviceGetRecStatus` | `DeviceGetRecStatusRequest` `:11` | chlIndexs, devId | `deviceGetRecStatus` → `deviceGetRecStatus` | JSON reply | routed |
| `/sdk/DeviceGroupSortByIds` | `DeviceGroupSortByIdsRequest` `:11` | groupIds | `deviceGroupSortByIds` → `deviceGroupSortByIds` | JSON reply | routed |
| `/sdk/DeviceReboot` | `DeviceRebootRequest` `:11` | devId | `deviceReboot` → `deviceReboot` | JSON reply | routed |
| `/sdk/GetDevAutoUpdate` | `GetDevAutoUpdateRequest` `:8` | none declared | `getDevAutoUpdate` → `getDevAutoUpdate` | JSON reply | routed |
| `/sdk/GetDeviceChlOnlineStatus` | `GetDeviceChlOnlineStatusRequest` `:10` | devId | `getDeviceChlOnlineStatus` → `getDeviceChlOnlineStatus` | JSON reply | routed |
| `/sdk/GetDeviceHealthReport` | `GetDeviceHealthReportRequest` `:10` | endTime, pageno, pagesize, startTime | `getDeviceHealthReport` → `getDeviceHealthReport` | JSON reply | routed |
| `/sdk/GetDeviceHealthSchedule` | `GetDeviceHealthScheduleRequest` `:9` | none declared | `getDeviceHealthSchedule` → `getDeviceHealthSchedule` | JSON reply | routed |
| `/sdk/GetDeviceNetQualityReport` | `GetDeviceNetQualityReportRequest` `:10` | devId, endTime, pageno, pagesize, startTime | `getDeviceNetQualityReport` → `getDeviceNetQualityReport` | JSON reply | routed |
| `/sdk/GetGroupListToMe` | `GetGroupListToMeRequest` `:8` | none declared | `getGroupListToMe` → `getGroupListToMe` | JSON reply | routed |
| `/sdk/GetLastedDeviceHealthReport` | `GetLastedDeviceHealthReportRequest` `:9` | none declared | `getLastedDeviceHealthReport` → `getLastedDeviceHealthReport` | JSON reply | routed |
| `/sdk/SendHealthCheckCmdToDev` | `SendHealthCheckCmdToDevRequest` `:10` | devId, time | `sendHealthCheckCmdToDev` → `sendHealthCheckCmdToDev` | JSON reply | routed |
| `/sdk/SendNetQualityCheckCmdToDev` | `SendNetQualityCheckCmdToDevRequest` `:9` | raw JSON/string | `sendNetQualityCheckCmdToDev` → `sendNetQualityCheckCmdToDev` | JSON reply | routed |
| `/sdk/SetDevAutoUpdate` | `SetDevAutoUpdateRequest` `:10` | isOpen, schedule | `setDevAutoUpdate` → `setDevAutoUpdate` | JSON reply | routed |
| `/sdk/SetDeviceHealthSchedule` | `SetDeviceHealthScheduleRequest` `:11` | isSwitch, schedules | `setDeviceHealthSchedule` → `setDeviceHealthSchedule` | JSON reply | routed |
| `/sdk/UpdateDeviceCode` | `DeviceUpdateCodeRequest` `:11` | code, devId | `deviceUpdateDeviceCode` → `deviceUpdateDeviceCode` | JSON reply | routed |
| `/sdk/addDeviceGroup` | `AddDeviceGroupRequest` `:10` | groupName | `addDeviceGroup` → `addDeviceGroup` | JSON reply | routed |
| `/sdk/addDeviceToGroup` | `AddDeviceToGroupRequest` `:11` | chlIDs, groupID | `addDeviceToGroup` → `addDeviceToGroup` | JSON reply | routed |
| `/sdk/addUserUnbindDevice` | `AddUserUnbindDeviceRequest` `:9` | raw JSON/string | `addUserUnbindDevice` → `addUserUnbindDevice` | JSON reply | routed |
| `/sdk/deleteUserUnbindDevice` | `DeleteUserUnbindDeviceRequest` `:9` | raw JSON/string | `deleteUserUnbindDevice` → `deleteUserUnbindDevice` | JSON reply | routed |
| `/sdk/deviceBind` | `DeviceBindRequest` `:12` | code, devName, FileSyncConstants.ADD_METHOD_SN→sn | `deviceBind` → `deviceBind` | JSON reply | routed |
| `/sdk/deviceGetInfo` | `DeviceGetInfoRequest` `:10` | devID | `deviceGetInfo` → `deviceGetInfo` | JSON reply | routed |
| `/sdk/deviceGroupSetHomeType` | `DeviceGroupSetHomeTypeRequest` `:10` | groupID, isHome | `deviceGroupSetHomeType` → `deviceGroupSetHomeType` | JSON reply | routed |
| `/sdk/deviceGroupSetTop` | `DeviceGroupSetTopRequest` `:10` | groupID, isTop | `deviceGroupSetTop` → `deviceGroupSetTop` | JSON reply | routed |
| `/sdk/deviceReName` | `DeviceReNameRequest` `:10` | devID, devName | `deviceReName` → `deviceReName` | JSON reply | routed |
| `/sdk/deviceRegister` | `DeviceRegisterRequest` `:13` | devType, model, FileSyncConstants.ADD_METHOD_SN→sn, ClientCookie.VERSION_ATTR→version | `deviceRegister` → `deviceRegister` | JSON reply | routed |
| `/sdk/deviceSetMotionSwitch` | `DeviceSetMotionSwitchRequest` `:10` | bOpen, devID | `deviceSetMotionSwitch` → `deviceSetMotionSwitch` | JSON reply | routed |
| `/sdk/deviceSetOfflineSwitch` | `DeviceSetOfflineSwitchRequest` `:10` | bOpen, devID | `deviceSetOfflineSwitch` → `deviceSetOfflineSwitch` | JSON reply | routed |
| `/sdk/deviceTransfer` | `DeviceTransferRequest` `:10` | code, devID, type, userName | `deviceTransfer` → `deviceTransfer` | JSON reply | routed |
| `/sdk/deviceUnBind` | `DeviceUnBindRequest` `:10` | devID | `deviceUnBind` → `deviceUnBind` | JSON reply | routed |
| `/sdk/endLiveVideoDataWithDeviceId` | `EndLiveVideoDataWithDeviceIdRequest` `:11` | chlId, deviveSN | `natCloseLiveVideo` → `natCloseLiveVideo` | no matching reply method | native zero-return stub |
| `/sdk/getAccountChannelList` | `GetAccountChannelListRequest` `:12` | snList | `getAccountChannelList` → `getAccountChannelList` | JSON reply | routed |
| `/sdk/getAccountDeviceList` | `GetAccountDeviceListRequest` `:10` | pageno, pagesize | `getAccountDeviceList` → `getAccountDeviceList` | JSON reply | routed |
| `/sdk/getAllDeviceCapability` | `GetAllDeviceAbilityRequest` `:8` | none declared | `getAllDeviceCapability` → `getAllDeviceCapability` | JSON reply | routed |
| `/sdk/getChannelDetailInfo` | `GetChannelDetailInfoRequest` `:11` | chlIndex, FileSyncConstants.ADD_METHOD_SN→sn | `getChannelDetailInfo` → `getChannelDetailInfo` | JSON reply | routed |
| `/sdk/getDeviceAbilityList` | `GetDeviceAbilityListRequest` `:10` | devID | `getDeviceAbilityList` → `getDeviceAbilityList` | JSON reply | routed |
| `/sdk/getDeviceAccessToken` | `GetDeviceAccessTokenRequest` `:10` | devId | `getDeviceAccessToken` → `getDeviceAccessToken` | JSON reply | routed |
| `/sdk/getDeviceBindStatus` | `getDeviceBindStatusRequest` `:8` | raw JSON/string | `getDeviceBindStatus` → `getDeviceBindStatus` | JSON reply | routed |
| `/sdk/getDeviceDcInfo` | `GetDeviceDcInfoRequest` `:11` | FileSyncConstants.ADD_METHOD_SN→sn | `getDeviceDcInfo` → `getDeviceDcInfo` | JSON reply | routed |
| `/sdk/getDeviceDetailInfo` | `GetDeviceDetailInfoRequest` `:11` | isReturnChl, FileSyncConstants.ADD_METHOD_SN→sn | `getDeviceDetailInfo` → `getDeviceDetailInfo` | JSON reply | routed |
| `/sdk/getDeviceGroupList` | `GetDeviceGroupListRequest` `:8` | none declared | `getDeviceGroupList` → `getDeviceGroupList` | JSON reply | routed |
| `/sdk/getDeviceListFromGroup` | `GetDeviceListFromGroupRequest` `:10` | groupID, pageNo, pagesize | `getDeviceListFromGroup` → `getDeviceListFromGroup` | JSON reply | routed |
| `/sdk/getDeviceListToOurGroup` | `GetDeviceListToOurGroupRequest` `:10` | pageNo, pagesize | `getDeviceListToOurGroup` → `getDeviceListToOurGroup` | JSON reply | routed |
| `/sdk/getDeviceList` | `GetDeviceListRequest` `:10` | pageNo, pageSize | `getDeviceList` → `getDeviceList` | JSON reply | routed |
| `/sdk/getDeviceNetSafeReport` | `getDeviceNetSafeReportRequest` `:10` | devId, endTime, pageNo, pageSize, startTime | `getDeviceNetSafeReport` → `getDeviceNetSafeReport` | JSON reply | routed |
| `/sdk/getDeviceNetSafeSwitch` | `getDeviceNetSafeSwitchRequest` `:10` | devId | `getDeviceNetSafeSwitch` → `getDeviceNetSafeSwitch` | JSON reply | routed |
| `/sdk/getDeviceSleepStatus` | `GetDeviceSleepStatusRequest` `:10` | md5SN | `getDeviceSleepStatus` → `getDeviceSleepStatus` | JSON reply | routed |
| `/sdk/getDeviceTragetValueSetCredential` | `GetDevicePwdSetCredentialRequest` `:10` | devId, targetValue, userPwd | `getDeviceTragetValueSetCredential` → `getDeviceTragetValueSetCredential` | JSON reply | routed |
| `/sdk/getOnOffDeviceConfig` | `OnOffDeviceConfigRequest` `:11` | chlModelNameArray, devModelNameArray, devSN | `getOnOffDeviceConfig` → `getOnOffDeviceConfig` | JSON reply | routed |
| `/sdk/getResidentDeviceList` | `GetResidentDeviceListRequest` `:10` | pageno, pagesize | `getResidentDeviceList` → `getResidentDeviceList` | JSON reply | routed |
| `/sdk/getTransferDeviceList` | `GetTransferDeviceListRequest` `:8` | raw JSON/string | `getTransferDeviceList` → `getTransferDeviceList` | JSON reply | routed |
| `/sdk/getUserDeviceList` | `GetUserDeviceListRequest` `:9` | raw JSON/string | `getUserDeviceList` → `getUserDeviceList` | JSON reply | routed |
| `/sdk/getUserUnbindDeviceList` | `GetUserUnbindDeviceRequest` `:9` | raw JSON/string | `getUserUnbindDeviceList` → `getUserUnbindDeviceList` | JSON reply | routed |
| `/sdk/modifyChannelRemark` | `ModifyChannelRemarkRequest` `:11` | chlIndex, remark, FileSyncConstants.ADD_METHOD_SN→sn | `modifyChannelRemark` → `modifyChannelRemark` | JSON reply | routed |
| `/sdk/modifyDeviceGroupName` | `ModifyDeviceGroupNameRequest` `:10` | groupID, name | `modifyDeviceGroupName` → `modifyDeviceGroupName` | JSON reply | routed |
| `/sdk/modifyDeviceRemark` | `ModifyDeviceRemarkRequest` `:11` | remark, FileSyncConstants.ADD_METHOD_SN→sn | `modifyDeviceRemark` → `modifyDeviceRemark` | JSON reply | routed |
| `/sdk/removeDeviceFromGroup` | `RemoveDeviceFromGroupRequest` `:11` | chlIDs, groupID | `removeDeviceFromGroup` → `removeDeviceFromGroup` | JSON reply | routed |
| `/sdk/removeDeviceGroup` | `RemoveDeviceGroupRequest` `:10` | groupID | `removeDeviceGroup` → `removeDeviceGroup` | JSON reply | routed |
| `/sdk/requestGetDeviceArm` | `RequestGetDeviceArmRequest` `:10` | md5SN | `requestGetDeviceArm` → `requestGetDeviceArm` | JSON reply | routed |
| `/sdk/requestSetDeviceArm` | `RequestSetDeviceArmRequest` `:10` | armStatus, md5SN | `requestSetDeviceArm` → `requestSetDeviceArm` | JSON reply | routed |
| `/sdk/requestWakeupDevice` | `RequestWakeupDeviceRequest` `:10` | md5SN | `requestWakeupDevice` → `requestWakeupDevice` | JSON reply | routed |
| `/sdk/sendNetSafeCheckCmdToDev` | `sendNetSafeCheckCmdToDevRequest` `:10` | devId | `sendNetSafeCheckCmdToDev` → `sendNetSafeCheckCmdToDev` | JSON reply | routed |
| `/sdk/sendNetSafeRepairCmdToDev` | `sendNetSafeRepairCmdToDevRequest` `:10` | devId | `sendNetSafeRepairCmdToDev` → `sendNetSafeRepairCmdToDev` | JSON reply | routed |
| `/sdk/setDeviceNetSafeSwitch` | `setDeviceNetSafeSwitchRequest` `:10` | devId, isOpen | `setDeviceNetSafeSwitch` → `setDeviceNetSafeSwitch` | JSON reply | routed |
| `/sdk/setOnOffDeviceConfig` | `SetOnOffDeviceConfigRequest` `:8` | raw JSON/string | `setOnOffDeviceConfig` → `setOnOffDeviceConfig` | JSON reply | routed |
| `/sdk/startLiveVideoDataWithDeviceId` | `StartLiveVideoDataWithDeviceIdRequest` `:10` | chlId, deviveSN, quality, resolution | `natOpenLiveVideo` → `natOpenLiveVideo` | no matching reply method | native zero-return stub |
| `/sdk/updateUserUnbindDevice` | `UpdateUserUnbindDeviceRequest` `:9` | raw JSON/string | `updateUserUnbindDevice` → `updateUserUnbindDevice` | JSON reply | routed |

### Sharing and friends (51 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/GetShareGroupChannelListToMeWithGroupIds` | `GetShareGroupChannelListToMeWithGroupIdsRequest` `:11` | groupIds | `getShareGroupChannelListToMeWithGroupIds` → `getShareGroupChannelListToMeWithGroupIds` | JSON reply | routed |
| `/sdk/GetSharedChlListByMy` | `GetSharedChlListByMyRequest` `:10` | pageNo→pageNO, pageSize | `getSharedChlListByMy` → `getSharedChlListByMy` | JSON reply | routed |
| `/sdk/GetSharedChlListToMe` | `GetSharedChlListToMeRequest` `:10` | pageNO, pageSize | `getSharedChlListToMe` → `getSharedChlListToMe` | JSON reply | routed |
| `/sdk/GetUserCountSharedChlList` | `GetUserCountSharedChlListRequest` `:11` | userIds | `getUserCountSharedChlList` → `getUserCountSharedChlList` | JSON reply | routed |
| `/sdk/SharedCameraChlsToFriend` | `SharedCameraChlsToFriendRequest` `:12` | cameraShareInfoList | `sharedCameraChlsToFriend` → `sharedCameraChlsToFriend` | JSON reply | routed |
| `/sdk/acceptShared` | `AcceptSharedRequest` `:10` | sharedId | `acceptShared` → `acceptShared` | JSON reply | routed |
| `/sdk/addFriendGroupWithGroupName` | `AddFriendGroupWithGroupNameRequest` `:11` | groupName | `addFriendGroupWithGroupName` → `addFriendGroupWithGroupName` | JSON reply | routed |
| `/sdk/addFriendToGroupWithGroupId` | `AddFriendToGroupWithGroupIdRequest` `:11` | friendIds, gid, isInvolveShare | `addFriendToGroupWithGroupId` → `addFriendToGroupWithGroupId` | JSON reply | routed |
| `/sdk/agreeApplyToNewFriendWithApplyId` | `AgreeApplyToNewFriendWithApplyIdRequest` `:11` | applyId | `agreeApplyToNewFriendWithApplyId` → `agreeApplyToNewFriendWithApplyId` | JSON reply | routed |
| `/sdk/batcjAcceptDeviceShared` | `BatchAcceptDeviceSharedRequest` `:12` | snList | `batchAcceptDeviceShared` → `batchAcceptDeviceShared` | JSON reply | routed |
| `/sdk/batcjAcceptShared` | `BatchAcceptSharedRequest` `:12` | sharedIds | `batchAcceptShared` → `batchAcceptShared` | JSON reply | routed |
| `/sdk/deleteFriendGroupWithGroupId` | `DeleteFriendGroupWithGroupIdRequest` `:10` | none declared | `deleteFriendGroupWithGroupId` → `deleteFriendGroupWithGroupId` | JSON reply | routed |
| `/sdk/deleteFriendsFromGroupWithGroupId` | `DeleteFriendsFromGroupWithGroupIdRequest` `:11` | friendIds, gid | `deleteFriendsFromGroupWithGroupId` → `deleteFriendsFromGroupWithGroupId` | JSON reply | routed |
| `/sdk/deleteShared` | `DeleteSharedRequest` `:12` | sharedIds | `deleteShared` → `deleteShared` | JSON reply | routed |
| `/sdk/getCanShareChlListWithFriendId` | `GetCanShareChlListWithFriendIdRequest` `:10` | none declared | `getCanShareChlListWithFriendId` → `getCanShareChlListWithGroupId` | JSON reply | routed |
| `/sdk/getCanShareChlListWithGroupId` | `GetCanShareChlListWithGroupIdRequest` `:10` | none declared | `getCanShareChlListWithGroupId` → `getCanShareChlListWithGroupId` | JSON reply | routed |
| `/sdk/getCanShareDeviceWithFriendId` | `GetCanShareDeviceWithFriendIdRequest` `:10` | friendId | `getCanShareDeviceWithFriendId` → `getCanShareDeviceWithFriendId` | JSON reply | routed |
| `/sdk/getCanShareFriendWithChannelId` | `GetCanShareFriendWithChannelIdRequest` `:10` | channelId | `getCanShareFriendWithChannelId` → `getCanShareFriendWithChannelId` | JSON reply | routed |
| `/sdk/getCanSharedFriendListByChlId` | `GetCanSharedFriendListByChlIdRequest` `:10` | none declared | `getCanSharedFriendListByChlId` → `getCanSharedFriendListByChlId` | JSON reply | routed |
| `/sdk/getCanSharedGroupListByChlId` | `GetCanSharedGroupListByChlIdRequest` `:10` | none declared | `getCanSharedGroupListByChlId` → `getCanSharedGroupListByChlId` | JSON reply | routed |
| `/sdk/getFriendGroupUserListWithGroupId` | `GetFriendGroupUserListWithGroupIdRequest` `:10` | none declared | `getFriendGroupUserListWithGroupId` → `getFriendGroupUserListWithGroupId` | JSON reply | routed |
| `/sdk/getMyFriendList` | `GetMyFriendListRequest` `:9` | none declared | `getMyFriendList` → `getMyFriendList` | JSON reply | routed |
| `/sdk/getMyGroupList` | `GetFriendGroupListRequest` `:9` | none declared | `getMyGroupList` → `getFriendGroupList` | JSON reply | routed |
| `/sdk/getReceiveApplyListForNewFriend` | `GetReceiveApplyListForNewFriendRequest` `:9` | none declared | `getReceiveApplyListForNewFriend` → `getReceiveApplyListForNewFriend` | JSON reply | routed |
| `/sdk/getReceiveApplyNumForNewFriend` | `GetReceiveApplyNumForNewFriendRequest` `:9` | none declared | `getReceiveApplyNumForNewFriend` → `getReceiveApplyNumForNewFriend` | JSON reply | routed |
| `/sdk/getSendApplyListForNewFriend` | `GetSendApplyListForNewFriendRequest` `:9` | none declared | `getSendApplyListForNewFriend` → `getSendApplyListForNewFriend` | JSON reply | routed |
| `/sdk/getShareAuthByChlId` | `GetShareAuthByChlIdRequest` `:10` | chlId | `getShareAuthByChlId` → `getShareAuthByChlId` | JSON reply | routed |
| `/sdk/getSharedChlInfoByChlID` | `GetSharedChlInfoByChlIDRequest` `:9` | raw JSON/string | `getSharedChlInfoByChlID` → `getSharedChlInfoByChlID` | JSON reply | routed |
| `/sdk/getSharedChlListByFriendID` | `GetSharedChlListByFriendIDRequest` `:10` | friendID | `getSharedChlListByFriendID` → `getSharedChlListByFriendID` | JSON reply | routed |
| `/sdk/getSharedChlListByGroupId` | `GetSharedChlListByGroupIdRequest` `:10` | none declared | `getSharedChlListByGroupId` → `getSharedChlListByGroupId` | JSON reply | routed |
| `/sdk/getSharedChlListByMyPage` | `GetSharedChlListByMyPageRequest` `:10` | pageNum, pageSize | `getSharedChlListByMyPage` → `getSharedChlListByMyPage` | JSON reply | routed |
| `/sdk/getSharedChlListToMePage` | `GetSharedChlListToMePageRequest` `:10` | pageNum, pageSize | `getSharedChlListToMePage` → `getSharedChlListToMePage` | JSON reply | routed |
| `/sdk/getSharedInfoByShareId` | `GetSharedInfoByShareIdRequest` `:10` | shareID | `getSharedInfoByShareId` → `getSharedInfoByShareId` | JSON reply | routed |
| `/sdk/getSharedListByTargetUser` | `GetSharedListByTargetUserRequest` `:12` | loginName, snList | `getSharedListByTargetUser` → `getSharedListByTargetUser` | JSON reply | routed |
| `/sdk/getSharedListFromOther` | `GetSharedListFromOtherRequest` `:11` | pageno, pagesize, resourceTypes | `getSharedListFromOther` → `getSharedListFromOther` | JSON reply | routed |
| `/sdk/getSharedListToAccount` | `GetSharedListToAccountRequest` `:10` | accountType, loginName | `getSharedListToAccount` → `getSharedListToAccount` | reply as /sdk/deleteShared | routed |
| `/sdk/getSharedListToOther` | `GetSharedListToOtherRequest` `:11` | pageno, pagesize, resourceTypes | `getSharedListToOther` → `getSharedListToOther` | JSON reply | routed |
| `/sdk/modifyFriendGroupWithGroupId` | `ModifyFriendGroupWithGroupIdRequest` `:11` | gid, groupName | `modifyFriendGroupWithGroupId` → `modifyFriendGroupWithGroupId` | JSON reply | routed |
| `/sdk/remarkMyFriendInfo` | `RemarkMyFriendInfoRequest` `:11` | friendID, remark | `remarkMyFriendInfo` → `remarkMyFriendInfo` | JSON reply | routed |
| `/sdk/removeMyFriend` | `RemoveMyFriendRequest` `:11` | friendID | `removeMyFriend` → `removeMyFriend` | JSON reply | routed |
| `/sdk/removeShareChlByChlID` | `RemoveShareChlByChlIDRequest` `:10` | chlID | `removeShareChlByChlID` → `removeShareChlByChlID` | JSON reply | routed |
| `/sdk/removeShareChlByFriendID` | `RemoveShareChlByFriendIDRequest` `:10` | friendID | `removeShareChlByFriendID` → `removeShareChlByFriendID` | JSON reply | routed |
| `/sdk/removeShareChlByShareID` | `RemoveShareChlByShareIDRequest` `:10` | shareID | `removeShareChlByShareID` → `removeShareChlByShareID` | JSON reply | routed |
| `/sdk/searchMyFriendByLoginName` | `SearchMyFriendByLoginNameRequest` `:10` | loginName | `searchMyFriendByLoginName` → `searchMyFriendByLoginName` | JSON reply | routed |
| `/sdk/searchMyFriendByRemark` | `SearchMyFriendByRemarkRequest` `:11` | remark | `searchMyFriendByRemark` → `searchMyFriendByRemark` | no matching reply method | routed |
| `/sdk/sendApplyForAddFriends` | `SendApplyForAddFriendsRequest` `:11` | friendId, message, mobile, remark | `sendApplyForAddFriends` → `sendApplyForAddFriends` | JSON reply | routed |
| `/sdk/setSharedChlPermission` | `SetSharedChlPermissionRequest` `:11` | infoDic, shareID | `setSharedChlPermission` → `setSharedChlPermission` | JSON reply | routed |
| `/sdk/shareChlToMyGroup` | `ShareDeviceToMyGroupRequest` `:13` | gid, settedDevcieMap | `shareChlToMyGroup` → `shareChlToMyGroup` | JSON reply | routed |
| `/sdk/shareChl` | `ShareChlRequest` `:13` | account, accountType, deviceShareInfoList, shareInfoList | `shareChl` → `shareChl` | JSON reply | routed |
| `/sdk/sharedChlToGroupsOrFriends` | `SharChlToGroupsOrFriendsRequest` `:13` | chlId, friends, groups | `sharedChlToGroupsOrFriends` → `sharedChlToGroupsOrFriends` | JSON reply | routed |
| `/sdk/sharedChlsToFriend` | `SharedChlsToFriendRequest` `:12` | chlsArray, friendID | `sharedChlsToFriend` → `sharedChlsToFriend` | JSON reply | routed |

### Alarm, events and push (32 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/DeviceGetAlarmSwitch` | `DeviceGetAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | JSON reply | routed |
| `/sdk/DeviceGetChlOfflineAlarmSwitch` | `DeviceGetChlOfflineAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/DeviceGetDetectAlarmSwitch` | `DeviceGetDetectAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/DeviceGetOfflineAlarmSwitch` | `DeviceGetOfflineAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/DeviceGetOtherAlarmSwitch` | `DeviceGetOtherAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/DeviceGetRecModeAlarmSwitch` | `DeviceGetRecModeAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/DeviceGetSensorAlarmSwitch` | `DeviceGetSensorAlarmSwitchRequest` `:11` | alarmType, TtmlNode.ATTR_ID→id | `deviceGetAlarmSwitch` → `deviceGetAlarmSwitch` | reply as /sdk/DeviceGetAlarmSwitch | routed |
| `/sdk/GetMsgPushSwitch` | `GetMsgPushSwitchRequest` `:8` | none declared | `getMsgPushSwitch` → `getMsgPushSwitch` | JSON reply | routed |
| `/sdk/GetServiceMsgList` | `GetServiceMsgListRequest` `:10` | endTime, msgType, pageNum, pageSize, startTime | `getServiceMsgList` → `getServiceMsgList` | JSON reply | routed |
| `/sdk/GetServiceMsgType` | `GetServiceMsgTypeRequest` `:8` | none declared | `getServiceMsgType` → `getServiceMsgType` | JSON reply | routed |
| `/sdk/GetUnReadServiceMsgNum` | `GetUnReadServiceMsgNumRequest` `:8` | none declared | `getUnReadServiceMsgNum` → `getUnReadServiceMsgNum` | JSON reply | routed |
| `/sdk/SetMsgPushSwitch` | `SetMsgPushSwitchRequest` `:10` | isOpen, schedule | `setMsgPushSwitch` → `setMsgPushSwitch` | JSON reply | routed |
| `/sdk/SetServiceMsgListStatus` | `SetServiceMsgStatusRequest` `:12` | msgIdList, NotificationCompat.CATEGORY_STATUS→status | `setServiceMsgListStatus` → `setServiceMsgListStatus` | JSON reply | routed |
| `/sdk/addUserDevicePushList` | `AddUserDevicePushListRequest` `:10` | assType, devUserName, deviceId, deviceName, mainSwitch, md5SN, password | `addUserDevicePushList` → `addUserDevicePushList` | JSON reply | routed |
| `/sdk/deleteDevicePush2Message` | `DeleteDevicePush2MessageRequest` `:10` | postJson | `deleteDevicePush2Message` → `deleteDevicePush2Message` | JSON reply | routed |
| `/sdk/deleteUserDevicePushConfig` | `DeleteUserDevicePushConfigRequest` `:10` | deviceId, md5SN | `deleteUserDevicePushConfig` → `deleteUserDevicePushConfig` | JSON reply | routed |
| `/sdk/deviceSetAlarmSwitch` | `DeviceSetAlarmSwitchRequest` `:12` | alarmType, TtmlNode.ATTR_ID→id, para | `deviceSetAlarmSwitch` → `deviceSetAlarmSwitch` | JSON reply | routed |
| `/sdk/editDevicePush2Config` | `EditDevicePush2ConfigRequest` `:10` | postJson | `editDevicePush2Config` → `editDevicePush2Config` | JSON reply | routed |
| `/sdk/editUserDevicePushConfig` | `EditUserDevicePushConfigRequest` `:10` | postJson | `editUserDevicePushConfig` → `editUserDevicePushConfig` | JSON reply | routed |
| `/sdk/getDeviceAlarmCountInTime` | `GetDeviceAlarmCountInTimeRequest` `:11` | chlIdList, devIdList, endTime, getAllByDevIds, startTime | `getDeviceAlarmCountInTime` → `getDeviceAlarmCountInTime` | JSON reply | routed |
| `/sdk/getDeviceAlarmLatestInfo` | `GetDeviceAlarmLatestInfoRequest` `:11` | chlIdList, count, getAllByDevIds | `getDeviceAlarmLatestInfo` → `getDeviceAlarmLatestInfo` | JSON reply | routed |
| `/sdk/getDeviceAlarmListPage` | `GetDeviceAlarmListPageRequest` `:11` | alarmTypeList, chlIdList, devIdList, endTime, getAllByDevIds, pageNum, pageSize, startTime | `getDeviceAlarmListPage` → `getDeviceAlarmListPage` | JSON reply | routed |
| `/sdk/getDeviceAlarmType` | `GetDeviceAlarmTypeRequest` `:8` | none declared | `getDeviceAlarmTypeCallBack` → `getDeviceAlarmTypeCallBack` | JSON reply | routed |
| `/sdk/getDeviceAlarmUnreadCounts` | `GetDeviceAlarmUnreadCountsRequest` `:11` | chlIdList, devIdList, getAllByDevIds | `getDeviceAlarmUnreadCounts` → `getDeviceAlarmUnreadCounts` | JSON reply | routed |
| `/sdk/getDeviceLocalStorageStatus` | `GetDeviceHDDAlarmListRequest` `:9` | devId, pageNo, pageSize | `getDeviceHDDAlarmList` → `getDeviceHDDAlarmList` | JSON reply | routed |
| `/sdk/getDevicePush2Config` | `GetDevicePush2ConfigRequest` `:10` | md5SN | `getDevicePush2Config` → `getDevicePush2Config` | JSON reply | routed |
| `/sdk/getDevicePush2DetailMessage` | `GetDevicePush2DetailMessageRequest` `:8` | raw JSON/string | `getDevicePush2DetailMessage` → `getDevicePush2DetailMessage` | JSON reply | routed |
| `/sdk/getUserDeviceEventMessageList` | `GetUserDeviceEventMessageListRequest` `:10` | lastId, lastTime, md5SN, pageSize | `getUserDeviceEventMessageList` → `getUserDeviceEventMessageList` | JSON reply | routed |
| `/sdk/getUserDevicePushConfig` | `GetUserDevicePushConfigRequest` `:10` | md5SN | `getUserDevicePushConfig` → `getUserDevicePushConfig` | JSON reply | routed |
| `/sdk/modifyPushDeviceName` | `ModifyPushDeviceNameRequest` `:10` | deviceId, md5SN, newName | `modifyPushDeviceName` → `modifyPushDeviceName` | JSON reply | routed |
| `/sdk/sendNotificationToken` | `SendNotificationTokenRequest` `:11` | appID, dataMessageTypes, pushType, tokenID | `sendNotificationToken` → `sendNotificationToken` | JSON reply | routed |
| `/sdk/setDeviceAlarmStatus` | `SetDeviceAlarmStatusRequest` `:12` | msgIdList, readAll, NotificationCompat.CATEGORY_STATUS→status | `setDeviceAlarmStatus` → `setDeviceAlarmStatus` | JSON reply | routed |

### Cloud, storage and records (39 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/AddDownloadAlarmVideoTask` | `AddDownloadAlarmVideoTaskRequest` `:10` | bucketName, objectName, storageUrl | `addDownloadAlarmVideoTask` → `addDownloadAlarmVideoTask` | JSON reply | routed |
| `/sdk/AddDownloadChlCoverImgTask` | `AddDownloadChlCoverImgTaskRequest` `:10` | bucketName, objectName, storageUrl | `addDownloadChlCoverImgTask` → `addDownloadChlCoverImgTask` | JSON reply | routed |
| `/sdk/AddDownloadFileTask` | `AddDownloadFileRequest` `:10` | accessKeyId, localPath, objectName, secretAccessKey, securityToken | `addDownloadFileTask` → `addDownloadFileTask` | JSON reply | routed |
| `/sdk/AddDownloadPTZPresetImgTask` | `AddDownloadPTZPresetImgTaskRequest` `:10` | bucketName, chlId, objectName, storageUrl | `addDownloadPTZPresetImgTask` → `addDownloadPTZPresetImgTask` | JSON reply | routed |
| `/sdk/AddDownloadRecordTask` | `AddDownloadRecordTaskRequest` `:10` | bucketName, localPath, objectName, storageUrl | `addDownloadRecordTask` → `addDownloadRecordTask` | JSON reply | routed |
| `/sdk/AddUploadChlCoverImgTask` | `AddUploadChlCoverImgTaskRequest` `:10` | bucketName, objectName, storageUrl | `addUploadChlCoverImgTask` → `addUploadChlCoverImgTask` | JSON reply | routed |
| `/sdk/AddUploadFileTask` | `AddUploadFileRequest` `:10` | uploadFile | `addUploadFileTask` → `addUploadFileTask` | JSON reply | routed |
| `/sdk/ChlGetCloudStorageInfo` | `ChlGetCloudStorageInfoRequest` `:10` | chlId | `chlGetCloudStorageInfo` → `chlGetCloudStorageInfo` | JSON reply | routed |
| `/sdk/DeviceFormatLocalStorage` | `DeviceFormatLocalStorageRequest` `:11` | devId, FirebaseAnalytics.Param.INDEX→index | `deviceFormatLocalStorage` → `deviceFormatLocalStorage` | JSON reply | routed |
| `/sdk/DeviceGetLocalStorageStatus` | `DeviceGetLocalStorageStatusRequest` `:10` | devId | `deviceGetLocalStorageStatus` → `deviceGetLocalStorageStatus` | JSON reply | routed |
| `/sdk/GetCloudRecordDate` | `GetCloudRecordDateRequest` `:11` | FileSyncConstants.ADD_METHOD_SN→sn, chlIndex, startTime, endTime | `getCloudRecordDate` → `getCloudRecordDate` | JSON reply | routed |
| `/sdk/GetCloudRecordList` | `GetCloudRecordListRequest` `:11` | taskId, FileSyncConstants.ADD_METHOD_SN→sn, chlIndex, alarmType, startTime, endTime, lastId, pagesize | `getCloudRecordList` → `getCloudRecordList` | JSON reply | routed |
| `/sdk/GetCloudRecordState` | `GetCloudRecordStateRequest` `:10` | chlId | `getCloudRecordState` → `getCloudRecordState` | JSON reply | routed |
| `/sdk/GetCloudVideoList` | `GetCloudVideoListRequest` `:11` | dcUrl, FileSyncConstants.ADD_METHOD_SN→sn, chlIndex, startTime, endTime, lastId, pagesize | `getCloudVideoList` → `getCloudVideoList` | no matching reply method | routed |
| `/sdk/RemoveCloudRecord` | `RemoveCloudRecordRequest` `:11` | dcs, recordIds | `removeCloudRecord` → `removeCloudRecord` | JSON reply | routed |
| `/sdk/SetCloudRecordSwitch` | `SetCloudRecordSwitchRequest` `:10` | chlId, isOpen | `setCloudRecordSwitch` → `setCloudRecordSwitch` | JSON reply | routed |
| `/sdk/applyVASService` | `VASApplyServiceRequest` `:11` | chlIndex, FileSyncConstants.ADD_METHOD_SN→sn, devId, goodsId, applicationId | `applyVASService` → `applyVASService` | JSON reply | routed |
| `/sdk/deviceCloudStorageIsValid` | `DeviceCloudStorageIsValidRequest` `:8` | raw JSON/string | `deviceCloudStorageIsValid` | JSON reply | empty SDK callback |
| `/sdk/getAccountChlVASStatus` | `VASAccountChlStatusRequest` `:11` | devId, vasId | `getAccountChlVASStatus` → `getAccountChlVASStatus` | JSON reply | routed |
| `/sdk/getCloudListFromGroup` | `GetCloudListFromGroupRequest` `:10` | groupID, pageNo, pagesize | `getCloudListFromGroup` → `getCloudListFromGroup` | JSON reply | routed |
| `/sdk/getCloudStorageDownloadToken` | `GetCloudDownloadTokenRequest` `:10` | devSN, resourceType, storageType, bucketName | `getCloudStorageDownloadToken` → `getCloudStorageDownloadToken` | JSON reply | routed |
| `/sdk/getDeviceCapability` | `VASGetDeviceCapabilityRequest` `:10` | devId | `getDeviceCapability` → `getDeviceCapability` | JSON reply | routed |
| `/sdk/getDeviceLocalStorageStatus` | `GetDeviceLocalStorageStatusRequest` `:9` | devId | `getDeviceLocalStorageStatus` → `getDeviceLocalStorageStatus` | JSON reply | overwritten route |
| `/sdk/getPlaybackRecordChl` | `GetPlaybackRecordChlRequest` `:10` | endTime, loginId, recordType, startTime | `getPlaybackRecordChl` → `getPlaybackRecordChl` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/getPlaybackRecordDate` | `GetPlaybackRecordDateRequest` `:11` | chlIds, loginId, recordType, timeZone | `getPlaybackRecordDate` → `getPlaybackRecordDate` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/getPlaybackRecordLog` | `GetPlaybackRecordLogRequest` `:10` | chlId, endTime, loginId, recordType, startTime, timeZone | `getPlaybackRecordLog` → `getPlaybackRecordLog` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/getVASApplyRecordList` | `VASGetApplyRecordListRequest` `:10` | applicationId, beginTime, chlIndex, endTime, pageNum, pageSize, vasApplyId→orderId, devId | `getVASApplyRecordList` → `getVASApplyRecordList` | JSON reply | routed |
| `/sdk/getVASCloudStoreGoodList` | `VASCloudStoreGoodListRequest` `:10` | devId, payType, vasId | `getVASCloudStoreGoodList` → `getVASCloudStoreGoodList` | JSON reply | routed |
| `/sdk/getVASGoodsList` | `VASGetServiceApplyListRequest` `:10` | applicationId, deviceId, payType, chlIndex, filter | `getVASGoodsList` → `getVASGoodList` | no matching reply method | routed |
| `/sdk/getVASServerInfo` | `VASGoodsInfoRequest` `:10` | devId, vasId | `getVASServerInfo` → `getVASServerInfo` | JSON reply | routed |
| `/sdk/getVASServiceList` | `VASGetServiceListRequest` `:8` | none declared | `getVASServiceList` → `getVASServiceList` | JSON reply | routed |
| `/sdk/getValidCloudStorageChlList` | `ValidCloudStorageChlListRequest` `:8` | raw JSON/string | `getValidCloudStorageChlList` | JSON reply | empty SDK callback |
| `/sdk/payVasInfo` | `VASPayRequest` `:10` | orderId, payType | `payVasInfo` → `payVasInfo` | JSON reply | routed |
| `/sdk/queryVASServiceStatus` | `VASQueryServiceStatusRequest` `:10` | devId, vasApplyId | `queryVASServiceStatus` → `queryVASServiceStatus` | JSON reply | routed |
| `/sdk/renewalVASService` | `VASReNewalServiceRequest` `:11` | chlIndex, FileSyncConstants.ADD_METHOD_SN→sn, devId, goodsId, applicationId | `renewalVASService` → `renewalVASService` | JSON reply | routed |
| `/sdk/setVasInstSwitch` | `VASSetInstSwitchRequest` `:10` | chlIndex, devSN, NotificationCompat.CATEGORY_STATUS→status | — | no matching reply method | empty executor |
| — (unregistered) | `GetDeviceRecordChlRequest` | devId, endTime, recordType, startTime | `getDeviceRecordChl` → `getDeviceRecordChl` | JSON reply | JNI export absent |
| — (unregistered) | `GetDeviceRecordDateRequest` | chlArray, devId, recordType, timeZone | `getDeviceRecordDate` → `getDeviceRecordDate` | JSON reply | JNI export absent |
| — (unregistered) | `GetDeviceRecordLogRequest` | chlId, devId, endTime, recordType, startTime, timeZone | `getDeviceRecordLog` → `getDeviceRecordLog` | JSON reply | JNI export absent |

### Media and device sessions (25 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/DeviceAddPTZPreset` | `DeviceAddPTZPresetRequest` `:11` | chlId, devId, presetIndex, prsetName | `deviceAddPTZPreset` → `deviceAddPTZPreset` | JSON reply | routed |
| `/sdk/DeviceDelPTZPreset` | `DeviceDelPTZPresetRequest` `:11` | chlId, devId, presetIndex | `deviceDelPTZPreset` → `deviceDelPTZPreset` | JSON reply | routed |
| `/sdk/DeviceGetPTZPresetList` | `DeviceGetPTZPresetListRequest` `:11` | chlId, devId | `deviceGetPTZPresetList` → `deviceGetPTZPresetList` | JSON reply | routed |
| `/sdk/DeviceSetChlSnapShot` | `DeviceSetChlSnapShotRequest` `:10` | chlId, pic | `deviceSetChlSnapShot` → `deviceSetChlSnapShot` | JSON reply | routed |
| `/sdk/closePlaybackStream` | `ClosePlaybackStreamRequest` `:10` | streamId | `closePlaybackStream` → `closePlaybackStream` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/closePlayback` | `ClosePlaybackRequest` `:10` | chlId, devId | `closePlayback` → `closePlayback` | JSON reply | JNI export absent |
| `/sdk/closeRealPlayStream` | `CloseRealPlayStreamRequest` `:10` | streamId | `closeRealPlayStream` → `closeRealPlayStream` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/connectDevice` | `ConnectDeviceRequest` `:10` | devId | `connectDevice` → `connectDevice` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/disConnectDevice` | `DisConnectDeviceRequest` `:10` | loginId | `disConnectDevice` → `disConnectDevice` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/endAudioDataWithDeviceId` | `EndAudioDataWithDeviceIdRequest` `:11` | chlId, deviveSN | `natLiveAudioSwitch` → `natLiveAudioSwitch` | no matching reply method | native zero-return stub |
| `/sdk/getConnectStatus` | `GetConnectStatusRequest` `:10` | loginId | `getConnectStatus` → `getConnectStatus` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/openPlaybackStream` | `OpenPlaybackStreamRequest` `:10` | chlId, endTime, loginId, recordType, startTime, streamType | `openPlaybackStream` → `openPlaybackStream` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/openPlayback` | `OpenPlaybackRequest` `:10` | chlId, devId, endTime, recordType, startTime, streamType | `openPlayback` → `openPlayback` | JSON reply | JNI export absent |
| `/sdk/openRealPlayStream` | `OpenRealPlayStreamRequest` `:10` | chlId, loginId, resolution, streamType | `openRealPlayStream` → `openRealPlayStream` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/playbackAudioSwitch` | `PlaybackAudioSwitchRequest` `:11` | TtmlNode.TEXT_EMPHASIS_MARK_OPEN→open, streamId | `playbackAudioSwitch` → `playbackAudioSwitch` | clears callback; no reply; UUID not forwarded | JNI export absent |
| `/sdk/realPlayAudioSwitch` | `RealPlayAudioSwitchRequest` `:10` | isOpen, streamId | `realPlayAudioSwitch` → `realPlayAudioSwitch` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/seekPlaybackStream` | `SeekPlaybackStreamRequest` `:10` | seekTime, streamId | `seekPlaybackStream` → `seekPlaybackStream` | no matching reply method; UUID not forwarded | JNI export absent |
| `/sdk/seekPlayback` | `SeekPlaybackRequest` `:10` | chlId, devId, seekTime | `seekPlayback` → `seekPlayback` | JSON reply | JNI export absent |
| `/sdk/sendCmdToGetKeyFrame` | `SendCmdToGetKeyFrameRequest` `:10` | chlId, endTime, frameNum, loginId, startTime | `sendCmdToGetKeyFrame` → `sendCmdToGetKeyFrame` | clears callback; no reply; UUID not forwarded | JNI export absent |
| `/sdk/sendCmdToPTZ` | `SendCmdToPTZRequest` `:11` | chlIndex, cmdType, loginId, presetIndex | `sendCmdToPTZ` → `sendCmdToPTZ` | clears callback; no reply; UUID not forwarded | overloaded JNI |
| `/sdk/sendCmdToPlaybackAllFrame` | `SendCmdToPlaybackAllFrameRequest` `:10` | startTime, streamId | `sendCmdToPlaybackAllFrame` → `sendCmdToPlaybackAllFrame` | clears callback; no reply; UUID not forwarded | JNI export absent |
| `/sdk/sendCmdToPlaybackByFrameIndex` | `SendCmdToPlaybackByFrameIndexRequest` `:10` | frameIndex, streamId | `sendCmdToPlaybackByFrameIndex` → `sendCmdToPlaybackByFrameIndex` | clears callback; no reply; UUID not forwarded | JNI export absent |
| `/sdk/sendCmdToPlaybackKeyFrame` | `SendCmdToPlaybackKeyFrameRequest` `:10` | startTime, streamId | `sendCmdToPlaybackKeyFrame` → `sendCmdToPlaybackKeyFrame` | clears callback; no reply; UUID not forwarded | JNI export absent |
| `/sdk/sendCmdToSnapShot` | `SendCmdToSnapShotRequest` `:10` | chlId, intervalTime, loginId, picNum, startTime, streamType | `sendCmdToSnapShot` → `sendCmdToSnapShot` | JSON reply; UUID not forwarded | JNI export absent |
| `/sdk/startAudioDataWithDeviceId` | `StartAudioDataWithDeviceIdRequest` `:10` | chlId, deviveSN | `natLiveAudioSwitch` → `natLiveAudioSwitch` | no matching reply method | native zero-return stub |

### Other services (16 classes)

| Route | Request class / declaration | Input keys | Dispatch | Result path | State |
| --- | --- | --- | --- | --- | --- |
| `/sdk/feedbackReportSubmit` | `FeedbackReportSubmitRequest` `:11` | contact, description, imgFilePaths, seceneld, uuid | `feedbackReportSubmit` → `feedbackReportSubmit` | JSON reply | routed |
| `/sdk/getAITranslateWithWords` | `GetAITranslateWithWords` `:9` | currentTime, language, words (declared; raw body forwarded) | `getAITranslateWithWords` → `getAITranslateWithWords` | JSON reply | routed |
| `/sdk/getCurrentDCAddress` | `GetCurrentDCAddressRequest` `:9` | none declared | `getCurrentDCAddress` → `getCurrentDCAddress` | JSON reply | routed |
| `/sdk/getExternalAppInfo` | `GetExternalAppInfoRequest` `:8` | raw JSON/string | `getExternalAppInfo` → `getExternalAppInfo` | JSON reply | routed |
| `/sdk/getFuncAvailable` | `GetFuncAvailableRequest` `:9` | none declared | `getFuncAvailable` → `getFuncAvailable` | JSON reply | routed |
| `/sdk/getInstallerBindUserList` | `GetInstallerBindUserList` `:8` | none declared | `getInstallerBindUserList` → `getInstallerBindUserList` | JSON reply | routed |
| `/sdk/getP2PUpgradeMaintenanceLang` | `getP2PUpgradeMaintenanceLangRequest` `:8` | raw JSON/string | `getP2PUpgradeMaintenanceLang` → `getP2PUpgradeMaintenanceLang` | JSON reply | routed |
| `/sdk/getProblemIndexList` | `GetProblemIndexListRequest` `:8` | none declared | `getProblemIndexList` → `getProblemIndexList` | JSON reply | routed |
| `/sdk/getProblemListByIndexId` | `GetProblemListByIndexIdRequest` `:10` | indexId | `getProblemListByIndexId` → `getProblemListByIndexId` | JSON reply | routed |
| `/sdk/getResidentBuildingListWithRoomId` | `GetResidentBuildingListWithRoomIdRequest` `:10` | pageNum, pageSize, queryType, roomId | `getResidentBuildingListWithRoomId` → `getResidentBuildingListWithRoomId` | JSON reply | routed |
| `/sdk/getResidentManagerState` | `GetResidentManagerStateRequest` `:10` | showAssociated | `getResidentManagerState` → `getResidentManagerState` | JSON reply | routed |
| `/sdk/getResidentRoomsList` | `GetResidentRoomsRequest` `:11` | FileSyncConstants.ADD_METHOD_SN→sn | `getResidentRoomsList` → `getResidentRoomsList` | JSON reply | routed |
| `/sdk/getUserBindInstallerInfo` | `GetUserBindInstallerInfoRequest` `:9` | postJson (declared; raw body forwarded) | `getUserBindInstallerInfo` → `getUserBindInstallerInfo` | JSON reply | routed |
| `/sdk/installerBindUser` | `InstallerBindUserRequest` `:8` | raw JSON/string | `installerBindUser` → `installerBindUser` | JSON reply | routed |
| `/sdk/setExternalAppInfo` | `SetExternalAppInfoRequest` `:8` | raw JSON/string | `setExternalAppInfo` → `setExternalAppInfo` | JSON reply | routed |
| `/sdk/userUnbindInstaller` | `UserUnbindInstallerRequest` `:8` | none declared | `userUnbindInstaller` → `userUnbindInstaller` | JSON reply | routed |

## Native declaration and JNI export inventory

The table includes all native Java declarations. Parameter names (`str`, `i`, `j`) are JADX placeholders; use the request input keys and `RequestCallback` signature for semantic meaning. Offsets are arm64 `st_value`; all 278 symbol names also occur in the 32-bit library. A matching short symbol proves conventional JNI name resolution is available, but does not establish a functioning implementation. Overloaded declarations need signature-specific review; this APK exports only the short JNI name for `sendCmdToPTZ` and no long `__...` form.

| Native declaration (`TVTOpenSDK.java`) | Return | Arm64 JNI export | Arm32 JNI export |
| --- | --- | --- |
| `acceptShared(long, String, String)` `:55` | `void` | `0x2a4af0` | `0x1d9641` |
| `addDeviceGroup(long, String, String)` `:57` | `void` | `0x2776ac` | `0x1bec25` |
| `addDeviceToFavoritesGroup(long, String, List<String>)` `:59` | `void` | `0x298618` | `0x1d216d` |
| `addDeviceToGroup(long, String, String, List<String>)` `:61` | `void` | `0x27813c` | `0x1bf259` |
| `addDownloadAlarmVideoTask(long, String, String, String, String)` `:63` | `void` | `0x2925cc` | `0x1ce9e1` |
| `addDownloadChlCoverImgTask(long, String, String, String, String)` `:65` | `void` | `0x29780c` | `0x1d1989` |
| `addDownloadFileTask(long, String, String, String, String, String, String)` `:67` | `boolean` | `0x28e39c` | `0x1cc2e9` |
| `addDownloadPTZPresetImgTask(long, String, String, String, String, String)` `:69` | `void` | `0x2972bc` | `0x1d1685` |
| `addDownloadRecordTask(long, String, String, String, String, String)` `:71` | `void` | `0x292084` | `0x1ce6e9` |
| `addFriendGroupWithGroupName(long, String, String)` `:73` | `void` | `0x283ed8` | `0x1c6175` |
| `addFriendToGroupWithGroupId(long, String, String, String[], boolean)` `:75` | `void` | `0x2847a0` | `0x1c6695` |
| `addUploadChlCoverImgTask(long, String, String, String, String)` `:77` | `void` | `0x297cc8` | `0x1d1c21` |
| `addUploadFileTask(long, String, String)` `:79` | `boolean` | `0x28e7c8` | `0x1cc585` |
| `addUserDevicePushList(long, String, String, String, String, String, int, String, int)` `:81` | `void` | `0x2ac1f8` | `0x1ddca5` |
| `addUserUnbindDevice(long, String, String)` `:83` | `void` | `0x2b1d78` | `0x1e131d` |
| `agreeApplyToNewFriendWithApplyId(long, String, String)` `:85` | `void` | `0x273a3c` | `0x1bc92d` |
| `applyVASService(long, String, String, String, String, int, int)` `:87` | `void` | `0x2a80fc` | `0x1db659` |
| `batchAcceptDeviceShared(long, String, List<String>)` `:89` | `void` | `0x2a52dc` | `0x1d9afd` |
| `batchAcceptShared(long, String, List<String>)` `:91` | `void` | `0x2a4e48` | `0x1d9849` |
| `bindMailByLogined(long, String, String, String)` `:93` | `void` | `0x288540` | `0x1c8b35` |
| `bindPhoneByLogined(long, String, String, String)` `:95` | `void` | `0x288938` | `0x1c8d8d` |
| `bindWx(long, String, String)` `:97` | `void` | `0x287ca8` | `0x1c8659` |
| `checkAccountIsRegister(long, String, int, String)` `:105` | `void` | `0x2837cc` | `0x1c5d45` |
| `checkIsBindAccount(long, String)` `:107` | `void` | `0x2879ec` | `0x1c84c9` |
| `checkIsMobileBind(long, String, String)` `:109` | `void` | `0x29b60c` | `0x1d3d55` |
| `chlGetCloudStorageInfo(long, String, String)` `:111` | `void` | `0x28f950` | `0x1ccf8d` |
| `closePlayback(long, String, String, int)` `:113` | `void` | absent | absent |
| `closePlaybackStream(long, String)` `:115` | `boolean` | absent | absent |
| `closeRealPlayStream(long, String)` `:117` | `boolean` | absent | absent |
| `connectDevice(long, String)` `:119` | `String` | absent | absent |
| `deleteDeviceFromFavoritesGroup(long, String, List<String>)` `:121` | `void` | `0x298aac` | `0x1d2421` |
| `deleteDevicePush2Message(long, String, String)` `:123` | `void` | `0x2abb28` | `0x1dd875` |
| `deleteFriendGroupWithGroupId(long, String, String)` `:125` | `void` | `0x2859dc` | `0x1c719d` |
| `deleteFriendsFromGroupWithGroupId(long, String, String, String[])` `:127` | `void` | `0x2867e0` | `0x1c7a19` |
| `deleteShared(long, String, List<String>)` `:129` | `void` | `0x2a5770` | `0x1d9db1` |
| `deleteUserDevicePushConfig(long, String, String, String)` `:131` | `void` | `0x2ac7f8` | `0x1de00d` |
| `deleteUserUnbindDevice(long, String, String)` `:133` | `void` | `0x2b20c8` | `0x1e1509` |
| `destoryTask(long)` `:1044` | `boolean` | `0x2ae984` | `0x1df3fd` |
| `deviceAddPTZPreset(long, String, String, String, String, int)` `:135` | `void` | `0x2891fc` | `0x1c927d` |
| `deviceBind(long, String, String, String, String)` `:137` | `void` | `0x2749ec` | `0x1bd249` |
| `deviceChlReName(long, String, String, String)` `:139` | `void` | `0x28ce58` | `0x1cb681` |
| `deviceCloudStorageIsValid(long, String, String)` `:141` | `void` | `0x2aa024` | `0x1dc869` |
| `deviceDelPTZPreset(long, String, String, String, int)` `:143` | `void` | `0x289a2c` | `0x1c971d` |
| `deviceFirmwareCheckUpdate(long, String, String)` `:145` | `void` | `0x289e00` | `0x1c9949` |
| `deviceFirmwareManualUpdate(long, String, String)` `:147` | `void` | `0x28a31c` | `0x1c9c4d` |
| `deviceFormatLocalStorage(long, String, String, int)` `:149` | `void` | `0x28e044` | `0x1cc0ed` |
| `deviceGetAlarmSwitch(long, String, String, String)` `:151` | `void` | `0x28b098` | `0x1ca43d` |
| `deviceGetInfo(long, String, String)` `:153` | `void` | `0x275e88` | `0x1bde31` |
| `deviceGetLocalStorageStatus(long, String, String)` `:155` | `void` | `0x28dcf4` | `0x1cbf01` |
| `deviceGetPTZPresetList(long, String, String, String)` `:157` | `void` | `0x289688` | `0x1c94ed` |
| `deviceGetRecStatus(long, String, String, List<Integer>)` `:159` | `void` | `0x28a66c` | `0x1c9e39` |
| `deviceGroupSetHomeType(long, String, String, boolean)` `:161` | `void` | `0x279098` | `0x1bfb3d` |
| `deviceGroupSetTop(long, String, String, boolean)` `:163` | `void` | `0x278e5c` | `0x1bf9f1` |
| `deviceGroupSortByIds(long, String, List<String>)` `:165` | `void` | `0x298184` | `0x1d1eb9` |
| `deviceReboot(long, String, String)` `:169` | `void` | `0x28ad48` | `0x1ca251` |
| `deviceRegister(long, String, int, String, String, String)` `:171` | `void` | `0x274708` | `0x1bd0ad` |
| `deviceReName(long, String, String, String)` `:167` | `void` | `0x275a98` | `0x1bdbd5` |
| `deviceSetAlarmSwitch(long, String, String, String, ConfigInfo)` `:173` | `void` | `0x28c8ac` | `0x1cb32d` |
| `deviceSetChlSnapShot(long, String, String, String)` `:175` | `void` | `0x28d84c` | `0x1cbc51` |
| `deviceSetMotionSwitch(long, String, String, boolean)` `:177` | `void` | `0x2793f4` | `0x1bfd41` |
| `deviceSetOfflineSwitch(long, String, String, boolean)` `:179` | `void` | `0x279630` | `0x1bfe8d` |
| `deviceTransfer(long, String, int, String, String, String)` `:181` | `void` | `0x2755d8` | `0x1bd92d` |
| `deviceUnBind(long, String, String)` `:183` | `void` | `0x275288` | `0x1bd741` |
| `deviceUpdateDeviceCode(long, String, String, String)` `:185` | `void` | `0x274e98` | `0x1bd4e5` |
| `disConnectDevice(long, String)` `:187` | `boolean` | absent | absent |
| `editDevicePush2Config(long, String, String)` `:189` | `void` | `0x2ab7d0` | `0x1dd66d` |
| `editUserDevicePushConfig(long, String, String)` `:191` | `void` | `0x2ab478` | `0x1dd465` |
| `feedbackReportSubmit(long, String, String, String, int, List<String>, String)` `:193` | `void` | `0x2995f4` | `0x1d2ab1` |
| `findPasswordPasswordWithAccount(long, String, String, String, String, String)` `:195` | `void` | `0x281ea8` | `0x1c4edd` |
| `getAccountChannelList(long, String, List<String>)` `:199` | `void` | `0x2a1ba4` | `0x1d79b9` |
| `getAccountChlVASStatus(long, String, String, String)` `:201` | `void` | `0x2a9f14` | `0x1dc7d1` |
| `getAccountDeviceList(long, String, int, int)` `:203` | `void` | `0x2a0fcc` | `0x1d72c9` |
| `getAITranslateWithWords(long, String, String)` `:197` | `void` | `0x271ba8` | `0x1bb7e9` |
| `getAllDeviceCapability(long, String)` `:205` | `void` | `0x2a9324` | `0x1dc0c5` |
| `getCanShareChlListWithFriendId(long, String, String)` `:211` | `void` | `0x285684` | `0x1c6f95` |
| `getCanShareChlListWithGroupId(long, String, String)` `:213` | `void` | `0x28532c` | `0x1c6d8d` |
| `getCanShareDeviceWithFriendId(long, String, String)` `:215` | `void` | `0x27c664` | `0x1c1bc5` |
| `getCanSharedFriendListByChlId(long, String, String)` `:219` | `void` | `0x287148` | `0x1c7f99` |
| `getCanSharedGroupListByChlId(long, String, String)` `:221` | `void` | `0x286df0` | `0x1c7d91` |
| `getCanShareFriendWithChannelId(long, String, String)` `:217` | `void` | `0x27c9bc` | `0x1c1dc5` |
| `getChannelDetailInfo(long, String, String, int)` `:223` | `void` | `0x2a2bc4` | `0x1d8329` |
| `getCloudListFromGroup(long, String, String, int, int)` `:225` | `void` | `0x29deb0` | `0x1d55b5` |
| `getCloudRecordDate(long, String, String, int, long, long)` `:227` | `void` | `0x291888` | `0x1ce241` |
| `getCloudRecordFileHttpURL(String, String, String)` `:1481` | `String` | `0x29d894` | `0x1d51ed` |
| `getCloudRecordList(long, String, int, String, int, String, long, long, String, int)` `:229` | `void` | `0x28fca0` | `0x1cd179` |
| `getCloudRecordState(long, String, String)` `:231` | `void` | `0x291c0c` | `0x1ce451` |
| `getCloudStorageDownloadToken(long, String, String, String, String, String)` `:233` | `void` | `0x290638` | `0x1cd715` |
| `getCloudVideoList(long, String, String, String, int, long, long, String, int)` `:235` | `void` | `0x290170` | `0x1cd455` |
| `getConnectStatus(long, String)` `:237` | `int` | absent | absent |
| `getCurrentDCAddress(long, String)` `:239` | `void` | `0x2aab0c` | `0x1dcec5` |
| `getDevAutoUpdate(long, String)` `:241` | `void` | `0x29a5d4` | `0x1d3431` |
| `getDeviceAbilityList(long, String, String)` `:243` | `void` | `0x277470` | `0x1bead9` |
| `getDeviceAccessToken(long, String, String)` `:245` | `void` | `0x276830` | `0x1be3bd` |
| `getDeviceAlarmCountInTime(long, String, List<String>, List<String>, long, long, boolean)` `:247` | `void` | `0x27db70` | `0x1c2855` |
| `getDeviceAlarmLatestInfo(long, String, int, List<String>, List<String>, boolean)` `:249` | `void` | `0x27ea90` | `0x1c3109` |
| `getDeviceAlarmListPage(long, String, int, int, List<String>, List<String>, List<String>, long, long, boolean)` `:251` | `void` | `0x27cd14` | `0x1c1fc5` |
| `getDeviceAlarmTypeCallBack(long, String)` `:253` | `void` | `0x27d8ec` | `0x1c26d5` |
| `getDeviceAlarmUnreadCounts(long, String, List<String>, List<String>, boolean)` `:255` | `void` | `0x27f374` | `0x1c3635` |
| `getDeviceBindStatus(long, String, String)` `:257` | `void` | `0x2ad0ac` | `0x1de505` |
| `getDeviceCapability(long, String, String)` `:259` | `void` | `0x2a8fcc` | `0x1dbebd` |
| `getDeviceChlOnlineStatus(long, String, String)` `:261` | `boolean` | `0x29599c` | `0x1d07d9` |
| `getDeviceDcInfo(long, String, String)` `:263` | `void` | `0x2a0c74` | `0x1d70c1` |
| `getDeviceDetailInfo(long, String, String, boolean)` `:265` | `void` | `0x2a2860` | `0x1d8111` |
| `getDeviceGroupList(long, String)` `:267` | `void` | `0x276b80` | `0x1be5a9` |
| `getDeviceHDDAlarmList(long, String, String, int, int)` `:269` | `boolean` | `0x296074` | `0x1d0be1` |
| `getDeviceHealthReport(long, String, long, long, int, int)` `:271` | `boolean` | `0x294128` | `0x1cf99d` |
| `getDeviceHealthSchedule(long, String)` `:273` | `boolean` | `0x2963f0` | `0x1d0df1` |
| `getDeviceList(long, String, int, int)` `:275` | `void` | `0x2761d8` | `0x1be01d` |
| `getDeviceListFromGroup(long, String, String, int, int)` `:277` | `void` | `0x277108` | `0x1be8cd` |
| `getDeviceListToOurGroup(long, String, int, int)` `:279` | `void` | `0x276e34` | `0x1be731` |
| `getDeviceLocalStorageStatus(long, String, String)` `:281` | `boolean` | `0x295d08` | `0x1d09dd` |
| `getDeviceNetQualityReport(long, String, String, long, long, int, int)` `:283` | `boolean` | `0x296ba0` | `0x1d126d` |
| `getDeviceNetSafeReport(long, String, String, long, long, int, int)` `:285` | `boolean` | `0x294f08` | `0x1d01b1` |
| `getDeviceNetSafeSwitch(long, String, String)` `:287` | `boolean` | `0x2952b8` | `0x1d03c5` |
| `getDevicePush2Config(long, String, String)` `:289` | `void` | `0x2ab120` | `0x1dd25d` |
| `getDevicePush2DetailMessage(long, String, String)` `:291` | `void` | `0x2abe90` | `0x1dda8d` |
| `getDeviceRecordChl(long, String, String, long, long, long)` `:293` | `void` | absent | absent |
| `getDeviceRecordDate(long, String, String, List<Integer>, int, long)` `:295` | `void` | absent | absent |
| `getDeviceRecordLog(long, String, String, int, long, long, long, int)` `:297` | `void` | absent | absent |
| `getDeviceSleepStatus(long, String, String)` `:299` | `void` | `0x2b16c8` | `0x1e0f0d` |
| `getDeviceTragetValueSetCredential(long, String, String, String, String)` `:301` | `void` | `0x2a6688` | `0x1da6b5` |
| `getDynamicCodeWithAccount(long, String, String, int, int, String, String)` `:303` | `void` | `0x28002c` | `0x1c3d99` |
| `getExternalAppInfo(long, String, String)` `:309` | `void` | `0x2b08c8` | `0x1e0699` |
| `getExternalAppOauth(long, String, String)` `:311` | `void` | `0x2afb68` | `0x1dfe79` |
| `getFriendGroupList(long, String)` `:313` | `void` | `0x284230` | `0x1c637d` |
| `getFriendGroupUserListWithGroupId(long, String, String)` `:315` | `void` | `0x285d38` | `0x1c73b1` |
| `getFuncAvailable(long, String)` `:317` | `void` | `0x283e7c` | `0x1c6141` |
| `getGroupListToMe(long, String)` `:319` | `boolean` | `0x293678` | `0x1cf36d` |
| `getImgVerifyCode(long, String)` `:321` | `void` | `0x280dec` | `0x1c4575` |
| `getInstallerBindUserList(long, String)` `:323` | `void` | `0x2af550` | `0x1dfadd` |
| `getLastedDeviceHealthReport(long, String)` `:340` | `boolean` | `0x293e58` | `0x1cf809` |
| `getMobileBindInfoList(long, String)` `:342` | `void` | `0x29b964` | `0x1d3f5d` |
| `getMobileBindSwitch(long, String)` `:344` | `void` | `0x29b350` | `0x1d3bc5` |
| `getMsgPushSwitch(long, String)` `:346` | `void` | `0x299fb4` | `0x1d3089` |
| `getMyFriendList(long, String)` `:348` | `void` | `0x2844ec` | `0x1c650d` |
| `getOnOffDeviceConfig(long, String, List<String>, List<Integer>, String)` `:350` | `void` | `0x2a6b44` | `0x1da94d` |
| `getP2PUpgradeMaintenanceLang(long, String, String)` `:352` | `void` | `0x2af80c` | `0x1dfc6d` |
| `getPlaybackRecordChl(long, String, long, long, long)` `:354` | `boolean` | absent | absent |
| `getPlaybackRecordDate(long, String, List<Integer>, long, int)` `:356` | `boolean` | absent | absent |
| `getPlaybackRecordLog(long, String, int, long, long, long, int)` `:358` | `boolean` | absent | absent |
| `getProblemIndexList(long, String)` `:360` | `void` | `0x29906c` | `0x1d2791` |
| `getProblemListByIndexId(long, String, int)` `:362` | `void` | `0x299328` | `0x1d2921` |
| `getReceiveApplyListForNewFriend(long, String)` `:364` | `void` | `0x2734d4` | `0x1bc61d` |
| `getReceiveApplyNumForNewFriend(long, String)` `:366` | `void` | `0x273788` | `0x1bc7a5` |
| `getRegisterDynamicCodeWithAccount(long, String, int, String, String)` `:368` | `void` | `0x2804f0` | `0x1c4059` |
| `getRequestTaskId()` `:2097` | `long` | `0x2ae95c` | `0x1df3e5` |
| `getResidentBuildingListWithRoomId(long, String, String, int, int, int)` `:374` | `void` | `0x2764ac` | `0x1be1b9` |
| `getResidentDeviceList(long, String, int, int)` `:376` | `void` | `0x2a12a8` | `0x1d7471` |
| `getResidentManagerState(long, String, boolean)` `:378` | `void` | `0x2a18dc` | `0x1d7821` |
| `getResidentRoomsList(long, String, String)` `:380` | `void` | `0x2a1584` | `0x1d7619` |
| `getSendApplyListForNewFriend(long, String)` `:382` | `void` | `0x273220` | `0x1bc495` |
| `getServiceMsgList(long, String, String, long, long, int, int)` `:384` | `boolean` | `0x28ef7c` | `0x1cc9e5` |
| `getServiceMsgType(long, String)` `:386` | `boolean` | `0x28e9dc` | `0x1cc6bd` |
| `getShareAuthByChlId(long, String, String)` `:388` | `void` | `0x29db58` | `0x1d53ad` |
| `getSharedChlInfoByChlID(long, String, String)` `:392` | `void` | `0x27c30c` | `0x1c19c5` |
| `getSharedChlListByFriendID(long, String, String)` `:394` | `void` | `0x27bcd8` | `0x1c161d` |
| `getSharedChlListByGroupId(long, String, String)` `:396` | `void` | `0x286090` | `0x1c75b9` |
| `getSharedChlListByMy(long, String, int, int)` `:398` | `boolean` | `0x292a78` | `0x1cec7d` |
| `getSharedChlListByMyPage(long, String, int, int)` `:400` | `void` | `0x27b9fc` | `0x1c1475` |
| `getSharedChlListToMe(long, String, int, int)` `:402` | `boolean` | `0x293388` | `0x1cf1bd` |
| `getSharedChlListToMePage(long, String, int, int)` `:404` | `void` | `0x27c030` | `0x1c181d` |
| `getSharedInfoByShareId(long, String, String)` `:406` | `void` | `0x27ac9c` | `0x1c0c75` |
| `getSharedListByTargetUser(long, String, String, List<String>)` `:408` | `void` | `0x2a5f5c` | `0x1da26d` |
| `getSharedListFromOther(long, String, int, int, List<Integer>)` `:410` | `void` | `0x2a44b0` | `0x1d928d` |
| `getSharedListToAccount(long, String, String, int)` `:412` | `void` | `0x2a5c04` | `0x1da065` |
| `getSharedListToOther(long, String, int, int, List<Integer>)` `:414` | `void` | `0x2a3e70` | `0x1d8ed9` |
| `getShareGroupChannelListToMeWithGroupIds(long, String, List<String>)` `:390` | `boolean` | `0x293838` | `0x1cf479` |
| `getTransferDeviceList(long, String, String)` `:416` | `void` | `0x2b0c20` | `0x1e08a1` |
| `getUnReadServiceMsgNum(long, String)` `:418` | `boolean` | `0x28ecac` | `0x1cc851` |
| `getUserAppData(long, String)` `:420` | `void` | `0x29ee28` | `0x1d5f39` |
| `getUserAppDataVersion(long, String)` `:422` | `void` | `0x29eb6c` | `0x1d5da9` |
| `getUserBindInstallerInfo(long, String)` `:424` | `void` | `0x2aec80` | `0x1df5b5` |
| `getUserCountSharedChlList(long, String, List<String>)` `:426` | `boolean` | `0x292d68` | `0x1cee2d` |
| `getUserDeviceEventMessageList(long, String, String, String, int, int)` `:428` | `void` | `0x2aa6d4` | `0x1dcc79` |
| `getUserDeviceList(long, String, String)` `:430` | `void` | `0x2b2ab8` | `0x1e1acd` |
| `getUserDevicePushConfig(long, String, String)` `:432` | `void` | `0x2aadc8` | `0x1dd055` |
| `getUserInfo(long, String)` `:434` | `void` | `0x2823c0` | `0x1c51bd` |
| `getUserPrivateData(long, String)` `:436` | `void` | `0x28d598` | `0x1cbac9` |
| `getUserPropertiesWithWords(long, String, String)` `:438` | `void` | `0x271ef8` | `0x1bb9d5` |
| `getUserQrcodeInfo(long, String)` `:440` | `void` | `0x2ae9b0` | `0x1df419` |
| `getUserUnbindDeviceList(long, String, String)` `:442` | `void` | `0x2b2768` | `0x1e18e1` |
| `getValidCloudStorageChlList(long, String, String)` `:454` | `void` | `0x2aa37c` | `0x1dca71` |
| `getVASApplyRecordList(long, String, String, int, String, int, long, long, int, int)` `:444` | `void` | `0x2a8b88` | `0x1dbc61` |
| `getVASCloudStoreGoodList(long, String, String, int, String)` `:446` | `void` | `0x2a95e0` | `0x1dc255` |
| `getVASGoodList(long, String, int, String, int, int, int)` `:448` | `void` | `0x2a7d60` | `0x1db441` |
| `getVASServerInfo(long, int, String, String)` `:450` | `void` | `0x2a96f0` | `0x1dc2ed` |
| `getVASServiceList(long, String)` `:452` | `void` | `0x2a7744` | `0x1db09d` |
| `installerBindUser(long, String, String)` `:456` | `void` | `0x2aef3c` | `0x1df745` |
| `linkExternalApp(long, String, String)` `:477` | `void` | `0x2afec0` | `0x1e0081` |
| `modifyChannelRemark(long, String, String, int, String)` `:479` | `void` | `0x2a2430` | `0x1d7ec9` |
| `modifyDeviceGroupName(long, String, String, String)` `:481` | `void` | `0x277d4c` | `0x1beffd` |
| `modifyDeviceRemark(long, String, String, String)` `:483` | `void` | `0x2a2038` | `0x1d7c6d` |
| `modifyEmail(long, String, String, String, String)` `:485` | `void` | `0x288d30` | `0x1c8fe5` |
| `modifyFriendGroupWithGroupId(long, String, String, String)` `:487` | `void` | `0x2863e8` | `0x1c77c1` |
| `modifyPassword(long, String, int, String, String)` `:489` | `void` | `0x28339c` | `0x1c5afd` |
| `modifyPhone(long, String, String, String, String)` `:491` | `void` | `0x288074` | `0x1c889d` |
| `modifyPushDeviceName(long, String, String, String, String)` `:493` | `void` | `0x2acbf0` | `0x1de269` |
| `natCloseLiveVideo(long, String, String, int)` `:495` | `boolean` | `0x28001c` | `0x1c3d91` |
| `natConnectDevice(long, String, String)` `:497` | `boolean` | `0x280004` | `0x1c3d85` |
| `natDisConnectDevice(long, String, String)` `:2617` | `boolean` | `0x28000c` | `0x1c3d89` |
| `natLiveAudioSwitch(long, String, String, int, boolean)` `:499` | `boolean` | `0x280024` | `0x1c3d95` |
| `natOpenLiveVideo(long, String, String, int, int, String)` `:501` | `boolean` | `0x280014` | `0x1c3d8d` |
| `openPlayback(long, String, String, int, int, long, long, long)` `:510` | `void` | absent | absent |
| `openPlaybackStream(long, String, int, int, long, long, long)` `:512` | `String` | absent | absent |
| `openRealPlayStream(long, String, int, int, String)` `:514` | `String` | absent | absent |
| `payVasInfo(long, String, int, String)` `:516` | `void` | `0x2a9a50` | `0x1dc501` |
| `playbackAudioSwitch(long, String, boolean)` `:520` | `boolean` | absent | absent |
| `playbackAudioSwitch(long, String, String, int, boolean)` `:518` | `void` | absent | absent |
| `queryVASServiceStatus(long, String, int, String)` `:522` | `void` | `0x2a7a00` | `0x1db22d` |
| `realPlayAudioSwitch(long, String, boolean)` `:524` | `boolean` | absent | absent |
| `registerCallback()` `:526` | `boolean` | `0x271714` | `0x1bb53d` |
| `registerDevStatusNotify()` `:528` | `void` | absent | absent |
| `registerMobile(long, String, String, String, String, String, String, String, String, String, int)` `:530` | `void` | `0x29a890` | `0x1d35c1` |
| `remarkMyFriendInfo(long, String, String, String)` `:532` | `void` | `0x2740dc` | `0x1bcd05` |
| `removeCloudRecord(long, String, List<String>, List<String>)` `:534` | `void` | `0x290b80` | `0x1cda11` |
| `removeDeviceFromGroup(long, String, String, List<String>)` `:536` | `void` | `0x2787cc` | `0x1bf625` |
| `removeDeviceGroup(long, String, String)` `:538` | `void` | `0x2779fc` | `0x1bee11` |
| `removeMobileBindListList(long, String, List<String>)` `:540` | `void` | `0x29bc20` | `0x1d40ed` |
| `removeMyFriend(long, String, String)` `:542` | `void` | `0x273d8c` | `0x1bcb19` |
| `removeShareChlByChlID(long, String, String)` `:544` | `void` | `0x27b6a4` | `0x1c1275` |
| `removeShareChlByFriendID(long, String, String)` `:546` | `void` | `0x27b34c` | `0x1c1075` |
| `removeShareChlByShareID(long, String, String)` `:548` | `void` | `0x27aff4` | `0x1c0e75` |
| `renewalVASService(long, String, String, String, String, int, int)` `:550` | `void` | `0x2a8674` | `0x1db97d` |
| `requestGetDeviceArm(long, String, String)` `:552` | `void` | `0x2b0f78` | `0x1e0aa9` |
| `requestSetDeviceArm(long, String, String, String)` `:554` | `void` | `0x2b12d0` | `0x1e0cb1` |
| `requestWakeupDevice(long, String, String)` `:556` | `void` | `0x2b1a20` | `0x1e1115` |
| `requestWebWithUrl(long, String, String, String)` `:558` | `void` | `0x2ae0a4` | `0x1dee79` |
| `resetDcCenterUrl()` `:560` | `void` | `0x2a6650` | `0x1da685` |
| `resetProtoToken()` `:562` | `void` | `0x2a666c` | `0x1da69d` |
| `rmrModifyPassword(long, String, String, String)` `:564` | `void` | `0x2ad954` | `0x1dea15` |
| `rmrSetUserInfo(long, String, String)` `:566` | `void` | `0x2add4c` | `0x1dec71` |
| `rmrUserLoginAccount(long, String, String, String, String, String)` `:568` | `void` | `0x2ad404` | `0x1de70d` |
| `searchMyFriendByLoginName(long, String, String)` `:570` | `void` | `0x283b2c` | `0x1c5f55` |
| `searchMyFriendByRemark(long, String, String)` `:572` | `void` | `0x2744cc` | `0x1bcf61` |
| `seekPlayback(long, String, String, int, long)` `:574` | `void` | absent | absent |
| `seekPlaybackStream(long, String, long)` `:576` | `boolean` | absent | absent |
| `sendApplyForAddFriends(long, String, String, String, String, String)` `:578` | `void` | `0x272cd8` | `0x1bc19d` |
| `sendAuthorizationforWebQrcodeLogin(long, String, String, boolean)` `:580` | `void` | `0x2a0910` | `0x1d6ea9` |
| `sendCmdToGetKeyFrame(long, String, int, int, long, long)` `:584` | `boolean` | absent | absent |
| `sendCmdToGetKeyFrame(long, String, String, int, byte, long, long)` `:582` | `void` | absent | absent |
| `sendCmdToPlaybackAllFrame(long, String, long)` `:592` | `boolean` | absent | absent |
| `sendCmdToPlaybackAllFrame(long, String, String, int, long)` `:590` | `void` | absent | absent |
| `sendCmdToPlaybackByFrameIndex(long, String, int)` `:596` | `boolean` | absent | absent |
| `sendCmdToPlaybackByFrameIndex(long, String, String, int, int)` `:594` | `void` | absent | absent |
| `sendCmdToPlaybackKeyFrame(long, String, long)` `:600` | `boolean` | absent | absent |
| `sendCmdToPlaybackKeyFrame(long, String, String, int, long)` `:598` | `void` | absent | absent |
| `sendCmdToPTZ(long, String, int, int, int, int)` `:588` | `boolean` | `0x29e710`; overloaded short name only | `0x1d5b19` |
| `sendCmdToPTZ(long, String, String, int, int, int, int)` `:586` | `void` | `0x29e710`; overloaded short name only | `0x1d5b19` |
| `sendCmdToSnapShot(long, String, int, int, long, long, int)` `:602` | `boolean` | absent | absent |
| `sendCmdToSnapShot(long, String, String, int, int, long, long, int)` `:604` | `boolean` | absent | absent |
| `sendHealthCheckCmdToDev(long, String, String, String)` `:606` | `boolean` | `0x294424` | `0x1cfb51` |
| `sendNetQualityCheckCmdToDev(long, String, String)` `:608` | `boolean` | `0x296f50` | `0x1d1481` |
| `sendNetSafeCheckCmdToDev(long, String, String)` `:610` | `boolean` | `0x294830` | `0x1cfda9` |
| `sendNetSafeRepairCmdToDev(long, String, String)` `:612` | `boolean` | `0x294b9c` | `0x1cffad` |
| `sendNotificationToken(long, String, String, String, int, List<String>)` `:614` | `void` | `0x27fa84` | `0x1c3a3d` |
| `sendUUIDforWebQrcodeLogin(long, String, String)` `:616` | `void` | `0x2a05b8` | `0x1d6ca1` |
| `setCloudRecordSwitch(long, String, String, boolean)` `:618` | `void` | `0x291e48` | `0x1ce59d` |
| `setDevAutoUpdate(long, String, boolean, String)` `:620` | `void` | `0x29a270` | `0x1d3219` |
| `setDeviceAlarmStatus(long, String, List<String>, int, int)` `:622` | `void` | `0x27e46c` | `0x1c2d8d` |
| `setDeviceHealthSchedule(long, String, boolean, List<String>)` `:624` | `boolean` | `0x2966c0` | `0x1d0f85` |
| `setDeviceListToNat(long, List<String>, List<String>)` `:626` | `void` | `0x298f40` | `0x1d26d5` |
| `setDeviceNetSafeSwitch(long, String, String, boolean)` `:628` | `boolean` | `0x295624` | `0x1d05c9` |
| `setEnableLog(boolean)` `:3092` | `void` | `0x2a6478` | `0x1da585` |
| `setExternalAppInfo(long, String, String)` `:630` | `void` | `0x2b0570` | `0x1e0491` |
| `setLanguage(long, String, String)` `:632` | `void` | `0x2a0260` | `0x1d6a9d` |
| `setMobileBindSwitch(long, String, boolean)` `:634` | `void` | `0x29b088` | `0x1d3a2d` |
| `setMobileIsBind(long, String, String, String, int)` `:636` | `void` | `0x29d464` | `0x1d4fa5` |
| `setMsgPushSwitch(long, String, boolean, String)` `:638` | `void` | `0x299c50` | `0x1d2e71` |
| `setOnOffDeviceConfig(long, String, String)` `:640` | `void` | `0x2a73ec` | `0x1dae95` |
| `setReDirectFinished(long, boolean, String)` `:3152` | `void` | `0x2ae49c` | `0x1df0d1` |
| `setReplaceUrl(long, List<String>, List<String>)` `:3154` | `void` | `0x2ae5a0` | `0x1df181` |
| `setServiceMsgListStatus(long, String, List<String>, int)` `:642` | `boolean` | `0x28f32c` | `0x1ccc05` |
| `setSharedChlPermission(long, String, String, ChlPermission)` `:644` | `void` | `0x27a248` | `0x1c05e1` |
| `setUserAppData(long, String, String, String)` `:646` | `void` | `0x29e774` | `0x1d5b4d` |
| `setUserInfo(long, String, String, String, String, String, String, String, int)` `:648` | `void` | `0x28268c` | `0x1c5359` |
| `setUserPrivateData(long, String, String)` `:650` | `void` | `0x28d248` | `0x1cb8dd` |
| `shareChl(long, String, String, int, List<ShareInfo>, List<DeviceShareInfo>)` `:652` | `void` | `0x2a3748` | `0x1d8a91` |
| `shareChlToMyGroup(long, String, String, Map<String, ChlPermission>)` `:654` | `void` | `0x285008` | `0x1c6bad` |
| `sharedCameraChlsToFriend(long, String, List<CameraShareInfo>)` `:656` | `void` | `0x29c964` | `0x1d4915` |
| `sharedChlsToFriend(long, String, String, Map<String, ChlPermission>)` `:660` | `void` | `0x27986c` | `0x1bffd9` |
| `sharedChlToGroupsOrFriends(long, String, String, HashMap<String, ChlPermission>, HashMap<String, ChlPermission>)` `:658` | `void` | `0x2874a0` | `0x1c81a1` |
| `startProtoManagerServer(String, String, int, String, String)` `:662` | `boolean` | `0x270ea0` | `0x1baff5` |
| `stopProtoManagerServer()` `:664` | `boolean` | `0x271674` | `0x1bb4bd` |
| `thirdLogin(long, String, String, String, int, String, String)` `:666` | `void` | `0x29f7e0` | `0x1d64a1` |
| `unLinkExternalApp(long, String, String)` `:668` | `void` | `0x2b0218` | `0x1e0289` |
| `updateUserUnbindDevice(long, String, String)` `:682` | `void` | `0x2b2418` | `0x1e16f5` |
| `userLogin(long, String, int, String, String, String, String, String, String, String, String, String)` `:686` | `void` | `0x2810a8` | `0x1c4705` |
| `userLoginedBindThird(long, String, String, int, String)` `:688` | `void` | `0x29f0e4` | `0x1d60c9` |
| `userLoginedUnBindThird(long, String, int)` `:690` | `void` | `0x29f514` | `0x1d6311` |
| `userLoginedUnBindWX(long, String)` `:692` | `void` | `0x287eb8` | `0x1c8791` |
| `userLogOut(long, String)` `:684` | `boolean` | `0x282d54` | `0x1c5741` |
| `userRegisterWithAccount(long, String, String, int, String, String, String, String, String)` `:694` | `void` | `0x280778` | `0x1c41d5` |
| `userThirdBindAccount(long, String, String, String, int, String, String)` `:696` | `void` | `0x29fd08` | `0x1d678d` |
| `userUnbindInstaller(long, String)` `:702` | `void` | `0x2af294` | `0x1df94d` |
| `userUnRegister(long, String, int, String)` `:698` | `void` | `0x282d80` | `0x1c575d` |
| `userUnRegisterNoParams(long, String)` `:700` | `void` | `0x2830e0` | `0x1c596d` |
| `userUploadHeadImg(long, String, String)` `:704` | `void` | `0x29d10c` | `0x1d4da1` |
| `wxBindMobile(long, String, String, String, String, String)` `:706` | `void` | `0x281b9c` | `0x1c4d29` |
| `wxLoginWithWxCode(long, String, String, String)` `:708` | `void` | `0x281938` | `0x1c4bc5` |

### Exported JNI names without a Java declaration

- `checkImgVerifyCode`: E64 `0x271858`, 848 bytes; no `TVTOpenSDK.java` native declaration.
- `checkMobileNumUpdateDynamicCode`: E64 `0x272a44`, 92 bytes; no `TVTOpenSDK.java` native declaration.
- `getMobileLoginDynamicCode`: E64 `0x2727bc`, 188 bytes; no `TVTOpenSDK.java` native declaration.
- `getMobileNumUpdateDynamicCode`: E64 `0x272878`, 188 bytes; no `TVTOpenSDK.java` native declaration.
- `getMobileRegisterDynamicCode`: E64 `0x272248`, 656 bytes; no `TVTOpenSDK.java` native declaration.
- `getPasswdFindDynamicCode`: E64 `0x272c1c`, 188 bytes; no `TVTOpenSDK.java` native declaration.
- `getPasswdResetDynamicCode`: E64 `0x272b60`, 188 bytes; no `TVTOpenSDK.java` native declaration.
- `getWxBindMobileDynamicCode`: E64 `0x272aa4`, 188 bytes; no `TVTOpenSDK.java` native declaration.
- `mobileNumberUpdate`: E64 `0x272934`, 272 bytes; no `TVTOpenSDK.java` native declaration.
- `mobileRegister`: E64 `0x2724d8`, 740 bytes; no `TVTOpenSDK.java` native declaration.
- `tokenLogin`: E64 `0x272aa0`, 4 bytes; no `TVTOpenSDK.java` native declaration.

## Specific gaps and interpretation

1. **Route collision:** `Protocol_Type.getDeviceHDDAlarmList` and `.getDeviceLocalStorageStatus` both equal `/sdk/getDeviceLocalStorageStatus` (`J:com/tvt/protocol_sdk/Protocol_Type.java:239-240`). The generated group first registers `GetDeviceLocalStorageStatusRequest` at line 321, then overwrites it with `GetDeviceHDDAlarmListRequest` at line 545. The effective route expects `devId`, `pageNo`, `pageSize` and calls `getDeviceHDDAlarmList`; the storage-status class expects only `devId` and is unreachable through this map. Both reply handlers label the same route (`TVTOpenSDK.java:1666,1749`).
2. **Unregistered classes:** `GetDeviceRecordChlRequest`, `GetDeviceRecordDateRequest`, and `GetDeviceRecordLogRequest` have neither `@cb4` annotation nor a generated router registration. Their executors call native-backed `RequestCallback` methods, but there is no `/sdk` route for them in this table. The `getDeviceRecordChl/Date/Log` native declarations also lack conventional exports.
3. **Empty Java paths:** `CheckImgVerifyCodeRequest.execute` and `VASSetInstSwitchRequest.execute` are empty (`J:com/tvt/protocol_sdk/request/CheckImgVerifyCodeRequest.java:19-21`; `com/tvt/protocol_sdk/request/VASSetInstSwitchRequest.java:26-28`). `TVTOpenSDK.deviceCloudStorageIsValid` and `.getValidCloudStorageChlList` callback implementations are empty even though their request classes dispatch to them (`J:com/tvt/protocol_sdk/TVTOpenSDK.java:1081-1082,2469-2470`). The matching `*Reply` methods do not make these outbound paths functional.
4. **Missing conventional JNI names:** 25 distinct Java native names have no `TVTOpenSDK` dynamic export in either packaged `libProtoSDK.so`: `closePlayback`, `closePlaybackStream`, `closeRealPlayStream`, `connectDevice`, `disConnectDevice`, `getConnectStatus`, `getDeviceRecordChl`, `getDeviceRecordDate`, `getDeviceRecordLog`, `getPlaybackRecordChl`, `getPlaybackRecordDate`, `getPlaybackRecordLog`, `openPlayback`, `openPlaybackStream`, `openRealPlayStream`, `playbackAudioSwitch`, `realPlayAudioSwitch`, `registerDevStatusNotify`, `seekPlayback`, `seekPlaybackStream`, `sendCmdToGetKeyFrame`, `sendCmdToPlaybackAllFrame`, `sendCmdToPlaybackByFrameIndex`, `sendCmdToPlaybackKeyFrame`, `sendCmdToSnapShot`. This covers connect/disconnect, live/playback stream and record controls, frame/snapshot controls, and `registerDevStatusNotify`. Dynamic `RegisterNatives` cannot be ruled out from symbol comparison alone; the examined Ghidra paths and `JNI_OnLoad` evidence have not established such a mapping. Treat these routes as unresolved, not callable by assumption.
5. **Native no-op evidence:** Ghidra’s arm64 decompilation of `natConnectDevice` (`E64:0x280004`), `natDisConnectDevice` (`0x28000c`), `natOpenLiveVideo` (`0x280014`), `natCloseLiveVideo` (`0x28001c`), and `natLiveAudioSwitch` (`0x280024`) shows short bodies returning zero. The corresponding Java routes are therefore present but these native entry points do not implement media transport in this binary. Exported `tokenLogin` (`0x272aa0`, 4 bytes) is also an empty native body and has no Java declaration (`ghidra-proto-more.txt:354-361`; `ghidra-paths.txt` for NAT stubs).
6. **Reply mismatches and drops:** Six specialized alarm-switch routes all call `deviceGetAlarmSwitch` and its reply labels `/sdk/DeviceGetAlarmSwitch`; `GetSharedListToAccountRequest` receives a reply labeled `/sdk/deleteShared` (`TVTOpenSDK.java:2284`). The `sendCmdToPTZReply` and `sendCmdToGetKeyFrameReply`/playback-control reply methods call `getCallback(uuid)` without invoking `TVTOpenCallback.reply` (`TVTOpenSDK.java:2930-2980`), so those named reply paths discard delivery. `getCloudVideoList` has no matching Java reply method in this class. Several synchronous session methods also have no UUID reply path and discard the return value in their request executors.
7. **Overloaded JNI ambiguity:** `sendCmdToPTZ` has two native declarations (with and without request UUID), while the ELF has one short `Java_com_tvt_protocol_1sdk_TVTOpenSDK_sendCmdToPTZ` export (`E64:0x29e710`) and no mangled long overload exports. Six other names are similarly overloaded in Java but lack exports entirely. Their binding/ABI cannot be declared reliable from this static mapping.
8. **Status limits:** Neither router registration nor an ELF export demonstrates server acceptance, authentication, authorization, payload format, or device capability. The native response JSON schemas are opaque at this layer. The SDK also contains reply methods for three `/sdk/rmr*` paths without generated route registrations. Actual endpoint availability and result codes require separately authorized runtime observation; none was performed for this audit.
9. **Constants without routes:** Six distinct `Protocol_Type` strings have no generated registration: `/sdk/mobileNumberUpdate`, `/sdk/getVasInstSwitchStatus`, `/sdk/requestWebWithUrl`, and `/sdk/rmrModifyPassword`, `/sdk/rmrSetUserInfo`, `/sdk/rmrUserLoginAccount`. The latter three have Java reply methods, but no request class route. The public availability of `TVTOpenSDK` itself is also unverified, as documented in the [web check](00-tvtopensdk-web-check.md).
10. **Interface methods without a request class call:** Seven distinct `RequestCallback` names are not called by any of the 281 request classes: `getSharedChlListByFriendId`, `natConnectDevice`, `natDisConnectDevice`, `requestWebWithUrl`, `rmrModifyPassword`, `rmrSetUserInfo`, and `rmrUserLoginAccount` (`J:com/tvt/protocol_sdk/RequestCallback.java`). Other entry points may call these methods directly, but the generated `/sdk` request class layer does not.

### Reproduction checks

The counts can be reproduced from the specified APK artifact by counting direct `request/*.java` files, `@cb4(path...)` annotations, and `map.put(...)` entries, then reading `.dynsym` names beginning `Java_com_tvt_protocol_1sdk_TVTOpenSDK_` in each `libProtoSDK.so`. The arm64 and arm32 exported-name sets are identical (278 names). `RequestFactory.createRequest(int)` returns `null` (`J:com/tvt/protocol_sdk/RequestFactory.java:5-7`) and is not the active generated route table. No source outside the declared APK artifacts was used to infer behavior.
