# Implementation ledger

Baseline: SuperLive Plus 1.18.1, APK SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.

This ledger tracks executable service work. The separate [parity ledger](../integrations/tvt-parity-ledger.md) tracks APK-versus-web evidence; a passing local test never means a user feature is matched.

| Work item | Implementation status | Verification | Remaining gate |
| --- | --- | --- | --- |
| T01 workspace and typed health | Offline foundation implemented | API health 9 passed; frontend 2 tests, typecheck, lint and production build passed; local FE→API HTTP smoke showed `서비스 연결됨`; integrated script passed | Real dependency readiness, Compose runtime smoke |
| T02 tenant persistence | Database-issued, one-use tenant grants and private transaction context implemented; former caller-settable GUC boundary replaced | Actual PostgreSQL 17.11: forgery, replay, expiry, rollback, concurrent context installation, membership changes, pool reuse, migration roundtrip and restricted-role denial tests passed; independent task review approved | Production role provisioning and deployment review; new tables must extend this role matrix |
| T03 web authentication and store selection | OIDC authorization code/PKCE, independently verified RS256 identity, opaque sessions, CSRF logout, tenant/store assignment authorization and functional responsive UI implemented | Integrated Python 139/139 with actual PostgreSQL, FE unit 10/10, HTTPS Chrome auth/navigation 14/14; independent backend/frontend reviews approved | Browser tests use a signed test issuer and test API fixture; actual FastAPI/PG behavior is tested separately. Real identity-provider deployment, provisioning and end-to-end deployment smoke remain pending. TVT account login is W05 |
| T04 connection credentials and lifecycle | AES-256-GCM tenant/connection/version binding, owner-only lifecycle/store mapping, fenced generation, durable revocation, separate scoped worker capability and responsive connection UI implemented | Independent backend/frontend/worker-runtime reviews approved; latest integrated Python 230/230, FE 15/15 and HTTPS browser 26/26, no PostgreSQL skips | Production KMS/key rotation, later job/session cancellation consumers and actual TVT/Tyco login are pending. Local saved state is NOT_VERIFIED or DISCONNECTED |
| Linux CI foundation | Pinned Actions and guarded disposable PostgreSQL/Valkey verification workflow implemented; independent review approved | [Actual Linux run 36703370870](https://github.com/himangga01/wisdom-super-observer/actions/runs/36703370870) passed: 230 Python/15 FE/26 HTTPS browser tests, real PostgreSQL migrations and Valkey persistence/empty-volume smoke; actual digests recorded | S3 compatibility and deployment checks remain distinct gates; subsequent T05 recovery result is recorded below |
| W00 atomic parity ledger | Static 77-case seed and desktop API preflight implemented; false-positive paths closed | 31 focused tests passed; checker 77/77 rows, zero errors; headless Chrome/Edge API probe 2/2 | Trusted W24 run registry and comparator; runtime reachability, Android/iOS/media/permission checks, support matrix sign-off; no `MATCHED` rows and `release_ready=false` |
| W01 TVT bridge feasibility | Static handoff, frozen 199-operation manifest and declaration inventories implemented | 10 schema tests passed; 77 cases / 199 candidate operations; 281 request classes and 299 native declarations inventoried | Vendor rights, runtime fixtures and pilot; all six remote G-P1 families `BLOCKED` |
| T05 durable jobs | Database-owned requests, outbox/inbox, restricted dispatcher/worker, fencing, cancellation, external uncertainty, status/items API and job-bound secret primitives implemented; task and milestone integration/fix reviews approved | [Actual Linux run 36716200713](https://github.com/himangga01/wisdom-super-observer/actions/runs/36716200713): 537 Python cases and all ten required real process/broker recovery cases, zero skips; no remaining Critical/Important review findings | Generic credential handlers fail CAPABILITY_UNSUPPORTED until the owning executor exists; no production IMPORT/REGISTRATION handler. Deployment and vendor effects remain pending |
| T05A private assets | In progress; MinIO v2 fixture source, strict consumers and optional public-proof source received scoped approval | [Latest integrated foundation run](../engineering/linux-ci.md#latest-integrated-linux-foundation-run) passed; [latest provider attempt](../engineering/linux-ci.md#sixth-sealed-private-asset-baseline-probe-control-route-setup-failed) stopped during setup | Actual provider privacy/IAM and HTTP preflight, complete fourteen-case GREEN acceptance, actual relay connectivity, and whole APK parity |
| W02–W25 service features | Pending | None | Private storage prerequisite and family-specific gates |

## Previous integrated verification — 2026-09-30

`pwsh -NoProfile -File scripts/verify.ps1 -WithPostgres -WithBrowser -WithAuthBrowser`
exited 0: Python 449 passed, no skips or warnings; Ruff and strict mypy (26 source files) passed;
frontend typecheck/lint, 15 unit tests and production build passed. The exact
15-file contract export set matched the reviewed inputs and a second export.
The evidence checker validated 77/77 rows with zero errors. Desktop Chrome/Edge
API preflight passed 2/2; the separate HTTPS authentication/browser suite passed
26/26. A temporary skipped PostgreSQL integration probe made the verifier exit
1 as intended; that probe was removed before the passing run.

The browser suite logs Next's experimental self-signed certificate warning and
Playwright color-environment warnings. Its intentional API-outage case logs a
sanitized `Service unavailable` error. These are separate from the successful
checks. This local run did not exercise Valkey/S3/Compose, handset/PWA or TVT. There
are still zero verified APK `MATCHED` cases and all six remote G-P1 families
remain `BLOCKED`.

The subsequent [Linux CI run](../engineering/linux-ci.md#first-recorded-linux-run--2026-09-30)
for commit `5dae70a` completed successfully with 230 Python tests, zero skips,
15 FE unit tests and 26 HTTPS Chrome cases. It also verified actual disposable
PostgreSQL and Valkey AOF persistence through SIGKILL/restart plus an isolated
empty broker volume. That run did not test T05 worker recovery or APK comparison.

The [provided design reference](../design/2026-09-30-dashboard-reference.md)
is applied to the login, store and connection screens. Browser screenshots use
fixture data; they are visual previews, not customer or camera evidence.

The previous T04 wave integration review approved that feature-branch milestone
with no Critical/Important findings. Fixture key length, role casing, user UUID
and logout status are now aligned with the real backend; touched JSX is formatted.
Nonblocking follow-ups remain: use one captured SQL timestamp at the session
expiry boundary; bound expected_generation to PostgreSQL bigint; preserve the
detail route after refresh/delete; reduce avoidable browser-tool warning noise.
These do not close production or APK release gates.

T05 task and scoped fix reviews approved the backend, additive role helper and
Linux fixture source with zero remaining findings. Actual lock-wait regressions
now recheck job/capability expiry after locks; external writes with no reconciler
cannot submit. Fixture safety tests preserve owned listener/process checks and
explicit duplicate/orphan ACK observations. The milestone integration review
found and closed explicit-broker/ambient-Celery configuration and dispatch-generation
documentation issues. The subsequent scoped fix passed 89 offline configuration
tests, including 88 new cases, without repeating the earlier full PostgreSQL run.
Both findings are addressed with no remaining Critical/Important issues. These
targeted results are not a new full-suite or process-recovery result.

The subsequent [T05 Linux run](../engineering/linux-ci.md#first-t05-recovery-run--2026-09-30)
at reviewed commit `6565929` passed 537 ordinary Python cases and all ten required
real Celery/Valkey recovery cases with zero skips. Its strict JUnit gate, Ruff,
mypy, 15 FE unit cases, typecheck/lint/build, 15 deterministic exports, 77-row
checker and 26 HTTPS Chrome cases passed. Owned fixtures were removed. This
closes T05's required actual recovery test gate; S3, live vendor execution,
device/media comparisons and the APK parity release gate remain open.

## Latest local foundation verification — 2026-10-01

A fresh, uncommitted workspace consolidation ran
`pwsh -NoProfile -File scripts/verify.ps1 -WithPostgres` and exited 0:
1194 Python cases passed with zero failures, errors or skips in 180.60 seconds.
Ruff and strict mypy on 40 source files passed; frontend typecheck, lint, 15 unit
tests and production build passed. Twenty contract documents were exported twice
and compared byte-for-byte stable; the evidence checker validated all 77 rows.
Browser/authentication browser, Valkey/container and Compose gates were not
selected in this local command.

A later local asset-metadata, isolated-migration and volume-mode packaging delta
passed 80 focused cases in 2.09 seconds, full Ruff, strict mypy on 40 source
files and two stable 20-document exports. The 80 focused cases overlap the 1194
case result and are not additive. One actual Windows migration round trip,
included in those focused cases, used a guarded unique disposable database for
`0003_jobs` → `0003a_assets` → `0003_jobs` → `0003a_assets`, checked asset
security and preserved T05 behavior, then removed only that database; the
managed database head remained unchanged. The integrated Linux run at `0deeb79`
covers the product foundation; later gate/relay changes are outside that run.

## Private asset implementation

T05A is in progress: private upload contracts, bounded S3/crypto/image adapters
and the real Linux S3/HTTP fixture are being implemented in separate owned files.
The initial fixture and strict result gates receive independent review. The
separate [baseline RED probe](../engineering/linux-ci.md#private-asset-baseline-red-probe)
must prove actual provider and authentication preflight before the missing route
assertion. No S3/lifecycle acceptance or APK parity is claimed at this stage.

The [latest integrated Linux foundation run](../engineering/linux-ci.md#latest-integrated-linux-foundation-run)
at `f79c83e` passed 1375 ordinary Python cases and ten actual Celery/Valkey
recovery cases, with zero skips, plus frontend/browser gates. This run predates
and excludes the later v2 control-profile and optional public-proof source
changes. Those v2 source and strict-consumer deltas each received independent
scoped approval with zero findings; the producer passed 251 focused cases and
the root rerun passed 251, while the consumer preserves the original 77-case
surface. The optional public-proof change also received scoped approval with
zero findings and passed 82 focused cases plus a fresh root rerun. These focused
source checks do not establish provider acceptance. The prior
[integrated run](../engineering/linux-ci.md#previous-integrated-linux-foundation-run)
at `0deeb79` passed 1200 ordinary cases and ten actual recovery cases, zero
skips, and included isolated `0003a_assets` migration/nine-role integration in
the ordinary pytest invocation; no per-case count is recorded. The prior
[foundation run](../engineering/linux-ci.md#previous-recorded-foundation-run)
at `e3865df` passed 855 ordinary cases and ten actual recovery cases.

Six separate private-asset probes have failed during setup, not at HTTP:
SeaweedFS lacked public-access-block support; the required ACL/grant refusal was
not proven; one MinIO volume check did not preserve its observed metadata; a later
run captured UID/GID `65532:65532` with mode `0755`; and the fifth passed the
`0700` volume gate but failed loopback publication, with actual port fields not
captured. The sixth [sealed baseline probe](../engineering/linux-ci.md#sixth-sealed-private-asset-baseline-probe-control-route-setup-failed)
reached relay S3 control preflight, then a shared-gateway administrative
bucket-route mutation returned HTTP 400 / `MalformedXML`; the first ownership
PUT is source inference, not a captured operation. Dependencies, PostgreSQL and
cleanup succeeded, but this setup result is neither IAM denial nor provider
acceptance, completed HTTP preflight, or genuine missing-route RED. Strict RED
receipts were rejected. Pinned [Moby v28.0.4 source](https://github.com/moby/moby/blob/v28.0.4/daemon/network.go#L860)
explains why port publication is skipped for an Internal network, but the
observed port shape is unknown. A fixture-only opaque TCP relay design was
accepted for implementation. The original scoped review found three Important
deadline-validity findings. The author’s fix round 1 addressed I1/I2/I3 and
received scoped approval with no new Critical or Important findings. Its
covering selection passed 120 tests in 1.15 seconds, Ruff, four-file formatting
and configured-source mypy for 40 files; the root’s fresh selection passed 120
tests in 1.11 seconds with Ruff and formatting passing. The older `0deeb79`
integrated receipt predates these changes. The newer `f79c83e` foundation run
does not establish actual relay connectivity or provider acceptance.
SeaweedFS remains excluded. The MinIO candidate still requires the unchanged
privacy/IAM and full fourteen-case lifecycle gates; no provider acceptance is
claimed.

The reviewed two-file result-gate receipt-safety correction passed 247 scoped
cases and an independent review with zero Critical or Important findings. It
improves receipt validation only; provider acceptance remains open. The
integrated Linux aggregates do not establish provider acceptance. The OpenAPI metadata issue was resolved with
required upload-session/download-ticket headers and JPEG/PNG binary schemas,
without eager request-body parsing or buffering. This source review result does
not establish actual provider behavior or APK parity.

The committed `aedbe2d` primitives passed 855 local PostgreSQL-selected Python
cases. Its subsequent Linux run passed 855 ordinary cases and ten actual
recovery cases, then failed mypy at a Windows-only function reference. The
minimal typing correction has a clean scoped review and focused
Linux/Windows checks; its actual full Linux rerun at `e3865df` passed as recorded
above. That result does not accept the separate asset lifecycle.

Storage work uses a fixed work cutoff before helper creation and refuses
dispatch after a late startup return. Synchronous OS/runtime process creation
or control calls can delay the caller beyond that cutoff. A hard worker-group
containment claim requires an independent deployment watchdog and verified
Linux cgroup or Windows Job Object ownership; that production gate remains
unimplemented. Local helper termination does not prove a remote write stopped.

## Local development

1. Use Node.js 24, pnpm 11 and Python 3.12. Install `uv` if absent.
2. Run `python -m uv sync --all-packages --group dev` and `pnpm install --frozen-lockfile`.
3. For actual PostgreSQL integration, follow [local PostgreSQL setup](../engineering/local-postgres.md), migrate through `0003a_assets`, then run `Provision`. No Docker installation is needed for this gate.
4. Run `pwsh -NoProfile -File scripts/verify.ps1 -WithPostgres -WithBrowser -WithAuthBrowser` for the verified local gate. `-WithAuthBrowser` starts an isolated HTTPS signed-issuer/API fixture and the real Next interface; it does not configure a production identity provider or seed production users.
5. When Docker is available, run `docker compose -f infra/compose.yaml --profile test up -d`, then the explicitly selected integration checks. The current Windows host has no Docker CLI, so these services have not been exercised.
6. Copy `.env.example` to ignored `.env` only after replacing placeholders appropriate to the environment. Never use real TVT, Tyco or device secrets in local fixtures.

For normal service startup, configure the server-only authentication settings
and distinct role URLs described in [web authentication](../engineering/web-auth-and-tenant-scope.md).
Run the API with `python -m uv run uvicorn wso_api.main:create_app --factory --host 127.0.0.1 --port 8000`
and serve Next behind the configured trusted HTTPS public origin. Secure cookies
require HTTPS. Missing auth configuration fails closed; unprovisioned identities
are not automatically granted membership. Deployment dependency readiness, S3
compatibility remain unverified. External TVT adapters remain disabled until their
W01 family gates are documented.

Connection lifecycle configuration and worker trust boundaries are documented
in [connection secrets](../engineering/connection-secrets.md). The CI gate uses
its own [disposable Linux runtime](../engineering/linux-ci.md), never the Windows
development database. Explicit PostgreSQL selection requires all nine role URLs;
partial environment configuration fails instead of falling back to local state.

The [durable jobs runbook](../engineering/durable-jobs.md) records the separate
dispatcher/job role boundaries, broker configuration and verified Linux recovery acceptance.
