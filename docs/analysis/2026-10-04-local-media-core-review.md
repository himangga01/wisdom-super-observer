# Independent local media core review

**Current scoped result: C0 / I0 / M0 after independently verified corrections.**
Initial findings and intermediate rereviews are retained below as historical evidence.

Review date: **2026-10-04, Asia/Seoul**. Coordinator-supplied source baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, active `superlive-web-service` worktree.
Reviewed M3 additions were uncommitted; parallel native, WebRTC, API and frontend
owners remained active. No Git operations or application source edits occurred.

Read before reuse and refresh afterward: [project instructions](../../AGENTS.md),
[canonical service report](../service-analysis.md),
[approved Phase 2/M3/M4 design](../integrations/tvt-local-service-integration.md),
and [core implementation guide](../integrations/tvt-local-media-service.md).
The shared Windows analysis policy governs this saved review.

## Scope and implemented behavior

Reviewed contracts `tvt/{media,local_media}.py`, core
`tvt/{local_media_admission,local_media_service}.py`, migration 0013,
`test_local_media_service.py` and `test_local_media_admission.py`. Other layers
were read only at their declared interfaces. This review does not approve the
complete parallel branch or M4 device/browser runtime.

The intended service is OWNER-only live viewing of a verified saved local
channel. Implemented start authority is a committed one-use ticket and sealed
worker/native-generation binding. Its bounded credential callback opens one
original native owner; a separate transaction publishes native permission proof.
Fresh media authority, heartbeat, bounded frame reads and cleanup operate outside
the credential transaction. Stop uses one-use purpose-bound control and CLOSED
requires native cleanup confirmation plus SQL retirement.

## Findings: C0 / I2 / M0

### I1 — shutdown omits pending owners from failed startup

`local_media_service.py:231–235` retains failed-start cleanup in `_retiring`.
`sweep:391–398` retries that list, but `shutdown:424` stops the monitor and only
closes `_owned`; it never processes `_retiring`. An original owner that failed its
first close can therefore survive shutdown even when its next close would succeed.
The shutdown call does not indicate this uncertainty to its caller.

Inert executed reproduction: start with a session whose permission proof is
false and whose `close` returns false on call one, true on call two. Failed start
produces `close_calls=1, pending_retiring=1`. After `shutdown`, both values remain
**1**. No device or native process was created; this tests the owner protocol.

Include failed-start retirement in the coordinated shutdown path, and retain or
report any remaining uncertain ownership rather than returning an apparently
settled shutdown. Add an inert regression that covers this exact retryable owner.

### I2 — failed retirement after uncertain redemption loses its retry binding

`local_media_admission.py:187–189` tries to close its generated sealed authority
after redemption/commit failure. If that close also fails, the generated authority
never returns to the executor. In `start`, `lease` is still `None`, so neither
`_owned` nor `_retiring` retains it. A committed LOGIN row may then consume channel,
actor and global capacity indefinitely with no normal sweep retry capable of
addressing it. SQL deliberately does not retire uncertain redeemed rows by timeout.

Inert executed reproduction extends the existing uncertain-commit fixture: the
fake DB records committed phase LOGIN, then reports uncertain commit; its close
query also raises an inert SQL-unavailable error. Result: **phase LOGIN, one close
attempt, zero owned bindings, zero retiring bindings**. Calling `sweep` leaves
the same phase and close count. This models uncertain completion; actual DB commit
and network-failure behavior was not executed by this reviewer.

Retain the exact generated sealed authority across uncertain redemption and
failed retirement, using an admission/executor retry owner that survives the failed
start. Do not infer rollback or clean closure from the thrown exception. Add a
regression in which retirement recovers and the same authority retires the row.

## Other source conclusions and integration limits

- SQL live checks require READ COMMITTED and exact OWNER membership, live web
  session, tenant epoch, store/link, TVT_DEVICE generation/secret version,
  inventory/device/channel revision and native grant binding. Lifecycle triggers
  invalidate existing leases/grants and set STOPPING; remove/re-add does not
  restore their authority. API/worker roles have function-only access to forced-RLS
  tables. One-use redemption/control updates recheck their consumable state.
- Native permission proof is distinct from inventory. Independent codec/framing/
  timing fields are required for the trusted PLAYING transition; their booleans
  are still worker assertions, not independent browser render evidence.
- Start has a bounded short credential transaction; streaming uses fresh separate
  queries. The provider must discard its startup credentials/callback and serialize
  concurrent `read_frames`, renewal and close of the original native owner. Core
  close serializes competing closes and fences local delivery before retirement;
  it does not itself lock native reads/renewals against native close.
- Media SQL TTL is 5–30 seconds, controls at most 20 seconds, normal sweep one
  second; renewal cannot revive expired/invalidated/STOPPING state. Quotas count
  uncertain STOPPING leases: global 32, actor four, channel one. These are source
  limits rather than measured native safety/capacity acceptance.
- Native close/read and thread shutdown are cooperative provider contracts, not
  a core-enforced process kill. Final cleanup confirmation and concurrent native
  read/stop/sweep acceptance remain separate integration gates.

