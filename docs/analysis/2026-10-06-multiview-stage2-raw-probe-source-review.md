# Stage2 raw probe startup custody: R188

Date: 2026-10-06, Asia/Seoul. Source baseline: HEAD6436748 on codex/superlive-web-service, reviewed uncommitted Stage1/2 changes. Current source verdict C0/I0/M0; actual recorder/browser verification remains a separate open gate. Root verified exact current source/test/review hashes before this portable handoff. Read this report with docs/service-analysis.md and the shared recorder acceptance guide before changing this consumer.


---

## Preserved evidence: r188-raw-probe-handoff-report.md

# R188 raw probe startup custody adapter

Date: 2026-10-06, Asia/Seoul. Author result: **implemented and focused source
gates passed; frozen for fresh independent review**. This is consumer source
evidence, not recorder, native SDK, browser, or observer COMPLETE acceptance.

## Baseline, scope, and authority

Root supplied temporary source baseline
`d517b7882b7a6879cf7c3115a05bf9e81688f6fb`; actual index and HEAD were unchanged
by that snapshot. Existing uncommitted Stage 1/2 work was preserved. Root
identified previous probe/test hash prefixes `6d3cc9e2` / `d07daeb3`.

Read before implementation: project AGENTS, shared analysis policy, canonical
service report, approved Stage 2 spec and plan, current execution ledger, actual
probe, Core startup signature, genuine viewer lifecycle, and final handoff rigs.
The Root R188 ledger ruling authorizes the two-phase raw consumer only.

This author owns only `scripts/test-local-devices/mux-probe.py`,
`tests/contract/test_local_mux_probe.py`, and this requested execution report.
Core, provider, observer, existing handoff rigs and other source were read only.
No Git command, dependency/install action, SQL/private credential access, SDK or
vendor DLL call, Popen/Job implementation, Chrome or actual media run occurred.
Root owns canonical portable report/AGENTS updates and source receipt refresh.

## Purpose, architecture, and implemented change

The service's shared recorder profile supports a bounded raw two-channel gate,
then a four-channel gate before the later twelve-camera browser acceptance.
Raw viewer custody is local to this consumer; native recorder epoch custody
remains independently owned and independently confirmed.

Previously the runner called `executor.start`, received its response, then
constructed and attached its raw owner. Cancellation after genuine native viewer
startup and before Core returned therefore lacked a local retirement supplier.
The existing Core `retain_local(lease_id, registration)` hook already runs before
genuine viewer `start`; the probe did not consume it.

The runner now passes its `_retain_local` callback into Core startup. That callback
constructs `ProbeViewerOwner(executor, lease_id, registration, handle=None)`,
retains that exact owner in `runner.owners`, and returns its stable
`original_retire` supplier. After startup returns, the runner obtains the original
`mux_binding`, checks the lease and registration, binds the exact handle once,
then binds the actual observer slot/cut before any read. There is no second
post-start retirement attachment.

The original owner can supply its sealed local receipt before handle binding only
when no read or binding preparation has been attempted. Binding intent is
recorded before registration property access, so a property exception cannot
certify unattempted empty. Invalid or repeated binding, failed read, failed
release, registration substitution, in-flight reads and original held batches
prevent certification. The original tuple must be released before retirement;
copies do not discharge custody. The same supplier and receipt objects persist.

Existing two/four selection, maximum 120-second live and cleanup bounds,
deadline failure, active/current observer run, exact cut/registration checks,
wire evidence, separate native epoch cleanup, and privacy-safe projection remain
in force. `RAW_GATE_RETIRED` continues to require current live evidence and
confirmed cleanup; it does not replace the caller's observer COMPLETE terminal.

## Causal verification and results

TDD evidence:

- Initial `pytest ...test_local_mux_probe.py -k r188 -q`: **7 failed**. Three
  assertions demonstrated missing pre-start retention using the actual
  `MuxMediaExecutor.start` and genuine `MuxSlotViewer.start/close`, with synthetic
  admission/coordinator ownership seams. Cancellation occurred before start,
  after the original admission cut, and after genuine start completed before
  Core returned. Four other failures demonstrated the missing two-phase owner
  API, not independent device failures. After the minimal adapter these same
  seven controls passed.
