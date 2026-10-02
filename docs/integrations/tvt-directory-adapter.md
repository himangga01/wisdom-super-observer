# Private TVT readonly directory adapter

Implemented and verified on 2026-10-02 (Asia/Seoul), against the source-approved SuperLive Plus 1.18.1 packet and its four reviewed precision corrections. APK SHA-256: `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. **MATCHED=0; release_ready=false.** The actual HTTPS acceptance here is a synthetic local peer, with certificate and hostname verification; it is not APK/vendor runtime equivalence.

## Implemented private interface

`wso_core.tvt.directory_client.DirectoryClient` exposes six readonly methods plus `close()`. Trusted composition supplies an `AccountScope`, exact managed `TvtIdentityRef`, configured `OriginPolicy` and allowlisted HTTPS origin. Each operation requires that identity, a matching `PrivateToken` of kind USER, a total `deadline_ms` (1–60000) and a bounded correlation ID. Scope equality is consistency, not actor/store authorization or proof that a credential is current in a vault.

| Method | Inputs beyond identity/token | Fixed POST path | Result |
| --- | --- | --- | --- |
| `device_list` | `page_num:int`, `page_size:int` | `/resource/device/list` | `AccountResult[DevicePage]` |
| `channel_list` | nonempty distinct `sn_list:list[str]` | `/resource/channel/list` | `AccountResult[ChannelDirectory]` |
| `device_detail` | `sn:str`, `return_chl:bool` | `/resource/device/detail` | `AccountResult[ObjectObservation]` |
| `channel_detail` | `sn:str`, `chl_index:int` | `/resource/channel/detail` | `AccountResult[ObjectObservation]` |
| `sent_shares` | page inputs, `resource_types:list[int]` | `/resource/channel/share/to-other/list` | `AccountResult[SharePage]` |
| `received_shares` | page inputs, `resource_types:list[int]` | `/resource/channel/share/from-other/list` | `AccountResult[SharePage]` |

`DirectoryProtocol` composes the existing `AccountProtocol` basic/request/task-ID helpers. The request envelope uses basic version `1.0`, decimal task string, Unix seconds, nonce and the USER token in `basic.token`. Empty resource-type input omits the wire member. No browser-selectable endpoint, arbitrary operation/path, bearer header, signing proof, device credential or native camera/media handle is exposed.

`DirectoryClient` composes `AccountClient` and calls its existing `_postlogin`/`_run` extension seams. That implementation continues to own the only `ProcessAccountTransport` boundary: original total deadline, one inflight operation, verified TLS, response byte bounds, close/cancel, late-result rejection, exact child settlement and permanent quarantine after unproved settlement. There is no second process or transport implementation and no automatic redirect adoption, retry or pagination followup. A validated business-404 DC candidate stays pending; a later repeated hint is a rejection. HTTP errors and business codes, including the decoded token-invalid codes, remain failures rather than empty data. Vault invalidation/session recovery is a caller obligation in the next worker integration.

## Explicit local bounds

`DirectoryBounds` is frozen and validates each setting. A supplied `DirectoryProtocol` carries its own bounds; otherwise the client constructs a protocol from the supplied `bounds`. Defaults are configurable downward only. These ceilings are local web policy, **not server maxima**:

| Setting | Default/local ceiling |
| --- | --- |
| page size | 1000 |
| SN selectors | 100 |
| resource-type selectors | 16 |
| top-level records/devices | 1000 |
| any nested list | 1000 |
| any UTF-8 string/key | 4096 bytes |
| response JSON nesting | 16 (root depth zero) |
| response JSON nodes, including keys | 10000 |
| client response body | 65536 bytes by default; existing account configurable ceiling 1048576 |

Page number/size zero is admitted, as in native source; negatives and bool-as-int are rejected. Page number is bounded by the signed native integer maximum. Channel index is a nonnegative signed native integer under local policy, not a decoded server enum. Resource-type integers retain signed native range and unknown values; duplicates are rejected. Selectors remain opaque BMP strings, with no SN-to-URL interpretation; local policy rejects empty values, surrounding whitespace, control/NUL characters, malformed surrogate/non-BMP inputs and overbound strings. Inputs fail before process creation. Returned channel SNs must be requested and distinct; explicit detail SN/index mismatches and duplicate observed indices in an account channel row fail parsing. Missing detail selectors remain unknown rather than being filled from the request.

## Source observations and safe projection

All decoders require HTTP 2xx, business 200 and a correct root shape. The five object consumers permit `array` fallback when `data` is absent, null or the native empty string; the account channel array reads `data` only. Stringified JSON, malformed/null payloads, missing/invalid page totals or records, false primitive values and null list elements do not become empty success. A valid empty records array is an observation. Device total stays a string, while share totals are nonnegative native integers under local policy. `complete` is always unknown (`None`); the APK `(0,1000)` default proves neither complete inventory nor pagination termination.

Frozen `ObjectObservation`/`FieldObservation` values retain missing, explicit null and observed value states separately. `field(name)` exposes the private source observation; `project()` builds fresh containers containing only the explicitly decoded nonsecret fields. The device-record `maxShareNum` metadata records the Java string initializer `"0"` independently of wire presence. An omitted member stays missing; explicit null and empty string are distinct. The ru0 UI fallback to five is not applied and is never share authority. Device-record `type` likewise records its Java initializer separately.

Schemas preserve returned SN/share IDs/channel indices and ordering, device/channel names, model/firmware and reported detail capability fields, including nested stream/disk/platform observations. Unknown online/status/resource/auth values are preserved without interpretation. Java Object metadata `userId`/`checkTime` retains safe scalar values; a structured value retains presence and object/array shape only, and its arbitrary contents are discarded from the projection. Unknown extra members, including credential names, are bounded privately before being counted and discarded. The result contains no raw response body or generic wire JSON passthrough.

Sent and received shares use independent schemas. Received observations include `ownerId`, `devRemark`, `ownerRemark`, `devType` and never inherit sent-only `recipientId`, `validData` or `shardIds`. Child grouping, selection and computed support values are omitted. Each row's auth list remains independent, including null/missing and unknown verbs; sibling permissions are never merged. All support/auth/status fields are observations. No result grants PTZ, Talk, cloud/media, online state, owner role or any operation. A private IP is metadata and cannot become a worker destination.

## Evidence and executed limits

The source evidence, concrete serializers and corrected Java consumers are documented in [TVT device directory source contracts](tvt-device-directory-source.md). Original frozen source/review/history remain byte-identical in ignored custody. The full adapter report, READY, seven-file frozen/source manifests and full diff are under `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-adapter-*`; command/output custody is in `.superpowers/verification/directory-adapter/`.

Executed checks: causal RED for the missing six serializers/parsers/client; source-shape and selector/fallback RED cases; 105 adapter tests GREEN; eight selected old account serializer/transport regressions; focused Ruff/format and strict mypy. The actual local HTTPS sequence executes each fixed readonly path once through six real contained child processes, verifying certificate/hostname trust, exact ordinary envelope/data/header and child/I/O settlement. Additional bounded tests cover strict malformed shapes, response fallback distinctions, independent received-share fields, safe opaque metadata, scope/token rejection, HTTP/business failure, pending DC, one inflight call, late success after close and inherited quarantine mapping. No new full account/native/foundation/browser suite was run for this slice.

No managed database, vault ticket, RPC/API/UI, generated contract, vendor origin, real account/device, native load or handset acceptance was exercised. Current credential freshness, per-store grants, revocation during a real directory request, server pagination, permission enforcement and ARM32/runtime equivalence remain unproved. The next independent worker task must supply W02 ticket/vault admission, authorize actor/tenant/identity/store/channel scope, recheck current generation before publishing, and add separately reviewed RPC/API and persistence projections. W08 remains the camera/media adapter owner. This prerequisite does not complete W07.
