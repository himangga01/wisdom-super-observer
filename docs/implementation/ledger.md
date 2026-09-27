# Implementation ledger

Baseline: SuperLive Plus 1.18.1, APK SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.

This ledger tracks executable service work. The separate [parity ledger](../integrations/tvt-parity-ledger.md) tracks APK-versus-web evidence; a passing local test never means a user feature is matched.

| Work item | Implementation status | Verification | Remaining gate |
| --- | --- | --- | --- |
| T01 workspace and typed health | Offline foundation implemented | API health 9 passed; frontend 2 tests, typecheck, lint and production build passed; local FE→API HTTP smoke showed `서비스 연결됨`; integrated script passed | Real dependency readiness, Compose runtime smoke |
| T02 tenant persistence | Offline foundation implemented; DB-role isolation gap documented as a production blocker | 6 focused tests passed, 14 live PostgreSQL cases skipped; Ruff/mypy and Alembic offline SQL render passed | Database-verified tenant scope, then disposable PostgreSQL migration, adversarial role/RLS, row-lock and pool-reuse runs |
| W00 atomic parity ledger | Static 77-case seed and desktop API preflight implemented; false-positive paths closed | 31 focused tests passed; checker 77/77 rows, zero errors; headless Chrome/Edge API probe 2/2 | Trusted W24 run registry and comparator; runtime reachability, Android/iOS/media/permission checks, support matrix sign-off; no `MATCHED` rows and `release_ready=false` |
| W01 TVT bridge feasibility | Static handoff, frozen 199-operation manifest and declaration inventories implemented | 10 schema tests passed; 77 cases / 199 candidate operations; 281 request classes and 299 native declarations inventoried | Vendor rights, runtime fixtures and pilot; all six remote G-P1 families `BLOCKED` |
| T03–T05A and W02–W25 service features | Not started | None | Prerequisite contracts, infrastructure and family-specific gates |

## Local development

1. Use Node.js 24, pnpm 11 and Python 3.12. Install `uv` if absent.
2. Run `python -m uv sync --all-packages --group dev` and `pnpm install --frozen-lockfile`.
3. In one persistent terminal run `python -m uv run uvicorn wso_api.main:create_app --factory --host 127.0.0.1 --port 8000`; in another run `pnpm --filter @wso/web dev --hostname 127.0.0.1 --port 3000`. The current shell shows API liveness and deliberately unavailable readiness.
4. Run `pwsh -File scripts/verify.ps1 -WithBrowser` for implemented offline checks and the desktop Chrome/Edge API probe. The final 2026-09-27 integrated run exited 0: Python 56 passed / 14 live PostgreSQL tests skipped; frontend 2 passed; Playwright 2 passed; Ruff, mypy, typecheck, lint, production build, deterministic contract export and 77-row evidence checker passed. An injected obsolete generated JSON file made the verifier fail as intended and was removed afterward.
5. When Docker is available, run `docker compose -f infra/compose.yaml --profile test up -d`, then the explicitly selected integration checks. The current Windows host has no Docker CLI, so these services have not been exercised.
6. Copy `.env.example` to ignored `.env` only after replacing placeholders appropriate to the environment. Never use real TVT, Tyco or device secrets in local fixtures.

Readiness and S3/Valkey selection remain unverified until container and capability smoke succeeds. External TVT adapters remain disabled until the W01 family gates are documented. The current UI is a health shell, not an APK-equivalent user flow. T02's current PostgreSQL RLS policy trusts a caller-settable tenant setting; its live adversarial release test is expected to fail until a database-verified scope claim replaces that boundary.
