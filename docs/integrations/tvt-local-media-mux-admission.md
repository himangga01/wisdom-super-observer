# Shared recorder SQL admission

Date: **2026-10-06 (Asia/Seoul)**. Source baseline: HEAD `6436748`, retained
Stage 1 changes and reviewed Stage 2 Tasks 1–4; Task 5 starting tree supplied by
Root was `4d1561480a3651acfb009b71f76a556d69f25b3c`. Approved plan `122796f6`,
design `036908e3`. This is the Task 5 implementation and owned PostgreSQL
verification record. The R1 base and R155–R163 ports passed independent review;
the latest R186 negotiation correction below **awaits its own scoped review**. It is not
recorder, native SDK, browser, or twelve-camera acceptance.

Read this guide with [service analysis](../service-analysis.md), the
[existing media authority guide](tvt-local-media-service.md), the
[mux wire/type guide](tvt-local-live-mux-codec.md), and the approved
[Stage 2 design](../superpowers/specs/2026-10-06-multiview-stage2-shared-recorder-design.md)
before changing admission or its consumers. Refresh affected implementation and
actual evidence after changes; retain earlier failed runs and their limits.
Root owns the canonical service report and AGENTS handoff.

## R1 correction — refresh denial and terminal wall state

2026-10-06: independent R0 review found **C0/I2/M0** in candidate `e1fb613d`.
The initial passing cases below remain valid for their assertions; they did not
cover denied refresh overriding a cached master or complete wall finalization.
R1 fixed both findings and subsequently passed fresh scoped independent review
at tree `57e5a0a06698ceb7bf490cd8250c8bee3d582c69`, C0/I0/M0.

Every failed refresh observation now retires the exact registered grant and
applies the original's denial policy before propagating the existing failure
mapping. This includes NULL, SQL exceptions, entry expiry, and expiry during the
query. Cached transport and viewer answers for that original immediately deny;
another master remains independent. A previously superseded closed grant is
still excluded from a new group fence. Successful refresh also checks the
original's denial state at replacement commit. Pending focus remains deliberately
nonrefreshable, and the qualified slow-success current/permit contract is unchanged.

New private `wso_tvt_local_media_finalize_wall(uuid)` acquires the existing short
mutation lock and the exact wall row lock. It closes only a STOPPING wall with
all masters CLOSED/confirmed, all physical slots CLOSED, all wall viewer leases
CLOSED/confirmed with their required local/native settlement, and no pending or
MAIN_ACTIVE focus reference. It cannot confirm native cleanup or infer it from
expiry. It is invoked after viewer, base-original, dedicated-original and focus
settlement, after empty/already-retired Stop All, and on already-closed viewer or
epoch retry paths. Other walls and legacy leases without that wall ID do not
participate. The same fixed owner/search-path/execute-denial rules protect this
private helper; application and worker roles cannot invoke it directly.

Four pure refresh tests first failed with cached master True. Five causal owned
SQL cases then produced **4 failures / 1 pass** in run
`d34e49b4eba645fda9348514ba77ced3`; the existing local-first/native-last path was
the passing control. After correction, the same five SQL cases passed in
`47d14fe7c7b3438281d4730b616018c8`. They assert both receipt orders, dedicated main
settling last, empty/already-retired walls, rejection of new wall creation while
cleanup is incomplete, and successful creation after complete closure.

Final R1 new selection: **34 passed (23 DB-fixture cases and 11 pure cases)**,
run `e8a9ab2bb8bb4c6ba6290433c30a89a5`. Separate affected legacy selection:
**19 passed**, run `c3f4013a405541929daba8f68ba8796c`. Root verified zero
errors/skips, original child reaped, owned database removed, source database and
source pins unchanged, and zero known private occurrences for all four R1 runs.
The expected-RED wrapper's success meant correct failure/cleanup evidence,
not that its four failing tests passed. Final scoped Ruff/format4, mypy1 and
offline migration3 checks passed. No hardware or broader suite was executed.

| R1 frozen file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `0bb53a08cf7103de8e5575e43d081507b612e8eb16cdc415935f12babf42e4d0` |
| `local_media_mux_admission.py` | `177486222ad40923d95e708ff2e618fc9ed2beb161b45a444ba7ffd2a94399a0` |
| `test_local_media_mux_admission.py` | `30eea141d1a5ddec9bd633d2a626d8d599ca7b1029216f20a1f9522ba6f343a1` |
| `test_local_media_mux_migrations.py` (unchanged) | `3e5e4a7832fb10e1e86fa8b4c790400ff8353a47a0c78f43ea3789b027ec0385` |

## Intertask selection and control ports — R155–R163

2026-10-06: coordinator integration required short selection and purpose-ticket
ports beyond the accepted R1 base. This scoped refinement preserves completed
Task 5 evidence and does not restart it. Exact callable contracts are:

| Worker facade | Result |
| --- | --- |
| `prepare_viewer(lease, *, budget)` | `LocalMediaChannel`, declaring actual `sub` or `main` stream |
| `prepare_dedicated(lease, *, budget)` | `(LocalDeviceCredentials, LocalMediaChannel)` |
| `redeem_wall_stop(ticket, *, budget)` | authenticated wall UUID |
| `redeem_wall_heartbeat(ticket, *, budget)` | authenticated wall UUID |
| `redeem_focus_settle(ticket, *, budget)` | `(focus_id, wall_id, "CANCELLED" | "FAILED")` |
| `focus_identity(grant)` | `(focus_id, wall_id)` from the exact retained grant |

New `viewer_selection(AUTH)` is worker-only and projects channel fields only.
It does not call legacy `media_use`, decrypt secrets, or change LOGIN. Sub
selection can precede master reservation. Main selection additionally validates
the exact current FORWARD pending focus, its master, worker, wall, channel and
full source/secret scope. A registered main in CLAIMED may be selected again for
the post-decryption recheck, without another claim or wider stream authority.
Selection queries use locking current predicates and return their checkout
before returning the selected channel. Only exact lease objects returned by
this admission's `redeem` are accepted; copies and known-denied leases fail
before SQL, including a known denial of their registered master.

The dedicated sequence is: obtain channel selection, prepare inert custody
issuers, register both dedicated issuers, call `prepare_dedicated`, then start
native work outside SQL. Preparation uses the existing legacy `media_use`
LOGIN→CLAIMED transition exactly once, under a bounded startup permit. After
the claim transaction ends it decrypts the exact registered secret UUID, then
rechecks custody, channel/focus/current SQL authority, local denial, cancellation
and caller deadline before returning credentials. No callback/native operation
is wrapped inside legacy `open` by this new path.

Application `wall_control_issue(..., "WALL_HEARTBEAT")` performs the validated
wall heartbeat in the same transaction, then issues a purpose ticket bounded by
twenty seconds, renewed wall expiry and the web session's expiry. Dedicated
worker `wall_heartbeat_redeem(ticket, worker)` rechecks current wall and every
retained master/slot but does not extend TTLs. Existing stop redemption remains
STOP-only; wrong-purpose attempts do not consume each other's tickets. After
heartbeat redemption the coordinator must replace its exact immutable grant
references before reporting renewal success. Pending focus deadlines remain
nonrenewable.

Application-only `focus_read(session, id)` returns exactly public reference ID,
wall ID, source lease ID, direction, state and expiry under current actor/session/
tenant scope. It exposes no authority token. `settle_focus` remains void; Task 9
must use scoped readback for its response rather than infer success from a no-op.
Clients can request only CANCELLED/FAILED controls, never ATTACHED or native
cleanup. `focus_identity` permits expired lookup solely for cleanup and neither
renews a deadline nor grants publication authority.

Causal owned run `4c45f95a8a79470b93020c84c06ba08d` recorded **11 missing-port
assertion failures**, zero errors/skips, before implementation. Corrected scoped
run `d127c00f02a74e5ab740f43aded611a9` passed **11 cases: ten DB-fixture cases and
one pure identity case**. Root verified original child reaped, owned DB removed,
source DB/source pins unchanged and zero known private occurrences for both.
The first wrapper's expected-RED success is not a passing test result. Direct
offline signature/identity REDs were followed by four focused passes; Ruff4,
format4 and mypy1 passed. No unchanged full suite or new hardware execution was
performed in this refinement; the earlier 34/19 results remain dated R1 evidence.

| Ports candidate file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `3fd5d6387b30768da232c85496641c7517c2703a45137bed7693d472015537c4` |
| `local_media_mux_admission.py` | `abcdb028cdf84caabc05f9fcb3fd8df22ca7efdbcc5b7e5ff1922f6c7cf51154` |
| `test_local_media_mux_admission.py` | `63df6b35c7d947ca8033bcca7b02e25b6afed6096553d335befb783fbb503c82` |
| `test_local_media_mux_migrations.py` | `8f8385c80fb960b03009fdaf78e163a415081cd0de8d4d166707b4959e09f34d` |

The ports subsequently passed scoped review at tree `3bb5b9c8`, C0/I0/M0;
subsequent coordinator/API integration remained required.
R164 downstream frame-credit release belongs to coordinator/provider work; this
refinement does not change native, codec, global types or credit ownership.

## R166 — authoritative focus settlement

2026-10-06: Task 6 review I3 found that a void SQL no-op was being treated as
successful MAIN_ACTIVE attachment. This integration correction supersedes the
earlier void worker settlement contract; application `focus_read` remains the
public scoped readback.

