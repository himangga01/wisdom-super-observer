# APK-derived private local NAT bootstrap profile

Analysis date: **2026-10-03, Asia/Seoul**. Root-supplied baseline `756946ca73cff31d7ebb23141873088b470a96b4` (no Git execution). Approved SuperLive Plus **1.18.1 / 20267**, package `com.tvt.superliveplus`, APK SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. **Configuration source/validation only; MATCHED=0; release_ready=false.** This module performs no discovery, credential authentication, media or native execution.

## Captured selection and exact values

Source paths below refer to `W04-local-QR-connection-source-evidence/frozen-sources/`: `J:` = `jadx/`, `R:` = `prior/apktool/`. Additional original APK sources are frozen in `W04-local-bootstrap-profile-evidence/readset/`. The packet manifests preserve complete files, line context, hashes, commands and owned additions.

`R:res/xml/custom.xml:3–28` selects the `SuperLivePlus` item by package; `J:com/tvt/other/CustomPath.java:397–418` installs its NAT fields. NAT1 is **`c2.autonat.com:40002`**. XML NAT2 is **`c2020.autonat.com:8888`**, but the ordinary regional initialization **replaces it**. This item has six `natServerArea` entries, no `nat2Port` and no `supportOnlyNat`. `AppInfomation.strNat2Port` defaults to **`7968`** (`CustomPath:66`), `supportOnlyNat` defaults false (`:71`), and `:443–475` constructs **`cli-nat20.<selected-root-domain>:7968`**. The selected branch does not use static `GlobalUnit.V0/Z0` initializers (`GlobalUnit:181,185`) or the XML NAT2 endpoint as the ordinary default.

| Explicit source country input | Resource region | Selected root domain | Selected ordinary NAT2 |
| --- | --- | --- | --- |
| US | US | autonat.us | cli-nat20.autonat.us:7968 |
| CN | CN | autonat.cn | cli-nat20.autonat.cn:7968 |
| RU | RU | autonatru.com | cli-nat20.autonatru.com:7968 |
| GB and the exact EU resource memberships | EU | autonateu.com | cli-nat20.autonateu.com:7968 |
| **KR**, JP and the exact AP memberships | **AP** | **autonatap.com** | **cli-nat20.autonatap.com:7968** |
| CA and exact GLB memberships | GLB | autonatglb.com | cli-nat20.autonatglb.com:7968 |
| Empty / unknown country, including TW absent from this resource | GLB fallback | autonatglb.com | cli-nat20.autonatglb.com:7968 |

`CustomPath.getCountryZipCode:348–350` reads **Android locale country**, not IP geolocation, timezone or device location. `GetRootDomain:115–135` first matches exact `AreasDomain.json` membership, then its `default:"Y"` record. All **248** resource country memberships are transcribed exactly; the focused static check independently compared every selection with the fixed resource. An explicit empty/unknown uppercase country deliberately uses the source GLB fallback. Missing, lowercase, whitespace or malformed input is rejected. `AP`/`EU` resource IDs are rejected as country input to prevent accidental substitution of a region for a locale. No current locale or current app preferences were observed. Choosing KR is an explicit root/operator policy, not a recovered guest locale.

`m42.k:409–430` has fallback literals **80** and **9998** only when selected strings lack a colon (and partially initialized state after parsing failures). Every supported resource identity here contains a valid port. This profile rejects malformed/portless values and never promotes those fallbacks to default service ports.

## Saved state and separate operator overrides

`CustomPath:454–457` can replace the root with saved `RootDomain`. `:480–487` invokes debug/saved configuration when `DebugConfig` is true or the root contains `glbsit`. `GlobalUnitItem.p:1175–1202` loads saved NAT2 `address`; `q:1209–1236` can load NAT1 `address`. These source paths establish that saved state can differ; they do not establish what values are active in a running app. The normal profile therefore records **`saved_state="unobserved"`**.

`ReviewedSavedOverrides(root_domain=..., nat1_address=..., nat2_address=...)` is a separate typed private operator input. It permits only the six exact resource root identities, NAT1 `c2.autonat.com:40002`, the six constructed NAT2 identities, and the selected XML NAT2 identity `c2020.autonat.com:8888`. Precedence: source country -> explicit operator root -> constructed NAT2 -> explicit operator address. Endpoint strings must exactly match a reviewed identity, including canonical decimal ports. Arbitrary DNS/IP/URL, debug roots, alternate ports, portless strings and live resource paths are unsupported. There is no resource XML/JSON parser in production.