- A later `-k binding_exception` run: **1 failed**, demonstrating that a raising
  handle registration getter incorrectly allowed an unattempted-empty receipt.
  Recording binding intent before access resolved this causal assertion.
- Final focused command below: **94 passed, 2 deselected**, exit 0. It includes
  twelve R188 cases and retained probe/current-observer/deadline controls.
- The three genuine cancel cases verify actual start-attempt/cut/start-state at
  each boundary, original supplier identity, original sealed receipt identity,
  local viewer cleanup through Core, zero raw reads, and separate unresolved
  native epoch custody. Their result remains `FAILED_RETAINED`, not success.
- A genuine blocked read and returned exact frame batch retain custody until the
  original batch release. A genuine registration substitution prevents both
  local and viewer receipts without replacing the supplier. Fixture teardown
  retires the original synthetic parent and observer threads.

Final verification commands (worktree `.venv/Scripts/python.exe`):

```text
-m pytest tests/contract/test_local_mux_probe.py tests/contract/test_local_media_observation.py -k 'not node_self_identity and not live_self_identity_probe' -q
-m ruff check scripts/test-local-devices/mux-probe.py tests/contract/test_local_mux_probe.py
-m ruff format --check scripts/test-local-devices/mux-probe.py tests/contract/test_local_mux_probe.py
-m mypy --follow-imports=silent --disable-error-code import-untyped scripts/test-local-devices/mux-probe.py
```

Ruff check and format passed. Scoped mypy passed for one source file. Its
`import-untyped` suppression qualifies the installed media module's missing
`py.typed` metadata; no dependency-wide type acceptance is claimed. The initial
unqualified mypy run also exposed the new handle's inferred-None annotation;
the owner now explicitly declares the handle as Any, matching the existing
dynamic executor/provider port.

## Actual limits and verification deviations

An initial whole probe/observer invocation passed 92 tests but inadvertently
included `test_node_self_identity_default_off_exact_bits_and_fixed_failure` and
`test_live_self_identity_probe_has_exact_private_record`, exceeding Root's
Node/kernel-helper test exclusion. Both original subprocess controls returned
normally; the latter exercised Windows self identity helpers. This was reported
to Root promptly and is not concealed as an excluded run. The final scoped
invocation excludes these two controls. No native device, SDK, SQL, browser,
decoder, or Job acceptance is inferred from either invocation.

The initial RED run failed before the genuine blocked-read test's constructor
entered its original teardown, leaving a synthetic parent thread pending. The
author interrupted only that original pytest exec session through its own
`write_stdin` Ctrl-C; no PID discovery or foreign signal occurred. The test now
uses a fixture that retains the original rig before yielding and closes it even
if owner construction fails. All subsequent GREEN processes exited normally.

These tests use genuine Core/viewer/IPC methods with inert callback/frame data
and synthetic admission/coordinator seams; they are not actual recorder or
production SQL confirmation. No full media, worker, kernel-helper, SDK, or Chrome
suite was run. Earlier Root Windows Job/profile evidence remains separate.

## Frozen file hashes

SHA256, exact files after final gates:

| Role | Path | SHA256 |
| --- | --- | --- |
| Changed source | `scripts/test-local-devices/mux-probe.py` | `a7e6f24e4de99fc0dc5eec3d709406d1acd5f81db478b560173ec0b6b87b0b5c` |
| Changed tests | `tests/contract/test_local_mux_probe.py` | `07b58664fed0df9aa125aaab401bac0be2de9d265e1e1b0a05eba594576ecae0` |
| Read-only Core | `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| Read-only provider | `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| Read-only observer | `scripts/test-local-devices/observation.py` | `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f` |
| Read-only observer tests | `tests/contract/test_local_media_observation.py` | `9f3a46ca56fe17c4504d5f262b065efe0e910362ff861c0f2096477e374231f1` |
| Read-only handoff rigs | `tests/contract/test_final_mux_handoff_refresh.py` | `766c4f70f17a9f37c2970088f1027fc8127eefc76d4f33b855c6eee566fcf373` |
| Read-only genuine viewer rig | `tests/contract/test_local_live_mux_provider.py` | `5248f60561c26ac87dba8e984534936bbdd45930bccf4acca1b8aded3575d8a9` |

