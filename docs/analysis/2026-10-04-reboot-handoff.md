# Reboot handoff — 2026-10-04

Recorded at approximately 19:47 KST (Asia/Seoul). The user requested preparation
and durable records before reboot. Implementation is intentionally stopped at
this checkpoint. This document is the continuation checklist; the canonical
service analysis remains [service-analysis.md](../service-analysis.md).

## 1. Where the current work lives

- **Active implementation worktree:**
  `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
- Active branch: `codex/superlive-web-service`.
- Baseline HEAD: `211d1484aa16eb30f5d362758f149f98dec9dfdf`.
- Primary checkout: `C:/2026_project/wisdom-super-observer`, branch `main`.
- At this checkpoint, local `main`, `origin/main` and
  `origin/codex/superlive-web-service` all resolve to the same baseline. Remote
  references were inspected locally; no fresh remote fetch was performed.
- **Latest continuous-media source, tests and reports are saved on disk but
  uncommitted.** They exist in the active worktree, not in primary `main`.
  Do not reset, clean, remove that worktree or substitute the primary checkout
  for it. The primary checkout receives a short pointer to this handoff.
- No new commit or push was made for reboot preparation. Earlier authorization
  to publish to `main` persists; source review and appropriate verification of
  the current changes remain necessary before publication.

Read the shared analysis policy, active `AGENTS.md`, this handoff and the top of
the canonical report first. Use Superpowers 6.4.2 and existing approved plans;
the user already authorized implementation and parallel agents. Do not repeat
design approval or request a phone connection for this Windows native path.

## 2. Intended service and actual progress

Purpose: reproduce SuperLive Plus APK functionality as a React/Tailwind web
service with Python backend, including both user-authorized CCTV stores.
Current local live path:

`Chrome → Next BFF → FastAPI → scoped SQL tickets → mTLS bridge → Windows TVT
native child → isolated continuous decoder → aiortc VP8 → browser video`.

| Area | Evidence and limit |
| --- | --- |
| Local HTTPS | Previously verified trusted mkcert HTTPS in Chrome without certificate bypass. |
| Actual device inventory | Previously verified store 1: 8 channels; store 2: 4 channels, including saved readback in Chrome. |
| Windows CCTV media | Previously captured and decoded bounded real HEVC frames on Windows. No Android/ADB dependency for this path. |
| Continuous native and web composition | Source exists, including leases, API/RPC, continuous decoding and FE playback controls. Latest integration remains incomplete. |
| Continuous Chrome playback | **Not accepted.** No demonstrated sustained video, two-store playback, or successful stop/reopen acceptance. |
| Full APK parity | **Not complete.** `release_ready=false`, `MATCHED=0`; do not infer parity from source presence or unit tests. |

The existing full-suite result remains historical: 5,634 passed, 599 skipped,
3 failures and 138 setup errors. Source-hash gates, unavailable Linux acceptance
fixtures and timing/settlement failures remain recorded in the canonical report.
No tests were rerun during this reboot-preparation request.

## 3. Exact unfinished code boundary

The completed media agent delivered fixes in:

- `services/tvt-media/src/wso_tvt_media/native_source.py`: independent original
  ingress and decoder owners; exact FIFO bounded to 16 compressed frames / 4 MiB;
  overflow fails closed; retained decoder cleanup; fast `transport_current()`.
- `services/tvt-media/src/wso_tvt_media/live.py`: separately retained original
  source and aiortc close tasks, shielded caller waits, actual settlement barrier.
- Tests: `tests/tvt_parity/test_local_media_source.py` and
  `tests/tvt_parity/test_local_webrtc.py`.
- Updated guide: [tvt-local-webrtc.md](../integrations/tvt-local-webrtc.md).

Author-reported verification: **38 tests passed, zero skipped, 7.24 seconds**;
scoped Ruff and strict mypy passed. Root has read the source boundary and guide
but has **not independently rerun or reviewed this latest delta**. Earlier
independent C0/I0/M0 reviews do not cover these latest corrections.

Author-frozen SHA-256 values (Root matched both at this reboot checkpoint;
verify again if later edits occur):

```text
native_source.py b7a7665dd09785fbdb422664a61919c4d13eeaa7d23293c50c317c7b67e61b19
live.py          91917e6ff8f60be8d71b5f8a0ef398df8a15d80bb4f9f3d55cd3ea65b00af308
```

**Next edit belongs in `services/tvt-media/src/wso_tvt_media/worker.py`:**

1. `_prepare` still supplies `current=source.current` to `LocalWebRtcSession`
   (line 144 at checkpoint). Wire `source.transport_current` after verifying
   the new contract. Synchronous SQL per RTP fragment blocks the media loop.
2. Move fresh SQL checks in async `_watch` off the event loop with
   `asyncio.to_thread`. Inspect `_browser_received` as well: its `source.current`
   and `executor.playing` calls must retain fresh authorization without blocking
   the loop. Preserve exact original proof and shutdown ownership.
3. The fast permit is at most 200 ms from the pre-SQL observation, clipped to
   fresh SQL lease expiry; query latency consumes the window. Fresh SQL checks
   remain in ingress, decode and publication. Do not lengthen it, cache SQL
   authorization indefinitely or substitute it for admission.
4. Run causal worker/source/WebRTC regression tests and scoped static checks.
   Reuse the independent media reviewer for this delta and the worker wiring.

The native small-chunk FIFO coalescing correction was already independently
reviewed C0/I0/M0 (346 author tests and two reviewer regressions). It preserves
the original 256-chunk / 1 MiB native limits. Do not confuse that completed
correction with the newer ingress/close/permit changes still awaiting review.

## 4. Runtime state before reboot

- All three non-root agents listed by the collaboration tool are completed;
  no active source writer remains.
- No listener on local port **3543**; no project media Python worker was found.
- The remaining project-related Node processes were Codex computer-use helpers,
  not the application server, and were left alone.
- The owned PostgreSQL 17 runtime on **127.0.0.1:57056** was gracefully stopped
  using its identity-verifying `runtime.py stop`. Exit code 0 reported
  `PostgreSQL runtime stopped; data preserved`. The temporary drive alias is
  removed by that routine. Existing cluster and credentials are retained.
- No OS reboot was initiated by the agent.

Two earlier failed live runs (`c7fad019cfe4438cb6222986d125f7ca` and
`fccdeb002f61446698b81f696f82f1f1`) required terminal recovery of their exact
broken workers after an aiortc close cancellation defect. Their custodians
exited with failure, removed owned databases/private state and preserved the
source DB. This was **not graceful playback cleanup acceptance**. Details and
earlier successful inventory/capture evidence remain in the canonical report.

## 5. Resume procedure

Start in the active worktree, inspect status and complete section 3 before any
real-device run. Use Windows PowerShell and the existing environments:

```powershell
Set-Location 'C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer'
git status --short --branch
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_webrtc.py tests/tvt_parity/test_local_media_worker.py --tb=short
```

Main `.venv` has Python 3.12, aiortc 1.15 and av 17.1. The isolated Windows
decoder uses `.superpowers/runtime/windows-media-decode/venv/Scripts/python.exe`
with PyAV 19. Node is `C:/Program Files/nodejs/node.exe`; pnpm/uv may not be on
PATH. Do not reinstall the environments or SDK for a normal reboot.

After reviewed fixes, start the **existing** PostgreSQL cluster:

```powershell
.venv/Scripts/python.exe .superpowers/runtime/postgresql17/runtime.py start
```

This restores the owned alias and keeps the original database/roles. Do not run
setup, delete the cluster or rotate credentials as a substitute for startup.

Then create a **new immutable source approval** for the actually reviewed tree.
Existing approval files under
`.superpowers/verification/local-device-media-browser-runtime/` describe older
source and must not be silently reused or overwritten. The latest pre-fix
`root-source-approval-vp8.json` is stale for the newly edited media modules.
`approve-local-media-root.py` and `approve-local-media-fifo-root.py` in the
verification directory are reference scripts; review/adapt their fixed output
names and source selection rather than blindly rerunning them. Native receipt
`C:/wso-private/windows-tvt-sdk-20261003/source-approved-local-live-service-m3-fifo.json`
was the current native source approval; keep it only if its sources still match.
Never replace a source review with merely recalculating hashes.

Launch the original owned coordinator after the new approval exists:

```powershell
# Replace the filename with the newly reviewed, immutable approval.
.venv/Scripts/python.exe .superpowers/verification/run-media-browser-root.py NEW_APPROVAL_FILENAME.json
```

Normal acceptance must have `WSO_TEST_LOCAL_MEDIA_TRACE` unset (the diagnostic
observer activates only when it is `1`). Do not print private environment
values. The launcher retains the original process and emits a ready URL:
`https://localhost:3543/api/auth/login`.

