# R206 attached focus cleanup: independent SPEC and QUALITY review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0.** No source
findings in the frozen six-path candidate. Approved for fresh references and
actual replay; successful RETURN and normal worker cleanup remain execution
gates, not results of this review.

## Scope and baseline

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted
Stage1/2/R193-R205 changes. The group and diagnostic source paths are untracked
relative to HEAD. All six current hashes match
`r206-attached-focus-fix-manifest.json` in the established Stage2 workspace.

Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[exact CDP/source diagnosis](2026-10-11-stale-forward-focus-cancellation.md),
and [author report](2026-10-11-attached-focus-cleanup-fix.md).
Reuse before focus/diagnostic changes and update after source or acceptance;
Root owns canonical handoff reconciliation. Only this review was written.

The service's browser group coordinates authenticated shared SUB and dedicated
MAIN ownership. Run5dd measured RETURN200, old-FORWARD-settle404, new-RETURN-
settle200, wallSTOP200 and MAINStop504. Old-reference equality was confirmed
by the lead's CDP projection. R206 addresses that frontend cancellation error;
R205 backend retention fixes and the older R203 slot failure remain separate.

## SPEC assessment

- Production group change is only removal of the completed record inside
  `attached()`, after its existing exact-record and `isUsable()` checks.
  Those checks require a current pending reference, no closing promise,
  unexpired reference and unfenced/undisposed group. The real caller additionally
  requires the exact current replacement player, nonclosed player and accepted
  lease. Removal occurs synchronously after timer clearing; no asynchronous
  interval lets attachment discard a different cleanup owner.
- In-flight cancellation sets `closing` and clears pending before attachment
  can act; late attachment then fails `isUsable()` and cannot remove the record.
  Timer expiry, canceled/late reservation and rejected original settlement keep
  their existing records/promises. There is no blanket `pending=false` skip,
  no404-as-success handling and no failed-promise replacement. Stop All still
  waits its actual pending operations and original wall cleanup.
- Removing positively attached metadata prevents `onStop` from launching an
  invalid new cancellation of consumed old FORWARD. The original player Stop
  promise remains independently tracked and blocks LOW until settlement.
  Pending RETURN still has its own timer, source/direction identity checks and
  cancellation path. The new wall control tests model server rejection of the
  exact obsolete FORWARD reference while allowing the new RETURN to proceed.
- The API logger adds only `focus_settle`, `wall_heartbeat`, `wall_stop`, chosen
  by equality with three fixed route templates. The caller supplies trusted
  `APIRoute.self.path` (`local_media.py:106`), not a raw request URL. Substituted
  paths cannot select these new labels and neither template nor identifier is
  serialized. Fields/schema, exception behavior, default-off sink,1024-byte
  row,128-row and64KiB caps are unchanged.
- Reversing only the three inserted attachment lines restores the exact group
  preimage hash `6bff8ed41244c957567f7db2e1a2ecb79085e855331222eec4b4365a2c89342a`.
  R2050017/admission/coordinator hashes still match the accepted R205 manifest.
  Strict startup/settlement/current bounds, SQL, native custody and timeouts
  are untouched.

## Fresh independent checks

All commands exited0, using installed local executables without installation:

```powershell
# apps/web
.\node_modules\.bin\vitest.CMD run tests/live-wall-group.test.ts
# 17 passed
.\node_modules\.bin\vitest.CMD run tests/live-wall.test.tsx -t "returns confirmed MAIN|test_last_tile_focus_and_return|test_expired_focus|test_return_cannot|test_ten_rapid_requests|cancelled late reservation|expires the original focus"
# 7 passed, 55 excluded by selection

# implementation worktree root
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_local_media_diagnostics.py -q -p no:cacheprovider --tb=short
# 11 passed in0.60s
```

The35 fresh controls cover obsolete attached cancellation, exact in-flight
rejected cleanup retention, held original Stop, expired focus, late canceled
reservations, rapid requests, failed RETURN and fixed diagnostic privacy/caps.
The wall tests use the existing rendered component/runtime with fake players
and API ports; they are not actual Chrome/native acceptance.

The author's watched causal group RED1 then GREEN, API template RED then GREEN,
86 related web passes, mypy/Ruff and Next type generation/tsc are reported author
evidence, not independently repeated wholesale. The two changed old assertions
correctly stop expecting cancellation of a completed transfer; the failed RETURN
case still asserts original player leases settle. No source mutation or frozen
preimage rollback was used for reviewer tests.

## Actual limits and priorities

Both preceding runs are retired, but their retirement evidence differs.
Run4b's normal retirement must not be used to qualify run5dd. Run5dd required
exact-original exceptional worker termination exit97; its coordinator reaped
exit1. Context/ownedDB/source/privacy outcomes are retained, but workerSettled
is false, observation is nonterminal and a final worker Job receipt was not
persisted outside the removed context. This remains FAILED exceptional cleanup,
not normal COMPLETE; the exact cleanup wait remains unmeasured.

Next priorities are fresh immutable closure, actual early LOW/HIGH/RETURN,
then duration/rapid-switch/Stop/reconnect/store2 and explicit normal original
worker cleanup. Historical R203169.56s slot denial, twelve-camera/APK gates,
broad7816 RED and historical runtime typing limits remain open. Source C0 does
not settle these questions. No DB/hardware/browser/runtime operation, private
input, source/test edit, nested agent or commit occurred during this review.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| apps/web/src/lib/tvt/live-wall-group.ts | `47d64ee6fd3a8c0c6e9c0d4dd1a8ef501bc7e52e928b13a8c145f3cb2255cdc9` |
| apps/web/tests/live-wall-group.test.ts | `e2f1d5729bacad2b2d5ea73e93174f17c16fee426e5ffdc86dfaca9f36e1b509` |
| apps/web/tests/live-wall.test.tsx | `acbec61323b5cd2d71fa457c865b16ebd18118b6a5f0015467c357a734298941` |
| services/api/src/wso_api/tvt/local_media_diagnostics.py | `e559499ad0f15cdc759777edf9b5a80cc8e96efb2f1ef69e58025c996bf96920` |
| tests/tvt_parity/test_local_media_diagnostics.py | `b1264a35a025789f371dfd166e59a6c4a6f1efb3482ce18e2ced324c31c39ff0` |
| docs/analysis/2026-10-11-attached-focus-cleanup-fix.md | `71b675403958603fc72b6dea175936c96cda11608f7d6ae8e6a781add39e98a2` |

Update log: 2026-10-11 frozen R206 SPEC/QUALITY C0/I0/M0 with35 independent
targeted passes; actual RETURN and normal cleanup acceptance pending.
