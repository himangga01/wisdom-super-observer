# Independent Windows local live session review

Review date: **2026-10-04, Asia/Seoul**. Baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, active worktree
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
The initial review tree contains concurrent uncommitted M3/M4 native, core,
SQL, media, API and browser changes. This review covers **only the native slice**,
not the reviewer's own core implementation.

Read [AGENTS.md](../../AGENTS.md),
[service-analysis.md](../service-analysis.md) and
[the native implementation reference](../integrations/tvt-windows-live-session.md)
before reuse. Refresh affected evidence after corrections. Root owns the canonical
service report and instruction bridges.

## Initial decision: request changes — C0 / I1 / M0

**Current status after the correction rereview: C0/I0/M0, source approved.**
The initial finding below is historical evidence; the dated closure records the
corrected source and independently executed regression. Actual acceptance remains
separate.

One Important expiry defect is reproduced in actual source with an inert clock.
Correct it and add the regression before treating this new source as approved
for actual SDK/device acceptance. No Critical or additional Minor findings were
identified in this bounded review. This decision is source review; it does not
establish native, device-safety, browser or continuous-runtime acceptance.

### I1 — renewal may revive a generation after its original expiry

Location: `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py`,
`LiveParentAuthority.renew`, initially around line 149.

The first `check(current)` checks the old deadline before and after the current
callback. The code then separately validates the new deadline and replaces
`self.deadline`. The final `check(current)` uses that replacement. If the old
deadline passes between the first check's return and the assignment, renewal
succeeds without ever testing that original deadline again. The watchdog need
not have observed that edge during its 10-millisecond poll interval.

Executed inert reproduction (no watchdog, child process, SDK, credentials, DB
or network): instantiate the real `LiveParentAuthority` with expiry `10.0` and
an invented `Event`; patch its module's monotonic clock with values
`9.8, 9.9, 10.1, 10.2, 10.3`; call `renew(20.0, lambda: True)`.
The first two reads pass the old expiry, the third is already after it, and the
last two check the replacement. Actual output:

```text
renewed=True, old_expiry=10.0, new_expiry=20.0, failure=''
```

This contradicts the documented nonrevivable native-generation expiry boundary.
Current SQL authority still independently fences live reads, so this observation
does not prove a SQL heartbeat or permission bypass. It does invalidate the
native orphan-renewal claim at the expiry edge.

Required correction: retain the old deadline and recheck it at the final renewal
decision before assignment; preserve the first terminal denial/expiry latch and
prevent a concurrent watchdog terminal state from being cleared or bypassed.
Add a deterministic regression for this exact crossing, plus a valid renewal
case. No timeout-based guessing or actual device run is needed for this fix.

## Reviewed purpose, architecture and implemented boundaries

`local_live_provider.py` adapts the fenced private core channel selection into
the already proved main/stream1 native path. Each open owns a fresh original
process, Job, socket and first exclusive live task. The process-wide attempt
gate admits at most two healthy explicitly handed-off owners, rejects a third
as fixed BUSY/429 and refuses new work when previous custody is uncertain.

The parent retains its exact `ChildOwner`, original Popen/Job handles, writer,
outputs and private IPC authority. `ChildOwner.finish` is serialized across
caller and reaper. Stop/expiry operates on the retained original process rather
than finding a replacement PID. Uncertain cleanup retains custody in
`PENDING_OWNERS`; successful close also waits for the retirement thread.

The child performs fresh same-session login, serial check, roster selection and
native live-basis validation. Before setup and live Send it closes/drops the
handshake and inventory/login objects, drops request/serial/raw references and
overwrites consumed ctypes Send buffers. The main entry point removes request
fields from its parsed packet; the supervisor drops its packet/request copy
before handoff. The returned session exposes no credential or startup SQL
callback field. Remaining immutable/native copies are not claimed erased.

The callback enqueues bounded byte copies and does no SQL, decoder, IPC or native
work. Serialized child code obtains external current authority after Send buffer
preparation and before native frame dequeue. Later parent reads/current calls
receive a fresh current callback, invoke it synchronously and discard it. The
new lifetime uses the renewable private authority rather than the fixed startup
20-second drive budget. Separate watchdog/reaper ownership handles caller stalls.

Both ends parse original bounded envelopes with the accepted `LiveCodec`.
Parent setup verifies the exact selected channel GUID/raw/window/ordinal and
callback generation derived from the fresh supervisor generation. Child setup
uses the accepted login's private session GUID and newly allocated task/open
request GUIDs. The source parser preserves those exact private identities and
timestamps in `PrivateLiveFrame`; public SQL lease IDs are not frame generation
or task bindings. Original open ACK and the exclusive first-task constraint
establish the qualified route0 context. This is separate from cryptographic
upstream authentication or actual decoded picture acceptance.

`LocalLiveProof` reflects fresh login/serial/channel/native permission basis and
the supported parsed compressed keyframe's framing/timestamp facts. The hardcoded
same-original-session flag is backed by the single fresh original owner and
same accepted login setup; it is not a synthesized public selector. The existing
qualified `legacy_no_group`/explicit selected-channel `lp` source branches are
reused. This review introduces no broader capability or admin-role inference.
Core must receive proof from the original session, and decoded/WebRTC delivery
must independently justify PLAYING.

## Evidence, executed verification and limits

Reviewed sources:

- `services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py`.
- `services/tvt-bridge/src/wso_tvt_bridge/local_live_ipc.py`.
- Changes from baseline in `windows_socket.py` and `windows_socket_worker.py`.
- `tests/contract/test_local_live_provider.py` and the scoped Windows socket test
  fixtures/changes, including two inert originals, close-one isolation, BUSY,
  credential discard, caller-thread authority, queued-byte bounds and receipt drift.
- `docs/integrations/tvt-windows-live-session.md` and relevant existing inventory
  IPC/codec cleanup definitions used by the new slice.

Executed by this reviewer: only the actual-code, five-clock-read renewal probe
above, plus direct source/diff inspection and four-file SHA-256 inventory.
No application/source edits, SDK/native DLL/device calls, credential reads,
database calls, network calls or Git mutations occurred. The author's **343
portable/inert passes**, scoped lint and strict mypy are recorded in the native
reference as author evidence; this reviewer did not rerun or independently claim
those counts. The probe exposes an uncovered clock edge despite that coverage.

Actual safety remains open for sustained read/decode, maximum orphan cleanup,
two-device resource use, loss of service, actual callback quiescence, revoke/
expiry/close/reconnect, codec timing and browser delivery. Vendor allocation
erasure and a live close ACK remain unproved. The 30-second native/SQL lease
policy and 10-second browser heartbeat are source bounds awaiting acceptance.

Priority: fix I1, rerun its inert regression and relevant source tests, refresh
the source receipt for the corrected exact native/core dependencies, then Root
can execute the separately authorized acceptance. Product/deployment questions
remain supported quality mapping, measured concurrency and orphan cleanup limits.

## Dated update log

- 2026-10-04: initial independent native review; **C0/I1/M0, request changes**.
  The renewal edge is reproduced above. No actual SDK/device acceptance advanced.
- 2026-10-04, correction rereview: the native author snapshots the old deadline,
  performs a final old/current deadline check immediately before assignment,
  and shares an `RLock` with the permanent deny latch. No SQL callback runs under
  that lock. The first-frame startup-to-orphan transition uses the same guarded
  replacement. Independent scoped command
  `python -m pytest tests/contract/test_local_live_provider.py -q -k
  'renew_cannot_cross or heartbeat' --tb=short` passed **3 cases, 18 deselected**,
  including the exact five-clock edge, valid/denied renewal and already-expired
  generation. I1 is closed; current bounded native source review is
  **C0/I0/M0, source approved**, with the original finding preserved above.
  The full author native suite, exact source receipt and actual SDK/device/browser
  acceptance remain separate. No native/device/DB/network action occurred here.

### Independent continuous FIFO correction review — 2026-10-04

**Current bounded correction decision: C0/I0/M0, source approved.** This is a
new narrow source correction after Root's failed continuous attempts, not actual
device/browser acceptance. Read the preserved
[first-attempt diagnosis](2026-10-04-windows-live-first-attempt-diagnosis.md) before
reusing these conclusions; refresh the source receipt and executed evidence after
the native author's final source/documentation freeze.

Scope: only `windows_socket_worker.py`'s `CallbackOwner.take_live_batch` and its
`serve_live` call site, two new inert cases in `test_local_live_provider.py`, and
their existing source/parser interfaces. Baseline remains `211d148` plus the
uncommitted correction and concurrent disjoint work. No source edits, Git calls,
SDK/device, credentials, database or private capture access occurred here.

The callback still copies bounded chunks without IPC/SQL/native reentry. The
consumer now drains one existing FIFO snapshot under the callback ownership lock,
decrements its exact byte accounting, and joins the copied parts **outside** that
lock. The same maximum 256 chunks and configured byte cap apply; no quota is
raised. Continuous mode retains its existing 1 MiB callback cap. Other diagnostic
capture/inventory paths still use the unchanged single-chunk `take` method.
No compressed bytes are dropped, replaced or reordered. Callback failure/closed
state remains terminal. External current admission still precedes batch dequeue;
the original bounded transport mux/parser and parent envelope/frame current checks
continue after dequeue. Transport segmentation is not treated as frame identity.

Fresh reviewer command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/contract/test_local_live_provider.py -k 'callback_batch or small_callback_chunks' --tb=short
```

Result: **two passed, 21 deselected, 3.08 seconds**. The FIFO case proves exact
ordered byte join and zero accounting/queue remainder. The real inert `drive` /
`serve_live` / private IPC regression sends a 64 KiB keyframe in 64-byte callback
chunks every 2 ms with the original parent's 20 ms pump cadence. It reaches ACK
and readiness with the exact original payload and leaves zero callback chunks/
bytes; the invented producer/worker settle. This is the previously reproduced
pressure shape, not an actual recorder stream or native DLL execution.

Root now reports the actual child cause as callback chunk saturation, with current
SQL authority/expiry excluded for the diagnosed attempt and all three failed
actual runs cleanly retired. Those are coordinator-supplied observations; this
reviewer did not recover or execute their private evidence. Full author native
checks, refreshed frozen receipt and Root's next ordinary uninstrumented SDK run
remain separate. No continuous CCTV/browser, safety/capacity or release gate
advances merely from this source correction.

Update log: 2026-10-04 — independently reviewed bounded FIFO coalescing correction,
fresh two-case pressure/order execution; C0/I0/M0. Prior expiry review and all
failed actual attempt evidence remain historical authority with their stated limits.
