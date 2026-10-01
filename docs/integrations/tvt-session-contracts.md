# TVT account sessions and token boundary

Analysis/implementation date: 2026-10-02. Source baseline supplied to W05: `3d982b0f94311324aa79a5ca83580d695a34572a`; the independently reviewed preceding batch was subsequently published as `ea5d94e9c49fee8f86e195a1db0a52330e094aaa`. W05 source/evidence is separate from either commit's acceptance. This document describes implemented development contracts, not successful TVT service or APK runtime acceptance. MATCHED remains 0 and release_ready remains false.

## Public endpoints

Every endpoint requires the existing T03 WSO session. Every POST checks both Origin and CSRF before parsing its body. Requests select a tenant using `tenant_id`; protected SQL derives the actor from consumed PID/XID context and current membership. STAFF, MANAGER and OWNER use the existing `account.login` admission; OWNER has no implicit access to another user's TVT account.

| Method and resource beneath `/api/v1/tvt/identities` | Request | Response |
| --- | --- | --- |
| POST `/login` | `AccountLogin`: trusted region/brand labels, email/phone mode, account, secret, optional local challenge/image code and second code | `AccountIdentity`: local identity UUID, labels, local state and generation |
| POST `/challenges/image` | `AccountSelection` | `ImageChallengeView`: actor-bound local UUID, bounded image MIME/Base64 and local 120-second reference lifetime |
| POST `/challenges/image/check` | `ImageCheckRequest` | `ImageCheckView`; consumes the reference once |
| GET `/{identity_id}/me` | Local identity UUID | `AccountProfileView` with an allowlisted current upstream profile |
| POST `/{identity_id}/refresh` | `AccountRefresh`: kind, expected generation, bounded reason enum | `AccountIdentity`; only the decoded USER renewal is executable |
| POST `/{identity_id}/logout` | Local identity UUID | `AccountLogoutView`: CLOSED and `confirmed`, `unknown`, or `not_attempted` upstream outcome |

Responses use generated OpenAPI/TypeScript contracts, the canonical nested error envelope, request IDs, no-store and Vary: Cookie. No upstream token, user/installer ID, worker ticket, saved-secret URL, private image path, or private device address is public. `SecretStr` inputs do not reveal values through repr/model JSON. Validation responses contain no rejected input.

`READY` records a subordinate local account connection and a bounded authority observation. It is not the APK's `isLogin` preference or proof of perpetual upstream validity. Logout preserves the WSO session. The API commits protected local revocation even with no configured worker or an uncertain remote reply.

## APK source and transformations

The existing `AccountClient` composes the decoded JSON protocol and process-contained HTTPS transport. The new executor invokes that client for `/user/login`, `/user/img-code/get`, `/user/img-code/check`, `/user/info/get`, `/user/token/renewal`, and `/user/logout`. It does not invent SDK documentation, refresh tokens, token expiry, DC adoption, or native method invocations. Trusted server configuration selects exactly one region/brand origin and keeps DC changes pending.

Private Java source root: `C:/wso-private/superliveplus/1.18.1-2026-09-27/jadx-full/sources`. Evidence hashes are retained in the ignored W05 packet.

- `defpackage/sc3.java:178-184,195-202`: password sign-in uses login mode 1; both phone/email inputs use the bounded password login operation. A second check code is an independent existing field. Other account establishment/recovery/SMS operations remain W06 work.
- `com/tvt/user/model/bean/UserInfoBeanNew.java:19-43` and getters: account type 0 means none, 1 user, and 4 installer. The allowlist exposes type, userName, nickName, email, mobile, address and noPassword. Unknown integer types remain unknown; they grant no installer capability. Private user/installer identifiers are omitted.
- `UserFragment.java:831,1044` and `UserManagerActivity.java:952,1062`: avatar `image` is appended to BaseImageHttpClient. This is a private server-relative path, not a browser-safe absolute URL. The current projection returns availability and a null public URL; a vetted authenticated avatar byte route remains separate work. No remote fetch is guessed.
- `defpackage/a62.java:287`, `ws.java:100`, `h62.java:41-44`, `rl1.a/j`, and `f11.a`: image challenge data is Base64, with the exact optional `data:image/jpg;base64,` prefix. The projection decodes, bounds to 64 KiB, permits only JPEG/PNG signatures and emits normalized Base64 with an inert image MIME. Arbitrary URLs/SVG are rejected. The upstream image identifier is encrypted in the existing private secret table and exposed only as a local once-only challenge UUID.

## Storage and admission

Migration 0007 adds five metadata tables owned by `wso_account_owner`, a NOLOGIN/NOBYPASSRLS role without role memberships. All new tables use FORCE RLS, explicit owner/migrator policies, scoped foreign keys and server timestamps. Runtime roles receive no direct private-table access. Security-definer functions have fixed `pg_catalog` search paths and no PUBLIC execution rights.

T04 `connection_secrets` has `connection_id` as its primary key and one current `version_id`. Consequently USER uses the real identity connection, while P2P and future DEVICE kinds have distinct auxiliary connection/version references. There is exactly one TVT identity row. Every auxiliary connection enters both the W05 private storage registry and the 0005 sticky domain registry atomically. Auxiliary rows are hidden from generic app connection listings and refused by the generic mutator. No new encrypted/plaintext byte store exists; the existing AES-GCM cipher and its tenant/connection/version AAD are reused.

