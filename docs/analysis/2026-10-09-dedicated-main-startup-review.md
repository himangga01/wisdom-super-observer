# Dedicated MAIN startup authority correction: scoped source review

Analysis date: **2026-10-09 (Asia/Seoul)**. Review R193/R193a, round 0.

**Verdict: C0 / I0 / M0.** The five-file correction satisfies the scoped
startup-authority and original login-BUSY requirements. No critical, important
or minor finding was identified. This verdict approves the reviewed source
delta; it does not establish actual SQL, native or repaired Chrome acceptance.

## Authority, baseline and scope

Read before review: shared `C:/Users/강지혜/.agents/analysis-policy.md`, the
implementation worktree's [AGENTS.md](../../AGENTS.md), the canonical
[service report](../service-analysis.md) R193/R193a rulings, relevant original
shared-recorder plan contracts, the
[diagnosis](2026-10-09-dedicated-main-startup-diagnosis.md), and final
[author report](2026-10-09-dedicated-main-startup-fix.md). Review and verification
skills were applied. The controller owns canonical report/instruction bridges,
receipt refresh and actual execution; this reviewer writes only this report.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch: `codex/superlive-web-service`. Actual HEAD:
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial working-tree status contained
extensive retained Stage 1/2 tracked modifications and untracked source, tests
and reports. They were preserved; the primary checkout is not this baseline.

