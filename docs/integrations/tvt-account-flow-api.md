# Authenticated registration and recovery API

Implementation date: 2026-10-02. W06 starts from the root-supplied published
baseline `1e9cd000732b7a424a9f59e3722ba6c4d2b3a7d7`. APK source evidence and
protected authority are documented in [tvt-account-flows-source.md](tvt-account-flows-source.md)
and [tvt-account-flow-service.md](tvt-account-flow-service.md).

## Public operations

All operations are POST under `/api/v1/tvt/account-flows`, with a required
`tenant_id` UUID query selector. These selectors never authorize a request.

| Suffix | Operation ID | Request model |
| --- | --- | --- |
| `start` | `tvtAccountFlowStart` | `AccountFlowStart` |
| `state` | `tvtAccountFlowState` | `AccountFlowReference` |
| `existence` | `tvtAccountFlowExistence` | `AccountFlowReference` |
| `image` | `tvtAccountFlowImage` | `AccountFlowReference` |
| `issue-code` | `tvtAccountFlowIssueCode` | `AccountDynamicCodeRequest` |
| `register` | `tvtAccountFlowRegister` | `AccountRegistrationSubmit` |
| `recover` | `tvtAccountFlowRecover` | `AccountRecoverySubmit` |
| `cancel` | `tvtAccountFlowCancel` | `AccountFlowCancel` |

Every success is the exact base `AccountFlowView`, including its request ID.
Registration and recovery are purpose-specific inputs. Region, brand, purpose,
flow UUID, and the local image challenge UUID/generation are selectors. No
browser input supplies an actor, role, session digest, admission ticket,
worker configuration, native idCode, RSA key, or saved TVT token.

`AccountRoute` starts one original 10000 ms budget and performs T03 opaque
session authentication, Origin and CSRF verification before FastAPI body/query
validation. Missing worker state returns 503 after admission and before SQL.
Inside the existing `require_tenant('stores:read', ...)` transaction, the API
computes `token_digest` from the actual authenticated server cookie and invokes
`FlowTicketIssuer(scope.session, budget.remaining).issue(digest, operation, body)`.
The tenant context commits before the fixed RPC method runs. The remaining
original budget and server request ID follow that method, and the API checks
the budget and exact public response scope before publishing it.

The API uses the same owned `AccountRpcClient` as existing account routes.
Creation still reads only the four mTLS client settings. It constructs no
worker admission, key provider, profile, native executor, or worker database.
Both app-state admissions are cleared before the once-owned client closes,
including startup failure. Flow failure codes/statuses use the reviewed closed
RPC vocabulary; old account failures delegate to their original handler.
Existing account logout, startup and asset/auth cleanup behavior is retained.

## Web proxy and typed client

The existing `/api/tvt/[...path]` proxy adds only eight closed flow paths. It
checks method, path and one valid tenant query; then session, Origin and CSRF
before reading the body. Input is strict JSON bounded to 32768 bytes. The
original ten-second budget covers request read, backend dispatch and response
read, including aborts and nonsettling stream cancellation hooks. No retry,
redirect, cache, body logging or native credential persistence is introduced.
Only `image` and `issue-code` successful flow responses use the existing 131072
byte image response bound. Other flow frames remain bounded to 65536 bytes.

`flow-api-client.ts` exports `accountFlowClient(csrf)` and `AccountFlowApi`, with
methods `start`, `state`, `existence`, `image`, `issueCode`, `register`, `recover`,
and `cancel`. Each takes `(tenant, typedBody, signal)` and returns the generated
`AccountFlowView`. Its types come from the generated OpenAPI contract. The
closed Zod schemas additionally enforce Python wire constraints and public
state relationships: strict false existence, bounded canonical Base64 JPEG/PNG
projection, COMPLETE returning to login, and no automatic retry. Correlation
IDs follow the Python bounded grammar; header/body IDs must agree when the
backend supplies the header. Region, brand, purpose and referenced flow ID
must agree with the request. Errors display fixed safe messages.

Email start must omit `country_code` entirely; explicit null is invalid. Phone
start requires digits for country code and local number. Passwords/codes allow
bounded native BMP input and are sent only in the protected request. The client
adds no browser storage. The 120-second resend countdown comes from the reviewed
service's local UI policy, and provides no vendor code expiry guarantee.

## Executed verification and limits

Focused API tests prove auth/CSRF before parsing, absent worker before issuance,
typed validation, purpose/selection/request-ID consistency, one original budget,
committed issuance before RPC, fixed error envelopes and shared-client teardown.
These mocked boundaries prove routing behavior, never PostgreSQL authority.
Focused web tests prove the eight routes, bounded input/result models, safe
failures, typed request secrecy and deadline/cancellation behavior; existing
account/startup proxy and lifespan regressions remain part of the scoped checks.

After root explicitly accepted the protected core and RPC hashes, one opt-in
end-to-end case used actual restricted PostgreSQL roles, T03 session store,
tenant authorization, real SQL issuer, verified mTLS client/server, protected
worker and actual verified HTTPS child transport against a loopback synthetic
peer. It proved start, false existence, image challenge, dynamic code,
registration/recovery completion, cancel, expiry projection and session revoke
denial without an upstream retry. The first attempt reached expiry but used an
incorrect test clock: shortening only SQL expiry left the live worker's
immutable monotonic deadline unchanged. The same case passed after synchronizing
both test clocks. This expiry check is controlled elapsed-time simulation, not
a five-minute wall-clock soak. No production expiry or authority code changed.

The guarded fixture retargeted all nine roles, created its own named database,
verified name/OID/owner/comment before dropping it, and preserved the source's
36 table row/owner snapshots, OID 16384, owner `postgres`, revision
`0003a_assets`. All three attempt databases were dropped. The final repeat also
proved worker shutdown cleared its binding key/config and server drainage before
SQL admission disposal. Private URL/password values
are excluded from captured evidence using eighteen-value sanitization.

Activation uses `WSO_TEST_W06_API_ACCEPTANCE=1` plus the existing guarded
`WSO_TEST_W06_FLOW_ACCEPTANCE` and parent SHA activation. The API fixture checks
the exact three root-approved protected source hashes before opening a database.
It defaults to skip. This opt-in case creates only synthetic session/policy/key
fixtures inside the owned environment. Production setup is not provided.

React Register/Recover forms are a separate later change. APK password complexity,
live vendor behavior and handset comparison remain unverified. `MATCHED=0` and
`release_ready=false`; synthetic local acceptance does not establish APK parity.
