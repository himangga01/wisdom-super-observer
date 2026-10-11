# Stage2 browser runtime source review

Date: 2026-10-06, Asia/Seoul. Baseline: codex/superlive-web-service HEAD6436748 with retained reviewed source. Final scoped helper review R1 C0/I0/M0; actual Chrome remains unexecuted behind real raw two/four gates. Root independently verified current helper and review SHA256. Read with docs/service-analysis.md before reuse; update actual source/native/browser/cleanup limits after execution.


---

## Preserved evidence: browser-owned-prep-report.md

# Root-owned Stage 2 browser launch preparation

Date: 2026-10-06, Asia/Seoul. Source-only preparation, awaiting independent
helper review and Root's actual raw two/four gates. No real browser acceptance.

Baseline supplied by Root: branch `codex/superlive-web-service`, HEAD `6436748`,
retained reviewed uncommitted Stage 1/2 source. Read shared analysis policy,
worktree AGENTS, current service report/ledger, shared acceptance guide,
browser-runtime guide, runtime/server and historical Stage 1 helpers. No Git,
production, documentation-authority, private input, SDK, DB or Chrome mutation
was performed. New files are under the already ignored current SDD directory.
Root must copy the source preparation/review outcome into the portable canonical
service/acceptance reports; this ignored preparation is not a second authority.

## Frozen helper and implemented contract

`run-media-browser-stage2-owned.py`, SHA256:
`5c980d3f2769c258c6374b9caa1bf411820437ae95029bb0f9cdd4c76ca3c1fe`.

One minimal helper with explicit `runtime` and `chrome` modes. Both require an
externally supplied current schema3 approval filepath and full SHA256. Both
require the helper itself in that reviewed source closure. The helper verifies
the approved runtime/server hashes before importing the inert runtime, then
calls its existing `verify_source_approval`. Fixed private paths are supplied
to that gate, before reading any PG or recorder credentials.

Runtime mode retains the original Node coordinator Popen from launch through
poll/wait and normal cleanup. The reviewed Node coordinator invokes the reviewed
Python runtime's `coordinate()` and owns Next/runtime shutdown; the runtime owns
its original exact2GiB WorkerSupervisor, shared admission/provider/coordinator/
executor/media instances, R184 observer, authenticated OWNER context and owned
DB. This helper duplicates none of that fixture. Runtime flags are fixed shared,
media and observer `1`; inherited WSO/PG/DATABASE/NODE and TLS overrides are
removed before the fixed settings and owned PostgreSQL URLs are applied.

The retained Root process publishes an original coordinator creation FILETIME
from its own original HANDLE. Startup90s and ready-to-live1200s ceilings request
the existing durable `shutdown.json` and mark the run failed when crossed. A
cleanup delay, reporting failure or interrupt retains the original Popen until
it actually exits; the helper never looks up a replacement PID or kills owners.
Root should normally stop earlier after the required actual acceptance windows.

The compatibility `root-current-run.json` gains source path/SHA and helper SHA.
An earlier pointer is only replaced if its correctly scoped state folder is
already absent. New `ContextPointer` checks run, exact owned folder/evidence,
source binding and helper SHA. Chrome additionally verifies actual OWNER/shared
context, ready URL and original coordinator identity against the coordinator's
published measurement identity before launching installed Chrome. Chrome is
visible, uses a fresh profile in the owned context, loopback CDP9333 and trusted
TLS, and has no certificate bypass flags. Its original Popen is retained through
actual wait/reap and a separate safe Root receipt. Browser actions remain Root's
GPT web control work. Close Chrome normally before requesting service shutdown,
so its owned profile is released before runtime context removal.

Root receipts include exit/reap, readiness, context removal, source pin equality,
known-private-string occurrence count and observation failure. The runtime's
existing resources/source/DB/coordinator/observer receipts remain the authority
for their respective owners; helper exit0 alone does not replace these checks.
Needles remain in memory and include PG URLs/passwords and recorder serial/user/
password. Scan scope is this run's Root and runtime evidence only; it is known
needle screening, not a proof about unknown sensitive data.