The W05 API explicitly issues typed, single-use, 30-second worker tickets through `CredentialProvider.with_account_ticket`. Scope objects and caller UUIDs are selectors, never authority. Redemption, callback use and publication recheck current membership, actor role, identity ownership/state, account grants, observations, connection/token versions and generation. Missing kind/session metadata denies access. USER/P2P/DEVICE references are independent; no P2P or DEVICE bytes are admitted through the USER operation.

Existing generic OWNER/job paths still deny mapped connections. W05-managed connections additionally reject the preexisting untyped domain issuer and every generic redeem/use validation, including capabilities issued before W05 adoption. Preexisting W02-only domain identities and never-mapped legacy connections retain their behavior. The original function bodies are backed up privately and restored exactly on downgrade; original owners and ACLs are retained. Existing connection rows, ciphertext and sticky mappings are not deleted by migration downgrade. New W05 metadata tables are removed by downgrade, so downgrade is not a running-session continuation mechanism.

## Renewal, uncertainty and deadlines

USER renewal calls only the decoded `/user/token/renewal` operation. A PostgreSQL session advisory lock serializes independent worker processes. A row-locked generation check and durable attempt UUID/INFLIGHT witness are committed before the callback. Publication must match the admitted generation and current witness. An interrupted owner leaves INFLIGHT; a successor returns `RENEWAL_OUTCOME_UNKNOWN` and cannot repeat the upstream action or publish a replacement. Re-login is required to establish a new account connection after this uncertainty; there is no automatic retry.

A separate renewal sequence deduplicates concurrent successful observations that contain no replacement USER token. Such a reply does not invent rotation, generation increments, refresh tokens, or expiry. P2P metadata and generation are unaffected by USER renewal. P2P and DEVICE renewal return `CAPABILITY_UNSUPPORTED` pending their actual native adapter; they never call USER renewal.

Successful account replies establish only account-read observations with a local five-minute authority TTL. This TTL is independent of unknown upstream token expiry. Device/media/control observations remain absent. Logout revokes only the affected connection kinds and existing dependent credential handles, leases and account tickets. Future media leases are owned by their later service.

The API starts a ten-second budget before authentication and forwards only remaining milliseconds. The executor accepts at most twenty seconds, shares its remaining budget across SQL/callback/publication, checks before commit, and retains uncertainty when renewal cannot publish. Nested worker scopes compose their local limit with the captured outer transport cancellation/deadline callback; they cannot reset or replace that authority. SQL statements receive the remaining timeout; locks have a three-second cap. Mandatory local logout cleanup explicitly detaches from the expired transport budget and has its own bounded SQL cleanup path, so expiry cannot skip revocation. Physical RPC/process cancellation and settlement are W04 runtime responsibilities; a timeout is never evidence that a dispatched operation was undone.

## Separate worker deployment contract

`AccountWorker` in `session_service.py` is the six-method synchronous transport interface. `AccountWorkerExecutor` is constructed only in a separate worker process using T04's existing worker role and key provider. The API constructs no vault, decrypt service, worker database URL or saved-byte callback. `configure_account(app, worker=...)` injects a transport client. Without it, account operations fail with fixed 503; local logout remains available.

Worker-only `WSO_TVT_ACCOUNT_PROFILE_FILE` points to a bounded JSON array of explicit `region`, `brand`, `origin`, `language`, `country`, and `app_version` entries, with optional customer labels. Unknown/duplicate labels and invalid HTTPS policies are rejected. No endpoint is read from the public request.

The subsequent W04 transport must provide authenticated mTLS, bounded request/reply sizes, capacity admission, original deadline propagation, once-only ticket delivery, no automatic retries after dispatch, process cleanup/settlement and explicit uncertain outcomes. Its sensitive request serializer must deliberately extract SecretStr input values into its protected envelope; public model JSON intentionally masks them. The worker returns only typed public projections, never saved bytes or worker capabilities. Native DEVICE renewal and P2P lifecycle remain separately named source-derived adapter work.

## Executed development checks and limits

Owned tests exercise real Windows PostgreSQL 17 and all restricted roles in unique guarded databases, including migration UP/DOWN/reUP, STAFF publication, actor/tenant/grant/kind/generation denial, old-handle adoption fencing, unchanged legacy/domain controls, once-only challenges, local logout, two independent process singleflight, crash witnesses, no-replacement deduplication, late-publication rollback and actual T03 API behavior. Source-derived synthetic AccountClient seams exercise login/profile/logout projection without any vendor/device request.

The ignored `W05-account-backend-report.md` and `W05-account-evidence` directory contain exact commands, exits, UTF-8 captures, raw hashes, source/dependency guards, generation determinism and database ownership/cleanup receipts. No APK-versus-web run, live token observation, device/media renewal, production RPC or release acceptance is claimed. Expired challenge/capability metadata retention and authenticated avatar delivery need their later deployment/lifecycle owners; expired references already deny use.
