# Owned local-device OWNER browser runtime

Date: **2026-10-04, Asia/Seoul**. Coordinator-provided baseline:
`36fc954e4754d69721596e190c35f9cf14de3e4c`, active worktree
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
The initial tree already contained accepted unpublished M0 core, API11, web7
and native M1 work. No Git command was executed by this implementation author.
Read [the canonical service report](../service-analysis.md),
[service integration](tvt-local-service-integration.md) and
[local API](tvt-local-device-api.md) before reuse; root owns their execution
updates and the project AGENTS canonical instruction bridge.

## Purpose and implemented composition

This new fixture composes the current OWNER connection UI, Next HTTPS proxy,
actual FastAPI restricted session/tenant entrance, local one-use ticket issuance,
shared verified mTLS bridge, `LocalVerificationExecutor`, reviewed native
inventory provider and encrypted `TVT_DEVICE` credentials. The actor and
organization are synthetic; device credentials and native replies become real
only in the explicitly activated root run. It creates no cloud TvtIdentity or
USER/P2P token and grants no media/live/control authority.

The existing directory fixture remains unchanged. This fixture reuses its
reviewed pure TLS, private-folder, signed issuer, admission and custody helpers,
and the existing guarded `directory_database.__wrapped__()` resource owner.
That owner retains the original source database name/OID/owner/revision/content
snapshot, parent migration identity, unique owned database marker and guarded
drop/absence verification. The new wrapper checks that fresh owned identity,
migrates only it to `0012_tvt_local_devices`, and downgrades to 0011 before the
original owner exits. It never migrates or resets the shared source database.
The old directory source gate is neither invoked, overridden nor repinned.

One newly generated fixed OWNER is provisioned for one new demo tenant. Two
active stores and two linked TVT_DEVICE connections are created through the
real scoped `ConnectionService` and existing encryption boundary. The normal
signed issuer uses that exact OWNER subject and current issuer binding. Its
button says **Sign in as local device demo owner**. No cookie injection or
precreated web session is used. Initial connection status remains NOT_VERIFIED;
the independent local inventory view starts unavailable.

## Constructors, environments and source approval

Worker composition is `LocalDeviceAdmission(worker_url, FileKeyProvider(key))`
plus `LocalVerificationExecutor(admission, provider)` passed to
`AccountRpcServer(..., local_device_worker=...)`. The existing shared client
implements `verify(ticket, deadline_ms<=20000, correlation_id, cancel=None)`;
no connection/store/credential selectors cross RPC. Cloud methods in this
dedicated local fixture return unavailable.

Only the worker receives WORKER database URL, owned key file and native settings:

| Variable suffix under `WSO_TVT_WINDOWS_LOCAL_INVENTORY_` | Root-approved value |
| --- | --- |
| `ENABLED` | `1` |
| `BUNDLE` | `C:/wso-private/windows-tvt-sdk-20261003/package` |
| `STAGING` | `C:/wso-private/windows-tvt-sdk-20261003/service-inventory-runs` |
| `SOURCE_REVIEW` | `C:/wso-private/windows-tvt-sdk-20261003/source-approved-local-inventory-service-m1-fix1.json` |
| `RUNTIME_REVIEW` | `C:/wso-private/windows-tvt-sdk-20261003/runtime-approved-r90.json` |

The M1 source receipt is pinned to
`06aea3adedc19e179aac515e9c962baf6a525ee36dad9b480ad18dde32410483`;
its R90 runtime dependency is
`77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d`.
The native constructor/config budget is 20 seconds. Missing or invalid loader
configuration, None, or an inert substitute fails real mode before admission.
The exact approved `NativeLocalInventoryProvider` class is required.

FastAPI receives only APP/IDENTITY/SESSION role URLs, the existing encrypt-only
connection key setting, old four bridge client TLS settings, ordinary OIDC/auth
settings and issuer CA. Its decrypt, local admission/executor and cloud vault
constructors are guarded. Native settings and WORKER URL are absent. Next
receives its own HTTPS/auth settings and API origin, with no database URL,
device input or native configuration.

A **new** source approval file is required before any database import/opening:
`WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE` is its absolute path and
`WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256` is the root-approved exact raw
SHA256. Its closed JSON schema is:

```json
{"schema_version":1,"root_explicitly_accepted":true,"scope":"owned-local-device-browser-only","sources":{"repository/relative/path":"exact-raw-sha256"}}
```

