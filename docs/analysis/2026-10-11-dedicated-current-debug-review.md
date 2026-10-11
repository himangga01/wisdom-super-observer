# R208 dedicated maintenance diagnostics: independent review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0.** No source
findings in this frozen runtime-only diagnostic scope. Approved for fresh
references and bounded cause measurement, not for an actual-cause or repair
claim.

## Baseline and scope

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted
Stage1/2/R193-R207 work. The runtime helper/new test paths are untracked
relative to HEAD. All four paths match `r208-dedicated-debug-manifest.json`,
whose SHA256 is
`6292d10b7f72ab9e80af9bb447f0f483e7ecbd4d0fb3742e0ee3dd593b5f5789`.

Read shared policy, [AGENTS](../../AGENTS.md), [service report](../service-analysis.md),
[R207 actual report](2026-10-11-r207-live-acceptance.md),
[dedicated-refresh causal map](2026-10-11-dedicated-refresh-race-causal-map.md)
and [author report](2026-10-11-dedicated-current-debug.md). Reuse before hook/
maintenance changes and refresh after source or actual execution; Root owns
canonical handoff updates. Only this review was written.

The service maintains dedicated MAIN authority and its original native session
alongside a retained shared base. R207 early RETURN and LOW311.638506s passed,
with280 additional browser drops. Long HIGH failed after a131.65s video sample;
peer explicit close was around145.58s and the first public current=false already
showed MAIN stopping/closing. Original73eaf/exec99535 retired normally with
source441/private0. Those facts motivate earlier direct-method observation;
the initiating branch remains unmeasured.

## SPEC and behavior preservation

- Installation adds only exact original bound methods on exact
  DeviceEpochCoordinator/SqlMuxAdmission classes. `MethodType` and original
  `__func__` equality are checked; substituted methods are skipped. The wrapper
  retains the original callable and invokes it once with unchanged positional
  and keyword arguments. Return values pass through; exceptions use bare
  rethrow and preserve identity. Optional snapshot/first/capture failures are
  isolated and never replace the original result or error.
- `DEDICATED_CURRENT` and `MAIN_RETENTION_CURRENT` capture only first false or
  exception per existing private identity key. True results remain quiet.
  `DEDICATED_CLOSE` captures its first ENTRY before the original changes
  stopping/closing flags. It does not initiate extra close, current, SQL or
  native operations. The safe call-chain projector identifies original callers
  without retaining arbitrary locals, messages, IDs or credentials.
- Dedicated refresh entry facts come from exact typed DedicatedRecord and
  OriginalConstructorRecord fields. Entry flag/version are read before the
  original call; `refresh_changed` is compared immediately on return/exception,
  before publishing. The two exported fields are closed booleans. Existing
  `snapshot_atomic=false` remains accurate: these are observation-interval facts,
  not a claim that a version change caused the result or an atomic state audit.
- MAIN retention snapshot uses an exact retained lease-to-dedicated identity
  match. The coordinator hooks do not replace provider binding/receipt methods,
  native/viewer issuer methods or cleanup owners captured by `_original_current`,
  `_dedicated_retained`, admission `_original` or `_binding`. The maintenance
  observer is dynamically called and is not a captured cleanup issuer method.
- Existing127 seen-key,128 record including summary,64KiB lifetime byte and
  bounded row/frame limits remain. New events accept only their designated
  false/exception or entry result; state keys/types remain allowlisted. No new
  file writer, retrying publisher or unbounded per-MAIN history is introduced.
  Saturation or identity reuse may omit diagnostics; absence is not proof that
  no failure occurred.
- Production Core remains accepted R207 `c324bc1e...`, admission `9ca1bef6...`,
  0017 `7d920845...` and runtime body `7745e95d...`. These hashes were checked
  against their accepted manifests. Source behavior, authority, SQL, timers,
  native callbacks and cleanup decisions are unchanged.

## Fresh independent verification

Reviewer command, exit0: **13 passed in0.28s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_dedicated_maintenance_debug.py tests/tvt_parity/test_dedicated_refresh_interleaving.py -q -p no:cacheprovider --tb=short
```

Nine diagnostic controls cover first false/pre-close facts, exact original
exception identity and one original entry, skipped substitution, optional
sink faults, synchronous refresh facts before delayed publication, no extra
SQL and300 distinct record attempts within the existing caps.

Four inert schedules exercise current production behavior: direct observation
crossing a refresh, sweep closing MAIN after that false, a native-probe supplier
receiving the transient false, and genuine revoked authority still closing
MAIN. They use fake native/admission ports with actual coordinator methods;
the native probe demonstrates the supplier's Boolean result, not actual
Windows transport failure or a repaired lifecycle. They are causal source
evidence only.

Author47 related passes and mypy/Ruff/format gates are retained author evidence,
not rerun wholesale. No source/test/runtime/DB mutation, private input, hardware,
browser, nested agent or commit occurred. Tests import inert fixtures only;
the review creates this report as its sole authored artifact.

## Remaining acceptance

R208 must capture the first direct-current/retention/close boundary in a fresh
bounded run before a production correction is selected. A refresh flag/version
fact alone is not sufficient attribution; real SQL denial, native maintenance,
original custody failure and other causes remain alternatives. No fixed600s
cause or retrospective equivalence with R203's169.56s slot-refresh failure is
claimed. LOW's measured drops remain disclosed, and the historical5dd
exceptional cleanup remains FAILED evidence.

After cause selection, causal RED/GREEN, independent correction review and
actual HIGH/LOW duration, transitions/Stop/reconnect/store2 and normal original
cleanup remain required. Broad tests, runtime typing, twelve-camera/APK and
release readiness remain open. This source diagnostic verdict is not product
completion.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| scripts/test-local-devices/core_state_debug.py | `32cf06800d568b6fbea36d88c3d10a6c0aa0145a904ec0479f9843827a42e15d` |
| tests/contract/test_dedicated_maintenance_debug.py | `4df59f473647cd667178f873349788379d15c045b34f99723afafb34e9ddfde2` |
| tests/tvt_parity/test_dedicated_refresh_interleaving.py | `ad7a0199024d7bad02bd4bed5e93bcc9bc51a4e9d7de96d23e94d004628a7124` |
| docs/analysis/2026-10-11-dedicated-current-debug.md | `3c3040ad937393676113de02862cf9218c708556e0ad0bf6e396873b1b4a666d` |

Update log: 2026-10-11 R208 frozen SPEC/QUALITY C0/I0/M0 with13 independent
targeted passes. Actual first-cause measurement and repaired acceptance pending.