## Exact deferred invocation

From the active worktree, after raw2/raw4 and helper review, Root creates a NEW
schema3 closure including this helper and any read-only tools selected for the
run. Supply its immutable output filename and SHA from Root verification:

```powershell
& '.venv/Scripts/python.exe' '.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/run-media-browser-stage2-owned.py' runtime --source-approval '<absolute NEW schema3 approval path>' --source-sha256 '<Root verified 64-character SHA256>'
```

Retain that helper process/session. Once its ready receipt appears, use a second
retained process/session to launch Chrome with the SAME approval arguments:

```powershell
& '.venv/Scripts/python.exe' '.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/run-media-browser-stage2-owned.py' chrome --source-approval '<same absolute approval path>' --source-sha256 '<same SHA256>'
```

No environment keys need external customization. Fixed keys are
`WSO_TEST_LOCAL_MEDIA_BROWSER`, `WSO_TEST_LOCAL_MEDIA_SHARED`,
`WSO_TEST_LOCAL_MEDIA_OBSERVE`, `WSO_TEST_LOCAL_DEVICE_BROWSER`,
`WSO_TEST_LOCAL_DEVICE_NATIVE`, `WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE`,
`WSO_TEST_LOCAL_BROWSER_INPUT_FILE`, `WSO_TEST_BROWSER_TLS_DIR`,
`WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE/SHA256`,
`WSO_TVT_WINDOWS_LOCAL_INVENTORY_ENABLED/BUNDLE/STAGING/SOURCE_REVIEW/RUNTIME_REVIEW`,
`WSO_TVT_WINDOWS_DECODER_PYTHON`, and the historical W07 acceptance/parent SHA.
Device input is `C:/wso-private/local-device-web/devices.json`. SDK paths use
`C:/wso-private/windows-tvt-sdk-20261003/{package,service-inventory-runs}` and
`source-approved-shared-mux-stage2-v1.json` / `runtime-approved-shared-mux-stage2-v1.json`.
Decoder is the active root's `.superpowers/runtime/windows-media-decode/venv/Scripts/python.exe`.
Only path strings were inspected during this preparation.

## Existing observation tools and exact measurement limits

Keep these historical helpers read-only and include their exact hashes if Root
uses them. No sampler copies or new layers were created:

| Historical helper | SHA256 |
| --- | --- |
| `measure-sql.py` | `66da77d701b026fde820c37a99bd705bd2258fa52e501da0fe6fc9c4c78a27f0` |
| `measure-processes.ps1` | `5b057a6056766db1e077338833ca7a83ffccad7ee54e3ad183ebe03da607a80f` |
| `compose-owner-identities.py` | `6f4db00773a1c2e0bc2c4d40a9f7e702ae86f0fdf9184177333235f997616edb` |
| `browser-observe.mjs` | `6326c0483b14a3d32dfe691fabd16b4f5cdca96de461845b46ed9af14cfb74d1` |

Their folder is `.superpowers/sdd/2026-10-05-multiview-stage1-plan/`.

0016 alters the SAME `wso_private.tvt_local_media_leases` table. The existing SQL
sampler's tenant/actor filters, state/stream counts, PLAYING lease-ID signature,
and CLOSED/cleanup_confirmed checks therefore cover shared viewers. Initial
private-table concern was corrected against 0016; no viewer sampler port gap.
SQL transaction/WAL normalization retains its existing sampled stability,
observer-query overhead and cluster-WAL qualifications.

Shared owner/profile acceptance additionally needs aggregates of
`tvt_local_media_masters` (state, cleanup_confirmed), `tvt_local_media_slots`
(state), `tvt_local_media_walls` (state), and `tvt_local_media_focus_refs` (state).
Use the same uniquely authenticated owned DB and tenant/actor: masters/walls
filter directly; slots join their master; focus refs join their wall. Count and
group states only, keeping IDs/digests/credentials out of exported evidence.
Final wall/master CLOSED, master cleanup_confirmed, slot closure and retired
reference evidence supplement viewer cleanup; a VIEWER-only receipt need not
claim that the still shared native master is already retired. This is a Root
aggregate query task, not missing production API.