Root must construct/approve that snapshot from accepted evidence after reviewing
this fixture. It must cover new4, borrowed helpers/guards, current core6/API11/web7,
and M1 owned8/dependencies11. Runtime checks the fixed core/API/web acceptance
receipt identities, the fixed M1 receipt and all exact source hashes. It rejects
duplicate keys, missing required sources, traversal, wrong scope/hash and source
drift. It never derives acceptance from an arbitrary live file hash. Root's
source manifest can supply reviewable current hashes; that manifest alone does
not activate or approve the runtime.

## Private input and root launch

Root owns the protected input file, staged separately from Git. It is bounded to
16 KiB and contains exactly two records:

```json
{"schema_version":1,"devices":[{"alias":"Safe recorder label","store_label":"Safe store label","credentials":{"schema_version":1,"kind":"TVT_DEVICE","serial":"INERT123","country":"KR","username":"inert-user","password":"inert-password"}},{"alias":"Second safe recorder","store_label":"Second safe store","credentials":{"schema_version":1,"kind":"TVT_DEVICE","serial":"INERT456","country":"KR","username":"inert-user","password":"inert-password"}}]}
```

The sample is inert. Real inputs stay private and must never be printed, attached
or committed. Aliases/store labels must be distinct, contain no credential
values, and remain bounded display text. Scope, role, endpoint, key and native
selector fields are rejected. The coordinator reads credentials once for
encrypted creation and discards its input objects. The worker obtains them
only through the committed purpose-bound SQL callback. The original root-owned
input file is retained; the fixture does not delete it.

After source review, root silently sources the existing managed PostgreSQL
environment and launches Node with a unique new state path. Required variables:

```powershell
$localRun = [guid]::NewGuid().ToString('N')
$env:WSO_TEST_LOCAL_DEVICE_BROWSER = '1'
$env:WSO_TEST_LOCAL_DEVICE_NATIVE = 'real'
$env:WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE = Join-Path (Get-Location) "auth-state/local-devices-$localRun/context.json"
$env:WSO_TEST_LOCAL_BROWSER_INPUT_FILE = 'C:/wso-private/local-device-web/devices.json'
$env:WSO_TEST_BROWSER_TLS_DIR = 'C:/wso-private/wso-local-dev-tls/server'
# Set the separately accepted SOURCE_APPROVAL_FILE/SHA256 and five native keys.
$env:WSO_TEST_W07_DIRECTORY_ACCEPTANCE = '1'
$env:WSO_TEST_W07_PARENT_SHA256 = 'a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958'
node scripts/test-local-devices/server.mjs
```

The nine managed `WSO_TEST_*_DATABASE_URL` values remain inherited only in the
coordinator; no roles or credentials are printed. Root should launch through
its retained hidden Process handle with redirected safe output, preserving the
same environment. The `auth-state` parent must exist; the unique child directory
must be new. Persistent trusted TLS is validated/copied from the existing
private server directory into coordinator custody; no trust installation,
browser ignore flag or hostname validation change occurs here. Bridge mTLS
uses a separate owned certificate directory.

`ready.json` contains the safe public entrance
`https://localhost:3543/api/auth/login` and original runtime/Next PIDs. It requires
the exact owned Next bind announcement and verified HTTPS readiness. API HTTPS
is also checked with the owned CA. Readiness means startup, not device/native
verification acceptance. A foreign listener is never reused or killed.

Root opens that normal entrance in direct controlled Chrome, signs in as the
demo OWNER, then opens `/connections` for its demo tenant. For each safe alias,
choose its linked store and click the existing device verification action.
Root must record the actual AVAILABLE inventory and safe **8/4** channel views
from current SQL/native callbacks, refresh/readback, and fixed errors on failure.
Neither a loaded provider nor the historical four-frame native captures proves
this public path. Media PLAYING/continuous browser playback remains separate.

## Durable stop and ownership

Create the owned state directory's `shutdown.json` sibling to stop. **External
stdin EOF is ignored by the coordinator.** It first settles its original Next
handle, then writes `runtime-shutdown.json`; Python closes API, drains the shared
bridge and original native owners, then downgrades/drops only the guarded fresh
database. It finally removes the matching private owner directory.

