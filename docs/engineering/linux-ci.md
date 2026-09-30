# Disposable Linux verification

`.github/workflows/verify.yml` verifies the implemented foundation, identity,
HTTPS web authentication and connection features on `ubuntu-24.04`. It runs on
pushes to `main` and `codex/**`, ordinary pull requests, and optional manual
dispatch. The job has a 30 minute deadline and cancels an older run for the same
branch or pull request. Its repository token has read-only contents permission;
checkout does not persist credentials. Every action is pinned to a full commit.

This workflow's first successful remote run is still required before claiming
Linux verification. Local parser tests or Windows PostgreSQL tests cannot prove
the Docker services, Ubuntu browser dependencies or Linux process behavior.

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
| Main gate | `pwsh ./scripts/verify.ps1 -WithPostgres -WithAuthBrowser` |
| Broker fixture smoke | `bash scripts/dev/valkey-smoke.sh` |

The main gate runs the full non-live Python suite, rejects skipped selected
PostgreSQL integration cases, checks Python types/lint, frontend types/lint/tests
and production build, verifies deterministic checked-in contracts, and runs the
HTTPS auth browser suite. Test counts grow with implementation; use the observed
run's counts. This job provides its own six PostgreSQL URLs and bypasses the
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
five roles to exist and validates that they have no superuser, createdb,
createrole, replication, bypass-RLS, inherit, or role-membership privileges.
It assigns distinct random passwords, grants the migrator database schema
creation rights required by migration fixtures, tests each restricted login,
and exports `WSO_TEST_{ADMIN,APP,IDENTITY,MIGRATOR,SESSION,WORKER}_DATABASE_URL`.
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

T05 remains open. The current smoke does not run Celery workers, publish through
Kombu, kill dispatcher/worker processes, fence stale leases, verify tenant/actor
scope at delivery, or reconcile DB requests after broker data loss. After T05
adds the locked Celery Redis dependencies, restricted dispatcher roles and real
worker fixtures, extend this Linux gate with those actual recovery tests. The
selected broker gate must fail on missing runtime/tests, zero collection,
failures, or any skip. Use the separately owned empty broker fixture to prove
reconciliation instead of assuming AOF guarantees delivery.

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
production image selection and T05 real worker recovery remain pending.

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