## Remaining risks, priorities, and handoff

Priority 1: fresh independent consumer review against these hashes and Root's
R188 ruling. Priority 2: Root refreshes the affected source/approval closures
and portable canonical service/AGENTS records before actual bounded probes.
Priority 3: execute Root-owned real recorder/SDK, frame/resource and browser
acceptance with separate normal cleanup and observer terminal evidence.

No new product question arose in this narrow correction. Uncertain binding or
read ownership remains conservatively retained; local receipts grant neither
SQL publication authority nor native epoch completion. Source gates do not
approve actual two/four/twelve-camera behavior or resource headroom. Source
files are frozen for review; further source mutation requires a reviewer finding
or Root's explicit continuation instruction.

Update log: 2026-10-06 — minimal R188 adapter, causal RED/GREEN, exact final
focused/static gates, verification deviations, and frozen hashes recorded.


---

## Preserved evidence: r188-raw-probe-handoff-review.md

# R188 raw probe startup custody — scoped independent review

**SPEC: issues found. QUALITY: needs fixes. Critical 0 / Important 1 / Minor 0.**

Date: **2026-10-06, Asia/Seoul**. Reviewer: `r188_raw_probe_review`.
The pre-start owner/supplier correction is present, but the runner has one
remaining unrecorded binding-preparation boundary. This is a source gate only;
no recorder, SDK, SQL, process, browser or observer COMPLETE acceptance is granted.

## Scope, baseline and verification

Reviewed only the startup consumer adapter in
`scripts/test-local-devices/mux-probe.py` and its contract tests in
`tests/contract/test_local_mux_probe.py`. Read the shared analysis policy,
worktree `AGENTS.md`, relevant current canonical `docs/service-analysis.md`
continuation, R188 execution-ledger ruling, task-190 frozen diff/hash manifest,
author handoff report, and requesting-code-review/task-reviewer rubrics.
The task-190 diff truncates the owner, runner and test functions into separate
hunks, so complete changed-function context was read to inspect receipt guards,
normal cleanup, retained observer/deadline controls and fixture teardown.

Root-supplied immutable BASE:
`d517b7882b7a6879cf7c3115a05bf9e81688f6fb`.
Frozen HEAD tree: `a3ffaf08cc87a8b39652ae8b25cd24958763aac7`.
Read-only Git inspection confirmed branch `codex/superlive-web-service` and
checkout HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained modified
and untracked Stage 1/2 source/reports. No index, HEAD, branch or source write
occurred. Root owns portable canonical report/AGENTS updates; this report is the
only review output written.

Fresh `Get-FileHash -Algorithm SHA256` matched the frozen changed files and
selected read-only authorities:

| Path | Verified SHA256 |
| --- | --- |
| `scripts/test-local-devices/mux-probe.py` | `a7e6f24e4de99fc0dc5eec3d709406d1acd5f81db478b560173ec0b6b87b0b5c` |
| `tests/contract/test_local_mux_probe.py` | `07b58664fed0df9aa125aaab401bac0be2de9d265e1e1b0a05eba594576ecae0` |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| `scripts/test-local-devices/observation.py` | `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f` |
| Author `r188-raw-probe-handoff-report.md` | `a01c05fcf84babd13de9f4a15ffe10640c16ada464c33ebcdc39309e4616c76d` |

Commands were filesystem reads, `rg`, read-only Git status/branch/HEAD inspection,
and SHA256 hashing. No Python import, pytest/static-check execution, credentials,
private configuration, DB, SDK, process-control or Chrome access occurred.

## Purpose and source checks

The service provides an OWNER monitoring wall using shared recorder transport
with distinct substream slot/viewer grants. This consumer prepares bounded raw
two-channel, then four-channel evidence before Root's later twelve-camera
browser gate. A local raw owner can certify only its own settled read/batch
custody; native epoch retirement and observation terminal acceptance remain
separate authorities.

