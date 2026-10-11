# Multi-view stage 1 combined native source review

Review date: **2026-10-05 (Asia/Seoul)**. Round: **r0**.

**Verdict: changes required before the Task 7 native receipt/device gate.**
**Open findings: Critical 0 / Important 1 / Minor 7.** The Important finding is
newly reproduced here. The seven Minor items are explicitly carried from the
Task 1/2 ledger; they are not seven newly discovered functional regressions.

## Baseline, purpose and scope

- Checkout: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
  branch `codex/superlive-web-service`, commit `6436748`.
- Immutable review range: `6436748` to tree
  `e65e3ec44a674d026476c06c8817a8aa58696df7`.
- Supplied package: `.superpowers/sdd/2026-10-05-multiview-stage1-plan/review-stage1-native-r0.diff`;
  4,373 lines, 16 changed paths, SHA-256
  `47fe47c5dd1495f245ebd4f1196dfaa73a868d91aeb260ab7fb5bd014bc935ef`.
- Initial tree contained uncommitted stage-1 Tasks 1–5, controller reports,
  migrations/tests, and concurrent Task 6 web changes. This review read the
  entire supplied immutable diff in bounded segments. It did not inspect the
  moving Task 6 implementation diff.
- All 16 supplied paths matched the immutable tree when comparing contents
  with CRLF normalized. The named context dependencies also matched:
  `local_inventory_ipc.py`, `local_inventory_provider.py`, `native_source.py`,
  migrations 0014/0015 and the test runtime. A plain `git diff` lists the two
  untracked gate tests as absent from its index view; direct `git show` versus
  filesystem comparison confirmed their contents match the snapshot.

The service supplies authorized local-recorder video through one original
Windows process/socket per tile, a private child/parent pipe, decoded media and
WebRTC. Stage 1 adds explicit main/sub selection, bounded authority observation,
first-frame failure and admission capacity 16. The reviewed closure covers the
changed native OWNED/LIVE files and their callback/core dependencies. Unchanged
code was read only for named correlation, custody, callback and cleanup risks.

Read-before references: the shared analysis policy, this worktree's `AGENTS.md`,
the current [service analysis](../service-analysis.md),
[liveness analysis](2026-10-04-local-media-liveness-review.md), approved plan,
global constraints, APK notes, execution ledger and relevant Task 1–5 reviews.
The controller owns updates to canonical report pointers and `AGENTS.md`.

## Requirement assessment