Resource owners are never killed on reporting deadlines. Python reports an
overrun while keeping the original Popen; Node similarly retains its runtime
custodian beyond the inherited 120-second reporting/130-second observer budgets.
Native pending originals use reviewed `ChildOwner.passive_wait()`/`finish()`;
database/key/private folder remain in custody until confirmed retirement. Next
alone has its inherited exact-handle subordinate termination budget. No PID
lookup, force-tree kill, recreated handle or fake resource-absence receipt exists.
An overrun or abnormal exit still fails even after eventual settlement.

Safe evidence goes under
`.superpowers/verification/local-device-browser-runtime/<local-devices-run>/`:
source before/after hashes, original database custody/source preservation,
coordinator events and bounded cleanup outcomes. Private input, state, cookies,
key/cert files, native captures and SDK logs must not be uploaded. Root must
review actual cleanup/absence/source stability; a source guard failure from
concurrent unrelated changes remains a failed proof. Arrange a stable source
window with the native owner before actual browser execution.

## Verification limits and priorities

The author ran focused offline parsing, source approval/anchor, environment
split, real-provider refusal, durable stop/import/CLI and owned migration/cleanup
seam contracts with inert values and controlled fake owners. No real input was
read, SDK called, database opened/migrated, listener started, browser operated,
Git mutated, or old fixture gate changed. A malformed copied core approval pin
was detected by root, reproduced with an independent anchor test and corrected
before review. Initial missing-module setup errors are not host acceptance;
the separate causal missing activation boundary and inert-provider rejection
were observed failing before implementation/correction.

Final focused host verification: **16 passed**, scoped Ruff/format and Node
syntax checks passed. These tests are source/host contracts only. The separate
root-run protected core-to-M1 check is additional native/SQL evidence, whose
actual outcome belongs in the canonical report; it does not replace the normal
OWNER OIDC, API/proxy/RPC and Chrome gate.

Root must independently review new4 and the exact dependency/constructor map,
approve the new snapshot, run the real OWNER browser path, and verify source
and resource custody. Root keeps actual outcomes in `docs/service-analysis.md`.
`MATCHED=0`; `release_ready=false`.

## Startup review correction — 2026-10-04

Independent initial review returned C0/I2/M0. Fix1 queues an early stop against
the original runtime handle: if its private folder does not yet exist, Node
retries the durable runtime marker until the folder appears or the child retires.
A reporting deadline emits an incomplete custody event once and does not abandon
the handle or terminate the resource owner. This closes the lost-marker case
while retaining the stdin-EOF rule.

Python now admits the new source snapshot before loading borrowed helpers. The
borrowed Python helper also checks its independently approved exact raw identity
and compiles those validated bytes. Node checks its independently approved
borrowed-server SHA256 before dynamic module import, rather than executing a
static unadmitted import. The older fixture, gates and caller/device inputs are
unchanged. Causal offline tests first failed in all three order/stop cases; final
focused verification passed **19 tests**, with Ruff/format/Node syntax checks
passing. Initial4, its review and preimages remain preserved in the Fix1 packet.

Root separately reported successful store1 native metadata/eight channels and
pipe observation followed by a parent post-publication protocol failure in its
protected core-to-M1 probe. That diagnosis is separately owned and does not
establish normal OWNER/API/RPC/Chrome acceptance. The author did not rerun it or
read its private input/captures. Root must independently accept Fix1, preserve
the native source/config closure, then create the new fixture snapshot and run
the actual public path and cleanup. `MATCHED=0`; `release_ready=false`.

## Native source receipt rebind — 2026-10-04

Fix2 changes only the native source receipt path/hash and the guide's protected
SOURCE_REVIEW pointer. Root independently closed the M1 post-publication
correction at `M1-native-inventory-postpublication-source-root-receipt.json`,
exact SHA256 `06aea3adedc19e179aac515e9c962baf6a525ee36dad9b480ad18dde32410483`.
The new protected copy is the `m1-fix1.json` path above. Fixture constructors,
20-second budget, source/authority gates, API/worker split, durable stop and
resource custody remain unchanged. Root's actual two-device core/SQL/M1 and
subsequent OWNER browser gates are separate from this source rebind; this author
executed neither. `MATCHED=0`; `release_ready=false`.

## Direct child launch, Next retirement and truthful issuer text — 2026-10-04

The first actual OWNER Chrome run reached signed login and saved connections,
but verification returned 503. Its new native generation had only an empty
result marker. The fixture's direct-base Python launch added venv packages but
lost `sys.prefix`; the native guard correctly refused that base context before
SDK launch. An inert subprocess reproduced the refusal with the original direct
Popen PID preserved. Fix3 restores the parent's admitted venv prefix before site
and application loading, retaining the direct base executable/handle. The same
real interpreter guard now admits the inert child; no credentials or SDK calls
were used in that regression.