The adapter now retains a two-phase owner keyed by exact lease and registration
and returns one stable original supplier (`mux-probe.py:48`, `:63`, `:239`).
`MuxProbeRunner._run` passes that callback to real Core startup (`:349–354`).
Named risk: genuine Core/provider startup ordering. The unchanged Core captures
the original retirement attachment, obtains and attaches the supplied callback
before calling viewer start (`local_media_mux_service.py:1062–1069`), and
`MuxMediaExecutor.start` forwards the callback and closes the lease on a failed
startup (`:2191–2225`). Genuine `MuxSlotViewer.attach_retirement` refuses a
second supplier (`local_live_mux_provider.py:1132–1138`). The consumer introduces
no post-start callback attachment or replacement.

On a successful return, the runner checks the grant lease, binds the exact
returned handle/registration and observer cut/slot before its first raw read
(`mux-probe.py:355–363`, `:392–407`). Owner `bind()` marks its own attempt before
reading a potentially raising registration property (`:67–80`). Known empty
receipt reuse is stable; stopping prevents a later bind (`:127–154`). Invalid
read, failed release and exact original held batches deny local certification
(`:82–125`). Named risk: genuine provider operation/batch retirement. Read-only
inspection of `MuxSlotViewer.read_frames`, `release_frames` and `close`
(`local_live_mux_provider.py:1034–1201`) confirms its own operations and batches
are independently retained and exact receipt identity/registration checked.

The three cancellation controls use actual `MuxMediaExecutor.start` and genuine
`MuxSlotViewer.start/close`, with explicitly synthetic coordinator/admission
seams (`test_local_mux_probe.py:606–706`). They assert before-start, after-cut,
and after-start-before-return state, original supplier/receipt identity, no raw
reads and separate unresolved native custody. The actual coordinator `attach`
is source-checked above; those tests do not execute it or establish SQL/hardware
acceptance. Genuine registration substitution and blocked-read/held-batch
controls preserve the supplier and refuse receipts until original release
(`:793–869`). Fixture cleanup retains original masters before yielding
(`:776–790`).

Existing current observer binding and deadline/cleanup predicates remain in
the inspected consumer: live interval and live deadline are checked after wire
observation (`mux-probe.py:450–459`); separately bounded native wall stop, CLOSED
viewer/wall and credit restoration remain required (`:461–491`); late observer
failure denies success (`:493–510`). Their retained controls remain at
`test_local_mux_probe.py:463–603`. These are source checks, not new execution.

## Important finding I1 — initial binding lookup precedes attempt bookkeeping

**Files:** `scripts/test-local-devices/mux-probe.py:355–360`, `:135–143`;
`tests/contract/test_local_mux_probe.py:762–773`.

After `executor.start()` successfully returns, the runner calls
`executor.mux_binding(lease)` at line 356 before obtaining the retained owner at
357 or recording any binding preparation. `_binding_attempted` is first set
inside `owner.bind()` at line 69. If that initial lookup raises, the owner stays
`handle=None`, `_binding_attempted=False`, `_read_attempted=False`, and not
uncertain. `_retire()` can consequently mint a sealed known-empty receipt during
the ensuing wall cleanup.

This is a concrete production API boundary, not only a hypothetical custom
handle: unchanged genuine Core `mux_binding` performs current-state and refresh
checks (`local_media_mux_service.py:2257–2299`) and `_mux_binding_once` accesses
`handle.current_grant()`, `handle.registration` and `handle.cut` before returning
(`:2310–2313`). A denial, getter failure or uncertain binding failure there never
enters the consumer's `owner.bind()` guard. Likewise, the lease mismatch guard
at consumer line 358 occurs before bookkeeping. The author getter test directly
invokes `owner.bind()` and therefore cannot detect this runner gap.