| Requirement | Source assessment |
| --- | --- |
| Main/sub and source request fidelity | `local_live.py:315` preserves 1281 plus stream 1/2 for main or older peers; sub with capability at least 5 uses 1285 XML. Close remains 1282 with the selected stream. Checked the referenced APK `cw3:2512–2578,6641–6675,7459–7468`; no broader APK crawl. |
| ACK and warning | `local_live.py:458–483` accepts only the pending success command, sequence, external generation and lifecycle. A 1285 payload needs at least 76 bytes. Its oz0 code can set the adaptation warning, never supply authority or manufacture success. Unknown advisory codes retain success. |
| R129 refusal | `local_live.py:512–531` requires class 3, the pending low-28-bit command, open/unacknowledged state, a payload of at least 76 bytes and the original task at payload `[52:68]`. It reads the reason from oz0 at payload `+72`. **The wz0 sequence is deliberately not compared.** `cw3:6969–6972,7051–7056,7093–7122` and `oz0.java:15–33` confirm this source interpretation; `ServerNVMSHeader.java:2701–2709` confirms the class range. |
| Exact parent/child validation | Selection becomes exact integer stream 1/2 in the request, supervisor packet and child setup. The parent validates channel/raw/window/ordinal/stream and derives the callback generation from the original process generation. The child derives setup from fresh same-session inventory; the parent rejects any mismatch before allowing live Send. Both codecs independently parse the original envelopes. |
| Original first task and proof | `CallbackOwner.claim_first_live()` remains one-use. Both codecs opt into exclusive first-task route 0; generation/channel/kind checks remain. Route 2 still requires the exact wire task. Supervisor handoff requires readiness and current authority; `OwnedLocalLiveSession.__init__` requires queued frames and setup. A valid keyframe, supported codec, timestamp and Annex-B prefix remain prerequisites. No ACK-only handoff or replacement socket/task was introduced. Diagnostic `capture_live` remains stream 1. |
| Refusal forwarding and cleanup | `windows_socket_worker.py:1130–1138` forwards a correlated refusal's exact envelope, and the parent independently derives the fixed reason. Busy maps to 429; denied/other correlated refusals map to upstream-rejected 502. Wrong command/task remains a bounded codec failure. Existing native Stop/Destroy/Quit and original-owner retirement remain responsible for cleanup. |
| R131 ACK-to-keyframe bound | `local_live_ipc.py:315–320,327,383–398` anchors one 10-second timer to an independently accepted open ACK. A late first keyframe cannot create readiness. No ACK retains caller deadline/protocol behavior. Authority, cancellation, caller deadline and already parsed refusal/protocol failures retain precedence. Timeout keeps original custody and maps to NO_SIGNAL/504. This is one phase bound, not a 10-second whole-request/retirement promise. |
| R120 callback amendment | **Accepted explicitly for this source review:** “checks current owner state every time” now means calling a per-lease authority gate backed by an SQL observation whose check began less than 100 ms before that call began. It no longer means fresh SQL for every callback. `local_media_admission.py:389–452` implements the call-entry invariant, one in-flight check, sticky denial and expiry-clipped ordinary cache reuse. The approved brief intentionally honors a slow successful in-flight result for eligible callers; it does not promise an observation at most 100 ms old at return time. `native_source.py:263–282` subtracts F before calculating an expiry-clipped emission permit, so late successful observations do not extend that permit. |
| R132 startup SQL reservation | `local_media_admission.py:188,196–197,264–299` limits long startup transactions to eight before checkout from the 8+8 pool. Polling is at most 50 ms, bounded by caller budget and 10 seconds, with cancellation/deadline precedence. The engine context settles before the outer semaphore releases. No registry/authority lock spans SQL or the native callback, and sticky denial/freshness remain unchanged. This reserves eight slots against long startup occupancy; it does not guarantee availability under arbitrary stalled short queries. |
| 16 originals and uncertain custody | The constants and shared lock/custody deadline are correct, but **the admission invariant fails under concurrent confirmed-owner removal: I1 below**. A second count under ATTEMPT_LOCK is insufficient because removers do not hold that lock. |

The request/reply selection, source-faithful refusal interpretation, independent
pipe validation and unchanged proof-before-handoff are strong parts of the
implementation. The R132 transaction context ordering is also explicit and
preserves the original ownership boundary.

## I1 — Mutable owner registry iteration can bypass custody and capacity

**Severity: Important. Fix before native receipt or device execution.**

Affected admission reads:
`services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py:1029,1039,1046`.
Concurrent removers include `local_live_ipc.py:143–144`,
`local_live_provider.py:177–178,261–262`, and
`local_inventory_provider.py:181–182`.

`PENDING_OWNERS` is a mutable list. The attempt lock serializes startup, but
confirmed-owner removal occurs independently during session close or retirement.
Removing an already visited predecessor shifts its live successor behind the
list iterator's next index. That successor is then omitted from the filtered
list. A confirmed entry does not count toward capacity, so removing it does not
free a live slot; skipping its unconfirmed successor incorrectly does.

Two effects follow from the same defect:

1. An uncertain original can be skipped by the loop at line 1046. The resulting
   list can appear empty/healthy, permitting startup while that original remains
   unconfirmed and retained.
2. A fast count and the later locked count can each miss an active original when
   different confirmed predecessors retire. Startup then proceeds with 16 active
   originals already present, permitting a seventeenth admission if later checks
   succeed.

The Task 5 r0 review's statement that concurrent cleanup cannot permit over-cap
admission is therefore superseded by this narrower reproduced finding. Its
other source/SQL conclusions are not invalidated by this race.

### Focused reproduction executed here