Root stopped the original run: API/worker/runtime settled and database/private
state/source preservation were confirmed, but coordinator shutdown still failed
because Next retained development event-loop handles after `app.close()`.
Fix3 restores deliberate exit0 for that subordinate after awaited app closure,
matching the reviewed original helper. A real inert Node subprocess with an
otherwise retained timer now exits normally. Resource-owner runtime/native
custody and reporting failure rules remain unchanged; prior exit1 is preserved.

The issuer text now distinguishes the synthetic OWNER from real registered
devices used for read-only verification; it no longer says there is no vendor
connection. Causal RED covered all three corrections; focused **22 tests pass**,
with scoped static checks passing. Root independently repeated the focused suite.
The author performed no SDK, protected database, listening server or Chrome run.
Root's actual retry must prove both 8/4-channel views, saved-channel readback after
reload and normal original-process shutdown. `MATCHED=0`; `release_ready=false`.

## Opt-in local media composition — 2026-10-04

Coordinator baseline for this extension is `211d1484aa16eb30f5d362758f149f98dec9dfdf`.
Read [media authority](tvt-local-media-service.md), [WebRTC transport](tvt-local-webrtc.md)
and [Windows decode](tvt-windows-decode.md) with the canonical report. Historical
OWNER inventory8/4 and saved readback remain separate from continuous playback.

`WSO_TEST_LOCAL_MEDIA_BROWSER=1` explicitly selects the media composition; absence
keeps the previous inventory mode and v1 source gate. Other values reject. Only
the fresh uniquely owned database is additionally upgraded from0012 to0013 and
downgraded to0012 before its unchanged0012→0011/original-owner cleanup. No existing
database migration or SQL authority/TTL change is performed by this fixture.

Worker-only composition is `LocalMediaAdmission(workerURL,key)` plus
`LocalMediaExecutor(admission,NativeLocalLiveProvider(reviewed_config))`, wrapped
by `wso_tvt_media.worker.LocalMediaWorker(executor,decoder_executable=Path(...))`
on the existing shared mTLS server's `local_media_worker` slot. The inventory
provider and route remain present. The decoder setting is explicit:
`WSO_TVT_WINDOWS_DECODER_PYTHON` points to the admitted private PyAV19 interpreter
under `.superpowers/runtime/windows-media-decode/venv/Scripts/python.exe`.
Its existing decoder constructor checks the infrastructure venv/base/site;
the fixture does not install packages or invoke it during author tests.

The API receives the opt-in marker but no decoder/native setting or WORKER URL.
Media admission/executor/native constructors are guarded there alongside the
existing decrypt guard. Next receives ordinary auth/HTTPS/API-origin settings
only. Source readiness and a loaded media facade do not establish video delivery
or PLAYING. Root must prove actual offer/heartbeat/frame delivery/stop and cleanup.

Extended core/API/native/frontend sources deliberately invalidate historical
inventory approvals. Media mode requires a **new closed v2 Root approval**, fixed
by the existing explicit FILE+SHA256 launch settings. Its schema is:

```json
{"schema_version":2,"root_explicitly_accepted":true,"scope":"owned-local-device-media-browser-only","sources":{"repository/relative/path":"ROOT_APPROVED_RAW_SHA256"},"private_sources":{"WSO_TVT_WINDOWS_LOCAL_INVENTORY_SOURCE_REVIEW":{"path":"EXACT_LAUNCH_PATH","sha256":"ROOT_APPROVED_RAW_SHA256"},"WSO_TVT_WINDOWS_LOCAL_INVENTORY_RUNTIME_REVIEW":{"path":"EXACT_LAUNCH_PATH","sha256":"ROOT_APPROVED_RAW_SHA256"},"WSO_TVT_WINDOWS_DECODER_PYTHON":{"path":"EXACT_LAUNCH_PATH","sha256":"ROOT_APPROVED_RAW_SHA256"}}}
```

Those strings are documentation placeholders, not candidate acceptance pins.
Root closes all current source reviews and constructs the exact composite map,
including inventory/media/core/native/decoder/WebRTC/API/frontend dependencies,
before real launch. Each protected path must equal its launch environment value
and match its approved bytes before helper/DB execution. Source drift, wrong
version/scope, missing roster and changed private inputs fail closed. The old
v1 anchors still reject drift; the new authority is the separately Root-approved
v2 receipt/hash, never a hash computed live to approve arbitrary changes. The
unchanged borrowed helper pins remain mandatory in both modes.

