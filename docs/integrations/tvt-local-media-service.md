# Local TVT media service authority

## R142 equal derived timestamps — 2026-10-06

Read [the frozen R142 source report](../analysis/c10-duplicate-timestamp-report.md)
and the canonical service report before changing this boundary. C10 established
one qualified duplicate derived device timestamp; earlier coarse c9 failures
remain unclassified. The private codec's strict wire frame-index ordering,
selected stream and original identity checks remain unchanged.

The adapter now keeps separate last raw and last presentation PTS. Raw missing,
non-integer, signed-int64 violations and regressions still fail at the existing
early guard. Equality is a candidate for all original media/scope/identity/codec/
configuration validation. Only afterward does the adapter map the first PTS
unchanged and each later PTS to `max(raw, last_mapped + 24)` microseconds. Overflow
fails closed before clock/ordinal commit, without saturation or reset. This
state spans decoder dimension epochs. Equal malformed/foreign candidates fail
their actual later guard; this is the intentional failure-priority change.

Decoder pending/opaque mapping, global output PTS/ordinal, original native/peer
ownership and confirmed predecessor retirement remain strict. R140 failure deltas
compare raw timestamps; observation production/schema is unchanged. The 24µs step
also separates the installed 90kHz conversion across signed zero. Ordinary 100ms
raw advances pass through unchanged when ahead of the mapped clock. No arbitrary
encoded drop, raw timestamp rewrite or native ABI/decoder change is introduced.

Author evidence: 163 focused source/transition/pressure/observation cases and 12
targeted portable decoder cases passed; one real synthetic same-peer VP8/RTP case
received four equal-raw inputs at distinct RTP PTS 0/2/4/6. These are source/local
synthetic gates, not repaired recorder acceptance. C10 exceptionally retired with
one original lease cleanup unconfirmed according to Root; the new source neither
repairs that historical outcome nor grants twelve-tile acceptance. Independent
review and a new immutable approval precede actual diagnostic execution.

## R138 bounded ingress pressure — 2026-10-06

Read after the R137 section below. c8 actual execution replaced the former
format rejection with six measured `ingress_queue/overflow` failures, including
one initial decoder launch without a dimension change. The approximately
1.6–1.7s delay is consistent with the sixteen-frame queue filling during lazy
decoder launch, but c8 did not distinguish count pressure from byte pressure.
Independent inert Windows HEVC samples measured first-decode costs719.8,
1712.8 and1847.6ms versus subsequent0.8–5.1ms; all original decoders settled.
This is a causal timing sample, not a throughput or recorder acceptance claim.

`NativeDecodedSource` now reserves remaining FIFO count/byte credit before
calling `read_frames`. There is one producer; its only concurrent consumer frees
credit. Queued plus returned-but-not-yet-queued input therefore remains inside
the same16-frame/4MiB budget, with no additional drained batch. A full queue
waits on its condition for at most50ms per check; dequeue and Stop notify it.
The next upstream frame can be larger than remaining byte credit, so an empty
bounded read waits for capacity instead of polling repeatedly. Credit released
during that read is recognized before waiting. A pressure episode lasts at
most5s, with the unchanged source/transition/decoder/caller/lease bounds able
to end it earlier. The new fixed diagnostic is `ingress_queue/wait_timeout`.
Current checks and the independent authority/permit thread continue while
waiting. Successful admission or complete queue drainage ends pressure.

The native parent also participates: after current/cancel/expiry/permanent-close
checks, `LiveParentAuthority.pump` leaves the original next IPC message unread
while parsed frames remain queued. Consumer dequeue restores credit. No sequence
is advanced or ACK fabricated during the pause; setup/control/media validation
occurs normally when that same message resumes. Original parent16/4MiB,
callback256 chunks/1MiB, framing,30s orphan, selected-stream, native identity and
retirement limits are unchanged. No SQL, decoder protocol, native callback,
frontend or dependency change is introduced. This native-parent change needs
scoped independent review and a new protected source receipt before execution.

