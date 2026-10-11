# R206 confirmed attached focus cleanup and closed API action logging

2026-10-11, Asia/Seoul. Worktree `codex/superlive-web-service`, HEAD6436748 plus retained Stage1/2/R193-R205. Read shared policy/AGENTS/service and `2026-10-11-stale-forward-focus-cancellation.md`. Prior421-source runtime pins were released after retained original retirement before edits. This service uses browser wall/focus ownership over authenticated Core/native recorder owners.

## Actual cause and cleanup limits

R205 early run4b217f18 still failed RETURN after LOW20.418611s/205frames and HIGH23.608235s/240frames. Same exact accepted421-source/envelope07de7ac9 replay5dd75c3d enabled documented CDP Network before actions. LOW23.687813s/237frames and HIGH34.33072s/348frames rendered. Exact request sequence: RETURN focus-reservations POST200, then focus-settle POST404 on the old FORWARD reference carried by the MAIN start; private equality comparison wastrue. New RETURN settlement200/old-forward=false followed, thenwallStop200 andMAINStop504. Generic fixed API route labelwall had hidden that the failed request was focus settlement, not wall heartbeat. No headers, bodies, GUIDs, tokens or SDP were exported; only method/masked path/status/equality projections were retained.

Source onStop always asks group.cancelFocus for its player's old attached FORWARD ref. SQL RETURN consumes that ref; settled/consumed references are not PENDING and the strict settlement issuer correctly rejects. Existing mocks returnedCLOSED for any state, hiding this failure; its rejected cleanup promise blocked replacement LOW before start. This is distinct from the reviewed R205 backend races and historical R203late-slot denial.

Run4b normally retired with421 source/private gates. Run5dd normal shutdown could not settle the worker. API exited0; all camera originals/viewer receipts reportedREAPED/returned, butworker-close marker wasabsent and worker receipt retained exitnull/job nonempty/unreaped/writer unsettled. Exactworker4316 creationFILETIME134361232398876088/parent18844 creation134361232363814452, current bootstrap/context andJob membership/assignment/limits were verified twice on the same termination handle. Root authorized task-owned exceptional cleanup; only4316 was terminated exit97. Original coordinator then reapedexit1/Next0 and removed context/ownedDB; sourceDB content equal/source421 unchanged/private0. The run remains FAILEDexceptional, workerSettledfalse, observation nonterminal. Final individual workerJob receipt was not preserved outside removed context; no normal worker/job/writer COMPLETE is claimed. Before-force original receipt/debug/action artifacts remain saved. The exact cleanup wait is still unmeasured.

## Narrow implemented change

Only the browser group attached-confirmation lane changes. `attached()` already requires this exact current usable pending ref, no closing promise, accepted replacement lease and unexpired current intent. After positive confirmation it clears the timer and removes only that completed record. PlayerStop/StopAll then issue no invalid settlement for it. Pending, expired, late, canceled, unknown and in-flight/rejected cleanup retain their existing records/promises and failure gates. No404 is accepted as success. Removing completed metadata also bounds retained history; native Stop still owns its original player cleanup.

The API diagnostic adds exactly three trusted route-template enum labels: focus_settle, wall_heartbeat and wall_stop. Actual URL/value substitution cannot select these new labels. Other route categories, original request/exception behavior, closed fields,1024byte row/128row/64KiB queue and default-off activation remain. No URL/template/ID/header/body/value is recorded. Source/Core/admission/SQL/provider/native/timeout/source permissions are unchanged by R206.

## Verification and remaining gates

Watched browser group RED1 (obsolete attached cancellation invokes404) with in-flight pending controlPASS, then group17 GREEN. Stateful wall test now models real refusal of old attached FORWARD and successfully begins/accepts RETURN SUB. Related group/wall/card suites86passed7.18s. Two historical mock-based expectations were corrected: confirmed transfers perform zero obsolete cancellation; failed RETURN still stops/settles original players and attempts no invalid attached cancellation. Genuine pending expiry and rejected original cleanup tests remain passing.

API exact-template test first failed genericwall vsfocus_settle; final11 API controls pass0.64s, including raw substituted-path exclusion/private value absence. API mypy/Ruff/format pass. Next route type generation and TypeScript noEmit both exit0. No optional broad suite ran; broad7816 RED/runtime whole151 typing limits remain historicalopen.

Frozen six-path candidate awaits independent SPEC/QUALITY review, fresh immutable references/closure and actual early LOW/HIGH/RETURN before five-minute/rapid-switch/Stop/reconnect/store2 gates. Neither this source result nor earlierR204 HIGH pass resolves historicalR203late-slot denial. Normal worker cleanup after the observed exceptionalrun must be explicitly demonstrated. Twelve-camera/APK/fullservice/publication remain open; no new product choice or expiry widening is introduced.

| Owned path | SHA256 |
| --- | --- |
| `apps/web/src/lib/tvt/live-wall-group.ts` | `47d64ee6fd3a8c0c6e9c0d4dd1a8ef501bc7e52e928b13a8c145f3cb2255cdc9` |
| `apps/web/tests/live-wall-group.test.ts` | `e2f1d5729bacad2b2d5ea73e93174f17c16fee426e5ffdc86dfaca9f36e1b509` |
| `apps/web/tests/live-wall.test.tsx` | `acbec61323b5cd2d71fa457c865b16ebd18118b6a5f0015467c357a734298941` |
| `services/api/src/wso_api/tvt/local_media_diagnostics.py` | `e559499ad0f15cdc759777edf9b5a80cc8e96efb2f1ef69e58025c996bf96920` |
| `tests/tvt_parity/test_local_media_diagnostics.py` | `b1264a35a025789f371dfd166e59a6c4a6f1efb3482ce18e2ced324c31c39ff0` |


Commands: web localvitest group/wall/local-live-panel selection; Node Nexttypegen then localtsc --noEmit; `.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_local_media_diagnostics.py -q -p no:cacheprovider --tb=short`; scopedAPI mypy/Ruff. `pnpm` is absent fromshellPATH, so existing local executables were used without dependency installation.

Update log: 2026-10-11 exact obsoleteFORWARD settlement matched and confirmed attachment cleanup/source logging repaired. Read before group/diagnostic changes and refresh canonical actual evidence after normal replay.