`settle_focus(grant, transition, *, viewer=None) -> FocusSettlement` now validates
an actual SQL transition acknowledgement. The local frozen result contains
`focus_id`, `wall_id`, actual `state`, `attached_viewer`, and a private issuer
identity. SQL supplies stored full scope, source lease, direction, original
master/native identity and target; the facade compares them with the exact
retained FocusGrant and records the exact issued acknowledgement. A declined,
expired or wrong-target ATTACHED result raises and does not close the pending
record. A successful but late acknowledgement remains usable for honest cleanup.

`focus_settlement_current(grant, acknowledgement, transition, *, viewer=None)`
returns bool. It requires the exact retained acknowledgement and issuer, then
performs bounded read-only worker SQL observation of actual state/target/scope.
Active acknowledgements also require current master and target lease authority;
the SQL helper rereads the reference state after those predicates. RETURN or
Stop invalidates the old MAIN_ACTIVE acknowledgement. Failed genuine observations
remove that acknowledgement's reusable validation; copied acknowledgements do
not invalidate the original. This observer assigns no XID or tuple locks and
does not renew expiry. Its read is not an end-to-end revocation SLA.

The coordinator must call this observer outside its registry lock and recheck
its exact pending deadline and retained target after the call before publishing
a local transfer. An old pending deadline is never extended by SQL acknowledgement.
Expired-grant lookup is permitted for acknowledgement validation/cleanup, not for
new ATTACHED admission or renewal.

Internal CANCELLED/FAILED/EXPIRED cleanup accepts expired retained grants and
acknowledges existing terminal CANCELLED/FAILED/EXPIRED/CONSUMED state idempotently.
It reports the actual terminal state, rather than pretending a different requested
state was written. A locally rejected late MAIN_ACTIVE/ATTACHED can be cancelled:
the reference loses retention authority and associated redeemed target leases
become STOPPING/invalidated with no cleanup confirmation. Their exact local and
native receipts still govern CLOSED. Never-redeemed tickets retain the existing
no-worker closure rule. Public settlement controls remain pending-only and cannot
request ATTACHED/native cleanup. These SQL facts do not prove physical retirement.

Root-owned causal run `a9e7d08b667f4e5892685f49b1a93c22` had **five behavioral
failures plus one test-fixture CHECK failure**, not six reached behavior assertions.
After implementation, `b46668866d664f3fa118dd108bd59af6` passed five cases but
still failed that fixture: two volatile clock reads made an intended twenty-second
interval exceed its strict limit by a small delta. Only the test was corrected
to one `statement_timestamp()` anchor. Targeted expiry run
`e51036cc4a6d41a3bb06eaae41508412` passed one; final focused run
`ca91f6593dc44fd1b4d33e65e8753fff` passed **all six DB-fixture cases**.
All runs had zero errors/skips, original child reaped, owned DB removed, source
DB/source pins unchanged and no known private occurrences in Root's receipts.
The initial expected-RED wrapper's success did not mean its tests passed.

Coverage includes declined/expired target admission, actual current acknowledgement
after RETURN/Stop, exact-copy rejection, read-only SQL, expired terminal retries,
late cancellation and dedicated cleanup remaining unconfirmed until both receipts.
Scoped Ruff/format3, mypy1 and unchanged offline migration3 passed. Earlier broad
results remain tied to their earlier source hashes; no broad suite/native run was
repeated for this correction.

| R166 frozen file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `595cafde79668379de4772e05db88368cae8a0c4c576dafad58848231ecb395c` |
| `local_media_mux_admission.py` | `4408fc7a51576dc4fad581b325305f55003bb51f5f59e521fd30b0781c6ae91c` |
| `test_local_media_mux_admission.py` | `f380bc0c1a2191e3ad83eaf17afb29deb0c0746f95db0bc5a3db312c359e1a52` |
| `test_local_media_mux_migrations.py` (unchanged) | `8f8385c80fb960b03009fdaf78e163a415081cd0de8d4d166707b4959e09f34d` |

Fresh scoped SQL/coordinator review remains necessary. No new native, recorder,
browser, memory-sizing or twelve-camera acceptance is implied.

## R176 — exact reservation recovery

2026-10-06: the recovery ports extend the completed admission work from SQL
`70f65859` / admission `4408fc7a`, using the ratified proposal `f61d2013`.
Core/coordinator integration and fresh security/custody review remain pending.

`begin_master_attempt(viewer)` is a local non-SQL factory. Core retains the exact
opaque handle before `reserve_master(..., attempt=handle)`; omitted `attempt`
preserves existing facade callers. One attempt binds one exact issued lease and
can dispatch once. Private admission records retain separate operation and
creator authorities, operation-native UUID, full scope, invocation phase and
original result. Credential-free SQL reads the original stored lease scope;
reserve independently validates current scope before mutation. An in-flight
original call or failed/mismatched lookup remains unresolved and charged.

