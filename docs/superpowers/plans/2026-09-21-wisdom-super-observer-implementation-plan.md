# Wisdom Super Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task after the user selects an execution approach. Steps use checkbox (`- [ ]`) syntax for tracking. This document authorizes no live account changes, purchases, broadcasts, commits, or deployments by itself.

**Goal:** Deliver a multi-tenant unmanned-store platform with sales analytics, multi-source product registration, saved wholesale-site logins, camera incident detection, CLI-generated summaries, mobile notifications, and human-controlled responses.

**Architecture:** A modular FastAPI backend owns authorization, PostgreSQL records, and durable jobs; a Next.js web app and Expo mobile app consume the same contracts. Separate browser, media, inference, CLI, notification, and broadcast workers process narrowly scoped jobs. Store edge gateways ingest camera streams locally; external product writes and broadcasts remain separate from read-only collection.

**Tech Stack:** TypeScript, Next.js, React Native/Expo, Python, FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL, Celery with Valkey compatibility verification, S3-compatible object storage, Playwright Python, ZXing-C++, PaddleOCR, FFmpeg/OpenCV, YOLO-compatible detection, ByteTrack, go2rtc, Codex CLI or Claude CLI, Docker Compose, OpenTelemetry/Prometheus.

**Spec:** [SERVICE_PLAN.md](../../../SERVICE_PLAN.md), including product registration, saved wholesale logins, and the mandatory APK reverse-engineering confirmation. Source SHA-256 at this revision: `1386F0F34C0B58206CAF598134937B118E041D5EB60464CC33718CB87561FCA8`.

**User preparation:** [Korean preparation checklist](../../../PREPARATION_CHECKLIST_KO.md) describes the device/account/sample inputs without storing credentials in the repository.

**Planning date:** 2026-09-21, Asia/Seoul. **Status:** implementation-ready specification of work; application code and live integration checks have not been completed. Every task below is unchecked intentionally.

**Review revision:** The ten findings from the three-agent plan review are addressed in this revision. Section 14 maps each correction to its contract, owning task, and required regression test; unchecked implementation steps remain unimplemented.

**Latest user instruction takes precedence:** LLM execution must use **Codex CLI or Claude CLI**, authenticated through the chosen CLI's supported login. Do not implement a direct OpenAI/Anthropic API client, require an API key, or silently fall back to API billing. This instruction supersedes the source document's GPT-only/provider-authentication wording. Codex is the first adapter to implement; Claude is an interchangeable adapter, not an automatic fallback that sends images to a different provider without configuration.

**Mandatory APK work:** the user explicitly reaffirmed that SuperLive Plus reverse engineering is required. T00A performs APK acquisition/static analysis during initial prerequisite research; T31 consumes its call map for TVT implementation/runtime validation. Working Tapo/RTSP or a public-code survey cannot replace or waive this work. A missing Android device/APK is a pending prerequisite, not a reason to relabel the task optional.