With overrides, `saved_state="operator_supplied"` reports only that input was supplied; **it does not claim recovery or completeness of saved active state**. `source_region_id` retains the original source selection. `region_id` records the effective selected root; a separate saved NAT2 address can differ from that root. No public/browser route consumes these types, and their construction establishes no actor/store/channel/credential authority. Trusted types are a caller contract, not an authentication mechanism.

## Exact build and runtime identity

| Field | Derivation |
| --- | --- |
| platform | `m42:441`: literal `AND` |
| appVersion | `GlobalUnit.t0 + "." + GlobalUnit.s0` -> **`1.18.1.20267`**. `LaunchApplication:298–304` reads package versionName/versionCode; `MainActivity:530–532` uses `base/tool/b.c:41–54`, again package versionName. Original `apktool.yml:9–11` has 20267/1.18.1. |
| appName | Original `res/values/strings.xml:2578` is **`SuperLive Plus`**. `GlobalUnit.d:1223–1235` receives selector 0, chooses PH, removes ASCII spaces, and formats `AND_M_%s_%s` -> **`AND_M_PH_SuperLivePlus`**. The localization special cases are inapplicable to this exact selected resource. |
| runtime `single_id` -> helper `model` | `m42:441` passes **`GlobalUnit.O(context)`**. `GlobalUnit:603–775` reads/writes private **`SINGLE_ID`**, removes hyphens from its contents, or generates UUID text without hyphens on missing/error paths. This is an app instance identity, **not `Build.MODEL`**. The trusted helper supplies the already resolved result; this module does not read an existing phone file, generate UUIDs, or embed any actual identity. |
| privateFilesPath | `m42:438`: API >29 selects `context.getFilesDir().getAbsolutePath()`, otherwise `GlobalUnit.t`. Trusted helper context supplies the applicable owned Android path. No static phone or Windows path is supplied by this profile. |

The earlier [connection source document](tvt-local-device-connection-source.md) uses `phoneModel` and “device model” for this final argument. That wording is superseded by the exact `GlobalUnit.O` trace above. The native/JNI field label `model` remains positional ABI/schema terminology. The input name **`single_id`** prevents a caller from mistaking it for a phone model.

## Explicit source flags and validation

`TrustedAndroidRuntime(private_files_path, single_id, source_network_type)` requires explicit trusted helper context. `GlobalUnit.h:1280–1297` yields 4=Wi-Fi, 5=Ethernet, 3=3G/4G/5G, 2=2G, 0=other/none. `m42:440` sets `networkFlag=1` **only for source type4**; all other admitted source types yield 0. It is not a universal boolean default.

| Required attempt_branch | Source history | traversalMode | disableUPnP |
| --- | --- | --- | --- |
| initial | Constructor initializes L via `r()` and N=false (`m42:145–146,173,663–665`) | 0 | false |
| retry_nat1 | `B(-2)` sets L=1 (`:180–186`); `k` uses old L then resets L (`:433–434`) | 1 | false |
| retry_disable_upnp | `B(-3)` sets N=true (`:185–186`) | 0 | true |
| retry_nat1_disable_upnp | Both updates applied before the next `k`; N remains true and current L=1 | 1 | true |

The profile represents one explicitly selected call's source state. It does not implement retries or infer errors from a failed password. Root must choose the branch from the current private attempt history; repeated `k` can reset L to 0. Other attempt histories are unsupported.

No strings are trimmed or silently truncated. Reject empty fields, NUL and malformed Unicode, then count UTF-8 bytes: NAT1 host<=127, NAT2 host<=63, platform<=31, version/app name/SINGLE_ID<=63, path<=255. Ports require canonical integers 1–65535 before the exact resource allowlist. Android path must be absolute, without backslashes, doubled separators, `.` or `..` components. These follow the selected JNI bounds documented in [the connection source](tvt-local-device-connection-source.md).

The profile contains **no serial** and cannot check cache-path composition by itself. `LocalSerialConfig.operatorReviewed` subsequently enforces `path UTF8 bytes + normalized SN bytes + 16 <=255`; 16 is that helper's conservative margin, not a recovered native suffix. Profile validity alone does not admit a device attempt. The helper separately applies its serial, queue/buffer/deadline and current authority checks. Object representations omit private runtime fields; errors omit supplied values.

## Private schema and next root invocation

`select_local_bootstrap(*, country_code, runtime, attempt_branch, saved_overrides=None)` returns an immutable factory-only `LocalBootstrapProfile`. Provenance fields are `package_name`, `apk_sha256`, `source_sha256`, `country_code`, `source_region_id`, `region_id`, `selection_reason`, `saved_state`, `attempt_branch`. `private_helper_json()` emits stable sorted compact JSON containing exactly:

