# Authenticated readonly TVT directory API

Analysis/implementation date: 2026-10-03 (Asia/Seoul). Source baseline: `b25df5268a6ff7b524232c7c62cf52bb1583061d`. These six reads connect the existing protected directory issuer and verified mTLS worker client. Device assignment, live media, native control, automatic pagination and deletion inference are outside this API.

## Fixed public operations

All routes are POST and require exactly one UUID `tenant_id` query parameter. The same-origin web proxy replaces `/api/v1/tvt/` with `/api/tvt/`.

| API route suffix under `/api/v1/tvt/directory/` | Operation ID | Request model | Browser method |
| --- | --- | --- | --- |
| `device-list` | `tvtDirectoryDeviceList` | `DeviceListRequest` | `deviceList` |
| `channel-list` | `tvtDirectoryChannelList` | `ChannelListRequest` | `channelList` |
| `device-detail` | `tvtDirectoryDeviceDetail` | `DeviceDetailRequest` | `deviceDetail` |
| `channel-detail` | `tvtDirectoryChannelDetail` | `ChannelDetailRequest` | `channelDetail` |
| `sent-shares` | `tvtDirectorySentShares` | `SentSharesRequest` | `sentShares` |
| `received-shares` | `tvtDirectoryReceivedShares` | `ReceivedSharesRequest` | `receivedShares` |

Every request includes `identity_id`, `region`, and `brand`. An optional `method` must equal its fixed underscore operation. Device and share pages default `page_num=0`, `page_size=1000`; sizes from zero through 1000 are preserved. Channel lists require 1–100 distinct `sn_list` strings. Device detail requires opaque `sn` and defaults `return_chl=false`. Channel detail requires opaque `sn` and returned native `chl_index` (0 through 2147483647). Share reads default distinct `resource_types=[]`, at most 16 signed native integers. Selectors preserve source strings; they reject whitespace edges, control/NUL/surrogate/non-BMP text and UTF8 lengths above 4096. Actor/session/role/generation/profile/key/origin/token fields are forbidden.

## Authority and budget

The directory route extends the accepted `AccountRoute` authentication boundary and uses `Current`. One original 10000ms `Budget` begins before real cookie authentication; Origin/CSRF succeeds before JSON or query validation. Exact JSON is bounded to 65536 bytes, with duplicate keys, nonfinite numbers and lexical nesting above 32 rejected. Canonical ASCII query encoding must also fit 65536 bytes. Missing shared directory client fails before SQL issuance.

Inside `require_tenant("stores:read", tenant_id)`, `DirectoryTicketIssuer` receives `token_digest` of the actual authenticated server cookie and the exact fixed request. Context exit commits issuance before RPC dispatch. The existing owned `AccountRpcClient` carries ticket, exact request, remaining deadline and request ID to its fixed `directory_*` method. The issuer and worker determine authority from current protected metadata; request identifiers/selection do not authorize operations. Response scope/method/request ID and safe positive generation are checked before publication; current identity generation is protected by worker admission and publication checks. No DB transaction spans RPC.

API configuration uses the existing four account mTLS settings only; the API does not create worker profiles, keys, admissions or worker DB providers. The once-owned client is shared across account, account flow and directory admissions; all three are cleared before one close, including failed asset startup. Existing auth/assets/account/flow behavior is retained.

## Closed directory observations

Every response is generated `DirectoryView`, with exact identity/region/brand/method/generation/request ID, `records`, operation-specific `total`, `complete=null`, and `grants_operations=false`. Device pages retain string totals. Share pages retain nonnegative native integer totals. Channel lists and details have null totals; details contain exactly one record. Empty pages do not prove removal or completeness.

Records contain `fields` and bounded `unknown_members`. A field includes exact decoded `name`, `state` (`missing`, `null`, `value`), `value`, `source_default` and `opaque_kind`. Source defaults are metadata, never substituted as observed values. Complex Java Object fields retain only object/array shape through `opaque_kind`; private contents are discarded. Nested object/list types, all expected decoded source fields, presence/default metadata, field uniqueness and source types are checked against the source projection whitelist. Unknown upstream credential keys are counted and omitted. Returned channel indices are preserved; `auth`, support, online/status and capability observations never grant control or media access.

Local response limits are 1MiB, 1000 records/items per source list, 50000 JSON nodes, lexical/model depth 32, observation depth 12 and UTF8 strings at most 4096. JavaScript integer observations and generation must be safe integers. The API OpenAPI hook documents finite array nesting (12) to avoid the pinned TypeScript generator's recursive indexed-union error; object recursion retains named schema references. Runtime validators enforce the tighter contextual source shapes.

## Proxy and typed browser API

Import `directoryClient`, `DirectoryApi`, the six exact request types, and `DirectoryView` from `apps/web/src/lib/tvt/directory-api-client.ts`. `directoryClient(csrf)` returns the six methods above. Each takes `(tenant: string, body: RequestType, signal: AbortSignal)` and returns `Promise<DirectoryView>`. Request aliases retain generated field types while allowing source defaults to be omitted. The client is constructed only during browser actions.

The proxy admits only fixed method/path/exact tenant query, requires server session/Origin/CSRF before reading the body, forwards only the session cookie to the fixed configured API origin, and uses no-store/redirect-error. Its original ten-second deadline covers request reading, fetch and bounded result reading; reader cancellation cannot extend it even when cancellation never settles. Directory-only input/response limits do not enlarge old account/flow bounds; old logout still accepts exactly zero bytes. Header/body request IDs must agree on successes and failures. UTF8 decoding, duplicate JSON keys, unsafe integers, nonfinite numbers, depth and exact schemas are checked. All error code/status pairs use the closed directory failure namespace with fixed public messages; unknown errors become `ACCOUNT_UNAVAILABLE/503`. Timeout/cancellation maps to `ACCOUNT_DEADLINE_EXCEEDED/504`. No retry, storage, logging, arbitrary URL, native handle, private token, ticket or key crosses the public boundary.

React callers should keep transient-failure snapshots, show safe errors and refresh only on explicit user action. Reset context and abort outstanding reads when tenant/identity selection changes; do not derive source grants, infer deletion, traverse pages automatically or retain credentials. UI implementation and actual browser acceptance are separate work.

## Evidence and limits

Scoped API/proxy causal RED-to-GREEN, affected old route/lifecycle checks, typecheck, lint, mypy, Ruff and deterministic export receipts are recorded in `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-api-report.md`. Synthetic routing and loopback fixtures do not establish live TVT acceptance. Protected composition remains subject to root approval of exact worker/RPC source hashes. APK/API parity remains MATCHED=0 and release readiness is false; no live vendor, browser, native or device acceptance is claimed.
