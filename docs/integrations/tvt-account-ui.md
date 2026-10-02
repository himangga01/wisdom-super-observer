# TVT account browser contract

Analysis and implementation date: 2026-10-02. The account page implements the approved W05 frontend scope using the published account API and the 2026-09-30 dashboard reference. Source and verification evidence are recorded in `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W05-account-frontend-report.md`.

## Startup and authorization

The deployment must explicitly register `/tvt/account` in the trusted `StartupProfile.local_routes`. Its only valid menu tuple is `local-account`, `Account`, `/tvt/account`. `/tvt/settings` remains independently registered. Both lists reject duplicates and contain at most two local entries. An absent registration hides account navigation and denies direct account links. Registration does not advertise device or native capabilities.

Account forms require the current accepted startup consent. Region and brand come from the authenticated tenant bootstrap; no browser region or backend URL picker exists. Identity options come only from the bootstrap account list and must match that selected brand and region. Navigation preserves the tenant query. Web authorization remains authoritative on the API.

## Exact same-origin proxy operations

| Backend path relative to `/api/v1/tvt` | Method | Input |
| --- | --- | --- |
| `identities/login` | POST | Published `AccountLogin` |
| `identities/challenges/image` | POST | Published `AccountSelection` |
| `identities/challenges/image/check` | POST | Published `ImageCheckRequest` |
| `identities/{UUID}/me` | GET | No body |
| `identities/{UUID}/refresh` | POST | USER, confirmed expected generation, manual reason |
| `identities/{UUID}/logout` | POST | No body |

The browser maps generated OpenAPI paths onto `/api/tvt`. Only one valid `tenant_id` query is allowed; extra parameters, duplicate selectors, trailing/extra segments, escaped path characters, aliases and invalid UUIDs are rejected. POST needs the configured exact Origin and matching nonempty CSRF cookie/header. Session presence and CSRF checks precede JSON parsing. The API checks real web session validity and tenant/identity authority.

Logout remains strictly body-free. The generated client sends an absent body and no Content-Type. Next's Node adapter may represent an actual zero-length HTTP POST as a non-null stream; the proxy accepts it only after reading to completion with a zero-byte cap and the original overall deadline. Any declared positive length or actual positive byte, including whitespace or `{}`, is rejected. An unfinished or cancelled zero-byte stream uses the existing safe timeout/cancel result and never dispatches logout upstream.

Account JSON requests have a 32,768 byte cap; existing startup requests keep their 4,096 byte cap. Both declared Content-Length and actual streamed bytes are checked. Image success envelopes have a 131,072 byte cap so the published maximum 90,000 character Base64 field plus bounded envelope fits. Other responses have a 65,536 byte cap. A single 10 second budget covers parsing, backend fetch and streamed read. Request cancellation propagates; there are no redirects or automatic retries. Every response sets private/no-store, Vary Cookie and a request ID header. Tokens, provider strings, cookies and remote URLs are never projected.

Known account code/status pairs map to fixed Korean messages. Unknown combinations fail closed to 503 ACCOUNT_UNAVAILABLE. Web unauthenticated/principal_not_provisioned/csrf_rejected remain distinct from TVT AUTH_REQUIRED/TOKEN_EXPIRED. ACCOUNT_DENIED is published at both 404 and 409; 409 and unknown renewal outcomes trigger authoritative reads without repeating renewal. A subordinate 401/403 triggers bootstrap authorization recheck before deciding that the WSO session is lost. Unknown write results explicitly state that automatic resubmission does not occur.

## Forms, challenges and local state

Stream cleanup propagates cancellation without awaiting a stream's cancellation hook, which can remain unresolved. Cleanup creates no timer or separate budget. Positive body bytes are still refused before account writes; stalled reads and request aborts use the original overall deadline and safe cancellation result.

