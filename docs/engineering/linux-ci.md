# Disposable Linux verification

`.github/workflows/verify.yml` verifies the implemented foundation, identity,
HTTPS web authentication and connection features on `ubuntu-24.04`. It runs on
pushes to `main` and `codex/**`, ordinary pull requests, and optional manual
dispatch. The job has a 30 minute deadline and cancels an older run for the same
branch or pull request. Its repository token has read-only contents permission;
checkout does not persist credentials. Every action is pinned to a full commit.

The foundation and actual T05 worker recovery runs are recorded below.
Windows PostgreSQL tests cannot prove Linux process or broker behavior.

## Runtime and checks

| Component | Selected version or gate |
| --- | --- |
| Python / uv | 3.12.10 / 0.12.19 (`python -m uv`) |
| Node / pnpm | 24.21.0 / 11.25.0 |
| Python dependencies | `uv sync --locked --all-packages --group dev` |
| JavaScript dependencies | `pnpm install --frozen-lockfile` |
| PostgreSQL | Official `postgres:17.11`, pulled and run by immutable digest |
| Valkey | Official `valkey/valkey:9.1.2-alpine3.24`, pulled and run by digest |
| Browser | Playwright's official Chrome installation for the auth `chrome` channel |
| Main gate | `pwsh ./scripts/verify.ps1 -WithPostgres -WithAuthBrowser -WithJobBroker` |
| Job transport | Celery 5.6.3 / Kombu 5.6.2 / Redis client 6.4.0, immutable Python lock |
| Broker fixture smoke | `bash scripts/dev/valkey-smoke.sh` |

The main gate runs the full non-live Python suite, rejects skipped selected
PostgreSQL integration cases, checks Python types/lint, frontend types/lint/tests
and production build, verifies deterministic checked-in contracts, and runs the
HTTPS auth browser suite. WithJobBroker additionally selects the ten mandatory
real recovery cases and checks their actual JUnit nodes for zero skips, failures
or errors. Test counts grow with implementation; use the observed run's counts.
The T05A migration extends the job from eight to nine PostgreSQL URLs and bypasses the
Windows runtime loader. `WSO_TEST_PYTHON` points the HTTPS fixture at
`.venv/bin/python`. The local TVT Chrome/Edge preflight remains a separate gate;
this job does not assume Edge is installed.

## PostgreSQL provisioning boundary

The workflow creates a uniquely named and labelled PostgreSQL container and data
volume, binds an assigned port on `127.0.0.1`, and generates its admin password
in memory. Docker receives the password through the environment. The helper
`scripts/dev/provision-ci-postgres.py` accepts only these inputs:

| Environment variable | Requirement |
| --- | --- |
| `CI` | Exactly `true` |
| `WSO_CI_DISPOSABLE_POSTGRES` | Exactly `1` |
| `WSO_CI_ADMIN_DATABASE_URL` | Explicit `postgresql+psycopg` URL, `postgres` user, password, literal `127.0.0.1`, explicit port, exact database `wso_ci_test`, no query overrides |
| `WSO_CI_RUNTIME_OWNER` | Unique UUID hex matching the running container's name and ownership label |
| `GITHUB_ENV` | Existing environment file supplied by GitHub Actions |

Before migration, the helper verifies the container's immutable PostgreSQL image,
loopback endpoint and running state. The connected server must report PostgreSQL
17.11, the expected database/admin/owner, only the default public schema and
plpgsql extension, no user objects or application roles, and no other business
databases. Existing data, schema, roles, query-based host redirects, a real local
fixture URL, a shared container, or a mismatched endpoint cause refusal.

