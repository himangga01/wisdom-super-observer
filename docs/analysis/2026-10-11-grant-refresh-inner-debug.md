# R204 original admission refresh exception measurement

Analysis date: 2026-10-11, Asia/Seoul. Worktree `codex/superlive-web-service`, HEAD6436748 plus retained Stage1/2/R193-R203. Read shared policy, AGENTS, canonical service and `2026-10-11-r203-live-acceptance.md`; R203 source/runtime reports remain preserved. The service streams authenticated shared SUB and dedicated MAIN through Core/native owners.

## Actual boundary and narrow implementation

R203 run4236755a normally retired after LOW331.112515s pass and HIGH169.56s failure. Actual heartbeat1840 is SLOT_RETENTION refresh; local_admission.checked66 emits fixed DENIED and loses the original traceback outside its except clauses. No initiating READ/native background event occurred. Exact slot denial condition remains unmeasured; no clock/SQL/hardware cause or complete repair is inferred.

Runtime helper now optionally wraps only exact SqlMuxAdmission's original bound `_refresh_current_grant` method. Admission has no captured method-binding entry for this private helper; existing public/current/provider callback bindings remain untouched. The wrapper calls the retained original exactly once with unchanged args/kwargs. Success returns the exact original value quietly. Failure queues before outer refresh cleanup and boundary sanitization, then rethrows the exact original error.

Only exact TransportGrant/SlotRetentionGrant/ViewerGrant select closed TRANSPORT/SLOT_RETENTION/VIEWER purpose. Other grant types emit no new record. `GRANT_REFRESH_EXCEPTION` uses empty state, existing heartbeat eight-frame/four-chain allowlist projection and fixed exception/code/status validation. It reads no locals, SQL results, grant IDs/expiry/state or arbitrary messages. Optional sink/projection BaseException is isolated; original authority behavior remains. There is no production Core/SQL/provider/native, timer, parser, queue, cleanup or extra authority/SQL call change.

The existing `sink.first(event, grant)` retains only event plus Python identity, suppressing repeated errors for the same grant. Fresh grant objects can select separate first failures, but the existing seen-map127, record127 plus summary128,64KiB lifetime bytes and per-row2048byte caps remain. Saturation still omits bounded evidence; no unbounded per-refresh map or record retry is added. Identity reuse can suppress later diagnostics and changes no authority.

One old R200 test hardcoded codec generation-raise line351, moved357 by R203 pure import/sentinel additions. Its exact function/chain assertion now locates the current first `_feed` raise through AST; the application/deep-trace behavior and original tested bad generation remain unchanged. This is a related test locator correction, not a parser change.

## Verification and limits

After fixing a synthetic reservation-field fixture before source changes, four causal tests failed solely for missing queued inner evidence. GREEN on implementation:4 passed. Final new7 tests plus existing state/heartbeat/read/numeric diagnostic controls:71 passed0.83s, exit0. Three affected files Ruff check passes; helper mypy passes. Controls invoke actual original SqlMuxAdmission refresh/_record with inert observation ports, exact boundary context clearing, all three purposes, expiry without SQL, same-grant suppression, optional first/capture KeyboardInterrupt isolation and quiet successful fresh-grant return. No DB/native/process/browser or broad test ran by this source task. Broad7816 RED remains in canonical triage.

Frozen candidate awaits independent review and fresh public/native/reference397-superset closure before actual replay. Next capture must select the original slot rejection line, then a measured repair and actual HIGH/LOW five-minute/returnStop/reconnect gates. Raw SQL states, exception messages, credentials, GUIDs and media remain private. No new product question is introduced by instrumentation; live acceptance remains open.

| Owned path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `a996daa7c14183c30d9a0bb1d25e15b4c0c9161bee0cb2b7fe2bb6d54f61461b` |
| `tests/contract/test_local_media_grant_refresh_debug.py` | `be069980dbd967cf71fe5d0c23c939842648d7c51bd251286039b3b3f06c1fe2` |
| `tests/contract/test_local_media_read_debug.py` | `a3ce626ae2d285c2161ec24039969656300ed781e0c040ad85af1dd993b53b74` |

Commands: `.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_grant_refresh_debug.py tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_mux_command_debug.py -q -p no:cacheprovider --tb=short`; helper mypy `--follow-imports=silent`; Ruff check/format for three owned paths.

Update log: 2026-10-11 bounded pre-boundary refresh trace and71-case source verification saved; no actual repaired HIGH or exact original slot cause captured yet.
