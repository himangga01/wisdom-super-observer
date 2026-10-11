# R203 R1 isolated import correction: independent review

2026-10-10, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0. R0 I1 resolved.**
The corrected source is approved for fresh references and bounded actual
replay. Repaired LOW/HIGH playback and original cleanup still require execution.

## Scope and baseline

Reviewed R1 delta from immutable tree
`e288ed3b78cb5308b20d34eb4f141d154d547895` to
`c4d1e751b0f8f4838f9099b5be8214cd28e1f65a`, in the existing modified
`codex/superlive-web-service` worktree, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Six manifest paths match;
the contract test is retained unchanged and five paths have R1 deltas.

Read with [R0 review and I1 history](2026-10-10-mux-notification-fix-review.md),
[updated author report](2026-10-10-mux-notification-fix.md),
[full-path research](2026-10-10-mux-interleaved-control-packets.md),
[service report](../service-analysis.md), and [AGENTS](../../AGENTS.md).
The shared policy and approved Stage2 stdlib codec requirement remain applicable.
Reuse these reports before changes and refresh after source/actual acceptance;
Root owns canonical handoff updates. Only this R1 report was written.

## Resolution and fresh verification

The service's retained native mux must import its wire codec without installed
site packages. R0 imported the complete N9000 login codec and consequently
required `cryptography`. R1 moves the exact notification length mapping and
header predicate into `local_n9000_notifications.py`, which has no imports.
N9000 imports both under their existing names; mux imports the pure predicate.

Independent `ast.parse`/`ast.dump(include_attributes=False)` comparisons against
the immutable R0 tree passed, exit0:

- Extracted `_STARTUP_BODY_LENGTHS` assignment and `_is_startup_header` function
  are structurally identical to the originals.
- After removing those two original definitions and the new import, the entire
  remaining N9000 AST is identical. Login, crypto and serialization code is
  unchanged.
- Normalizing only the mux import module makes its complete AST identical to
  R0. Strict packet shape, consumed-control handling, typed rejection, frame/
  ACK/cut/credit/clock and authority behavior reviewed in R0 are preserved.
- The new helper contains zero import nodes. All six frozen SHA256 values match.

Fresh isolated gate, exit0: **1 passed, 52 deselected in 1.51s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_mux_notifications.py -q -p no:cacheprovider --tb=short -k native_mux_bootstrap_keeps_stdlib_only_import_boundary
```

The reviewed test launches the actual interpreter with `-I -S -B`, adds only
`packages/core/src`, imports mux and epoch types, and asserts no cryptography,
SQLAlchemy, Pydantic, bridge or contracts module was loaded. This directly
clears the R0 import failure independently reproduced in the earlier review.
R0's 61 reviewer protocol/diagnostic passes remain dated evidence; no broad
rerun was needed for an AST-proven extraction/import correction. The author's
448 focused passes and static gates are reported author evidence, not fresh
reviewer executions. Broad7816 remains RED.

No source edits, new tests, private input, runtime/device/browser/DB work,
agents, commit or source-envelope mutation occurred. Priority is fresh native
references and actual LOW/HIGH duration, stop/reconnect and normal original
retirement. The historical packet's full shape, sustained playback,
twelve-camera capacity and APK parity remain acceptance questions.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_live_mux.py | `18fea85ce19edbc87ca74ef63e254a33e66330e76407e5909585c6a6a82db1b2` |
| packages/core/src/wso_core/tvt/local_n9000.py | `38c7c0f539b062e75d00ca34ae3f79ba548287e607500ee6481bdd6422f82bab` |
| packages/core/src/wso_core/tvt/local_n9000_notifications.py | `96420059fe46a9d0e9d45947acbcf7a719590f5237bcde029ccdfcf3535984f9` |
| tests/tvt_parity/test_mux_notifications.py | `b367d4224f3a2ce9cc075af0559ec93e24ef50a87c6f2abb7faed249db4cf130` |
| tests/contract/test_mux_notification_ingress.py | `63523afa3c021767d0fea7f6306422b40d39dfe80714e63cdaef839591a93ae0` |
| docs/analysis/2026-10-10-mux-notification-fix.md | `98ffb5e5a6da85cf60adbb74081ceea9d0481535b7003ede3c7eccc908ba4da7` |

Update log: 2026-10-10 R1 I1 closure confirmed by exact AST comparison and
isolated import execution; corrected source C0/I0/M0, actual replay pending.