**Navigation:** [Execution](#1-how-to-execute-this-plan) · [Open-source research](#2-open-source-research-and-selection) · [Capability gates](#3-capability-gates-and-external-inputs) · [Repository](#4-repository-and-deployment-layout) · [Data and authorization](#5-data-and-authorization-design) · [Contracts](#6-api-event-and-state-contracts) · [Domain rules](#7-domain-implementation-rules) · [Verification](#8-test-harness-and-verification-commands) · [Tasks](#9-detailed-implementation-tasks) · [Acceptance](#10-release-acceptance-and-measurable-targets) · [Operations](#11-required-operational-behavior) · [Traceability](#12-requirements-traceability) · [Handoff](#13-implementation-handoff) · [Review corrections](#14-review-correction-matrix).

## Global Constraints

- Support multiple owners and one or more stores per owner; never hard-code the initial two stores.
- Authorize every store, object, job, browser session, event stream, and download against the authenticated tenant and assigned stores.
- OrderQueen sales collection is read-only and uses an exact endpoint allowlist. New-product registration is the sole scoped write exception; existing-product edits, deletion, transaction cancellation, price/stock changes, bulk upload, and POS transmission are excluded.
- Wholesale sites allow login and read-only product/order collection; never create, pay for, modify, or cancel wholesale orders.
- OrderQueen sales synchronization runs once on dashboard entry, once on reentry, and on explicit refresh. No recurring sales polling or background scheduled refresh.
- Initial historical backfill is a resumable finite job, not recurring polling. Job-status polling and camera event subscriptions are separate from external sales refresh.
- Store wholesale usernames/passwords and browser state encrypted, isolated per tenant/site/account. Reuse valid sessions; log in again on expiry. Extra authentication is handed to the user.
- Keep barcode strings, leading zeros, variants, pack units, purchase prices, and retail prices distinct. Never invent a barcode or retail margin.
- YOLO/tracking/pose/rules generate incident candidates. Invoke an LLM CLI only for selected incident images and summaries, never continuous CCTV streaming.
- AI output is evidence assistance, not proof of theft, criminal intent, age, or identity. No facial recognition or cross-day person identification.
- Broadcast only after an authorized human approves the exact store, incident, and audio/text payload.
- Camera configuration changes, Android device commands, APK extraction, SDK/device trials, and audible broadcast trials require the user's instruction for that operation. A documentation request does not supply that authority.
- SuperLive Plus APK acquisition and static reverse engineering are mandatory initial research. Complete the evidence-backed Java/Kotlin/JNI/native call map before implementing the TVT connector; use scoped dynamic tracing for unresolved runtime paths. Independent sales/foundation work may proceed while device inputs are pending, but the full CCTV integration cannot be declared complete by substituting a standard camera.
- Use HTTPS, encrypted secrets, minimal personal data, retention/deletion, and access auditing from the first working slice.
- Preserve existing workspace changes. Commit/push only when requested or authorized; task completion does not imply publication.
- Examples in this document are implementation contracts and test seeds, not claims that files or fixtures already exist. Paths under the proposed tree are created by their owning task.

## Review Focus

1. **Cross-tenant references in queued jobs and object downloads:** reject them even when the UUID, browser connection, or storage key is valid. Tests: T02, T03, T18.
2. **Remote save succeeds but the response is lost:** reconcile the target barcode before any retry; never create a second product. Tests: T11, T12.
3. **Missing historical coverage or concurrent shoppers:** unknown data remains unknown; it never becomes zero sales, a payment error, or theft. Tests: T07, T08, T27.
4. **Expired login or credentials deleted during an active job:** stop further external requests, invalidate stale browser contexts, and resume only through an authorized connection. Tests: T04, T13.
5. **CLI hangs, inherits tools, or returns invalid JSON:** terminate the process tree, isolate credentials/data, retain the original incident, and never trigger a broadcast. Tests: T21, T22, T25.

---

## 1. How to execute this plan

Read Sections 1–8 before implementing any task. Then read the selected task, its dependencies, and the relevant contract sections. Do not load or implement every subsystem at once.

Each T-number is an independently reviewable deliverable, not a calendar day. Follow its checkbox cycle: failing behavioral test, focused failure run, implementation, focused and repository-wide verification, evidence record. Split a task into smaller commits when useful, but do not split a state machine across incompatible interfaces. Documentation and setup belong to the feature that needs them.

Write execution evidence to `docs/implementation/ledger.md`: task ID, code revision, commands, actual results, remaining limitations, and capability gates cleared. Create the ledger in T01. A simulated connector passing tests is **not** a verified live connector.

Source precedence is: latest user instruction → `SERVICE_PLAN.md` requirements → this plan's explicit engineering decisions → upstream documentation. If the source file changes, compare requirements before execution; do not overwrite the new requirements with this snapshot.

### 1.1 Proposed decisions versus confirmed requirements

The product behavior above is required. The following are engineering defaults proposed by this plan and can be changed through a short decision record before their implementation:

| Decision | Default | Reason and boundary |
|---|---|---|
| Backend shape | Modular monolith plus process-isolated workers | Shares contracts and transactions without deploying a service per entity |
| Mobile | Expo/React Native | Shares TypeScript contracts with the web; use native builds for push and camera-compatible playback |
| Identity | OIDC authorization-code flow with PKCE; Keycloak in local integration tests | Avoid custom password recovery/MFA logic; tenant membership remains in our DB |
| Object storage | S3 interface; SeaweedFS for local/self-hosted evaluation | Source listed MinIO, but its repository is now archived; retain portability |
| Broker | Celery, Valkey through the Redis transport, gated by integration tests | Queue is delivery infrastructure; PostgreSQL remains job truth |
| First detector | Isolated YOLOX baseline with ByteTrack | Permissive code licenses, but older upstream activity requires compatibility checks |
| Detector alternative | Ultralytics only after the deployment/license choice is recorded | Strong ecosystem; AGPL code and model/deployment conditions need review |
| First stream router | go2rtc | Tapo-specific talkback; MediaMTX remains a tested alternative for generic routing |
| Off-site media transport | Outbound frp tunnel to a private edge gateway for signaling/HLS; coturn for WebRTC relay | Control/signaling and media are separate; no inbound store port forwarding |
| LLM transport | Codex CLI first, Claude CLI selectable | Explicit user choice; no direct API integration |
| First usable slice | Text product intake + OrderQueen catalog/read + verified new registration | Produces operational value before difficult vision work |
| Retention defaults | Evidence 14 days; raw import photos 7 days; sanitized job diagnostics 7 days; audit metadata 180 days | Engineering defaults requiring owner confirmation before real data ingestion, not legal conclusions |

### 1.2 Difficulty and dependency order

| Release gate | Tasks | Difficulty | Demonstrable result |
|---|---|---|---|
| R0: prerequisite research | T00, T00A | Variable, bounded probes | Mandatory APK static analysis/call map completed; other capabilities have evidence or explicit pending status |
| R1: tenant foundation | T01–T05, T05A | Medium | Owner logs in, sees assigned stores, stores a secret/private asset, and runs a durable mock job |
| R2: sales read | T06–T09 | Medium–high | Correct per-store sales with finite backfill and manual refresh |
| R3: text registration | T10–T12 | High | Validated text item is registered once, read back, and audited |
| R4: wholesale/photo intake | T13–T16 | High | Saved login, product/order parsing, OCR, and review feed the same registration pipeline |
| R5: camera incidents | T17–T20 | High | Standard stream, evidence, person/zone candidate, web review |
| R6: summaries/mobile | T21–T24 | Medium–high | CLI summary, push notification, same incident/sales on mobile |
| R7: human responses | T25–T26 | Very high | Approved audio and calibrated behavior/help rules |
| R8: matching and learning | T27–T29 | Very high | Honest payment matching, repeat patterns, controlled model rollout |
| R9: operations/pilot | T30 | High | Recoverable, observable multi-store pilot |
| RTVT: required TVT integration | T31 after T00A | Research, highest uncertainty | APK-informed TVT adapter and runtime evidence; no optional fallback designation |

Dependency edges: `T00 → capability-specific tasks`; `T00A + T17 → T31`; `T01 → T02 → T03 → T04 → T05`; `T03+T05 → T05A`; `T04+T05 → T06 → T07 → T08 → T09`; `T03+T05 → T10`; `T06+T10 → T11 → T12`; `T04+T05 → T13`; `T10+T13 → T14 → T15`; `T05A+T10 → T16`; `T03+T04+T05 → T17`; `T05A+T17 → T18 → T19 → T20`; `T04+T05 → T21`; `T18+T20+T21 → T22`; `T05+T20 → T23`; `T03+T09+T20+T23 → T24`; `T17+T20 → T25`; `T19+T20 → T26`; `T07+T19+T26 → T27`; `T20 → T28`; `T20+T26 → T29`; release gates feed T30. T00A starts in initial research without an application-code dependency; T31 is required follow-through, not a conditional alternative. A partial Tapo/sales pilot may proceed but cannot close the mandatory TVT work or full CCTV completion. T00A/T05A are inserted prerequisite/shared-assets tasks; existing task IDs remain stable.

R3 needs OrderQueen catalog/session support, not completion of advanced sales analytics. R7 payment help does not require a proprietary P2P receiver when standard streams work. Start capability probes early even when their final implementation has high difficulty.

## 2. Open-source research and selection

### 2.1 Evidence method

Repository metadata was retrieved from GitHub's public REST API on **2026-09-21**: `GET https://api.github.com/repos/{owner}/{repo}` for `stargazers_count`, `license.spdx_id`, `archived`, and `pushed_at`; release candidates came from `/releases/latest`. Stars are an exact snapshot, not a quality score, SLA, proof of security, or adoption requirement. A recent push can be automation rather than substantial maintenance. Inspect releases, relevant issues, model weights, and transitive licenses when freezing dependencies.

Use the linked repositories as primary sources. Each row states this plan's recommendation, not an upstream promise of suitability.

| Repository | Stars | Code license reported/inspected | Last push UTC date | Planned use / decision |
|---|---:|---|---|---|
| [Next.js](https://github.com/vercel/next.js) | 142,383 | MIT | 2026-09-21 | Web shell, server-side session boundary; selected |
| [FastAPI](https://github.com/fastapi/fastapi) | 102,499 | MIT | 2026-09-18 | Typed API and OpenAPI; selected |
| [Expo](https://github.com/expo/expo) | 52,366 | MIT | 2026-09-21 | React Native mobile tooling; selected |
| [Keycloak](https://github.com/keycloak/keycloak) | 36,906 | Apache-2.0 | 2026-09-21 | OIDC reference deployment; selected |
| [Playwright](https://github.com/microsoft/playwright) | 96,442 | Apache-2.0 | 2026-09-21 | Deterministic browser adapters and E2E tests; selected |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 89,928 | Apache-2.0 | 2026-09-16 | Korean label/text extraction; isolated OCR worker |
| [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp) | 2,027 | Apache-2.0 | 2026-09-20 | Barcode decoding; selected for fit despite fewer stars |
| [go2rtc](https://github.com/AlexxIT/go2rtc) | 14,228 | MIT | 2026-09-06 | Edge stream reuse, WebRTC, Tapo talkback; selected |
| [MediaMTX](https://github.com/bluenviron/mediamtx) | 20,218 | MIT | 2026-09-20 | Alternative RTSP/WebRTC router; avoid deploying both initially |
| [Ultralytics](https://github.com/ultralytics/ultralytics) | 61,849 | AGPL-3.0 | 2026-09-21 | Detector/pose alternative; license/deployment gate |
| [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) | 10,629 | Apache-2.0 | 2025-06-08 | YOLO-family baseline; compatibility and maintenance risk |
| [ByteTrack](https://github.com/FoundationVision/ByteTrack) | 6,697 | MIT | 2024-06-19 | Tracking algorithm baseline; pin source and regression fixtures |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | 37,022 | Apache-2.0 | 2026-09-18 | Pose candidate; benchmark cropped multi-person use before selection |
| [SeaweedFS](https://github.com/seaweedfs/seaweedfs) | 34,873 | Apache-2.0 | 2026-09-21 | S3-compatible local/self-hosted candidate |
| [MinIO](https://github.com/minio/minio) | 61,355 | AGPL-3.0 | 2026-04-24 | **Archived** at observation; not the new deployment default |
| [Valkey](https://github.com/valkey-io/valkey) | 27,267 | BSD-3-Clause | 2026-09-21 | Cache/locks/broker candidate; test Celery compatibility |
| [Celery](https://github.com/celery/celery) | 28,908 | BSD-3-Clause; API reported NOASSERTION | 2026-09-21 | Durable dispatch with DB-backed reconciliation |
| [CVAT](https://github.com/cvat-ai/cvat) | 16,761 | MIT | 2026-09-21 | Video/pose annotation after feedback exists |
| [MLflow](https://github.com/mlflow/mlflow) | 28,072 | Apache-2.0 | 2026-09-21 | Model experiment and registry metadata, late phase |
| [pytvt](https://github.com/dannielperez/pytvt) | 0 | MIT | 2026-09-16 | Narrow TVT research helper; not a proven production receiver |
| [pytapo](https://github.com/JurajNyiri/pytapo) | 471 | MIT | 2026-09-08 | Targeted compatibility reference; never run full device-changing tests |
| [Frigate](https://github.com/blakeblackshear/frigate) | 36,028 | MIT | 2026-09-21 | Architecture/reference for video processing; do not embed its whole UI/backend |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 84,017 | Apache-2.0 | 2026-09-18 | Optional extraction benchmark; explicit Playwright adapters remain default |
| [Marker](https://github.com/datalab-to/marker) | 39,876 | Apache-2.0 metadata | 2026-09-13 | Not selected: document/PDF focus adds weight for this photo workflow; inspect model terms separately |
| [Prometheus](https://github.com/prometheus/prometheus) | 66,154 | Apache-2.0 | 2026-09-21 | Runtime metrics; selected |
| [Grafana](https://github.com/grafana/grafana) | 76,836 | AGPL-3.0 | 2026-09-21 | Optional internal operations dashboards; review packaging conditions |
| [uv](https://github.com/astral-sh/uv) | 90,027 | Apache-2.0 metadata | 2026-09-21 | Python dependency/workspace tooling; preserve all upstream notices |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | 247,641 | MIT | 2026-09-21 | Not selected: user chose direct Codex/Claude CLI adapters, so no extra agent runtime |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 14,889 | Apache-2.0 | 2026-09-21 | Local TTS candidate; Korean voice quality and individual model terms are separate gates |

The Celery license was checked in its [LICENSE file](https://github.com/celery/celery/blob/main/LICENSE), rather than interpreting GitHub's `NOASSERTION` as a missing license. Code-license labels do not cover every model weight, codec, dependency, or trademark.

### 2.2 Version baseline and compatibility gate

Observed release candidates: Next.js `16.3.5`; FastAPI `0.141.1`; Playwright `1.63.0`; PaddleOCR `3.7.0`; ZXing-C++ `3.1.1`; go2rtc `1.9.14`; MediaMTX `1.21.1`; Ultralytics `8.4.157`; SeaweedFS `4.47`; Valkey `9.1.2`; Celery `5.6.3`; CVAT `2.76.0`; MLflow `3.16.1`. These were reported by each repository's `/releases/latest` endpoint, not installed or tested together. Expo did not return a usable latest-release result; choose its stable SDK and the matching React Native/React versions together during T01/T24.

Local command inspection found Codex CLI `0.155.1` and Claude Code `2.1.278`. Their `--help` outputs establish candidate flags, not successful account authentication or image inference. No CLI inference was executed for this planning task.

T01 must resolve and record a working baseline in `docs/engineering/dependency-lock.md`, `uv.lock`, `pnpm-lock.yaml`, and image digests. Use Python 3.12 for the control plane and Node 24 LTS as proposed runtime baselines; isolate OCR and vision images if their wheels/CUDA requirements need a different compatible Python runtime. Do not force a single GPU image for unrelated OCR and detector stacks. Do not use floating `latest` tags in deployed Compose files. Keep patch/security updates a reviewed lockfile change.

### 2.3 Findings that change the original plan

- **Storage:** the [MinIO repository](https://github.com/minio/minio) is archived. Evaluate SeaweedFS against the exact S3 operations we use: put/get/head/delete, multipart, presigned URLs, and cleanup. Managed S3 remains compatible through the same interface; no hosting purchase is part of this plan.
- **Camera audio:** [TP-Link's guide](https://www.tp-link.com/us/support/faq/2680/) distinguishes RTSP/ONVIF media support from two-way audio. The [go2rtc Tapo adapter](https://github.com/AlexxIT/go2rtc/blob/master/internal/tapo/README.md) uses the proprietary talk channel and different authentication from the RTSP camera account. Model/firmware trials remain mandatory.
- **Vision licensing/maintenance:** [Ultralytics' license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) and older YOLOX/ByteTrack activity make a replaceable detector boundary necessary. An ONNX export does not erase upstream model/license conditions.
- **Browser state:** [Playwright authentication documentation](https://playwright.dev/python/docs/auth) treats saved state as sensitive and distinguishes storage mechanisms. Persist encrypted state through a connection adapter; detect sites requiring unsupported session restoration and log in again rather than claiming universal persistence.
- **Isolation:** PostgreSQL table owners/superusers can bypass ordinary row policies. Use a non-owner application role and force policies where applicable; tests must run with that role. See [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).
- **Queues:** broker redelivery is expected; business idempotency belongs in PostgreSQL. Verify the selected Redis transport/Valkey pairing under worker crashes. See [Celery Redis transport](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html).
- **LLM:** use [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive) and [Claude programmatic execution](https://code.claude.com/docs/en/headless). Do not translate a CLI integration into a direct API implementation. CLI image support, account limits, and process isolation are explicit gates below.
- **Off-site media:** [go2rtc's WebRTC documentation](https://github.com/AlexxIT/go2rtc/blob/master/internal/webrtc/README.md) distinguishes signaling from media delivery. The revised design selects [frp](https://github.com/fatedier/frp) for an outbound reverse tunnel and [coturn](https://github.com/coturn/coturn) for a WebRTC relay, with an HTTPS HLS fallback. These additional transport dependencies require version/license locking and restricted-network verification in T17; a working local stream is insufficient.

## 3. Capability gates and external inputs

Record each gate in `docs/integrations/capabilities.md` with status `UNTESTED`, `SUPPORTED`, `UNSUPPORTED`, or `NEEDS_USER_INPUT`, sanitized evidence, adapter version, and date. A failed gate blocks its dependent capability only, not local fixture-driven development elsewhere.

| Gate | Required input | Probe and evidence | If not supported |
|---|---|---|---|
| G01 OrderQueen read | Authorized account and selected stores | Login, exact read requests/parameters, pagination, source IDs, time zone, redacted HTML/JSON fixtures | Continue fixtures; no guessed live endpoints |
| G02 new product | Target store, registration request, sample product | Inspect required fields and duplicate behavior; one authorized save and readback; determine shared-catalog/POS side effects | Keep candidate review; disable live writer |
| G03 wholesale site | Site URL, account, selected order/time scope | Login success locator, expiry, additional-auth path, product/order fields and pagination | Mark unsupported site/field; allow text/photo input |
| G04 retail price | Explicit sale price or owner-approved conversion rule | Verify currency, unit/pack, tax basis and rounding on examples | Candidate remains `NEEDS_REVIEW` |
| G05 standard camera | Model, hardware/firmware, LAN access, credentials | Read stream, one snapshot, event, reconnect, supported codecs/FPS | Try another authorized standard device; use recorded fixtures |
| G06 CLI | Selected CLI installation, its normal login, account/workload scope | Synthetic image → strict JSON, auth expiry, timeout, isolation and quota behavior | Keep rules-only alerts with summary status unavailable |
| G07 talkback | Speaker/channel, protocol, authorized audible test | Approved short phrase, busy session, timeout and release | Hide unsupported broadcast action; retain manual response |
| G08 payment errors | Documented read-only event or transaction field | Show a real redacted error and its timing/meaning | Only label observed kiosk difficulty, never fabricate a payment error |
| G09 stock history | Historical stock availability source | Establish observed intervals and missing periods | Historical stock effect is unknown, not reconstructed from today's stock |
| G10 required APK/TVT work | Authorized Android device/base+split APKs; SDK/device access for runtime validation | Separate static and runtime records: T00A call map first, then T31 login/channel/frame/alarm/reconnect evidence | Keep required work pending/blocked with evidence and request missing inputs or an explicit scope decision; do not waive it because LAN/Tapo works |
| G11 media/model packaging | Model weights and intended distribution mode | License/source manifest, dependency scan, hardware benchmark | Block that artifact; use an approved alternative |

Fresh CLI login may require a person. Credentials for the CLI are not wholesale credentials and do not belong in the application's general credential table. Use a deployment-owned CLI identity or a separately isolated tenant runner, explicitly mapped in `cli_accounts`; do not silently share a personal account across tenants. Multi-tenant workload eligibility and concurrency limits are validation inputs, not an assumption of unlimited subscription capacity.

For G10, track `static_status` and `runtime_status` separately using the same capability statuses. T00A requires the installed Android app/device or an authorized complete base/split APK set; SDK access and live DVR access are runtime inputs and must not delay available static analysis. Static success does not imply P2P or Talk success. An unsupported runtime result is a finding requiring a user scope/approach decision, not automatic completion of this mandatory requirement.

## 4. Repository and deployment layout

```text
apps/
  web/src/app/                 # Next.js routes and server-side session handlers
  web/src/features/            # domain UI: stores, sales, imports, incidents, connections
  web/tests/                  # component tests; E2E tests are at repository root
  mobile/app/                 # Expo Router screens
  mobile/src/                 # auth, API, secure storage, notifications, player adapters
services/
  api/src/wso_api/             # main, dependencies, domain routers, authorization
  orderqueen-connector/src/wso_orderqueen/
  product-intake/src/wso_intake/
  product-registration/src/wso_registration/
  video-worker/src/wso_video/
  llm-worker/src/wso_llm/      # CLI subprocess adapters only
  notification-worker/src/wso_notifications/
  broadcast-gateway/src/wso_broadcast/
  edge-relay/src/wso_relay/     # authenticated command channel, signaling and HLS proxy
  edge/src/wso_edge/           # device identity, spool, camera/media adapters
packages/
  contracts/src/wso_contracts/ # Python wire models; export JSON Schema/OpenAPI
  contracts/generated/        # generated TypeScript client/types; no manual edits
  core/src/wso_core/           # DB session, jobs, encrypted secrets, audit, storage
  rules/src/wso_rules/         # pure temporal rules
  analytics/src/wso_analytics/ # pure sales metrics, visits, matching, repetition
infra/
  compose.yaml                # control plane and optional profiles
  edge.compose.yaml           # gateway/router/video workers
  relay.compose.yaml          # frps/coturn and central authenticated relay
  migrations/versions/        # Alembic migrations
  keycloak/                   # local test realm, no production credentials
  observability/              # metrics/alerts/dashboard definitions
tests/
  conftest.py                 # shared deterministic factories and services
  unit/ integration/ contract/ acceptance/ e2e/ vision/
  fixtures/                   # sanitized HTML/JSON, synthetic images/clips, CLI transcripts
scripts/                      # repeatable bootstrap, QA, contract export, restore drill
docs/
  integrations/ engineering/ operations/ implementation/
pyproject.toml                # uv workspace, pytest and lint settings
package.json                 # pnpm scripts and workspace tooling
pnpm-workspace.yaml
```

Python distributable names use `wso-*`; import names use underscores as shown above. Add each service/package as a uv workspace member with explicit local dependencies. Web/mobile consume generated types rather than importing Python internals. Workers share code through packages, not HTTP loops back into every internal function.

Name the frontend packages `@wso/web` and `@wso/mobile` so task commands resolve consistently. Python test tooling is pytest + pytest-asyncio (`asyncio_mode = "auto"`), HTTPX/ASGI test clients and fixture-controlled HTTP mocks; web tests use Vitest/Testing Library and Playwright. Ruff and a selected Python type checker run through `scripts/verify.ps1`. Set package-local `test` and `typecheck` scripts explicitly; an absent script must be reported, not mistaken for a passing suite.

Deploy the API/web, connector/browser worker, media worker, and CLI worker as separate processes with different secret/network access. A store edge makes outbound authenticated connections; never expose DVR ports or go2rtc's control UI publicly. Media access requires a short-lived authorized ticket; ticket scope includes tenant/store/camera and stream purpose.

T17 owns the following concrete transport. The edge maintains an mTLS-authenticated outbound WSS command channel to `wso_relay`; commands carry a scoped device ID, command ID, expiry, connection generation and payload hash. Reconnect may resume acknowledged read operations; it cannot replay an uncertain broadcast. The edge separately runs an frp client over an authenticated TLS/WebSocket transport to a central frp server. Its only exported service is the **private edge gateway**, not go2rtc, the DVR, a shell or an arbitrary LAN host. Central reverse-proxy bindings are loopback/private and are assigned from the enrolled device registry, never from a client-supplied hostname or port. Pin frp configuration/version and enforce per-device proxy/destination restrictions.

The browser/mobile client obtains a scoped media session from the API and connects to the public HTTPS/WSS relay. Both relay and edge gateway validate session audience, actor/store/camera, expiry and device generation before allowing that camera's signaling requests. The gateway translates only allowed signaling operations to local go2rtc. **WebRTC media does not ride this HTTP signaling tunnel**: use coturn with short-lived credentials, configure ICE on both peers, and verify UDP and TURN-over-TLS/TCP behavior for the pinned go2rtc/client versions. Tests force relay use behind NAT. If ICE cannot establish media, the edge packages H.264 HLS using FFmpeg and serves its manifest/segments through the same authenticated gateway and reverse tunnel; this fallback works over outbound HTTPS/WSS and has higher declared latency.

A media session has a maximum five-minute lease; renew only after API authorization. Relay/edge close signaling and terminate the associated media consumer at expiry/revocation, not merely when the initial ticket expires. TURN allocation lifetime is bounded independently; TURN credentials alone never select a camera. HLS routes validate the session on every manifest/segment and stop the packager when unused. T25 sends approved audio command metadata through WSS and delivers the approved asset through a scoped HTTPS fetch; it does not depend on exposing the camera talk endpoint. T17 must test this full route off-LAN with inbound connections and UDP blocked, including HLS fallback and expired/revoked sessions.

### 4.1 Runtime configuration contract

T01 creates an `.env.example` containing **names and non-secret local defaults only**. Required names: `DATABASE_URL`, `BROKER_URL`, `OIDC_ISSUER`, `OIDC_WEB_CLIENT_ID`, `OIDC_MOBILE_CLIENT_ID`, `SECRET_KEY_PROVIDER`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `PUBLIC_WEB_ORIGIN`, `CLI_PROVIDER`, `CLI_MODEL`, `CLI_TIMEOUT_SECONDS`, `EVIDENCE_RETENTION_DAYS`, `IMPORT_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`.

Production database/storage/identity credentials are injected as secret files or secret-manager references. No OpenAI/Anthropic API-key variables are required. The CLI process launcher strips inherited API-key environment variables so account-login behavior cannot silently change. A runner's login is provisioned separately using its normal CLI; never print its credential file.

Suggested initial limits, all configurable and measured in the pilot: 20 MiB per photo, 25 million decoded pixels, 100 text candidates per request, 50 registration items per batch, 500 order pages per import, one active browser job per external account, one active CLI inference per CLI account, three representative images per incident, CLI deadline 90 seconds, one transient CLI retry. Reject oversized input before expensive processing.

## 5. Data and authorization design

### 5.1 Shared conventions

- UUID primary keys; `tenant_id` on all tenant-owned rows; composite foreign keys `(tenant_id, referenced_id)` prevent cross-tenant references.
- All stored instants use PostgreSQL `timestamptz`/UTC. Preserve source timezone and original timestamp text for import diagnostics; default store timezone is `Asia/Seoul`.
- Money uses integer minor units plus currency. KRW values are integer won. Quantity uses `numeric(18,3)` where fractional quantities are possible; never use float for money.
- Barcode is text. Preserve leading zeros; distinguish EAN-13, EAN-8, UPC-A, and internal SKU identifiers. Unsupported/ambiguous codes require review rather than digit padding.
- Use `(tenant_id, store_id, provider, external_id)` for imported identity where possible. No stable ID means fingerprint + collision review, not blind merging by display name.
- Keep historical source records and import coverage separate from derived analytics. Refreshing a recent window is an upsert, never an additive double count.
- Audit actor, action, scoped entity ID, correlation ID, timestamp, and sanitized result. Never audit plaintext credentials, browser cookies, raw CLI prompts, or whole payment payloads.

### 5.2 Tables and essential invariants

| Group / tables | Essential fields and indexes |
|---|---|
| `tenants`, `users`, `memberships`, `store_memberships` | OIDC subject unique by issuer; membership unique `(tenant,user)`; role `OWNER/MANAGER/STAFF`; explicit store assignment |
| `stores`, `kiosks` | tenant, source store/POS IDs, timezone, active flag; unique external store identity per connection |
| `store_connections` | tenant, store, connection, provider and external store ID; explicit mapping used by reader/writer ports; reject ambiguous active mapping |
| `connections`, `credential_versions`, `connection_sessions` | provider/site/account alias, domain allowlist reference, encrypted blob, key ID, version, generation, state, last success; unique active account scope |
| `jobs`, `job_items`, `outbox`, `inbox_dedup` | type, scope, idempotency key, payload version/hash, lease token, attempts, state, timestamps; unique scoped idempotency key |
| `dispatch_ready` | restricted control-plane projection of job/outbox ID, tenant, kind, due_at, lease and dispatch state; no business payload or secrets |
| `assets` | tenant, optional store, purpose, private key/checksum/type/size, parent asset, state and expires_at; generic upload/cleanup owned by T05A |
| `sync_coverage`, `sync_cursors`, `sync_requests` | resource/window coverage and cursor; requested_at/required_fresh_after, resource sweep start and completion, fulfilled request IDs; coverage and freshness are separate |
| `products`, `product_price_states`, `stock_observations` | external product ID, barcode, variant/unit, price interval, observed stock timestamp; no assumed historical stock |
| `transactions`, `transaction_items`, `payments`, `cancellations` | source keys, POS, occurred_at, signed totals, currency, cancellation linkage; exclude card/member fields not needed |
| `store_operating_days`, `daily_product_metrics`, `product_trends`, `demand_patterns` | explicit OPEN/CLOSED/UNKNOWN daily calendar and provenance; gross sold/returned/net quantity, metric version, coverage, nullable stock adjustment and confidence |
| `import_jobs`, `product_candidates`, `product_sources` | input kind, source URL/order/line, asset IDs, barcode/name, variant options, sellable unit, pack quantity, purchase/sale price basis, tax basis, adapter-schema fields, errors, revision |
| `registration_jobs`, `registration_items`, `registration_write_holds` | frozen request and attempt; unique active hold `(tenant,store,barcode)` survives job/lease expiry, cancellation and new idempotency keys until definitive reconciliation |
| `edge_devices`, `cameras`, `camera_health`, `zones`, `behavior_rules` | scoped device identity, capability flags, heartbeat, source clock offset, zone polygon, rule version |
| `person_tracks`, `visit_sessions`, `detection_events`, `incidents` | track epoch, timestamps, zone/rule/model versions, confidence, evidence IDs, review status; no biometric identity |
| `evidence_assets`, `incident_summaries`, `model_feedback` | evidence references generic `assets`; capture window, masking, CLI/provider version, structured summary and feedback provenance; no second object lifecycle |
| `alerts`, `alert_deliveries`, `push_devices` | event ID, recipient user/device, delivery state, retry count, provider receipt; unique recipient/event/channel |
| `staff_visit_modes`, `broadcast_commands` | selected rules and expiry; exact approved audio hash, actor, incident, camera, expiry, state |
| `payment_matches`, `review_decisions`, `repeat_patterns` | visit/transaction candidate links, algorithm version, evidence windows, status, user verdict |
| `cli_accounts`, `cli_runs`, `model_versions`, `model_deployments` | runner reference, tenant mapping, capability/login state, quota backoff; model artifact hash, metrics, active/canary version |

Connection-secret deletion removes active access immediately; delete/rotate wrapped encryption keys and document backup expiry. Object deletion is a two-step tombstone plus physical delete with retries. Do not claim deletion from every backup instantaneously.

### 5.3 Authorization and RLS

API derives tenant context from authenticated membership, never trusts a request's `tenant_id`. Managers see assigned stores; staff see assigned stores and their permitted staff-mode actions. Owner-only defaults: credentials, registration, role changes. Manager broadcasts require explicit store permission. System operators see sanitized health metadata only; evidence access is a separately audited exceptional grant.

For every **tenant data** transaction, set the validated tenant using transaction-local configuration. Application workers run as a non-owner, non-`BYPASSRLS` role. Migrations use a separate role. Background jobs reload scope and permission at execution time, not just enqueue time. Authentication bootstrap and dispatch discovery have the narrowly scoped paths defined below; they do not grant a global business-data bypass.

```sql
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents FORCE ROW LEVEL SECURITY;
CREATE POLICY incidents_tenant_policy ON incidents
USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
```

Apply equivalent policies to tenant business tables. Store assignment is additionally enforced in repositories/endpoints. Test a reused pooled connection after a different tenant's transaction and a job carrying another tenant's entity ID.

**Identity bootstrap (T02/T03):** after validating the OIDC signature, issuer, audience and expiry, a separate `wso_identity_bootstrap` connection sets transaction-local `app.oidc_issuer` and `app.oidc_subject` from that verified token, never request JSON. This role can select only the minimal `users` identity columns and `memberships` membership columns. Role-specific SELECT RLS policies allow the matching issuer/subject user and memberships linked to that user, without requiring a selected tenant. It has no grants on stores, jobs, credentials or evidence, no writes, no `BYPASSRLS`, and cannot `SET ROLE` to application/migration roles. Return the authorized tenant choices, then validate the selected tenant and use the ordinary app pool with tenant RLS. Unset principal context returns no rows; invalid/forged tokens are rejected before reaching this pool, and pooled connections reset transaction settings. The backend is the trusted identity-context setter, not a public SQL endpoint; a database session setting is not itself cryptographic proof of a principal. Owner onboarding provisions identity/membership through an explicitly scoped administrative flow; login does not auto-grant membership from a supplied tenant ID.

**Dispatcher bootstrap (T05):** write tenant `jobs`/`outbox` and the minimal `dispatch_ready` projection in one transaction. A distinct `wso_dispatcher` role may claim due projection entries across tenants and publish only `(job_id,outbox_id,tenant_id,kind,lease_generation)` references; it cannot select tenant job payloads or any other business table. Claim/ack operations use restricted stored functions with a fixed search path, explicit grants (PUBLIC revoked), parameter bounds and a NOLOGIN owner with privileges only on this projection. Application enqueue/completion functions can update a projection entry only for the matching tenant job; user-facing roles cannot write arbitrary projection rows. Workers load the referenced job under tenant RLS, check its persisted kind/scope/actor/current permissions, and ignore any untrusted payload in a broker message. Expired dispatch leases are discovered from the projection, while domain-job recovery occurs inside that job's tenant transaction. Function/role tests must prove discovery succeeds without granting global access to payloads or memberships.

## 6. API, event, and state contracts

### 6.1 HTTP conventions

Base path `/api/v1`. JSON uses snake_case and UTC RFC3339 times. Cursor pages return `{items,next_cursor}`; no unbounded list endpoints. Ordinary async operations return `202 {job_id,state}`. Sales sync creation returns `202 {sync_request_id,job_ids,state,required_fresh_after}` because a request may wait for a trailing job; request state is `PENDING/FULFILLED/FAILED/CANCELLED` and is distinct from individual job state. Errors return `{code,message,details,request_id}` with sanitized details. Use 401 for unauthenticated, 403 for a disallowed operation on an accessible scope, 404 for inaccessible foreign resources, 409 for revision/idempotency conflicts, 422 for invalid data, and 429 for bounded admission limits.

`Idempotency-Key` is mandatory for sync/import/registration/broadcast creation. Scope the key to tenant + operation + target; persist the request hash. Same key/same payload returns the original result; same key/different payload returns 409. Browser-entry keys include a navigation-instance ID so legitimate later reentry is not suppressed.

| Endpoint | Contract / authorization |
|---|---|
| `GET /me`, `GET /stores` | current memberships and only accessible stores |
| `POST /connections`, `PATCH /connections/{id}`, `DELETE /connections/{id}` | owner manages secret-bearing connections; responses never contain passwords |
| `POST /connections/{id}/check`, `POST /connections/{id}/auth-resume` | bounded login check; owner-bound additional-auth continuation |
| `POST /stores/{id}/sync-jobs` | reason `INITIAL_BACKFILL/DASHBOARD_ENTRY/MANUAL_REFRESH`; authorized owner/manager |
| `GET /sync-requests/{id}` | own request watermark, pending/fulfilled state, associated jobs and per-resource observation times; local status read only |
| `PUT /stores/{id}/operating-calendar` | owner/authorized manager sets effective-dated OPEN/CLOSED schedule and exceptions; unknown history remains UNKNOWN |
| `GET /jobs/{id}` | local job status only; never triggers a source refresh |
| `GET /stores/{id}/sales`, `GET /sales/aggregate` | date/product/category filters; coverage and freshness always included |
| `POST /imports`, `GET /imports/{id}/candidates` | text/photo/product URL/order-scope input; async extraction |
| `POST /assets/uploads`, `PUT /assets/{id}/content`, `POST /assets/{id}/complete`, `GET /assets/{id}/download`, `DELETE /assets/{id}` | tenant-scoped bounded upload/verification/private access; photo imports reference READY asset IDs |
| `PATCH /candidates/{id}` | human correction with `expected_revision`; derived fields recomputed |
| `POST /registration-jobs` | frozen selected candidate revisions + target store + explicit registration request |
| `GET /registration-jobs/{id}` | per-item results and unresolved remote state |
| `GET /cameras`, `GET /cameras/{id}/health`, `POST /cameras/{id}/media-ticket` | assigned-store access; no raw secret RTSP URL |
| `PUT /cameras/{id}/zones`, `PUT /cameras/{id}/rules` | versioned owner/manager rules; reject stale edits |
| `GET /incidents`, `GET /incidents/{id}`, `POST /incidents/{id}/review` | state + evidence + summary + feedback; authorization per store |
| `POST /staff-visit-modes`, `DELETE /staff-visit-modes/{id}` | scoped rules, maximum duration and actor |
| `POST /incidents/{id}/broadcasts` | approved text/audio hash and target; supported camera only |
| `GET /events` | authorized SSE stream, resume cursor; event body contains IDs/minimal metadata |
| `POST /push-devices`, `DELETE /push-devices/{id}` | bind token to current user; revoke on logout |
| `GET /visits/{id}/payment-match`, `POST /payment-matches/{id}/review` | evidence/coverage/ambiguity visible; never a crime label |
| `GET /stores/{id}/patterns` | aggregate incident repetition, no person identification |

Web login uses same-origin HTTP-only Secure cookies via an OIDC BFF; state/nonce and PKCE are validated. Mutating cookie-authenticated requests require CSRF protection and origin checks. Mobile uses PKCE with system browser, secure token storage, and registered redirects. API validates issuer, audience, signature, expiry and membership. Identity provider login does not authorize a store by itself.

### 6.2 Canonical Python wire types

T01 owns these models in `packages/contracts/src/wso_contracts/models.py`; later tasks extend them through reviewed schema changes. Money and public ID formats remain stable.

```python
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class TenantScope(WireModel):
    scope_kind: Literal["TENANT"] = "TENANT"
    tenant_id: UUID

class StoreScope(WireModel):
    scope_kind: Literal["STORE"] = "STORE"
    tenant_id: UUID
    store_id: UUID

JobScope = Annotated[TenantScope | StoreScope, Field(discriminator="scope_kind")]

class Money(WireModel):
    amount_minor: int = Field(ge=0)
    currency: Literal["KRW"] = "KRW"

class VariantOption(WireModel):
    name: str
    value: str

class ProductCandidate(WireModel):
    id: UUID
    tenant_id: UUID
    revision: int = Field(ge=1)
    barcode: str | None
    name: str | None
    purchase_price: Money | None
    sale_price: Money | None
    variant_options: list[VariantOption] = Field(default_factory=list)
    sellable_unit: str | None = None
    pack_quantity: int | None = Field(default=None, ge=1)
    purchase_price_basis: Literal["PER_PACK", "PER_SELLABLE_UNIT", "UNKNOWN"] = "UNKNOWN"
    sale_price_basis: Literal["PER_SELLABLE_UNIT", "UNKNOWN"] = "UNKNOWN"
    purchase_tax_basis: Literal["INCLUSIVE", "EXCLUSIVE", "EXEMPT", "UNKNOWN"] = "UNKNOWN"
    sale_tax_basis: Literal["INCLUSIVE", "EXCLUSIVE", "EXEMPT", "UNKNOWN"] = "UNKNOWN"
    registration_schema_id: str | None = None
    registration_fields: dict[str, StrictStr | StrictInt | StrictBool] = Field(default_factory=dict)
    source_kind: Literal["TEXT", "PHOTO", "PRODUCT_PAGE", "ORDER_HISTORY"]
    source_ref: str
    confidence: float = Field(ge=0, le=1)
    errors: list[str]

class EventEnvelope(WireModel):
    event_id: UUID
    event_type: str
    schema_version: Literal[1] = 1
    tenant_id: UUID
    store_id: UUID | None
    occurred_at: datetime
    correlation_id: UUID
    payload: dict

class IncidentSummary(WireModel):
    incident_id: UUID
    verdict: Literal["SUPPORTED", "UNCERTAIN", "NOT_SUPPORTED"]
    summary_ko: str
    visible_person_count: int | None = Field(ge=0)
    observed_actions: list[str]
    uncertainty_reasons: list[str]
    evidence_ids: list[UUID]
    suggested_warning_ko: str | None = None
```

`Money` is for nonnegative product prices. Signed transaction/refund totals use a separate `SignedMoney` model with unconstrained integer amount; never negate or reject cancellations through the product-price validator. Evidence IDs in a CLI result must be a subset of the supplied evidence manifest. `suggested_warning_ko` is optional draft text only; it cannot approve or enqueue a broadcast. Event type/version selects a registered payload model; validate `EventEnvelope.payload` against that model at publication and consumption, rejecting unknown versions to a diagnostic dead-letter state.

T05's job-kind registry requires `TenantScope` for connection checks, wholesale login, asset processing and imports; it requires `StoreScope` for sales sync, registration, incidents and broadcast. A tenant-only job cannot invoke a store mutation; the registration request selects and authorizes a real store before constructing `StoreScope`. Persist `scope_kind`; DB checks require a non-null store ID only for STORE jobs and prohibit it for TENANT jobs. Idempotency uses an explicit tenant-operation target for tenant jobs, never a fake store UUID or an unscoped NULL unique key. Asset IDs/connection IDs in tenant jobs still require matching tenant ownership.

T10 owns the full `ProductCandidate` schema above. Preserve variant names/values and unit distinctions from every input through review; an empty variant list means no known options, not proof of equivalence between two products. Adapter-specific registration fields are validated against the versioned, allowlisted schema identified by `registration_schema_id`, including required keys, types and accepted values established by G02. They are not arbitrary form selectors or executable instructions. Unknown price/unit/tax information required by the selected form blocks READY status. Any change to a submitted value, variant, unit, tax/price basis or schema version increments the candidate revision; freeze the full validated payload, schema ID, target store and revision in the registration hash. The writer receives that same snapshot and cannot rederive choices from a changed source page.

### 6.3 Process ports

These are our interfaces, not claims about external SDK method names. T01 creates protocol declarations with postponed annotations; the owning tasks introduce their result models and implementations together. The model names and fields below are contractual, so downstream tasks must not invent alternate names.

```python
# packages/contracts/src/wso_contracts/ports.py
from __future__ import annotations
from datetime import datetime
from typing import Protocol
from uuid import UUID

# Import the named contract models under TYPE_CHECKING as their modules land.
# These are protocol methods, not runnable connector implementations.
class OrderQueenReader(Protocol):
    async def list_stores(self, connection_id: UUID) -> list[SourceStore]: ...
    async def fetch_page(self, scope: StoreScope, resource: str,
                         params: dict, cursor: str | None) -> SourcePage: ...
    async def find_product(self, scope: StoreScope, barcode: str) -> SourceProduct | None: ...

class WholesaleAdapter(Protocol):
    async def ensure_session(self, connection_id: UUID) -> SessionHandle: ...
    async def product(self, connection_id: UUID, url: str) -> list[ProductCandidate]: ...
    async def order_page(self, connection_id: UUID, selection: OrderSelection,
                         cursor: str | None) -> OrderPage: ...

class RegistrationWriter(Protocol):
    async def register_new(self, scope: StoreScope, candidate: ProductCandidate,
                           attempt_id: UUID) -> RegistrationReceipt: ...

class CameraAdapter(Protocol):
    async def list_cameras(self, scope: StoreScope) -> list[CameraInfo]: ...
    async def get_stream(self, camera_id: UUID, purpose: str) -> StreamHandle: ...
    async def get_detection_events(self, camera_id: UUID, since: datetime) -> list[CameraEvent]: ...
    async def capture_snapshot(self, camera_id: UUID, timestamp: datetime) -> Snapshot: ...
    async def get_health(self, camera_id: UUID) -> CameraHealth: ...
    async def start_talk(self, camera_id: UUID) -> str: ...
    async def send_audio(self, talk_id: str, audio_path: str) -> None: ...
    async def stop_talk(self, talk_id: str) -> None: ...

class CliRunner(Protocol):
    async def health(self, account_id: UUID) -> CliHealth: ...
    async def summarize(self, account_id: UUID, manifest: RunManifest) -> IncidentSummary: ...
```

The ellipses mark **protocol declarations**, not missing implementation steps. Models are owned by T06 (OrderQueen), T12 (registration receipt), T13/T15 (wholesale), T17 (camera), T21 (CLI), and T01 (shared types). Add each typed port when its result models land so static checking never accepts unresolved names; the block above is the final target interface, not an instruction to commit a failing initial module. Provider-native payloads are parsed into these models and never returned directly through the public API. Public request models are stricter than internal `fetch_page` parameters: each allowlisted resource has its own parameter schema established by G01/T06.

### 6.4 Job and registration states

Generic job: `QUEUED → RUNNING → SUCCEEDED | PARTIAL | FAILED | NEEDS_USER_INPUT | CANCELLED`. A lease-expired read-only job can requeue with bounded backoff; an external write first enters reconciliation. Persist attempts, heartbeat and lease generation. Use outbox publication and consumer deduplication so DB commit and broker interruption cannot lose a job.

Registration item: `DRAFT → NEEDS_REVIEW | READY → QUEUED → SUBMITTING → VERIFYING → REGISTERED | ALREADY_EXISTS | UNKNOWN_REMOTE_STATE | FAILED`. A conflicting existing item becomes `NEEDS_REVIEW`. `UNKNOWN_REMOTE_STATE` cannot transition directly to `SUBMITTING`: read back first and record a decision. Approval/request scope freezes candidate revision, store ID and payload hash; editing the candidate invalidates queued approval.

An item encountering another attempt's active hold enters `BLOCKED_BY_UNRESOLVED_ATTEMPT` from READY/QUEUED, with the blocking attempt ID. Once the original hold is definitively resolved, re-run authorization/revision checks and preflight before any transition to QUEUED/ALREADY_EXISTS/NEEDS_REVIEW. It never jumps directly from blocked to SUBMITTING. A canceled requested item remains canceled even if the original hold later clears.

Before entering `SUBMITTING`, atomically acquire a durable `registration_write_holds` row uniquely keyed by `(tenant_id,store_id,barcode)` and bind it to the attempt. It remains active throughout `SUBMITTING`, `VERIFYING` and `UNKNOWN_REMOTE_STATE`, even if the worker lease expires, the job is canceled, another candidate/batch is created, or an idempotency key changes. A new request for that key reports `BLOCKED_BY_UNRESOLVED_ATTEMPT` and links the existing item; it cannot submit. The ephemeral per-barcode lock serializes transitions but does not replace the durable hold.

Release the hold only in a transaction recording definitive reconciliation: matching remote product exists, a conflicting existing product ends the attempt without a write, or the remote operation is proven not to have been accepted and can no longer commit. A single absent/temporarily stale catalog read is not proof of failure. If the site has no authoritative operation status or verified consistency bound, retain `UNKNOWN_REMOTE_STATE` and require a documented operator/source resolution; never auto-expire the hold or treat cancellation as permission to retry. A late acknowledgement/readback resolves the original attempt, not a new submit. Reconciliation workers may retry reads while retaining the hold.

Wholesale connection: `DISCONNECTED → LOGGING_IN → CONNECTED | ADDITIONAL_AUTH_REQUIRED | LOGIN_FAILED`. Account edits increment `generation`, invalidate sessions and cancel old contexts. Generation is checked before navigation and before every externally mutating registration step.

## 7. Domain implementation rules

### 7.1 OrderQueen reads, history, and metrics

Exact read allowlist from the source document:

```text
BAS01020_STORE_LST.itp
SAL02020_LIST.itp SAL02020_CHART.itp
SAL02010_LIST.itp SAL02010_CHART.itp
SAL03020_LIST.itp SAL03020_CHART.itp
SAL03070_LIST.itp SAL03070_CHART.itp
SAL03080_LIST.itp SAL03080_CHART.itp
SAL01020_LIST.itp SAL01020_POPUP.itp SAL01020_PAYMENT.itp
SAL01060_LIST.itp SAL01030_LIST.itp
MNU01020_LST.itp MNU01050_LST.itp SYS02010_POSLIST.itp
```

Allowlisting applies to resolved scheme/host/path and validated parameters, not substring matching or HTTP method alone: reads commonly use POST. Login/navigation resources are a separate minimal authentication allowlist verified by G01. Cross-host redirects fail closed. Changes in expected columns or an HTML login page returned as 200 are parser/session errors, never empty sales.

Initial backfill: discover stores, query monthly summaries across the source-supported date range, find each store's first nonempty month, then page through transactions/items/cancellations/catalog. Store coverage per resource and window. Checkpoint only after DB commit. On continuation, repeat the last page safely by source-key upsert. A store with no sales remains valid.

Incremental refresh default: recent 35 calendar days plus any explicitly requested historical window. This is a **proposal**, not proof all delayed cancellations occur within 35 days. Reconcile monthly summary totals and offer an explicit historical rescan when mismatched; do not schedule hidden rescans.

Each distinct dashboard-entry/reentry/manual request persists `required_fresh_after = server_received_at` separately from its date window. Each resource sweep records `sweep_started_at` before its first request, `completed_at` after all pages commit, and complete coverage. A request is fulfilled only when every required resource/window has complete coverage from a sweep started **at or after** its freshness watermark. Completion time alone is insufficient: a job may finish after the click while its transaction page was fetched before it. Source-side replication delay is reported separately; the watermark guarantees a new observation, not information the source has not yet exposed.

Coalescing accumulates outstanding request IDs, unioned windows and the maximum required freshness watermark under a per-store lock. If the active sweep already started too early, retain one trailing finite sync job; after the active job finishes, that job re-reads affected resources/windows and satisfies all requests it covers. Requests arriving after the trailing job has started can require one further trailing job by the same rule. Never schedule a sweep without an outstanding explicit request or finite initial-backfill checkpoint. Repeated clicks with the same idempotency key are the same request; a distinct click/navigation is not discarded merely because the date range matches.

Metric definitions (T08 implements pure functions):

- Net revenue = source-consistent sale revenue minus linked refunds; distinguish tax-inclusive/exclusive source totals and never subtract the same cancellation twice.
- Preserve `gross_sold_quantity`, `returned_quantity` and `net_quantity = gross_sold_quantity - returned_quantity` separately. Gross demand counts completed positive sales on their sale date; voided/never-completed sales are excluded. Completed-sale returns remain returns on their observed return date and do not erase the original demand observation. Record this policy/version; a source correction of a falsely imported sale is a data correction, not a return.
- Calendar velocity = sum of net quantity over complete observed days / number of complete observed calendar days. Trading-day velocity = sum of net quantity on complete OPEN days / number of complete OPEN days, including OPEN days with no sales. Active-sales-day velocity is an additional, distinctly named metric: sum of net quantity on complete positive-sale days / number of those days. Expose period totals separately so denominator-specific numerators are not confused.
- Store operating days are OPEN/CLOSED/UNKNOWN in the store timezone, with source/owner confirmation and an effective-dated schedule/exception record. A confirmed 24/7 schedule can mark every covered day OPEN; never infer OPEN from a sale or CLOSED from zero sales. UNKNOWN operating days yield a null full-window trading-day metric plus `OPERATING_CALENDAR_UNKNOWN`. Zero denominators yield null. Incomplete source days are excluded and reported; show coverage and warn that any remaining ratio is over observed days only.
- Revenue contribution = product net revenue / store net revenue; zero/nonpositive denominator returns null and a reason.
- Momentum = `(recent_daily_rate + alpha) / (previous_daily_rate + alpha) - 1`, initially `alpha=0.1 units/day`, equal complete windows of 7 or 28 days. Record alpha/window/version; sparse/new items receive insufficient-data labels.
- ADI = complete observed calendar days / days with positive **gross sold quantity**. CV² = population variance of those positive daily gross sold quantities / squared mean of the same quantities. Returned/net quantities and sale transaction counts cannot substitute for gross quantities. Exclude incomplete days without converting them to zeros. Zero positive days yields no finite demand classification.
- Initial experimental ADI/CV² boundaries: 1.32 and 0.49, labeled an engineering baseline to validate, not universal truth. Return raw values and sample size; require at least 28 complete days and 5 positive-demand days for this label.
- Stock-adjusted metrics use observed stock intervals only. Unknown stock history remains null. Today's sold-out flag cannot explain a sale-free day six months ago.
- Confidence is an explained component vector (coverage, days, transactions, stock availability), not an uncalibrated probability. A deterministic low/medium/high label uses documented thresholds and shows reasons.

### 7.2 Intake and registration

Text format supports explicit columns `barcode,name,sale_price` (CSV/tab-delimited with quoted names) and labeled lines; ambiguous free-form text yields candidates requiring review. `"8801234567893"` is a synthetic valid EAN-13 test value; it is not a real product assertion.

Photos first undergo file-signature validation, orientation normalization and bounded resizing. Decode barcodes through ZXing-C++; use OCR for names/prices. Associate text to barcode regions; multiple products require explicit grouping, not nearest price blindly. A checksum is error detection, not proof that a barcode belongs to the named product.

Wholesale adapters are allowlisted plugins in application code, each with hostnames, login form locators, authenticated-state evidence, parser version, pagination rules and fixtures. A user's arbitrary URL is not an arbitrary network destination: allow only the configured site's public HTTPS hosts, validate redirects/DNS, block loopback/private/link-local/metadata addresses, and enforce outbound firewall policy. The edge camera network uses a different network policy and is not reachable by the browser worker.

Use Playwright directly and parse rendered DOM fields. Do not delegate browser navigation or saving to an unconstrained LLM agent. Ignore page text that asks to change workflow, reveal secrets, or submit forms. Order extraction is scoped to selected order IDs or a finite date range; canceled lines remain marked, and only selected purchasable variants feed registration.

Registration runs after local validation and target-store catalog read. Lock `(tenant,store,barcode)` across batches and enforce the persistent cross-job write hold in Section 6.4 before any submit. An existing product is `ALREADY_EXISTS` only when all comparable registration values match, including variant/unit/pack and required tax/adapter fields; a name/barcode/price match alone does not establish equivalence. Missing comparison data or differing values require review and never overwrite. Form save request paths/CSRF fields are discovered through G02, not guessed. If site registration affects other stores or automatically triggers unsupported POS changes, stop the live capability until the user resolves that scope. Save acknowledgement alone is insufficient: read the catalog and compare the frozen submitted fields available through the verified source contract; unverifiable required fields prevent automatic verified-success status.

### 7.3 Media, detection, and incidents

Keep a bounded edge ring buffer; initial evidence target is 10 seconds before and 10 seconds after the event. If the available clip is shorter, record actual coverage. Prefer substream sampling for inference and main stream for evidence; count the physical sessions during G05 instead of assuming all protocols can share one camera connection.

`capture_snapshot(camera_id,timestamp)` resolves a retained frame near the requested instant or a verified device playback capability. A live-only camera cannot supply arbitrary historical snapshots: return `FRAME_UNAVAILABLE` with available coverage rather than substituting a current image under an old timestamp.

Frame manifest contains camera ID, stream epoch, capture timestamp, monotonic sequence, decoder timestamp, and clock-quality flag. Drop stale frames older than the configured 2-second inference lag budget; do not replay a reconnect backlog as new live incidents. On reconnect, increment epoch so reused track IDs cannot merge people across sessions.

Zones are normalized polygons in `[0,1]`, versioned with source dimensions. Use footpoint/pose contact evidence rather than mere box overlap for freezer rules. Running uses calibrated floor speed where possible and body-scale-normalized displacement otherwise, with confidence reduced when perspective is unknown. Hand waving requires repeated wrist motion over time plus visibility; camera-facing intent remains uncertain if pose cannot establish it.

An incident merges compatible detections for the same camera/rule/track epoch inside a configurable cooldown, initially 15 seconds. Persist rule/model versions and triggering measurements. Staff mode suppresses selected notifications, not evidence recording, payment records, or every alert in a store; it expires automatically.

### 7.4 Codex CLI and Claude CLI execution

Implementation uses `asyncio.create_subprocess_exec` with an argument array and stdin, never a shell-built command. Each job gets a private temporary workspace containing only selected images, a manifest, a schema, and an output path. A dedicated runner account/container must have no wholesale/camera credentials, general app DB credentials, user project plugins/hooks, or other tenants' media. Read-only CLI flags alone are **not** a filesystem isolation boundary; mount/ACL isolation and a restricted runner network are required.

Codex candidate argument vector, verified against local `codex exec --help` (capability-test the exact deployed version):

```python
args = [
    "codex", "exec", "--ephemeral", "--skip-git-repo-check",
    "--ignore-user-config", "--sandbox", "read-only",
    "--json", "--output-schema", str(schema_path),
    "--output-last-message", str(result_path),
    "--cd", str(job_dir), "--image", str(image_path), "-",
]
# For multiple images, append supported image arguments before the final '-'.
# Send the instruction and metadata through stdin; never include secrets.
```

Codex `--ignore-user-config` does not replace OS isolation or the authentication profile. Normal supported CLI login is provisioned in the runner context; job-specific workspaces cannot read its raw auth files. Parse JSONL for execution state, then parse/validate the final schema-constrained result. Preserve sanitized error categories, CLI version, selected model, latency and available usage counters; do not infer API charges from CLI usage.

Claude candidate text-only invocation uses `claude -p --output-format json --json-schema <schema-json> --tools "" --strict-mcp-config --no-session-persistence --disable-slash-commands`. Add a controlled settings configuration that disables hooks and unmanaged MCP; verify those effects during G06. Do **not** use `--bare` for subscription login: the inspected local help says it skips OAuth/keychain auth. Do not use permission-bypass flags.

Claude image input is a **G06 capability check**: validate the deployed CLI's documented stream-JSON image input or constrained local image-read mechanism using a synthetic image. Implement only the mode that succeeds with normal CLI login and an image-specific test; do not treat Claude's `--file` remote-resource flag as a local image flag. If no mode passes, report `UNSUPPORTED_IMAGE_INPUT` for that adapter while retaining the working Codex image path. Image-bearing stream JSON, if selected, must be built using a JSON serializer rather than shell concatenation.

Initial scheduler: one job per CLI account, 90-second deadline, bounded queue, one retry for an explicitly transient transport failure. `AUTH_REQUIRED`, `QUOTA_LIMITED`, `UNSUPPORTED_IMAGE_INPUT`, `INVALID_OUTPUT`, `TIMEOUT` are distinct states. A timeout kills the full process tree (POSIX process group; Windows Job Object or equivalent tested mechanism), then removes media from the temporary workspace. No cross-tenant resume sessions. No automatic Codex↔Claude fallback.

Prompt contract: describe only visible actions; distinguish measurements from interpretation; return `UNCERTAIN` when occluded; write Korean summary; use only supplied evidence IDs; do not infer age/crime/identity. An optional polite warning draft is plain text for human review, never an execution instruction. CLI output cannot authorize registration or broadcast. A failed summary does not erase or delay the initial rule-based alert.

### 7.5 Visit/payment/help semantics

Build visits from entrance/exit/kiosk zones and bounded inactivity. Use camera topology and timing for cross-camera candidates, not facial identity. Preserve multiple hypotheses when crossings are ambiguous. Correct source clock offsets before matching; offsets beyond tolerance mark the visit for review.

Match store + POS + kiosk interval to transactions, initially allowing configurable ±120 seconds. Enforce a transaction-to-visit assignment constraint; multiple plausible visits remain `REVIEW_REQUIRED`. Matching runs after a visit closes **using currently synchronized local transactions**, and is recalculated after a user-triggered source sync. It never causes periodic external sales polling.

If the relevant transaction window is not completely synchronized, emit `REVIEW_REQUIRED` with `SOURCE_NOT_FRESH`; absence is not `NO_MATCH_CANDIDATE`. A visual repeated attempt without an authoritative error event is `KIOSK_DIFFICULTY`, not `PAYMENT_ERROR`. The latter requires G08 evidence.

Statuses: `PAID_CONFIRMED` only with an explicit human or deterministic source link; ordinary time proximity is `PAID_LIKELY`. Also support `REVIEW_REQUIRED`, `NO_MATCH_CANDIDATE`, `PAYMENT_ERROR`, `CANCELLED_TRANSACTION`. Display reasons, candidate transactions, clock quality, coverage and cancellation state.

## 8. Test harness and verification commands

T01 creates the scripts below; these are intended commands for the future repository, not commands that currently pass. Default tests use synthetic media, mock HTTP sites, local PostgreSQL/S3/broker, and fake CLI executables. Live tests are opt-in and require scoped credentials/device authorization. Use Linux containers for Celery/media; PowerShell is a supported orchestration shell.

```powershell
uv sync --all-packages --group dev
pnpm install --frozen-lockfile
docker compose -f infra/compose.yaml --profile test up -d
uv run alembic -c infra/alembic.ini upgrade heads
uv run pytest -m "not live" -q
pnpm -r typecheck
pnpm -r test
pnpm exec playwright test
pwsh -File scripts/verify.ps1
```

`scripts/verify.ps1` runs Python formatting/lint/type checks, all non-live Python tests, TypeScript checks/tests, contract regeneration drift checks, and fixture-backed browser E2E against a started test stack. Task-local commands are for fast feedback; completion requires the full relevant repository suite, including failures outside the edited file. Mobile native smoke and GPU benchmarks are separately recorded; do not pretend desktop CI proves APNs/FCM delivery or device inference speed.

Independent asset/catalog migrations branch from their actual shared prerequisite; use `upgrade heads` while independent feature heads exist, and create an explicit merge revision at a release boundary. A numerically earlier filename is not a dependency. T30 tests both independent feature upgrades and the merged release graph from an empty DB and the prior release.

The no-polling requirement has **two** tests: T09 observes frontend sync-request triggers using browser time; T07 observes actual mock-upstream sales reads using the backend's injected clock/scheduler after jobs settle. [Playwright clock](https://playwright.dev/docs/clock) controls browser timers, not the backend scheduler. Neither job counts nor a successful frontend test substitute for the backend invariant.

Fixture factories created in T01/T02/T05: two tenants, owner/manager/staff sessions, three stores with different assignments, scope IDs, an isolated DB role, fake clock, temporary object storage, fake reader/writer/browser/CLI ports, job factory and sanitized HTML fixture loader. A task adds only the fixtures it needs and defines their behavior in its test file or `tests/conftest.py`.

Every synthetic date and barcode below is test data. Test code uses public methods defined in the owning task; failures should initially be missing behavior, not syntax errors or accidental external network calls.

## 9. Detailed implementation tasks

### T00 — Record external capabilities without guessing contracts

**Dependencies:** none for public research; live probes require G01–G11 inputs. **Difficulty:** variable research.

**Create:** `docs/integrations/capabilities.md`, `docs/integrations/orderqueen.md`, `docs/integrations/wholesale-sites.md`, `docs/integrations/cameras.md`, `docs/integrations/cli-runners.md`.

**Consumes:** user-authorized account/device scope and Section 3. **Produces:** versioned capability records used by connector and runner factories.

- [ ] Create one row per G01–G11, preserving untested status where evidence is absent; include a sanitized evidence location and the exact dependent task.
- [ ] For each authorized site, record canonical hosts, login boundary, authenticated-state proof, required request fields, pagination termination and stable source keys. Record a site that requires manual extra authentication explicitly.
- [ ] For each authorized camera, record model/firmware, LAN route, codec, timestamp behavior, active stream count and talk capability. No configuration writes are part of this read probe.
- [ ] Inspect deployed CLI `--version` and `--help`; with authorization for inference, run a synthetic image test and a structured-output test. Record account-login and isolation behavior without copying tokens.
- [ ] For product saving and audible talk, first prepare the exact sample and expected result. Execute only with the scope needed for that live write; record readback/audio observation separately from screen inspection.
- [ ] Review each result: evidence must support the specific capability, not an adjacent one. Login success does not prove order parsing; one snapshot does not prove continuous P2P video.

**Exit:** independent developers can tell which capabilities work, which are blocked, and which local adapters can be built using fixtures. Do not delay all foundational work while waiting for one device.

### T00A — Mandatory SuperLive Plus APK acquisition and static reverse engineering

**Dependencies:** authorized installed Android app/device or an authorized complete APK set; no T01/T17 application dependency and no vendor SDK requirement for static inspection. **Difficulty:** high research; mandatory initial work.

**Create:** `docs/integrations/superlive-static-analysis.md`, `docs/integrations/tvt-call-map.md`. Store raw APKs/splits, decompiled files, native binaries and secret-bearing captures outside Git; repository reports contain only sanitized technical evidence and artifact hashes.

**Interfaces:** produce an `ApkAnalysisManifest` in the report with app version, APK hashes, split/ABI inventory, analysis tools/versions and a call map keyed by capability. Each call-map entry records Java/Kotlin class/method, JNI binding, native symbol or binary offset, input/output structure, callback/lifetime observations, evidence reference and confidence; unknown paths are explicitly listed for dynamic validation. T31 consumes this report rather than repeating acquisition as optional work.

- [ ] Confirm the exact SuperLive Plus installation and APK/device scope. For the installed-device path, have the user connect the Android phone with a USB data cable and authorize USB debugging; then run the scoped ADB device/path checks and copy base plus relevant split APKs. Do not store device serials or account secrets in reports.
- [ ] Record versions/hashes/ABI inventory and inspect the Manifest, Java/Kotlin and resources using JADX/apktool. Map login/session/channel/live/alarm/talk entry points; do not infer successful connectivity from an endpoint string alone.
- [ ] Inspect native libraries with readelf/nm/strings and Ghidra. Follow `JNI_OnLoad`, `RegisterNatives` and exported JNI bindings into NAT selection, login, preview start/stop, compressed-video callbacks, alarm callbacks, Talk/Broadcast send/stop, and decoder input boundaries.
- [ ] Write the evidence-backed call graph and data/lifetime assumptions. Identify H.264/H.265 frame boundaries, threading/callback ownership and any unknown or obfuscated paths needing scoped runtime tracing. Distinguish confirmed static facts from hypotheses.
- [ ] Review the report against each required path, verify artifact hashes and evidence references, and record G10 static status. Static completion means the acquired code has been analyzed and its confirmed/unresolved paths documented, not that every runtime behavior has been proved. Missing APK/code inspection is never a completed static gate.

**Exit:** the mandatory static report and call map are reviewed and available before TVT implementation. Dynamic traces, actual frame/alarm reception and Talk support remain T31/G10 runtime evidence. Tapo/RTSP success cannot substitute for this deliverable.

### T01 — Establish a reproducible workspace and typed health contract

**Dependencies:** none. **Difficulty:** low–medium.

**Create:** root `pyproject.toml`, `uv.lock`, `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.gitignore`, `.env.example`; `services/api/pyproject.toml`, `services/api/src/wso_api/main.py`; `packages/contracts/pyproject.toml`, `packages/contracts/src/wso_contracts/models.py`, `packages/contracts/src/wso_contracts/ports.py`; `apps/web/package.json`, `apps/web/tsconfig.json`, `apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx`; `infra/compose.yaml`, `scripts/verify.ps1`, `scripts/export_contracts.py`; `tests/conftest.py`, `tests/contract/test_health.py`; `docs/implementation/ledger.md`, `docs/engineering/dependency-lock.md`.

**Interfaces:** `create_app() -> FastAPI`; `GET /health/live -> {status:"ok"}`; `GET /health/ready -> 200|503` with sanitized dependency readiness. Implement Section 6 wire models; export their JSON Schema and the API OpenAPI document deterministically.

- [ ] Add the failing health test and a readiness test with DB unavailable. Build the package manifests and local test installation required to collect it.

```python
from fastapi.testclient import TestClient
from wso_api.main import create_app

def test_liveness_has_no_dependency_secrets():
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] Run `uv run pytest tests/contract/test_health.py -q`; confirm missing endpoint/behavior fails.
- [ ] Implement `create_app`, request ID/error middleware, contracts, and a Compose test profile for PostgreSQL, Valkey, S3 candidate, and mock external sites. Bind test services to loopback. Add ignore rules for auth state, APKs, device identifiers, raw media, logs, `.env`, and CLI workspaces.
- [ ] Add lockfile/contract scripts and QA commands from Section 8. Verification runs all currently implemented workspace packages and must not silently skip a failing test; it does not require future mobile/GPU packages to exist in T01. Run the selected broker and S3 capability smoke before marking those backends selected; record actual versions/digests, not just Section 2 candidates.
- [ ] Run the focused test, contract export twice (no diff), and `pwsh -File scripts/verify.ps1`. Record the baseline and any unavailable native/GPU checks.

**Exit:** one documented local bootstrap produces the same health contract and test environment from a clean checkout. No real credentials are required.

### T02 — Build tenant schema and prove database isolation

**Dependencies:** T01. **Difficulty:** medium, high consequence.

**Create:** `packages/core/pyproject.toml`, `packages/core/src/wso_core/db.py`, `packages/core/src/wso_core/tenancy.py`; `infra/alembic.ini`, `infra/migrations/env.py`, `infra/migrations/versions/0001_tenants.py`; `tests/integration/test_tenant_isolation.py`.

**Interfaces:** `tenant_session(tenant_id: UUID)` is a context manager yielding a transaction-bound SQLAlchemy session; `identity_session(verified_issuer: str, verified_subject: str)` exposes only the Section 5.3 bootstrap lookup; `StoreRepository(session).list_visible(user_id: UUID) -> list[Store]`. `Store` maps `id,tenant_id,name,timezone,active`; composite scoped references follow Section 5.

- [ ] Create migrations for tenants/users/memberships/stores/store assignments and audit metadata, with indexes and RLS. Test fixtures provision rows using a migration role; assertions run under the restricted application role.

```python
def test_database_role_cannot_read_another_tenant(scoped_db, tenants):
    with scoped_db(tenants.a.id) as session:
        ids = set(session.execute_text("select id from stores").scalars())
    assert tenants.a.store_id in ids
    assert tenants.b.store_id not in ids
```

`scoped_db` is a T02 fixture wrapping `tenant_session`; its `execute_text` adapter uses SQLAlchemy `text()` and bound parameters. Add foreign-tenant insert/FK, missing tenant context, and pooled-connection reuse tests.

- [ ] Run `uv run pytest tests/integration/test_tenant_isolation.py -q` against actual PostgreSQL; SQLite is not a substitute for this gate.
- [ ] Implement transaction-local tenant settings, explicit application/migration/bootstrap roles, forced policies and tenant-aware repositories. Implement the role-specific identity lookup from Section 5.3 before requiring tenant selection; reject unvalidated tenant IDs before establishing an ordinary tenant session.
- [ ] Add `test_bootstrap_lists_only_verified_subject_memberships` with two tenants for one user and a third tenant for a different user; select no tenant before lookup. In T02, test unset-principal, stale pooled-setting, denied writes/role switches and denied bootstrap SELECT on the existing stores table. T03 owns invalid-token rejection before bootstrap; T04/T05 extend denied-table tests when secrets/jobs exist. Bootstrap reads must pass while foreign memberships and already-existing business data remain inaccessible; T02 does not depend on later API/schema tasks.
- [ ] Run migration from empty DB and from the immediately prior schema, then isolation tests and repository verification. Record generated SQL constraints in the migration review.

**Exit:** API and workers cannot read or attach another tenant's objects even when they know the IDs.

### T03 — Implement identity, store authorization, and the web shell

**Dependencies:** T02. **Difficulty:** medium.

**Create:** `services/api/src/wso_api/auth.py`, `services/api/src/wso_api/stores/router.py`; `apps/web/src/app/api/auth/login/route.ts`, `apps/web/src/app/api/auth/callback/route.ts`, `apps/web/src/app/api/auth/logout/route.ts`, `apps/web/src/app/stores/page.tsx`, `apps/web/src/lib/session.ts`; `infra/keycloak/test-realm.json`; `tests/contract/test_store_permissions.py`, `tests/e2e/store-switching.spec.ts`.

**Interfaces:** `require_tenant(action: str, tenant_id: UUID) -> TenantScope`; `require_store(action: str, store_id: UUID) -> StoreScope`; the verified OIDC principal first uses T02's restricted identity lookup, then selects an authorized tenant and enters ordinary RLS. `GET /me` and `/stores` use Section 6 responses. Use a maintained OIDC client library locked in T01 rather than implementing token cryptography.

- [ ] Add cross-tenant and restricted-staff tests with a signed test issuer and seed assignments.

```python
def test_store_list_is_scoped(api_client, users, stores):
    response = api_client.as_user(users.staff_a).get("/api/v1/stores")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["items"]] == [str(stores.assigned.id)]
```

- [ ] Run `uv run pytest tests/contract/test_store_permissions.py -q`; confirm scope is not yet enforced.
- [ ] Implement OIDC callback state/nonce/PKCE validation, secure session cookie, CSRF/origin checks, token expiry and logout. Verify JWT issuer/audience and use stored membership, not user-supplied roles. Staff and system-operator restrictions are explicit policy checks.
- [ ] Add the staged bootstrap integration test from T02: malformed signatures, wrong issuer/audience and expired tokens are rejected before opening the identity pool; a valid token lists only its own memberships before tenant selection.
- [ ] Build responsive navigation, store selection, empty/loading/error states and keyboard-accessible forms. Invalidate tenant/store query caches on switch/logout; no global shared Next.js cache for personalized responses.
- [ ] Add browser tests for single-store and multi-store owners, browser-back navigation, expired login and malicious foreign-store URL; run contract and E2E suites.

**Exit:** authenticated users see exactly their accessible stores; a URL change cannot grant access.

### T04 — Create encrypted connection management and credential lifecycle

**Dependencies:** T03. **Difficulty:** medium–high.

**Create:** `packages/core/src/wso_core/secrets.py`, `packages/core/src/wso_core/connections.py`; `services/api/src/wso_api/connections/router.py`; `apps/web/src/features/connections/connection-form.tsx`; `infra/migrations/versions/0002_connections.py`; `tests/integration/test_connection_secrets.py`.

**Interfaces:** `SecretStore.put(tenant_id: UUID, connection_id: UUID, plaintext: bytes) -> version_id`; `SecretStore.with_secret(connection_id, generation)` grants short-lived worker-only access after tenant authorization; `ConnectionService.disconnect(connection_id)` revokes sessions/jobs. Connections belong to a tenant and can map to multiple stores through `store_connections`; they do not require an invented store ID at creation. `Connection` returns alias/site/status/last_success only, never the saved password.

- [ ] Add encryption round-trip, ciphertext tamper, wrong tenant/AAD, API redaction and revocation tests.

```python
def test_disconnect_invalidates_existing_generation(connections):
    account = connections.create_wholesale(username="fixture", password="not-real")
    old_generation = account.generation
    connections.disconnect(account.id)
    assert connections.can_access(account.id, old_generation) is False
    assert connections.secret_count(account.id) == 0
```

- [ ] Run `uv run pytest tests/integration/test_connection_secrets.py -q` and observe the missing lifecycle behavior.
- [ ] Use a maintained authenticated-encryption primitive through a key-provider abstraction; bind tenant/connection/version as associated data. Keep keys outside DB rows and generated configs. Local development uses an untracked key file; production uses a secret manager/KMS-backed provider. Do not invent crypto.
- [ ] Implement owner-only create/update/delete, generation changes, sanitized audit, worker-only decrypt, and active browser invalidation hooks. Redact secrets from validation errors and tracing.
- [ ] Test password changes while a worker holds a prior generation, reconnection after update, and deleted-connection retries; run repository verification.
- [ ] Extend T02's restricted-role matrix for the newly created credential/session tables: `wso_identity_bootstrap` must have no SELECT or mutation access to them.

**Exit:** credentials support real automated login later while remaining unreadable through general API/UI/logs.

### T05 — Add durable jobs, outbox, leases, and idempotency

**Dependencies:** T02, T04. **Difficulty:** medium–high.

**Create:** `packages/core/src/wso_core/jobs.py`, `packages/core/src/wso_core/outbox.py`, `packages/core/src/wso_core/worker.py`, `packages/core/src/wso_core/dispatch.py`; `services/api/src/wso_api/jobs/router.py`; `infra/migrations/versions/0003_jobs.py`; `tests/integration/test_job_delivery.py`, `tests/integration/test_dispatch_permissions.py`.

**Interfaces:** `enqueue(scope: JobScope, kind, payload, idempotency_key) -> Job`; `claim(job_id, worker_id) -> lease_token`; `complete(job_id, lease_token, result)`; `Job` persists its discriminated scope, Section 6 state, hash, heartbeat and item results. `claim_dispatch_batch(limit,worker_id)` returns metadata-only references under `wso_dispatcher`, not full tenant jobs.

- [ ] Add duplicate delivery, changed payload/key conflict, outbox recovery and expired worker lease tests.

```python
def test_duplicate_delivery_has_one_domain_effect(job_harness):
    job = job_harness.enqueue_counter(key="same-request")
    job_harness.deliver(job.id)
    job_harness.deliver(job.id)
    assert job_harness.effect_count(job.id) == 1
```

- [ ] Run `uv run pytest tests/integration/test_job_delivery.py -q` using a real broker for crash/restart cases.
- [ ] Store job, outbox and minimal `dispatch_ready` reference in one DB transaction; implement the restricted dispatcher functions/grants in Section 5.3. Publish references with retry; consumer dedup and lease fencing prevent old workers completing a new attempt. Use bounded backoff for reads and explicit reconcile handlers for writes. Job payload contains IDs, not passwords or presigned media URLs.
- [ ] Add `test_tenant_import_without_store_is_queueable` and `test_registration_rejects_tenant_only_scope`; the first enqueues the registered IMPORT job kind with a contract-valid fixture payload before any stores exist, without executing the not-yet-built intake handler. The second fails job-kind/scope validation before any writer runs. Test cross-tenant existing connection IDs and tenant-only idempotency uniqueness here; T05A tests asset IDs when its table exists, and T13/T16 own the real storeless login/import acceptance. Extend bootstrap denied-table checks to the newly created jobs/outbox tables.
- [ ] Add `test_dispatcher_discovers_two_tenants_without_payload_access`: discover due references with no selected tenant, deny direct SELECT on tenant jobs/credentials/memberships, then process each reference under its stored tenant scope. Test a forged kind/tenant envelope, lease recovery, and application attempts to insert a reference for a foreign tenant job.
- [ ] Enforce tenant/connection generations on claim. Add cancellation checks and a separate queue for browser/CLI/media work so one hung process cannot starve all work.
- [ ] Crash after DB commit/before publication, crash after publication/before ack, and restart Valkey; verify no lost domain request and no false exactly-once claim for external writes.

**Exit:** at-least-once delivery is safe and job status survives worker/broker restart.

### T05A — Add generic private uploads, storage, and retention before photo intake

**Dependencies:** T03, T05; no camera dependency. **Difficulty:** medium–high.

**Create:** `packages/core/src/wso_core/storage.py`, `packages/core/src/wso_core/assets.py`, `packages/core/src/wso_core/retention.py`; `packages/contracts/src/wso_contracts/assets.py`; `services/api/src/wso_api/assets/router.py`; `infra/migrations/versions/0003a_assets.py`; `tests/integration/test_private_assets.py`.

**Interfaces:** `AssetStore.begin_upload(scope: JobScope, purpose, content_type, byte_size, checksum) -> UploadSession`; `complete_upload(asset_id) -> Asset`; `authorize_download(actor,asset_id) -> DownloadTicket`; `delete_asset(asset_id)` tombstones and schedules physical removal. `Asset(id,tenant_id,store_id,purpose,parent_asset_id,state,checksum,byte_size,expires_at)` uses the scope's real optional store and state `PENDING/READY/DELETING/DELETED/REJECTED`. `UploadSession(id,asset_id,upload_path,expires_at,max_bytes)` permits only that asset's authenticated `PUT /assets/{id}/content` route. Purposes initially include IMPORT_PHOTO, IMPORT_CROP and EVIDENCE; purpose-specific authorization/retention remains explicit. Import photos/crops may use TenantScope; EVIDENCE requires StoreScope and camera authorization.

- [ ] Create a real test-S3 fixture and HTTP upload test with two tenants but **no stores/cameras**. Add truncated upload, mismatched checksum/type, size/pixel limits, wrong-tenant reference and abandoned upload expiry cases.

```python
def test_photo_upload_does_not_require_a_store(asset_harness):
    scope = asset_harness.tenant_without_stores()
    asset = asset_harness.upload_photo(scope, "synthetic-label.png")
    assert asset.state == "READY"
    assert asset.store_id is None
    assert asset_harness.foreign_download(asset.id).status_code == 404
```

- [ ] Run `uv run pytest tests/integration/test_private_assets.py -q` before implementing the missing upload lifecycle.
- [ ] Stream uploads through the bounded authenticated asset gateway to private S3 keys; verify actual length/checksum/content signature before READY. A multipart completion callback is not proof of a valid image. Add decoded-pixel checks before OCR; never trust a supplied object key or content type. `POST /imports` accepts only owned READY photo asset IDs, not arbitrary file paths/URLs.
- [ ] Implement tenant authorization, optional store restriction, expiring download tickets, audit, expiry tombstones, retryable deletion and cleanup of incomplete multipart uploads. Crop derivatives inherit tenant/access constraints and cannot outlive their parent retention unless an explicit retention decision permits it. A deletion request blocks new access immediately and accounts for already-issued ticket lifetimes.
- [ ] Test asynchronous job retry reading the same asset after process restart, parent/crop cleanup, wrong-tenant job references and idempotent deletion; run full verification without starting any camera container.

**Exit:** R4 photo intake can persist/read/expire private inputs independently of T17/T18. T18 extends this shared asset lifecycle with camera evidence metadata and buffering; it does not create another storage implementation.

### T06 — Implement the OrderQueen read boundary and catalog

**Dependencies:** T04, T05, G01 for live access. **Difficulty:** high.

**Create:** `services/orderqueen-connector/pyproject.toml`, `services/orderqueen-connector/src/wso_orderqueen/client.py`, `allowlist.py`, `parsers.py`, `catalog.py`; `packages/contracts/src/wso_contracts/orderqueen.py`; `infra/migrations/versions/0003b_catalog.py` for catalog/POS/store-connection mapping; `tests/contract/test_orderqueen_reader.py`; `tests/fixtures/orderqueen/` redacted list/chart/login pages owned by this task. Keep this migration independent of camera/assets; Alembic branch dependencies must match task dependencies rather than filename order.

**Interfaces:** implement `OrderQueenReader`. Define `SourceStore(id,name)`, `SourcePage(items,next_cursor,source_total,source_timezone)`, `SourceProduct(external_id,barcode,name,sale_price,variant_options,sellable_unit,pack_quantity,sale_tax_basis,registration_fields,verified_fields)`. Unknown source fields remain explicitly unknown; `verified_fields` states which comparison fields were actually observed. Parsers return typed normalized records plus sanitized parse diagnostics.

- [ ] Add fixture tests for stores, product/transaction pages, Korean names, locale currency, no-sales pages, pagination, expired-login HTML, changed column layout and blocked write endpoints.

```python
import pytest
from wso_orderqueen.allowlist import validate_read_request

def test_write_name_is_not_a_read_endpoint():
    with pytest.raises(ValueError, match="ENDPOINT_NOT_ALLOWED"):
        validate_read_request("https://www.orderqueen.kr/backoffice_admin/MNU01020_SAVE.itp")
```

- [ ] Run `uv run pytest tests/contract/test_orderqueen_reader.py -q`; no test performs a live save.
- [ ] Implement exact host/path allowlisting, verified auth bootstrap, read POST requests, cookie isolation, CSRF/session renewal where observed, response content-type and page-shape checks. The sample blocked save name is synthetic; never use it as a real writer endpoint.
- [ ] Implement read catalog/store/POS discovery and source identity mapping. Compare existing store grants before attaching newly discovered stores; record provenance, do not auto-attach a foreign tenant's connection.
- [ ] Run all fixture tests and a scoped read-only smoke if G01 is authorized; record verified parameters and hashes without secrets.

**Exit:** catalog and store discovery are usable independently of analytics or product writes.

### T07 — Implement historical backfill and explicit refresh

**Dependencies:** T06. **Difficulty:** high.

**Create:** `services/orderqueen-connector/src/wso_orderqueen/sync.py`, `normalization.py`; `services/api/src/wso_api/sales/sync_router.py`; `infra/migrations/versions/0004_sales.py` for transactions/coverage/freshness requests/operating calendar; `tests/integration/test_sales_sync.py`, `tests/integration/test_sales_polling_policy.py`.

**Interfaces:** `run_sync(job_id: UUID) -> SyncResult`; `SyncResult` has store/resource/window coverage, sweep start/completion timestamps, fulfilled request IDs, rows upserted, resumable cursor and errors. `request_sync(scope: StoreScope, reason, navigation_id, window, received_at) -> SyncRequest` persists a server-clock freshness watermark and returns request ID plus active/queued job references. `received_at` is set internally, not accepted from client JSON. Coalescing follows Section 7.1, not just window equality.

- [ ] Build finite-page fixtures spanning an empty early year, first active month, two POS devices, cancellation, missing page and a repeated page.
- [ ] Implement authenticated sync-request status and operating-calendar endpoints from Section 6.1; store confirmed effective dates, exceptions, actor and provenance. A shop with no known schedule remains UNKNOWN until verified; calendar edits recompute local metrics without automatically querying OrderQueen.

```python
def test_resume_does_not_double_count_sales(sync_harness):
    sync_harness.fail_after_page(2)
    job = sync_harness.start_backfill()
    sync_harness.resume(job.id)
    assert sync_harness.transaction_count() == 12
    assert sync_harness.coverage(job.id).complete is True
```

- [ ] Run `uv run pytest tests/integration/test_sales_sync.py -q`.
- [ ] Implement source-month discovery, per-store/resource paging, checkpoint-after-commit, idempotent upsert and cancellation linkage. A repeated cursor or page fingerprint terminates with `PAGINATION_LOOP` and incomplete coverage, not a silent success.
- [ ] Implement entry/manual reasons, locks and explicit 35-day recent window; record monthly reconciliation mismatches. Preserve missing/failed windows independently from empty successful windows.
- [ ] Persist outstanding freshness requests and atomically schedule the one needed trailing job. Add `test_refresh_after_transaction_read_requires_trailing_sweep`: pause a job after its transaction page, add a source sale, issue a manual refresh with the same date range, complete the job, and verify a later sweep includes the sale and fulfills the second request. Repeat for reentry and multiple coalesced clicks; completion timestamps alone must not satisfy them.
- [ ] Add a backend `Clock`/scheduler fixture used by every source-sync scheduling path. After all initial jobs/retries settle, record the mock server's **actual outbound sales-read request counter**, advance backend time five minutes and drain due tasks; assert zero new reads. Browser/job-status calls are excluded from this counter. Exercise reentry/manual refresh separately. Add a deliberate test-only periodic reader as a negative control and demonstrate that the invariant detects its extra calls; no production scheduler may periodically create external sales reads.
- [ ] Test duplicate dashboard entry in development strict mode, simultaneous refresh, resuming a long backfill, late refund outside the recent window, and no recurring source calls during an idle dashboard.

**Exit:** dashboard refresh and finite backfill are correct under retries, with honest coverage/freshness.

### T08 — Build explainable product metrics

**Dependencies:** T07. **Difficulty:** medium algorithms, high data correctness.

**Create:** `packages/analytics/pyproject.toml`, `packages/analytics/src/wso_analytics/sales.py`, `confidence.py`; `tests/unit/test_sales_metrics.py`.

**Interfaces:** `product_metrics(observations: list[DailyObservation], config: MetricConfig) -> ProductMetrics`; define `DailyObservation(day,gross_sold_quantity,returned_quantity,net_quantity,net_revenue,positive_sale_count,coverage_complete,operating_state,operating_source,stock_state)`, where `operating_state` is OPEN/CLOSED/UNKNOWN. Validate `net_quantity = gross_sold_quantity - returned_quantity`. `ProductMetrics` exposes separate calendar/trading-day/active-sales-day velocities, their numerators/denominators, coverage and nullable results/reasons from Section 7.1.

- [ ] Write numeric fixtures covering full windows, zero sales, negative net revenue, refunded-only days, one observation, unknown stock and incomplete coverage.

```python
from wso_analytics.sales import demand_pattern

def test_no_positive_days_is_not_smooth_demand():
    result = demand_pattern([0] * 28, complete_days=28)
    assert result.label == "INSUFFICIENT_DATA"
    assert result.adi is None
    assert result.cv_squared is None
```

Define `demand_pattern(gross_quantities:list[float], complete_days:int) -> DemandPattern` in `sales.py`; inputs are nonnegative gross sale quantities for complete observed days, never net/refund quantities. `DemandPattern` contains label/ADI/CV²/reasons/sample size. Preserve decimal quantities in production normalization; fixture integers are exact examples.

- [ ] Run `uv run pytest tests/unit/test_sales_metrics.py -q`.
- [ ] Implement Section 7.1 formulas using integer money and explicit denominators; store metric config/version with aggregates. Rank within store/category and expose component metrics alongside labels.
- [ ] Verify golden examples: quantity 28 over 28 complete days gives velocity 1; incomplete days do not become zeros; a current sold-out observation does not alter old metrics. Test zero denominators and cancellation double-subtraction.
- [ ] Add `test_refund_does_not_erase_gross_demand`: compare a 10-unit sale plus 9-unit return with a 1-unit sale/no return. They have equal net quantity but different preserved demand quantities. Evaluate `[10,1,1,1,1] + [0]*23` versus `[1,1,1,1,1] + [0]*23`; CV² must differ. Move the return to a later day and assert net accounting changes on the return day while gross demand on the original sale day remains unchanged; voided sales remain excluded.
- [ ] Add `test_trading_days_include_zero_sale_open_days`: 28 units sold on seven of 28 confirmed OPEN days yields calendar/trading velocity 1 and active-sales-day velocity 4 (with no returns). Mark an operating day UNKNOWN and require null trading velocity with its reason; test CLOSED days, all-closed denominator, effective-dated 24/7 confirmation and incomplete observation windows.
- [ ] Run unit and sync integration suites; compare dashboard totals to normalized source totals in a fixture window.

**Exit:** metrics are reproducible and explain uncertainty rather than hiding it in one score.

### T09 — Ship the sales dashboard and refresh behavior

**Dependencies:** T03, T07, T08. **Difficulty:** medium.

**Create:** `services/api/src/wso_api/sales/router.py`; `apps/web/src/app/sales/page.tsx`, `apps/web/src/features/sales/queries.ts`, `sales-table.tsx`, `product-detail.tsx`; `tests/e2e/sales-refresh.spec.ts`.

**Interfaces:** Section 6 sales endpoints return `SalesPage(items,coverage,as_of,metric_version,next_cursor)`; client `enterSales(navigationId)` creates one `SyncRequest` and uses cached reads/request-job status until explicit refresh. Display outstanding freshness requests even if coalesced behind another job. Calendar/trading-day/active-sales-day labels, coverage and unknown operating-calendar reasons are distinct in the table/detail view.

- [ ] Add a frontend-trigger E2E test against the **application sync-request** counter. This intentionally does not claim to prove backend source inactivity; T07 owns that separate test.

```typescript
import { test, expect } from './fixtures';

test('an idle dashboard creates no new sync requests', async ({ ownerPage, syncRequests }) => {
  await ownerPage.goto('/sales');
  await expect.poll(() => syncRequests.count()).toBe(1);
  await ownerPage.clock.fastForward('05:00');
  expect(await syncRequests.count()).toBe(1);
  await ownerPage.getByRole('button', { name: 'Refresh' }).click();
  await expect.poll(() => syncRequests.count()).toBe(2);
});
```

T09 creates `tests/e2e/fixtures.ts` with authenticated `ownerPage` and `syncRequests.count()` backed by the application's test-only request observer; the browser clock is installed before navigation. T07 creates a separate backend harness whose counter increments on every sales-read HTTP request received by the mock OrderQueen server, including repeated reads inside the same job. Add the following tests in `tests/integration/test_sales_polling_policy.py`:

```python
import pytest

def assert_no_idle_source_reads(harness):
    before = harness.upstream.sales_read_request_count
    harness.clock.advance(seconds=300)
    harness.scheduler.run_due_tasks()
    assert harness.upstream.sales_read_request_count == before

def test_idle_backend_does_not_read_orderqueen(sales_policy_harness):
    sales_policy_harness.complete_initial_sync_and_drain_retries()
    assert_no_idle_source_reads(sales_policy_harness)

def test_no_polling_guard_detects_a_periodic_reader(sales_policy_harness):
    sales_policy_harness.complete_initial_sync_and_drain_retries()
    sales_policy_harness.install_test_only_periodic_reader(interval_seconds=60)
    with pytest.raises(AssertionError):
        assert_no_idle_source_reads(sales_policy_harness)
```

The negative control installs a periodic reader only in the test harness; it must cause the exact production-invariant assertion to fail. Clear that fixture between tests. Run the same counter check after local job-status polling and local sales GETs; those requests must not trigger source reads. The harness advances all backend scheduling decisions through its injected clock, including retry due times, and starts the idle measurement only after requested work/retries are complete.

- [ ] Run `pnpm exec playwright test tests/e2e/sales-refresh.spec.ts` and confirm refresh semantics fail before implementation.
- [ ] Implement store/all-store views, product/barcode/category filters, period comparison, pagination, quantities/revenue/trends, Best/Worst and stock/confidence explanations. Show partial coverage, stale data and sync progress without clearing the last valid data.
- [ ] Disable focus-refetch and interval-refetch on source-sync mutations. Local data cache revalidation must not itself create external sync jobs. Test reentry creates a new navigation ID and exactly one new source sync.
- [ ] Verify mobile-width and keyboard interaction, tenant switch cache isolation and empty store behavior.

**Exit:** a one-store and multi-store owner can understand sales and freshness without surprise source polling.

### T10 — Implement text intake, candidate revisions, and review

**Dependencies:** T03, T05. **Difficulty:** medium.

**Create:** `services/product-intake/pyproject.toml`, `services/product-intake/src/wso_intake/text.py`, `validation.py`; `services/api/src/wso_api/imports/router.py`; `apps/web/src/features/imports/candidate-review.tsx`; `infra/migrations/versions/0005_imports.py`; `tests/unit/test_product_intake.py`.

**Interfaces:** `parse_text(text:str) -> list[ProductCandidate]` is executed with an authenticated import context for IDs/tenant; `validate_candidate(candidate) -> list[str]`; `PATCH /candidates/{id}` increments revision and invalidates stale registrations.

- [ ] Add parsing and validation fixtures for quoted commas, leading-zero UPC, KRW separators, box prices, missing barcode, duplicate line, ambiguous free-form text and more than 100 items.

```python
def test_purchase_price_is_not_implicitly_retail(intake):
    item = intake.from_fields(barcode="8801234567893", name="Sample",
                              purchase_price=900, sale_price=None)
    assert item.sale_price is None
    assert "SALE_PRICE_REQUIRED" in item.errors
```

- [ ] Run `uv run pytest tests/unit/test_product_intake.py -q`.
- [ ] Implement the complete candidate model in Section 6.2, explicit-column/labeled-line parsing, checksum/format validation, variant/unit/pack and price/tax-basis separation, provenance and versioned adapter-field validation. Keep unsupported barcodes as reviewable strings without generating replacement codes. Text `sale_price` is an explicitly supplied sale price, but missing required unit/tax/form choices remain reviewable rather than assumed.
- [ ] Build editable candidate rows with original values/source, validation reasons, proposed retail price, target store and selected items. Require revision matching on updates; do not infer registration permission from merely uploading an image/text.
- [ ] Add `test_variant_unit_tax_survive_candidate_round_trip`: collect a variant and pack, correct its unit/tax/form choice, serialize/deserialize the candidate and assert every value/schema ID survives. Changing any submitted field increments revision. Test unknown adapter keys, stale revisions, multi-product input with one invalid row and manager/staff restrictions. T11 owns the downstream registration snapshot test after the registration service exists; T10 does not depend on T11/T12. Run full verification.

**Exit:** text imports produce stable reviewed candidates usable by every later input adapter.

### T11 — Build registration orchestration with remote-state reconciliation

**Dependencies:** T05, T06, T10. **Difficulty:** high.

**Create:** `services/product-registration/pyproject.toml`, `services/product-registration/src/wso_registration/service.py`, `states.py`, `reconcile.py`, `write_holds.py`; `services/api/src/wso_api/registration/router.py`; `infra/migrations/versions/0006_registration.py` including durable `registration_write_holds`; `tests/integration/test_registration_recovery.py`.

**Interfaces:** `RegistrationService.request(scope, candidate_revisions, idempotency_key) -> RegistrationJob`; `run_item(item_id) -> RegistrationItem`; reader/writer are injected ports. Persist all states in Section 6.4.

- [ ] Build a fake writer that commits a source product and then raises a timeout; reader subsequently finds it.

```python
def test_lost_save_response_is_reconciled_without_resubmit(registration):
    registration.writer.commit_then_timeout = True
    item = registration.run_ready_item()
    registration.reconcile(item.id)
    assert registration.writer.submit_count == 1
    assert registration.get(item.id).state == "REGISTERED"
```

- [ ] Run `uv run pytest tests/integration/test_registration_recovery.py -q`.
- [ ] Implement request hash/revision freeze over the full typed candidate and adapter schema, target-store authorization, per-barcode transition lock and persistent write hold, preflight read, submit marker, verification and reconciliation. The hold is created atomically before the first possible remote write and survives worker lease expiry. Store only sanitized form values and response evidence necessary for the result.
- [ ] Handle existing exact product as `ALREADY_EXISTS`, conflicting values as `NEEDS_REVIEW`, unknown remote outcome as a visible unresolved item. A lost lock or changed permission before save must abort submission.
- [ ] Test two batches racing on one barcode, one success/one invalid row, changed candidate after enqueue and retry after worker crash; ensure no existing product is edited.
- [ ] Add `test_variant_unit_tax_survive_frozen_request`: take a reviewed T10 candidate, queue it through the real registration service and capture its injected writer-port input. Assert all variant/unit/pack/tax/price-basis/adapter values and schema ID survive; changing any field/revision after queueing rejects the stale snapshot. Same barcode/name/price but different variants cannot become ALREADY_EXISTS. T12 repeats the field-preservation assertion against its real browser adapter and local form fixture.
- [ ] Add `test_uncertain_save_blocks_a_new_batch`: the fake remote accepts a submit but delays both commit/readback; expire the worker lease and cancel the first job, then submit another batch/candidate/idempotency key for the same barcode. Assert the second item is `BLOCKED_BY_UNRESOLVED_ATTEMPT` and submit count remains one while reads return absent. Deliver the late remote commit and reconcile the original attempt; only its definitive result releases the hold, and the next request becomes ALREADY_EXISTS. Add a pre-submit failure case that safely releases the hold and a source-without-consistency-proof case that keeps it indefinitely.

**Exit:** orchestration is safe against duplicate delivery before connecting a live browser writer.

### T12 — Implement the isolated OrderQueen site writer

**Dependencies:** T11, G02. **Difficulty:** high, external mutation.

**Create:** `services/product-registration/src/wso_registration/orderqueen_browser.py`, `request_guard.py`; `apps/web/src/features/imports/registration-results.tsx`; `tests/contract/test_orderqueen_writer.py`, `tests/e2e/registration.spec.ts`; sanitized registration-form fixtures.

**Interfaces:** implement `RegistrationWriter.register_new`; return `RegistrationReceipt(attempt_id,submitted_at,acknowledged,external_id,readback_state)`. Exact form locators/request path/required fields are adapter config backed by G02 evidence, not arbitrary user input.

- [ ] Build a local mock form that requires a CSRF token and distinguishes store/variant/unit; add save timeout, duplicate validation and unexpected form-field cases.

```python
async def test_writer_never_edits_existing_product(writer, reader, ready_candidate):
    reader.existing = {"barcode": ready_candidate.barcode, "name": "Different"}
    result = await writer.preflight_and_register(ready_candidate)
    assert result.state == "NEEDS_REVIEW"
    assert writer.captured_mutation_requests == []
```

`preflight_and_register` is a test adapter wrapper around T11's preflight plus the T12 writer, not a second production registration path.

- [ ] Run `uv run pytest tests/contract/test_orderqueen_writer.py -q` against the local mock website.
- [ ] Use a Playwright context scoped to the connection; revalidate target store, active attempt hold and full frozen candidate/schema before clicking save. Fill only the frozen, schema-validated variant/unit/tax/form choices, never fresh source-page guesses. Permit only the verified new-product submit operation for that attempt; block unrelated writes, uploads, cancellation and POS dispatch.
- [ ] Extend T11's snapshot test through the local mock registration form: inspect the actual submitted values and readback for variant/unit/tax/schema fields, not only the injected port payload. An unsupported or changed form schema must stop the attempt before submission.
- [ ] Re-read through the reader port and compare required fields. UI displays success, existing, failed and uncertain separately, with retry only for the safe subset. A selector/form drift fails closed as `SITE_CONTRACT_CHANGED`.
- [ ] Run browser/contract tests, then one explicitly requested live registration when available. A mock success alone leaves G02 unverified.

**Exit:** R3 works end to end with text input and exactly-once business intent, without claiming distributed exactly-once transport.

### T13 — Implement saved wholesale logins and extra-auth continuation

**Dependencies:** T04, T05, G03 for each live site. **Difficulty:** high.

**Create:** `services/product-intake/src/wso_intake/browser_pool.py`, `wholesale/auth.py`, `wholesale/registry.py`; `packages/contracts/src/wso_contracts/wholesale.py`; `apps/web/src/features/connections/auth-continuation.tsx`; `tests/integration/test_wholesale_sessions.py`.

**Interfaces:** `SessionHandle(connection_id,generation,context_ref,state,expires_at)`; `WholesaleAdapter.ensure_session` returns this model. `AuthContinuation(id,connection_id,owner_user_id,expires_at)` is a single-use continuation, not a URL containing credentials.

- [ ] Add tests for valid-state reuse, expiry/relogin, incorrect password, CAPTCHA/OTP, generation revocation and two owners on the same hostname.

```python
async def test_expired_session_uses_saved_credentials_once(wholesale):
    wholesale.site.expire_session()
    session = await wholesale.ensure_session()
    assert session.state == "CONNECTED"
    assert wholesale.site.login_attempts == 1
    await wholesale.ensure_session()
    assert wholesale.site.login_attempts == 1
```

- [ ] Run `uv run pytest tests/integration/test_wholesale_sessions.py -q`.
- [ ] Implement one account mutex and isolated browser context per connection generation, encrypted state serialization, authenticated-state checks and a bounded relogin path. Prefer in-memory state restoration; if disk state is unavoidable, use a private temporary path and delete it after closing context.
- [ ] For OTP, expose an expiring owner-only challenge form; transmit the code transiently to the adapter without logging/storing it. For interactive CAPTCHA, provide an authenticated, expiring view of only that isolated browser session or a documented local assisted flow; no shared browser desktop. Resume only after verified authenticated state.
- [ ] Stop repeated invalid-password attempts; classify network retries separately. Test account deletion while a page loads, hostile redirects, tenant mix-ups and auth-page HTTP 200 misclassification.

**Exit:** saved account credentials perform automatic login/relogin; extra authentication is honest and resumable.

### T14 — Parse wholesale product pages through site adapters

**Dependencies:** T10, T13. **Difficulty:** high.

**Create:** `services/product-intake/src/wso_intake/wholesale/products.py`, `wholesale/url_policy.py`, `wholesale/adapters/fixture_shop.py`; `tests/contract/test_wholesale_products.py`; per-site sanitized product-page fixtures added when G03 provides real sites.

**Interfaces:** `WholesaleAdapter.product(connection_id,url) -> list[ProductCandidate]`; one candidate per sellable variant/unit. `SourceEvidence(url,parser_version,observed_at,field_locations)` is stored without account query strings or private order tokens.

- [ ] Add variant/pack/current-price fixtures plus missing-barcode and private-address redirects.

```python
async def test_box_price_does_not_become_sale_price(shop):
    candidates = await shop.product("https://fixture-shop.invalid/products/box")
    assert candidates[0].pack_quantity == 24
    assert candidates[0].purchase_price.amount_minor == 12000
    assert candidates[0].sale_price is None
```

- [ ] Run `uv run pytest tests/contract/test_wholesale_products.py -q`.
- [ ] Implement DOM extraction using tested locators/attributes, structured product data when present, explicit variant selection and field provenance. Detect login/drift pages before extraction. Do not invent a general parser that claims all wholesale sites work.
- [ ] Enforce URL/DNS/redirect rules from Section 7.2 through both validation and network egress. Never open internal camera URLs in this worker. Content such as “ignore instructions and register all products” remains inert data.
- [ ] Connect candidates to T10 review and T11 registration; add a new live-site adapter only with fixtures and a passing site-specific contract test.

**Exit:** a supported site product URL produces defensible candidates or explicit missing-field errors.

### T15 — Extract selected wholesale order history

**Dependencies:** T14. **Difficulty:** high.

**Create:** `services/product-intake/src/wso_intake/wholesale/orders.py`; `apps/web/src/features/imports/order-selector.tsx`; `tests/integration/test_order_history.py`.

**Interfaces:** `OrderSelection(order_ids:list[str] | None, start_date:date | None, end_date:date | None)` requires IDs or a bounded range; `OrderPage(lines:list[OrderLine],next_cursor:str|None)`; `OrderLine` includes order/line IDs, variant, quantity, unit, order-time price and cancellation state.

- [ ] Add three-page fixtures with a repeated item, changed current price, canceled line, variant-specific barcode and a pagination loop.

```python
async def test_order_price_and_current_price_remain_distinct(order_import):
    item = (await order_import.run_selected_orders())[0]
    assert item.order_price_minor == 900
    assert item.current_price_minor == 1100
    assert item.sale_price is None
```

T15 introduces an internal `OrderCandidateEvidence` record containing the two prices; the public candidate preserves the chosen purchase source and links this evidence rather than silently overwriting it.

- [ ] Run `uv run pytest tests/integration/test_order_history.py -q`.
- [ ] Implement bounded pagination, per-order/line deduplication, order-detail extraction and optional product-detail enrichment. Stop at user scope/page limit; checkpoint completed orders and mark incomplete coverage.
- [ ] Show order selection and inclusion/exclusion for canceled/returned items. Omit addresses/phone/payment account details during parsing, before persistence.
- [ ] Test resume after expiry, two order lines with same barcode but different pack units, absent barcode on both pages, duplicate pages and order history changes during collection.

**Exit:** selected order history yields reviewable ordered products with source-time price context.

### T16 — Add barcode and OCR photo intake

**Dependencies:** T10, T05A; OCR/model packaging gate G11. **Difficulty:** high.

**Create:** `services/product-intake/src/wso_intake/images.py`, `barcode.py`, `ocr.py`, `association.py`; `infra/ocr.Dockerfile`; `tests/unit/test_image_intake.py`, `tests/fixtures/images/manifest.json` and synthetic images.

**Interfaces:** photo import requests carry owned READY `asset_ids` from T05A; `decode_barcodes(image) -> list[BarcodeRegion]`, `extract_text(image) -> list[TextRegion]`, `associate(regions,text) -> list[ProductCandidate]`. Region models contain bounds/value/confidence and algorithm version. Persist crops through T05A's AssetStore with `parent_asset_id`; source references point to assets rather than process-local files.

- [ ] Create synthetic fixtures for a rotated valid barcode, blurred barcode, two products/two prices, leading-zero UPC, Korean label, EXIF rotation and oversized decoded dimensions.

```python
def test_multiple_price_candidates_require_review(photo_intake):
    result = photo_intake.run_fixture("two_prices_one_barcode")
    assert result[0].sale_price is None
    assert "AMBIGUOUS_PRICE" in result[0].errors
```

- [ ] Run `uv run pytest tests/unit/test_image_intake.py -q`.
- [ ] Implement content sniffing, byte/pixel limits, EXIF stripping, decoding, OCR and spatial association with confidence thresholds. Keep crop/source references and editable proposed fields. Barcode mismatch across decoder/OCR becomes review, not arbitrary preference.
- [ ] Package PaddleOCR separately, pin downloaded weights/hash/license, and test Korean labels. Never fetch mutable model weights at first production request.
- [ ] Test malformed image/decompression bomb, no barcode, OCR substitutions, parent/crop retention cleanup and a worker restart between upload and OCR. Run the upload → asynchronous OCR → candidate review acceptance with no stores or camera services configured; T17/T18 must not be required. Record measured latency on CPU and optional GPU.

**Exit:** photos feed the same candidate/revision/registration pipeline without automatic low-confidence writes.

### T17 — Connect a standard camera through a scoped edge gateway

**Dependencies:** T03–T05; G05 for real devices. **Difficulty:** high.

**Create:** `services/edge/pyproject.toml`, `services/edge/src/wso_edge/identity.py`, `camera.py`, `router.py`, `health.py`, `control.py`, `hls.py`; `services/edge-relay/pyproject.toml`, `services/edge-relay/src/wso_relay/control.py`, `media.py`, `sessions.py`; `packages/contracts/src/wso_contracts/cameras.py`; `infra/edge.compose.yaml`, `infra/relay.compose.yaml`, `infra/relay/frps.toml`, `infra/relay/coturn.conf`; `infra/migrations/versions/0007_cameras.py`; `tests/integration/test_edge_camera.py`, `tests/integration/test_remote_media.py`.

**Interfaces:** implement `CameraAdapter` read operations. Define `CameraInfo(id,store_id,capabilities)`, `StreamHandle(internal_ref,codec,width,height,fps,epoch)`, `Snapshot(asset_ref,captured_at)`, `CameraHealth(state,last_frame_at,reconnects,clock_offset_ms)` and `CameraEvent(camera_id,kind,occurred_at,source_id)`. Unsupported talk methods return a typed capability error until T25.

- [ ] Build a synthetic FFmpeg RTSP source and an adapter fake for ONVIF events, then test stream loss/reconnect and device scoping.

```python
async def test_reconnect_changes_track_epoch(edge_camera):
    first = await edge_camera.stream()
    await edge_camera.source.disconnect_and_reconnect()
    second = await edge_camera.stream()
    assert second.epoch != first.epoch
    assert second.internal_ref not in edge_camera.public_api_response()
```

- [ ] Run `uv run pytest tests/integration/test_edge_camera.py -q` against test media services.
- [ ] Implement outbound edge enrollment with one-use scoped token, per-device credential/certificate rotation, allowlisted cameras and heartbeat. API binds an edge identity to its tenant/store; arbitrary edge claims cannot choose another tenant.
- [ ] Implement the Section 4 transport: outbound mTLS WSS command channel; frp reverse tunnel exporting only the private scoped edge gateway to private central bindings; authenticated HTTPS/WSS signaling/HLS relay; coturn ICE relay with short-lived credentials; FFmpeg HLS fallback. Pin versions/configs and test device binding/destination allowlists so a compromised or misconfigured edge cannot register another device's proxy or export arbitrary internal services. Keep go2rtc private. Implement standard media/events/snapshot health and bounded reconnect for the verified hardware model.
- [ ] Test two consumers, codec compatibility, expired tickets, revoked edge identity, 30-second disconnect and bounded stale-frame discard. Document live H.265/browser fallback and optional H.264 transcoding cost.
- [ ] Add `test_off_lan_media_with_inbound_blocked` using separate network namespaces/containers for edge, central relay and client. Deny edge ingress and direct client-to-edge routing; force TURN relay and verify decoded video, not just successful signaling. Then block UDP/ICE and verify HLS playback through HTTPS/WSS. Revoke the device/session during playback and assert signaling/media consumers and segment access stop; test reconnection cannot replay expired commands. Record an off-site mobile smoke before release.

**Exit:** a selected standard camera supplies frames and health without exposing credentials or device ports.

### T18 — Store evidence with retention and scoped access

**Dependencies:** T05A, T17. **Difficulty:** high.

**Create:** `services/edge/src/wso_edge/evidence.py`, `spool.py`; `services/api/src/wso_api/evidence/router.py`; `infra/migrations/versions/0008_evidence.py`; `tests/integration/test_evidence_access.py`. **Reuse:** T05A's `storage.py`, `assets.py`, `retention.py` and private object lifecycle.

**Interfaces:** `EvidenceStore.put(scope: StoreScope,manifest,stream) -> EvidenceAsset` wraps T05A's AssetStore; `EvidenceAsset` references its generic asset ID plus capture window/masking metadata. `authorize_download(actor,asset_id) -> DownloadTicket` reuses T05A's authorization and expires after a proposed 60 seconds. Live media sessions/tickets from T17 are a different type and lifecycle from static asset downloads.

- [ ] Test object-key/tenant isolation, checksum mismatch, partial clips, expired evidence and interruption during upload.

```python
def test_other_tenant_cannot_mint_evidence_url(api_client, users, evidence):
    response = api_client.as_user(users.owner_b).get(
        f"/api/v1/evidence/{evidence.tenant_a.id}/download")
    assert response.status_code == 404
    assert "url" not in response.json()
```

T18 adds `GET /evidence/{id}/download` to the API contract; the response is a short-lived ticket or authorized proxy stream, never a permanent public object URL.

- [ ] Run `uv run pytest tests/integration/test_evidence_access.py -q`.
- [ ] Implement bounded pre/post-event buffer and actual clip-window metadata; delegate hashed private uploads and `PENDING/READY/DELETING/DELETED` transitions to T05A. Resume upload safely; only READY assets can be shared. Evidence-specific expiry/masking rules extend, rather than duplicate, generic asset rules.
- [ ] Edge spool is encrypted/permission-restricted, capped by disk quota and TTL, and keyed to event ID. Overflow emits an explicit evidence-loss health event; never silently grows without limit.
- [ ] Extend T05A's retention/audit service with camera evidence limits and configured privacy masks. Test evidence deletion after signed-ticket mint and document its maximum remaining lifetime; verify generic import-photo cleanup still works without an edge.

**Exit:** evidence is accessible only to authorized users, expires predictably, and survives bounded connectivity loss.

### T19 — Implement detector, tracking, and temporal zone rules

**Dependencies:** T17, T18, G11. **Difficulty:** high.

**Create:** `services/video-worker/pyproject.toml`, `services/video-worker/src/wso_video/detector.py`, `tracker.py`, `pipeline.py`; `packages/rules/pyproject.toml`, `packages/rules/src/wso_rules/zones.py`, `temporal.py`; `tests/vision/test_zone_pipeline.py`, `tests/fixtures/video/manifest.json`.

**Interfaces:** `Detector.infer(frame) -> list[Detection]`; `Tracker.update(epoch,timestamp,detections) -> list[TrackObservation]`; `evaluate_rule(rule,observations) -> list[RuleCandidate]`. A detection contains class/box/confidence; observations include track ID+epoch, timestamp, footpoint and optional pose; candidates include rule/version/measurements and evidence window.

- [ ] Add deterministic track fixtures for entry/exit, occlusion, two people crossing, exact duration boundary, reconnect and out-of-order frames.

```python
def test_dwell_requires_continuous_observed_duration(rule_engine):
    rule_engine.observe(track="a", at=0.0, inside=True)
    rule_engine.observe(track="a", at=1.0, inside=False)
    result = rule_engine.observe(track="a", at=2.1, inside=True)
    assert result == []  # A two-second rule does not accumulate separate visits.
```

- [ ] Run `uv run pytest tests/vision/test_zone_pipeline.py -q`; pure rules use deterministic observations, not a stochastic GPU model.
- [ ] Implement YOLOX adapter as first approved artifact, isolated ByteTrack wrapper, normalized polygon validation and duration/cooldown state machine. Reject self-intersecting/empty zones and negative durations. The last-known detection cannot continue a dwell indefinitely through missing frames.
- [ ] Benchmark actual decoded frames and inference; configure backpressure, sampling and stale frame budget. Record FPS/latency/hardware/model hash; enable an alternative detector only after its license and fixture gates pass.
- [ ] Separate model-quality tests from deterministic rule correctness. Run held-out synthetic/authorized clips and full repository verification.

**Exit:** person/zone events are explainable and temporally stable without pretending to solve every behavior yet.

### T20 — Build incident review, visual rules, and staff mode

**Dependencies:** T03, T18, T19. **Difficulty:** medium–high.

**Create:** `services/api/src/wso_api/incidents/router.py`, `rules/router.py`, `staff_modes/router.py`; `apps/web/src/features/incidents/incident-list.tsx`, `incident-detail.tsx`, `zone-editor.tsx`, `rule-editor.tsx`, `staff-mode.tsx`; `infra/migrations/versions/0009_incidents.py`; `tests/integration/test_incident_workflow.py`, `tests/e2e/incident-review.spec.ts`.

**Interfaces:** incident statuses `NEW/ACKNOWLEDGED/FALSE_POSITIVE/RESOLVED`; `review_incident(id,expected_revision,decision) -> Incident`; `StaffMode(scope,rule_ids,expires_at,actor_id)` suppresses selected deliveries only. Rules include behavior, normalized zone, duration, confidence threshold and notification level.

- [ ] Add merge-window, state-transition, concurrent review and staff-expiry tests.

```python
def test_staff_mode_expires_without_discarding_evidence(incidents, clock):
    incidents.enable_staff_mode(rule="running", duration_seconds=60)
    first = incidents.emit(rule="running")
    assert first.evidence_saved and first.notification_suppressed
    clock.advance(seconds=61)
    second = incidents.emit(rule="running")
    assert second.evidence_saved and not second.notification_suppressed
```

- [ ] Run `uv run pytest tests/integration/test_incident_workflow.py -q`.
- [ ] Implement incident candidate grouping, versioned review/feedback, evidence retrieval, zone drawing/editing, rule preview on a snapshot and staff mode TTL. Enforce owner/manager/staff permissions separately.
- [ ] Show measurements and model/rule version alongside confidence; include camera/time/store, representative image, clip coverage and summary state. Avoid crime/identity assertions in UI labels.
- [ ] Test stale rule edits, camera resize/rotation, mobile viewport, keyboard controls and another store's incident URL; run E2E and backend suites.

**Exit:** administrators can understand and correct incidents; feedback is recorded for later training.

### T21 — Build the isolated CLI process runner

**Dependencies:** T04, T05, G06. **Difficulty:** high.

**Create:** `services/llm-worker/pyproject.toml`, `services/llm-worker/src/wso_llm/process.py`, `codex_cli.py`, `claude_cli.py`, `health.py`; `packages/contracts/src/wso_contracts/cli.py`; `infra/cli-runner.Dockerfile`; `tests/integration/test_cli_process.py`; fake executables under `tests/fixtures/cli/`.

**Interfaces:** `CliHealth(provider,version,auth_state,image_supported)`; `RunManifest(job_id,tenant_id,incident_id,image_paths,evidence_ids,schema_path,prompt_version)`; `CliRunner.summarize` returns validated `IncidentSummary`; failures use Section 7.4 categories, not raw stdout.

- [ ] Fake CLI programs cover valid JSONL, final structured JSON, log noise, nonzero exit, missing auth, malformed JSON, oversized output and a spawned child that hangs.

```python
async def test_timeout_kills_descendants_without_shell_execution(cli_harness):
    result = await cli_harness.run_fake("spawn_child_then_hang", timeout=0.2)
    assert result.error_code == "TIMEOUT"
    assert cli_harness.live_descendants() == []
    assert cli_harness.shell_was_used is False
```

- [ ] Run `uv run pytest tests/integration/test_cli_process.py -q`; OS-specific process-tree tests run on both Linux and Windows runners where supported.
- [ ] Implement argument-array launch, stdin prompt, bounded stdout/stderr capture, deadline/cancel, process-tree cleanup, isolated job directory and auth preflight. Strip direct-API credential variables; no app/browser secrets in the child environment. Enforce per-account concurrency.
- [ ] Implement Codex image/schema path from Section 7.4. Implement Claude structured output and only the G06-verified image mode. Separate transport events from final model output; nonzero exit is not overridden by a plausible partial JSON fragment.
- [ ] Test hostile filenames/prompt text as data, inherited hooks/MCP absence, cross-tenant paths, quota backoff and auth-required recovery. Record real CLI smoke separately; do not run provider inference in default CI.

**Exit:** either selected CLI can be invoked through one controlled port without API-key integration or hidden tool access.

### T22 — Generate incident summaries with CLI-only inference

**Dependencies:** T18, T20, T21. **Difficulty:** medium–high.

**Create:** `services/llm-worker/src/wso_llm/summary.py`, `frame_selection.py`, `prompts/incident-v1.txt`; `packages/contracts/schemas/incident-summary.json`; `tests/unit/test_incident_summary.py`.

**Interfaces:** `prepare_manifest(incident_id) -> RunManifest`; `summarize_incident(incident_id) -> SummaryResult(status,summary,error_code)`; cache key includes tenant/incident/evidence hashes/prompt version/model and provider, not just image bytes.

- [ ] Add duplicate-frame, obscured-scene, invented-evidence-ID and unavailable-CLI cases.

```python
async def test_unknown_evidence_id_invalidates_summary(summary_worker):
    summary_worker.cli.result.evidence_ids = [summary_worker.foreign_evidence_id]
    result = await summary_worker.run()
    assert result.status == "FAILED"
    assert result.error_code == "INVALID_OUTPUT"
    assert summary_worker.incident_exists is True
```

- [ ] Run `uv run pytest tests/unit/test_incident_summary.py -q`.
- [ ] Select up to three nonduplicate frames spanning the incident, apply configured masking/crops, and pass a fact manifest to the selected CLI. Validate schema, allowed evidence IDs, text length and unsupported identity/crime assertions; uncertain output is reviewable, never an operational command.
- [ ] Store Korean summary, optional warning draft, provider/CLI/model/prompt versions, latency and available usage counters. Warning text is editable and enters T25's audio preview/approval flow only through an explicit human action. Rate-limit repeated summaries; auth/quota failure leaves the incident reviewable with a clear summary status.
- [ ] Verify initial incident notification does not await the CLI. Test retry deduplication and no automatic provider switch.

**Exit:** useful summaries augment evidence while rules and alerts remain functional without the CLI.

### T23 — Implement durable web and mobile notification delivery

**Dependencies:** T05, T20; T22 for later summary updates. **Difficulty:** medium–high.

**Create:** `services/notification-worker/pyproject.toml`, `services/notification-worker/src/wso_notifications/service.py`, `webpush.py`, `mobile_push.py`; `services/api/src/wso_api/events/router.py`, `push/router.py`; `apps/web/src/features/notifications/stream.ts`; `tests/integration/test_notifications.py`.

**Interfaces:** `notify_incident(event:EventEnvelope) -> list[Delivery]`; `Delivery` key `(event_id,recipient_id,channel)`; SSE replay uses stored event IDs, with current membership filtering on reconnect.

- [ ] Test broker duplicate, transient provider failure, revoked push token, recipient removed from a store and SSE reconnection.

```python
def test_duplicate_event_creates_one_delivery(notifications):
    event = notifications.fixture_event()
    notifications.consume(event)
    notifications.consume(event)
    assert notifications.delivery_count(event.event_id) == 1
```

- [ ] Run `uv run pytest tests/integration/test_notifications.py -q`.
- [ ] Implement outbox-driven fanout, user/store permission checks, idempotent delivery and bounded exponential retry with a dead-letter state. Provider acceptance is `ACCEPTED`, not proof a person saw the alert.
- [ ] Web uses authorized SSE for in-app realtime plus Web Push when opted in. Mobile uses FCM/APNs directly or Expo's chosen transport with documented credentials; keep provider behind a delivery port. Push payload contains incident/store IDs and generic text, not permanent evidence URLs or sensitive imagery.
- [ ] Test expired tokens, logout/reassignment and reconnect cursor gaps. Show unread/acknowledged status based on application actions, not inferred notification delivery.

**Exit:** alerts are scoped, retriable, and observable across web and mobile channels.

### T24 — Deliver the mobile client with shared data contracts

**Dependencies:** T03, T09, T17's remote-media contract, T20, T23. **Difficulty:** medium–high.

**Create:** `apps/mobile/package.json`, `app.config.ts`, `app/(auth)/login.tsx`, `app/(main)/stores.tsx`, `app/(main)/incidents/[id].tsx`, `app/(main)/sales.tsx`, `src/auth.ts`, `src/api.ts`, `src/notifications.ts`, `src/media.ts`; `apps/mobile/tests/deep-links.test.ts`.

**Interfaces:** generated API types from T01; registered OIDC redirect; `resolveIncidentLink(url) -> {incidentId}|null`; authorization is always rechecked by the API after a push tap.

- [ ] Add unit tests for malformed/deep foreign links, logout token cleanup and stored tenant changes.

```typescript
import { expect, test } from 'vitest';
import { resolveIncidentLink } from '../src/notifications';

test('rejects a foreign deep-link host', () => {
  expect(resolveIncidentLink('https://untrusted.invalid/incidents/123')).toBeNull();
});
```

- [ ] Run `pnpm --filter @wso/mobile test` after configuring the task's test harness.
- [ ] Implement PKCE login via system browser, secure refresh-token storage, store picker, incidents/evidence/summary, sales filters/refresh and staff mode. Share contracts, not platform-incompatible UI components. Offline content shows its timestamp; writes are not silently queued offline.
- [ ] Implement evidence playback and a camera-live player adapter consuming T17's central signaling URL, media session and short-lived ICE credentials; renew sessions only through authorized API calls. Test actual codec/WebRTC support in a native development build. Use T17's HTTPS HLS fallback when ICE/native WebRTC is unavailable; do not promise live playback from Expo Go alone or substitute a clip while labeling it live.
- [ ] Run Android and iOS device smoke: login, push receipt, background push tap, revoked incident access, expired media ticket and sales entry/manual refresh. Record missing APNs/FCM signing credentials as a mobile-release gate.

**Exit:** web and mobile show the same authorized store, incident and sales records.

### T25 — Add approved TTS and camera broadcast

**Dependencies:** T17, T20, G07. **Difficulty:** very high device integration.

**Create:** `services/broadcast-gateway/pyproject.toml`, `services/broadcast-gateway/src/wso_broadcast/service.py`, `tts.py`, `tapo.py`; `services/api/src/wso_api/broadcast/router.py`; `apps/web/src/features/incidents/broadcast-confirmation.tsx`; `tests/integration/test_broadcast.py`.

**Interfaces:** `prepare_audio(text,voice) -> AudioAsset(hash,duration,codec)`; `approve_broadcast(actor,incident,camera,audio_hash) -> BroadcastCommand`; state `APPROVED/SENDING/SENT/FAILED/UNKNOWN/EXPIRED`. Talk uses CameraAdapter methods, implemented only for validated hardware.

- [ ] Test no approval, changed audio after approval, wrong camera/store, expired approval, busy backchannel and timeout.

```python
async def test_talk_session_closes_on_send_failure(broadcast):
    broadcast.camera.fail_send_before_write = True
    await broadcast.execute_approved()
    assert broadcast.camera.stop_talk_calls == 1
    assert broadcast.command.state == "FAILED"
```

- [ ] Run `uv run pytest tests/integration/test_broadcast.py -q` with fake audio/camera ports.
- [ ] Start with prerecorded owner-approved phrases and a `TtsEngine` port. Evaluate sherpa-onnx using its [offline TTS example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-tts.py) and a Korean voice from its [voice catalog](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html); pin the selected voice hash and inspect that voice's terms and Korean pronunciation. Implement the local engine after that gate, retaining prerecorded phrases if no voice passes. Codex/Claude text inference is not an audio synthesizer. Preview the exact rendered audio before approval.
- [ ] Convert to the verified device format through FFmpeg; acquire one talk session per camera and call `stop_talk` in `finally`. Approval expires after a proposed 60 seconds and binds actor/store/incident/audio hash. Failure before sending is `FAILED`; a disconnect after any audio may have been sent is `UNKNOWN`. Do not replay an uncertain audible send automatically.
- [ ] Add equivalent mobile confirmation UI once T24 is ready. Run one scoped audible device test; verify another app can use the audio channel afterward.

**Exit:** only an authorized, reviewed payload is broadcast, and the channel is released even after failure.

### T26 — Add calibrated behavior and help-request rules

**Dependencies:** T19, T20; pose capability/weights under G11. **Difficulty:** very high.

**Create:** `packages/rules/src/wso_rules/freezer.py`, `running.py`, `waving.py`, `kiosk.py`; `services/video-worker/src/wso_video/pose.py`; `tests/vision/test_behavior_rules.py`, `docs/engineering/behavior-calibration.md`.

**Interfaces:** each evaluator consumes `TrackObservation` and a versioned `BehaviorConfig`; produces `RuleCandidate(kind,confidence,measurements,evidence_window)`. Pose adapter returns named keypoints and visibility, never an inferred identity.

- [ ] Add labeled observation fixtures for standing beside freezer, actual top contact, sitting/standing occlusion, walking across perspective, running, shelf-reaching versus waving, and repeated kiosk approaches.

```python
def test_box_overlap_alone_is_not_freezer_climbing(behavior_engine):
    candidate = behavior_engine.freezer(box_overlap=0.8, top_contact=False,
                                         pose_visible=True, duration=4.0)
    assert candidate is None
```

- [ ] Run `uv run pytest tests/vision/test_behavior_rules.py -q`.
- [ ] Implement rule inputs from Section 7.3 and camera-specific calibration. Store actual threshold/rule version and reason. Add confidence reduction for low visibility, perspective uncertainty and frame drops.
- [ ] Kiosk rules emit difficulty candidates using dwell/reapproach evidence. True payment-error labels require G08; when absent, neither missing transactions nor a raised hand establishes a payment failure.
- [ ] Evaluate held-out per-camera clips, report precision/recall and false alerts per camera-hour for each behavior. Human review remains required; do not claim validated accuracy from synthetic fixtures alone.

**Exit:** freezer, running, waving and kiosk difficulty have measured, tunable behavior rather than untested heuristics hidden behind an AI label.

### T27 — Build visit sessions and cautious payment matching

**Dependencies:** T07, T19, T26. **Difficulty:** very high.

**Create:** `packages/analytics/src/wso_analytics/visits.py`, `payments.py`; `services/api/src/wso_api/visits/router.py`; `apps/web/src/features/incidents/payment-review.tsx`; `infra/migrations/versions/0010_matching.py`; `tests/unit/test_payment_matching.py`.

**Interfaces:** `build_visits(observations,topology) -> list[VisitSession]`; `match_visit(visit,transactions,coverage,clock_quality) -> PaymentMatch`; results include Section 7.5 statuses, candidate IDs, reasons and data freshness.

- [ ] Test one visitor/one transaction, two visitors/one transaction, cancellation, POS mismatch, clock drift, unsynchronized window and multi-camera ambiguity.

```python
def test_stale_source_cannot_establish_no_payment(payment_fixture):
    result = payment_fixture.match(transactions=[], coverage_complete=False)
    assert result.status == "REVIEW_REQUIRED"
    assert "SOURCE_NOT_FRESH" in result.reasons
```

- [ ] Run `uv run pytest tests/unit/test_payment_matching.py -q`.
- [ ] Implement bounded visit lifecycle, track-epoch separation, optional topology-based cross-camera hypotheses and store/POS/time matching. Constrain transaction assignment, preserve uncertainty, and record algorithm version.
- [ ] Trigger recalculation from local visit-close and completed explicit-sync events. Do not add sales polling. Only authoritative error events produce `PAYMENT_ERROR`; only reliable links/human review produce `PAID_CONFIRMED`.
- [ ] Build evidence/transaction timeline and review actions, including source freshness and cancellation details. Test no criminal labels and no automatic enforcement/broadcast from a match result.

**Exit:** matching assists a manager with evidence and explicitly unresolved cases.

### T28 — Analyze recurring incident patterns

**Dependencies:** T20; T27 is optional enrichment. **Difficulty:** medium–high.

**Create:** `packages/analytics/src/wso_analytics/patterns.py`; `services/api/src/wso_api/patterns/router.py`; `apps/web/src/features/incidents/patterns.tsx`; `tests/unit/test_repeat_patterns.py`.

**Interfaces:** `incident_patterns(incidents,store_timezone,window) -> list[RepeatPattern]`; group by store/zone/behavior/local weekday/time bucket, not person identity. Pattern output includes count, reviewed-positive count, exposure/coverage and rule versions.

- [ ] Add timezone-boundary, duplicate-event and false-positive fixtures.

```python
def test_repetition_excludes_confirmed_false_positives(patterns):
    result = patterns.compute(confirmed=3, false_positives=9)
    assert result[0].reviewed_positive_count == 3
    assert result[0].person_identity is None
```

- [ ] Run `uv run pytest tests/unit/test_repeat_patterns.py -q`.
- [ ] Implement rolling 28-day initial aggregation, minimum count 3, reviewed/unreviewed separation and coverage normalization. Annotate model/rule changes that make before/after counts incomparable.
- [ ] Display time/zone patterns with source incidents and confidence reasons. Do not link people across days; tracking IDs are ephemeral.
- [ ] Test sparse windows, store timezone change and duplicate incident merging; run repository verification.

**Exit:** repeated store behavior is visible without covert identity tracking.

### T29 — Build feedback datasets and controlled model releases

**Dependencies:** T20, T26, enough authorized labeled data. **Difficulty:** very high.

**Create:** `services/video-worker/src/wso_video/model_registry.py`, `rollout.py`; `scripts/export_annotation_dataset.py`, `scripts/evaluate_model.py`; `docs/engineering/model-lifecycle.md`; `tests/integration/test_model_rollout.py`.

**Interfaces:** `DatasetManifest(version,asset_hashes,labels,consent_scope,split)`; `ModelVersion(id,artifact_hash,dataset_version,metrics,license_ref)`; `activate_model(store_ids,model_id,expected_previous_id)`; deployment tracks previous version for rollback.

- [ ] Add dataset leakage and failed-canary tests.

```python
def test_failed_canary_keeps_previous_model(model_rollout):
    model_rollout.candidate.false_alert_rate = 2.0
    model_rollout.baseline.false_alert_rate = 0.2
    result = model_rollout.evaluate_and_promote()
    assert result.promoted is False
    assert model_rollout.active_id == model_rollout.previous_id
```

- [ ] Run `uv run pytest tests/integration/test_model_rollout.py -q`.
- [ ] Export only eligible masked/cropped evidence to CVAT, track labeler/review state, and split by store/day/incident before frame extraction to avoid train/test leakage. Respect evidence deletion/consent and prevent orphan dataset copies.
- [ ] Track experiments/artifacts in MLflow behind internal authentication. Pin model/weight/dataset hashes and compare per-behavior precision/recall, latency and false alerts/hour on a fixed held-out set.
- [ ] Deploy to a limited opt-in store set, evaluate measured gates, then promote. Canary failure/latency regression restores the prior artifact/config atomically. A high aggregate score cannot hide a severe store-specific regression.

**Exit:** a new model can be audited, rejected or rolled back; training is not a substitute for fixing bad zones/thresholds first.

### T30 — Complete observability, recovery, and pilot acceptance

**Dependencies:** the release slices being piloted; start instrumentation in T01/T05, do not defer it here. **Difficulty:** high.

**Create:** `infra/observability/prometheus.yml`, `alerts.yml`; `scripts/restore_drill.ps1`, `scripts/pilot_report.py`; `docs/operations/runbook.md`, `backup-restore.md`, `incident-response.md`; `tests/acceptance/test_pilot_contract.py`.

**Interfaces:** sanitized metrics include job queue age, source failures, registration uncertainty, login state, camera freshness, evidence loss, detection latency, CLI queue/auth/quota state, notification delivery and deletion backlog. Avoid tenant names, device serials and unbounded IDs in metric labels.

- [ ] Add acceptance tests for every invariant in Section 10 and a restore exercise with two synthetic tenants.

```python
def test_restored_tenants_are_still_isolated(restore_harness):
    restore_harness.backup_and_restore_to_clean_stack()
    assert restore_harness.foreign_store_request().status_code == 404
    assert restore_harness.pending_registration().requires_reconciliation is True
```

- [ ] Run `uv run pytest tests/acceptance/test_pilot_contract.py -q`.
- [ ] Configure alerts for camera stale >60 seconds, queue age above budget, repeated auth failures, registration unknown state, failed object deletion and unavailable CLI. Set measured thresholds after pilot; separate health notification from duplicate incident notification.
- [ ] Implement DB backups, object inventory/backups, secret/key recovery references and restoration to an isolated environment. Restore does not replay broadcasts or unverified registrations. Document backup retention and key revocation consequences.
- [ ] Run a 72-hour proposed pilot on authorized stores with disconnect/restart/auth-expiry drills. Publish measured results, unsupported capabilities, known issues and rollback commands. Use canary application deployment and expand only after acceptance.

**Exit:** the chosen release scope meets Section 10 with evidence; features whose capability gates remain blocked are visibly disabled and not called complete.

### T31 — Required APK-informed TVT P2P implementation and runtime validation

**Dependencies:** completed T00A static report, T17 adapter contract, G10 runtime inputs and explicit device/SDK/tracing scope. G10 runtime support is this task's output, not a prerequisite assumed already proven. **Difficulty:** highest research uncertainty; mandatory follow-through.

**Create:** `docs/integrations/tvt-compatibility.md`; `services/edge/src/wso_edge/tvt.py`; `tests/contract/test_tvt_adapter.py`. **Update:** T00A's `tvt-call-map.md` with runtime evidence. APKs, proprietary libraries, captures and decompiled output are excluded from Git.

**Interfaces:** implement the same CameraAdapter as T17. Native handle ownership and shutdown live inside this adapter; no native pointer or device serial reaches public API/contracts.

- [ ] Verify the device/SDK scope and that the app/ABI matches T00A's artifact manifest. Read the completed static call map and unresolved-path list; rerun affected static analysis only when the analyzed artifact has changed. Do not treat static symbols as successful live transport.
- [ ] Prefer vendor SDK/documented bindings and targeted `pytvt` read functions. Map NAT selection → login → channel list → start preview → compressed frame callback → stop/logout. Document native callback threading and buffer lifetime.
- [ ] If static evidence is insufficient, obtain the required dynamic-analysis scope before tracing. Separate login/frame/alarm observation from audible talk testing.
- [ ] Add adapter lifecycle tests using fake native bindings.

```python
async def test_failed_preview_releases_native_session(tvt):
    tvt.native.fail_preview = True
    await tvt.try_open_stream()
    assert tvt.native.logout_count == 1
    assert tvt.native.live_callback_handles == 0
```

- [ ] Run `uv run pytest tests/contract/test_tvt_adapter.py -q`; implement lifetime-safe bindings and feed compressed frames into the existing media pipeline. Add watchdog restart for native crashes and cap reconnects.
- [ ] A live pass requires P2P login, channel list, decodable H.264/H.265 frame, one alarm, clean teardown and reconnect without UI. Talk capability is separately proven; never infer it from video success.

**Exit:** an APK-informed compatibility report and validated TVT adapter with the runtime evidence above. If required SDK/device/protocol capabilities remain unavailable, record the unsupported or pending result and escalate the concrete blocker; do not mark mandatory TVT work complete or silently replace it with LAN/Tapo. Alternative transports can keep an explicitly partial pilot useful, but changing this requirement requires a user decision. Research has no invented completion date.

## 10. Release acceptance and measurable targets

These are proposed engineering acceptance targets, not existing measured performance or contractual SLAs. Record hardware, number of cameras, stream resolution/FPS, network path, model and CLI versions for every benchmark. Change a target through an explicit decision record rather than changing the test until it passes.

| Area | Required correctness gate | Proposed pilot target / evidence |
|---|---|---|
| Tenant isolation | Cross-tenant API/DB/jobs/storage/browser/SSE/media all rejected | Full isolation matrix passes; zero foreign records in tests |
| Bootstrap/job scope | Membership and dispatcher discovery work without global business-data access; tenant jobs need no fake store | No-selected-tenant discovery, denied-role reads and storeless import tests pass |
| Sales | No hidden source polling, no lost freshness request; source-key upsert; gross/return/net and three velocity denominators distinct | Backend request counter and negative control, trailing-refresh and refund/calendar fixtures pass |
| Product registration | Full variant/unit/tax snapshot and durable cross-job uncertain-write hold prevent blind resubmit/overwrite | Delayed remote commit + new batch still yields one submit; uncertainty remains explicit |
| Wholesale auth | Session reuse, expiry/relogin, extra auth, revocation isolated per account | First supported site passes all lifecycle cases; other sites marked separately |
| Image intake | No guessed barcode/price; private input/crop persistence independent of cameras | Storeless/cameraless async upload/restart/cleanup acceptance plus per-field held-out accuracy |
| Camera | Reconnect, scoped access, off-LAN relay/HLS, bounded frame lag/spool | Decode media with store ingress blocked; UDP-blocked HLS fallback; expire/revoke active sessions; measure reconnect target |
| Evidence | Correct event/clip window, checksum, tenant access, deletion | 100% fixture linkage; missing pre/post coverage explicitly shown |
| Rules | Deterministic temporal boundaries and measured model behavior | Initial goal: >=90% precision per enabled behavior and <=1 false alert/camera/day on held-out pilot data; report recall, disable unvalidated rules |
| Alert latency | Rule alert is independent of CLI availability | P95 candidate-to-enqueue <=3 seconds at documented camera load; provider/network delivery measured separately |
| CLI | Supported login/image/schema, process cleanup, no inherited operational credentials | >=95% schema-valid successful synthetic runs outside auth/quota errors; P95 completion target <=60 seconds, hard deadline 90 seconds |
| Broadcast | Human-approved immutable payload; no replay after unknown send | 0 unapproved sends in fault tests; backchannel released on all exits |
| Payment matching | Stale data and multiple shoppers remain uncertain | No unsupported PAID_CONFIRMED/PAYMENT_ERROR/NO_MATCH in test matrix |
| Mobile | Same authorization/data, real device push and protected deep links | Android+iOS smoke evidence; provider acceptance not confused with reading |
| Recovery | DB/object/key restore and safe job reconciliation | Proposed RPO 24 hours, RTO 4 hours; prove via timed isolated drill |

R1–R4 can be piloted as a product/sales release without declaring the source's full CCTV MVP complete. The complete scope includes cameras, CLI summaries (latest instruction), mobile, approved broadcasts, sales, review-only visit/payment matching, and the user's mandatory APK/TVT research and validation. T00A's static deliverable and T31's runtime evidence are tracked separately; a Tapo-only pilot does not satisfy them. Product-registration inclusion in a named MVP remains a product rollout choice; the feature remains fully planned regardless of release naming.

## 11. Required operational behavior

### 11.1 Retry matrix

| Operation | Retry behavior | Terminal/hold condition |
|---|---|---|
| Source read | Up to 3 transient attempts with jitter, then visible failure | Invalid credentials, parser drift, disallowed destination |
| Wholesale login | One login after detected expiry under account mutex | Invalid password/locked account; user completes extra auth |
| Registration submit | No blind repeat after submit begins, including from a new batch/key | Persistent store/barcode hold remains until definitive reconciliation; absent read alone never releases it |
| CLI inference | One transient retry under account queue | Auth/quota/schema/image-capability error; keep incident |
| Notification | Bounded provider-aware retry; unique delivery key | Invalid token or configured attempt limit |
| Broadcast | Do not replay an uncertain audible send | Human decides a new command after checking state |
| Evidence upload | Resume/retry by checksum/event key | Quota/TTL reached; report missing evidence |
| Object delete | Retriable cleanup with tombstone | Alert on prolonged backlog; no restored public access |

### 11.2 Deployment and rollback

1. Build immutable images from locked dependencies and model assets. Generate source/license inventory and dependency vulnerability report; record accepted exceptions with owner/date.
2. Apply backward-compatible schema expansion, deploy compatible workers/API, then clients. Destructive contraction is a separate reviewed migration after data verification and rollback window.
3. Drain browser/CLI jobs before worker replacement. Registration/broadcast jobs preserve attempt state; replacement workers reconcile instead of replaying.
4. Deploy one tenant/store canary and observe errors/latency. Roll back application image/model version on regression; do not automatically downgrade a schema with newly written data.
5. Keep secrets out of builds, prompts, screenshots and logs. Validate that production app roles cannot access migration/admin privileges.
6. Disable a single connector/site/model capability by config when it breaks, while retaining last valid data and clear stale/unsupported status.

### 11.3 Performance and capacity planning

Start with the smallest authorized pilot, not a guessed GPU purchase. Measure decoded pixels/second, inference milliseconds/frame, active stream sessions, evidence bytes/day, browser jobs/minute and CLI quota/latency. Derive capacity from those measurements.

Example sizing equation for storage (not a measured estimate): `daily_event_bytes = cameras × events_per_camera_day × (clip_seconds × encoded_bytes_per_second + representative_image_bytes)`. Add retention, replication, spool and backups separately. Evidence-only storage must not accidentally become continuous cloud CCTV recording.

Use per-tenant/account admission limits to prevent one large order import or camera burst from starving others. Do not put raw frames in Celery/Valkey; queue IDs and store media in the bounded media pipeline/object store. Workers report backpressure, and UI shows queued status.

## 12. Requirements traceability

| Source requirement / latest addition | Implementation tasks | Acceptance evidence |
|---|---|---|
| Tenant/user/store roles, one or many stores | T02, T03, T24 | Isolation and store-switch tests |
| Credential encryption, audit, revocation | T04, T05, T18, T30 | Tamper/redaction/revocation/restore tests |
| OrderQueen read allowlist and dynamic stores | T06 | Fixture contracts and G01 |
| First-sales-month backfill, recent upsert, no polling | T07, T09 | Resume/duplicate/idle/reentry tests |
| Quantity/revenue/velocity/trends/ADI/CV²/stock confidence | T07, T08, T09 | Gross/refund/net and operating-day fixtures, coverage reasons |
| Text/photo/product page/order history | T05A, T10, T14, T15, T16 | Four-input fixtures; variant/unit/tax preservation and camera-independent photo lifecycle |
| Saved wholesale IDs/passwords, auto-login/relogin | T04, T13 | Expiry, MFA, isolation, deletion tests |
| New product registration, duplicate and partial failure | T11, T12 | Lost-response and existing-product tests; G02 |
| Standard camera adapters, health, live media | T17, T18 | G05 and reconnect/ticket tests |
| YOLO/tracking/pose/zones/duration | T19, T26 | Temporal fixtures and measured behavior evaluation |
| Freezer/running/waving/kiosk difficulty | T26 | Per-behavior precision/recall and G08 distinction |
| Frames/clips, incident states, feedback, staff mode | T18, T20 | Evidence/review/suppression tests |
| Codex CLI or Claude CLI instead of direct API | T21, T22 | Versioned CLI/image/schema/isolation tests; G06 |
| Web/mobile alerts and common data | T23, T24 | Duplicate delivery and real-device smoke |
| Human-approved warning templates/TTS/talk | T25 | Approval hash, busy/timeout cleanup and G07 |
| Visit/payment matching and human review | T27 | Ambiguity, stale sync, clock and cancellation tests |
| Repeat incident patterns | T28 | Local-time aggregation without identity linkage |
| Feedback datasets/model versions/rollback | T29 | Dataset split and failed-canary tests |
| Retention, deletion, minimum payment data, operations | T05A, T07, T18, T30 | Sanitized payload, shared asset/crop deletion, restore/pilot evidence |
| Mandatory SuperLive Plus APK reverse engineering and TVT integration | T00, T00A, T31 | G10 static/runtime records, APK/ABI manifest, JNI/native call map, lifecycle and real frame/alarm evidence; no Tapo substitution |

## 13. Implementation handoff

The repository currently contains the service specification and planning artifacts, not an application. Begin prerequisite work with mandatory T00A APK acquisition/static analysis and scoped T00 probes. T01/T02 and independent sales work can proceed alongside device-input preparation; complete the static gate before TVT implementation. Do not mark tasks complete by creating empty directories or stubs, and do not reclassify T00A/T31 as optional because another camera path works.

Before each task, verify dependencies and capability gates. After each task, record changed paths, test commands/results, newly verified capabilities and remaining blockers in the ledger. Review public contract changes before downstream tasks consume them. Never replace a missing real-site contract with a fabricated endpoint or selector.

Execution choices:

- **Native execution:** one implementer follows this document, with review at coherent release boundaries. Recommended initially because the shared schema, authorization and job contracts are tightly coupled and the repository is empty.
- **Subagent-driven execution:** independent implementers/reviewers can work from stable task briefs after core interfaces exist. Assign disjoint files and pin the contract revision; do not parallelize migrations or shared-contract edits without an owner.

Use the existing Superpowers skills; no project-specific skill was created. Review this plan and choose the execution mode before starting application implementation. The requested planning work does not require live credentials, device access, a deployment, or an automatic commit.

## 14. Review correction matrix

These are document corrections, not assertions that application tests have already run. Keep all corresponding task checkboxes open until implementation and verification. R-numbers follow the ten findings in the review report.

| Finding | Corrected contract | Task ownership | Required regression evidence |
|---|---|---|---|
| R01 Uncertain registration across jobs | Durable `(tenant,store,barcode)` write hold; no timeout/cancel/absent-read release | T11, T12; Sections 6.4/7.2/11.1 | Delayed remote commit, lease expiry, canceled job and a new batch/key cause exactly one remote submit |
| R02 Lost variant/unit/tax fields | Typed candidate fields and versioned adapter schema preserved in revision/frozen hash/readback | T10, T14–T16, T11–T12; Section 6.2 | Full round trip retains fields; editing any submitted choice invalidates prior snapshot |
| R03 No off-site media route | Scoped outbound WSS control/frp signaling-HLS tunnel, coturn relay and HTTPS HLS fallback | T17, T24, T25; Section 4 | Off-LAN decoded video with inbound blocked; UDP-blocked fallback; active-session revocation |
| R04 RLS bootstrap circularity | Verified-principal-only identity role; metadata-only dispatcher projection/functions | T02, T03, T05; Section 5.3 | Discovery without selected tenant plus denied payload/secret/foreign-principal access |
| R05 Mandatory store for tenant jobs | Discriminated TenantScope/StoreScope and per-job-kind registry | T01, T03, T05; Section 6.2 | Import/login before any store exists; store mutation rejects tenant-only scope |
| R06 Photo storage depends on cameras | Generic private upload/assets/retention moved to T05A; T18 reuses it | T05A, T16, T18 | Async photo upload/OCR/restart/cleanup with camera services absent |
| R07 Lost manual/reentry refresh | Per-request freshness watermark and one trailing finite sweep for outstanding requests | T07, T09; Section 7.1 | Refresh after transaction page read sees a newly added sale even with identical date range |
| R08 Missing gross demand quantities | Gross sold/returned/net quantities and explicit completed-sale/return policy | T07, T08; Section 7.1 | Equal net but different gross sales produce different demand metrics; delayed returns preserve demand date |
| R09 Trading-day denominator omitted | Separate calendar, OPEN trading-day and positive-sales-day metrics with operating calendar provenance | T07–T09; Section 7.1 | 28 units/seven sale days/28 OPEN days => 1 trading versus 4 active-sale; UNKNOWN calendar => null |
| R10 Browser test misses backend polling | Frontend sync-request test plus backend-clock actual-upstream-request invariant and negative control | T07, T09; Section 8 | Idle settled backend makes zero reads; a test-only periodic reader is detected by the same assertion |