Use the GPT Chrome tool, reacquiring the browser/tab after reboot (old tab IDs
and JavaScript bindings may be invalid). Normal UI flow:

1. Open the ready URL; verify ordinary trusted HTTPS, without ignore-cert flags.
2. Click `Sign in as local device demo owner`, then `연결 관리`.
3. Run `기기 확인` for both stores before live playback; expect 8 and 4 channels.
4. For store 1 select `2번 채널`; for store 2 select `1번 채널`.
5. Click `실시간 재생`; verify real rendered frames, dimensions and increasing
   `video.currentTime` for more than 60 seconds. The `data-presented-frames`
   attribute currently records first-frame evidence, not a continuous counter.
6. Verify both-store operation, stop/reopen, TTL/heartbeat and original-resource
   retirement. Stop the owned runtime through its `shutdown.json` file-control
   mechanism and await the original coordinator receipt.

Record actual results, source stability and cleanup in the canonical report.
Do not edit source while a source-pinned acceptance runtime is running. Use
bounded structural diagnostics only if a concrete failure remains; preserve
failed-run evidence rather than retrying the SDK blindly.

## 6. Local-only material and evidence

These paths are references only; their secret contents must stay outside Git:

- Device credentials: `C:/wso-private/local-device-web/devices.json`.
- Trusted TLS: `C:/wso-private/wso-local-dev-tls/server/`.
- Native SDK: `C:/wso-private/windows-tvt-sdk-20261003/package/`.
- Runtime cluster/credential state: `.superpowers/runtime/postgresql17/`.
- Root run pointer: `.superpowers/verification/local-device-media-browser-runtime/root-current-run.json`.
- Actual receipts: `.superpowers/verification/local-device-browser-root/` and
  `.superpowers/verification/local-device-browser-runtime/`.