R188 allows an unbound local receipt only when **no read or binding preparation
has been attempted**. The current runner violates that condition after an
attempted failed lookup. Genuine provider/native gates remain separate and
may independently refuse cleanup, but they do not repair this local supplier's
false known-empty certification. No actual incorrect DB settlement or hardware
cleanup is claimed to have occurred.

**Minimal fix:** obtain the already retained owner immediately after the response
lease ID, then record its binding-preparation attempt under the owner's lock
before invoking genuine `executor.mux_binding()`. Preserve that marker on any
lookup/getter/grant-validation exception; it must keep the original supplier
returning `None` while unbound. The existing successful exact bind may continue
with the same owner, callback and receipt authority. Do not add a second owner,
post-start callback replacement or Core/provider change.

**Required focused regression:** exercise the runner's first post-start genuine
binding lookup with a failing getter/lookup; assert the retained original supplier
returns `None`, no read or second supplier occurs, and local custody stays
retained. Keep the three genuine pre-return cancellation controls valid: they
must still allow a genuinely never-prepared unbound raw owner to issue the same
sealed receipt. Root may authorize the original author to run this focused
control; the reviewer ran none.

## Assessment, evidence limits and disposition

Critical: none. Important: **I1**. Minor: none. No unrelated final-combined Core,
provider or observer finding is reopened. The architecture and new original
supplier controls are consistent with the requested correction except for I1.

The author reports final **94 passed / 2 deselected**, Ruff check/format and
scoped mypy with `import-untyped` suppressed. Those remain author evidence for
the frozen files, not commands run or independently reproduced in this review.
The report explicitly retains the earlier accidental 92-test run including two
Node/self-identity controls and the original RED pytest thread interruption;
neither is silently converted into excluded execution or hardware acceptance.

Declined to judge: actual recorder two/four/twelve-channel behavior and SDK wire
acceptance, because this source review has no execution authority; actual
Windows Job/headroom/decoder/Chrome capacity, because they belong to separate
Root gates; production SQL custody settlement, because the causal rigs use
synthetic admission/coordinator seams; observer COMPLETE terminal/hash receipt,
because the caller owns that independently; unrelated final-combined source
behavior, because its existing approved review remains the authority.

Priority: resolve I1 in the original consumer/test ownership, freeze and conduct
one scoped re-review, then Root refreshes source closures and portable handoff
records. No new product question was identified. Until I1 is resolved this task
is **not source-approved**; no new actual acceptance is implied by any outcome.

Update log: 2026-10-06 — scoped frozen review, matching hashes, genuine API
causality, one binding-preparation finding and verification limits recorded.


---

## Preserved evidence: r188-raw-probe-handoff-fix1-report.md

# R188 fix round 1 — initial binding preparation

Date: 2026-10-06, Asia/Seoul. Status: **I1 corrected and focused author gates
passed; frozen for one scoped independent re-review**. No actual recorder,
native SDK, SQL, browser or observer COMPLETE acceptance is claimed.

## Baseline and authorized scope

Reviewed candidate tree: `a3ffaf08cc87a8b39652ae8b25cd24958763aac7`, derived from
Root baseline `d517b7882b7a6879cf7c3115a05bf9e81688f6fb`. Previous probe/test
SHA256 were `a7e6f24e4de99fc0dc5eec3d709406d1acd5f81db478b560173ec0b6b87b0b5c`
and `07b58664fed0df9aa125aaab401bac0be2de9d265e1e1b0a05eba594576ecae0`.
The current working tree contains preserved uncommitted Stage 1/2 work; this
author used no Git commands and changed no index, branch or HEAD.

The [frozen review](r188-raw-probe-handoff-review.md), SHA256
`31a9090e9a2c224d4f8802070db512ba658a7893ef22d4be0b099b70585ddd58`, found
C0/I1/M0. Root authorized this single consumer correction and its causal tests.
Shared policy/project instructions, canonical service/spec/plan/ledger and the
[initial author report](r188-raw-probe-handoff-report.md) remain the read-before
authorities. The review and genuine Core/viewer lookup paths were read before
implementation, using receiving-code-review and TDD procedures.

