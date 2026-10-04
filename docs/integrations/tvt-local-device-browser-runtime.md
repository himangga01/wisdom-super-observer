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
