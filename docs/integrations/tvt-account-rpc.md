# TVT account worker RPC

Analysis / implementation date: 2026-10-02. This is the W04 account transport between the W05 API and its concrete APK-derived `AccountWorkerExecutor`. It does not implement device, native SDK, media or Talk transport. The API wiring and real PostgreSQL-to-RPC composition are a separate reviewed follow-up. Loopback fixtures do not pass G-P1, change MATCHED=0, or make `release_ready=false` true.

## Deployment and ownership

The installable `wso-tvt-bridge` base contains the API client and service-owned generated stubs. Its runtime dependencies are contracts, core, grpcio 1.84.0 and protobuf 7.36.2. The `worker` extra adds `wso-api`, which currently owns the concrete executor. Keeping this an extra permits the API to depend on the bridge client without a mandatory dependency cycle. The client module does not import the executor, TokenVault, secret cipher or worker bootstrap.

From the repository root, install the dedicated worker with `uv sync --package wso-tvt-bridge --extra worker`; a complete development workspace may instead use `uv sync --all-packages`. Launch the installed worker with `.venv/Scripts/python.exe -m wso_tvt_bridge` on Windows or `.venv/bin/python -m wso_tvt_bridge` on Linux. The worker extra is required in a dedicated deployment. Missing executor/configuration causes the sanitized `ACCOUNT_WORKER_UNAVAILABLE` startup failure; there is no synthetic executor or insecure fallback.

The worker process alone receives these configuration names:

| Name | Meaning |
| --- | --- |
| `WSO_TVT_BRIDGE_BIND` | Explicit private DNS/IP and port, such as `localhost:5443`; no resolver scheme |
| `WSO_TVT_BRIDGE_CA_FILE` | CA roots authenticating allowed API client certificates |
| `WSO_TVT_BRIDGE_SERVER_CERT_FILE` | Server certificate chain; SAN must match the client's endpoint host |
| `WSO_TVT_BRIDGE_SERVER_KEY_FILE` | Server TLS private key file |
| `WSO_TVT_BRIDGE_CLIENT_SANS_JSON` | JSON list of exact allowed client SAN identities |
| `WSO_WORKER_DATABASE_URL` | Existing explicit `postgresql+psycopg` worker-role database configuration |
| `WSO_CONNECTION_KEY_FILE` | Existing FileKeyProvider reference; exactly 32 bytes, worker only |
| `WSO_TVT_ACCOUNT_PROFILE_FILE` | W05 trusted endpoint profile loaded by `load_account_endpoints` |

No actual credential values belong in documentation, source, process arguments or browser configuration. Restrict secret files to their service identity. FileKeyProvider is the existing local deployment provider; a production secret-manager integration can construct the same executor/server inside its dedicated worker process. Production certificate enrollment and revocation distribution remain deployment work.

The API receives only `WSO_TVT_BRIDGE_ENDPOINT`, `WSO_TVT_BRIDGE_CA_FILE`, `WSO_TVT_BRIDGE_CLIENT_CERT_FILE` and `WSO_TVT_BRIDGE_CLIENT_KEY_FILE`. Its factory is:

```python
from wso_tvt_bridge.client import create_account_worker_client

worker = create_account_worker_client()  # AccountWorker six-method implementation
# Inject worker using the API's reviewed lifecycle adapter.
# At API shutdown:
worker.close()
```

The factory also accepts an explicit `Mapping[str, str]` with those same four names. It must not be given the worker DB URL or saved-credential decrypt key. Loading TLS key material does not authorize saved-token decryption. W05's ticket issuance and local logout revocation remain API responsibilities.

## Contract and security

Canonical source: `packages/contracts/proto/tvt_bridge.proto`. Generated Python source has exactly one location, `services/tvt-bridge/src/wso_tvt_bridge/generated/`. Run `uv run python scripts/generate_tvt_bridge_stubs.py` with the pinned grpcio-tools 1.84.0; the generator uses a virtual protoc source prefix to generate correct package imports and message module identities directly, without post-generation edits. Runtime protobuf 7.36.2 is compatible with the compiler's generated runtime requirement. PyPI metadata and Windows CPython 3.12 / Linux manylinux wheel evidence are frozen in the W04 evidence packet.

`wso.tvt.account.v1.AccountBridgeV1` has exactly Login, ImageChallenge, CheckImage, Profile, Renew and Logout. Each uses its own request message. The fixed RpcContext fields are protocol_version=1, a lowercase 64-hex opaque SQL ticket, remaining deadline_ms (1..20,000), and a 1..128-character restricted correlation_id. Field numbers 1..4 are permanent; 5..15 and the authority field names are reserved. Future removed fields must reserve their former number and name. Unknown protobuf fields, unrecognized versions, malformed/extra/duplicate JSON fields and invalid Pydantic DTOs are rejected before the executor runs. No method, URL, native pointer, shell command, DB selector, tenant, actor or authority is dynamically dispatched from wire input.