Frozen review package:
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/task-1931-review-r0.diff`.
Baseline tree: `225f9786f273fd6276ac3f1fed50835a912cf3bb`.
Candidate tree: `86cfe44397475c672be5a9b3ef44614d07781bf4`.
These are source snapshot trees, not changes to actual Git HEAD. The packaged
source/test delta has **five files, 576 insertions and four deletions**. Additional
documentation changes between the snapshot trees were outside this assigned
five-file review. No whole-branch or unchanged Stage 2 re-review is claimed.

Freshly verified reference SHA256 values:

- Diagnosis: `5b078f74f5c089052febf9ca3f3abc09ac1c17a439aa9e2b3f2cd0582aeaaa30`.
- Final author report: `b628e87d6f3214de1846ca837bb87ac02a79b27f3328eb30dd50dbcc700375ef`.

| Reviewed file | Frozen raw-file SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `f48373ce7861106a72901165177fede2d3da31a0a7ff9d658a2c16d29398cf33` |
| `tests/contract/test_dedicated_main_startup_authority.py` | `a6a3d4fceca2529013ee1333ee1ebc5d0e517b212481a80870af62400d4d5682` |
| `tests/contract/test_local_live_mux_provider.py` | `a15803b23f3c9b9085bc3bbd42ce348442eb182676fb2b88c078bf9b0fc71a51` |
| `tests/integration/test_local_media_mux_admission.py` | `b1ed2895f230cf41368640fcca4e3f5ab9b2f324e1db17d0df8699ed42d21899` |

All five current raw hashes matched the supplied frozen manifest. Current source
also matched candidate Git blobs after newline normalization. The provider and
existing provider-test working files use CRLF while their candidate Git blobs
use LF; the other three matched raw blob bytes. An initial strict raw-blob
equality assertion stopped before controls; the corrected comparison verified
that newline conversion was the only difference. Raw-file receipt hashes were
checked separately and were not normalized.

## Service purpose, cause and reviewed implementation

The service presents authorized recorder channels in Chrome. Shared SUB viewers
retain recorder master/slot custody; MAIN uses a separately owned native original
under a pending FORWARD focus. Selection/claim, native startup/proof, SQL
activation, focus settlement and activated media authority remain distinct.

Historical controller evidence from retired `ba37feae` establishes SUB PLAYING
200 with 330 decoded frames before HIGH focus 200 and SUB stop 200 were followed
by MAIN RPC 404 at prepared startup. The diagnosis's actual-source inert probe
established the cause: `CLAIMED` startup queried activated-only `media_observe`,
received NULL and acquired a sticky denial before native review/resources.
This reviewer did not repeat the historical browser or retirement execution.

The new admission port at `local_media_mux_admission.py:429` uses existing
`_selection`/`0016 VIEWER_SELECTION` for the correct LOGIN/CLAIMED startup phase.
The provider startup callback and immediate handoff postcheck use that port;
later coordinator activation and normal hot current remain unchanged.

## Requirements and findings

| Requirement | Review evidence and assessment |
| --- | --- |
| Exact retained lease and known denial | `_known_lease` preserves exact issued object, worker, cleanup/master denial, tombstone and sticky hot-denial checks before and after selection. |
| Same dedicated custody, registration and original issuers | `_dedicated_owner` retains exact viewer and unchanged native/viewer receipt methods. The new guard compares retained UUID registration and worker scope and rechecks custody object identity around issuer calls and SQL. |
| Complete MAIN selection | Exact `LocalMediaChannel` type, MAIN stream and equality with the validated complete SQL selection cover GUID, raw/window index, ordinal, kind and stream. |
| Current SQL actor/session/wall/focus/master/channel authority | Existing selection performs locking LIVE, wall scope, pending FORWARD focus, current master and complete lease/device/secret/channel predicates. No SQL body or global OBSERVE predicate changes. |
| Registration qualification | Selection requires registered CLAIMED MAIN but does not project SQL registration. Equality relies on the existing one-shot `DEDICATED_REGISTER` plus retained registration; neither source nor report claims direct equality from an unreturned field. |
| Bounded checkout and caller budget | `_sql` completes its short transaction before returning. Budget and local custody are checked around selection. Existing native cancellation/deadline/stopping and cleanup paths remain present. |
| Preserve activated authority | Startup success does not create a hot entry or activate/settle focus. Existing hot denial remains sticky; the new composed test exercises activation followed by revocation. |
| Normal startup rejects settled owners | Any original-native receipt or viewer receipt denies normal startup, including changes occurring during SQL. |
| R193a original BUSY only | Provider captures the same `close_native` return, then calls unchanged original-result recovery. Only proven recovery with protocol/closed failure supplies the optional receipt for refusal classification. |
| Exact retired readback | The receipt must be the same issued `EpochCleanupReceipt`, REAPED, bound to exact lease ID, worker and native generation, with unsettled viewer and all normal selection/registration/budget/denial checks. There is no boolean bypass. |
| Native I/O cannot use retired readback | The nested native callback supplies only `budget`. The optional receipt appears only after close and proven original BUSY recovery. Readback neither restarts native I/O nor grants live authority. |

**Exact findings: none.** No source correction is requested by this review.
The new provider fixture delegates startup to its existing current overrides,
preserving their negative controls. The eight added SQL cases are appropriately
guarded and qualify real SQL separately from the inert phase model.

## Fresh reviewer verification

Executed from the implementation worktree:

```powershell
& .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/contract/test_dedicated_main_startup_authority.py
```

Exit **0**: **24 passed**, no failures or skips, pytest duration **0.10 s**.
The real admission/prepared/native-run composition reached the inert review
sentinel with zero SQL checkout. That sentinel stops before native review,
manifest/ACL/staging/process work. The other cases exercise sticky hot denial,
invalid startup, after-query budget/custody changes and original BUSY readback.

An independent stdin probe executed with `.venv/Scripts/python.exe -B -` reused
only the inert fixture edges and called the production startup guard. Exit **0**:
**11 denial controls passed**. Each GUID/raw index/window index/ordinal/kind/
stream mismatch denied. Same-issued synthetic REAPED receipts with wrong worker
or native generation denied, as did a boolean receipt. Native issuer replacement
and original closure during selection also denied. Every result was exactly
`LOCAL_DEVICE_DENIED` 404; all checkouts returned to zero, no hot entry was
seeded, fixture cleanup settled and no native child or Job was created. The
receipt substitutions are explicit synthetic controls, not native reap evidence.

The independent probe also verified the frozen raw source hashes, normalized
candidate source equality and final diagnosis/author report hashes. Python
bytecode and pytest cache writes were disabled. No application source/test,
index, HEAD/ref, DB, native original, browser, private input or receipt was changed.

Author-reported **92 focused passes**, Ruff/format on five paths, strict mypy on
two production paths and **eight SQL cases collected only** were read and remain
author evidence. They were not rerun or promoted to fresh reviewer SQL/static
results. The reviewer gate intentionally stopped after the meaningful scoped
inert checks above.

## Declined scope, remaining risk and acceptance limits

Unchanged Stage 1/2, unrelated frontend/debugging, broad suites, DB/native/browser
execution, source/index/HEAD mutation, guides and public/native receipt pins were
outside this review. Only this review report was written. The controller records
its path/read-before-update-after bridge in AGENTS and the canonical report.

Priority P1 remains the controller's owned SQL eight-case gate, then source/native/
runtime receipt refresh and a new bounded actual SUB PLAYING to HIGH MAIN
start/offer/PLAYING to return/stop run with original cleanup. The fake engine
does not execute PostgreSQL predicates, locks, roles or current revocation data.
The sentinel and modeled receipts do not establish Windows SDK startup, actual
login-BUSY recovery, native reap, MAIN formats or presented-frame advance.
Existing receipt pins do not authorize the changed source until refreshed by
the controller. Twelve-camera, duration/performance and APK comparison remain
separate open acceptance gates.

No new product question blocks this source correction: the already approved
MAIN transfer behavior is clear. The remaining question is whether actual guarded
SQL and recorder/Chrome execution satisfy that behavior with the refreshed
authority. Historical failure/retirement receipts remain evidence and are preserved.

Update log: 2026-10-09 — scoped R193/R193a SPEC+QUALITY review completed with
C0/I0/M0, 24 fresh causal passes and 11 independent denials; frozen source hashes
verified, actual SQL/native/Chrome acceptance not claimed. This report is frozen
for controller authority refresh after its final hash is supplied.