The sixth private table, `tvt_local_media_master_operations`, journals immutable
RESERVED or ABSENT outcomes under the same mutation fence as reserve. It binds
the original lease/authority digest, worker, operation-native UUID, full scope,
canonical master and creator/follower role. Resolver cannot infer ABSENT from a
bare SELECT: it writes the terminal tombstone under that fence. A delayed reserve
with the same operation key is then refused. A follower never substitutes its
requested nonce/authority for the canonical creator's identity; a missing local
canonical creator must be resolved first. Read-only private scope is not renewed
startup authority, and newly recovered reservation objects are cleanup-only.

The journal has a hard **65,536-entry global ceiling**, failing BUSY for new
entries without deleting/reusing old keys. There is no TTL eviction. This is an
operational capacity limit: long-lived production maintenance requires a reviewed
exact worker/SQL quiescence policy before any fence can be retired. No such
maintenance or automatic database cleanup policy is implemented here.

| Recovery port | Result / meaning |
| --- | --- |
| `resolve_master_attempt(attempt, *, budget)` | exact cached `MasterAttemptResolution` or unresolved `None` |
| `master_resolution_current(attempt, resolution)` | pure exact-result/issuer/input check |
| `claim_unstarted_master(reservation)` | exclusive cleanup-only `UnstartedMasterClaim` |
| `register_unstarted_original(claim, issuer, custody)` | retains the one actual prepared empty original's issuer/custody |
| `finish_unstarted_master(claim, receipt, *, budget)` | `UnstartedMasterClosure(master_id, lease_ids)` |
| `unstarted_master_closed(claim, closure)` | pure exact closure check |
| `finish_absent_attempt(attempt, resolution, *, budget)` | separate no-master local `UnadoptedViewerClosure` |
| `absent_attempt_closed(attempt, resolution, closure)` | pure exact ABSENT/local-closure composition check |
| `finish_unadopted_follower(viewer, reservation, *, budget)` | local-only `UnadoptedViewerClosure` preserving the creator |
| `unadopted_viewer_closed(viewer, reservation, closure)` | pure exact follower closure check |

`MasterAttemptResolution.outcome` is ABSENT or RESERVED and carries the original
reservation only for RESERVED. Closure classes and claims are local opaque
factory results with retained issuer identity. `UnadoptedViewerClosure.master_id`
is `None` for ABSENT; no master is invented. ABSENT alone is neither a local nor
native receipt. Core must complete and verify its separate local closure before
removing that operation charge.

Normal login/registration/slot/viewer acquisition marks its attempt under the
admission lock before SQL or supplier callbacks. Cleanup claim refuses prior
acquisition/original registration and prevents normal use. The caller prepares
the existing provider's empty original with its retained original budget,
registers that original, never calls start/login, closes it and supplies only its
own exact NOT_CREATED receipt. The facade compares the retained issued receipt
by identity and checks master/worker/native binding before SQL completion.

SQL separately rejects claimed login, proof, wire identity, any physical slot,
registered viewer, permission proof or active/acquired lease. Eligibility locks
the relevant leases so legacy claim cannot race the check. Only eligible
never-admitted leases close under that composed empty-original proof. Follower
cleanup instead fences just its exact unadopted lease and leaves native settlement,
the live creator and sibling slots untouched. Existing actual local/native
receipt paths remain required once acquisition was attempted.

Root run `c57b7251b0a74f12bd7930bc957a965b` recorded seven missing-port failures
before implementation. Run `01cdee6cb79d448290f8ea06a494f78c` passed **eight focused
cases: seven DB-fixture cases and one pure identity/in-flight case**. Both had
zero errors/skips; Root verified original child reaped, owned DB removed, source
DB/source pins unchanged and zero known private occurrences. Ruff/format3,
mypy1, offline migration3 and the one pure case passed. The added pure case is
verification after implementation, not retroactively claimed RED.

Executed coverage includes Stop of an unused creator with exact synthetic
NOT_CREATED issuer identity, prior login/registration rejection, lost creator
and one follower commit response, permanent ABSENT blocking a delayed replay,
separate absent-lease close, unknown lookup remaining charged, and unadopted
follower closure preserving a live creator. These tests do not execute the real
empty provider, certify native custody, or prove all Core concurrent schedules;
the required original-budget/provider composition belongs to subsequent Core
integration and review. No broad unchanged suite or hardware test was rerun.

| R176 frozen file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `1704d4e74f948a6ea1fcd0443e1b800aabab841b04a7c0e5edc83bb47d5040e5` |
| `local_media_mux_admission.py` | `9e5177706379ad7005ebb919fb60bfce302115814167c81564b2337c6ec08b05` |
| `test_local_media_mux_admission.py` | `f94918804149591f03b383351d49bf05171567458a0b03b50ebd5ecf7db9395c` |
| `test_local_media_mux_migrations.py` (unchanged) | `8f8385c80fb960b03009fdaf78e163a415081cd0de8d4d166707b4959e09f34d` |

## R176 R1 — follower pairing and persistent claim history