Media shutdown retries the same original `LocalMediaWorker.shutdown()` while it
returns False, retaining its sources/event loop/thread/native/decoder owners.
Only after True may media admission shutdown complete; only then does ordinary
inventory/native/worker/database/key cleanup proceed. Reporting deadlines retain
the original worker/custodian. No unconfirmed media owner is converted into CLOSED
or resource absence. This fixture changes no player, API/core/native protocol or
decoder semantics.

Causal offline RED covered opt-in, worker-only decoder handoff, retained media
shutdown and v2 protected-source authority. Focused inventory/media host contracts
and static checks are reported in the minimal media packet. Migration/retirement
tests use controlled inert owners, not PostgreSQL or cameras. The author opened
no browser/listener/database, invoked no SDK/decoder/certificate changes, read no
real CCTV input and made no Git action. Root owns actual playback and canonical
execution reporting. Final v2 approval is **pending Root**, not supplied by this
guide. `MATCHED=0`; `release_ready=false`.

## Optional stage-1 observation preparation — 2026-10-05 (R134)

Source baseline: controller review tree `881a18b8776311efabc398e16ab9ac411fa98c9c`,
with Tasks 1–6 and native registry fixes already present in the uncommitted
worktree based on `6436748`. This section documents fixture preparation only;
source review, new c6 approval and actual twelve-tile acceptance remain separate.
Read this section before reusing the observation helper and update its evidence
after later changes. The fixture still hosts the synthetic OWNER's normal
API/RPC/native/decoder/WebRTC/Next pipeline for the two owned recorders.

Set `WSO_TEST_LOCAL_MEDIA_OBSERVE=1` together with the existing explicit media
activation to collect the bounded private observations. It is absent by default.
Keep `WSO_TEST_LOCAL_MEDIA_TRACE` absent. `observation.py` and its focused contract
test are in `MEDIA_SOURCES`, so a new media approval must pin both. No SDK callback,
wire parser, native owner registry, authority constant, database or frontend
behavior is changed by this observation preparation.

Python publishes `measurement_owner` at API/worker readiness and in
`runtime-owner.json` for the runtime. Node adds its owner to `next-bound.json`
and the coordinator's `ready.json`. Each owner is the closed object
`{role,pid,creation_filetime}`; creation FILETIME is a decimal **string**, preserving
all bits through JavaScript JSON. Python reads its current pseudo-handle.
Node synchronously invokes a trusted existing Python helper while Node is still
alive, using structured arguments and separate bounded five-second discovery
and identity calls. Direct base Python bypasses the Windows venv redirector;
the helper verifies Node is its original parent, opens a read-only query handle,
checks process identity and STILL_ACTIVE, reads exact FILETIME and closes that
query handle. No cleanup custody moves to the helper. Failures publish only
`measurement_owner_error: IDENTITY_UNAVAILABLE`, which cannot satisfy measurement
admission; default-off readiness schemas remain unchanged.

The controller privately composes `measurement-owner-identities.json` inside
the exact run's state folder as `{run,owners:[...]}`, matching the run name and
existing readiness PIDs. Read the five owner objects above; supply Chrome and
PostgreSQL from Root's retained original handles and verify coordinator identity
against the original Root child as well. Require exactly the seven roles
coordinator/runtime/next/api/worker/chrome/postgres, and reject any unavailable
record or mismatch. Never replace a missing original with a later PID lookup.
Identity records remain private; reports and measurement stdout contain no
PID, creation-time or command-line values.

The worker persists `media-observation.json` in its existing private evidence
run directory, outside the disposable auth-state folder. A separate optional
writer samples once a second; it has no SDK or transport calls. Data is bounded
to 256 attempts and peers, with two recorder ordinals and explicit omitted and
observation-failure counts. Recorder ordinal is assigned by first observed
credential identity (only its digest is retained privately in memory). Establish
store correspondence with the planned sequential one-tile-per-store trial;
do not assume concurrent start order matches the store UI order. Channel ordinal
is the provider selection ordinal. Attempt numbers distinguish reopen/focus
cycles. No credential digest or device/session/channel/task identifier is emitted.
Private generation/session/channel/task binding only correlates the later peer
to its attempt in memory and is removed on use; failed preparations leave at
most the bounded attempt roster.

