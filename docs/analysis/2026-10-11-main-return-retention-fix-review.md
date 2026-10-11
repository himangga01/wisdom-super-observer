# R205 MAIN retention fix: independent SPEC and QUALITY review

2026-10-11, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0. Early I1 resolved.**
No remaining source findings in the frozen scope. Approved for fresh source/
native references and bounded actual replay; successful Chrome RETURN,
Stop/reconnect and broader service acceptance are not established here.

## Baseline and scope

Implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with pre-existing uncommitted
Stage1/2/R193-R204 work. The ten-path manifest
`r205-main-return-fix-manifest.json` has SHA256
`5d48f66059b2c57bc69176d1ec1d94b3e1d799fce74ad675dc1919ff609b1f1f`.
Every frozen file matches. Reviewed shared policy, [AGENTS](../../AGENTS.md),
[service report](../service-analysis.md), [R204 actual acceptance](2026-10-11-r204-live-acceptance.md),
[RETURN causal map](2026-10-11-return-focus-causal-map.md) and final
[author report](2026-10-11-main-return-retention-fix.md).

The service retains a shared SUB original while a separate original MAIN plays.
R204's reported five-minute HIGH pass was followed by failed RETURN. This fix
represents the existing bounded RETURN interval during original MAIN retirement.
Reuse this review before changing that boundary; refresh after source or actual
acceptance. Root owns canonical handoff updates. Only this report was written.

## SPEC assessment

- New0017 follows0016 and adds one worker-only maintenance observer. Historical
  0016 remains byte-identical at `64e28f20...`. The new function is SECURITY
  DEFINER, owned by `wso_tvt_local_owner`, with `search_path=pg_catalog` and the
  established lock timeout. PUBLIC and named runtime roles are revoked before
  only `wso_connection_worker` receives EXECUTE. Downgrade drops only the new
  signature. Owned SQL verifies head/ACL and fixture downgrade restoration.
- The SQL result requires the exact original FORWARD authority, worker,
  attached MAIN, matching wall/master/channel and current MAIN/master rights.
  MAIN_ACTIVE uses its active expiry. CONSUMED qualifies only through one
  unexpired PENDING RETURN for that exact MAIN, same scope and existing20s
  bound. Before redeem, worker and authority must both be NULL; afterward the
  worker must match and authority must be present. Other terminal states,
  foreign references and generic CONSUMED do not qualify.
- The observer reclassifies the original focus after authority checks, with
  at most two attempts when the original state changes. Its final checks reload
  the original MAIN/master, preserve each distinct native generation and
  original bindings, recheck state/scope/rights, then check current rows and
  the exact pending RETURN. Consumed old active expiry is not incorrectly
  applied to a still-valid new pending reference. No expiry or quota expands.
- `SqlMuxAdmission.current_main_retention:1628` authenticates retained lease,
  dedicated custody, original factory grant and settlement object/issuer before
  SQL. Returned scope/master/focus/source/viewer plus both base and dedicated
  native generations are checked. Expired/unknown results deny; retained
  identity is rechecked after SQL. The method neither manufactures an ACK nor
  invalidates the original strict settlement cache as a fallback.
- Independent AST comparison proves `_focus_ack` and
  `focus_settlement_current` are unchanged from accepted R203R1 tree
  `c4d1e751b0f8f4838f9099b5be8214cd28e1f65a`. Startup/transfer publication
  continues to reject consumed ACKs. Only established MAIN maintenance uses
  the new observer; local RETURN still requires its own exact current grant.
- RETURN publication increments dedicated `focus_version`. The two-attempt
  retry is inside `_current_dedicated:1620`, covering outer current, sweep and
  native maintenance callbacks. It reruns actual new authority/custody checks;
  a version change never returns success by itself. Stop, missing identity,
  genuine denial and exhausted attempts still return false.

## Preserved early Important finding and resolution

Early I1 identified stale SQL MAIN/master composites: an observer could load
PLAYING, pause, then accept that old composite after ordinary Stop committed
STOPPING. Rechecking focus alone did not detect it. The lead implemented a
real SQL advisory barrier after initial MAIN read and issued the standard
application Stop in another transaction.

Saved owned run `6de03fa66e194aa6880897804b3c1418` records two cases with one
failure, no error/skip, exit1: valid concurrent RETURN passed, Stop failed.
After fresh original MAIN/master reload and final current-row guards, run
`489546b7dd99427fa5182b36c554dd16` records both passing, exit0. Both retain
normal original reap, owned DB removal, source DB preservation, unchanged
source pins and zero known private occurrences. This reviewer inspected these
receipts and the barrier test source; no DB was opened by this review.

