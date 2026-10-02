# Private TVT prelogin account-flow adapter

Implementation date: **2026-10-02, Asia/Seoul**. The implementation follows the independently accepted [APK-derived account-flow reference](tvt-account-flows-source.md), SuperLive Plus 1.18.1. Its accepted source hash is `ce91cf86e9005efd419715e294ed8fa96da569514ee018967912d0af9ea14056`. Static source acceptance and synthetic host verification do not establish APK or TVT server interoperability. **MATCHED = 0; release_ready = false.**

`packages/core/src/wso_core/tvt/account_flows.py` implements a private `PreloginAccountFlow`. It composes the existing `AccountClient` and `ProcessAccountTransport`: verified HTTPS with normal CA and hostname checks, an explicitly allowlisted origin, bounded JSON, one inflight request, a whole-operation deadline, owned cancellation/settlement and permanent process quarantine. Each request uses one real isolated child. Business 404 retains the existing pending DC candidate and causes no retry.

This slice implements serializers and private flow state. Protected worker service admission, RPC, public API projections, React/Tailwind screens, browser flow ownership and end-to-end readback are later slices. An equal Python scope does not authorize an actor. The protected service must admit the current T03 actor before constructing or calling a flow, bind its opaque browser handle to that actor, and close the flow when its owner leaves.

## Operations and results

| Operation | Implemented request and response |
| --- | --- |
| `exists` | Phone mode 1 POSTs `/user/info/phone/is-exist` with `mobile`; email mode 2 POSTs `/user/info/email/is-exist` with `email`. Optional configured `customerAppId`; generic 1.0 basic without token. HTTP 2xx/business 200 requires an explicitly present boolean `isExist`. False is a valid result; missing, null and wrong types are fixed protocol errors. |
| `image` | POST `/user/img-code/get`; optional configured app ID. Fetch image data is `imgCodeImgData`. An admitted runtime RSA key may arrive in the same response. |
| `issue_code` | POST `/user/sms-code/no-token/get` with `loginName`, integer `loginType`, registration purpose 15 or recovery purpose 12, and `lang`. Nonempty image text emits paired `idCode` from private flow state and `imgCode`; empty image text omits both. App ID is conditional; the configured default-domain MD5 mark is conditional on a nonempty domain. |
| `register` | POST `/user/register`, token-free 1.1 basic. `sign` is SHA-512 of lowercase MD5(password), a separator and the dynamic code. `password` is one RSA PKCS#1 v1.5 encryption of the 32 ASCII MD5 hex bytes, using ordinary unwrapped Base64. The data always includes `loginName`, `loginType`, `lang`, `customerMark` (including MD5 of an empty domain) and locale `country`; nonempty terminal/app fields are conditional. No clear dynamic/image code, UUID or token data is emitted. |
| `recover` | POST `/user/info/password/reset`, token-free and sign-free 1.1 basic. Data includes `loginName`, `dynamicCode`, plaintext lowercase MD5 hex `newPassword` and `lang`. App ID and nonempty-domain mark are conditional. No RSA, AES, UUID or old password is used. |

Phone binding preserves the APK account format `countryCode + "+" + localNumber`; locale country remains a separate registration field. Inputs are bounded and reject NUL, surrogates and supplementary characters, whose JNI encoding is unresolved. The adapter requires the source-native nonempty account/password/code/language and supported web modes. Exact decompiled UI password/email validator parity is still pending; these checks do not claim to implement the unresolved `yg3` edge cases.

`FlowResult` separates `EXISTENCE`, `IMAGE_AVAILABLE`, `CODE_SENT`, `IMAGE_REQUIRED`, `IMAGE_REJECTED`, `COMPLETE`, `FAILED` and `UNKNOWN_OUTCOME`. Registration business 1007 and 1005 with object data become distinct image states; recovery converts only 1007. Non-2xx or missing-data error replies remain failures. Dynamic image data uses `imgData`, and its original integer business code is preserved. True 200 returns `CODE_SENT` without a UI challenge while privately retaining an observed native image ID.

