# R204 grant refresh inner diagnostic review

2026-10-11, Asia/Seoul. Independent **SPEC PASS, QUALITY PASS; C0/I0/M0**.
This verdict approves bounded pre-boundary exception measurement. It does not
identify the actual slot denial or establish repaired HIGH playback.

## Scope and baseline

Implementation worktree: `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, preserving retained uncommitted
Stage1/2/R193-R203 changes. Scoped initial status shows the helper, new grant
test, existing read test and author report untracked; no source/index/HEAD was
changed by this reviewer. Frozen authority is
`r204-grant-refresh-debug-manifest.json` in the established Stage2 workspace.
Compared the helper/read-test delta with accepted R203 R1 review tree
`c4d1e751b0f8f4838f9099b5be8214cd28e1f65a`.

Read shared analysis policy, current AGENTS/service evidence,
[R203 acceptance](2026-10-11-r203-live-acceptance.md), preserved R0/R1 and
diagnostic review history, frozen manifest, actual refresh/binding references,
and final [author report](2026-10-11-grant-refresh-inner-debug.md).

The service supplies authenticated shared SUB/dedicated MAIN through
Core/native/media owners. Historical R203 LOW331s passed, while HIGH169.56s
failed at slot refresh before five minutes. Admission boundary sanitization
removed the inner traceback; those runtime facts were read from canonical
reports, not replayed here.

## Requirement and quality checks

- Optional installation requires exact `SqlMuxAdmission` type and an existing
  `MethodType` whose `__func__` is the original class `_refresh_current_grant`.
  The selected original bound callable is retained and called once with the
  same args/kwargs. A substituted private function is left untouched. This
  helper is not among captured admission/provider binding/receipt identities;
  no production guard or original authority callback identity changes.
- The wrapper catches the original inner failure before outer refresh cleanup
  and `_boundary` sanitization, queues fixed evidence and uses bare rethrow.
  Successful original return is unchanged and quiet. Logger/projection/first/
  capture BaseException is isolated; it adds no current query, SQL/authority,
  grant state/expiry/ID inspection or cleanup invocation.
- Exact transport, slot-retention and viewer grant types select only
  TRANSPORT/SLOT_RETENTION/VIEWER. Unsupported types produce no new event.
  `GRANT_REFRESH_EXCEPTION` uses empty state, fixed public failure code/status
  or unexpected, and the existing heartbeat allowlist/four-chain/eight-frame
  projection. No READ wire fields, locals, messages, credentials or raw values
  are added. The closed codec enforces purpose/result and primitive bounds.
- `sink.first` uses the existing event/identity map and suppression accounting.
  The 127-entry seen map, 127 accepted events plus summary128, lifetime64KiB,
  per-row2048-byte caps and publisher/custody are unchanged. Only checked bytes
  enter the queue; no exception/frame reference is retained there.
- The existing read test's generation-rejection location now comes from the
  first Raise in the actual `_feed` AST, accommodating R203's line movement.
  Its exact module/function/chain and rejecting-generation assertions remain.
  This is in `test_local_media_read_debug.py`, not a wider suppression or source
  codec change. Earlier R0/R1 findings and evidence remain preserved.

No material finding or further source correction was identified.

## Independent verification

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_grant_refresh_debug.py tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_mux_command_debug.py -q -p no:cacheprovider --tb=short
```

**71 passed in0.73s, exit0.** Actual admission refresh/_record controls cover
all three purposes, pre-sanitization ordering, no extra observation on expiry,
same-grant suppression, optional sink faults and successful fresh return.
Existing state/read/heartbeat/numeric controls remain green.

One read-only in-memory `python -B -` probe additionally ran 300 distinct
expired grant failures using actual admission methods and a forbidden-observation
seam: **seen127, final126 rows, 63,444 bytes, omitted175**, exit0. Queue entries
were bytes, all new event states empty, and bounds stayed intact. A substituted
private callable was skipped and preserved its argument/keyword/result identity.
The probe also independently rehashed all four frozen manifest entries.

The author's RED4/GREEN4, final71, Ruff/mypy are reported author evidence, not
relabeled as reviewer execution. No optional broad suite was run; existing
broad7816 RED authority remains unchanged.

| Frozen artifact | SHA256 |
| --- | --- |
| Runtime helper | `a996daa7c14183c30d9a0bb1d25e15b4c0c9161bee0cb2b7fe2bb6d54f61461b` |
| New grant test | `be069980dbd967cf71fe5d0c23c939842648d7c51bd251286039b3b3f06c1fe2` |
| Existing read test | `a3ce626ae2d285c2161ec24039969656300ed781e0c040ad85af1dd993b53b74` |
| Author report | `563c82d9035c969500c3addaeda8895efc2c7d85289e2afe27100ddae8357f4a` |

## Limits and next gate

First-failure suppression, Python identity reuse, finite traceback or queue
saturation can omit later evidence. Diagnostic failure can consume a first
selection without a row; existing failure accounting exposes that limit.
Summary-write accounting/custody caveats remain unchanged. Missing records do
not prove an absence of slot failures.

Only this portable review was written. No production/runtime/browser/source/
private/receipt/pin mutation, real DB/native/hardware operation, commit or
subagent occurred. Root owns AGENTS/service links and fresh reference/source
397-superset validation before actual capture. Identify the original slot
rejection, then select/review the measured correction and rerun HIGH/LOW,
return/Stop/reconnect and remaining store/load gates. No timer/authority
widening or new product decision follows from this diagnostic approval.

Update log: 2026-10-11, frozen R204 SPEC+QUALITY C0/I0/M0 with independent71
tests and300-grant boundedness control. Read before refresh instrumentation
changes; refresh after source or actual owned runtime evidence.