```text
nat1Host:str, nat1Port:int, nat2Host:str, nat2Port:int,
networkFlag:int, traversalMode:int, disableUPnP:bool,
privateFilesPath:str, platform:str, appVersion:str, appName:str, model:str
```

There is no USER/P2P/datoken/SID, serial, credential, opaque66 result, authority grant or browser-controlled endpoint in this schema. Serialize only on the private helper channel; do not log it or add it to public diagnostics. Serialization creates a Python string and does not promise memory erasure.

After independent root review, use this exact API in the root's private host orchestration:

```python
from wso_core.tvt.local_bootstrap import TrustedAndroidRuntime, select_local_bootstrap

profile = select_local_bootstrap(
    country_code="KR",  # explicit AP resource policy; not recovered app locale
    runtime=TrustedAndroidRuntime(
        private_files_path=trusted_android_context.private_files_path,
        single_id=trusted_android_context.single_id,
        source_network_type=trusted_android_context.source_network_type,
    ),
    attempt_branch="initial",  # exactly this attempt, no implicit retry
)
private_helper_channel.send_config(profile.private_helper_json())
```

`trusted_android_context` and `private_helper_channel` designate the host's private integration boundary; this slice does not implement them. In the helper, map the twelve exact JSON fields into `LocalSerialConfig.operatorReviewed(serial, nat1Host, nat1Port, nat2Host, nat2Port, networkFlag, traversalMode, disableUPnP, privateFilesPath, platform, appVersion, appName, model, maxBufferBytes, maxQueuedEvents, maxQueuedBytes, budgetNanos)` in that order. Root supplies the separately normalized private serial and reviewed limits/current authority. `LocalSerialTransport(driver, config).discover()` is the next exact transport method; returned type/error stays private. Supplied passwords are needed later for the separate device protocol handshake and never enter the bootstrap profile. A JSON parser/host adapter is not added to the existing helper in this three-file slice.

Unobserved runtime inputs are **current owned Android path, current SINGLE_ID output, network type, saved preferences and attempt state**. All source field derivations are resolved statically; no generic phone/vendor-SDK prerequisite remains. A Windows-hosted compatible Android process may obtain these context inputs. Actual bootstrap reachability, SN discovery, device authentication/channel/live/decode and store isolation remain unexecuted.

## Frozen source identities and executed limits

| Complete source | SHA-256 |
| --- | --- |
| custom.xml | b2521a3837868b2a96605e0456eaf4a1db72e23654e9b8192564baf1ebe2dc2f |
| AreasDomain.json | e47dae84995270f644a58f34743615e9854bbafb51400e4db7e954408c968e94 |
| CustomPath.java | 0323621e2566a51b092e27a531fb637d8bd5ce6496daab28b43a406e017aea2d |
| GlobalUnitItem.java | e5e25420694341064ed4a510192e67b2682019904092daa05592c8cdc00aea68 |
| GlobalUnit.java | 0a4c202de827cb2597588c9437d88c11c9df47c0d13054148f76ff0c518acba2 |
| m42.java | dbfe5f964c1c85481ac734be44389a760cf2dbbfbc8038b7a6f8c0a086ddaa02 |
| apktool.yml | c732e5c92b79351e03df61da5905e7332531702c48f2a6518ab510073c03b79e |
| values/strings.xml | 9206e8cb5379119d102ab7c890d8797d7f5b2d13214bf9d44f49662f0d97cf60 |
| LaunchApplication.java | 13e04e70da181ec6f8309993ed1c0b4695b42c26d277f732435242b8b84597a3 |
| MainActivity.java | 483926f7d61a77cbd0597a9332c9db126df21d36b25402dae22547c499fb977e |
| base/tool/b.java | 0ab4bd2f5badb21a2f30695082a91982fba39e3bb4b67797c9a9afd5b7b1c576 |

Focused pytest checks cover selection, override uncertainty/precedence, build identity, flag histories, private serialization, native text/port/path bounds, malformed/unsupported values and endpoint prohibition. Three isolated semantic mutations produced causal failures for wrong XML NAT2, wrong Wi-Fi comparison and wrong SINGLE_ID mapping. Static verification checks the frozen readset and all 248 region selections. Ruff and strict mypy are scoped to the owned files/module. No broad suite, network, native SDK, ADB, browser, database, actual QR/password/device identity or phone-app preference read occurred; root performs private exact-value scanning and independent review separately.
