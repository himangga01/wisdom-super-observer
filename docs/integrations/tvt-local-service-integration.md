# Local TVT device service integration design

Design date: **2026-10-04, Asia/Seoul**. Current status: **M0 source reviewed,
14 owned SQL tests passed, real core/SQL/native inventory returned8/4 channels;
normal Chrome OWNER verification and saved readback also passed8/4**. This narrows W07/W08
of the [approved parity plan](../superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md).
Read [service-analysis.md](../service-analysis.md) and [local registration](tvt-local-device-registration.md)
before reuse; verify current source and refresh affected findings afterward.
Root owns the canonical service report and project instruction bridge.

## Source baseline and actual limits

Active workspace: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
HEAD: `36fc954e4754d69721596e190c35f9cf14de3e4c`, branch
`codex/superlive-web-service`. Initial tree contains the unpublished registration,
directory, native inventory/live and decoder work plus other agents' changes;
this design is based on those working files, not HEAD alone. The initial design
pass wrote two documents. Root then authorized the six-file M0 source/test slice
listed below. No native command, real-device call, database migration, UI action
or Git mutation was executed by this agent.

## M0 implementation update

Initial implementation record below is historical. The canonical service report
records later Fix2 SQL acceptance, real M1 inventory and current browser outcomes.

- `packages/contracts/src/wso_contracts/tvt/local_device.py`: strict local
  request/ref/channel/device views, generated channel labels, UTC observations,
  duplicate rejection and JavaScript-safe counters capped at 2^53-1.
- `infra/migrations/versions/0012_tvt_local_devices.py`: local purpose-bound
  one-use tickets, exact OWNER/session/store/link/connection-generation/secret-
  version/tenant-epoch checks, separate local devices/channels, forced RLS,
  functions-only runtime access and lifecycle invalidation that does not revive
  after a removed membership/link or inactive store is restored.
- `packages/core/src/wso_core/tvt/local_admission.py`: protected API issuer and
  safe reader, worker-only committed redemption, existing-envelope decryption
  inside a bounded native callback, fenced atomic inventory publication and
  independent short disposal after cancellation/expiry. Generic WorkerLease
  and cloud identity/token tables are unchanged.
- `packages/core/src/wso_core/tvt/local_service.py`: fixed error mapping,
  20-second absolute budget, cancellation/current callbacks, immutable private
  observation/provider port and verification executor. Accepted login,
  same-original-session, serial match, complete roster and confirmed cleanup
  are explicit required facts; count-only results cannot create inventory.
  The injected provider defaults to None and returns fixed unavailable.
- `tests/tvt_parity/test_local_device_service.py` and
  `tests/integration/test_local_device_admission.py`: inert-provider boundary
  tests and Root-activated owned PostgreSQL authority/roundtrip cases.

Stable public interfaces: `LocalDeviceTicketIssuer(session, remaining).issue(
session_digest, connection_id, LocalVerifyRequest) -> str`;
`LocalDeviceInventoryReader(session).list(store_id, *, correlation_id) ->
tuple[LocalDeviceView,...]` and `.get(connection_id, store_id, *, correlation_id)
-> LocalDeviceView`; `LocalVerificationExecutor(admission, provider=None).verify(
ticket, *, deadline_ms, correlation_id, cancel=None) -> LocalDeviceView`.
API/RPC/FE and native provider/loader are separately owned integration work;
this source does not itself expose an HTTP verification route or call a device.

Initial M0 verification: scoped Ruff and three-file mypy passed; portable
pytest passed **57 cases with ten gated PostgreSQL cases skipped**. These are
the preserved initial-review results; the Fix1 results below supersede the
current source status.
Root must activate `WSO_TEST_W08_LOCAL_ACCEPTANCE=1` and
the existing W07 directory acceptance parent/source/role settings. The fixture
reuses that owned create/snapshot/identity/drop owner and migrates only its
fresh `w07_directory_<uuid>` database. No existing database was migrated here.
Skipped SQL cases are not PostgreSQL acceptance. No production/native success
default, public live authority, persistent media or parity completion is claimed.

TDD record: initial missing-module/migration failures, then positive/negative
provider tests; cleanup failure and original-deadline expiry during disposal
were observed failing before their fixes. Initial UV lookup failed because it
was absent from PATH; subsequent checks used the existing .venv interpreter.
The implementation used the approved design and Root's scoped handoff; the
design sections below remain the future integration reference where not covered
by this update. The exact six owned sources and document preimages are captured
in the short W08 local-service review handoff, with no shared-source freeze.

