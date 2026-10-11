# R195 sole legacy MAIN isolation controls: source review

Analysis date: **2026-10-09, Asia/Seoul**. Narrow independent SPEC and QUALITY
review of two fresh ignored controller-helper clones.

**Verdict: C0 / I0 / M0.** The launcher and source-approval builder implement
the proposed schema-2/nonshared control without weakening the retained guards.
No critical, important or minor finding was identified. This approves these
exact helper source bytes; no helper, private metadata gate or recorder test
was executed by this reviewer.

## Authority, baseline and purpose

Read before review: shared `C:/Users/강지혜/.agents/analysis-policy.md`, project
[AGENTS.md](../../AGENTS.md), current canonical
[service report](../service-analysis.md), and the latest schema-2 section of
[the worker-evidence proposal](2026-10-09-dedicated-main-worker-evidence-proposal.md).
The frozen [R194 pin review](2026-10-09-r194-native-pin-review.md) and native/
runtime reviews remain the retained implementation authority. Read this report
with the proposal before changing or reusing the control and refresh actual
evidence after execution/retirement. The controller owns canonical bridges,
fresh approval materialization and the actual CCTV/Chrome comparison.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Fresh branch `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Existing Stage 1/2/R193/R194 source
changes remain retained. Scoped status still reports the previously modified
runtime/server/Windows provider/worker; fresh exact raw hashes match their
accepted R194 bytes. This reviewer edits only this portable report.

The service presents authorized local CCTV channels. Controller-supplied actual
R194 run `6d2c380f` received a MAIN open ACK but its parent snapshot contained
zero parsed MAIN frames. The controller confirmed normal original exit 0/reap
and API/worker/context/source/private/owned-DB retirement before this work.
Those are supplied historical execution facts; private run artifacts were not
read here. A fresh sole legacy MAIN run is the next availability control before
adding worker-before-forward telemetry. It is **not an exact dedicated/shared
coexistence A/B comparison** and cannot alone identify recorder or worker cause.

## Exact helper hashes and deltas

All helper files are under
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/`.
Fresh raw hashes matched:

| Role and filename | SHA256 |
| --- | --- |
| Original launcher `run-media-development-r194-20261009.py` | `307634df575aeb4b317fa8e6106c8410596844385e44f2a206f6ee3b24829fc1` |
| New launcher `run-media-legacy-development-r195-20261009.py` | `2ec0344c3cabd4b625fc38fd18aaedd48d0570bfde82fe2b21cccafaacc82740` |
| Original builder `create-shared-source-approval-r194.py` | `9b0cda9e5d2dea83c92e6f47ffd3862622f3f1f1281ae56b0f0f463fcbc405f2` |
| New builder `create-legacy-source-approval-r195.py` | `5f680faf8fcc2bf8b058fc18a72cf2f43af7a46825c4a558c94c5bc0b4a3bedc` |

An exact byte transformation of each original recovered the corresponding
clone with only the following substitutions. No additional body change occurs.

The launcher has **three** substitutions: module description, removal of the
fixed `WSO_TEST_LOCAL_MEDIA_SHARED:1` entry, and replacement of readiness's
shared-profile equality by `'sharedMedia' in context` in its rejection condition.
That condition rejects any presence of the shared key, including a false or
null value. The environment scrub is unchanged and removes all inherited WSO
flags before fixed legacy values are supplied. Inherited shared/TRACE settings
therefore have no source path back into this launch environment.

The builder has **eight** substitutions: module description, schema version 2,
legacy media scope, omission of `shared_profile`, new legacy approval filename,
explicit shared-flag removal plus media opt-in, summary schema 2, and unique
legacy metadata filename. Both old helpers remain byte-identical.

## Schema, closure and original-control preservation