Priorities: correct I1/I2, preserve exact retry ownership, then verify coordinated
shutdown/concurrent native lifetime before M4. Open product questions remain the
accepted orphan bound, restart reconciliation and measured simultaneous sessions.
No authority expansion or new product choice is needed to fix these findings.

## Verification and actual limits

Fresh reviewer command:

```powershell
$env:PYTHONPATH='packages/core/src;services/tvt-media/src'
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_local_webrtc.py tests/tvt_parity/test_local_media_service.py tests/tvt_parity/test_local_media_contracts.py tests/tvt_parity/test_contracts.py --tb=short
```

**153 passed, zero skipped, 0.96 seconds**: 130 portable contracts/core cases
plus 23 corrected WebRTC cases. The two additional direct inert reproductions
produced the ownership gaps above. No DB, device, credentials or browser calls
were made. Ruff/mypy results are author-reported, not independently rerun here.

Root reported actual guarded SQL run `a1056ae425954233abb0160c235afb5c`:
**13 passed, zero skipped/errors**, original child reaped, owned DB removed,
source preserved and zero known private-value hits. This is coordinator-reported
evidence, not reviewer execution; the prior 12-pass/one-failure grant-count case
was scoped to its own tenant/connection/session before that rerun. These SQL cases
do not exercise the two newly reproduced uncertainty paths or actual native life.

The earlier [WebRTC review](2026-10-04-local-webrtc-review.md) now records independent
closure of both minor findings, with all four correction regressions passing.
No M4 browser/device, full-suite or release-ready conclusion follows from this review.

Update log: 2026-10-04 — initial independent M3 source review, fresh portable
verification, two inert cleanup reproductions; C0/I2/M0 before correction.

### Correction rereview — 2026-10-04: C0 / I1 / M0

Initial I2 is closed: admission retains the exact sealed authority after failed
retirement, retries at most four bindings per sweep, and keeps its engine/owner
when shutdown remains uncertain. The recovery regression checks equality of all
original authority/worker/native fields. Sequential initial I1 is corrected:
executor shutdown retries failed startup owners and returns false while ownership
remains; a later successful retry returns true. The immutable private `proof()`
port validates original-session proof and rechecks current authority.

Fresh reviewer portable contracts/core execution: **133 passed, zero skipped,
0.53 seconds**, including the three new regression cases. SQL was unchanged;
Root's prior actual 13-case SQL result remains separately reported above.

One concurrent variant of I1 remains. `_retry_retiring` removes its pending list
into a local snapshot before calling native close. With the supported external
scheduler (`monitor_interval=0`), another thread's `shutdown` cannot see those
inflight owners. Executed inert Event/Thread reproduction: a failed-start owner's
first close returns false; an external sweep's second close blocks on an Event.
While it blocks, **shutdown returns true, sweep remains alive, `_retiring` is
empty**. Release makes that close return false and the original owner reappears
in `_retiring`. Thus the true result does not establish settled original ownership.
Track inflight retirement/sweep work in the shutdown condition or serialize the
whole retirement/shutdown operation, with a regression for this concurrent case.
No production process or DB was used by this reproduction.

### Concurrent correction closeout — 2026-10-04: C0 / I0 / M0

The remaining I1 is closed. `_retry_retiring` publishes every exact owner in
`_retiring_inflight` while holding the ownership lock before native/SQL work.
It atomically settles or requeues each binding and restores unprocessed bindings
on interruption. Shutdown checks both queued and inflight ownership, so an
external sweep cannot hide its original owner in a local snapshot.

Reviewer read the changed scope and new Event/Thread regression, then ran only
`test_shutdown_cannot_report_settled_while_external_retirement_is_inflight`:
**one passed, 14 deselected, 0.14 seconds**. It asserts false during blocked
original close and true only after recovery, with the same original owner.
The author's final 134 portable passes and Root's unchanged 13 actual SQL passes
remain separately attributed; they were not repeated for this bounded closeout.
No SQL/native/browser acceptance or original verification limit advances here.

### Pipeline barrier and playing-control extension — 2026-10-04

Reviewed matching core delta for the separately recorded
[pipeline correction](2026-10-04-local-media-worker-review.md): private
`attach_retirement` is exact-owner/current/once-only and serialized with original
close; current checks recheck stopping/shutdown after SQL; `_retire` combines
original native cleanup with a nonblocking external media settlement callback,
including when native cleanup itself fails. `finish_stop` completes an already
authorized ID without second ticket redemption. The new `playing` control purpose
is one-use/current and does not create a new live grant.

Fresh narrow correction selection: **eight passed, 14 deselected, 0.41 seconds**.
Root reported actual SQL run `628390264af04a5d8c2f9b49d555d4cc`: **15 passed,
zero skipped/errors**, owned cleanup/source preservation/private-value scan clear;
not independently executed here. Current reviewed core outcome stays **C0/I0/M0**.
Actual native/decoder/peer/browser retirement acceptance remains separately required.