### M0 Fix1 after independent review — 2026-10-04

The independent review returned C0/I2/M0. Fix1 changes one core file and the two
owned tests, preserving the initial packet and public signatures:

- Redemption constructs its opaque cleanup owner before the transaction. If
  commit/transport completion or the postcommit deadline/cancellation check
  fails, it retires that token through the existing independent short disposal
  path before propagating failure. Credential-use/publication budgets remain
  unchanged. Actual-code inert SQL/commit regressions first failed with a
  REDEEMED ticket and zero close calls, then passed for expiry, cancellation and
  uncertain commit with one close, zero provider calls and no success response.
- The SQL expiry fixture ages both issued_at and expires_at from one stable
  statement_timestamp(), with a 29-second valid interval that already expired.
  Its owned SQL assertion checks both constraints before testing denied use.
  No actual PostgreSQL failure or acceptance is claimed from this source fix.
- Three owned SQL cases additionally verify that published inventory stays
  STALE, with no channels, after membership/link/store removal and restoration.

Final Fix1 scoped verification: **60 passed, 13 gated SQL skips**; Ruff passed
for the current six owned files; mypy passed for the three contract/core files.
The unchanged migration still awaits Root's guarded owned SQL execution. Fix1
source/preimage identities and the concise correction record are under
`W08-local-service-integration-review/fix1/`; independent rereview is pending.

### M0 Fix2 after actual guarded SQL execution — 2026-10-04

Fix1 subsequently passed source review. Root's actual owned SQL run
e07622be32ed4347bc32c87e546e6922 completed14 tests: nine passed, five failed,
zero skipped; owned DB cleanup and source rows/owners preservation passed.
The five failures share successful credential use. Root's scoped owned probe
bc45f11711c3416badbed910eaff8043 confirmed ProgrammingError/SQLSTATE42702 in
wso_tvt_local_use before decryption/provider execution; public masks stayed fixed.

Fix2 changes only the migration's CLAIMED update to qualify ticket-column
references with alias x. expires_at had collided with the function's named
RETURNS TABLE output. The same authority/state/deadline predicates are retained.
The other statements in that function and adjacent new functions were audited
for named output collisions; no additional changes were needed. Existing actual
SQL failures are the regression cases. Migration Ruff and focused portable
tests60/13 skipped passed; SQL rerun/source closure remain Root's gates.
Preserve Fix1 acceptance and both actual runs. Minimal source/preimage and
diagnosis are in `W08-local-service-integration-review/fix2/`.

Implemented source boundaries:

| Source | Existing behavior relevant to this design |
| --- | --- |
| `services/api/src/wso_api/connections/router.py`; `wso_core/connections.py` | OWNER/CSRF/tenant/store/generation protected encrypted TVT_DEVICE registration; public connection statuses are only NOT_VERIFIED/DISCONNECTED |
| `wso_core/tvt/local_credentials.py` | Strict private serial/country/username/password parser; legacy input needs replacement |
| `wso_core/secrets.py`; migrations `0002_connections`, `0003_jobs` | OWNER-only, 30-second secret capabilities; callbacks hold authorization locks and must not retain credentials; job callbacks cannot nest inside a held job step |
| migrations `0004_tvt_domain`, `0007_tvt_account_sessions`, `0011_tvt_directory_read_tickets` | TVT cloud identity FK requires TVT_ACCOUNT; cloud directory depends on actual USER token/session. Existing checks cannot admit a TVT_DEVICE by changing a selector |
| `wso_tvt_bridge/windows_socket.py`, `windows_socket_worker.py` | Bounded diagnostic provider returns SafeResult counts; private inventory and files stay in its original owned worker; operator opt-in/current callback is not service SQL authority |
| `wso_core/tvt/local_inventory.py`, `local_live.py`, `windows_decode.py` | Private inventory, source-routed frame and decoder types exist; no public inventory enrollment, continuous FramePipe or browser signaling implementation |
| `wso_core/jobs.py`, `worker.py`, `tvt/domain_jobs.py` | Durable job/outbox/status/cancel foundation exists; reserved REGISTRATION is an external write, domain DEVICE_OPERATION is cloud identity bound; generic credential handlers fail unsupported |
| `wso_core/assets.py` | Private asset tickets, bounded admission and revalidation exist; live frames are not assets |