2026-10-06: review `r176-sql-review-r0.md` found C0/I2/M0 in the initial recovery
candidate. Its earlier eight passes remain evidence for their assertions, not
for these previously untested call paths. This R1 correction awaits fresh review.

Follower closure now retains the exact attempt that issued each follower
reservation. The attempt, its original lease, returned reservation, issuer and
full scope must match before any local fence, supplier inspection or SQL call.
The relationship is rechecked after callbacks/SQL and by the pure closure
validator. SQL also receives the original operation authority and operation-native
UUID and matches that exact journal row, viewer-authority digest, worker, lease,
scope and canonical master. Two genuine followers on one master cannot be
cross-paired; rejecting a crossed pair does not fence either valid lease.

Additive `mux_acquisition_started` is monotonic for shared leases. The existing
0016 BEFORE UPDATE guard sets it before CLAIMED/active state or slot/registration
can be published and preserves it after Stop/revocation overwrites visible state.
All three recovery SQL closures require that durable evidence to remain false.
Thus a prior legacy `media_use` claim cannot become "never acquired" simply by
moving to STOPPING before a permission proof exists. The inherited facade `open`
also records acquisition locally before its SQL/starter callback, closing the
same-process cleanup-claim race. Genuine nonshared legacy execution delegates to
the original path; its rows do not gain the shared marker. Historical 0013–0015
are unchanged.

Two pure crossed-pair regressions failed before the fix and passed afterward.
Root-owned run `f5fa05724a644b2bb1b7efbe4758c618` recorded **10 failures** before
implementation: two pure pairing cases and eight DB-fixture claim/history/race
cases. Corrected run `6d7a3f56e767457781c97e464705675c` passed the same ten cases.
Separate positive-control run `26998c4b0ae6447a8d146107089dfd46` passed four DB
cases: genuine nonshared open/activate/close, unused creator cleanup, ABSENT
local closure and live-creator follower closure. These are separate selections,
not a fourteen-case full-suite run.

Root verified zero errors/skips, original child reaped, owned DB removed,
source DB/source pins unchanged and zero known private occurrences for all three
runs. Claim-only probes counted returned rows without projecting credential
values; session callbacks were synthetic. Scoped Ruff/format3, mypy1, pure2 and
offline migration3 passed. No real native or broad unchanged suite was run.

| R176 R1 frozen file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `50ac053c8da9c2b8966aca5e8baf59ecd1aff01ea54510c67f0089fcedd3a065` |
| `local_media_mux_admission.py` | `98a5d4f0562301c743349f70d27321ffa601871b660ee7d8fa44c90e3c9342e9` |
| `test_local_media_mux_admission.py` | `be5b6c7a3d7e35ad745b284adc804fec008dc6f8007c7717f1d37e43fdf3646a` |

The operation-journal capacity/quiescence limits and subsequent Core/provider
composition requirements above remain. Acquired owners require their actual
receipts; this correction does not provide a shortcut for them.

## R186 — initial binding proof permits negotiation

2026-10-06: composed startup exposed a phase mismatch: fresh provider binding
proof supplies login, same-original session, serial, channel and live-permission
facts, while codec/framing/timing facts follow validated frames. Requiring full
delivery before first admitted read prevented genuine initial negotiation.

Only two production checks changed: `SqlMuxAdmission.activate_viewer` validates
with `delivery=False`, and 0016 `VIEWER_ACTIVATE` invokes the existing SQL proof
validator with `false`. Both still require the five exact initial binding flags,
the retained viewer grant/registration and current scoped authority. They still
return NEGOTIATING. Supplied codec/framing/timing fields are preserved unchanged;
none is fabricated as True. Actual PLAYING and frame/output/decoder delivery
validation remain strict and unchanged. No R176 journal, acquisition marker or
cleanup semantics changed.

Causal owned run `047904801f1647db9dd0d5184f698223` produced 3 failures / 8 passes:
two real initial-phase failures at the facade and SQL boundaries, plus one test
call-contract error. The new test had incorrectly supplied `budget=` to inherited
`playing(lease, proof)`; its wrapper mapped that TypeError to unavailable. The
test was corrected to the real signature and now requires the precise protocol
failure/SQLSTATE 22023 for incomplete delivery. Production PLAYING was not changed.
A separate pure initial-payload test failed before the two-line fix and then
passed, proving that the unchanged initial proof reaches SQL.

Final Root-owned run `80402c4a64fa4f1c893d1c90f31d3dea` passed **13 cases: twelve
DB-fixture cases and one pure case**. It covers initial NEGOTIATING at both
boundaries, all five missing binding flags, strict pre-delivery PLAYING rejection,
complete synthetic delivery-payload success, expired/revoked/copied grant denial,
and the existing genuine nonshared legacy control. Root verified zero errors/
skips, original child reaped, owned DB removed, source DB/source pins unchanged
and zero known private occurrences. Ruff/format3 and mypy1 passed.