Ran an in-memory Python script using `.venv/Scripts/python.exe -B -`. It imported
the actual `WindowsSocketProvider.run` and `ChildOwner` code. All objects,
requests and child polling were synthetic. A `verify_review` sentinel recorded
entry and immediately raised `ProviderError`, stopping before filesystem
generation, Job creation, SDK loading or any native child/device activity.

Reproducible schedule:

- For uncertain custody, initialize the registry as `[confirmed A, uncertain B]`.
  At line 1046, after the list iterator has processed A and before its next
  iteration, a separate thread removes A. B remains unconfirmed in the registry
  but is absent from the admission snapshot.
- For capacity, initialize `[confirmed A, live L1, confirmed B, live L2, …, live L16]`.
  Each live owner has an inert live authority marked ready/handed-off and a fake
  original child whose `poll()` returns `None`. Remove A after its evaluation
  in the line-1029 generator, so the fast count misses L1. Remove B after its
  evaluation in the line-1046 comprehension, so the locked count misses L2.
- Line tracing only coordinates these ordinary thread interleavings. The
  remover checks `confirmed` before removal and never alters a live owner's
  state. The sentinel independently counts a stable tuple and checks that
  ATTEMPT_LOCK is held. Controls use the same objects without the removals.

| Case | Observed result |
| --- | --- |
| Uncertain custody, control | BUSY; pre-native sentinel not reached. |
| Uncertain custody, removal at 1046 | Sentinel reached with one unconfirmed original still retained; ATTEMPT_LOCK held. |
| Sixteen live owners, control | BUSY; sentinel not reached. |
| Sixteen live owners, removals at 1029 and 1046 | Sentinel reached with exactly 16 unconfirmed live originals still retained; ATTEMPT_LOCK held. |

The successful four-case probe exited 0. An initial opcode-tracing harness did
not deliver opcode callbacks and failed its own reproduction assertion; using
line events corrected the harness without changing application source. No
actual seventeenth child was started, and no live race frequency is claimed.

### Exact correction directions

1. Introduce one dedicated, short owner-registry lock and a stable snapshot
   helper. Synchronize **all** production append, snapshot and remove operations.
   Filter/count the returned tuple rather than iterating the mutable list.
   Keep startup serialized with ATTEMPT_LOCK, including its final capacity check
   and original-owner registration before resource acquisition.
2. Make confirmed removal atomic/idempotent through that interface, preferably
   by original object identity. Update the append at `windows_socket.py:1151`,
   all three admission reads, both live-provider cleanup sites, the live reaper
   and inventory-provider cleanup. Preserve original-owner-only confirmation;
   a waiter must never remove or manufacture confirmation for an uncertain owner.
3. **Do not acquire ATTEMPT_LOCK from close/reaper cleanup.** Startup holds that
   long lock while waiting for uncertain originals to finish; making retirement
   acquire it would prevent the awaited progress. Never hold the registry lock
   across `finish`, `passive_wait`, SQL, callbacks, process operations, sleeps or
   thread joins. Snapshot first, then operate outside the short lock.
4. Update the concrete runtime consumers too: `scripts/test-local-devices/runtime.py:763,765,814`.
   Disposal already copies for its `passive_wait` loop, but its later direct
   `any` and final `all` can skip an unconfirmed successor during removal and
   falsely report cleanup. Use the same stable-snapshot interface for each
   decision and keep waiting outside the registry lock.
5. Add deterministic regressions for both schedules above and cleanup readback.
   Require no progress past admission with an uncertain original or 16 active
   originals, plus successful progress after an original confirms cleanup.
   Check that close/reaper can complete while startup is waiting. Preserve the
   one shared 10-second wait budget and immediate full-capacity BUSY behavior.

## Carried Minor findings and dispositions still required

These remain open in the existing ledger. They are nonblocking hardening or
documentation matters, but must be closed or explicitly dispositioned before
the controller emits a receipt that asserts zero Minor findings.