The canonical report records actual native login and metadata with 8/4-channel
rosters. Root's latest handoff reports the first actual store2 HEVC frame was
decoded and visually checked on Windows (1280 x 1936, approximately 7.4 MB RGB).
Fresh four-frame proof for both stores is running. This observation was supplied
by the coordinator; it was not independently rerun here. The native owner
confirmed the current provider is one original process, at most 60 seconds, one
channel and first-keyframe/four-frame capture followed by close/destroy. Decoder
duration defaults to 30 seconds with a 60-second ceiling. Actual single-frame
decode now has coordinator-reported evidence. No continuous session or browser
live playback is established by this design.

## Purpose and selected approach

Expose locally registered devices in the existing Windows-hosted Python service
and React/Tailwind connection/device views. First provide owner-initiated
verification and safe channel inventory, then an actor/store/channel scoped
live lease through the existing W08 camera adapter and media architecture.

Use a **separate local connection scope and purpose-bound admission**. Reuse
the encryption primitive, worker role, mTLS transport, bounded admission and
MediaState vocabulary. Never create a cloud USER/P2P token or TvtIdentity for
a serial, or insert TVT_DEVICE into the cloud identity tables.

Alternatives considered: widening cloud identity FKs and authorization would
mix distinct upstream proofs; running the current diagnostic CLI from FastAPI
would expose counts without roster authority and retain credentials for its
entire run. Neither provides the needed contract. The recommended local path
leaves those existing cloud contracts compatible.

Use a bounded synchronous verification RPC for the first milestone: a single
metadata read sequence needs no durable external-write intent or broker retry.
Its total service budget is **20 seconds**, shorter than the existing 30-second
credential capability. It never resets on redemption, login or metadata reads.
If actual metadata cannot complete in that budget, return a fixed timeout and
close; do not quietly lengthen the secret callback. Later background refresh or
exports must use the existing jobs/outbox and status/cancel routes, with a new
READ job kind if needed. Do not repurpose REGISTRATION or DEVICE_OPERATION.

## Phase 1: protected verify and inventory

Public routes (proposed):

| Route | Input/output and admission |
| --- | --- |
| `POST /api/v1/tvt/local-devices/{connection_id}/verify?tenant_id=...` | Strict `{store_id, expected_generation}`; OWNER, exact-origin CSRF, current web session, active tenant/store, current store_connections link, TVT_DEVICE and usable generation; returns LocalDeviceView only after fenced publication and owned native cleanup |
| `GET /api/v1/tvt/local-devices?tenant_id=...&store_id=...` | OWNER first; safe saved connection metadata plus current inventory state; no vendor access |
| `GET /api/v1/tvt/local-devices/{connection_id}/channels?tenant_id=...&store_id=...` | Same current scope; safe generation-bound inventory, no native read |

An unassigned connection can be saved; verification requires an active selected
store association. The existing connection editor supplies it. Inaccessible
selectors return 404; malformed input 422; generation conflict 409; saturation
429; unavailable provider 503; upstream rejection 502; total timeout 504.
Use the shared `{error:{code,message},request_id}` envelope, fixed messages,
no-store and `Vary: Cookie`; no exception/native response text in errors.

New `packages/contracts/src/wso_contracts/tvt/local_device.py` defines:

- `LocalVerifyRequest(store_id: UUID, expected_generation: positive int)`.
- `LocalDeviceRef(tenant_id, actor_user_id, connection_id, store_id, device_id,
  channel_id?)`: UUID selectors only; construction grants no authority.
- `LocalChannelView(id: UUID, ordinal: int, label: str)` with generated
  `Channel {ordinal}` labels initially. Preserve native GUID/raw/window indices
  privately; list position is not a native command index.
- `LocalDeviceView(connection_id, device_id?, store_id, connection_generation,
  inventory_revision, inventory_state, observed_at?, channels, request_id)`.
  `inventory_state` is UNAVAILABLE/AVAILABLE/STALE. AVAILABLE means a current
  accepted login, serial match and complete same-session roster, followed by
  confirmed owned cleanup and protected publication. It does not assert a
  cryptographic security proof, live capability or continuing online status.

