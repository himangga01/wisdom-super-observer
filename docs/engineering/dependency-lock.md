# Dependency lock and runtime evidence

The repository's `uv.lock` and `pnpm-lock.yaml` are the authoritative resolved Python and JavaScript graphs. Package manifests declare supported ranges; installation in CI uses their frozen locks. This document records runtime/container inputs and their verification state.

| Input | Selected version/image | Local evidence | Integration status |
| --- | --- | --- | --- |
| Python | 3.12.10 on Windows | `python --version` | Available |
| uv | 0.12.19 | `python -m uv --version` | Available |
| Node.js | 24.21.0 | `node --version` | Available |
| pnpm | 11.25.0 | `pnpm --version` | Available |
| FastAPI / Pydantic / Uvicorn | 0.141.1 / 2.13.5 / 0.54.0 | `python -m uv tree --depth 1` and `uv.lock` | Integrated offline checks passed; real dependency readiness pending |
| SQLAlchemy / Psycopg / Alembic | 2.1.1 / 3.3.6 / 1.20.0 | `uv.lock` after T02 workspace addition | Offline migration render and type checks passed; PostgreSQL runtime unverified |
| Next.js / React / Tailwind / TypeScript | 16.3.6 / 19.3.0 / 4.3.3 / 5.9.3 | `pnpm list --depth 0 -r` and `pnpm-lock.yaml` | Integrated typecheck, lint, test and production build passed |
| Playwright test runner | 1.63.0 | Root and `apps/web` workspace lock | Desktop Chrome/Edge API preflight 2/2 passed; handset, permission and actual media gates pending |
| PostgreSQL fixture | `postgres:17.11-alpine3.24` | [Official tag list](https://hub.docker.com/_/postgres) | Not pulled or smoked; Docker CLI absent |
| Valkey fixture | `valkey/valkey:9.1.2-alpine3.24` | [Official download/tag list](https://valkey.io/download/) | Not pulled or smoked; Docker CLI absent |
| S3 candidate | `chrislusf/seaweedfs:4.47` | [SeaweedFS release](https://github.com/seaweedfs/seaweedfs/releases/tag/4.47), [container guide](https://github.com/seaweedfs/seaweedfs/blob/master/docker/README.md) | Candidate only; S3 compatibility and image digest unverified |
| Mock external HTTP | `mockserver/mockserver:5.15.0` | [Published image](https://hub.docker.com/layers/mockserver/mockserver/5.15.0/images/sha256-b8a8bc5042b6fd7fbe0acfbf81b23a5f576579fae48fcdecb676c9492905341d) | Not pulled or smoked; Docker CLI absent |

Before selecting any image for production, record the pulled multi-platform digest, license, vulnerability review and a smoke result on the deployment host. A tag alone is not an immutable deployment pin. The S3 candidate must pass put/get/head/delete, multipart, presign and retention cleanup before it becomes the service's AssetStore backend. Valkey must pass broker publish/consume and recovery tests before Celery jobs depend on it.
