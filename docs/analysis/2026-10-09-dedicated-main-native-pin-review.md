# Dedicated MAIN: native receipt pin and launcher source review

Analysis date: **2026-10-09 (Asia/Seoul)**.

**Verdict: C0 / I0 / M0.** The two native receipt pin values, fresh public
source receipt, two guide appendices and one launcher filename substitution
satisfy this narrow source gate. No critical, important or minor finding was
identified. This review does not create private native/runtime approval or
establish repaired recorder/Chrome acceptance.

## Authority and baseline

Read before review: the shared analysis policy and worktree
[AGENTS.md](../../AGENTS.md), canonical [service report](../service-analysis.md),
frozen [R0 startup review](2026-10-09-dedicated-main-startup-review.md),
[R1 fixture review](2026-10-09-dedicated-main-startup-review-r1.md), current
author/diagnosis references, the v2 public receipt and appended guide sections.
Controller evidence supplies the latest owned-SQL outcome. Prior production
reviews and historical receipt files remain frozen.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch `codex/superlive-web-service`, established HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained extensive Stage 1/2
modifications and untracked source/tests/reports. Pre-pin snapshot tree:
`fbc7c55645cf6e784a1226b1ecd3ba13c504e481`. No application source, index,
HEAD/ref, DB, SDK/native original, browser or private approval input was changed
or executed by this reviewer. Only this separate report is written. Controller
owns canonical report/AGENTS bridges and future approval/execution.

The local service presents authorized CCTV channels. Reviewed R193 startup
authority admits exact current dedicated MAIN before activation; later hot
authority remains separate. These pin changes bring its reviewed source bytes
into the public closure consumed by the existing native review gate. The native
provider's execution and retirement behavior are otherwise unchanged.

## Exact reviewed changes and findings

`windows_socket.py:57` changes `LIVE_RECEIPT` from the historical v1 path to
`docs/integrations/receipts/tvt-local-live-mux-stage2-source-v2.json`.
Its accepted SHA256 at line 62 changes from
`96aa2b0a979fb22f286a72699a5d2eec18cf3544863c216fe5bef94fe2387a02` to
`0aec9097b0e132e34532dbcbfc0681da62f2e21a222ab972a302a0948efb0879`.
Full normalized-source equality against the pre-pin snapshot proves these are
the **only two changed values**; neither native code nor other pins changed.
Current raw Windows-provider SHA256:
`32cd642a8e2ec74a7afefdaae14c365ad89a016db5ac21337e291bd5c4dae2cd`.

The v1 receipt remains byte-identical at its historical hash above. The fresh
v2 receipt matches its pinned raw hash and all **20 file / 11 dependency**
entries match current raw byte counts and SHA256 values. Its closure includes
reviewed admission/provider/tests, the updated guides, unchanged SQL/hot/Core
source, and the diagnosis, author, R0/R1 and prior combined-review dependencies.
The reviewed R193 admission/provider and both other contract tests remain at
their frozen R0 hashes; the R1 integration and author hashes also match.

The receipt status remains
`SOURCE_ACCEPTED_WITH_EVIDENCE_QUALIFICATION_UNPUBLISHED`. Actual shared
recorder-frame, Windows-profile and Chrome-acceptance flags are all **false**.
Its qualification explicitly leaves repaired MAIN/Chrome, twelve-camera
duration/performance and APK equality unestablished. Zero source findings and
references to accepted R0/R1 reports accurately describe the reviewed gates;
they do not promote them to actual native/browser evidence.

The admission and provider guides are append-only relative to the pre-pin tree.
Their appended R193 sections correctly describe the narrow startup predicate,
unchanged activated cache, same-issued REAPED BUSY readback and one-shot SQL
registration qualification. They record controller run
`7b616a1a2e7b4256b1674ee86de8ea37`: exit 0, **8/8 SQL cases passed**, no errors
or skips, normal original/owned-DB/source/private gates and known private
occurrences zero. Earlier `e592dd93` fixture setup failure is preserved. The
appendices explicitly state that source/SQL qualification does not establish
repaired recorder/Chrome or twelve-camera proof. SQL results are controller
evidence supplied for this review; the reviewer did not inspect private run
inputs or execute PostgreSQL.

The ignored launcher clone has exactly one byte-level substitution:
`source-approved-shared-mux-stage2-v1.json` becomes
`source-approved-shared-mux-startup-r193-v1.json` in its privateSourceReview
filename. The original R192 launcher remains unchanged at
`7550ad67bac19eff2965927a55627fe6319e5dfdaff3cbbeba489405e13f7ec4`.
The new R193 launcher is
`5bc91257e9dccf4a2c1e012aa0a771336b22db1bc2e090907d36ae3cd87af562`.
No broader launcher review or changed runtime behavior is claimed. Neither
launcher nor the referenced private approval file was executed or inspected
as runtime input.

**Exact findings: none.** No further source edit is requested by this gate.

## Fresh verification and limits

Two successful read-only stdin probes ran through
`.venv/Scripts/python.exe -B -`, both exit **0**. They checked exact source
substitutions, historical/new raw hashes, all 31 closure byte/hash bindings,
source qualification flags, retained R193/R0/R1 hashes and append-only guide
qualification. `ast.parse` and `compile(..., 'exec')` succeeded for the Windows
provider and the new launcher without executing either module. An initial
probe reached a Windows default-encoding error while reading guide text; rerun
with explicit UTF-8 completed successfully. This was a probe read issue and
caused no source or runtime mutation.

No tests, database fixtures, SDK calls, native children/Jobs, private approval
files, live inputs or Chrome sessions were run or read. No optional suite or
unchanged Stage 1/2 source review was added. Frozen prior report hashes remain
`c3102fe63391fc882d2c2521f60bec097cb8df9d053f660a0942120f38e28449` and
`01c5f1e066bed40d53a4991f2d9b51d0ac158a67ebb82f5662ae284da9e2571c`.

Priority P1: controller creates the separately qualified private native/runtime
approval closure for these exact bytes, then executes bounded actual MAIN
start/offer/PLAYING, return/stop and original cleanup. Source pin approval alone
does not establish manifest verifier runtime acceptance, SDK MAIN formats,
native BUSY/reap, presented-frame advance, twelve-camera capacity or APK parity.
No new product question is introduced by the receipt and filename changes.

Update log: 2026-10-09 — narrow source gate C0/I0/M0; exact pin/launcher deltas,
31 current raw closure bindings, retained historical receipt/report/source
hashes and source/SQL qualifications verified. Actual MAIN/browser acceptance
remains open. This report is frozen after its final hash is supplied.
