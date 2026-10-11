# R140 c9 timestamp first-failure observation

Date: **2026-10-06 (Asia/Seoul)**. Status: **author implementation and focused source verification complete; frozen for independent review**. This is diagnostic source evidence. It does not establish the actual timestamp subtype, its cause, repaired playback, or twelve-tile acceptance.

## Baseline and scope

Active worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`. Branch `codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`; confirmed by reading the worktree HEAD and branch ref directly, without Git commands. The tree already contains the authorized uncommitted stage-1/R137/R138 implementation. Root concurrently owns the separate native LOGIN/BUSY correction and the canonical service, instruction and ledger updates.

Read the shared analysis policy, worktree AGENTS, canonical service report, R137/R138 source and independent reviews, the local media service integration guide, and the relevant liveness report. Applied focused test-driven development. Existing R137/R138 evidence remains historical and is not rerun device acceptance.

The four authored Python paths are listed with frozen hashes below. No native provider/socket writer, native guide, admission, decoder, WebRTC, frontend, manifest, dependency, receipt, or approval was changed. Root approved the narrow design as R140 before implementation. Root incorporates this report into `docs/service-analysis.md`, AGENTS and the stage-1 ledger; those shared files remain under its ownership.

## Purpose and actual evidence boundary

The service carries an authorized original recorder stream through private native IPC, an adapter, a bounded decoder owner and its existing WebRTC peer. R137 permits validated same-codec dimension transitions; R138 provides bounded producer credit during decoder startup/rotation. This change only improves the optional failure evidence at the adapter's existing strict timestamp guard.

Root's retired c9 dispatch identifies source attempt 3 (store 1/channel 4), 6 (channel 3), and 7 (channel 5) with first failure `adapter/timestamp_invalid` at source-relative 937311, 789983 and 787421 ms respectively. Their starts differ; the approximate global 1040-second grouping is a controller correlation, not a shared absolute timestamp proof. It occurred after focus/main-to-sub and rapid UI cycles, but temporal association does not establish causation. Store 2 sources had no corresponding actual failure. Intentional `peer/close_scheduled` records, including the original channel 2 and short focus attempts, remain separate lifecycle outcomes.

The existing observations lack the prior/current timestamp relationship. They do not distinguish a missing derived value, equality, a regression, an invalid value, wall-clock adjustment, reordering/B-frames, malformed recorder media, or another upstream mechanism. No claim about those causes is made here. Root reports c9 fully retired with 22 leases CLOSED/cleanup-confirmed, original Chrome/coordinator exited 0, original application resources/private state settled, and observer terminal/hash completion; this author did not independently rerun retirement or device probes. Existing safe controller browser summaries do not contain prior/current timestamp scalars. No new private media or native result was exported.

## Implemented source behavior

`NativeFrameAdapter.packet` keeps its existing guard order. The strict timestamp check still runs before later metadata/scope/identity/codec/format/framing checks; the same inputs are rejected and permanently fenced. The prior valid PTS, global ordinal, identity binding, decoder/native/peer ownership and all playback policy remain unchanged.

At that exact failed timestamp guard, an enabled observer may receive one bounded `timestamp_failure` event before the existing coarse `adapter/timestamp_invalid` event. The two-string callback signature remains unchanged. Optional observation stores only the first accepted source context, and only while observation is enabled. At failure it requires an already accepted binding/PTS, exact private frame/timestamp/identity types, exact integer context tuple equality and identity generation/session/channel/task equality against that binding. The established live scope must still be zero. Foreign contexts, changed stream kind/identity, unbound first frames and malformed scope/types receive no detailed metadata; their original coarse guard result remains unchanged. A later accepted frame's PTS is used even across resolution changes.

The event builder and callback boundary catch `BaseException`; failure in optional metadata cannot change admission, fencing or resource custody. It performs no executor/permission predicate, SQL/native call, decoder call, I/O, media serialization or timestamp normalization. Successful frames emit no new event; the only additional success-path state is the once-per-observed-adapter context reference. Activation remains the existing default-off fixture observation path.

The controller parses the bounded two-string event into a closed object. It atomically records the canonical `adapter/timestamp_invalid` first failure with the nested metadata only if no first failure exists. A subsequent generic error, close, timestamp event or metadata cannot replace or enrich an earlier first failure. Invalid event metadata increments the existing observation failure counter and cannot inject raw values. Snapshot copies now include a deep copy of the nested first failure.

## Exact safe controller schema

The existing summary remains `schema_version: 2`; terminal records remain `schema_version: 1`. For a qualified first timestamp failure, the source row contains:

```json
{
  "first_failure": {
    "stage": "adapter",
    "reason": "timestamp_invalid",
    "elapsed_ms": 250,
    "timestamp": {
      "kind": "regression",
      "delta_us": -1000,
      "delta_saturated": false
    }
  }
}
```

`timestamp` is optional. A coarse first failure has exactly its previous fields. `elapsed_ms` is the existing source-attempt-relative monotonic observation time, clamped to `[0, 2147483647]`; it is neither recorder time nor an absolute wall time.

| `kind` | `delta_us` | `delta_saturated` | Meaning at the existing guard |
| --- | --- | --- | --- |
| `missing` | `null` | `false` | The existing `unix_microseconds` value is `None`; this does not assert absence of raw timestamp bytes. |
| `invalid` | `null` | `false` | Value is not an exact integer, or is outside signed 64-bit bounds. No invalid value is retained. |
| `duplicate` | `0` | `false` | Current value equals the prior accepted source PTS. |
| `regression` | integer in `[-2147483647, -1]` | Boolean | Current value is below the prior accepted PTS. Delta is current minus prior; values below the configured `-2147483647` microsecond floor are clamped and marked `true`. |

The fixed source saturation magnitude is `TIMESTAMP_DELTA_LIMIT_US = 2147483647`. A saturated value establishes only a delta smaller than that floor. The exact floor with `false` remains distinguishable from saturation. Positive deltas cannot occur at this rejected boundary and are refused by the controller schema. No prior/current absolute PTS, identifier, raw media, credential, exception string, source text or user-supplied enum enters this object.

The private two-string callback uses stage `timestamp_failure`, with reason limited to 48 characters and one of these canonical encodings:

- `missing,,0`
- `invalid,,0`
- `duplicate,0,0`
- `regression,<canonical-negative-decimal>,<0-or-1>`

For regression the range is as above; flag `1` is valid only at `-2147483647`. Alternate decimal spellings, extra fields, arbitrary objects/strings, positive/oversized values and inconsistent flags are rejected. This diagnostic event is not an exported failure-stage enum and does not replace the existing `timestamp_invalid` reason.

Existing row limits (maximum 256), bounded writer, milestone/transition bounds, independent sticky terminal decision and terminal/settlement/hash gate are unchanged. Evidence completion still requires original terminal COMPLETE, writer settlement, zero observation failures/omissions and the matching canonical snapshot digest. Failure metadata can describe an actual source failure inside a complete observation; it does not certify playback success.

## Verification actually executed

All commands used the existing `.venv/Scripts/python.exe`; no dependency installation occurred.

1. Causal RED, before implementation: `-m pytest tests/tvt_parity/test_local_media_source.py tests/contract/test_local_media_observation.py -q --tb=short -k timestamp` yielded **12 failed, 21 passed, 72 deselected**. The failures were the absent new event and nested metadata; existing rejection/guard tests passed.
2. Focused GREEN after implementation, same command: **33 passed, 72 deselected**. Additional boundary cases then covered exact saturation versus overflow, latest accepted PTS across dimension changes and prior coarse first-failure preservation.
3. Final requested source/transition/pressure/observation selection: `-m pytest tests/tvt_parity/test_local_media_source.py tests/tvt_parity/test_local_media_format_transition.py tests/tvt_parity/test_local_media_pressure.py tests/contract/test_local_media_observation.py -q --tb=short -k 'not live_self_identity_probe and not node_self_identity'` yielded **135 passed, 2 deselected in 33.63 s**. These are inert/synthetic source cases; both self-process identity probes were explicitly excluded. No Windows SDK or actual codec/media/device/SQL/Chrome execution occurred.
4. Scoped Ruff check on the four authored files: final **all checks passed**. The first invocation found one test import-order issue, corrected without behavior changes; the passing rerun is retained as final evidence. The final format check caught mixed line endings introduced by that import-only patch. Formatting the test file restored the existing line endings; its Ruff recheck passed and the final format check reported **4 files already formatted**.
5. `-m mypy --follow-imports=silent services/tvt-media/src/wso_tvt_media/native_source.py scripts/test-local-devices/observation.py`: **success, no issues in 2 source files** under the repository strict configuration.

Tests cover missing/duplicate/regression/invalid classification; missing initial and foreign scope/type refusal; unchanged permanent rejection and binding/PTS/ordinal; default-off and callback `KeyboardInterrupt`; exact/clamped delta bounds; unchanged PTS history through dimension changes; atomic sticky controller state; schema injection refusal; bounded rows; nested snapshot/writer isolation; late event refusal after terminal; and hash invalidation when evidence is changed. Existing source, transition, pressure and writer-retirement tests passed in the same final selection. No broader repository gate or actual acceptance claim is made. The final test run loaded before the import-order-only correction, which does not alter test behavior.

## Frozen authored SHA256

Hashes are exact current on-disk bytes, including line endings.

| Path | SHA256 |
| --- | --- |
| `services/tvt-media/src/wso_tvt_media/native_source.py` | `3f6fcf8976cfe5b27876ed7a46c4e00a863908051db79837a517f98779aec340` |
| `scripts/test-local-devices/observation.py` | `617a9ae9f477db6a602c09973a1c7c93cb66b65171764c2034047beca0aa67de` |
| `tests/tvt_parity/test_local_media_source.py` | `76e55557953a75a53c6509df02c2e6e503455e537cce9db1472f4bbe143bc2e9` |
| `tests/contract/test_local_media_observation.py` | `9750164339b875570f2aa54dee1894252a8b25e9a5b1093b73097a70e78ed652` |

No Git command/index/history operation, subagent, receipt generation, service startup or real run was performed. Other writers' files were preserved.

## Remaining limits and next boundary

Independent source review is next. Root then decides the new immutable approval and any bounded actual diagnostic run after all original c9 resources have retired. This author creates neither approval nor execution evidence. The source diagnostic can identify the immediate timestamp relationship only if the original scope is already established; it deliberately gives no detailed evidence for a malformed first timestamp or foreign input. It cannot identify why the recorder supplied that relationship, infer wall-clock correction or B-frame policy, or authorize relaxing strict PTS. The current actual twelve-tile target remains unaccepted. No product-policy change is proposed.

Update log: **2026-10-06** — R140 optional timestamp first-failure source implemented, focused verification completed and four authored files frozen for review. Reuse this report before changing the diagnostic boundary and refresh affected evidence afterward; current overall execution status remains in `docs/service-analysis.md`.