The helper applies Alembic `head`; migrations create the roles. It requires all
eight restricted LOGIN roles to exist at `0003a_assets` and validates that they have no superuser, createdb,
createrole, replication, bypass-RLS, inherit, or role-membership privileges.
It assigns distinct random passwords, grants the migrator database schema
creation rights required by migration fixtures, tests each restricted login,
and exports `WSO_TEST_{ADMIN,APP,IDENTITY,MIGRATOR,SESSION,WORKER,DISPATCH,JOB,ASSET_MAINTENANCE}_DATABASE_URL`.
The sealed T05 baseline retains its original eight-URL schema and provisioner.
It never creates missing roles itself and never alters the Windows cluster.

Passwords and complete URLs are masked before environment export. SQL driver
errors are reduced to a sanitized failure class. PostgreSQL statement/error SQL
logging and container logs are disabled. No credential file is saved. Cleanup
checks each uniquely named container/volume's owner label before deleting it.
No broad Docker pruning or shared database cleanup is used.

## Valkey smoke and the T05 boundary

The smoke creates its own labelled containers and volumes with loopback-only
published ports, 128 MiB bounded memory, `noeviction`, and AOF configured with
`appendfsync always`. It checks PING, the actual 9.1.2 server version and enabled
AOF, writes synthetic values/queue references, SIGKILLs and restarts the same
container, and confirms the acknowledged fixture data survived. It then starts
a separately owned empty volume and proves the original fixture is preserved.
Cleanup checks exact ownership labels for both containers and both volumes.

The pulled digest and successful smoke description appear in the job summary
and ignored `.superpowers/verification/valkey-runtime.txt`. AOF `always` is a
deterministic test choice; it does not establish production performance or
external-write semantics.

The separate smoke does not run Celery workers, publish through
Kombu, kill dispatcher/worker processes, fence stale leases, verify tenant/actor
scope at delivery, or reconcile DB requests after broker data loss.

The T05 recovery suite uses actual prefork Celery subprocesses and Kombu over
separately owned Valkey containers/volumes, with the recorded 9.1.2 digest.
It selects producer/dispatcher/worker crash boundaries, committed-effect replay,
AOF restart, empty-broker reconstruction, external uncertainty/reconciliation,
and queue isolation. Its PostgreSQL fixture requires the exact CI database,
administrator identity and owned container mapping. Missing Linux/runtime,
missing mandatory tests, zero collection or any skip/failure/error fail the
selected gate. See [durable jobs](durable-jobs.md) for the authority and outcome
boundaries. The actual T05 result is recorded below.

## First recorded Linux run — 2026-09-30