| ID | Current evidence and precise follow-up |
| --- | --- |
| M1 (Task 1 M1) | `local_media_admission.py:365` still allows the unused internal `current`/`worker_view` query selectors. Remove those dead names or document a concrete caller requiring them. This does not change the new `observe` gate. |
| M2 (Task 1 M2) | `_authorities` creates entries at `local_media_admission.py:402–406` and only removes them during close/shutdown. Re-querying evicted closed tombstones can leave denied entries retained. Define reclamation only when the original lease can no longer be queried, or record the accepted lifetime-retention bound. Do not evict a live lease's sticky denial merely to shrink the dictionary. |
| M3 (Task 1 M3) | `local_media_admission.py:441–452` returns a fresh successful result even if its `expires_at` has passed by return; the test at `test_local_media_authority_gate.py:510` explicitly allows this once. This is consistent with the approved slow-success semantics and remains bounded by call entry plus downstream permit clipping. The earlier “clock-skew only” explanation is incomplete: response latency can also cross expiry. Clarify this distinction in the gate documentation/test comment; any stricter result-denial policy must preserve the approved non-sticky treatment of slow success. |
| M4 (Task 1 M5) | `local_media_admission.py:471–475` returns the shared mutable cached `MediaLease`. Current consumers only read it, so no current corruption was found. Return an independent model copy from public `view`, or explicitly document/read-protect that interface. Do not alter cache freshness. |
| M5 (Task 1 M7) | `_authority` deliberately uses the injected clock for freshness and real `time.monotonic` for the 5-second waiter bound. Add a short explanatory comment at the wait loop; changing the timeout to a fake/injected clock is not requested. |
| M6 (Task 2 M2) | `docs/integrations/tvt-local-live-codec.md:138,216` omits the refusal sequence exception. Add “the wz0 sequence is not compared; m8 correlates by task only” to the refusal contract. Keep the ACK sequence check explicit and distinct. |
| M7 (Task 2 M4) | The same guide's newly added lifecycle text still contains joined prose such as `as1`, `pending1285`, `at least76` and `low28`. Normalize number/word spacing in those added paragraphs/table rows without changing wire constants or source citations. |

Other carried observations have concrete dispositions:

- **Task 2 M1, exact-76-byte boundary: covered by later Task 3 tests.**
  `test_local_live_provider.py:744,765` feeds exactly `yz0(72)+int32(4)` to the
  real parent codec and asserts refusal/ACK outcomes; child-side tests at
  `test_windows_socket.py:3699,3720` also use that exact boundary. The codec
  suite retains the 75-byte negative cases. Adding another identical assertion
  solely in the codec test file is optional, so this is not counted open here.
- **Task 2 M3:** the wrong-command sub refusal now fails immediately as codec
  failure; the native pipe tests retain original Stop/Destroy/Quit assertions.
- **Task 1 M6:** the demonstrated startup-pool starvation was addressed by R132
  and the prior independent review of the actual 47-case SQL receipt. That does
  not establish capacity under arbitrary workloads.
- **Task 1 M8:** the native-owned renewal comment at
  `local_media_service.py:527` now states the 100 ms observation contract, which
  this review explicitly acknowledges above.
- **Task 1 M4/M9:** measured permit margin and runtime static-warning debt stay
  qualified acceptance/baseline matters; no new clean runtime static claim is made.

## Verification limits, priorities and handoff

Executed in this review: source/status reads, the complete supplied diff,
targeted exact APK source reads, normalized snapshot comparisons, registry-site
search and the focused inert four-case concurrency probe. No test suite, SQL,
SDK, device, browser runtime, private capture or credential access was executed.
No source, receipt, index, commit, stash or reset was changed. The only requested
write is this portable report.

Earlier Task 2–5 synthetic/static results and Task 5's actual SQL receipt are
historical author/controller evidence inspected through their reports and prior
independent reviews. They were not rerun or recertified here. In particular,
this verdict is **source review, not actual substream or 12–16-stream capacity
acceptance**, and grants no source receipt or runtime approval.

Behaviors considered and set aside from this source gate:

- Actual recorder stream-kind, oz0/warning/refusal shape, connection limits and
  keyframe cadence require Task 7 device measurements; the APK notes' inferred
  stream-kind behavior is not presented as device proof.
- Task 6 focus/grid scheduling and public quality UI belong to its separate
  frozen web review; concurrent web changes were excluded here.
- General SQL redesign, unrelated native ABI changes and broad APK analysis
  are outside the supplied closure. R132's source integration was assessed;
  prior migration/SQL verification remains separately attributed.
- Slow-success authority semantics and the two separate first-frame phase
  anchors are approved contracts, not new defects to “fix” by weakening proof
  or silently changing deadline behavior.

Next priorities: fix I1 across the complete registry interface; close or record
explicit dispositions for the carried minors; perform a scoped independent
re-review of that delta; then let the controller regenerate LIVE/native receipts
and source approval. Actual Task 7 must still measure substream decoding,
no-signal timing and eventual original retirement, SQL/resource sizing and
permit lapse/withheld counts. Recorder behavior and the suitability of the
10-second phase limits remain open product/acceptance questions.

Update log: **2026-10-05** — Initial combined native r0 review; C0/I1/M7, including
a deterministic registry-race reproduction and explicit R120 contract acceptance.


## Author fix1 addendum - 2026-10-05 (Asia/Seoul)

The r0 verdict and reproduction evidence above remain historical review findings. This addendum records authored changes and executed regression gates; independent re-review has not yet accepted the delta. Baseline for the fix is tree `e65e3ec44a674d026476c06c8817a8aa58696df7`; uncommitted Tasks 1-6 and FE are preserved.

I1 was independently reproduced in deterministic synthetic tests: removing confirmed predecessors allowed admission to skip an uncertain owner and to proceed with sixteen active originals. Runtime disposal/readback similarly skipped an unconfirmed successor. Controls without removal denied correctly. The fix introduces a dedicated short registry lock for tuple snapshots, append and idempotent confirmed-original removal by identity. Every production registry read/write named above now uses that interface, including inventory cleanup, both live-provider sites, the live reaper and all three runtime consumers. Filtering, process polling, finish/passive_wait, sleep and joins occur outside the registry lock. Close/reaper do not acquire the long attempt lock. Tests verify original retirement progresses while an attempt holds that lock, and startup proceeds only after original confirmation.

Minor dispositions: M1 removes unused current/worker_view query selectors. M4 deep-copies public MediaLease views and their nested scope while keeping current's internal cache fast path. M5 explains the injected freshness clock versus real monotonic waiter time. M6 explicitly documents the refusal sequence exception while preserving ACK sequence checks. M7 fixes the new lifecycle prose spacing. M2 is accepted under R133: re-queried distinct sealed closed tokens may retain denied state until retirement/shutdown; the authority registry has no configured cap and memory can grow across an admission/process lifetime. Active sticky denial is not evicted. M3 keeps approved slow-success answers for eligible callers even when SQL response latency crosses expiry, with ordinary cache reuse and emission permits still clipped; source, guide and test comments now state this alongside clock skew.

Executed after the fixes: **464 native/inventory/runtime contract tests passed**, and **83 authority/startup/core/source tests passed**. The twelve focused fix cases also passed. Ruff check/format passed for nine changed non-runtime Python files; strict mypy passed for five production files. Runtime's isolated baseline/current mypy errors remain the same 88 messages; no whole-runtime or whole-repository static success is claimed. The first core covering run exposed its old shared-object-identity assertion, which was updated to eight equal independent views backed by one SQL check before the final 83-pass run.

No SQL rerun was needed for the dead-selector/model-copy/comment delta; the prior reviewed 47-case SQL receipt remains historical evidence. No SDK/device/browser acceptance, FE edits, receipt/approval changes, migrations or Git index/history changes occurred. Original-owner synthetic tests do not prove recorder capacity. Accepted R133 memory growth, existing runtime static debt and Task 7 actual load/latency acceptance remain explicit limits. Controller must obtain scoped re-review before new source receipts. Detailed local handoff: `.superpowers/sdd/2026-10-05-multiview-stage1-plan/task-7-native-fix1-report.md`.