The private dynamic decoder admits these challenge codes only for this operation. Existing login/challenge/profile/renew/logout and `AccountResult.ok` keep their original HTTP 2xx plus business-200 vocabulary. A challenge result is not account creation.

Rejected dynamic replies also retain their already bounded private raw response bytes, including recovery 1005, absent/non-object challenge data, other business codes, non-2xx and DC candidates. A private evidence hook runs only after the existing bounded envelope parser; it does not decode or admit rejected keys, change failure classification, or expose raw data publicly. Malformed envelopes and over-cap bodies retain the original closed failure behavior and provide no raw evidence.

## Runtime key and local flow policy

The only key ingress is `data.publicKey` in this client's own admitted image or dynamic response. The member must be bounded canonical standard Base64 of DER SubjectPublicKeyInfo containing an RSA public key. Complete PEM, PKCS#1 public keys, private keys, non-RSA keys, trailing bytes and malformed Base64 are rejected. There is no caller/browser replacement-key input or invented key endpoint. Missing or malformed key state blocks registration before its dispatch.

The private instance binds actor, tenant, region, brand, account, mode and purpose. Keys and image IDs are never shared across instances. A scope mismatch clears state and invalidates an inflight response; malformed replacement data also clears state. Close cancels active work and rejects late success. Expiry is checked at admission, before dispatch and after completion; expired state is cleared when observed. Failed or uncertain operations clear admitted state where reuse cannot be proved.

The configurable `lifetime_seconds` default is **300 seconds**, an explicit local policy rather than server TTL. `code_interval_seconds` defaults to **0** (disabled); a protected service can configure a local issuance interval independently of the source UI's resend countdown and its own aggregate rate limits. Neither setting asserts server expiry, code consumption or maximum attempts.

Final submission is consumed locally once serialization is admitted, including definite upstream rejection. A subsequent submission requires a new flow and a deliberate caller decision. Any failure after code issuance or final submission may have begun returns `UNKNOWN_OUTCOME`, preserves available status evidence, clears state and prohibits replay by that instance. This conservative policy also consumes a serialized submission that exhausts its remaining budget before child dispatch; an unknown result does not assert that a remote write occurred. Transport quarantine retains exact unsettled boundary ownership and closes admission permanently.

Successful registration/recovery produces safe completion with `return_to_login = true`. Generic upstream token members are ignored; no TVT identity, USER/P2P token, auto-login or web session is minted. Passwords and the APK's temporary MD5(code) state are not persisted. Result bodies, keys, image payloads and credentials remain private and are omitted from representations and fixed error messages.

## Verification and limits

Focused tests cover exact source envelopes and digest vectors (including non-NUL BMP text), independent synthetic RSA decryption, strict existence booleans, operation-specific image states, missing/malformed/foreign/expired keys, scope/inflight/cancellation/budget/quarantine, duplicate and unknown-outcome refusal, and unchanged existing operation semantics.

An owned localhost sequence uses the concrete process transport and normal certificate/hostname verification with a narrowly injected test CA. It exercises email existence, image acquisition, a registration-purpose dynamic challenge carrying the sole runtime key, registration, and a separate phone recovery-purpose code/reset flow. All six actual children, channels, worker threads, TLS servers and test key/certificate files are cleaned. This is synthetic host proof; it is not Android/JNI execution, a TVT network exchange, a real account write or a usable-account readback.

The full implementation report, focused native exit logs, source preimages, frozen candidate files, complete owned diff and manifest are held privately under `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W06-prelogin-flow-adapter-*`. Independent implementation review and publication remain separate from this author report. W06 remains incomplete until the protected service/RPC/API/UI slices and their separately authorized acceptance are complete.

Fix1 preserves private rejected-response evidence and was checked with focused parser/state tests and existing client regressions. The original actual TLS sequence and W05 browser fixture runs retain their recorded original source checkpoints; neither was rerun for Fix1, and they are not acceptance of the revised source.