Inert source→original-session→real parent/remote IPC coverage preserved forty
ordered frames through a1.8s blocked first decode, with source16/parent1 queued
and unchanged original decoder. Parent authority/sequence/deferred-invalid
message cases and existing provider tests passed75 cases. Current source and
decoder/WebRTC/worker test counts are recorded in the canonical service report.
No recorder, Chrome, SQL or service run was performed for this repair. The fixed
callback queue can still overflow if the source stalls beyond its actual byte
budget; acceptance under1/4/12 live tiles must measure that residual risk.

## R137 source dimension transitions — 2026-10-06

Baseline: `6436748`, active uncommitted stage-1 worktree after the retired c7
run. This section records a source repair and inert verification; current device
acceptance remains in the canonical service report. Read this section before
changing `native_source.py` and update it after source or execution changes.

`NativeDecodedSource` now enables same-codec dimension changes in its original
adapter. The standalone adapter remains strict by default. Source identity,
generation/channel/task, proof, timestamp, stream validation and byte/dimension
limits are preserved. Its lifetime packet ordinal and source PTS never reset.
Each bounded FIFO entry carries validated random-access status and a format
epoch. A new dimension observation clears queued RGB and starts a five-second
deadline. Further changes cannot extend that deadline before valid current-epoch
RGB is published. The authority stage checks the deadline independently of a
blocked decoder retirement. Existing startup, ingress, permit and lease bounds
still apply.

The serial decoder owner retires the exact old decoder with `close()` followed
by `wait_closed() is True`, retaining it through interruption/retries. Only then
may it allocate a successor, after a current-authority/stop check and a complete
same-codec parameter-set/random-access picture. Validated new-format inter
pictures are omitted only while waiting for that configuration, in FIFO order;
malformed headers, reserved transition pictures, missing key configuration,
codec/identity/PTS changes remain terminal. At most sixteen successor allocations
occur in any rolling sixty seconds; history expires, so no lifetime format cap
is imposed. Encoded FIFO remains sixteen pictures/four MiB and latest RGB one.
Decoder protocol, original native session/socket/task and original peer do not
change. No native reconnect, frontend retry or SQL/TTL change is introduced.

Decoder output must match declared dimensions and original binding. Publication
rejects late old-epoch outputs under the same lock as the observation boundary
and maintains global strictly increasing PTS/ordinals. Stop/revoke/overflow can
fence immediately while old close is pending, but source settlement stays pending
until that exact owner and all source threads settle. Existing worker retirement
therefore cannot certify attached cleanup early.

Executed source evidence: causal RED five failures/two passes; initial combined
source/transition/observation GREEN **92 passed**, then expanded H264/H265
transition selection **21 passed**. Existing decoder/WebRTC/worker selection
**138 passed**, including explicitly selected real isolated Windows H264/HEVC
synthetic codec tests. One additional real local VP8 peer test passed for
352×240 → 1280×720 → 352×240 with increasing received PTS and unchanged peer.
Six changed Python files pass Ruff check/format; two production/helper files pass
strict mypy. No SDK, device, Chrome, service or SQL execution occurred. Review,
new immutable approval and actual 1/4/12-tile sizing are still required.

Updated: **2026-10-04, Asia/Seoul**. Scope: approved M3 contract, SQL admission
and original native-session ownership. Read this document with
[service-analysis.md](../service-analysis.md),
[local service integration](tvt-local-service-integration.md) and
[local device API](tvt-local-device-api.md) before changes; update affected source
and executed evidence afterward. The canonical service report remains the
authority for Root's database, native and browser acceptance outcomes.

Current review correction adds whole-pipeline retirement and the browser started
report below. Portable evidence is **142 passed / 15 guarded SQL skipped**.
Root's earlier **13/13 SQL** acceptance is historical; the expanded `playing`
purpose and two additional SQL cases require a fresh owned-database execution
before current SQL acceptance is claimed.

*Update 2026-10-04:* the owned SQL suite was re-executed with the pooled media
admission engine — **15 passed, 0 skipped** (run `d7dc899c84f1434aa69f5c4c86496d4f`),
owned database removed, source database unchanged. Later 0013 corrections and
their SQL runs are recorded in the [liveness review](../analysis/2026-10-04-local-media-liveness-review.md).