Keep ConnectionView's status schema intact; show a separate device inventory
badge. Do not update last_success or mark an actively playing connection from
registration or merely available inventory. Never return serial, credentials,
upstream GUIDs, login session IDs, group IDs, raw indices or native file paths.
Display names/model/firmware can be added later with a reviewed projection;
raw vendor text is not needed for the first channel list.

### SQL migration and worker flow

Create `infra/migrations/versions/0012_tvt_local_devices.py`, following
`0011_tvt_directory_read_tickets` (reconcile the revision if another migration
lands first). Do not alter cloud identity/token tables or the connection status
constraint. New tables under `wso_private`:

| Table | Required fields/invariants |
| --- | --- |
| `tvt_local_device_tickets` | ticket/lease digests, tenant/actor/web-session digest, tenant epoch, connection/generation/secret-version, selected store/link, method=verify, ISSUED/REDEEMED/PUBLISHED/CLOSED state, issued/expires timestamps; 30-second maximum, one-use committed redemption, one active verify per connection/generation |
| `tvt_local_devices` | opaque local device UUID, tenant/connection FK requiring TVT_DEVICE, connection_generation, inventory_revision, observed_at; one device per registered connection; serial remains only in encrypted credentials |
| `tvt_local_channels` | opaque UUID, tenant/device FK, private native GUID/raw/window index, display ordinal, active flag, observed revision; unique native GUID per device; stable UUID on unchanged GUID within unchanged connection generation |

Use forced RLS, no direct runtime table access and a NOLOGIN
`wso_tvt_local_owner` definer with only the needed columns/function privileges.
API uses functions only under its existing PID/XID tenant context; worker uses
the existing `wso_connection_worker` URL/role. No new administrator DSN or public
credential endpoint. Reuse SecretCipher/Envelope and existing encrypted payload;
do not copy plaintext to SQL or create another credential store.

Proposed fixed SQL functions:

- `wso_tvt_local_issue(session_digest text, connection uuid, store uuid,
  expected_generation bigint) -> text`, API only; derives actor/tenant and
  current secret version, binds exact method/scope and checks capacity.
- `wso_tvt_local_redeem(ticket text, lease text) -> boolean`, worker only;
  consumes ticket and commits before callback work, preserving original expiry.
- `wso_tvt_local_use(lease text) -> scoped encrypted-envelope row`, worker only;
  rechecks exact saved authority and takes bounded shared lifecycle locks in the
  project's established order, then returns the original nonce/ciphertext/AAD
  identifiers plus scope and expiry. It cannot read an arbitrary connection ID.
- `wso_tvt_local_current(lease text) -> boolean`, worker only; checks current
  clock/session/epoch/scope/generation/secret version immediately before each
  native Send, including after buffer preparation.
- `wso_tvt_local_publish(lease text, observation jsonb) -> safe view`, worker
  only; validates a closed fixed schema, complete roster, exact generation,
  current expiry/authority and cleanup success; atomically upserts the roster
  and increments inventory revision. No raw observation is a public API input.
- `wso_tvt_local_close(lease text) -> void` and
  `wso_tvt_local_inventory(connection uuid, store uuid) -> safe rows` for
  disposal and currently authorized reads.

`packages/core/src/wso_core/tvt/local_admission.py` owns issuer/redeemer and
`LocalDeviceAdmission.use_credentials(lease, callback)`. This purpose-specific
callback decrypts through the shared SecretCipher under that bounded transaction
and clears request-local references before return. The SQL function enforces the
local ticket scope rather than extending generic WorkerSecretStore privileges.
Recheck deadline before decrypt and before/after every native step/publication.
The callback can hold lifecycle locks for at most the remaining 20-second
budget; use bounded connection/statement/lock timeouts. Cancellation stops
admission immediately, closes the original process and refuses publication.
No secret use inside a held JobStep.

`services/api/src/wso_api/tvt/local_device_service.py` defines
`LocalDeviceWorker.verify(ticket: str, *, deadline_ms: int, correlation_id: str)
-> LocalDeviceView` and its trusted executor. API commits issuance before mTLS
dispatch; authority is derived in worker SQL, never accepted from RPC IDs.
Add LocalDeviceBridgeV1.Verify using the existing RpcContext and a safe reply to
`packages/contracts/proto/tvt_bridge.proto`, regenerate existing stubs, and wire
client/server using their existing TLS, deadline, fixed failure and capacity
patterns. Keep native execution outside FastAPI's process.