[Run 36703370870](https://github.com/himangga01/wisdom-super-observer/actions/runs/36703370870)
completed successfully for commit `5dae70a8ffaad4660841221abd59ffbc5b524ded`.
Actual PostgreSQL migration/provisioning and Python tests passed (230 passed,
zero skips). Ruff, strict mypy, FE typecheck/lint, 15 unit tests, production
build, deterministic contracts and the 77-case checker passed. The HTTPS
authentication/connection Chrome suite passed 26/26. The local Windows run
separately checked desktop Chrome/Edge; this Linux run did not run that Edge
preflight or a handset/media comparison.

The pulled runtime inputs were:

- PostgreSQL: `postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`.
- Valkey: `valkey/valkey@sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11`.

Valkey's actual 9.1.2 server, PING, enabled AOF, SIGKILL/restart persistence and
separately owned empty-volume checks passed. Owned PostgreSQL and broker
fixtures were removed successfully. These are recorded test-run digests;
production image selection remains separate. That first run did not test T05
real worker recovery; the subsequent result follows.

## First T05 recovery run — 2026-09-30

[Run 36716200713](https://github.com/himangga01/wisdom-super-observer/actions/runs/36716200713)
completed successfully for reviewed commit `6565929776c2ff5b9ff55670bc4567b6d2cf4821`.
The ordinary Python suite passed 537 cases with zero skips; the separate actual
Celery/Valkey recovery suite passed all ten required cases in 257.02 seconds.
The strict JUnit checker confirmed the exact required set and zero skips.

These real cases cover producer/dispatcher interruption, worker child and full
process loss before effects, committed-effect replay before ACK, broker AOF
restart, empty-broker reconstruction, submitted external-write reconciliation,
unresolved uncertainty blocking resubmission and queue isolation. They use
actual prefork Celery 5.6.3, Kombu 5.6.2 and Redis client 6.4.0. Original orphan
reservation restoration, explicit ACK observations and owned pidfd signaling
were exercised by the accepted fixture. The same PostgreSQL and Valkey digests
listed above were observed; they are test inputs, not production approval.

Ruff, mypy on 26 source files, FE typecheck/lint/build, 15 FE unit tests,
15 deterministic generated documents, the 77-row checker and 26 HTTPS Chrome
cases passed. Separate Valkey persistence smoke and owned-resource cleanup also
passed. Its legacy message about pending T05 work describes that smoke's own
scope; the distinct ten-case gate above supplies the recovery result.

The masked run log is retained locally in ignored
`.superpowers/verification/linux-ci-36716200713.log`. No S3/private asset,
handset/media, vendor effect, production deployment or APK comparison was tested.

## Private asset baseline RED probe

The separate `Private asset baseline RED proof` workflow prepares a fresh owned
Linux PostgreSQL fixture and runs only the initial photo-upload case against
sealed T05 commit `6565929776c2ff5b9ff55670bc4567b6d2cf4821`. An explicit overlay
copies the provider/HTTP fixture and locked dependency/test infrastructure;
it copies no asset product code, contracts, routes or migrations. PostgreSQL
uses the recorded immutable digest above. The selected provider's exact artifact
identity and actual private IAM capabilities must be observed before any RED proof.

Success of this probe means the actual S3 and authenticated HTTP/CSRF preflight
passed, then the missing asset route returned 404 versus expected 201. The
strict RED checker requires pytest exit 1, exactly the named assertion failure,
zero setup/teardown errors or skips, the sealed source SHA and a bounded
sanitized receipt. Import errors, provider incompatibility, failed auth and
an arbitrary failing test cannot satisfy it. The first attempted run is recorded
below; it did not satisfy the RED gate.

This is an initial missing-feature proof, **not successful asset implementation**.
The full T05A gate still requires all fourteen actual lifecycle/recovery cases
and its separate strict GREEN checker. Ordinary/offline and local PostgreSQL
verification explicitly exclude the Linux-only asset acceptance file; the
separate workflow selects it deliberately and cannot skip a missing runtime.

### Provider profile foundation run

[Run 36733796406](https://github.com/himangga01/wisdom-super-observer/actions/runs/36733796406)
passed for commit `dbe68fa6d0c6e32c9d25f7811eeb608da4c7a94a`. The ordinary Python
suite passed 696 cases with zero skips in 101.23 seconds; the separate actual
Celery/Valkey recovery suite passed all ten cases with zero skips in 252.83
seconds. Ruff, mypy on 26 source files, 15 frontend unit cases, frontend
typecheck/lint/build, 15 deterministic generated documents, the 77-row checker,
26 HTTPS Chrome cases, Valkey smoke and owned-resource cleanup passed.
PostgreSQL and Valkey used the same recorded digests above.

The additional ordinary cases verify fixture safety and strict result gates;
this run did not exercise private asset storage or upload routes.

### First private asset probe: provider setup failed

[Run 36726648510](https://github.com/himangga01/wisdom-super-observer/actions/runs/36726648510)
used the same infrastructure commit, with the product source sealed at
`6565929776c2ff5b9ff55670bc4567b6d2cf4821`. Locked Linux dependencies and owned
PostgreSQL migration/provisioning succeeded. The selected photo test reported
one setup error in 8.67 seconds: SeaweedFS 4.47 returned `NotImplemented` for
`PutPublicAccessBlock`. The strict RED checker rejected the incomplete receipt;
owned PostgreSQL cleanup succeeded. No authenticated HTTP or completed provider
preflight was reached, and no meaningful missing-feature RED was accepted.

### Second private asset probe: required ACL refusal failed

[Run 36733796553](https://github.com/himangga01/wisdom-super-observer/actions/runs/36733796553)
used infrastructure `dbe68fa`, still sealing product source at `6565929`.
PostgreSQL and dependency setup succeeded. The selected test reported one
setup error in 9.08 seconds: `bootstrap public ACL/grant refusal` failed.
The diagnostic does not distinguish an accepted request from an unexpected
error; it establishes that the required refusal was not proven. The strict RED
gate rejected incomplete evidence. No actual HTTP preflight or meaningful
missing-feature RED was accepted. SeaweedFS 4.47 is excluded as this fixture's
candidate.

The replacement candidate is official MinIO
`RELEASE.2025-04-22T22-12-26Z`, with an independently pinned official `mc`
client. Its proposed `minio-inert-acl-dedicated-bucket-v1` profile requires
actual signed byte checks and anonymous GET/HEAD denial after every public ACL
attempt. It claims neither AWS PublicAccessBlock nor BucketOwnerEnforced
compatibility. Each installation requires a separate private bucket and
distinct runtime credentials. Artifact hashes, local image identity and
all actual capability checks must be recorded before a receipt is accepted.
The [private asset runbook](private-assets.md) records the portability and
containment constraints. Actual MinIO acceptance remains pending.

### Asset primitive run: tests passed, Linux typing gate failed

[Run 36737333575](https://github.com/himangga01/wisdom-super-observer/actions/runs/36737333575)
at `aedbe2d4c85f208d65c50a9ffdc27f72a602667e` passed 855 ordinary Python cases
with zero skips in 115.58 seconds and ten actual recovery cases with zero skips
in 249.25 seconds. Ruff passed. Linux mypy then failed at the Windows-only
`msvcrt.get_osfhandle` reference in `asset_crypto.py`; the frontend/browser and
Valkey smoke gates were not reached. Owned PostgreSQL cleanup succeeded.
This run is **failed**, despite the passing test subsets. A minimal platform
guard was independently reviewed and passed focused Linux/Windows typing and
crypto checks; its subsequent full Linux run remains to be observed.

### Previous recorded foundation run

[Run 36742382150](https://github.com/himangga01/wisdom-super-observer/actions/runs/36742382150)
at `e3865dff7d947d90a31ff3baa941f7a1c68731c9` passed after the minimal
Windows-import typing correction. It verified 855 ordinary Python cases with
zero skips in 116.33 seconds and ten actual Celery/Valkey recovery cases with
zero skips in 250.27 seconds. Ruff, strict mypy on 35 source files, frontend
typecheck/lint/build, 15 frontend unit cases, 15 deterministic exports, the
77-row checker, 26 HTTPS Chrome cases and the Valkey smoke passed. Owned
PostgreSQL cleanup succeeded. General Chrome/Edge preflight and the separate
Compose container gate were not selected. This is foundation evidence;
private-asset provider and lifecycle acceptance remain separate.

### Previous recorded Linux foundation run

[Run 36751744939, job 110011840693](https://github.com/himangga01/wisdom-super-observer/actions/runs/36751744939/job/110011840693)
at commit `d8530aeeca3e2c8863597ecbb3dcec1f8a47b9a2` succeeded. It passed 887
ordinary Python cases with zero skips in 116.89 seconds and ten actual recovery
cases with zero skips in 250.16 seconds. Ruff and strict mypy on 35 source files,
frontend typecheck/lint/build and 15 frontend unit cases, 15 deterministic
contract exports verified twice, the 77-row evidence checker, and 26 HTTPS Chrome
cases in 58.1 seconds all passed. The Valkey persistence smoke and owned fixture
cleanup also passed. General Chrome/Edge preflight and Compose were not selected.
This run is foundation evidence; it does not exercise the private-asset provider
or lifecycle acceptance.

### Latest integrated Linux foundation run

[Run 36760448179, job 110041356232](https://github.com/himangga01/wisdom-super-observer/actions/runs/36760448179/job/110041356232) at product HEAD `0deeb79024fccf6bb7e6e3157aceadd39674da77` succeeded. It passed 1200 ordinary Python cases with zero skips in 129.82 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 247.76 seconds; the recovery checker confirmed the exact ten required cases. Ruff and strict mypy on 40 source files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical contract exports were verified twice, the 77-row checker passed, and HTTPS Chrome passed 26 cases in 47.1 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

This run selected the actual PostgreSQL migration/provisioning gate, including the isolated `0003a_assets` migration and nine-role integration in the ordinary test invocation; only the aggregate pytest count is recorded here. PostgreSQL used the recorded digest `d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`; the pinned Valkey digest was unchanged. This run closes the product-Linux foundation boundary at `0deeb79`. It predates later gate/relay changes, including the scoped relay fix approval, and does not cover them. General Chrome/Edge preflight and Compose were not selected. Provider privacy/IAM, the authenticated baseline RED proof, and the full fourteen-case GREEN gate remain open.

### Third private asset probe: data volume verification failed

[Run 36749047523](https://github.com/himangga01/wisdom-super-observer/actions/runs/36749047523)
at `b02703d075f86f1e57be4fec05539dc2ff7f88cb` installed locked dependencies
and provisioned the owned PostgreSQL fixture successfully. The selected test
reported one setup error in 6.62 seconds while checking the actual MinIO data
volume UID/GID/mode before server execution. The generic exception did not
preserve the observed metadata, so the cause is under investigation. No MinIO
privacy/IAM acceptance, HTTP preflight or meaningful missing-feature RED was
established. The strict checker refused the incomplete receipt. Owned
PostgreSQL cleanup succeeded; the candidate remains unaccepted.

### Fourth private asset probe: data-volume mode rejected

[Run 36751745062](https://github.com/himangga01/wisdom-super-observer/actions/runs/36751745062)
reported one setup error in 7.71 seconds. The observed MinIO data-volume entry
was owned by UID/GID `65532:65532` with mode `0755`; the fixture's required
private-mode check stopped setup before MinIO ran. The strict RED receipt was
rejected. This records the actual metadata for this attempt; no HTTP, provider
privacy/IAM, or missing-feature result was established.

### Fifth private asset probe: loopback publication check failed

[Run 36754155359, job 110020003744](https://github.com/himangga01/wisdom-super-observer/actions/runs/36754155359/job/110020003744)
reported one setup error in 5.97 seconds. The data-volume check passed with the
required `0700` mode, then fixture setup failed its owned-loopback-publication
check. The returned port fields were not captured, so the actual mapped-port
shape is unknown. The strict RED receipt was rejected; this was not an HTTP or
provider-privacy result. The owned PostgreSQL cleanup step ran.

Pinned Moby v28.0.4 source returns before installing port options for an Internal
network ([`daemon/network.go`](https://github.com/moby/moby/blob/v28.0.4/daemon/network.go#L860)).
That source behavior is consistent with the fixture publication failure, but it
does not reveal the uncaptured port fields from the run. A fixture-only opaque
loopback TCP relay topology has been accepted for implementation; its code and
actual Linux connectivity remain unverified.

## Evidence handling

The workflow uploads no artifacts. Auth state, browser traces/screenshots and
runtime credentials remain in the disposable runner and are excluded from
publication. Logs and summaries retain check outcomes, versions and immutable
image digests. The job does not access TVT devices, provider accounts, KMS,
production services, publishing or deployment.

Official references: [GitHub Linux service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers),
[official PostgreSQL image version catalogue](https://github.com/docker-library/official-images/blob/master/library/postgres),
[Valkey image/download catalogue](https://valkey.io/download/),
[Valkey persistence](https://valkey.io/topics/persistence/), and
[Playwright browser installation](https://playwright.dev/docs/browsers).