- Existing SDD log:
  `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/progress.md`.

Runtime scripts and evidence in ignored directories survive this machine's
reboot but are not a portable deployment package. Portable sources and reports
are the handoff authority. Do not print credentials, serials, raw SDP, cookies
or private media into documentation/tool output.

## 7. Work after successful browser acceptance

Production `create_server_from_environment` still wires inventory only; owned
fixture composition is not production media integration. Finish production
media bootstrap, then work through remaining APK plan/acceptance gaps. Reuse
`docs/superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md`
and the canonical report rather than declaring all APK features implemented.
Deployment TURN policy, supported browsers/audio and capacity remain review
items in the media guide; no new user decision is needed for the immediate fix.

Before authorized publication, review selected changes and secret exclusions,
run relevant verification, update reports, and commit/push to `main` without
overwriting unrelated checkout changes. Keep source/tests/manifests tracked;
keep only generated, runtime and private artifacts ignored.

Update log: 2026-10-04 — reboot checkpoint; source boundary and process inventory
inspected, author-reported latest test evidence distinguished, owned PostgreSQL
stopped with data preserved, implementation and actual acceptance left pending.
Final readback verified this handoff and both AGENTS entry points, matched the
two author source hashes, confirmed cluster/credential files still exist and
found no listeners on 3543 or 57056. `git diff --check` passed in both checkouts
(only existing Windows line-ending conversion warnings were emitted).

## 8. Continuation outcome — 2026-10-04 (post-reboot, Claude Code controller)

Section 3's boundary was completed and reviewed, and the actual acceptance
gate has now been met for the two configured channels. Details, reviews,
measurements and rulings R104–R112 are in the
[liveness review](2026-10-04-local-media-liveness-review.md); the canonical
[service report](../service-analysis.md) carries the summary.

- **Code (uncommitted, same worktree/branch, HEAD still `211d148`):** worker
  wiring (off-loop SQL, fast permit); pooled media admission engine; authority
  heartbeat, non-terminal staleness, SQL reduction, quarantine on failed
  aiortc close (`native_source.py`, `live.py`, `worker.py`,
  `local_media_admission.py`); native N9000 keepalive every 6 s in
  `windows_socket_worker.serve_live`; live video fills its 16:9 box. Each change
  passed an independent review (final blocking findings C0/I0; native keepalive
  C0/I0/M0).
- **Approvals/receipts (immutable, ignored paths):**
  `root-source-approval-c1.json`, `-c2.json`, `-c3.json` (latest; 92 sources) in
  `.superpowers/verification/local-device-media-browser-runtime/`; new native
  receipt `C:/wso-private/windows-tvt-sdk-20261003/source-approved-local-live-service-m3-keepalive.json`
  (the older `-m3-fifo.json` no longer matches the native worker). Scripts:
  `approve-local-media-c{1,2,3}-root.py`, controller Chrome driver
  `cdp-drive.mjs`, adapted SQL runner `run-local-media-admission-sql-c1.py`.
- **Executed acceptance:** trusted HTTPS, OWNER login, 8/4 channels, real video
  in Chrome for both stores concurrently, continuous playback (~5 min store 1,
  81.7 s store 2 concurrently), stop/reopen, TTL/heartbeat, confirmed cleanup of
  every lease, clean runtime shutdown and source stability; the user visually
  accepted the display proportions.
- **Runtime state at hand-off:** owned PostgreSQL 17 cluster **running** (data
  preserved; stop with its `runtime.py stop` if needed). No listener on 3543 or
  9333; controller Chrome closed; no run processes.
- **Next priorities:** (1) user decision on publishing — whole-branch review,
  secret-exclusion check, then commit/push only with explicit user approval in
  the active session; (2) 429 on near-simultaneous starts (client retry or
  queue); (3) quarantine recovery path for production; (4) production media
  bootstrap wiring (`create_server_from_environment` still wires inventory
  only); (5) remaining APK features (playback, PTZ, audio, sub-stream,
  "original scale" option, etc.). `release_ready=false`, `MATCHED=0`.

**Publication update — 2026-10-05.** The work listed in section 8, plus the
final-review fix wave, was committed to `codex/superlive-web-service` and
fast-forwarded to `main` with user approval (see the service report's
"Publication — 2026-10-05" entry). It is no longer uncommitted. Excluded from
that commit: the `/monitoring` live wall page, still in review.