| Contract | Source assessment |
| --- | --- |
| Exact schema-2 shape | The builder's approval has exactly `schema_version`, `root_explicitly_accepted`, `scope`, `sources` and `private_sources`; version is integer 2, acceptance is true and scope is `owned-local-device-media-browser-only`. `shared_profile` is absent. This matches current `verify_source_approval` for media enabled/shared absent. |
| Mode before validation | The builder explicitly removes `WSO_TEST_LOCAL_MEDIA_SHARED` before `fixture.verify_source_approval`. The launcher supplies media enabled with no shared flag, and strict owned-context readiness requires the shared key absent. |
| Retain full source superset | The existing union of `OWN`, `BORROWED`, `MEDIA_SOURCES`, `SHARED_SOURCES`, imported production graph, native receipt files/dependencies and review/plan references is unchanged. Self and supplied extra helper/report paths remain pinned and validated. The runtime verifier uses a required subset, so retaining shared source pins in a schema-2 envelope is supported. |
| Retain fresh immutable approval guards | Tag validation, project containment, file/symlink/junction checks, current raw hashes, 64-KiB payload bound, exclusive approval creation and unique metadata creation are unchanged. The verifier still validates every supplied source and limits sources to 1024. |
| Retain private/native bindings | Exact native-reference literal `0fb88c6a…`, policy literal `77eb86a0…`, decoder/bundle/staging references, private ACL checks, fourteen-package native review, `ProviderConfig(...,20,runtime_path)` and runtime override checks are unchanged. Actual private files were not opened by this review; their unchanged checks still must execute before device work. |
| Retain private-input ordering and originals | Exact AST equality covers launcher `sha`, `approval_gate`, `original_identity`, `retain`, `runtime_launch`, `chrome_launch` and `main`. Full source/private and self-approval checks still precede private credentials/input and Node launch. Original handles/creation identities, retained waits, durable shutdown and source/private/DB/original receipts are unchanged. |
| Retain run/HTTPS bounds | Acceptance remains 1200 seconds and development 7200 seconds after readiness, with the same 90-second readiness bound and failure retention. HTTPS/CA behavior, trusted Chrome arguments, runtime SHA `2140c035…` and server SHA `598280a1…` remain unchanged. This review selects no new runtime mode or duration. |

Current runtime source selects schema 2 and the legacy media scope for media
enabled/shared absent, omits `shared_profile`, and requires exact three-key
private bindings against environment and file digest. Its source validator
allows the retained superset without weakening any per-source check. Existing
`shared_context(False)` returns no shared key and legacy `media_revision` selects
0015. These are source-supported compatibility statements, not an executed
approval or migration gate.

**Exact findings: none. C0 / I0 / M0.** Application, Core, SQL, codec, native ABI,
provider/worker, parser, timers and authority policies were not changed by these
clones. Worker telemetry remains deferred until the actual availability control
selects a need.

## Fresh verification and actual limits

Two read-only stdin probes used `.venv/Scripts/python.exe -B -`, both exit **0**.
The first printed only the two exact source diffs. The second verified all four
helper raw hashes, exact three/eight byte substitutions, unchanged seven-method
launcher AST, schema-2 approval/private-key shape, before-verification shared
flag removal and unchanged source/ACL/native/runtime guard snippets. All four
helpers parsed/compiled without executing their modules.

The second probe also verified **12 protected raw pins**: runtime, server,
Windows provider/worker, live codec, Core coordinator/admission, public v3
receipt and the frozen R194 native/runtime/pin reviews. All **43** public v3
source/dependency raw byte/hash bindings remain current. Thus the application/
native bodies and prior source reviews remain the accepted R194 bytes. The
historical 336-source runtime envelope was not read, rewritten or reused as a
legacy approval.

No optional tests, helper execution, actual private source/native approval,
private live input, DB/SQL, SDK/native child/Job, browser, source/test/index/HEAD
mutation, staging, commit, push or nested agent was performed. The builder's
actual native files/dependency counts and private ACL/manifest/runtime checks
remain controller execution gates. The initial controller clone attempt's
CRLF expectation was reported as failing before writing the new builder; the
current exact LF byte comparison succeeds and old helper hashes are preserved.

## Next gate and interpretation limits

The controller may now create a fresh schema-2 approval with the exact two new
control files, proposal and this review included as reviewed extra paths, then
run the unchanged source/private/native metadata checks. Any mismatch blocks
device work rather than selecting a weaker guard. A schema-3 shared approval
must not be used merely with its shared flag removed.

After those gates, the authorized sole legacy MAIN Chrome test can establish
availability on that path under its actual recorder/profile conditions. It
does not isolate the dedicated/shared coexistence variable. Success or failure
does not alone prove SDK forwarding, recorder silence, native-slot contention
or the cause of prior zero-parent-frame evidence. If ambiguity remains, the
separate reviewed worker-evidence proposal selects the next measurement.

Open questions remain actual sole MAIN frame delivery and whether that result
warrants worker telemetry. No twelve-camera, sustained shared performance,
repaired MAIN, first unexpected SUB close cause or APK parity acceptance follows
from this source verdict.

Update log: 2026-10-09 — narrow R195 two-helper source gate C0/I0/M0; exact clone
deltas, schema-2/control shape, unchanged original guards and protected/public
closure hashes verified. Fresh approval materialization and actual sole MAIN
acceptance remain controller-owned. Freeze this report after its final hash is
supplied.
