# R143 c11 observation publication budget repair

Date: **2026-10-06 (Asia/Seoul)**. Status: implemented and offline verified, frozen for independent source review; no repaired actual acceptance. Worktree `codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`, approved uncommitted stage-1/R141/R142 baseline. Existing unrelated changes are preserved. Root owns canonical service/liveness reports, AGENTS and ledger.

Read-before references: shared analysis policy, active AGENTS, canonical service report, existing browser-runtime observation guide, and [c11 observation diagnosis](2026-10-06-c11-observation-diagnosis.md). The diagnosis was saved before implementation; its historical facts are preserved. R143 was explicitly authorized by Root after c11 normally retired. Read both reports before later writer changes and update their execution evidence afterward.

## Problem and implemented behavior

The recorder playback service has separate native/source/decoder/WebRTC owners and an optional fixture observer. In c11 the observer's legal roster exceeded the borrowed private-context writer's65,536-byte cap. The retained65,055-byte schema2 snapshot stopped at90 sources; its canonical hash matched the terminal's last successful snapshot, but terminal FAILED/6850errors and stop_requested=false correctly rejected completion. The detailed diagnosis distinguishes this from native502 and records the R141/R142 source provenance.

R143 adds `write_snapshot(path, value)` to the optional observation helper. It emits compact canonical UTF-8 JSON (`sort_keys=True`, separators comma/colon) with **SNAPSHOT_MAX_BYTES=1,048,576**. The only runtime integration change is its observation snapshot callback: one loaded observation module supplies MediaObservation and this dedicated writer. The ordinary borrowed write_private remains unchanged at65,536 bytes, and read_terminal remains unchanged at4096 bytes. Default-off activation, source/native/peer events, counters, privacy schema and all service decisions remain unchanged.

The new writer preserves the existing private writer's path and atomic publication rules: reject target/parent symlink or junction; create exact sibling `.tmp` using O_WRONLY|O_CREAT|O_EXCL and mode0600; write through the retained descriptor; replace the target atomically; remove the original owned temporary in finally. It refuses oversize **before** opening/replacing. It does not adopt or remove an already existing temporary if exclusive creation fails. Windows ACL inheritance remains the original private parent directory's responsibility; no new ACL relaxation is introduced. No raw private resource, ID, exception string or credential is added to snapshot content.

The byte cap is finite and fail-closed. There is no record truncation, smaller roster, silently omitted history or counter saturation change. Writer exceptions still flow only into the existing observer failure counter. A blocked writer still has the same200ms join, independently sticky terminal and original-custodian behavior. COMPLETE still requires successful final stop snapshot, settled writer, zero failures/omissions and matching canonical hash. Compact file bytes now match the canonical digest input exactly, but the controller still validates the parsed snapshot and independent terminal.

## Size derivation and deliberate numeric envelope

The approved cardinality is256 native attempts,256 sources,256 peers, up to16 format transition rows per source and six unique milestone rows per source. The test fixture exercises the real projection through begin_source, provider wrapping and peer correlation, substituting only original native/peer resources. The extreme serialization envelope then uses maximum legal dimension digit widths,2147483647 elapsed/transition counts, the longer unsaturated timestamp-regression metadata representation, and unsigned64-bit widths for otherwise unsaturated peer/top-level counters.

| Projection | Compact bytes | Previous indent2+newline bytes |
| --- | ---: | ---: |
|91 populated attempts/sources/peers |75,162 |122,719 |
|201 populated attempts/sources/peers |166,314 |271,291 |
|256 full-cardinality,16 formats/six milestones,64-bit counter envelope |809,267 |1,623,658 |

A conservative bound allowing every ordinal its largest legal width is **809,807 bytes**. Empty top-level envelope=338 bytes; maximum individual attempt/source/peer rows=223/2768/168 bytes. Add256 copies of each row and255 separating commas for each of three arrays:

`338 + 256*(223+2768+168) + 3*255 = 809807`.

This leaves238,769 bytes below1MiB. No universal mathematical bound is claimed for arbitrary Python integers: peer/top-level counters remain unsaturated by design. Values outside this documented64-bit width envelope or future schema growth must still obey the1MiB serialization cap; oversize remains FAILED without replacing the prior snapshot. The maximum-envelope regression detects expansion beyond the configured budget. Root explicitly accepted this envelope rather than changing counter semantics.

The ordinary private context/approval readers at65,536 bytes do not consume media-observation.json. Repository/controller source search found no existing snapshot-specific65,536-byte read gate to update; complete_observation accepts the parsed object. The separate terminal reader stays4096. Any future bounded snapshot reader must use SNAPSHOT_MAX_BYTES, not the private-context bound. No coordinator/server or unrelated writer was modified.

## Executed verification

Causal RED: five new writer tests failed before implementation because write_snapshot was absent (91/201/256 publication, oversize failure/preimage, exclusive temporary ownership). GREEN: all five passed with the production writer.