Only `scripts/test-local-devices/mux-probe.py`,
`tests/contract/test_local_mux_probe.py` and this required fix report were written.
Core/provider/observer and prior review/report evidence remain unchanged. Root
owns canonical portable service/AGENTS updates and approval closure refresh.

## Purpose, architecture, and I1 correction

The shared recorder service prepares bounded two-channel and then four-channel
raw evidence before later twelve-camera browser acceptance. The raw consumer
retains one local owner/supplier before genuine viewer startup; native epoch
custody and observer COMPLETE remain independent authorities.

I1 was verified against actual Core: after successful start, the runner called
`executor.mux_binding()` before recording binding preparation. Core's genuine
lookup accesses `current_grant`, `registration` and `cut` before returning. A
getter exception left the raw owner unbound and apparently unattempted, allowing
its supplier to mint a false known-empty local receipt during Stop cleanup.

`ProbeViewerOwner.begin_binding()` now records binding intent under the same
owner lock and refuses repeated preparation, already bound, stopping or uncertain
owners. Immediately after the response lease ID, the runner obtains its exact
already-retained owner, calls `begin_binding()`, then enters genuine
`executor.mux_binding()`. Getter/lookup or grant-validation exceptions therefore
leave an unbound attempted owner that cannot certify empty.

The existing successful `bind()` completes the same preparation on the same
owner. Existing direct bind property-exception guarding and all three genuine
pre-return cancellation controls remain: a truly never-prepared owner still
issues its same sealed local receipt. No second supplier, attachment, receipt
authority or native cleanup authority was introduced. Existing observer/current
cut, deadline, cleanup limits and `RAW_GATE_RETIRED` predicates remain intact.

## Causal RED and GREEN evidence

The new parameterized runner regression executes actual
`MuxMediaExecutor.start`, `mux_binding`, `_mux_binding_once`, and genuine
`MuxSlotViewer.start`/`close`, with explicit synthetic admission/coordinator
seams. The actual provider getter is faulted only after genuine start completes;
the actual executor's lookup is not replaced. Three cases fault
`current_grant`, `registration`, or `cut`.

Before the production correction:

```text
.venv/Scripts/python.exe -m pytest tests/contract/test_local_mux_probe.py -k r188_fix1 -q
3 failed, 33 deselected
```

Each failure was the same causal assertion: `owner.handle is None` but
`owner.original_retire()` returned a sealed receipt. An initial test-authoring
attempt had three enum import errors; the import was corrected and the three
causal assertion failures were observed before changing production code. Import
errors are not counted as causal RED evidence. All RED processes exited normally.

After the correction the final once-only focused verification command was:

```text
.venv/Scripts/python.exe -m pytest tests/contract/test_local_mux_probe.py tests/contract/test_local_media_observation.py -k 'not node_self_identity and not live_self_identity_probe' -q
97 passed, 2 deselected in 2.23s
```

This includes all fifteen R188 cases: the twelve previous controls and three I1
getter cases. The new cases verify genuine start and exactly one failed lookup,
same retained owner/original supplier, zero reads, supplier `None` on every Stop
cleanup attempt, no genuine viewer receipt, retained local coordinator entry,
native custody still unconfirmed and final `FAILED_RETAINED`/zero CLOSED claims.
Fixture teardown retains and closes only the original synthetic parent/observer.

Scoped static gates, each run once after the final source edit, exited 0:

```text
.venv/Scripts/python.exe -m ruff check scripts/test-local-devices/mux-probe.py tests/contract/test_local_mux_probe.py
.venv/Scripts/python.exe -m ruff format --check scripts/test-local-devices/mux-probe.py tests/contract/test_local_mux_probe.py
.venv/Scripts/python.exe -m mypy --follow-imports=silent --disable-error-code import-untyped scripts/test-local-devices/mux-probe.py
```

Mypy covers one source file with the previously recorded installed media
`py.typed` metadata qualification. No dependency-wide type claim is made.

## Frozen hashes and verification limits

SHA256 after all final gates:

| Role | Path | SHA256 |
| --- | --- | --- |
| Changed source | `scripts/test-local-devices/mux-probe.py` | `f2db7a05e322867997a9623896328b7c222e24bb5e68d6bd199e31f93f77370e` |
| Changed tests | `tests/contract/test_local_mux_probe.py` | `310a7152e3dfb9f54d2ed79a262f63500849e95b97ced0d4b45a7db8eae6d2a9` |
| Read-only Core | `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| Read-only provider | `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| Read-only observer | `scripts/test-local-devices/observation.py` | `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f` |

The new causal tests are genuine-method composition with synthetic ownership
seams and synthetic data, not production SQL settlement or recorder evidence.
This fix round executed no Node/Windows identity helper, process/Job helper,
SDK/vendor DLL, private credential/configuration, SQL/DB, decoder or Chrome
action. No broad media/worker/native suite was run. Earlier initial-round
verification deviations remain explicitly preserved in the initial report and
review; they did not recur in this fix round.

## Risks, priorities, and continuation

The conservative behavior deliberately retains a failed initial binding owner
without a local receipt. It cannot turn an uncertain lookup into completion;
Root must preserve retained custody according to the existing runtime policy.
No new product question arose from I1. Priority is one scoped re-review against
these hashes, followed by Root's portable canonical reports and source/approval
closure updates before actual bounded recorder tests. Hardware/browser/resource
acceptance remains separately open. Source files are now frozen; this author
stops mutation pending the scoped re-review or explicit Root direction.

Update log: 2026-10-06 — I1 verified, three causal RED→GREEN controls, 97 focused
PASS/2 explicit exclusions, scoped static gates and exact source hashes saved.


---

## Preserved evidence: r188-raw-probe-handoff-review-r1.md

# R188 fix1 — scoped independent re-review

**SPEC: compliant for this correction. QUALITY: approved. Critical 0 / Important 0 / Minor 0.**

Date: **2026-10-06, Asia/Seoul**. Reviewer: `r188_raw_probe_review`.
R0 **I1 is resolved**. No new regression was identified in the single consumer
correction and its three added getter-failure cases. This closes the scoped
source finding; it grants no actual recorder, SDK, SQL, Windows profile, Chrome
or observer COMPLETE acceptance.

## Baseline, scope and source identity

Reused [R0](r188-raw-probe-handoff-review.md), SHA256
`31a9090e9a2c224d4f8802070db512ba658a7893ef22d4be0b099b70585ddd58`, and read the
complete [fix1 author report](r188-raw-probe-handoff-fix1-report.md), current
AGENTS/service continuation and shared analysis policy. Applied the previously
loaded requesting-code-review/task-reviewer rubric. Inspected the supplied
task-190 R1 diff once, its frozen manifest, and focused line locations. Existing
unchanged Core/provider behavior was reused from R0 and its bytes rechecked;
the final-combined review was not reopened.

Root-supplied BASE: `a3ffaf08cc87a8b39652ae8b25cd24958763aac7`.
Frozen HEAD tree: `5a15289d870f2295d307c5237c9c0194df887a2e`.
The worktree remains the existing `codex/superlive-web-service` checkout at
HEAD `6436748` with retained uncommitted Stage 1/2 work. No Git state changes or
fresh Git invocation occurred in this round. Review scope is only R0 I1 and the
new regression; Root owns canonical portable reports and source approvals.

Fresh SHA256 checks matched all supplied identities:

| Role/path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/mux-probe.py` | `f2db7a05e322867997a9623896328b7c222e24bb5e68d6bd199e31f93f77370e` |
| `tests/contract/test_local_mux_probe.py` | `310a7152e3dfb9f54d2ed79a262f63500849e95b97ced0d4b45a7db8eae6d2a9` |
| Fix1 author report | `ec8031e3c58d942ed498755c4b993617a0a1097ea65ba7d288125a666834af30` |
| Read-only Core `local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| Read-only provider `local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |
| Read-only observer `observation.py` | `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f` |

## I1 disposition and strengths

The consumer's role remains bounded raw two-channel/four-channel preparation
for the shared recorder service. It owns local read/batch retirement while the
recorder epoch and observer terminal remain separate. No product scope or
authority changed.

At `mux-probe.py:368–370` the runner obtains the previously retained owner,
calls `owner.begin_binding()`, then evaluates the complete genuine
`self.executor.mux_binding(lease)` lookup/call. Thus a method lookup failure,
Core current-grant/registration/cut getter failure, denial, or later grant
validation failure cannot precede the attempt marker. The marker is set under
the same original owner lock (`:67–77`); it refuses repeated preparation,
an already bound owner, stopping, or uncertainty. Existing unbound retirement
requires no binding/read attempt (`:139–155`), so failed preparation leaves the
original supplier returning `None` without replacement or a fabricated receipt.

Successful binding still completes on the same owner (`:79`, `:373`), preserving
the existing callback/receipt authority. The call is only after successful
executor return: pre-return cancellations have not entered binding preparation
and still use R0's genuinely known-empty raw receipt. Existing before-start,
after-cut and after-start cancellation controls at
`test_local_mux_probe.py:606–706` are unchanged. This follows the required
distinction between attempted preparation and genuinely unprepared custody.

The new parameterized regression (`test_local_mux_probe.py:872–978`) faults
`current_grant`, `registration` and `cut` on the genuine viewer type. Its gate is
activated after genuine viewer startup (`:886–923`); actual
`MuxMediaExecutor.start`, `mux_binding` and `_mux_binding_once` are used rather
than replacing the binding method. Coordinator/admission are explicit synthetic
seams. The unchanged genuine Core getter accesses at
`local_media_mux_service.py:2310–2313` establish the source causality already
identified in R0.

Cleanup queries the original supplier and genuine viewer close through the
actual executor (`test_local_mux_probe.py:929–945`). Assertions require exactly
one failed getter lookup and genuine started state, an unbound retained owner,
`None` on every local and viewer cleanup attempt, no issued viewer receipt,
one unchanged original supplier, no reads, retained coordinator entry,
unconfirmed separate native owner, and `FAILED_RETAINED` with zero CLOSED claims
(`:966–978`). These assertions directly cover I1 and would reject the old false
known-empty behavior. Extending the genuine-viewer fixture to accept
`started=False` preserves its original-parent teardown ownership (`:782–790`).

The diff makes no change to observer/current-run checks, separately bounded
live/cleanup deadlines, normal cleanup predicates, Core/provider retirement or
native epoch authority. Their prior reviewed dispositions remain qualified
source evidence; they are not inferred to have executed anew.

## Issues and verification limits

Critical: none. Important: none. Minor: none. R0 I1: **resolved**.
No further fix or broader test was requested by this review.

The author reports three causal RED assertion failures before the source fix,
then **97 passed / 2 deselected** with Ruff check/format and scoped mypy using
the previously disclosed `import-untyped` suppression. Earlier enum import
errors are explicitly separated from causal RED. These are author results,
not reviewer executions. The two Node/self-identity controls were explicitly
excluded in fix1; initial-round accidental inclusion and original RED thread
interruption remain historical in R0/initial report.

Reviewer verification consisted of `Get-Content`/`rg` source-report inspection
and `Get-FileHash -Algorithm SHA256`; no Python imports, tests/static tools,
credentials/private configuration, DB, SDK, process/control/Job or Chrome work
was performed. This report is the only written artifact; source stayed frozen.

Declined to judge: actual recorder/SDK two/four/twelve-channel behavior and
headroom/Chrome acceptance, because these are separate Root execution gates;
production SQL settlement, because regression ownership seams are synthetic;
observer COMPLETE terminal/hash acceptance, because the caller owns it;
unrelated final-combined source behavior, because this is one scoped re-review.

Priority: Root records this scoped source acceptance in portable authority and
refreshes affected exact source/approval closures before actual bounded probes.
Failed preparation intentionally remains retained until independent original
custody settlement; source approval supplies no alternative cleanup authority.
No new product question arose.

Update log: 2026-10-06 — single I1 correction source-approved C0/I0/M0, all
supplied hashes matched, new genuine lookup regressions reviewed with unchanged
pre-return cancellation authority and actual verification limits preserved.