Each successful original provider return projects its already parsed first
`PrivateLiveFrame`: `source_context[1]` is the actual ep3 media kind, separately
from `requested_stream`; `summary()` supplies source codec, width and height.
`sub_stream_adaptation_off` is the original parent's accepted ACK warning.
`OPEN_RETURNED` establishes neither successful decoding nor browser rendering.
The exact original session is returned without wrapping its lifetime; original
proof, first-keyframe and decoder validation remain in their existing paths.
Open failures retain the original exception and record only `OPEN_FAILED`.
Metadata failures record a fixed unavailable outcome without throwing away the
original session. The helper never reads or emits raw payload, SDP or GUIDs.

The fixture peer subclass enables three optional integer counters in `live.py`;
ordinary peers keep `observation_counts=None`. `permit_lapse_episodes` counts
observed transitions into stale state after a successful lifetime check, across
watcher/track/transport observations. It does not count every SQL delay or every
physical deadline crossing. `withheld_datagrams` counts actual calls at the
existing `_send_rtp` gate withheld by a false permit, including RTP/RTCP and
retransmit traffic passed through that gate. `withheld_decoded_frames` counts
frames actually consumed and withheld by the track's stale branch. No predicate
is reevaluated for measurement, no bytes are retained, and no transport decision
changes. Peers expose safe attempt correlation and their separate counters.

Writer errors are swallowed and counted. The observer is a daemon containing
only metadata; stop waits at most 200 ms for it after normal server retirement,
so a blocked writer cannot retain API/native/decoder/database resources. Summary schema2 uses `stop_requested` only; this is never a completion claim.
Completion requires the independent original-custodian terminal and exact
summary digest described in fix1 below. The existing private writer atomically
replaces the summary. Missing/stale data or reporting failure invalidates the
measurement, never establishes acceptance.

Verification on 2026-10-05: causal RED/GREEN covers default-off/schema/actual-kind,
exact identity bits, current Python and synchronous Node self probes, private
attempt/peer correlation, original open failure and resource preservation,
bounded rosters, writer failure/bounded stop, and actual permit withholding.
No service, SDK, recorder, browser, SQL or listener was launched by this author.
Focused final counts and static limitations are recorded in the Task7 handoff;
existing untyped/TRACE formatting debt in `runtime.py` remains outside this
change. Actual recorder codecs/kinds/warnings, load sizing and browser acceptance
are open Task7 questions. `MATCHED=0`; `release_ready=false`.

### R134 fix1: durable completion after bounded writer shutdown — 2026-10-05

Independent review I1 reproduced a delayed final snapshot publishing the old
finished=true/failures0 record after close had timed out and counted a failure.
That initial completion gate is withdrawn. The correction keeps the 200 ms join
bound and separates stop request, final publication, and custodial completion.

`media-observation.json` is now schema2, with `stop_requested` replacing
`observation_finished`. Its writer can publish summaries only. The observer's
`close()` returns a separate cached terminal decision that the writer cannot
replace. Timeout/failure remains FAILED even if the outstanding snapshot is
successfully published later. COMPLETE requires the original writer thread to
have settled, a final stop-requested snapshot to have been published successfully,
zero failures and zero omitted attempts/peers. Subsequent close calls return a
copy of the same decision. A SHA256 binds the terminal to the final summary.

After original server retirement and the bounded observer join, the existing
original worker writes this terminal as `mediaObservation` in its existing
private `bridge/worker-close.json`. No new synchronous observation writer is
added. After settling the original worker, the original runtime reads the
bounded closed terminal schema and preserves it as `mediaObservation` in its
existing evidence `resources.json`. This file survives auth-state removal.
Missing/malformed worker records produce only `{schema_version:1,status:
"UNAVAILABLE"}` and cannot certify observation. Original cleanup/resource
proof remains separately required.

Controller final gate: wait for the original fixture custodians to settle;
read same-run `media-observation.json` and `resources.json.mediaObservation`
from `.superpowers/verification/local-device-browser-runtime/<run>/`. Require
`complete_observation(summary, terminal)` from the pinned fixture helper to
return true. It checks the closed terminal schema, status COMPLETE,
writer_settled=true, failures/omissions zero, summary schema2 and
stop_requested=true, and matching canonical SHA256. Canonical encoding is
Python `json.dumps(summary, sort_keys=True, separators=(",", ":"))` encoded as
UTF-8. The terminal's exact keys are schema_version, status, writer_settled,
observation_failures, omitted_attempts, omitted_peers, snapshot_sha256.
A late summary alone never satisfies this gate. Require the normal whole-run
resource/source/privacy checks in addition; COMPLETE describes observation,
not actual video acceptance.

