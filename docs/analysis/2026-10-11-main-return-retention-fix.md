# R205 exact MAIN retention during bounded RETURN

Analysis date: 2026-10-11, Asia/Seoul. Worktree `codex/superlive-web-service`, HEAD6436748 plus retained Stage1/2/R193-R204. Initial worktree was already modified. Read shared policy/AGENTS, canonical service, R204 actual HIGH/RETURN report and independent RETURN causal map. Runtime95cef193 normally retired with original/API/worker/context/ownedDB/source408/private0 before source edits. PostgreSQL57056 runs; no app runtime is active.

## Purpose, cause and implemented boundary

Authenticated shared SUB uses one recorder original; one dedicated MAIN focus must return safely to the parked SUB. ActualR204 HIGH sustained322.51s but selecting LOW gave focus200 thenwall404 before LOWstart. Two causal source schedules were reproduced: SQL commits MAIN_ACTIVE CONSUMED/PENDINGRETURN before local worker publication; a current observation can also span the local ACK-to-pending swap. New Core tests first failed2/negative4 passed. Source current previously inspected strict old settlement, which correctly rejects CONSUMED but cannot prove already-authorized pending RETURN maintenance.

New0017 migration adds worker-only `main_retention_observe` without changing applied0016 or earlier migrations. It binds exact original FORWARD authority/worker/master/wall/channel and attached MAIN lease/current rights, checking original master and dedicated native identities through SQL plus retained Python capabilities. It accepts current MAIN_ACTIVE or unique current20sPENDINGRETURN for that exact MAIN. Pending worker/authority must both be NULL before redeem or exact original worker/non-null authority after redeem. CONSUMED alone, wrong-source/channel/worker/epoch, missing/terminal/expired references and revoked/stopped MAIN never qualify. CONSUMED uses new pending expiry, not the obsolete active expiry.

The observer reclassifies after current predicates and retries at most twice if its own snapshot spans MAIN_ACTIVE to CONSUMED. Early review found stale PLAYING composites could survive a committed standard MAIN Stop. A real SQL barrier reproduced this as RED [stop], with valid [return] passing. Final observer reloads original MAIN/master and rechecks exact native/scope/state/rights, then plain current rows and pending reference before returning. The same two SQL schedules now pass. No TTL/grace/revocation or generic settlement relaxation is added.

Private `MainRetentionObserver` port and SqlMuxAdmission preserve exact factory grant/settlement/custody identities, complete returned scope, both native IDs and positive observed expiry. Retention never calls strict focus_settlement_current as a fallback or invalidates its publication cache. The strict startup/transfer settlement method is unchanged. Dedicated current uses only this maintenance path for old active ACK, while local RETURN still uses its exact pending grant. Publishing RETURN increments the dedicated focus version; bounded two-attempt current retry covers direct sweep callers and outer current, rechecking real new state rather than treating version change as success. Existing stop/original/cancellation/expiry checks remain.

Owned runtime SHARED_SOURCES includes0017; shared media_revision advances0017, legacy stays0015. Runtime raw2140 baseline is preserved except those two edits (new7745e95d). SQL fixture upgrades0017 and downgrades0015, removing the new observer and restoring historical function bodies/ACLs. Updated fixture locators and fake admission port only support these actual contracts. Fresh guarded SQL runner adds only scope-pin members, retaining original ownership/private/DB guards.

## Verification

- Causal Core RED2/PASS4 before production change, then6 new/104 combined passes.
- Owned SQL initialRED7f8ce97d:1failure/0error/skip, then initialGREEN7230b7fb:1pass. Both ownedDB/source/private/original cleanup passed.
- Early review stale-Stop RED6de03fa6:2cases/1Stop failure; final fresh-row GREEN489546b7:2pass. All cleanup gates passed.
- Final fully pinned owned SQL96dd934e:19passed/0failure/error/skip, original reaped, uniqueownedDB removed, source DB content equal, all scope pins unchanged/private0. Tests cover pre/postredeem, strict publication cache, terminal states, deadline, wrongMAIN/channel/worker, both foreign native epochs, malformed unredeemed authority, genuine MAIN revoke/Stop, observed concurrent RETURN, expired consumed-active deadline and worker-only ACL/head/downgrade.
- Final Core/service/runtime fixture:159passed4.28s, exit0. Two Core sources mypy passes; eight affected files Ruff check passes; seven formatted source/test files pass format check. Runtime keeps exact raw two-change diff. Whole-runtime strict mypy was also attempted and reported151 untyped/call/base-class issues; no runtime typing repair is claimed or included. Broad7816 remains RED.

One expanded SQL run failed because two synthetic negatives reused a unique digest; fixture changed to unique synthetic UUID-derived bytes, then18 and final19 passed. This fixture failure and earlier Red runs are preserved, not hardware regressions or acceptance.

## Limits and next execution

Frozen candidate awaits independent SPEC/QUALITY source review, exact runtime/native/public/CODEC references and new immutable prior408-source closure. No repaired Chrome return/Stop/reconnect/store2 was run by this source task. HistoricalR203169.56s slot denial remains unmeasured and is not declared resolved by R204 HIGH pass or this RETURN repair. Final actual LOW/HIGH five-minute/returnStop/reconnect and second-store sanity, twelve-camera/APK, broadgreen and publication remain open. No new product decision is required; this implements existing bounded RETURN semantics.

| Owned path | SHA256 |
| --- | --- |
| `infra/migrations/versions/0017_tvt_main_return_retention.py` | `7d920845b784c32b6748ecf0c647bf86746f2918e926c2b33e7533d2ae93b4ff` |
| `packages/core/src/wso_core/tvt/local_media_mux_admission.py` | `9ca1bef6a7066968c8e4aedad17fb7a93b9b74918f79c0c8601c5f0c0ffd1c7e` |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `0cdf1c30c050d337b738fa12ef8d4c16ceb585839e8959465e2fe93d9aa7cf4f` |
| `scripts/test-local-devices/runtime.py` | `7745e95d319a4c4e9b50499613c266f56094ff7ebdbc52768d50b8a8d56609da` |
| `tests/tvt_parity/test_main_return_continuity.py` | `6be8bb6f17636474d515f61cf321bf3a39d7162cdb563ffa53eb8d183abc3b28` |
| `tests/tvt_parity/test_local_media_mux_service.py` | `e4720ef10ba5f9b1410adcf9d5d565fd0480f0cdb16b704ac3dba274f52cd54d` |
| `tests/integration/test_local_media_mux_admission.py` | `b3fb291c5a7cf2fe40ac63c6935a680e0a5a5f5d7895233d0f9afd195f4e06e5` |
| `tests/contract/test_local_device_browser_fixture.py` | `536fbcaef55e8f9c1bf45607d30f35b0e908d1a74a364595c2b984cbce515c8a` |
| `.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/run-local-media-mux-sql-r205.py` | `944f9f897042838b313c3ead37ff58084d3175f12e442d9a907a9505239c7cf3` |


Verification commands: `.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_main_return_continuity.py tests/tvt_parity/test_local_media_mux_service.py tests/contract/test_local_device_browser_fixture.py -q -p no:cacheprovider --tb=short`; guarded `run-local-media-mux-sql-r205.py -k 'main_retention or main_return_retention'`; scoped Core mypy and affected-file Ruff.

Update log: 2026-10-11 two RETURN races and stale-Stop control repaired/source-verified; independent review and actual completion remain pending. Read before retention/SQL/refresh changes and update canonical actual evidence after replay. No secret/token/GUID/media/exception contents are included.
