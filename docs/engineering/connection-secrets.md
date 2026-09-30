# Connection credentials and worker access

T04 provides local connection management for `TVT_ACCOUNT`, `TVT_DEVICE`, and `TYCO_ACCOUNT`. No device or vendor network request runs here. A saved or replaced credential is `NOT_VERIFIED`; disconnect changes it to `DISCONNECTED`. A later adapter must establish actual login evidence before any online state is introduced.

## HTTP contract

All endpoints require the `__Host-wso-session` cookie and a real owner membership in the selected `tenant_id`. Every mutation additionally requires an exact configured `Origin` and `X-CSRF-Token` matching the server-side session digest. A header alone never grants tenant access. Membership is freshly verified using the existing one-use tenant authorization mechanism.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/api/v1/connections?tenant_id=UUID` | 200 `{items, selected_tenant_id}` |
| POST | `/api/v1/connections?tenant_id=UUID` | 201 connection view |
| GET | `/api/v1/connections/{id}?tenant_id=UUID` | 200 connection view |
| PATCH | `/api/v1/connections/{id}?tenant_id=UUID` | 200 connection view |
| POST | `/api/v1/connections/{id}/disconnect?tenant_id=UUID` | 200 disconnected view |
| DELETE | `/api/v1/connections/{id}?tenant_id=UUID` | 204 empty body |

A view contains exactly `id`, `tenant_id`, `kind`, `alias`, `site`, `status`, `last_success`, `generation`, and `store_ids`. The saved username, password, key, ciphertext and worker capabilities are absent. Responses use `Cache-Control: no-store` and vary by Cookie.

Creation accepts `kind`, `alias` (1–200 characters), `site` (1–500), `username` (1–512), `password` (1–4096), and optional `store_ids` (at most 100). The list defaults to empty: a connection does not invent a store. Site is display metadata, not permission to fetch a URL. Store mapping checks active stores within the same tenant and uses a composite foreign key.

Patch accepts required positive integer `expected_generation`, optional `alias`, `site`, `store_ids`, and optional complete replacement of both `username` and `password`. Omitting a field retains it. Explicit null, blank credentials, partial credentials and unknown fields are rejected. A metadata-only patch also advances generation and revokes existing access. Disconnect and delete accept `{expected_generation}`. Reconnecting means patching a disconnected connection with a complete new credential pair; its new status is `NOT_VERIFIED`.

Errors use the application's sanitized envelope `{error:{code,message},request_id}`: 401 unauthenticated; 403 current nonowner or rejected CSRF; 404 unknown/foreign tenant, connection, or mapping; 409 stale generation; 422 invalid input; 503 unavailable credential key. CSRF uses `csrf_rejected`; validation uses `validation_error`; 404 uses `not_found`; other HTTP failures use `http_error`. Writes are never automatically retried.

## Encryption and key configuration

`SecretCipher` uses maintained `cryptography` AES-256-GCM with a fresh 96-bit nonce for each encryption. Canonical associated data contains a format domain separator plus the tenant, connection and secret-version UUID bytes. A modified ciphertext or any wrong identity fails authentication. The credential payload is an encrypted UTF-8 JSON object containing username and password.

`KeyProvider.encryption_key()` supplies the key outside the database. `configure_connections(app, provider)` accepts an injected provider. For local development only, `WSO_CONNECTION_KEY_FILE` identifies a raw 32-byte key file under an ignored `private/` or `.superpowers/` directory with permissions limited to the service account. Generate the file locally with a cryptographically secure random source; never print its contents or commit it. Missing/invalid files fail closed, and credential writes persist nothing.

Production needs an actual secret manager/KMS integration and key retention/rotation design before deployment. This change provides an interface, not a simulated KMS adapter. The local provider exposes one current key; replacing that file without retaining the old key makes existing credentials unreadable. Database backups require the separately protected key to restore credentials. Restrict database parameter/statement logging and tracing in deployments: application SQLAlchemy engines hide bound parameters; API validation errors and audit records never serialize credential input.

## Database and capability boundary

Migration `0002_connections` follows `0001c_auth_sessions`. As with existing role-creating revisions, initial migration uses the explicit administrative migration URL because role creation/hardening requires administration. All new tables and security-definer functions are owned by `wso_migrator`; forced RLS applies. Security-definer search paths are fixed to `pg_catalog` and table references are qualified.

- `wso_app` can read only owner-visible public connection metadata and mapping rows, and execute protected mutation/handle issuance functions. It cannot select credential, handle, lease or revocation rows, and cannot call worker functions.
- `wso_identity_bootstrap` and `wso_web_session` have no new table or function privileges.
- `wso_connection_worker` is a dedicated login with NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION and NOBYPASSRLS. It has no membership edges and only executes capability redemption/use functions. It cannot read tables, mint tenant grants, issue its own capability or switch to application/bootstrap/session/migrator roles.
- `WSO_WORKER_DATABASE_URL` is explicitly passed to `WorkerSecretStore`; its current PostgreSQL role is checked. No admin or application URL fallback exists. Tests use `WSO_TEST_WORKER_DATABASE_URL`.

`ConnectionService.authorize_worker(id,generation)` must run inside a protected owner tenant transaction. The database produces a random, opaque handle scoped to tenant, actor, connection, generation and secret version, expiring after 30 seconds. Only its SHA-256 digest is stored. This handle is an internal server capability; there is no REST endpoint to request or redeem it.

`WorkerSecretStore.with_secret(handle)` redeems the handle and commits consumption before returning a lease. Exactly one concurrent redemption wins; rollback of subsequent worker callback work cannot restore the handle. A lease expires at the original handle deadline. `lease.use(callback)` checks the current owner membership, connection state/generation/version and expiry before decrypting. It holds shared membership and connection locks until the callback completes. Trusted callbacks must bound their work and must not copy or retain credentials. Future adapters must avoid holding this transaction across unbounded network calls.

Update, disconnect and delete acquire locks in the same membership-then-connection order. They advance/revoke the old generation and remove outstanding handle/lease rows atomically. An in-flight authorized callback completes before a conflicting lifecycle mutation can commit; all later use is rejected. Disconnect/delete delete the encrypted secret. Delete retains a nonsecret durable revocation record. There is no public API to mark a worker result online, so stale worker completion cannot promote a connection in this phase.

The database prevents untrusted roles from fetching saved ciphertext. The cipher primitive itself is not an authorization boundary. A trusted worker holding plaintext can copy it; generation invalidation cannot erase copies in an already compromised process. Likewise, a privileged database administrator or the migration owner is outside the runtime role boundary. Raw worker SQL can roll back its own redemption transaction; callers must use the durable-commit worker API before running work. No claim of protection from a malicious holder of both the worker credentials and decryption key is made.

## Lifecycle integration points

`wso_private.connection_revocations` records tenant, connection, prior generation, reason and timestamp. The current public generation and these durable records support later T05/W05 browser/session/job cancellation consumers. T04 does not create remote sessions or a broker and does not claim that future browser or job cancellation consumers already run.

The original plan's `SecretStore.put` interface was refined to an encrypt-only preparation step and atomic lifecycle mutation so credential replacement, generation advance, audit and revocation cannot commit separately. `SecretStore.prepare` never reads saved ciphertext. Saved credentials are only retrieved through a worker capability; a connection UUID and generation alone cannot decrypt them.

## Verification

`tests/integration/test_connection_secrets.py` exercises AES-GCM identity binding/tamper, missing key failure, public/log/audit redaction, signed sessions and CSRF, owner/tenant/store boundaries, explicit restricted-role SQLSTATE 42501 denial, handle replay and expiry, membership revocation, generation races, disconnect/delete/reconnect, callback rollback, schema upgrade/downgrade and catalog ownership/forced-RLS/function ACLs against PostgreSQL. Live checks require explicit role URLs and do not run against SQLite.
