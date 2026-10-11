# R203 ordinary interleaved notification repair

2026-10-10, Asia/Seoul. Worktree `codex/superlive-web-service`, HEAD6436748 plus retained uncommitted Stage1/2/R193-R202. Read shared policy, AGENTS, canonical service, approved Stage2 spec/plan, N9000/mux guides and full-path notification research. The service carries authenticated recorder media through Core/native mux and web/API media owners.

## Actual cause and original retirement

Fresh R202 run6a366e9c under384-source envelope06bd9426, publicv8 a51fd2c8 and nativee93f853d reached trusted Chrome login and actual store1 eight-channel inventory. Cold channel2LOW start2006156ms, offer200108ms and PLAYING20062ms preceded VIEWER_READ_EXCEPTION. Its bounded trace reports exact wire_command2563 (0xA03), wire_route0 at mux `_parse621`; no clock/budget attribution is needed for this event. Native background log was empty because foreground reading caught the first exception. UI ended unable to connect. The ordinary family complete actual header/body shape was not exported or inferred from command alone.

Own Chrome tab closed; exact normal shutdown marker then retained original exec31090 settled exit0/reaped. API/worker/context source cleanup passed, ownedDB cleanup true/source content equal, coordinator runtime/Next exits0/custody false, observation COMPLETE with zero omissions/failures, known private occurrences0. All384 source hashes matched throughout. Prior failed receipts remain preserved; no PID kill or original receipt rewrite occurred.

## Implemented narrow change

Mux codec consumes the notifications; the unchanged pure N9000 header helper and length mapping are extracted to a stdlib-only module and reimported under the same legacy names. Exact2561/2562/2563 now use the existing shared pure N9000 `_is_startup_header` validator plus positive signed-short version1..32767, ordinary8-byte outer magic/actual-length and declared-equals-actual checks. Bodies retain strict92/40/36 bounds and remain opaque. Reply/error prefixes, sequence, route/flags, encoding, wrong magic/length/version and fragments still fail. Malformed recognized controls retain UnsupportedMuxPacket numeric diagnostic rejection.

A private consumed-control enum distinguishes successful consumption from `None` backpressure. Ordinary dispatch counts the packet, consumes the original spans/buffer, then continues without returning an ACK/frame or claiming encoded credit. Fragment dispatch never accepts the sentinel. No slots, tasks, cuts, clocks, format, ACK, grant, timer, queue limit or transport/authority check changes; existing parent before/after transport checks remain. No control body effects or callback are added.

## Verification and limits

Before production change, new51-case codec gate failed14 positive controls at existing UnsupportedMuxPacket guard;37 negative controls passed. After implementation a fixture corrected `observed_wire` to existing `wire_observation`. The first affected gate exposed malformed-control diagnostic regression in six old tests; typed rejection was preserved, then383 passed. Final expanded actual-parent/retained-consumer and credit/counter/source compatibility gate401 passed in17.53s, exit0. Final fixture import cleanup: new55 cases rerun passed0.29s. Mypy on codec passes; Ruff check/format of allthree owned paths pass. No full suite was rerun; broad7816 gate remains RED in the existing triage.

New controls cover all three families/peer version bounds, every packet byte split, coalesced media and blocked media credit, pending ACK preservation, ingress origin/slot clock order,1000-control received/packet counting and overflow, malformed headers/body sizes, fragments/action prefixes, and actual retained callback/parent/consumer drain with zero media credits/terminal rows.

This frozen source candidate awaits independent review and fresh native/reference/envelope gates. Actual repaired LOW/HIGH continuous Chrome playback, stop/reconnect and twelve-camera/APK acceptance remain open. Next priority is reviewed replay for at least five minutes per LOW/HIGH, followed by stop/reconnect and normal original cleanup. No new product choice is required; a packet outside this strict recognized shape remains rejected.

| Owned path | SHA256 |
| --- | --- |
| `packages/core/src/wso_core/tvt/local_live_mux.py` | `18fea85ce19edbc87ca74ef63e254a33e66330e76407e5909585c6a6a82db1b2` |
| `packages/core/src/wso_core/tvt/local_n9000.py` | `38c7c0f539b062e75d00ca34ae3f79ba548287e607500ee6481bdd6422f82bab` |
| `packages/core/src/wso_core/tvt/local_n9000_notifications.py` | `96420059fe46a9d0e9d45947acbcf7a719590f5237bcde029ccdfcf3535984f9` |
| `tests/tvt_parity/test_mux_notifications.py` | `b367d4224f3a2ce9cc075af0559ec93e24ef50a87c6f2abb7faed249db4cf130` |
| `tests/contract/test_mux_notification_ingress.py` | `63523afa3c021767d0fea7f6306422b40d39dfe80714e63cdaef839591a93ae0` |

Commands: `.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_mux_notifications.py tests/tvt_parity/test_local_live_mux.py tests/tvt_parity/test_local_live.py tests/contract/test_mux_notification_ingress.py tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_command_debug.py tests/contract/test_mux_background_debug.py tests/contract/test_local_live_mux_ipc.py tests/contract/test_local_live_mux_pressure.py -q -p no:cacheprovider --tb=short`; focused55 uses only two new test files. Scoped mypy/Ruff paths match the table.

Update log: 2026-10-10 actual2563/route0 selected; strict ordinary-control candidate with source/causal gates frozen. No repaired hardware acceptance claimed.


## R1 pure import boundary correction

Fresh isolated `-I -S -B` mux import exposed ModuleNotFoundError for cryptography when mux initially imported N9000. Root extended ownership to N9000 and a new pure helper. The exact original `_STARTUP_BODY_LENGTHS` mapping and `_is_startup_header` AST now live in `local_n9000_notifications.py`; N9000 reimports both under unchanged names, mux imports only the pure helper. A direct AST comparison with frozen5df75b9d confirms all remaining N9000 AST is identical. No login/crypto/packet serialization behavior changes.

Watched isolated RED then GREEN: mux/types import with only core source path and no site packages passes; cryptography/SQL/Pydantic/contracts/bridge modules remain absent. The new permanent subprocess control checks this exact boundary. Focused N9000 serializer/shape plus legacy live/mux and new actual-parent tests:448 passed1.45s, exit0. Three-source mypy passes, five-file Ruff check passes; final format/test hashes are recorded above. Earlier401 affected controls remain executed evidence; no broad suite or hardware acceptance is substituted.

Update log: 2026-10-10 R1 corrects isolated import regression; source candidate remains pending independent corrected review. Runtime is stopped, PostgreSQL alone listens57056. No new actual packet was accepted by this correction yet.