## Independent fix1 re-review — r1, 2026-10-05 (Asia/Seoul)

**Spec: compliant with the authorized R133 dispositions. Quality: approved for
the combined native source gate. Open findings: Critical 0 / Important 0 /
Minor 0.** I1 is corrected; each carried Minor item is resolved or explicitly
accepted below. The r0 review and author addendum above remain historical
evidence. Zero open findings does not mean zero residual risk or actual device
acceptance.

### Frozen scope and evidence

Reviewed the complete 1,308-line `review-stage1-native-fix1.diff`, all 12 changed
paths, the fix1 author report, r0 findings, R133 ledger entry, shared analysis
policy, worktree `AGENTS.md` and current service-analysis continuation. The
checkout still contains uncommitted stage-1 implementation and concurrent web
work; the latter was excluded from this scoped review.

- BASE tree: `e65e3ec44a674d026476c06c8817a8aa58696df7`.
- HEAD tree: `791f2ee927ebd370103874d22ba20846e9923ed7`.
- Fix1 diff SHA-256:
  `ff5c453b93a19f5332363348a26a63364aa427bb53977c29c0d4ccb23ec23c76`.
- Direct `git show HEAD:path` versus filesystem comparison, normalizing CRLF,
  confirmed that all 12 reviewed files match HEAD, including the new registry
  test file. No source changes occurred during this review.

### I1 — resolved in source

`windows_socket.py:984–1004` now supplies one short-lock registry interface:
tuple membership snapshot, registration, and idempotent confirmed removal by
original object identity. Removal checks the original `confirmed` field and
does not manufacture cleanup. Equal-but-distinct dataclass objects cannot cause
the wrong owner to be removed.

The three admission reads at `windows_socket.py:1055,1066,1076` iterate stable
snapshots. A concurrent confirmed-predecessor removal therefore cannot shift a
live or uncertain successor behind the iterator. Final admission and original
registration at `:1183` remain inside the existing ATTEMPT_LOCK; all production
registration sites use that serialized path. The capacity 16 constant and one
shared lock/custody wait deadline are unchanged.

The production-site search confirmed complete adoption of the interface:

- live-provider session cleanup at `local_live_provider.py:178` and failed-open
  cleanup at `:261`;
- original live reaper at `local_live_ipc.py:143`;
- inventory cleanup at `local_inventory_provider.py:181`;
- runtime disposal iteration, its custody decision, and final readback at
  `runtime.py:763,765,814`.

Direct mutable-list reads/writes in production now occur only inside the three
registry helpers. Existing test fixture seeding is outside that production
interface and does not weaken the reviewed runtime path.

Lock ordering is correct for this fix: close/reaper never acquire ATTEMPT_LOCK.
Registry lock scopes contain membership copying/appending or the original
boolean check plus identity removal. They do not contain process polling,
`finish`, `passive_wait`, SQL, callbacks, sleeps or joins. Admission evaluates
health after snapshot release; cleanup finishes the original before invoking
the removal helper. Thus the startup waiter does not hold the lock required
by the retirement it awaits.

The added test sources directly address the reproduced mechanism:

- `test_local_owner_registry.py:62,88` coordinates a separate confirmed-owner
  remover during field evaluation, including controls for uncertain custody and
  sixteen active originals. The fixed pre-lock capacity snapshot can reject
  immediately, so the second scheduled removal need not occur in the passing
  capacity case; the same test exposes both removals on the old code.
- `:126` verifies stable tuple membership, refusal to remove an uncertain owner,
  identity-only removal and harmless repeated removal.
- `:147` uses actual session-close and actual live watchdog/reaper paths while
  an attempt holds ATTEMPT_LOCK, requiring progress only after confirmation and
  checking that original finish runs outside the registry lock.
- `test_local_device_browser_fixture.py:605` checks both runtime disposal and
  final readback with a confirmed predecessor removed during evaluation. The
  uncertain successor still prevents a successful cleanup conclusion.