Final code addresses state **and** native/binding freshness, rather than merely
requerying focus. The final pinned19-case SQL run includes both schedules again.
I1 is resolved in the frozen candidate; its RED/GREEN history is preserved here.

## Independent verification and evidence limits

Fresh reviewer command, exit0: **18 passed, 86 deselected in0.23s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_main_return_continuity.py tests/tvt_parity/test_local_media_mux_service.py -q -p no:cacheprovider --tb=short -k 'return or attached_focus_requires_exact or main_active_requires_still or focus_transfer_requires'
```

This covers both original RETURN schedules, genuine revoke/expiry/Stop/foreign
grant negatives, source/target settlement requirements and original native
cleanup before returned SUB. Core ports are inert; no hardware acceptance is
implied. Direct sweep coverage is established by inspected call routing through
the same retried method, not a new dedicated sweep interleaving test.

Read-only verification of final owned SQL receipt
`96dd934ecb274808a45cce6d3bda3edc` confirms19 tests, zero failures/errors/skips,
exit0, original child reaped, owned DB cleanup, source DB equality, source pins
unchanged and zero known private occurrences. All receipt source pins match
current files; its eight scope source/test paths match the corresponding frozen
manifest entries. Receipt SHA256:
`1381a20dde0ba4a807e91661cfaea5a007b47c2151190acfa1f3586957136617`.
Reviewed cases include pre/postredeem retention, copy rejection, strict ACK
rejection, pending deadline versus consumed expiry, terminal states, wrong
MAIN/channel/worker, both foreign native epochs, malformed pre-redeem authority,
revoked MAIN, concurrent RETURN/Stop and worker-only ACL/head.

Independent AST comparison of the guarded SQL runners confirms the sole change
is expanding required pin members from3 to9, preserving the prior set and all
ownership/DB/privacy/result guards. Reversing only runtime's new0017 source
member and shared migration target restores prior raw SHA256
`2140c0352294f13e9ad387c8482c1d92451b8ad8e636ba3697981ba9f4960008`.
Shared now targets0017; legacy still targets0015.

Author159 Core/runtime passes and mypy/Ruff gates are retained author evidence,
not rerun wholesale here. Existing runtime mypy151 issues and broad7816 RED
remain disclosed. No new source/test/runtime/DB mutation, native or browser
operation, private input, nested agent or commit was performed. Historical
R203 late slot denial remains unresolved; actual RETURN/Stop/reconnect/store2,
twelve-camera capacity and APK parity still require their own acceptance.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| infra/migrations/versions/0017_tvt_main_return_retention.py | `7d920845b784c32b6748ecf0c647bf86746f2918e926c2b33e7533d2ae93b4ff` |
| packages/core/src/wso_core/tvt/local_media_mux_admission.py | `9ca1bef6a7066968c8e4aedad17fb7a93b9b74918f79c0c8601c5f0c0ffd1c7e` |
| packages/core/src/wso_core/tvt/local_media_mux_service.py | `0cdf1c30c050d337b738fa12ef8d4c16ceb585839e8959465e2fe93d9aa7cf4f` |
| scripts/test-local-devices/runtime.py | `7745e95d319a4c4e9b50499613c266f56094ff7ebdbc52768d50b8a8d56609da` |
| tests/tvt_parity/test_main_return_continuity.py | `6be8bb6f17636474d515f61cf321bf3a39d7162cdb563ffa53eb8d183abc3b28` |
| tests/tvt_parity/test_local_media_mux_service.py | `e4720ef10ba5f9b1410adcf9d5d565fd0480f0cdb16b704ac3dba274f52cd54d` |
| tests/integration/test_local_media_mux_admission.py | `b3fb291c5a7cf2fe40ac63c6935a680e0a5a5f5d7895233d0f9afd195f4e06e5` |
| tests/contract/test_local_device_browser_fixture.py | `536fbcaef55e8f9c1bf45607d30f35b0e908d1a74a364595c2b984cbce515c8a` |
| .superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/run-local-media-mux-sql-r205.py | `944f9f897042838b313c3ead37ff58084d3175f12e442d9a907a9505239c7cf3` |
| docs/analysis/2026-10-11-main-return-retention-fix.md | `24c9286bf81f51a66ead0cb2063373f845bdf7803e7da144eff80307ef2cc6f7` |

Update log: 2026-10-11 frozen R205 SPEC/QUALITY C0/I0/M0; early I1 and its
causal RED/GREEN evidence preserved, actual replay pending.