### Required native contract (implemented by NativeLocalInventoryProvider)

Native owner supplies a bounded `verify(credentials: LocalDeviceCredentials,
*, deadline: absolute monotonic time, current: Callable[[], bool],
cancel: Event) -> LocalInventoryObservation`. The result is a private immutable
projection of the same original login/metadata InventoryEvidence with channel
GUID/index mapping, serial-match flag, user/group branch provenance and confirmed
original-process cleanup. No credential reference, serial string, security key
or native handle may escape the callback. SafeResult.channel_count must never
be expanded into invented channels. Source-specific proof flags remain distinct.

For the legacy no-group path, metadata branch completion is three reads while
permissions_complete stays false. Preserve missing/empty provenance; whitespace,
comment or CDATA shapes do not silently become the same branch. A group path
needs actual selected GUID and `lp`; admin/system flags do not confer permission.
Phase 1 roster publication does not create live grants from these observations.

## Phase 2: credential-free lifetime and MediaLease

This is a separate implementation slice after phase 1 and accepted native
frame/decode evidence. Extend MediaLease owner/device with explicit compatible
local variants (`LocalMediaOwnerRef`, `LocalDeviceRef`); keep existing cloud JSON
valid and require matching local tenant/actor/connection/store/channel scope.
Use existing MediaState transitions and the planned `/api/v1/tvt/live-sessions`,
`/{id}`, `/{id}/webrtc-offer`, optional candidates and heartbeat/stop surfaces.
Do not add a second T17/T31 adapter: extend `services/edge/src/wso_edge/tvt.py`
through W08's `services/tvt-media/src/wso_tvt_media/{live,lease,codec,signaling}.py`.

Add subsequent migration `0013_tvt_local_media_leases.py`: purpose-bound local
actor/channel grants plus media leases with tenant/actor/web-session/store/
connection generation, inventory/grant revisions, worker epoch, native session
generation, state and expiry. Owner-created local grants intersect current
tenant membership, active store assignment/link and verified native live basis.
Start owner-only; MANAGER/STAFF credential delegation is a separate reviewed
local SQL capability, never a widening of the generic OWNER secret lease.
No grant substitutes for current native channel permission or codec support.

Native owner must supply `open_session(...) -> OwnedLocalSession`, bounded
`read_frames(...)`/`close(...)`, and a typed private FramePipe. Login happens
inside the short credential callback; both parent PrivateRequest and worker
credential fields are discarded before returning the credential-free session.
Only private session material needed for the protocol stays with the original
worker, bound to continuously renewed media authority. Returning the current
PrivateRequest/login object unchanged does not meet this boundary.

For current route0 evidence, use one fresh original socket/process with its
first exclusive live task and matching open ACK. Do not share, replace or reuse
that task/socket; close destroys the process. Quality switch/reconnect closes
and obtains a new admitted session. Session pooling is deferred until a source
and execution proof establishes disambiguation. This restriction must be part
of multiview capacity decisions, not hidden behind a shared session cache.

The pipeline is: revalidated native callback queue -> source-routed
PrivateLiveFrame -> proved framing/unencrypted/PTS adapter -> ElementaryPacket
with DecodeBinding -> bounded decoder -> authorized W08 browser delivery.
Never convert raw media to public diagnostic JSON/files. Recheck admission
after buffer preparation before Send and before frame dequeue/decode/delivery;
callbacks only enqueue bounded data, with no native work or SQL inside them.
Bound queue bytes/frames, decoder memory, actors and sessions; slow consumer,
revoke, close or expiry discards queued frames and reaps original resources.
Heartbeat cannot revive a revoked generation. Use lifecycle revision tombstones
so removing then restoring membership/link never revives an old lease.

Local media authority is independent of the 30-second secret capability. No
long-lived DB transaction or plaintext credential callback wraps streaming.
Review and test a short configurable media TTL/heartbeat and maximum orphan
duration before enabling; the approved plan explicitly requires actual device
safety evidence for that release bound. The existing 60-second capture/decoder
ceilings are diagnostic bounds, not a continuous-runtime promise. Decode,
packet timing and negotiated WebRTC codec must pass actual acceptance before
advertising PLAYING; HEVC receipt alone does not decide the browser codec.
HLS/audio/listen/Talk/snapshot/recording remain their W08/W09 slices; private
assets are used only when an authorized user saves a snapshot/recording.