These assertions support the fix's scope. The reviewer did not rerun them or
claim that their synthetic schedules measure the incidence of races on devices.

### Explicit disposition of all seven Minor items

| r0 finding | Independent r1 disposition |
| --- | --- |
| M1 — dead SQL selectors | **Resolved.** `local_media_admission.py:368` now allows only `activate`, `playing` and `observe`. The regression at `test_local_media_authority_gate.py:620` invokes the real `_query` and requires both removed selectors to fail before any engine statement. |
| M2 — retained denied entries | **Closed by accepted R133 qualification, not by reclamation.** Source at `local_media_admission.py:185–187` and the media guide explicitly state that distinct sealed closed tokens re-queried after tombstone eviction can retain denied entries for the admission/process lifetime, until explicit retirement or shutdown. There is **no configured cap on this registry**; the 64 recent tombstones do not bound it. Memory growth remains an accepted risk, and sticky denial is not evicted. |
| M3 — success crossing expiry | **Resolved by accurate contract documentation.** Source docstring, media guide and expiry-test comment now cover response latency crossing expiry as well as clock skew. The approved runner/eligible-waiter slow-success behavior is unchanged. Ordinary cache reuse and emission permits remain expiry-clipped; no return-time freshness/unexpired-lease guarantee or new sticky denial is asserted. |
| M4 — mutable cached view | **Resolved.** Public `view()` at `local_media_admission.py:479–483` returns `model_copy(deep=True)` outside gate locks. The mutation test at `test_local_media_authority_gate.py:601` changes expiry and nested owner/device scope, then verifies a later view is intact with one SQL observation. The concurrent test at `:329` now requires eight equal independent views backed by one in-flight check. `current()` retains its internal cache fast path. |
| M5 — two clocks | **Resolved.** The wait-loop comment at `local_media_admission.py:429–430` explains injected-clock freshness versus real monotonic waiter liveness. Timeout behavior is unchanged. |
| M6 — refusal sequence exception | **Resolved.** The codec guide now explicitly states in the lifecycle row, explanatory paragraph and predicate table that refusal wz0 sequence is not compared because m8 correlates by task. Success ACKs still require the exact pending sequence. No wire code changed. |
| M7 — joined numeric prose | **Resolved in the requested text.** The added lifecycle paragraphs and relevant table rows now separate the reported number/word combinations while retaining wire constants, offsets and source citations. No broader historical-guide restyling was required. |

### Preserved contracts and actual verification limits

The r0 source assessments remain applicable to the unchanged protocol, proof,
R131 first-keyframe and R132 startup-reservation paths. **R120 is still accepted
as a call-entry observation bound of less than 100 ms, not fresh SQL on every
callback or a maximum observation age at return.** This fix does not alter the
authority gate state machine, expiry policy, startup semaphore or SQL bodies.

Reviewer-executed verification was read-only: complete fixed diff inspection,
scoped registry-interface/caller searches, source/context reads, branch/status
inspection and the 12-path immutable-tree comparison. No additional execution
probe was needed. No suites, database, SDK, device, browser runtime, private
credentials/captures or child agents were invoked. Only this report addendum
was written; source, Git index/history and receipts were not changed.

The author reports 12 focused passes, 464 native/inventory/runtime contract
passes, 83 core/source passes, strict mypy for five source files and Ruff
check/format for nine files. This reviewer assessed the changed test assertions
and source but **did not reproduce those counts or causal RED runs**. The
reported unchanged 88 isolated runtime type errors remain baseline debt; no
whole-runtime static success is inferred. The earlier 47-case SQL receipt stays
historical; this selector/copy/comment fix makes no new SQL execution claim.

No additional behavior was declined within this scoped fix review. The r0
out-of-scope device, web and broader architecture items remain excluded. Next,
the controller may use this source verdict for the required receipt/approval
workflow. Actual substream playback, recorder limits, no-signal and retirement
timing, twelve-tile behavior, SQL/resource sizing and permit lapse/withheld
measurements remain Task 7 acceptance work. Accepted R133 lifetime memory growth
and the suitability of the existing timing bounds remain explicit limits.