Login explicitly unwraps only the entering AccountLogin account/secret/image_code/second_code SecretStr fields; CheckImage explicitly unwraps only image_code. Pydantic's normal masked JSON serialization cannot be used for those inputs. Saved account/P2P tokens never pass through this serializer. Bodies are sent over an explicitly configured mTLS channel. Never log protobuf messages, wire frames, credentials, raw upstream data or exception representations; only fixed allowlisted failure codes reach the peer.

Application request limit is 32 KiB, and the gRPC send/receive frame limit is 512 KiB. These cover the actual 90,000-character image DTO and bounded profile fields, while rejecting oversized frames. Replies contain only the method's exact validated public Pydantic DTO or one allowlisted failure code. The client rechecks the DTO and correlation binding before returning.

The worker requires a client certificate trusted by its explicit CA and exactly one SAN identity that is present in its configured allowlist. Admission uses gRPC's verified auth_context and peer_identity_key, never metadata. Trust by CA alone is insufficient. The client uses normal hostname verification of its explicit endpoint. No ssl_target_name_override/default_authority or insecure channel is used.

## Deadlines, uncertainty and lifecycle

One client monotonic deadline starts before serialization. Only its remaining duration reaches the RPC timeout and request context; TLS, remote admission/queue and executor work consume that original duration. The server intersects its RPC time_remaining with the request duration. Its remaining callback also checks cancellation, and is propagated through W05 token_budget to SQL/executor publication checks. W05 composes nested budgets; its explicit local-logout cleanup detaches the outer budget for bounded independent local revocation.

No client retries are configured. A post-dispatch deadline, cancellation or ambiguous transport failure returns UNKNOWN_OUTCOME; this does not claim upstream cancellation, rollback or replay safety. The worker may already have sent a request or committed SQL. W05's protected durable renewal INFLIGHT state and SQL generation fences remain authoritative after a crash. The transport neither invents SQL success nor clears uncertain attempts. gRPC's pre-execution capacity rejection maps to SESSION_BUSY; exact peer SAN denial maps to ACCOUNT_DENIED.

The client and server each use bounded per-epoch ownership registries. Capacity defaults to 32 (maximum 256). Admission does not wait in an unbounded application queue. Correlation tombstones are retained for at most 65,536 admitted calls per epoch; once exhausted, rotate to a fresh configured lifecycle rather than forget old terminal ownership. Slots abandoned after dispatch retain capacity until the real executor settles. One settlement can publish at most one terminal result, late completion cannot publish into a closed/different registry epoch, and close refuses new admission and cancels client waiters. No registry lock is held over network, SQL or executor work.

Server close stops gRPC immediately and waits at most the bounded grace (default one second, capped at five). It returns whether all owned calls drained. Unsettled calls and their DB resource remain quarantined; their eventual settlement disposes the worker resource exactly once. A stuck thread cannot safely be forcibly interrupted in Python, so the operating process can remain alive until it settles; a supervisor may retire that process while treating every affected attempt as uncertain. Close is not proof of upstream cancellation.

For certificate/identity rotation, construct a fresh channel/server with the new explicit files and SAN allowlist and close the old lifecycle. Active old calls retire with uncertain results; new admissions require the new policy. Editing a PEM file alone does not update an existing channel/server, and removing an identity in a new process does not retroactively revoke an old process still accepting traffic. Stop old admission as part of deployment cutover.

## Verification and limits

Owned tests use real loopback mTLS with the server in a separately launched Python process and client in the parent. They exercise all six methods, 90,000-character replies, ticket replay in a strict test executor seam, missing client certificate, wrong CA, wrong hostname, unauthorized signed SAN, spoofed metadata, old protocol, unknown fields/methods, malformed DTO/frame, bounded frames, fixed error redaction, total deadlines, capacity quarantine, client/server close, reconnect epochs, identity removal and CA/certificate replacement. The tests generate ephemeral one-hour certificates, restrict Windows ACLs/POSIX modes, terminate only owned child processes, and remove their credential files. No certificate authority or production keys are committed.

The in-memory seam is deliberately not a PostgreSQL authorization implementation. Its ticket replay result does not prove SQL authority, and synthetic identity/profile/image outputs do not prove APK interoperability. A separate test executes W05's real budget decorator/context and demonstrates cancellation blocks the publication callback; W05 owns actual PostgreSQL publication/rollback acceptance. No vendor/device network, Android .so Linux loading, PG reset, CI/private14 or broad acceptance suite is part of these transport tests.

Full exact commands, failed attempts, stdout/stderr hashes, interface snapshots, lock delta, deterministic generation and READY hashes are in `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-account-rpc-report.md` and its adjacent evidence directory. Source acceptance remains subject to root review. Real deployment wiring, service enrollment, actual PG→RPC→upstream account composition, and APK/account/device acceptance are outstanding.