Fix1 validation reproduced a final write blocked beyond close return, then
allowed that original write to finish. Its late snapshot still has zero failure
count, while the independently persisted custodial terminal stays FAILED and
the combined gate rejects it. Other cases cover final writer exception, clean
final publication/digest binding, missing/extra terminal fields, existing
writer/startup failures and default-off behavior. The focused fixture/WebRTC
suite passes76 tests; scoped Ruff/format, helper+live strict mypy and Node syntax
checks pass. Runtime's existing isolated88 mypy errors remain unchanged. No
service, recorder, browser or SQL acceptance occurred; independent re-review is
pending.

### Optional first-failure diagnostics after failed c6 — 2026-10-05

The c6 run's first-start 503 and later heartbeat 404 remain unexplained. This
addition records the first observed terminal boundary and up to six successful
milestones per worker source attempt; it does not change admission, validation,
stream format policy, leases, deadlines, retries or resource ownership. Read
this section before reuse and update its evidence after source review/execution.

Both existing flags remain required: `WSO_TEST_LOCAL_MEDIA_BROWSER=1` and
`WSO_TEST_LOCAL_MEDIA_OBSERVE=1`. Without opt-in the worker observation factory
and source/peer callbacks are absent. The original synchronous worker start
creates an ordinal before executor startup; the same original thread privately
correlates the native provider attempt. A failed pre-peer start therefore still
has a diagnostic record. No lease ID, binding, credential digest, exception
text, SQL, SDP or media is exported by this addition.

Additive summary schema2 fields:

| Field | Meaning / bound |
| --- | --- |
| `source_attempt_count` | Number of observed worker starts. |
| `omitted_source_attempts` | Starts beyond the existing observation limit (maximum 256 retained). |
| `source_attempts[]` | At most 256 entries: `source_attempt`, `first_failure`, `milestones`. |
| `first_failure` | Null until a terminal boundary is observed; then exactly `stage`, `reason`, `elapsed_ms`. First entry is sticky through later cleanup. |
| `milestones[]` | At most six entries, each exactly `stage`, `elapsed_ms`; each milestone occurs at most once. |
| `attempts[].source_attempt` | Safe worker ordinal correlating a native provider row, including failures before peer creation. |

Times are integer monotonic milliseconds since the original worker attempt began,
clamped to 0..2147483647. They do not provide wall-clock timestamps or a common
cross-attempt origin. Milestone stages are `native_return`, `first_adapter_packet`,
`first_decoded_frame`, `binding_ready`, `peer_created`, `peer_connected`. The
decoded milestone means decoder output exists, even if publication authority
then fails; it does not establish accepted browser delivery.

Failure stages cover executor startup, worker preparation/retirement/proof,
source creation/start/binding, adapter validation, ingress read/queue, decoder
creation/decode, publication/renewal authority, source-current, and peer checks,
renewal deadline/watch/connection/close. `FAILURE_STAGES`, `FAILURE_REASONS` and
`MILESTONES` in the pinned observation helper are the closed export enum lists.
Specific adapter reasons include `format_changed`, `identity_changed`,
`timestamp_invalid`, `scope_invalid`, `metadata_invalid`, `framing_invalid`,
`header_invalid`, `picture_unsupported`, `initial_picture_unsupported`, and
`parameter_sets_missing`. The H264 combined original check is conservatively
reported as `parameter_sets_or_idr_missing`. Actual queue overflow is distinct
from source stop; peer current-false/error, deadline, stale-permit and connection
failure/close are distinct. An otherwise unclassified scheduled peer retirement
records `peer/close_scheduled` before source cleanup. Normal requested cleanup
may be the first record (`explicit_close`); that is not a diagnosed fault.

Normalized native/core errors retain only their already available fixed class
such as denied/deadline/protocol-invalid/failure. Decoder failures remain coarse:
this observation does not distinguish decoder inactivity, binary dimension
mismatch or packet rejection when that boundary erased the reason. Core sticky
denial can already combine SQL NULL, database errors and wait timeout; no new SQL
or core hook is added. First observed boundary is evidence for investigation,
not proof of the underlying cause or of global event ordering.

