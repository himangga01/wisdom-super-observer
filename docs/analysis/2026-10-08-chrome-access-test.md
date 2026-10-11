# Chrome access test

Date: 2026-10-08, Asia/Seoul. Requested action: open Chrome and test access to
the local service. Source authority remains the implementation worktree described
in `2026-10-08-original-plans-remaining-work.md`.

## Executed result

- GPT Chrome extension control connected successfully to the existing Chrome.
- Created a new task tab and navigated to
  `https://localhost:3543/api/auth/login`.
- Chrome returned `net::ERR_CONNECTION_REFUSED`. A separate accessibility
  observation showed the actual “사이트에 연결할 수 없음” page and
  `ERR_CONNECTION_REFUSED`.
- Independent bounded HTTP requests to the known HTTPS3543 and HTTP3000 local
  endpoints also returned connection refusal. No certificate bypass was used.
- Saved the actual error-page screenshot at
  `.superpowers/verification/2026-10-08-chrome-access/connection-refused.png`.

Chrome control works; the service is not accepting connections at these endpoints.
This is not a successful application/login/CCTV test.

## Startup constraints and limits

The primary checkout has no root or web `node_modules`. Existing Next/Python
dependencies are present in the separate implementation worktree, whose files
are read-only in this session. Its normal runtime creates auth-state/evidence and
Next build files there; those writes are outside the current writable roots.
No existing test runtime was launched into that read-only directory, no temporary
dummy service was substituted, and no product code/dependency change was made.

Current permission configuration also makes `.git` read-only. A user permission
approval inside chat does not change these filesystem rules. The authorized
service implementation/restart/publication work needs an appropriate writable
implementation workspace; research/report work can continue in the primary
checkout. No browser permission or certificate problem is established here.

The broader selected-feature and abnormal-behavior research task remains active.
Related research: `2026-10-08-cctv-incident-research.md` and
`2026-10-08-apk-selected-features-research.md` when completed.

Update log: 2026-10-08 — actual Chrome navigation, accessibility failure state,
bounded HTTP refusal and screenshot recorded; startup limits distinguished from
application feature acceptance.


## 2026-10-09 update: permission restored and actual restart

The previous read-only limitation no longer applies: filesystem policy is now
unrestricted. No Windows folder read-only attribute was changed. The old
implementation source304 hashes matched before restart. PostgreSQL17 and the
reviewed local runtime started with original data preserved; the HTTPS listener
uses localhost IPv6::1. GPT Chrome opened the trusted page without interstitial,
logged in as the synthetic OWNER and verified real8/4 recorder channels.

Live start failed HTTP422 LOCAL_DEVICE_INPUT_INVALID before worker admission:
legacy connection-card request lacks the explicit shared wall/main-focus fields.
Frontend correction and safe API diagnostic logs were implemented with causal
regressions. Logging C0/I0/M0 and separate development launcher C0/I0/M0 reviews
passed; frontend STOPPING-remount fix1 source re-review remains pending.

The20min acceptance runtime expired and normally retired its Node/API/worker/
DB/context, source unchanged/private0; it stays an expired failure rather than
a playback pass. New development-only launcher uses an explicit maximum2h/API
debug profile and preserves the1200s/900s formal acceptance separately. Actual
corrected playback and private log capture still require the next run. See the
implementation worktree's canonical service report and2026-10-09 source reports.

### Subsequent actual development result (2026-10-09)

The frontend fix1 independent review is now C0/I0/M0. New development run1be34ba
created the private API log successfully. Actual substream start/focus/offer/
substream stop returned200, then MAIN start reached RPC and returned404
LOCAL_DEVICE_DENIED. This replaces the earlier input422 but is not successful
video playback. The pending diagnosis is runtime-only whitelisted exception
locations; Core/native/admission source remains unchanged.

Run1be34ba retired original Node/Next/API/worker/context and owned database;
source database contents are equal, private occurrences0. Root closure drift is
only a pinned logging-author report update, not source-body drift. Preserve this
run as a failed development result. PG57056 runs; app3543 is stopped for the
reviewed diagnostic restart. Reuse the active worktree service/handoff and
Oct9 frontend/logger/review reports for current implementation authority.