Email/phone/password/image code/second code validation matches the published APK supported input rules: phone optionally starts with `+` followed by 4–32 digits, email has no whitespace, account length ≤512, password 1–4096, verification codes 1–256, and NUL, non-BMP characters and isolated surrogates are refused. Optional second verification code has an accessible input. Trusted region is displayed.

An image response is normalized Base64 with a closed PNG/JPEG media enum. The browser validates the corresponding magic/ending bytes, canonical Base64 and at most 67,500 decoded bytes (the 90,000 Base64 field bound), then creates an owned Blob URL. The backend's current projection additionally caps images at 65,536 decoded bytes. Images have alt text and keyboard accessible request/check/cancel controls. A challenge expires after 120 seconds and is locally consumed before either login or standalone check dispatch. After consumption or expiry, later login is blocked until a fresh challenge is acquired. A standalone check clears the ID/code/image and explains that login requires a fresh challenge. URLs are revoked on consumption, replacement, expiry, cancellation and unmount.

Secrets live only in form inputs, temporary FormData and the active request. Password and verification inputs clear on submission settlement, mode change, successful login, cancellation, actor/tenant/identity/consent/profile scope change, authorization loss and unmount. Nothing persists in storage, cookie values, URLs, logs, analytics, TanStack mutation variables or query cache. Account profile PII stays in a scoped component's transient memory, with no generic profile cache.

The non-secret requirement to acquire a fresh image stays in the current session boundary while a temporary same-scope authority check unmounts the login form. Consumed or expired image checks, including unknown outcomes, therefore cannot enable challenge-free login when that form returns. Credentials, challenge IDs/codes and Blob URLs still clear during the transition. A newly acquired challenge clears the requirement; changing the selected identity or the keyed actor/tenant/profile/brand/region/consent/roster scope creates an isolated requirement state. No challenge data is retained by the boundary or query cache.

The session boundary keys actor, tenant, deployment profile, brand, region, consent revision/status and authoritative identity roster. It aborts tracked requests on scope change, identity selection, page leave and WSO logout. Epoch checks and per-form controllers reject late completion even if a transport ignores cancellation. Profile state renders fields as plain text. Account type is shown exactly as returned within a finite signed 32 bit bound; unknown values confer no permissions. Avatar availability is text only and avatar_url must be null.

Manual refresh sends USER and the generation from the confirmed profile, then rereads the profile. It never submits P2P/DEVICE renewal. Logout closes only the selected TVT identity, accepts authoritative CLOSED even when upstream outcome is unknown/not_attempted, clears that profile and rereads bootstrap. It does not invoke WSO/OIDC logout.

## Actual verification limits

Fix1 focused regressions cover cancellation hooks that never settle and delayed same-scope challenge checks. The earlier R59 desktop/mobile actual browser pass is historical evidence for its frozen source, not executed browser proof for Fix1. Current Fix1 source and command results are recorded separately in `W05-account-frontend-fix1-report.md` alongside the original immutable packets.

Focused component/proxy tests use synthetic public interfaces and prove local behavior, cancellation, scoping, validation and safe projections. They do not establish PostgreSQL/RPC/provider/browser or APK parity.

`tests/tvt_parity/e2e/login.spec.ts` is gated by `WSO_TVT_ACCOUNT_BROWSER_STATE_FILE`. It requires the separately owned actual PG → API → RPC → synthetic HTTPS upstream fixture, fresh private WSO cookies and `proofKind: actual-pg-rpc-https`. It checks actual anonymous 401, CSRF 403 and invalid input 422; consumes a check challenge, requests a new image for login, exercises profile/USER refresh/TVT logout and proves WSO remains authorized on `/stores`. It checks keyboard activation, image decode, storage and overflow at the configured desktop/mobile sizes without response mocking. The fixture must disable traces, automatic screenshots and video. Only a synthetic profile screenshot is explicitly captured for visual QA after all account/password/code inputs and challenge images are confirmed cleared. Browser execution and original APK/live OAuth/device/provider acceptance have separate evidence gates; absence of the fixture is reported as pending, never as executed acceptance.