The callback performs bounded memory updates only. It does not reevaluate an
authority predicate, issue SQL, perform writer I/O, or retain original resource
objects. Observer exceptions are isolated from media decisions and cleanup.
The existing independent periodic writer, bounded join, sticky terminal and
canonical snapshot hash remain authoritative. Terminal `omitted_attempts` now
counts omitted native attempts **plus** omitted source attempts, so either
truncation prevents COMPLETE. The snapshot retains both separate omission
counts. No new terminal fields or alternate completion path are introduced.

Controller recipe: freeze and review the changed source closure; obtain the new
immutable approval before a small recorder/browser run. Keep c6 evidence intact.
After original custody settles, use the same helper
`complete_observation(summary, resources.mediaObservation)` gate, then inspect
each correlated native/source ordinal's first failure and six milestone slots.
Require zero omissions/failures and the usual cleanup/source/privacy evidence.
Record the smallest failed boundary before deciding any behavioral correction;
do not infer decoder dimensions, expired SQL TTL or a format transition from a
coarse failure. Actual four/twelve-view acceptance remains failed/pending.

Executed offline validation: 166 focused media/worker/WebRTC/observation/runtime
fixture tests passed; two Node/self-identity process probes were deselected.
Causal RED runs preceded implementation (9 initial missing-hook failures,
5 worker/peer hook failures, one missing scheduled-close boundary and one missing
decoded-before-publication milestone). Seven changed non-runtime files pass
Ruff check/format; four production/helper files pass strict mypy with silent
dependency traversal. Runtime's one wiring addition has fixture static/import coverage; no actual
runtime composition or whole-runtime static success is claimed. No SDK, recorder, browser,
database, service or dependency operation occurred. Source review and a newly
approved actual reproduction are still required.
# R137 transition observations — 2026-10-06

**R138 update (2026-10-06):** source FIFO pressure now waits under the same
16-frame/4MiB cap with a5s bound and current/stop checks. Optional observation
accepts the additional fixed first-failure reason `ingress_queue/wait_timeout`;
`overflow` remains a hard admission violation. No new metadata, identifiers,
terminal fields or completion gate were added. c8's six overflow observations
remain immutable historical evidence. A new native-parent credit guard requires
independent source/native review and a newly pinned approval before actual
execution. No new device/Chrome/SQL acceptance is implied by inert pressure tests.

Read with the existing R136 observation contract below and the canonical service
report. The retired c7 run established `adapter/format_changed` as the first
failure for measured source attempts; older c6 uncertainty below remains dated.
The current source repair enables bounded same-codec decoder rotation and needs
independent review/new immutable approval before any actual 1/4/12-tile run.

Both opt-in flags remain required. Each `source_attempts[]` entry now additionally
contains `transition_counts`, `format_transitions`, and
`omitted_format_transitions`. Five fixed counter names are `started`,
`decoder_rotated`, `inter_picture_omitted`, `output_verified`, and
`late_output_omitted`; each saturates at2147483647. At most sixteen safe format
records are retained per attempt, each with `old` and `new` objects containing
only `codec`, `width`, `height`, plus bounded `elapsed_ms`. Codec must be equal
on both sides and one of `h264`/`hevc`; dimensions obey4096×2160 and16MiB RGB
caps. Additional format records increment a bounded omission counter; all fixed
event counters continue. This diagnostic truncation is explicit, distinct from
omitted whole attempts, and does not change the terminal completion gate.

These nonterminal events never become `first_failure`. Added terminal stages
are `format_transition` and `decoder_retire`; added fixed reasons are
`transition_deadline` and `rotation_limit`. Existing `adapter/format_changed`
still identifies rejected codec changes (and standalone strict adapter use).
No exception text, identifiers, media, source objects or authority is exported.
Unknown values fail observation evidence without changing resource ownership.

Controller interpretation: `started` records a fully header-validated dimension
observation; `decoder_rotated` records successor allocation after actual old
retirement; `output_verified` records current-format validated RGB publication.
None establishes browser rendering. `inter_picture_omitted` counts only validated
waiting-for-configuration pictures; `late_output_omitted` counts old-epoch RGB
discarded at publication. Review current source hashes and freeze them before
creating approval; keep c7 evidence immutable and use the original terminal/hash
and cleanup gates. Offline observation selection passed19 tests. Real decoder
synthetic and local WebRTC checks are documented in the media/decoder guides;
no new recorder, Chrome, runtime service or SQL acceptance was performed.
