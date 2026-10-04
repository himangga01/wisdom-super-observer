# Local TVT device API and RPC wiring

Updated: **2026-10-04, Asia/Seoul**. This guide records implemented source and
synthetic transport verification. Read [the local service design](tvt-local-service-integration.md)
and [the canonical service report](../service-analysis.md) before reuse; Root owns
the current actual SQL/native/browser acceptance record and project AGENTS bridge.

## Baseline and scope

Active workspace: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Coordinator-provided source baseline: HEAD `36fc954e4754d69721596e190c35f9cf14de3e4c`,
branch `codex/superlive-web-service`. Initial working tree already contained
unpublished registration, directory, native and decoder changes. This task did
not run Git, database migrations, native SDK/device commands or browser actions.

Owned implementation: `packages/contracts/proto/tvt_bridge.proto`, generated
bridge stubs, bridge `client.py`, `server.py`, new `local_rpc.py`, API
`tvt/local_device_service.py`, `tvt/local_devices.py`, minimal API `main.py`
wiring and `tests/tvt_parity/test_local_device_rpc_api.py`. Core contracts,
admission/migration/provider files are separately owned; their APIs were agreed
with their authors. Shared reports and AGENTS are updated by Root.

## Public behavior

| Route | Input | Output |
| --- | --- | --- |
| POST `/api/v1/tvt/local-devices/{connection_id}/verify?tenant_id=...` | Closed `{store_id: UUID, expected_generation: positive integer}` | `LocalDeviceView` |
| GET `/api/v1/tvt/local-devices?tenant_id=...&store_id=...` | Exact query keys, UUID selectors | Array of `LocalDeviceView` |
| GET `/api/v1/tvt/local-devices/{connection_id}/channels?tenant_id=...&store_id=...` | Exact query keys, UUID selectors | `LocalDeviceView`, including state/generation/channels |

Authentication precedes body parsing; POST uses existing exact-Origin CSRF.
`connections:write` and `connections:read` enforce OWNER through `require_tenant`.
The API issues the core purpose-bound ticket inside the current scoped transaction;
its context exits and commits before RPC dispatch. Worker reply must match
connection, store, expected generation, AVAILABLE state and request ID.

GET uses `LocalDeviceInventoryReader(session).list(store_id, correlation_id=...)`
or `.get(connection_id, store_id, correlation_id=...)`. It invokes no worker.
The core SQL reader is responsible for current store/link/session/tenant/kind
scope and generation staleness. API projection rechecks the selected IDs.

The route starts one 20-second monotonic budget before authentication. JSON must
be `application/json`, is capped at 1,024 bytes, rejects duplicate keys and
nonfinite/deep JSON, and uses the remaining budget while receiving. Contract
validation rejects extra fields and boolean generations. During verification,
HTTP disconnect/cancellation sets the Event passed to the RPC client.

Responses use the existing `{error:{code,message},request_id}` envelope,
`Cache-Control: no-store`, `Vary: Cookie`, and `X-Request-ID`. Local failures
use the core allowlist (404 scope denial, 409 generation/cancellation, 429 capacity,
422 input, 502 protocol/upstream rejection, 503 unavailable, 504 deadline).
Messages are fixed and contain no native or exception details.

## Worker boundary

`LocalDeviceWorker` is an API-side Protocol only:
`verify(ticket, *, deadline_ms, correlation_id, cancel: Event | None = None)`.
The shared `AccountRpcClient` adds this method on the existing mTLS channel.
`LocalDeviceBridgeV1.Verify` accepts only `LocalDeviceVerifyRequest.context`;
no connection/store IDs, query JSON or raw credentials cross the wire. Existing
protobuf fields/services/numbers were preserved. Existing generation script
regenerated the stubs with pinned grpcio-tools 1.84.0.

The server checks TLS transport, SAN identity key, exactly one peer SAN, and the
configured allowlist before admission. Unknown protobuf fields, protocol/version,
ticket format, correlation and deadline bounds fail before worker dispatch.
The existing callback registry and session pool retain capacity/epoch ownership;
client close, server close and abandoned RPCs signal the original executor Event.
A single remote deadline covers admission and execution; no retry or budget reset.
Replies are at most 65,536 bytes, have exactly one success/failure branch, and are
revalidated as exact `LocalDeviceView`/`LocalChannelView` models before publication
onto RPC. Raw model dictionaries are checked before serialization to reject
hidden extras and malformed `model_construct` or mutated outputs.

Only worker bootstrap invokes
`wso_tvt_bridge.local_inventory_config.load_local_inventory_provider()` when
`WSO_TVT_WINDOWS_LOCAL_INVENTORY_ENABLED` is present. A configured provider is
passed to core `LocalVerificationExecutor(LocalDeviceAdmission(worker_url,
key_provider), provider)`; admission shutdown participates in existing owned
reverse-order disposal. Absent provider leaves local verification unavailable.
The native loader/adapter has separate ownership and source/runtime acceptance;
an invented provider is used only in tests. No diagnostic SafeResult count is
converted into a channel, cloud USER token, identity or live authority.

## Verification and practical limits

Focused tests first failed for the missing protobuf service, projection and routes;
after implementation, 31 focused tests passed. They exercise real loopback mTLS
with invented worker results: wrong SAN, unknown authority fields, malformed and
private worker outputs, capacity, original-executor cancellation, client close,
late results, fixed exception errors, deadline limits and bootstrap ownership.
API seam tests cover authentication/CSRF before parsing, commit-before-RPC,
strict body limits, selected-scope binding, no-store and worker-free inventory.

Compatibility execution is recorded in
`.superpowers/verification/local-device-api/pytest.txt`. Initial broad run had
209 passes, 7 bootstrap compatibility failures and 1 optional skip. The failures
were corrected by keeping optional local startup imports/arguments absent when
local verification is disabled; all 56 focused local/bootstrap/contract tests
then passed. **Final broad rerun: 230 passed, 1 skipped in 41.30s.** The skip is the existing
`test_directory_api.py:469` optional Root-owned accepted-source activation case;
no selected local API/RPC test skipped.

Scoped API mypy: **2 files passed**. A direct bridge mypy invocation also reported
the existing generated protobuf dynamic-member/untyped-stub errors; it is not
claimed as passing. Ruff passes/format are run for owned files. No source snapshot
pin or historical receipt was weakened, and existing fixture files were not edited.

The 20-second budget blocks RPC after late authentication/tenant/issuance work and
refuses late results. Existing `PostgresSessionStore` and tenant/identity engines
use ordinary SQLAlchemy pools without an explicit fixed connect/pool timeout in
these code paths. Therefore the HTTP wall-clock bound is **not established for
pre-RPC authentication/tenant database waits**. Root requested preserving shared
T03 behavior in this slice; a separately scoped bounded authorization runtime is
an open follow-up. The core issuer sets SQL statement/lock bounds once admitted;
that does not bound earlier connections. Synthetic seams do not prove current
SQL authority, real device verification, full cleanup under native failures or
public browser CCTV playback. Those remain Root/native acceptance work.

Open product points: OWNER-only reads/verification are implemented; expansion to
other roles requires a reviewed local delegation policy. AVAILABLE inventory is
saved observation, not an assertion of present live permissions or playback.

Update log: 2026-10-04 — API/RPC implementation and scoped synthetic verification;
coordinated exact core/provider interfaces; retained honest authorization DB and
native/browser execution limits.
