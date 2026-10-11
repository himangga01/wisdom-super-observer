# R209 dedicated refresh barrier: independent review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0.** No source
findings in the frozen Core scope. Approved for composition with separately
reviewed frontend work, fresh references and actual replay. This verdict does
not establish normal worker cleanup, full service acceptance or the cause of
historical spontaneous HIGH failures.

## Baseline and scope

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, retaining uncommitted
Stage1/2/R193-R208 work. Scoped source/tests remain untracked relative to HEAD.
All four paths match `r209-refresh-barrier-manifest.json` in the Stage2
workspace. Concurrent frontend work is outside this review and was not edited.

Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[dedicated race map](2026-10-11-dedicated-refresh-race-causal-map.md),
[R208 actual report](2026-10-11-r208-live-acceptance.md) and
[author report](2026-10-11-dedicated-refresh-barrier-fix.md).
Reuse before current/refresh changes and update after source or acceptance.
Root owns canonical handoff updates. Only this review was written.

The service maintains a dedicated MAIN original while shared base grants
refresh. R208 measured direct false during ACTIVE base refresh with version
change; public retries preserved playback. Its two HIGH intervals passed
309.091298s and314.603772s without spontaneous termination. Therefore actual
reachability of the transient observation is established, while attribution of
earlier terminal HIGH/slot failures remains unresolved. Deterministic controls
separately demonstrate the unsafe direct/sweep/native-supplier outcome.

## SPEC assessment

- Public `current()` creates the existing monotonic five-second deadline and
  now passes it through `_current_once` into dedicated current. Direct calls
  get at most the same five-second window; nested public calls take the earlier
  deadline. The loop never refreshes that deadline on a retry.
- Dedicated current validates exact registry membership, retained master,
  ACTIVE state and absence of Stop/start/shutdown under the existing short
  lock. It snapshots shared refresh version and dedicated focus version.
  Waiting on the retained master's `refresh_done` occurs outside the registry
  lock, in at most50ms clips of the remaining window. The refresh owner thread
  returns false instead of waiting on itself.
- After actual authority observation, late completion fails the caller deadline.
  Stop/shutdown/retained identity/master state are checked again. A refresh
  publication superseding the observation triggers a fresh check, not success.
  Stable refresh plus unchanged focus returns only the original authority
  result. Focus replacement also triggers observation again, with the existing
  two-change limit retained. Unknown, expired, revoked or retired authority is
  never replaced with a grace-period true value.
- The barrier lives in `_current_dedicated`, so sweep's direct call, the
  retained native session's supplier and the post-maintenance direct check
  all use it. It covers a refresh entered before or during those observations.
  No native callback, SQL predicate, lease TTL, grant expiry, queue/capacity,
  issuer identity or cleanup receipt is changed.
- Lock ordering remains the existing one: no registry lock spans SQL/authority
  callbacks or the Event wait; heartbeat can acquire the lock to publish new
  grants and signal completion. The deadline bounds waits and acceptance;
  it does not forcibly preempt an already-running external authority call.
  Such a call returning after deadline is rejected.
- Exact preimage SHA256 `c324bc1e...` was verified. AST comparison proves only
  `current`, `_current_once` and `_current_dedicated` changed. Admission,
  0017 and runtime body still match accepted hashes `9ca1bef6...`,
  `7d920845...` and `7745e95d...`. `_current_dedicated_once` retains the prior
  strict rights/lease/original-custody/focus checks.

## Fresh independent verification

Reviewer command, exit0: **22 passed in0.63s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_dedicated_refresh_barrier.py tests/tvt_parity/test_dedicated_refresh_interleaving.py tests/tvt_parity/test_main_return_continuity.py -q -p no:cacheprovider --tb=short
```

The12 new barrier cases cover direct observation, sweep and native supplier
across controlled refresh entry/completion, outside-lock publication, real
Stop/shutdown/revocation, owner-thread reentry, caller deadline and slow valid
observation that finishes too late. Six RETURN controls preserve exact pending
handoff and genuine negative outcomes. These use actual coordinator methods
with inert authority/native ports and real Python synchronization; no live SQL
or recorder execution is implied.

Four older inert controls remain explicit **unsafe single-observation
comparisons**. Their retained preimage matches prior `ad7a0199...`; reviewed
edits rename the description and invoke/route `_current_dedicated_once` for the
historical unsafe schedules. They are not passed off as repaired production
behavior. The new tests exercise the repaired barrier separately, and the
genuine-revocation close control remains in place.

Author watched9 RED then12 GREEN,124 Core cases,43 diagnostics and static gates
are retained author evidence, not rerun wholesale. The targeted fresh reviewer
execution is reported separately above. No optional broad suite or fresh SQL
gate was added for unchanged SQL/admission source.

## Actual limits and remaining work

R208's benign public-path retries and two HIGH duration passes do not prove this
patch repaired earlier spontaneous terminal failures. The prior R203169.56s
slot-refresh condition remains unmeasured, and the R207 late HIGH initiating
branch is not retrospectively selected. Historical LOW drops remain measured
performance evidence rather than a zero-drop claim.

R208 manual Stop produced wall200/session404 response order and worker shutdown
stalled. Exact-original worker termination exit97 and coordinator exit1 ended
that run exceptionally; context/owned DB/source454/private0 cleanup does not
convert workerSettled=false/FAILED into normal COMPLETE. Earlier5dd exceptional
history also remains separate. The disjoint frontend Stop correction requires
its own source review; it is not approved by this document.

After combined reviewed closure, actual LOW/HIGH duration, transitions,
Stop/reconnect/store2 and normal original worker cleanup are still required.
Broadpytest/runtime typing, twelve-camera/APK and release/publication gates
remain open. No source/test/frontend/canonical/runtime/DB mutation, hardware,
browser, private input, nested agent or commit occurred during this review.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `f12f1c4d4c55956f67cc94fb4e96a01992fbbe1afd4dbb9732f7c3d2543d2fc1` |
| tests/tvt_parity/test_dedicated_refresh_barrier.py | `6eff36e456d098c074f829b02f8ced31283fc25f5608cb8ea7b282c1a91a95ca` |
| tests/tvt_parity/test_dedicated_refresh_interleaving.py | `28219afee32629b4b8b5a33e12e7e98524f8a1f16f4f7bf85400d9bd232379d1` |
| docs/analysis/2026-10-11-dedicated-refresh-barrier-fix.md | `8ee08512b411f30e4447b9e41b28c453c1d5bba4548f4056ec6749f70e55c212` |

Update log: 2026-10-11 frozen R209 SPEC/QUALITY C0/I0/M0 with22 independent
targeted passes; combined source and actual normal-cleanup acceptance pending.