The process sampler retains original-announced identity admission and seven
roots plus verified descendants; descendant coverage and common-window CPU
limitations remain qualified. Legacy browser DOM snapshots expose visible
videos' frame/time/dimension progression. Its install instrumentation only
recognizes `/api/live-sessions` starts; shared wall/focus actions use
`/api/live-walls`, so its start/attempt/latency counters cannot establish the
shared rapid-pair acceptance. Use current shared observer and GPT web evidence
for those outcomes. Do not infer twelve presented streams from API success.

## Verification and remaining gates

Fresh command: `.venv/Scripts/python.exe -I -S -`, inline AST parse/compile and
`runpy.run_path(..., run_name='inert_stage2_browser_check')`, with Popen and Path
read/write/mkdir blocked after loading source and unchanged-environment assert.
Result: exit0, syntax PASS, inert import PASS, external operations0, application
launch false. No production imports, private file contents, DB, SDK, browser,
network or application processes were used. No end-to-end or custody runtime
claim follows from these inert checks. Full helper SHA was freshly calculated.

Root pending actions: review frozen helper; confirm real raw2/raw4 receipts;
freeze fresh source closure; execute owned Windows/Chrome acceptance; verify
separate runtime/coordinator/Chrome/DB/source/privacy/observer normal retirement;
update portable canonical reports. No new product question was introduced.

## Fix round 1: preserve callback deadline failure

2026-10-06: Independent initial helper review
`browser-owned-source-review.md`, SHA
`3c3d2f6b263d0b7f6a080c6c52c7b28c94123f8fc57f14c1f507598e395b6e27`,
found C0/I1/M0 against initial helper
`015e0b0ebd3069dcbc384af1db46dab72cfa9e62bde17626f082853e3d031768`.
The initial `failure |= retain(process, tick)` saved the old False before
`retain` ran; `tick` could mark a startup/live deadline failure True, then the
assignment could replace it with False after an ordinary retained exit.

Only that runtime assignment changed. `retained_failure = retain(process, tick)`
now finishes first; `failure = failure or retained_failure` then reads the
current sticky failure. Original custody and durable stop behavior are retained.
The other augmented assignment is Chrome's
`failed |= retain(process, lambda: None)`: its callback never changes `failed`,
so the reviewed dependent-callback evaluation defect is absent there.

Pure AST-extracted actual runtime assignment check before correction reproduced
the defect: callback sets failure True, retained call returns False, actual
assignment leaves failure False (RED observation, command exit0 verifying the
defect). After correction, the actual two statements passed four controls:
callback failure, retained-call failure, clean return, and preexisting failure
(GREEN, exit0). The statements were executed in a pure dictionary with fake
retain/callback; no launcher body or actual process was run. Syntax compilation
and inert import were repeated with blocked Popen/Path read-write-mkdir and an
unchanged environment assertion: PASS, external operations0. No private reads,
application imports, DB, SDK, Kernel, Chrome or child-process execution occurred.

Current fix1 helper SHA is the frozen hash at the top. This author verification
does not grant source acceptance; one scoped I1 re-review remains required.
Root's separately reported raw2 setup failure and normal owned retirement belong
to the raw gate and are not replaced or reclassified by these pure helper checks.


---

## Preserved evidence: browser-owned-source-review.md

# Root-owned Stage 2 browser helper source review

Date: 2026-10-06, Asia/Seoul. Independent, narrowly scoped source review.

## Verdict

**SPEC: correction required. QUALITY: correction required. C0/I1/M0.**

The frozen helper preserves the reviewed runtime composition and original
process ownership, but its final assignment can erase a deadline failure. Do
not use this candidate as the fresh Chrome launch source gate until I1 is fixed
and the changed bytes receive a scoped review. No earlier production source
approval is reopened by this verdict.

## Scope, baseline and authority

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
HEAD: `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, branch authority
`codex/superlive-web-service`. The working tree contains retained, uncommitted
Stage 1/2 implementation and reports; that existing state was preserved.

Reviewed new helper:
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/run-media-browser-stage2-owned.py`.
Fresh filesystem SHA256 matches Root's frozen candidate:
`015e0b0ebd3069dcbc384af1db46dab72cfa9e62bde17626f082853e3d031768`.

