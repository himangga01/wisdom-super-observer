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

### Linux foundation run 36760448179

[Run 36760448179, job 110041356232](https://github.com/himangga01/wisdom-super-observer/actions/runs/36760448179/job/110041356232) at product HEAD `0deeb79024fccf6bb7e6e3157aceadd39674da77` succeeded. It passed 1200 ordinary Python cases with zero skips in 129.82 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 247.76 seconds; the recovery checker confirmed the exact ten required cases. Ruff and strict mypy on 40 source files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical contract exports were verified twice, the 77-row checker passed, and HTTPS Chrome passed 26 cases in 47.1 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

This run selected the actual PostgreSQL migration/provisioning gate, including the isolated `0003a_assets` migration and nine-role integration in the ordinary test invocation; only the aggregate pytest count is recorded here. PostgreSQL used the recorded digest `d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`; the pinned Valkey digest was unchanged. It is the distinct 0deeb79 receipt and does not cover the later f79c83 foundation state. General Chrome/Edge preflight and Compose were not selected. Provider privacy/IAM, the authenticated baseline RED proof, and the full fourteen-case GREEN gate remained open.

### Linux foundation run 36765314386

[Run 36765314386, job 110057881132](https://github.com/himangga01/wisdom-super-observer/actions/runs/36765314386/job/110057881132) at product HEAD `f79c83eb01ff4486b097dd159d1d1f36dabd4238` succeeded. It passed 1375 ordinary Python cases with zero skips in 139.16 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 251.40 seconds; the strict checker confirmed exactly ten. Ruff and strict mypy on 40 source files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical exports were verified twice, the 77-row checker passed, and HTTPS Chrome passed 26 cases in 55.5 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

This is a separate newer foundation receipt. PostgreSQL used the same recorded digest `d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f`; the pinned Valkey digest was unchanged. This run predates and excludes the later v2 control-profile and optional public-proof source changes. It does not establish actual provider privacy/IAM, authenticated baseline RED, or the full fourteen-case T05A GREEN gate. No per-case result is inferred from the aggregate ordinary Python count.

### Linux foundation run 36774933005

[Run 36774933005, job 110090343686](https://github.com/himangga01/wisdom-super-observer/actions/runs/36774933005/job/110090343686) at product commit `406f47e315ae19ed52fa79d92c6e4253e4e159c4` succeeded. It passed 1512 ordinary Python cases with zero skips in 128.54 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 246.10 seconds; the strict checker confirmed exactly ten. Ruff and strict mypy on 40 files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical exports were verified twice, the 77-row checker passed, and HTTPS Chrome passed 26 cases in 42.2 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

At `406f47e`, this run covers the reviewed v2 control-profile and optional public-proof source changes recorded in source commit `9060f61797c05773d0e329595ffc40e70281edc5`. It predates and excludes the later component-diagnostic amendment. It is ordinary foundation/recovery evidence and does not establish private-provider acceptance.

### Linux foundation run 36782405311

[Run 36782405311, job 110115613887](https://github.com/himangga01/wisdom-super-observer/actions/runs/36782405311/job/110115613887) at product commit `dff9ec754387e7bc90e41f6b7926197d37590600` succeeded. It passed 1567 ordinary Python cases with zero skips in 138.55 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 250.51 seconds; the strict checker confirmed exactly ten. Ruff and strict mypy on 40 files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical contract exports were verified twice, and the TVT evidence checker reported 77 audit cases, 77 ledger rows and zero errors (these are checker counts, not 77 tests). HTTPS Chrome passed 26 cases in 57.3 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

The complete private log was 92,026 bytes with SHA-256 `64f8db38a25b01ba6950cea5700fc69179704be31ac77c7ae82aabfd860cadf7`; all selected steps succeeded. This receipt covers the previously reviewed component-diagnostic source commit `3bcf178a9eb93d296658a11a2cedf03e833e02f3`, but predates and excludes the later diagnostic-only source commit `cddeee3e438ccfa7a51f817b24d2781e51be2495` and this documentation amendment. It remains foundation evidence and does not establish actual provider privacy/IAM, authenticated HTTP/CSRF preflight, genuine baseline RED, or full fourteen-case acceptance.

The later source-only diagnostic amendment is scoped approved and committed as `cddeee3e438ccfa7a51f817b24d2781e51be2495` (four files, 927 insertions and 40 deletions). The initial meaningful RED selection had three failures before 375 passed; review found two Important findings concerning causal-origin masking and closed-stdout `ValueError`. After fix round 1, the six-case RED selection failed all six cases, with 375 deselected, in 0.67 seconds before the minimal fix. The covering 381-case selection passed after the fix in 1.95 seconds. Scoped Astra review marked I1/I2 addressed with no Critical, Important, or Minor findings. Root’s fresh 381-case selection passed in 2.07 seconds; Ruff on four files, formatting on four files, configured product-source mypy on 40 files, source-boundary/hash checks, six unchanged gates, curated staging, no-drift/diff checks and the private 18-value guard passed. Source commit `cddeee3` and the reviewed docs were pushed in one branch update resulting in `ee9c11b2c14a409b1d055e3b62a1359abb93c718`; remote SHA was verified and the tree was clean. These diagnostics preserve behavior and do not determine the eighth or ninth probe’s actual cause or establish provider acceptance.

### Linux foundation run 36789932368

[Run 36789932368, job 110140188216](https://github.com/himangga01/wisdom-super-observer/actions/runs/36789932368/job/110140188216) at product commit `ee9c11b2c14a409b1d055e3b62a1359abb93c718` succeeded. It passed 1642 ordinary Python cases with zero skips in 139.88 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 252.03 seconds; the strict checker confirmed exactly ten. Ruff and configured product-source mypy on 40 files passed, as did frontend typecheck/lint/build and 15 frontend unit cases. Twenty canonical contract exports were verified twice, and the TVT evidence checker reported 77 audit cases, 77 ledger rows and zero errors (not 77 tests). HTTPS Chrome passed 26 cases in 57.5 seconds. Valkey smoke and owned PostgreSQL cleanup succeeded.

The complete private log was 90,091 bytes with SHA-256 `1b4081dd61c4980e380ff96d9a6dee8b043b288a2141e1283ccc8089ad2eacfd`. This receipt covers diagnostic source commit `cddeee3` and the published documentation at `ee9c11b`; it predates and excludes the later cutoff/request-boundary source commit `3048067bd515bcd86a2a41f48c1de56874e26785` and the later 0a033bc update. The ordinary collection excludes the private fourteen-case acceptance file. This remains foundation evidence and establishes no provider privacy/IAM, authenticated HTTP, sealed-656 genuine RED, full14, or parity acceptance. No CI run is currently in progress.

### Later cutoff/request-boundary diagnostic amendment

Source commit `3048067bd515bcd86a2a41f48c1de56874e26785` is a four-file diagnostic-only amendment (753 insertions, 60 deletions) against `ee9c11b`. The meaningful RED selection failed five cases with 381 deselected in 0.47 seconds before implementation; the final covering selection passed 442 cases in 2.35 seconds. Independent Astra spec review passed and quality review approved with zero findings. Root’s fresh 442-case run passed in 2.16 seconds; Ruff four files, formatting four files, configured mypy 40, four final hashes, the AST boundary (seven provider methods, two relay methods and two new helpers), six unchanged gates, exact four-file staging, no-drift/diff checks and private 18-value guard all passed. Source commit `3048067` and the reviewed documentation were subsequently pushed together in the `0a033bc` branch update; remote SHA was verified and the worktree was clean. No provider acceptance is established.

The diagnostics preserve the existing stop/event and zero-or-one-clock behavior, retain the prior minimum cutoff value and fixed bound label across late checks, and record fixed nonblocking `relay_before` / `relay_at_failure` snapshots detached from the first failure. Successful HTTP response, status/content access and call order are unchanged. A private helper binding adds fixture-only ABI cost; no product or harness caller is changed. Fatal poison/admission, budgets, the 381-contract surface, 24-control/63-effect checks, profile/schema and cleanup/refusal behavior are unchanged. These source checks do not determine the ninth probe’s cause or establish provider acceptance. The source-intentional stop branch cannot be labeled first-stage `PUMP_CUTOFF`; an idle or absolute deadline may instead install cutoff metadata during teardown, but the actual bound and its chronology relative to the HTTP failure remain unknown. Immediately after the tenth workflow completed, no eleventh attempt had yet been authorized. The later root ruling accepted the two-file idle-retirement implementation and conditionally authorized one automatic eleventh cold workflow after final source/document approval, exact curated staging, private18/no-drift/whitespace checks, local source and documentation commits, and remote-SHA verification. This one-attempt conditional authority was consumed by run 36801780564 below; no manual retry or twelfth run is authorized.

### Linux foundation run 36795275636

[Run 36795275636, job 110157170634](https://github.com/himangga01/wisdom-super-observer/actions/runs/36795275636/job/110157170634) at product commit `0a033bce6733e0a15ffd8f8e2180c1e2d7c39e05` succeeded. It passed 1703 ordinary Python cases with zero skips in 138.97 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 250.35 seconds; the enclosing exact-ten gate passed. Configured mypy passed on 40 files; frontend passed 15 unit cases and typecheck/lint/build. Twenty canonical contract exports were verified twice, the TVT evidence checker reported 77 audit cases, 77 ledger rows and zero errors (not 77 tests), and HTTPS Chrome passed 26 cases in 58.7 seconds. Valkey smoke and owned PostgreSQL provision/removal succeeded.

The complete private log was 90,067 bytes with SHA-256 `31854f67b53460a782b74906141f704508dfdea796fd6eb2b625311b415da51c`. This run covers reviewed source commit `3048067` and published docs at `0a033bc`; it predates and excludes the later idle-retirement fixture source implementation and this draft. The private fourteen-case acceptance file remained excluded from ordinary collection. It is foundation evidence, not actual provider or lifecycle acceptance. No CI run is currently in progress.

### Linux foundation run 36801780609

[Run 36801780609, job 110177504261](https://github.com/himangga01/wisdom-super-observer/actions/runs/36801780609/job/110177504261) at source/document commit `d5aaba84fd1f456bb93e0d40b600203c1ee6877f` succeeded. It passed 1726 ordinary Python cases with zero skips in 134.54 seconds and all ten actual Celery/Valkey recovery cases with zero skips in 250.61 seconds; the exact-ten enclosing gate passed. Configured mypy passed on 40 files. Frontend passed 15 unit cases and typecheck/lint/build. Twenty canonical contract exports were verified twice, and the TVT evidence checker reported 77 audit cases, 77 ledger rows and zero errors (not 77 tests). HTTPS Chrome passed 26 cases in 48.4 seconds. Valkey 9.1.2 smoke and PostgreSQL 17.11 provision/removal succeeded.

The complete private log was 89,980 bytes, SHA-256 `935a412757df60a0fe7cf848ad3117836c052a454206cfc73854b3e8d42f56c2`. This run covers reviewed idle-retirement source commit `52343d4` and the docs at `d5aaba8`; ordinary collection excluded the private fourteen-case acceptance file. It is foundation evidence, not provider acceptance. Both relevant workflow watches completed; no workflow is currently running.

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

### Sixth sealed private asset baseline probe: control-route setup failed

[Run 36765314359, job 110057880890](https://github.com/himangga01/wisdom-super-observer/actions/runs/36765314359/job/110057880890) used product commit `f79c83eb01ff4486b097dd159d1d1f36dabd4238` and reported one setup error in 9.54 seconds. Locked dependencies, the owned PostgreSQL fixture, and the overlay/cleanup steps succeeded. The probe reached relay S3 control preflight, then the shared-gateway administrative bucket-route mutation returned HTTP 400 with `MalformedXML`. The strict checker refused this setup receipt: it is not a provider authorization result, actual privacy/IAM acceptance, completed HTTP preflight, or a genuine missing-route RED proof. This historical probe predates the later independently reviewed v2 control-profile and optional public-proof source changes; the four parser and two existing-bucket CreateBucket checks have not been completed as an accepted provider profile.

The first ownership PUT is a source inference, not an operation captured by this run. The returned 400 characterizes only that observed route/request outcome and cannot be treated as an IAM denial or as the full v2 profile result. The complete operation-specific v2 checks, unchanged-state/effects bundle, authenticated HTTP/CSRF preflight, and sealed missing-route assertion remain required.

### Seventh sealed private asset baseline attempt: inert PUT effect unclassified

[Run 36774933030, job 110090344234](https://github.com/himangga01/wisdom-super-observer/actions/runs/36774933030/job/110090344234) used product commit `406f47e315ae19ed52fa79d92c6e4253e4e159c4` and reported one setup error in 21.59 seconds. PostgreSQL, dependencies, overlay and cleanup succeeded. The safe trace retained one typed outcome: gateway `put_object`, variant 1, HTTP 200, accepted-inert-candidate. The following effects bundle failed, but the target and component were not retained. The strict checker rejected the incomplete setup result. A successful mutation response is not privacy acceptance or an accepted receipt, and no effect assertion is weakened.

By source order, the v2 control profile returned normally on this path and execution reached the 26th scheduled public-matrix entry. This does not verify 25 prior independent privacy bundles, the complete 24-control profile, or the 63-effect matrix. The failing target/component remains unknown. A diagnostic-only two-file source amendment received independent scoped approval with no Critical/Important/Minor findings; the author’s final selection passed 306 cases in 1.80 seconds and root’s fresh selection passed 306 in 1.73 seconds, with Ruff/format of four files and configured mypy 40 passing. Review confirmed only seven declared methods changed; relay, safety, checker and workflow hashes remained unchanged. These diagnostics identify a bounded failure stage only; no provider-cause determination, privacy/IAM proof, HTTP/CSRF preflight, genuine baseline RED, or full fourteen-case GREEN is established. Exact two-path staging, private 18-value guard and no-drift checks passed; diagnostic source commit `3bcf178a9eb93d296658a11a2cedf03e833e02f3` was pushed and remotely verified; the later eighth attempt is recorded below and remains unresolved.

### Eighth sealed private asset baseline attempt: anonymous GET transport error and cleanup failure

[Run 36782405326, job 110115613910](https://github.com/himangga01/wisdom-super-observer/actions/runs/36782405326/job/110115613910) used product commit `dff9ec754387e7bc90e41f6b7926197d37590600` and ended with one setup error in 21.04 seconds. PostgreSQL, dependencies, overlay, and workflow-owned PostgreSQL cleanup succeeded, but fixture-local provider close failed: the fixed private-S3 cleanup message matched twice, with one occurrence during exception handling.

The retained typed mutation was gateway `create_multipart_upload`, variant 1, HTTP 200 / accepted inert candidate. Its following effect targeted the original object’s `anonymous_get` and returned `TRANSPORT_ERROR`, null status, and code `TRANSPORT_ERROR`. The original HTTP exception kind/phase and provider-close category are unknown. This broad label does not establish an HTTPX/socket failure or an anonymous public HTTP 200. By source order this was the 27th scheduled entry; that is not accepted evidence for 26 earlier bundles, the full 24-control profile, or the full 63-effect matrix. No provider privacy/IAM, authenticated HTTP/CSRF preflight, genuine RED, public proof, or full fourteen-case acceptance was reached.

The failure remains unresolved. The separate diagnostic-only source amendment now records fixed exception kind/phase and only a status actually obtained, first relay origin with a safe nonblocking snapshot, and fixed provider-close category. Combined-branch cutoff reason remains `PUMP_CUTOFF` or `UNKNOWN`; counters do not prove quiescence. Immediate poisoning/refusal behavior, the 24-control profile, 63-effect matrix, schema, budgets, call order, and cleanup authority are unchanged. The source-only commit does not identify the actual eighth-probe cause or establish a provider fix. At the time of this eighth attempt, no ninth attempt had occurred.

### Ninth sealed private-asset baseline attempt: anonymous HEAD transport error

[Run 36789932312, job 110140187890](https://github.com/himangga01/wisdom-super-observer/actions/runs/36789932312/job/110140187890) used source commit `ee9c11b2c14a409b1d055e3b62a1359abb93c718` and ended with one setup error in 22.04 seconds. PostgreSQL, dependencies, sealed overlay setup, and workflow-owned PostgreSQL cleanup succeeded; fixture-local provider close refused with `RELAY_TRANSPORT`.

The typed mutation was gateway `create_multipart_upload`, variant 1, HTTP 200 / accepted inert candidate. The first retained failed effect targeted the new object’s `anonymous_head` and recorded `TRANSPORT_ERROR`, null status, code `TRANSPORT_ERROR`, exception kind `HTTPX_READ_ERROR`, and phase `HTTP_REQUEST`. One closed diagnostic snapshot recorded schema 1, categories `[RELAY_TRANSPORT]`, relay available, state `CLOSED`, `failed=true`, tracked connections/sockets/workers all zero, first stage `PUMP_CUTOFF`, and first kind `UNKNOWN`. The byte-complete private log was 59,250 bytes with SHA-256 `3878b534388c1a63fb297edd5dd7ca398b2f69bb149329c124d53cc32e916ed2`.

The snapshot counters are not proof of quiescence. The monotonic stop guard prevents an intentional stop from installing first-register `PUMP_CUTOFF` metadata. An idle or absolute deadline may nevertheless install cutoff metadata during teardown. The actual bound and its chronology relative to the HTTP failure remain unknown; the close observation does not prove causation or rule out teardown. Public-proof prefix count was zero. No provider privacy/IAM acceptance, authenticated HTTP/CSRF, sealed-656 genuine RED, or full14 acceptance was reached. This observation alone does not authorize a behavior fix or tenth probe.

### Tenth sealed private-asset baseline attempt: anonymous HEAD read error

[Run 36795275640, job 110157170235](https://github.com/himangga01/wisdom-super-observer/actions/runs/36795275640/job/110157170235) used source `0a033bce6733e0a15ffd8f8e2180c1e2d7c39e05` and ended with one setup error in 22.79 seconds. PostgreSQL provisioning, dependency installation, sealed656 checkout/fixture-only overlay and workflow-owned PostgreSQL cleanup succeeded; fixture-local provider close refused with `RELAY_TRANSPORT`.

The typed mutation was gateway `put_object_acl`, variant 4, HTTP 403 / `AccessDenied`. The first retained failed effect targeted the original object’s `anonymous_head` and recorded `HTTPX_READ_ERROR` / `HTTP_REQUEST`, with null status. Before the request, the relay snapshot was available, `RUNNING`, `failed=false`, with 4 connections, 9 sockets, 5 workers and first stage/kind `UNKNOWN`. At failure, it was available and still `RUNNING`, but `failed=true`, with 2 connections, 5 sockets, 5 workers, and first stage `PUMP_CUTOFF` / first kind `IDLE_CUTOFF`. The closed snapshot retained `RELAY_TRANSPORT`, `CLOSED`, failed true, zero tracked counts, and the same first stage/kind. The complete private log was 59,653 bytes with SHA-256 `5d7a911e121a6345d7a6993fcf8c853eccc346fbe36088cd8e841a99a335a56a`.

The before snapshot recorded no global failure then; the failure snapshot shows that idle-cutoff poison was installed by that later observation. Neither snapshot identifies the same connection or proves the cause of the HTTP error. These samples do not establish expiry chronology relative to the HTTP failure, same-connection causality, connection freshness or quiescence. The first retained origin is idle rather than absolute; this does not establish that other failures were absent. Public-proof prefix count was zero. No provider privacy/63-effect or 24-control receipt, authenticated HTTP, sealed656 genuine RED, full14 GREEN or APK parity was established.

The tenth workflow consumed the prior conditional authority. The connection-local idle-retirement design has since been accepted and implemented in two fixture files. The original source review found 0 Critical / 1 Important / 1 Minor; fix round 1 addressed both findings and received independent scoped approval with 0 Critical / 0 Important / 0 Minor. Root completed the exact two-file source gate and committed it locally as `52343d410755ceb1190e979557d0bc6bcb0b153f`; that source commit and the reviewed docs were pushed together in `d5aaba84fd1f456bb93e0d40b600203c1ee6877f`, the remote SHA matched and the worktree was clean. This source status does not establish provider acceptance or explain the tenth result. Root conditionally authorized one automatic eleventh cold workflow after the required source/document gates; that authorization was consumed by run 36801780564 below. No manual or twelfth run is authorized. No CI run is currently in progress.

### Fixture-only idle retirement implementation

The accepted fixture change is implemented in `_worker` in `tests/support/asset_minio.py` and twenty focused contracts plus the superseded idle-health assertion in `tests/contract/test_asset_fixture_safety.py`. Only a typed `RelayOriginFailure` from the forwarding phase with exact origin `PUMP_CUTOFF/IDLE_CUTOFF` retires that connection without poisoning relay-wide state. Direct pump cutoff, absolute cutoff including ties, byte limits, unknown failures, forged tuples and native transport/control faults remain fatal. Finalization attempts both owned handles even when the first close raises; failed closes retain their handle and slot reservation. Pending `failed=true` / `first_origin=None` and STOPPING metadata are preserved. This adds no deadline, clock read, retry, probe, or inventory clear.

The initial meaningful pre-implementation selection failed 9 cases with 115 deselected in 2.13 seconds. The expanded pre-implementation selection failed 9 and passed 11, with 115 deselected, in 2.59 seconds. The initial covering selection passed 462 cases in 4.51 seconds; root’s fresh initial selection passed 462 in 4.40 seconds. The original implementation review recorded 0 Critical / 1 Important / 1 Minor; fix round 1 addressed the Important teardown guarantee and Minor fragmented request-line read, and its independent scoped review approved with 0 Critical / 0 Important / 0 Minor. The worker implementation remained byte-identical through this fix. The targeted fix RED failed 3 cases with 135 deselected in 0.45 seconds. Final covering author verification passed 465 cases in 4.37 seconds and root’s fresh run passed 465 in 4.38 seconds. Ruff passed on two files; formatting reported two unchanged files. The configured mypy40 result remains applicable because the fix changed only untyped tests. Root confirmed the normalized module is identical outside `_worker`, eight provider/profile/harness/process/private-case/RED+GREEN-checker/workflow gates are unchanged, exact two-file stage and source hashes passed, as did private18, no-drift and whitespace guards. Final source hashes are `11519d09de56fcce583376730078fa140b4e434064ffe992a6a0c21c9822d076` (`tests/support/asset_minio.py`) and `340b8b2f6e2bd219059d5ab69b321424e846681d784f1b8974c718448df426a9` (`tests/contract/test_asset_fixture_safety.py`). Source commit `52343d410755ceb1190e979557d0bc6bcb0b153f` and the reviewed docs were pushed together in `d5aaba84fd1f456bb93e0d40b600203c1ee6877f`; remote SHA matched and the worktree was clean. These owned-socket tests do not verify real provider performance at the configured 10-second idle and 60-second absolute limits. Actual provider behavior, the tenth request’s cause, authenticated HTTP, genuine sealed656 RED and full14 acceptance remain unverified.

### Eleventh sealed private-asset baseline: native listing contract failure

[Run 36801780564, job 110177497442](https://github.com/himangga01/wisdom-super-observer/actions/runs/36801780564/job/110177497442) used source/document commit `d5aaba84fd1f456bb93e0d40b600203c1ee6877f` and ended with one setup error in 36.28 seconds. Sealed baseline checkout, fixture-only overlay, dependency synchronization, PostgreSQL provision and workflow-owned PostgreSQL removal succeeded. The actual observation step failed at the fixture's combined forced-pagination/filter checkpoint. The complete private log was 57,773 bytes, SHA-256 `9571f6a737c502421f6bcde711d21f67198f42f03a3097d2e3f5b241d276ecb5`; bounded extraction found zero public-proof prefixes, zero validated ACL-effect failure records and zero validated provider-close diagnostic records. PostgreSQL cleanup success is separate from provider-level evidence.

The fixed error combines four checks over installed-prefix objects and multipart identities. It does not retain evaluated page counts, row counts, set-equality results, or which predicate first failed; no actual values are inferred. By executed source order, authenticated object PUT/HEAD/GET and `privacy_profile()` (including its source-controlled 24-control and 63-effect checks), presigned GET and expired refusal, maintenance and foreign-authority probes, exact foreign-key multipart check, three child-key object/multipart/list-parts checks, and both listing helper calls returned before the aggregate checkpoint. This is progress only, not an accepted provider receipt or retained 24/63 receipt. API startup, authenticated HTTP/CSRF preflight, missing-route RED and full14 execution were not reached. The run therefore is neither a genuine sealed656 RED nor provider acceptance.

Independent source inspection of the pinned MinIO release used by this run (`RELEASE.2025-04-22T22-12-26Z`, commit `0d7408fc9969caf07de6a8c3a84f9fbb10a6739e`) establishes a native capability mismatch. Its [multipart-upload listing implementation (`ListMultipartUploads`)](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-sets.go#L881) treats its nonempty `Prefix` as one exact object. Its [multipart listing](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-multipart.go#L254) visits only that exact object’s multipart directory, rather than enumerating multipart uploads on arbitrary installed child keys. Its [server-pool implementation](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-server-pool.go#L1696) does not provide durable, bounded cross-key pagination through its empty-prefix cache path. Thus this pinned candidate cannot satisfy installed-prefix multipart enumeration, continuation across child keys, and durable restart/orphan discovery. The actual four-way predicate remains unknown; this capability rejection is based on pinned source semantics, not invented run counts.

Root rejected this MinIO candidate for the required contract. No same-provider diagnostic retry, manual or twelfth run is authorized; do not weaken pagination, filtering, set equality or privacy assertions, substitute known database rows, or patch the vendor. The conditional eleventh authority was consumed. Read-only primary-source investigations are complete. RustFS 1.0.0 is the approved transition design and source implementation is underway; no provider is selected for acceptance and no retry authority exists. T05A remains in progress; provider acceptance, authenticated sealed656 RED, full14 and APK parity remain unproved.

### RustFS transition implementation status — 2026-10-01

The approved RustFS 1.0.0 design and exact archive/member hashes, profile,
receipt ABI, role boundaries, restart proof, containment and budget are recorded
in the [private asset transition status](private-assets.md#rustfs-transition-status--2026-10-01).
This design does not change the actual-run record above. The latest completed
Linux foundation remains run 36801780609 / job 110177504261 at d5aaba8, with
1726 ordinary Python cases and ten actual Celery/Valkey recovery cases, both
zero skips; the full foundation receipt remains recorded above. No CI is
currently active and no RustFS runtime or provider run has occurred.

The independent receipt-checker component is READY: 216 focused contracts
passed in 1.31 seconds, Ruff, formatting and scoped mypy passed, and fresh
independent review approved with zero Critical, Important or Minor findings.
The original fixture review found six Important findings; one owner fix batch
addressed all six, and fresh scoped review approved with zero findings. The
fixture owner passed 676 profile/safety cases in 4.98 seconds; the helper owner
passed 201 cases in 0.41 seconds. Root's one amended aggregate passed 1,093
cases in 7.26 seconds with no skips. Ruff check/format across nine files,
configured mypy across 40 product files and explicit pure-checker mypy across
two files passed. These are source/contract gates, not provider acceptance.

Root defined but has not activated one conditional RustFS probe12. Activation
requires final four-doc review, private18, staged no-drift/whitespace/source
hash gates, one reviewed curated commit and combined push, and verified remote
SHA equality. If activated, at most one automatic cold run uses the existing
20-minute sealed656 overlay12 workflow and foundation workflow; no manual retry
or budget increase is authorized. The 11th MinIO attempt remains the latest
actual provider run. No RustFS execution/acceptance, authenticated HTTP, genuine
sealed-656 RED, full14 GREEN, W02 reopening or APK parity is established.

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