Focused command:

```powershell
.venv/Scripts/python.exe -m pytest tests/contract/test_local_media_observation.py tests/contract/test_local_device_browser_fixture.py -q -k 'not live_self_identity_probe and not node_self_identity'
```

**79 passed,2 deselected in6.84s.** The deselections are existing process/self-identity probes. This selection includes actual filesystem91/201/256 snapshot publication and terminal digest completion, maximum-cardinality projection, oversize preimage retention with FAILED, private sentinel absence, existing temporary preservation, all four target/parent symlink/junction branches, atomic replacement failure with owned temporary cleanup, ordinary context64KiB rejection, default-off activation, callback failures, blocked/late final publication and sticky hash/terminal regressions.

After that run, the maximum synthetic envelope's saturation boolean was changed from true to the one-byte-longer legal false. Its focused regression was rerun: **1 passed,50 deselected**. Read-only exact size arithmetic produced the table above. This changes test data only; implementation remained unchanged.

Final scoped Ruff check passes for observation helper/test; Ruff format check passes2files. Strict mypy with --follow-imports=silent passes the1helper source file. A final mixed-newline formatting check on the changed test initially requested normalization; formatter was applied and final check passed. Runtime's narrow callback is exercised by static/import fixture coverage; its inherited whole-file lint/type debt was not broadened or represented as green. Scoped git diff --check passed with an existing LF/CRLF conversion warning for runtime.py.

No full suite, SDK/native decoder, SQL, service, browser, dependency operation, source receipt or immutable approval was run/created. Tests use temporary synthetic files and inert resource substitutes; no real run evidence was changed. Source review, a new immutable c12 approval and Root-owned actual reproduction remain required. The last c11 summary stays historical and cannot become COMPLETE through this source repair.

## Risks, priorities and open questions

P1: independently review the compact writer/runtime callback and byte-bound test closure; include these source/test/report hashes in the next approval. Then run the smallest useful actual sequence and require the existing independent terminal/hash/cleanup/source/privacy gates after original retirement. This repair establishes enough bounded output capacity for the documented roster, not repaired native502 behavior or twelve-tile playback.

The aggregate c11 failure count lacks an error-class breakdown, so cap arithmetic does not attribute every historical observer failure to size. Larger allowed I/O remains on the optional existing writer; the200ms shutdown wait is unchanged and still fails completion if the original writer is late. Slow actual disk behavior is an execution question, not grounds to extend cleanup waits. A future data schema or number-width expansion needs an explicit budget review; silent truncation or bypassing terminal checks is prohibited by this contract.

No product question is resolved or introduced for playback. Native502 diagnosis and actual12-view acceptance remain separate work owned by Root/the native investigator.

## Frozen source/report hashes

- `scripts/test-local-devices/observation.py`: `573b5a4dc78d9e4c6ed3de8820cdab5097a679dd8531555517ca3fd9a822f25d`
- `scripts/test-local-devices/runtime.py`: `e41701ad4a6ccdd5c3e5aea726dd69cbc81b5d1611451e3945eb12841d7054c5`
- `tests/contract/test_local_media_observation.py`: `9a447bed516669a7223dc4a1a7787a6ac61ec05c48bef2bc403465c079f14317`
- `docs/analysis/2026-10-06-c11-observation-diagnosis.md`: `e16e20346aa861d0cb4457506a9e3b9aa411042c82e926660216576ef27dd1f4`

Update log:2026-10-06 ? R143 approved after saved diagnosis; dedicated bounded compact writer, causal tests and maximum-envelope derivation implemented and verified; frozen for independent review.

## Actual c12 publication acceptance ? 2026-10-06

After independent C0/I0/M0 review and immutable146-source c12 approval, the normally retired run `local-devices-790c686c772b4fe29db973dce986901a` persisted its complete90-native/90-source/12-peer summary: schema2,stop_requested=true,zero observation failures/omissions. The original-custodian terminal is COMPLETE with writer_settled=true and canonical SHA256 `ccd899a5be25a7d53776cc8131948a0cfe0924460df526d7175fb3d197975ff2`. The existing pure completion gate was independently checked against the retained files and returned true.

The snapshot is45,511 compact bytes; the exact same value using the previous indent2/newline serialization is71,089 bytes, exceeding the previous65,536-byte writer. This is actual acceptance of the repaired runtime callback/publication composition for this run. The1MiB maximum remains a synthetic design-envelope test, and c11's failed terminal remains historical. Normal API/worker/coordinator/source/database cleanup is separately evidenced. Read the [c12 actual acceptance audit](2026-10-06-multiview-stage1-acceptance.md) for original Chrome receipt qualifications, nine-stream five-minute playback and still-incomplete twelve-stream acceptance. No source change or test rerun accompanied this addendum.