Read before review: `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
`AGENTS.md`, current `docs/service-analysis.md`, execution ledger,
`docs/integrations/tvt-local-live-mux-acceptance.md`, browser runtime guide and
`browser-owned-prep-report.md`. The supplied final combined R1 and R188
independent source approvals remain authorities for their existing scopes.
This report examines only the new Root launch adapter and necessary approved
runtime/server interfaces. Root owns updates to portable canonical reports;
this ignored execution report is review evidence, not a competing authority.

Freshly checked unchanged dependency hashes:

| File | SHA256 |
| --- | --- |
| `scripts/test-local-devices/runtime.py` | `54fd494cf05599790460f9f0963253327c075d6bcb3aa4072b0a89c90b43da06` |
| `scripts/test-local-devices/server.mjs` | `598280a1abcb095252e7755181559e52dda213ae1964dcde38e2a076197e6d72` |
| `scripts/test-local-devices/worker_job.py` | `7d2144638b2ce697095b9b90ee05c569dde9dff7920c225d9d01408d95f736b6` |
| `scripts/test-local-devices/observation.py` | `6a473a5f2e0f581f802992b299fddbd438867d05b1b99394e08e75bcd9d6b08f` |

No private approval contents or credential values were opened. The private
native `1f9b7976` / runtime `77eb86a0` identities are prior Root evidence, not
newly verified private-file hashes in this review.

## Implemented purpose and composition

The helper supplies explicit `runtime` and `chrome` modes around the existing
authenticated OWNER fixture. It supplies a new external source approval path
and exact SHA256, selects the shared profile, keeps the original Node or Chrome
Popen object until actual wait/reap, and writes limited ownership receipts.
The approved Node server and Python `coordinate()` continue to own service,
worker, DB, context, native/media composition and shutdown. This adapter does
not implement another service fixture or device grant issuer.

## I1 — Final assignment loses a sticky deadline failure

Severity: **Important**, launch gate blocker.

Evidence: helper lines 175–184, 194 and 200–208. `tick()` modifies the outer
`failure` variable when readiness exceeds 90 seconds or the ready-to-live
ceiling reaches 1200 seconds. It then requests the approved durable shutdown
at lines 185–186. At line 194, however, the code is:

```python
failure |= retain(process, tick)
```

Python evaluates the augmented assignment's current left-hand value before
evaluating its right-hand expression. If `failure` was initially False,
`retain()` runs the ticks and eventually returns False after an ordinary
poll/wait with no caught exception (lines 116–127). Its successful return is
then ORed with the saved initial False and assigned back to `failure`, erasing
the True set inside `tick()`.

Concrete source schedule: valid readiness is published; the live ceiling is
crossed; `tick()` marks failure and writes `shutdown.json`; approved service
owners stop normally; the original Node coordinator exits 0 and is reaped;
`retain()` returns False. With the context removed, source pins unchanged and
no known private occurrences, the Root receipt reports
`observation_failure=false` and the helper returns 0. The startup-lateness
assignment can be lost through the same mechanism. Normal cleanup must not
convert exceeded acceptance ceilings into a successful Root wrapper result.

Minimal correction: evaluate `retain()` into a separate local first, then
combine that result with the **current** `failure` value after it returns.
Preserve the original Popen retention, durable stop and all approved runtime
interfaces. This is a source reasoning finding; no process/test reproduction
was executed under this review's explicit source-only scope.

## Other scoped checks

- Helper lines 54–70 require an explicit absolute approval path in the existing
  approval directory, lowercase full SHA256, unchanged runtime/server hashes,
  the existing `verify_source_approval()` and the helper's own exact closure
  entry. Runtime lines 301–410 retain schema3/shared scope, exact profile,
  private environment/path/hash checks and required source hash checks.
- Helper lines 29–50 clear inherited WSO/PG/DATABASE/NODE and SSL certificate
  overrides before installing the fixed shared/media/observer flags and the
  reviewed private paths. Credential reads occur after approval at lines
  145–153. No new bypass of native/runtime approval or manufactured grant is
  introduced. The schema3 file remains an externally supplied Root authority.
- Fixed paths name `source-approved-shared-mux-stage2-v1.json` and
  `runtime-approved-shared-mux-stage2-v1.json`; they preserve the prior Root
  native/runtime path selection. Runtime validation, not an arbitrary browser
  payload, selects the shared service profile.
- Runtime launch lines 161–194 retain the original Node Popen, obtain creation
  FILETIME through its original HANDLE, publish a safe ownership identity and
  eventually poll/wait that original. The helper delegates fixture cleanup to
  the approved server's durable shutdown and `runtime.coordinate()` rather
  than discovering/replacing owners by PID.
- `ContextPointer` lines 73–101 bind run, exact owned folder/evidence,
  source approval/SHA and helper SHA. Chrome admission compares OWNER/shared
  context and ready URL with the original coordinator identity and the
  server's self-announced measurement identity.
- Chrome lines 215–241 use installed, visible Chrome with a new profile in the
  owned context, loopback CDP, no certificate bypass flags, and the original
  Popen retained through wait/reap. Root must close Chrome before requesting
  runtime/context retirement as the existing preparation specifies.
- Root source/privacy/context and original coordinator/Chrome receipts are
  supplemental. Existing runtime/coordinator resources, DB/source preservation,
  and observer COMPLETE plus matching final digest remain separate acceptance
  gates. Known credential needle screening is limited to this run's exported
  evidence; it does not certify absence of unknown sensitive values.

No additional load-bearing ownership, foreign-context, private-output or
profile-selection finding was identified in this bounded source review.

## Measurement scope that must remain explicit

`0016_tvt_device_media_epochs.py` alters the SAME
`wso_private.tvt_local_media_leases` table used by the historical SQL sampler.
`measure-sql.py` lines 43–60 authenticate owned tenant/actor context and sample
state/stream counts, PLAYING identities and CLOSED/cleanup-confirmed outcomes.
These viewer counts remain applicable to shared mode.

Shared retirement additionally needs wall, master, slot and focus-reference
state aggregates: `tvt_local_media_walls`, `tvt_local_media_masters`,
`tvt_local_media_slots` and `tvt_local_media_focus_refs`. Masters/walls filter
by the same owned tenant/actor; slots join their master and references join
their wall. Export state/count aggregates and cleanup confirmation, keeping
private identities/digests out of the report. Viewer-only cleanup does not
certify that the retained native master has retired. This existing Root query
requirement is not a new product API request or another source finding.

The historical `browser-observe.mjs` video DOM snapshots at lines 150–155 can
observe visible videos' frame/time/dimension progression. Its request
instrumentation at line 65 accepts only `/api/live-sessions`; shared wall/focus
requests use `/api/live-walls`. Its attempted/start/latency counters cannot
establish the shared rapid-pair acceptance. Record actual shared evidence
through the applicable approved observer and GPT browser actions. Neither API
success nor unsupported legacy counters establish twelve presented streams.

## Verification, risks and next gate

Executed verification was limited to direct source/document reads, `rg`
interface searches, existing working-tree/HEAD inspection and SHA256 queries.
No helper import, syntax/test execution, application/Chrome launch, Kernel
query, DB access, private credential input, SDK or recorder operation occurred.
Historical author inert checks and accepted SQL/Windows results were read as
historical evidence only. No production or earlier plan files were edited.

Fix and freeze I1, review only the corrected helper schedule, then Root creates
a fresh exact schema3 closure after the independently qualified raw two/four
gates. Actual Windows service/Chrome acceptance and normal original-owner,
DB/source/context/privacy/observer retirement remain unexecuted by this
reviewer. No new product question arose; the concrete open item is whether the
corrected source preserves the failure set during `retain()`.

Update log: 2026-10-06 — initial frozen helper review saved, C0/I1/M0;
deadline result assignment requires correction before source acceptance.


---

## Preserved evidence: browser-owned-source-review-r1.md

# Root-owned Stage 2 browser helper scoped re-review R1

Date: 2026-10-06, Asia/Seoul.

**SPEC: compliant. QUALITY: approved. C0/I0/M0. Initial I1 resolved.**

## Scope and baseline

This is the single scoped review of the initial I1 deadline assignment and its
direct regression. It carries forward the unaffected findings and limits in
`browser-owned-source-review.md` (SHA256
`3c3d2f6b263d0b7f6a080c6c52c7b28c94123f8fc57f14c1f507598e395b6e27`).
Other production/runtime/Chrome contracts were not reopened.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Baseline remains `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, retained reviewed uncommitted source.
Shared analysis policy was already read; current AGENTS/service continuation,
initial review and updated preparation report were read for this re-review.
Root owns the portable canonical report update; this ignored report is scoped
execution evidence.

