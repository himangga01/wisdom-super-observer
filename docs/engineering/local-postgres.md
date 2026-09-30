# Local PostgreSQL integration runtime on Windows

Run from the repository root after synchronizing Python dependencies:

```powershell
python -m uv sync --all-packages --group dev
./scripts/dev/postgres-runtime.ps1 Setup
. ./.superpowers/runtime/postgresql17/env.ps1
python -m uv run pytest tests/integration/test_tenant_isolation.py -q
```

The script downloads PostgreSQL **17.11**, EDB packaging revision **4**, from the
[official EDB binaries page](https://www.enterprisedb.com/download-postgresql-binaries),
linked by the [PostgreSQL Windows download page](https://www.postgresql.org/download/windows/).
It checks the archive against the SHA-256
`b9424ee7bc60b52450ff910a3630225df32e633f3cb29c1d126d9299d59aea28`,
[published by an EDB maintainer](https://github.com/EnterpriseDB/edb-installers/issues/706).
Only the archive's `bin`, `lib`, and `share` directories are extracted.

The runtime binds to `127.0.0.1` on an automatically selected free port and uses
SCRAM password authentication. It creates the `wso_test` database, applies the
initial `0001_tenants` migration to create roles, and provisions random passwords
through psycopg's safely quoted SQL composition. Subsequent schema revisions are
applied by the integration suite or an explicit migration command.
The migrator receives `CREATE` on this disposable database so later migrations
can create their protected schemas. Application and identity roles receive no
database creation privilege or role memberships.

The dot-sourced loader sets these variables in the current PowerShell process:

| Variable | Database role |
| --- | --- |
| `WSO_TEST_ADMIN_DATABASE_URL` | `postgres` |
| `WSO_TEST_APP_DATABASE_URL` | `wso_app` |
| `WSO_TEST_IDENTITY_DATABASE_URL` | `wso_identity_bootstrap` |
| `WSO_TEST_MIGRATOR_DATABASE_URL` | `wso_migrator` |
| `WSO_TEST_SESSION_DATABASE_URL` | `wso_web_session` |
| `WSO_TEST_WORKER_DATABASE_URL` | `wso_connection_worker` |
| `WSO_TEST_DISPATCH_DATABASE_URL` | `wso_dispatcher` |
| `WSO_TEST_JOB_DATABASE_URL` | `wso_job_worker` |

The dispatch and job URLs are reserved for `0003_jobs`. Before that
migration, `Setup` and `Provision` can run while their roles are absent. After
the migration creates `wso_dispatcher` and `wso_job_worker`, run `Provision`
to apply their saved passwords. The migration also creates the `NOLOGIN`
owners `wso_dispatch_owner` and `wso_job_owner`; these owners receive no runtime
credentials. The runtime creates neither those owners nor the LOGIN roles.
After `0003_jobs` or a later revision is applied, `Provision` and `Status` fail
if either new LOGIN role is missing, so a damaged migration cannot appear ready.
Both actions first require exactly one applied Alembic version row, including
when all roles already exist. An empty or multiple-row version table fails
before role discovery or application password assignment. A single known
pre-job revision (`0001_tenants`, `0001b_tenant_grants`, `0001c_auth_sessions`
or `0002_connections`) permits absent dispatcher/job roles. A single
`0003_jobs` or any other later head requires both roles; unknown single heads
are treated conservatively as requiring them.

Loading a runtime with the original six credentials adds only missing dispatcher
and job worker passwords and URLs to the same private files. Existing passwords,
URLs (including connection options), endpoint, database and cluster metadata are
preserved. Repeated loads retain both added passwords. Older runtimes also retain
the existing upgrade path for a missing connection worker credential.

`Status` authenticates every currently existing application role, including roles
created since the saved provisioned-role list was written. It checks `LOGIN`,
`NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION` and
`NOBYPASSRLS`. Dispatcher, job worker and connection worker roles must have no
memberships as either member or granted role. The administrator authenticates to
validate the server version and loopback binding. Absent application, identity
or migrator roles remain an error.

The session URL is reserved for the auth migration; the worker URL is reserved
for `0002_connections`. `Setup` can run before either optional role exists.
After the corresponding migration creates `wso_web_session` or
`wso_connection_worker`, run `Provision` before using that URL. Provision sets
the saved passwords for existing migration-created roles. Missing application,
identity or migrator roles remain an error.

Loading credentials from an older runtime adds a random worker password and its
URL to the same private credentials file and refreshes the process environment
loader. Existing passwords, the database, port and cluster metadata are preserved.
The worker role and its schema are created by the migration. `Status` checks the
worker login, its restricted role flags (including `NOINHERIT`), and absence of
role memberships in both directions.

```powershell
./scripts/dev/postgres-runtime.ps1 Status
./scripts/dev/postgres-runtime.ps1 Stop
./scripts/dev/postgres-runtime.ps1 Start
./scripts/dev/postgres-runtime.ps1 Provision
```

`Setup` reuses an existing cluster and never clears its data. It refuses to
initialize over existing data when its matching credentials are missing. A free
port is selected for a new cluster; if another process claims it before startup,
startup fails and leaves the cluster available for inspection.

All binaries, downloads, data, logs, random passwords and the environment loader
live under ignored `.superpowers/runtime/postgresql17/`. Credentials are stored
locally in `credentials.json`; keep that directory private and do not upload it.
Passwords are not placed on command lines or printed. PostgreSQL helpers start
without visible windows. No Windows service is installed and no machine security
settings are changed. `Stop` preserves data and ends only this cluster.

PostgreSQL's Windows initialization can fail when its binary path contains
non-ASCII characters ([upstream report](https://www.postgresql.org/message-id/642665.1738684548%40sss.pgh.pa.us)).
The helper temporarily maps an unused drive letter to the ignored runtime
directory with `SUBST`. PostgreSQL receives an ASCII path through that alias;
the actual files stay inside the worktree. `Stop` removes the alias, and `Start`
recreates it. An alias occupied by another location causes a safe failure.

Before shutdown, `Stop` authenticates to the saved loopback endpoint, checks the
actual data directory and postmaster startup time, and verifies that the SQL
backend's Windows parent is the PID recorded for this cluster. It also checks
that PID's executable and Windows creation time. A process handle stays open
through the shutdown signal and exit wait, preventing Windows from reusing that
PID ([Windows process identity lifetime](https://devblogs.microsoft.com/oldnewthing/20110107-00/?p=11803)).
Shutdown signals the verified PID directly with `pg_ctl kill INT`, avoiding a
second read of the mutable PID file. Unknown, stale, inaccessible or mismatched
identities cause Stop to refuse signaling and retain the drive alias. The alias
is removed only after the verified process exits and its mapping is rechecked.
An already stopped cluster with no PID file is also refused without changing an
existing alias.

The default Python executable is `.venv/Scripts/python.exe`. Use `-Python` to
select another Python 3.12 executable containing the workspace's `psycopg`,
SQLAlchemy and Alembic dependencies. Logs are `initdb.log`, `pg_ctl.log` and
`server.log` in the runtime directory.

Successful runtime validation proves the server version, loopback binding and
role authentication. Tenant isolation remains a separate integration test gate.