These are SQL phase and protected-facade tests using controlled registered
synthetic originals. The complete delivery payload is test data, not evidence of
actual validated/decoded recorder frames. Real provider/Core/media composition
and output proof remain their owners' gates; no native/recorder/Chrome execution
or broader suite was performed here.

| R186 frozen file | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `64e28f2008e548f33802afb821635e000536d4b9354c4ea931711f979a57aa92` |
| `local_media_mux_admission.py` | `0a4162c6866d0d6f29f504ff5b185452b2964a7b1cda3ca1cc1b73f1cdc0f797` |
| `test_local_media_mux_admission.py` | `4436fbbd0ae3454e87f02d1e40d2f50223705ffd0397c9eae21145da88e0b3c3` |

Fresh scoped review remains required before composed runtime acceptance.

## Purpose and structure

### Task 9 scoped wall readback and session clipping — 2026-10-06

R172 adds application-only
`public.wso_tvt_local_media_wall_view(p_session text,p_wall uuid) -> jsonb`.
Its exact public row contains `id`, `state`, and `expires_at`; the API derives
`tenant_id` from the authenticated OWNER scope. The function checks the current
tenant epoch, OWNER membership, same actor and web-session digest, and a current
unrevoked web session. It observes ACTIVE, STOPPING, or CLOSED metadata without
renewal, mutations, or tuple locks. A terminal wall view does not establish a
native receipt. Existing `wall_read(..., true)` remains the live heartbeat path
with the existing current wall, master and retained-slot predicates.

Wall issue and heartbeat now clip the stored expiry with the actual SQL web
session expiry. The API supplies the fixed thirty-second wall TTL; client JSON
supplies no expiry. API focus deadlines remain server-derived, at most twenty
seconds and clipped to the authenticated session expiry. The application focus
response uses `focus_read(session,id)` plus existing scoped `media_read` of its
source lease for public connection/channel selectors, including a retired
source. MAIN_ACTIVE maps to public ACTIVE; terminal references map to public
CLOSED without reporting viewer or original cleanup completion.

Root-owned causal R172 run `639193c385484b7086137add4be18b7c` recorded eight
failures: six missing-readback assertions and two expiry-clipping assertions,
with zero errors/skips. Candidate run `e5d2be1d4e6b40ac86141ea903fa114c`
recorded seven passes and one fixture CHECK failure before the expiry readback:
the synthetic expired session had an expiry earlier than its creation time.
Only the test was corrected to use one statement timestamp for an earlier
creation time and expired expiry; no production constraint changed. The
targeted selector `b3fd185c7522470aaaa6d682b24dd728` collected two cases, both
passing (its base test name contains “session”); final selection
`08804520827c46648c6d649dda9a2305` passed all eight. Root reported zero
errors/skips, reaped original children, removed owned databases, unchanged source
database/source pins, and zero known private occurrences for these runs.

Read-only qualification: existing authenticated application tenant contexts
already assign a transaction ID, and `wso_connection_owner` uses `txid_current`.
The new observer adds no transaction writes or tuple locks and preserves the
preexisting XID. These tests do not claim that an authenticated application
transaction has no XID.

R172 source identities: migration
`70f658593e6649b5a25fcf389daa289d122e63cc2611f84305662dd92cd46e61`;
final integration test
`02016b47dc5738794dc3d84b5fe0f11f52635af69b0eb8743dd0eb353ac9fa3e`.
API/RPC source review and shared hardware/browser acceptance are separate gates.

`0016_tvt_device_media_epochs.py` adds walls, device masters, immutable physical
slots, focus references, and purpose-specific control tickets. Existing leases
receive nullable mux linkage plus explicit local/native cleanup state. All five
base tables and the R176 operation journal use the existing fixed NOLOGIN owner, ENABLE/FORCE RLS, and no runtime
direct table privileges. New SECURITY DEFINER functions use `search_path=pg_catalog`,
a three-second lock timeout, and explicit application or connection-worker grants.

Applied migrations 0013–0015, their function definitions and ACLs are unchanged.
The existing active-channel unique index, separate non-CLOSED issue check,
actor 16/global 64 limits, and legacy cleanup meaning remain. New admission adds
two non-CLOSED base masters, one registered dedicated main original, and sixteen
non-CLOSED physical slots. STOPPING, parked, and unresolved resources remain
charged. A closed viewer does not imply that its upstream task disappeared.

`SqlMuxAdmission` uses the existing 8+8 pool and eight startup permits. Creator
reservation, encrypted login lookup, and activation are short transactions.
Decryption and original producer/native work happen after checkout release.
Startup permits remain held across original construction and are released on
activation or confirmed epoch settlement. Lock waiting polls caller cancellation
and the bounded startup deadline. A lost response after a committed reservation
retains the exact pending authority/native nonce; it cannot dispose or create a
replacement original. Automatic recovery of those pending records is not claimed.