Fresh filesystem hashes match Root's fix1 freeze:

| Artifact | SHA256 |
| --- | --- |
| `run-media-browser-stage2-owned.py` | `5c980d3f2769c258c6374b9caa1bf411820437ae95029bb0f9cdd4c76ca3c1fe` |
| `browser-owned-prep-report.md` | `572ad47de45566bffec0653612d6e5e4bb2fcc74eab32d0f7ce0c4ac6baeaff0` |

Both files are in the current
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/` workspace.

## I1 resolution and direct evidence

Helper lines 194–195 now execute:

```python
retained_failure = retain(process, tick)
failure = failure or retained_failure
```

The first statement finishes original-process retention. The second reads the
current `failure`, including any True written by the deadline callback while
`retain()` was running. Normal retirement can no longer erase that callback
failure. A retained-call failure and a preexisting identity failure also remain
failed; a clean call remains clean. The unchanged final receipt and return gate
consume this current sticky value at lines 201–209.

Independent isolated Python verification read only the frozen helper source,
reversed those exact two statements in memory, and obtained the initial helper
SHA256 `015e0b0ebd3069dcbc384af1db46dab72cfa9e62bde17626f082853e3d031768`.
This exact-byte reconstruction confirms that the assignment is the only source
change from the reviewed R0 candidate.

The same verification parsed the current source AST, selected the actual
assignments at lines 194–195 and executed only those statements with fake
`retain`/`tick` in a dictionary. Four controls passed: callback failure with
clean retirement, retained-call failure, clean return, and preexisting failure.
Whole-helper syntax compilation also passed. Command:
`.venv/Scripts/python.exe -I -S -` with the isolated inline AST check; exit0,
output `PASS exact single correction; actual AST statements controls4; syntax`.

The author preparation report additionally records the old actual-assignment
RED observation and blocked inert import/syntax checks. Those author results
were read as supplied evidence; the reviewer did not execute the helper import
or launcher body. Chrome's unchanged line 236 callback is `lambda: None` and
does not modify `failed`, so it does not have this dependent-callback defect.

## Acceptance limits and next gate

No helper runtime body, application import, private input, DB, SDK, Kernel,
Chrome or service launch occurred in this re-review. The only executed Python
logic was source parsing/compilation, hashing and the four pure assignment
controls. No production source or old plan was edited. No new product question
or residual I1 waiver remains.

The original helper's purpose, retained Node/Chrome owners, schema3 gates and
measurement limitations remain as recorded in R0. Historical SQL viewer counts
still apply to the same lease table; shared wall/master/slot/focus retirement
aggregates remain separately required. Legacy DOM video observations do not
provide shared request-attempt/latency counters.

Root reports the first actual raw2 attempt failed during setup. That separate
failure is not reclassified by this pure source approval. Raw telemetry changes
belong to the separately owned raw helper. Actual raw2/raw4 qualification,
fresh exact source closure, service/Chrome execution and normal original-owner,
observer, source/DB/context/privacy retirement remain separate required gates.
Chrome remains held until real raw2/raw4 pass.

Update log: 2026-10-06 — fix1 exact scope and four direct controls verified;
initial browser helper I1 resolved, C0/I0/M0.