Update log: **2026-10-05** — Independent fix1 r1 source re-review completed;
I1 corrected, M1/M3/M4/M5/M6/M7 resolved, M2 closed under R133 with its memory
qualification retained. Current open counts C0/I0/M0; no device acceptance or
receipt issued by this reviewer.


## R138 bounded queue-credit scoped native review ? 2026-10-06

BaselineHEAD6436748, uncommitted scoped tree387bcb12861a615d899dc070e9cb2b3b2590dd43
against R137 tree20c4a7d7. Independent review approved C0/I0/M0, twelve authored
paths match. Protected local_live_ipc.py SHA52109c4df410fbafc37170a78a2d5c76ce24870dfd0156b7a137ea54ce5aaf85.
Native parent retains current/cancel/expiry/permanent-close checks while parsed
frames remain, then defers receiving the exact next IPC envelope/sequence/ACK
until consumer credit returns. Existing16frames/4MiB parent,256chunks/1MiB
callback, original native/socket/task/proof/sequence and thirty-second child
orphan bound stay unchanged. Source reserves remaining16frames/4MiB credit and
waits at most5s or shorter existing deadlines with stop/dequeue notification.
No arbitrary media drop, owner overlap, forged ACK or authority expansion.

Author executed75 parent/provider,102 source/transition/observation and139
actual isolated synthetic Windows decoder/WebRTC/worker cases, all pass; scoped
Ruff9/strict mypy3 pass. Reviewer source/hash verification only, no rerun.
Faithful original-session/parent/remote composition preserves40 synthetic frames
across1.8s blocked first decode. Keepalive may be delayed while ACK is held;
unchanged callback capacity can still overflow under actual load. These limits
require new actual1/4/12 recorder acceptance, not a wider unrelated audit.

Retired c8 actual sources/evidence remain unchanged; seven leases CLOSEDconfirmed,
all original owners retired0/sourceprivate0/observerCOMPLETE. Root creates a new
protected native source receipt under a new filename plus immutable c9 approval.
This source gate does not establish actual repaired playback or APK parity.
Scoped review SHA4854f301a7922227b17b6d0b5b74e51af1ba2259f500bd2bd8d65df5a1b7545e.


## R139 exact-original login BUSY and public manifest ? 2026-10-06

Scoped tree dbbf2c277ea100f517f2e40a650184d6aff53999 against387bcb1286,
HEAD6436748 with authorizeduncommittedStage1. Independentnative/source review
C0/I0/M0,9paths/fivePythonhashes/fourLIVEmanifestsourcehashes matched.
Recoveredhandshake/rejected/0x20000030 ispassiveerror evidence onlyafterexact
originalreap/fileidentity/generation/boundedread; providercurrent/cancel/expiry
anduncertaincustody retainprecedence. Nohandoff/session/grant revived, noPID
lookup/retry/ABI/worker/timeoutchange. Missing/partialoriginalresult afterEOF
stillfails502; thisconditionalinterleavinglimit needsactualexecution.

Authorfaithful16casespass; initial443selection429pass14fail, targetedpin4 and
provider/inventory112pass afterstalepin/exactowner-test-teardown corrections.
Publicpointer4pass, Ruff5/mypy2pass. Reviewer read-only/hashes, no tests/devices.
PublicLIVE source manifest nowdocs/integrations/receipts/tvt-local-live-substreams-stage1.json,
EXACTbe556205bc41a47a0c996fb5bc71582225e730ba0ffdd45e2cd0c8bd96a99143.
Narrowattributes preserveapprovedfileEOL; privateSDK/sourceapprovalstayprivate.
Reviewdigest878244? insidepublicmanifest ishistorical(c6/c7/c8immutablepins),
notcurrentappend-onlyreporthash. Oldreceiptbytes unchanged. Newprotectednative
closure+c10 pinscurrentreviewedsource. R139review86a5fece16e5e2bb8d032217882a23b99a067c955a9477313878020d6d1500aa.
Actual12tiles,recordercapacity andtimestampplaybackcorrectionremainunaccepted.