Mutations use new short locking predicates, including each retained channel;
observers use non-locking predicates and do not assign an XID. New lifecycle
triggers independently inspect parked slots and stop their master and attached
viewers when required scope is revoked. Historical lifecycle functions are not
replaced.

## Exact authority and original provenance

The complete scope includes tenant and tenant epoch, actor, web-session digest,
wall, store, device, connection and generation, secret-version UUID, inventory
revision, and worker epoch. Inventory source-session binding must match the
current actor's exact web session. R150 corrected the original planned integer
secret version to the existing database's UUID; no lossy conversion or surrogate
version was introduced. SQL native-generation UUID and actual wire epoch integer
remain distinct.

Only the admission factory creates `TransportGrant`, `SlotRetentionGrant`,
`ViewerGrant`, and pending `FocusGrant` instances. It retains their exact object
identity, private issuer identity, purpose, SQL authority and original row keys.
A matching dataclass copy or known seal is insufficient. Native binding similarly
requires the exact `OriginalMuxBinding` returned by the one registered original
issuer, matching scope/master/native/channel/epoch, and a post-callback provenance
check. Master activation consumes that binding's exact login proof object;
channel permission/open/frame proof remains a separate viewer activation check.

The original creator reservation remains stable. R154 followers receive a
different sealed reservation with `creator=False`, the same master/scope/native
identity and retained transport grant. Followers cannot prepare login, register
another original issuer, or activate the master. The coordinator must wait on
the existing constructor result.

Current checks preserve the qualified R120 contract: cache freshness is anchored
at SQL check start, not completion. Slow success may answer its eligible call
while its reusable cache is already expired. Observed denial is sticky. A known
slot-retention or transport denial immediately fences cached grants for that
exact original; unrelated masters remain independent. These checks are not an
end-to-end 100 ms revocation guarantee. The separate downstream 200 ms emission
permit and native/source return-boundary checks remain later integration duties.

`refresh_grant` reads an already-renewed SQL expiry and returns a new immutable
grant of the same exact purpose and scope. It invalidates the old object; it
cannot revive an expired/denied grant, change epoch identity, or refresh a pending
focus reference. Owner wall heartbeat performs actual SQL retention renewal and
checks every retained slot. Consumers must replace current references together;
obsolete callbacks conservatively deny.

## Cleanup and focus contracts

Viewer custody and original custody are separately registered, retained objects.
`finish_viewer` requires the exact registered issuer's `ViewerCleanupReceipt` for
the lease and registration. `finish_epoch` requires the original custodian's exact
`EpochCleanupReceipt` for master, worker, and SQL native generation. A receipt
constructor, caller boolean, or SQL JSON row alone is never physical cleanup
proof. The native provider must implement the registered `issued_receipt` port
with its actual retained process/IPC/Job custodian.

The last viewer stays STOPPING until both its local media and base original
receipts have settled, in either order. Viewer-only closure can park a slot while
another current viewer or focus reference retains the device. The SQL cleanup
guard prevents legacy `cleanup_confirmed=True` from closing an unconfirmed mux
viewer. Old leases without mux linkage retain their previous meaning.

R151/R152 keep the dedicated main lane separate because `ViewerGrant` carries a
stream-2 slot identity. The implemented private methods are:

- `register_dedicated(lease, native_custody, viewer_custody, *, registration, budget)`;
- `finish_dedicated_viewer(lease, viewer_receipt)`;
- `finish_dedicated(lease, epoch_receipt)`.

Registration retains the lease's exact object, full scope, registration and both
issuer callables. Completion uses that retained registration, with a bounded
cleanup SQL call; it does not accept a replacement registration from the caller.
The main original receipt's `master_id` is the dedicated lease ID and its native
UUID is that lease's own generation. A base-master receipt cannot settle it.
Legacy exclusive media login/permission proof remains the main lane's proof.

Pending FORWARD/RETURN references have immutable, nonrenewable deadlines no
longer than twenty seconds. MAIN_ACTIVE is a distinct SQL state tied to the
current dedicated main lease and bounded wall/channel authority, with a separate
active expiry of at most thirty seconds. RETURN creation consumes MAIN_ACTIVE
atomically before main Stop. A pending return does not bypass the non-CLOSED
channel barrier: sub issuance remains blocked until the dedicated main local
and original receipts both settle. Wall-stop and client cancellation/failure
tickets have separate application/worker entrypoints; clients cannot issue an
ATTACHED settlement or native cleanup receipt.

## Executed evidence and limits

Root ran the new guarded wrapper against fresh marked owned databases. The
implementer did not read private connection values, invoke the source database
directly, or migrate a production/source database. SQL tests use synthetic
inventory/proof/receipt issuers; those issuers do not establish native custody.