*Update 2026-10-05 (rulings R120/R121, multi-view stage-1 Task 1):* the worker's
hot-path `current`/`view` checks are now answered by a bounded per-lease cache
over a new non-locking SQL read (migration 0014). Statements below that every
check is fresh SQL are amended by the
[hot-path authority gate](#hot-path-authority-gate-r120r121--2026-10-05) section.

## Baseline and verification limits

Source baseline: `211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, active worktree
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
The initial tree was clean. Other agents concurrently own native, WebRTC and
API/frontend work; this report covers the listed contract/core/migration/tests.

The implementing agent made **no database, device or browser calls**, migrated
no existing database and made no Git commits. Portable synthetic tests establish
the source boundaries below. Guarded SQL cases remain skipped until Root enables
the fresh owned database fixture. Historical 8/4 inventory browser readback and
bounded native frame/decode acceptance are described in the canonical report;
they do not establish continuous browser video or media safety here.

## Purpose and architecture

Expose an OWNER's saved, verified local channel through the planned W08 media
path without borrowing cloud account identity or keeping credentials available
for the streaming lifetime. Inventory AVAILABLE is only an enrollment
prerequisite. A new original-session native permission observation is required
before entering NEGOTIATING; browser delivery needs separate codec/framing/timing
proof before PLAYING.

1. API `LocalMediaTicketIssuer.issue(session_digest, connection_id,
   LocalLiveRequest)` creates a purpose-bound ticket under the protected tenant
   transaction. API commits before dispatch.
2. Worker redemption commits the one-use ticket and generated opaque authority
   token binding to a process worker epoch and fresh native generation.
3. `LocalMediaAdmission.open` decrypts the existing encrypted connection envelope
   inside a maximum 20-second startup budget. Its callback receives the fenced
   private channel selection. Credentials and local plaintext references are
   discarded before the transaction commits; the provider must discard its own
   credential request and startup callback references as well.
4. A separate short transaction publishes strict native login/session/serial/
   channel/live-permission facts as an invalidatable grant and a NEGOTIATING
   media lease. No streaming read, decoder or browser delivery runs inside the
   credential transaction.
5. `LocalMediaExecutor` retains only the sealed media authority and credential-free
   original native owner. Bounded SQL authorizes reads and delivery (since
   2026-10-05 through the R120 hot-path gate, at most 100 ms old).
   A default one-second sweep checks authority and synchronously renews the
   unexpired native owner with a fresh callback; native code must discard that
   callback immediately. Provider renewal does not extend SQL lease expiry.
6. API heartbeat renews a current NEGOTIATING/PLAYING lease. One-use purpose-bound
   offer/stop/playing control tickets carry authority to RPC without allowing arbitrary
   actor/channel selectors. Stop immediately sets STOPPING; CLOSED requires
   confirmed original native and attached media-resource cleanup, followed by
   successful SQL retirement.

## Implemented contracts and interfaces

`packages/contracts/src/wso_contracts/tvt/local_media.py` provides
`LocalLiveRequest(store_id, device_id, channel_id, expected_generation,
inventory_revision, stream="main")`, `LocalLiveResponse(lease, request_id)` and
bounded SDP offer/answer request/response models. `main/sub` is a structural
selector; native mapping remains independently source-derived. Initial browser
quality must use the proved default and must not claim unproved quality behavior.

`MediaLease` accepts compatible `LocalMediaOwnerRef`/`LocalDeviceRef` variants.
Local live requires exact tenant/actor/connection/store/channel equality and
positive JavaScript-safe connection/inventory/grant revisions. Local playback
and talk are rejected. Existing cloud lease default JSON serialization omits
the local counters automatically and preserves its original eight fields.

API ports in `local_media_admission.py`:

- `LocalMediaTicketIssuer(session, remaining, ttl_seconds=30).issue(...) -> str`.
- `.issue_control(session_digest, lease_id, purpose="offer"|"stop"|"playing") -> str`.
- `LocalMediaReader(session, remaining=None).get(session_digest, lease_id)` and
  `.heartbeat(...) -> MediaLease`.

Worker ports in `local_media_service.py`:

- `LocalMediaExecutor.start(ticket, deadline_ms, correlation_id, cancel=None)`
  returns `LocalLiveResponse` with NEGOTIATING after native permission proof.
- `.authorize_control(ticket, purpose, deadline_ms) -> UUID` redeems a one-use
  control ticket. `.stop(ticket, deadline_ms, correlation_id)` returns a confirmed
  CLOSED receipt, including the stop/watchdog race via 32 bounded tombstones.
- `.attach_retirement(lease_id, check)` registers exactly one nonblocking check
  under the current original owner's lock before Root creates decoder/peer
  resources. The callback only schedules original asynchronous cleanup and checks
  its retained completion flag. It must not block, perform SQL or authorize
  additional work. Closing, revoked, shutdown and duplicate registration are
  denied. Default `None` preserves native-only sessions.
- Every owned retirement calls native close and the attached check, including
  native cleanup failure. SQL receives `cleanup_confirmed=True` only when both
  report exact `True`. Otherwise the original owner remains retained and SQL stays
  STOPPING; channel/actor/global quota is held until whole-pipeline cleanup.
- `.finish_stop(lease_id, correlation_id)` is worker-private completion after the
  caller derives the ID from the consumed stop ticket and settles the pipeline.
  It uses the retained original/tombstone and never redeems a second ticket.
  The original `.stop` wrapper preserves its response deadline.
- `.current(lease_id)`, `.lease(lease_id)` and `.read_frames(lease_id, max_frames,
  max_bytes, deadline_ms)` use held worker bindings and gate-bounded SQL
  authority (R120: an answer comes from a check begun at most 100 ms earlier).
  Reads allow at most 16 frames and 8 MiB; both type and actual compressed byte
  counts are checked after provider return, then authority is checked again.
- `.playing(lease_id, LocalLiveProof)` requires independent native permission,
  framing, codec support and timing proof. Root's integration waits for a
  purpose-bound browser started report, a connected original peer and actual
  server decoder evidence. Server track delivery or SQL receipt alone cannot
  prove browser decode.
- `.close`, `.sweep`, `.shutdown` own original resources. Uncertain native or SQL
  retirement retains retry ownership and prevents a successful CLOSED response.
- `LocalMediaFailure` aliases the established fixed `LocalDeviceFailure`
  vocabulary and status mapping. Arbitrary provider text is not public output.

The native port is `open_session(credentials, selection, deadline_monotonic,
current, cancel) -> OwnedLocalLiveSession`. The result exposes strict
`LocalLiveProof`, bounded private `read_frames`, synchronous `current` renewal
and idempotent `close() -> bool`. Raw native indices/GUIDs, tokens, process handles,
private compressed frames and credentials never enter public lease JSON.

`LocalLiveStartedRequest(decoded_frames)` accepts only a strict positive integer
at most `2^53-1` and rejects unknown fields. It is a browser observation, not a
permission or decoder grant. A current one-use `playing` ticket is separate from
offer/stop, and expiry, replay, wrong purpose and STOPPING deny its redemption.
Root owns the browser RPC/HTTP wiring and trusted connected/decoded checks.

## SQL authority and lifecycle

Migration `0013_tvt_local_media_leases.py` (described as future when this section
was written; implemented and exercised on 2026-10-04), after `0012`, creates forced-RLS
private leases, native permission grants and control tickets. Runtime roles have
functions-only access. The existing NOLOGIN `wso_tvt_local_owner` reuses its
reviewed foundation metadata privileges; cloud tables and generic secret/job
leases are unchanged.

Every live authorization rechecks READ COMMITTED, exact current OWNER membership,
web session, tenant epoch, active store/link, TVT_DEVICE generation/secret version,
inventory device/revision, active safe channel and matching grant/native generation.
Saved API state remains exact actor/session scoped and requires the current
connection generation and active store/link. Membership, link, store, generation,
tenant epoch, session, secret version and inventory/channel changes create
STOPPING tombstones and invalidate grants. Restoring a removed membership/link
cannot revive the original lease. Heartbeat and PLAYING transitions cannot revive
an expired, invalidated or STOPPING lease.

Default SQL TTL is **30 seconds**; allowed configuration is **5–30 seconds**.
Browser heartbeat guidance is **10 seconds**. Controls expire within 20 seconds
and the media lease's remaining authority. The native owner independently applies
a maximum 30-second orphan renewal horizon. These are implemented source bounds,
**not accepted device-safety or continuous-runtime bounds**. Measure actual orphan
cleanup, loss of service, cancellation, decoder/browser backpressure and resources
before release acceptance. An external scheduler may select monitor interval zero
only if it owns explicit sweep scheduling; normal runtime uses the default monitor.

Expired tickets that were never redeemed can retire as CLOSED because no native
owner was created. Uncertain redeemed/native cleanup stays STOPPING and consumes
capacity.

*Correction 2026-10-05 (final review I1/I2, ruling R116):* a lease that no worker
ever redeemed (`worker_epoch IS NULL`) now becomes `CLOSED` with
`cleanup_confirmed=true` on **every** path that previously set `STOPPING` — the
lifecycle revoke trigger, the API non-live path and the expiry sweep — so a
revocation before redemption no longer strands the channel or a quota slot.
Redeemed leases still go to worker-owned `STOPPING`. No `STOPPING` writer may
touch a `CLOSED` row (closes the API read-path revival race; the stop-control
path is additionally serialized by its `FOR SHARE` grant lock). The revoke
trigger now invalidates only the grants of leases revoked by that firing, skips
unchanged rows, and uses the partial index `local_media_open` on open leases.
Evidence: owned SQL suite **29 passed, 0 skipped** (run
`288e51e5…`, migration hash `be9332c6…`); details in the
[liveness review](../analysis/2026-10-04-local-media-liveness-review.md). A
pre-existing lock-order inversion (close: lease→grant; heartbeat/stop-control:
grant `FOR SHARE`→lease) can deadlock and fails safe as 503 with retry; it is a
production follow-up with the hot-path authority redesign (final review I3). SQL intentionally does not assume a worker crash or elapsed timeout
proves cleanup. Restart/recovery reconciliation needs confirmed native/process
ownership evidence before retiring those rows; this remains an operational risk.
SQL caps are 32 outstanding leases globally, four per actor and one per local
channel. Native process and decoder limits can be lower; production integration
must enforce the reviewed actual native capacity instead of treating SQL caps as
measured multiview support.

## Hot-path authority gate (R120/R121) — 2026-10-05

Scope: multi-view stage-1 Task 1 (final review I3). Source baseline: worktree at
`6436748` on `codex/superlive-web-service` plus the uncommitted Task 1 delta
(ruling R104: implementers do not commit). Cause, from the Phase 0 measurement
in the liveness review section 6c: every hot-path check was a pooled
transaction whose `LIVE` predicate share-locked about ten rows, about 33 checks
per frame, about 665 SQL transactions/s and 200 KB/s of WAL per stream.

Implemented (source exists; executed evidence below):

- `LocalMediaAdmission.current(lease)` and `.view(lease)` are answered by a
  per-lease gate (`LocalMediaAdmission(worker_url, keys, *,
  clock=time.perf_counter)`). A cached answer serves a call only while
  `clock() < valid_until`, where `valid_until = min(s + F, s + (expires_at − UTC
  at s))`, `F = AUTHORITY_FRESHNESS_SECONDS = 0.1` and s is the gate clock
  sampled just before the check's transaction begins. The first call for a lease
  always runs SQL, and nothing is shared between leases. `view` returns the
  independently deep-copied `MediaLease` of that check, including nested owner
  and device scope; callers cannot mutate the cached authority. `current` keeps
  its internal cached-object fast path.
- At most one check per lease is in flight. Other callers wait up to
  `AUTHORITY_WAIT_SECONDS = 5.0` and accept its answer only if it began after
  their own call time minus F; otherwise they check again. A call re-entering
  from the checking thread is denied at once instead of waiting on itself.
  Freshness uses the injected gate clock; the waiter bound uses real monotonic
  time so a stopped test clock cannot keep a waiter blocked.
- The approved slow-success contract uses call-entry timing: a successful
  in-flight observation answers its runner and eligible waiters even if response
  latency crosses the lease expiry. Clock skew can also produce a successful
  returned view whose expiry has already passed. Neither case becomes sticky
  denial solely because the answer is slow. Ordinary cache reuse remains
  clipped to expiry, and the downstream emission permit is also clipped; this
  does not promise freshness or an unexpired lease at return time.
- Denial is sticky per lease: a NULL answer, any error (pool or statement
  timeout, role mismatch, invalid view), a waiter timeout, `close()` during a
  check and `shutdown()`. The caller that ran a failing check still receives the
  fixed 503 mapping. `close()` denies and tombstones before its own SQL; the
  `AUTHORITY_TOMBSTONES = 64` most recently closed tokens are denied without SQL.
  R133 explicitly accepts lifetime retention when a distinct sealed closed token
  is re-queried after eviction from those 64 tombstones: its newly created denied
  entry stays until explicit retirement or admission shutdown. There is no
  configured cap on the authority registry. Its size can grow with the number
  of distinct sealed tokens re-queried during that admission/process lifetime;
  the 64-entry tombstone cap does not bound this retained denial state. The
  tradeoff preserves active sticky denial rather than evicting it to save memory.
  Only already sealed internal leases can reach this path.
  One registry lock and one lock plus condition per lease; no SQL or callback
  runs while any of them is held.
- Migration `0014_tvt_local_media_hot_authority.py` (down revision 0013) adds
  `wso_private.wso_tvt_local_media_live_read`, 0013's `LIVE` predicate with all
  ten `FOR SHARE` clauses removed, and
  `public.wso_tvt_local_media_observe(p_authority text, p_worker uuid, p_native
  uuid) RETURNS jsonb`, 0013's worker view on `live_read` that additionally
  requires NEGOTIATING or PLAYING. Both use 0013's function options and owner
  `wso_tvt_local_owner`, are revoked from every runtime role, and only
  `observe` is executable, by `wso_connection_worker`. Downgrade drops both. Its
  revision id is `0014_tvt_local_media_hot_auth` because the file stem is 34
  characters and `alembic_version.version_num` is `varchar(32)`. 0013 is
  unchanged: state transitions, startup open, API reads/heartbeats and control
  tickets keep the locking `LIVE`.
- `NativeDecodedSource` anchors its emission permit at
  `time.monotonic() − AUTHORITY_FRESHNESS_SECONDS` (see the
  [WebRTC guide](tvt-local-webrtc.md)).

Bounds. R120 amends R106(a) ("every check is a fresh SQL transaction"). t_r is
the commit time of a revoke, stop or expiry:

- No grant to any `current`/`view` call that begins after t_r + 100 ms. This
  bounds native child grants, the parent queue, decoder input and output, and
  publication.
- WebRTC sender: nothing after t_r + 200 ms + one `time.monotonic` tick
  (15.625 ms on this Python), unchanged, because the permit is anchored at
  now − F.
- Overall t_r + 300 ms while check latency stays at or below 200 ms.
- Cost: at most one `observe` check per lease per F, so at most 10/s per stream
  (about 20 transactions/s with pool pre-ping) whatever the packet or frame
  rate. `observe` assigns no transaction ID and takes no row locks.
- R121: a check that overlaps an uncommitted revoke returns the pre-revoke
  state; the first check after the commit denies, so the cache window bounds it.
  Cost if R120 is wrong: native/decoder-side revocation lands up to 100 ms later
  than with per-call SQL.

Executed in this session (2026-10-05, no device, browser or network):

- Media selection (pool, worker, source, WebRTC, service, contracts, RPC, gate,
  migrations): **139 passed** (116 before plus 23 new). Browser-fixture contract
  test: 27 passed.
- Guarded PostgreSQL 17 suite through the controller's runner: RED run
  `63f24e7b4a9f4df78afb487b287dc170` (15 new cases errored: revision 0014
  missing); run `7fd8d1bf289f486cb55ccac7ca27e641` after the migration and before
  the gate (14 passed; the gate end-to-end case failed with 1,000 locking
  `current` calls); GREEN run `6795ab93c07443918ae95d5cad37e460`: **44 passed,
  0 failed, 0 errors, 0 skipped**, owned database removed, source database
  unchanged, zero known private occurrences.
- Ruff check and format clean on the authored files; strict mypy clean on the
  admission module, `native_source.py` and migration 0014.

Not established: device, browser or long-duration playback with the gate, and
the 12–16-stream sizing (later stage-1 tasks). The native codec owner contract
says the authority callback "checks the current owner state every time"; it now
answers from a check at most 100 ms old. No native-owned file changed, and the
later native review (Task 7) must acknowledge that wording change. Five
existing guarded SQL cases that asserted a revocation right after a recent check
now first wait out F, which is the R120 behavior change, not a weaker fence.

## Verification and priorities

Scoped portable verification command:

```powershell
.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_contracts.py tests/tvt_parity/test_local_media_contracts.py tests/tvt_parity/test_local_media_service.py tests/integration/test_local_media_admission.py -q
```

Results are recorded in the dated update log below. Scoped Ruff checks and mypy
of the two contract/two core files also passed. Red observations preceded new
scope validation, negative permission/start/revocation tests, uncertain-cleanup
ownership, stop/watchdog receipt and compressed-byte bound fixes. Existing cloud
contract tests exposed three added-null-field regressions before the serializer
correction. SQL constraints/functions still require actual PostgreSQL execution.

Root must explicitly activate `WSO_TEST_W08_LOCAL_MEDIA_ACCEPTANCE=1`, the
existing W08 local flag and W07 directory owned-database settings. The fixture
uses only its fresh `w07_directory_<uuid>` owned DB, checks identity/comment,
upgrades to 0013 (to 0014 since 2026-10-05), then downgrades to 0012 before the
parent fixture cleanup.
It does not migrate the configured source database. Thirteen SQL cases cover
scope/replay/table access, permission separation, heartbeat/expiry, eight lifecycle
tombstones, purpose/replay/stop and independent PLAYING proof.

Priorities: execute guarded SQL acceptance, independently review the short
credential boundary and original-session native lifetime, then connect and prove
decoder/WebRTC/browser behavior with actual devices. Open product questions remain
the supported default stream mapping, measured simultaneous session capacity,
revocation/orphan release limits, safe restart reconciliation and future actor
delegation. OWNER-only live is implemented; expanding permissions or claiming
parity completion is outside this source slice.

## Dated update log

- 2026-10-04: initial M3 source implementation. Portable runs confirmed scope,
  startup, revocation, stop, uncertain cleanup and byte bounds. Initial related
  final related contract/executor/guarded SQL run after review corrections:
  **134 passed / 13 guarded SQL
  skipped**. Four-file mypy passed; scoped Ruff passed after binding the synchronous
  renewal callback to its exact loop owner.
  Actual SQL/native/browser execution remains Root-owned and unperformed here.
- 2026-10-04: stop/control now accept optional RPC cancellation and preserve the
  original response budget through cleanup. A late confirmed close retires the
  resource but returns a fixed timeout instead of late success. The focused
  regression failed before this fix, then passed; SQL authority was unchanged.
- 2026-10-04, Root-reported actual guarded SQL run
  `891c578a4a1c41829cf84d9f2c3462f1`: **12 passed, one failed, zero skipped**.
  Owned DB cleanup/source preservation and child reaping passed. The failed
  permission assertion counted all grants in the module database; one grant
  belonged to the preceding accepted scope case. The assertion now joins leases
  and counts only the rejected case's exact tenant/connection/session. The
  permission fence and production source are unchanged by that correction.
  Corrected full 13-case SQL rerun was Root-owned; its later result is preserved
  below. Preserve the earlier
  Root run with 13 setup failures when PostgreSQL was stopped; no owned database
  was created by that run and Root restarted the existing private PostgreSQL 17
  cluster without resetting schema. These are coordinator-reported execution
  facts, not independently executed by this implementing agent.
- 2026-10-04, Root-reported corrected actual guarded SQL run
  `a1056ae425954233abb0160c235afb5c`: **13 passed, zero skipped/errors/failures**.
  Root confirmed original child reaping, owned database cleanup, source
  preservation and zero known private-value hits. Preserve the preceding runs.
  The cancellation/cleanup corrections at that stage affected Python lifetime
  ownership and did not change SQL. The later `playing` purpose below changes
  migration source and requires its fresh acceptance; native/browser acceptance
  remains separate.
- 2026-10-04, independent core review corrections: the original C0/I2/M0 report
  is retained in [the independent review](../analysis/2026-10-04-local-media-core-review.md).
  Executor shutdown now retries failed-start retirement and returns `bool`:
  `False` preserves unresolved native/SQL/inflight/monitor ownership; `True`
  requires settled ownership. Admission keeps the exact sealed authority after
  uncertain redemption plus failed close; `retry_cleanup()` makes at most four
  fair independent short attempts per sweep. Admission shutdown returns false
  and keeps its engine/bindings when cleanup remains pending. Three new
  regressions failed before the corrections and pass afterward. Independent
  rereview of these corrections remains Root-owned.
- 2026-10-04: `executor.proof(lease_id)` exposes the immutable proof from the
  current original native session to the private packet/decoder adapter. It
  rechecks media authority and does not construct facts from public lease IDs.
  Actual frame identity supplies decoder generation/session/channel/task binding;
  public lease UUIDs are not substituted for those private fields.
- 2026-10-04, concurrent cleanup correction: independent rereview reproduced an
  external sweep holding an original owner in a local retirement batch while
  shutdown incorrectly returned true. Retirement now moves exact bindings into
  an executor-owned in-flight map under the ownership lock; native/SQL close runs
  outside that lock, and completion or interruption atomically settles/requeues
  each original owner. Shutdown requires both queued and in-flight retirement
  to be empty. The Event/Thread regression first failed with `shutdown=True`
  during blocked close, then passed with false while in-flight and true only
  after confirmed recovery. No SQL schema, native port or proof change occurred;
  Root's 13/13 SQL acceptance remains historical actual evidence.
- 2026-10-04, whole-pipeline review correction: an exactly-once retirement hook
  gates native plus original peer/source/decoder cleanup before SQL CLOSED and
  quota release. Native failure still invokes the hook; hook false/exception
  keeps STOPPING and retains the owner for retry. Stop authorization is split
  from private `finish_stop`, avoiding second redemption. A strict browser started
  counter and one-use `playing` control purpose are implemented; the counter
  grants no authority and Root must check actual connected/decoded facts.
  New attach/close race, cleanup barrier, wrong/replayed/late purpose and strict
  counter tests were observed failing before implementation. Final focused
  **142 passed / 15 SQL skipped**, scoped Ruff and four-file mypy passed.
  Fifteen guarded SQL cases now include the original thirteen plus barrier and
  playing-purpose cases. Fresh SQL execution, correction review and current
  native/browser acceptance remain Root-owned; no DB/device/Git call occurred here.

- 2026-10-04: a causal attach/shutdown crossing test also failed before correction. Current authority now fences executor shutdown before and after its SQL query; attachment rechecks the exact owned entry and shutdown flag before storing the hook. No SQL runs under the global executor ownership lock; the per-owner attachment lock intentionally serializes its bounded current check against close. This prevents a late registration from enabling resource creation after shutdown begins. Final portable count is 142 passed / 15 gated SQL skipped.
- 2026-10-05, multi-view stage-1 Task 1 (R120/R121): per-lease hot-path
  authority gate in `LocalMediaAdmission`, migration 0014 `observe`/`live_read`
  and permit anchoring at now − F. Media selection 139 passed; guarded SQL run
  `6795ab93c07443918ae95d5cad37e460`: 44 passed with zero failed, errored or
  skipped cases. Bounds and limits are in the hot-path authority gate section.
  No device, browser or Git operation occurred; the change is uncommitted.
