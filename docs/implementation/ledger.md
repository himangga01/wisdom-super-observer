# Implementation ledger

Baseline: SuperLive Plus 1.18.1, APK SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.

This ledger tracks executable service work. The separate [parity ledger](../integrations/tvt-parity-ledger.md) tracks APK-versus-web evidence; a passing local test never means a user feature is matched.

| Work item | Implementation status | Verification | Remaining gate |
| --- | --- | --- | --- |
| T01 workspace and typed health | Offline foundation implemented | API health 9 passed; frontend 2 tests, typecheck, lint and production build passed; local FE→API HTTP smoke showed `서비스 연결됨`; integrated script passed | Real dependency readiness, Compose runtime smoke |
| T02 tenant persistence | Database-issued, one-use tenant grants and private transaction context implemented; former caller-settable GUC boundary replaced | Actual PostgreSQL 17.11: forgery, replay, expiry, rollback, concurrent context installation, membership changes, pool reuse, migration roundtrip and restricted-role denial tests passed; independent task review approved | Production role provisioning and deployment review; new tables must extend this role matrix |
| T03 web authentication and store selection | OIDC authorization code/PKCE, independently verified RS256 identity, opaque sessions, CSRF logout, tenant/store assignment authorization and functional responsive UI implemented | Integrated Python 139/139 with actual PostgreSQL, FE unit 10/10, HTTPS Chrome auth/navigation 14/14; independent backend/frontend reviews approved | Browser tests use a signed test issuer and test API fixture; actual FastAPI/PG behavior is tested separately. Real identity-provider deployment, provisioning and end-to-end deployment smoke remain pending. TVT account login is W05 |
| W00 atomic parity ledger | Static 77-case seed and desktop API preflight implemented; false-positive paths closed | 31 focused tests passed; checker 77/77 rows, zero errors; headless Chrome/Edge API probe 2/2 | Trusted W24 run registry and comparator; runtime reachability, Android/iOS/media/permission checks, support matrix sign-off; no `MATCHED` rows and `release_ready=false` |
| W01 TVT bridge feasibility | Static handoff, frozen 199-operation manifest and declaration inventories implemented | 10 schema tests passed; 77 cases / 199 candidate operations; 281 request classes and 299 native declarations inventoried | Vendor rights, runtime fixtures and pilot; all six remote G-P1 families `BLOCKED` |
| T04–T05A and W02–W25 service features | Pending | None | Prerequisite contracts, infrastructure and family-specific gates |

## Latest integrated verification — 2026-09-30

`pwsh -NoProfile -File scripts/verify.ps1 -WithPostgres -WithBrowser -WithAuthBrowser`
exited 0: Python 139 passed, no skips or warnings; Ruff and strict mypy passed;
frontend typecheck/lint, 10 unit tests and production build passed. The exact
10-file contract export set matched the committed inputs and a second export.
The evidence checker validated 77/77 rows with zero errors. Desktop Chrome/Edge
API preflight passed 2/2; the separate HTTPS authentication/browser suite passed
14/14. A temporary skipped PostgreSQL integration probe made the verifier exit
1 as intended; that probe was removed before the passing run.

The browser suite logs Next's experimental self-signed certificate warning and
Playwright color-environment warnings. Its intentional API-outage case logs a
sanitized `Service unavailable` error. These are separate from the successful
checks. Valkey/S3/Compose, handset/PWA and TVT runtime were not exercised. There
are still zero verified APK `MATCHED` cases and all six remote G-P1 families
remain `BLOCKED`.

The [provided design reference](../design/2026-09-30-dashboard-reference.md)
is applied to the login and store screens. Browser screenshots use fixture
stores; they are visual previews, not customer or camera evidence.

The independent wave integration review approved this feature-branch milestone
with no Critical/Important findings. Nonblocking follow-ups remain: use one
captured SQL timestamp for session creation at the expiry boundary; format dense
JSX when extending the screens; reduce avoidable browser-tool warning noise; and
align the browser API fixture's key length, role casing, user UUID and logout
status with the real backend. These do not close production or APK release gates.

## Local development

1. Use Node.js 24, pnpm 11 and Python 3.12. Install `uv` if absent.
2. Run `python -m uv sync --all-packages --group dev` and `pnpm install --frozen-lockfile`.
3. For actual PostgreSQL integration, follow [local PostgreSQL setup](../engineering/local-postgres.md), migrate through `0001c_auth_sessions`, then run `Provision`. No Docker installation is needed for this gate.
4. Run `pwsh -NoProfile -File scripts/verify.ps1 -WithPostgres -WithBrowser -WithAuthBrowser` for the verified local gate. `-WithAuthBrowser` starts an isolated HTTPS signed-issuer/API fixture and the real Next interface; it does not configure a production identity provider or seed production users.
5. When Docker is available, run `docker compose -f infra/compose.yaml --profile test up -d`, then the explicitly selected integration checks. The current Windows host has no Docker CLI, so these services have not been exercised.
6. Copy `.env.example` to ignored `.env` only after replacing placeholders appropriate to the environment. Never use real TVT, Tyco or device secrets in local fixtures.

For normal service startup, configure the server-only authentication settings
and distinct role URLs described in [web authentication](../engineering/web-auth-and-tenant-scope.md).
Run the API with `python -m uv run uvicorn wso_api.main:create_app --factory --host 127.0.0.1 --port 8000`
and serve Next behind the configured trusted HTTPS public origin. Secure cookies
require HTTPS. Missing auth configuration fails closed; unprovisioned identities
are not automatically granted membership. Dependency readiness and S3/Valkey
selection remain unverified. External TVT adapters remain disabled until their
W01 family gates are documented.