| Run | Actual result | Qualification |
| --- | --- | --- |
| `b5bf897b124147cb9a0611a65dbe3363` | Initial 3 SQL cases passed | Additive install/RLS, STOPPING issue barrier, legacy cleanup scope |
| `ec4caa082a3e4fa9ade23f2f3a94dc90` | 15 passed, 1 failed | Observed slot denial did not yet override cached transport True |
| `50d62b93851f4d75824635f9e3fc8d3e` | 3 passed, 1 failed | Revocation and actual actor-lock race passed; native-first last-viewer settlement failed |
| `0324903f74cc4b7188f787979061419d` | 21 passed, 1 failed | Uncertain-commit fixture injected RuntimeError outside the existing exception mapping |
| `460a8090451d4c8495d7e51eaaea1d59` | 4 passed | Corrected commit-loss injection, both last-viewer orders, actual actor-lock race |
| `ffc29067fc0a499db67b03d74c0f8d12` | **25 passed: 18 DB-fixture cases, 7 pure cases** | Complete new admission selection, including actual two-master and sixteen-retained-slot SQL caps |
| `be7de9a6be73432e9272fc973408e5e7` | **19 passed** | Root's affected legacy SQL selection, in a separate owned fixture |

Every listed owned run completed with zero errors/skips, its original test child
reaped, owned database removed, source database content unchanged, pinned source
unchanged, and no known private-value occurrences, as verified by the Root-owned
wrapper receipts. Historical function bodies/ACLs are compared before upgrade,
after upgrade, and after downgrade to 0015; existing fixture teardown then
continues through its older revision. The final legacy selection is a separate
0015 regression gate, not a claim that every legacy case ran with 0016 installed.
The seven final pure cases cover copied/foreign grants, receipt type confusion,
slow-success/sticky denial, original-binding substitution, observed-slot cache
fencing, startup deadline, and shutdown retention; they do not independently
open a PostgreSQL connection.

The implementer separately executed the three offline additive-migration cases,
the focused capability/cache/deadline regressions, Ruff/format on all four new
source/test files, and strict mypy on the admission module. All final scoped
checks passed. Missing-migration/factory assertions, cached-master denial,
inherited premature shutdown, and expired startup invocation were observed RED
before their fixes. Later added coverage is verification, not retroactively
claimed test-first work. No whole-project green claim is made.

Remaining priorities are independent SQL/security review, coordinator/provider
and API integration using these exact registered issuers, and later real native
and recorder acceptance. No new SDK, camera, decoder, browser, Job profile,
memory sizing or twelve-camera playback was executed here. Host headroom and the
shared-recorder failure impact remain the previously approved product/probe
questions; SQL source gates do not answer them.

## Historical R0 frozen source identities

| File | SHA-256 |
| --- | --- |
| `0016_tvt_device_media_epochs.py` | `9f514ec5c0feead36fab17c81a1a2fd39828cd13c96d229e65ff5a6051f9920a` |
| `local_media_mux_admission.py` | `0f71ec130823e3e34c6fe392d64f1f9c69c90b68c355b189913839b396390c24` |
| `test_local_media_mux_admission.py` | `a1a7afb7c2bdb14040d0503b9e0809f3cf7da66c743b5d43ccd4486a53bd2ef4` |
| `test_local_media_mux_migrations.py` | `3e5e4a7832fb10e1e86fa8b4c790400ff8353a47a0c78f43ea3789b027ec0385` |

2026-10-06 update: implemented additive Task 5 SQL/factory and R150–R154 contract
corrections, preserved failed evidence, recorded final owned SQL gates and scoped
static checks, and froze the candidate for Root's independent review. No Git
stage, reset, stash, commit, push, installation or recorder operation was performed.


## R193 dedicated startup authority correction (2026-10-09)

The approved MAIN transfer now uses current_dedicated_startup with the exact
known lease, retained registration/issuers and complete expected MAIN selection.
Existing0016 selection validates current wall/pending FORWARD focus/master and
actor/session/device/secret/channel scope while LOGIN/CLAIMED; startup no longer
asks the activated-only hot observer. No activated cache entry or grant is issued
by this short query, and its checkout returns before native IO. Ordinary activated
current/freshness/sticky-denial remains unchanged. Source reviewc3102fe6 accepted
the production correction; the test-only expiry margin correction has its own
R1 review. Guarded owned SQL run7b616a1a passed8/8 with normal original/DB/source
cleanup/private0; earlier e592dd93 failed expiry fixture setup and is preserved.

Normal native startup refuses settled native/viewer receipts. Proven original
login-BUSY classification after the same close_native return may supply only
that issued REAPED EpochCleanupReceipt with exact lease/worker/native binding
and all original startup guards. IO callbacks never supply that readback option.
One-shot SQL registration plus retained equality is preserved; selection does
not project SQL registration equality. See the Oct9 diagnosis/fix/R0/R1 reports
in docs/analysis and canonical service report for current actual playback gates.
This source/SQL qualification is not repaired recorder/Chrome or12-camera proof.