## Small implementation milestones and checks

1. **M0, independent of video:** implement local request/view contracts,
   0012 admission/readback, safe worker port, Verify RPC and API with an injected
   inert provider; production configuration defaults unavailable. Tests use
   invented inputs/observations, including nonsequential native indices, with no
   native DLL/device access. This yields reviewable service enrollment and
   inventory plumbing while real verification remains unavailable.
2. **M1, native inventory:** native owner adds the exact private observation
   export/cleanup contract; connect the executor after source review, then Root
   executes authorized real-device verification. Publish only source-derived
   same-session channels; mismatch, incomplete roster, late result and uncertain
   cleanup cannot advance inventory. Device permissions and live stay separate.
3. **M2, current UI:** extend `apps/web/src/features/connections/connections-view.tsx`
   with owner verify/inventory actions and a local inventory component under
   `features/tvt/devices/`; add `lib/tvt/local-device-api-client.ts`. Existing
   DirectoryPage is gated on a cloud account: local entry must be reachable
   from connections/stores independently of that account gate. Reuse its
   abort/stale-response patterns and Tailwind tokens, not its cloud selectors.
4. **M3, live control:** approved compatible MediaLease extension, local grants,
   0013 leases and synthetic continuous FramePipe cancellation/expiry tests;
   production media remains unsupported until native lifetime and codec proof.
5. **M4, actual live:** connect the reviewed dedicated-session frame/decoder
   path and W08 signaling; Root proves channel identity, decoded pixels,
   timestamps, revoke/expiry/close/reconnect and browser playback per device.
   Multiview capacity follows measured native process/decoder use.

M0 file ownership: create contracts `tvt/local_device.py`, core
`tvt/local_admission.py`, API `tvt/{local_devices,local_device_service}.py`,
migration 0012 and tests `tvt_parity/test_local_device_{contracts,service,rpc,api}.py`
plus `integration/test_tvt_local_device_admission.py`. Modify API `main.py`,
bridge proto/client/server/selected/generated stubs and generation tests.
Native provider/codec files remain under the native owner's control.

Required M0 assertions: current OWNER/session/tenant/store/connection-kind
and generation checks; wrong or removed link; replay/expiry and old authority
after remove/re-add; publication after revoke or timeout; scope substitution;
incomplete/duplicate channel mappings; safe zero-channel roster; legacy encrypted
input rejection; no saved plaintext in public DTO/audit/error/RPC reply; fixed
provider-unavailable response; cancellation/cleanup failure blocks success.
Run scoped portable pytest first, then the existing owned PostgreSQL fixture
with zero selected integration skips and source-database preservation. Only M2
needs frontend lint/types and browser component/service acceptance. No design
claim below is a passed runtime test.

## Risks, product questions and verification record

Highest priority is the typed native inventory export; counts cannot bridge it.
Next is honest credential disposal and cancellation before a persistent session
is retained. Route0 exclusivity currently limits reuse and increases per-tile
resource cost. A 20-second metadata deadline may require explicit timeout UX on
slow devices. Local inventory is historical evidence, not current live authority.

Proposed first release is OWNER-only verify/read/live. Before expanding actors,
Root must confirm the local explicit-grant and worker credential-delegation
policy. Decide whether device names should ever be projected publicly and what
live TTL/orphan limit actual acceptance can support. These do not block M0.

Verification in this task: `git status --short`, `git log -1`, `git branch
--show-current`; read canonical reports, approved W04/W07/W08 plan sections,
listed Python/SQL/proto/React source; `rg` for existing job/admission/media APIs;
native owner's contract confirmation. Some initial path guesses did not exist
and were corrected through file inventory. No tests were executed because this
task changes only design Markdown. Runtime outcomes are inherited evidence with
their limits stated above. No parity case or release gate advances.

Update log: 2026-10-04 — initial scoped service design; incorporate native
owner's same-session inventory, no-group provenance, route0-exclusive lifecycle
and diagnostic-duration limits; include Root's subsequent first store2 decoded
frame/visual check, with both-store four-frame proof still running.
Root should record this canonical guide in
AGENTS.md and link it from service-analysis.md when the scoped design is accepted.
