# R202 fixed shared background ingress failure evidence

2026-10-10, Asia/Seoul. Source authority: implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`
plus preserved uncommitted Stage1/2 and reviewed R193–R201. Starting hashes:
provider `6a5bec30a88f993021a29bb83aacb132247a7958b33822281ffb68c6b37ffd95`,
diagnostics `69356a812a5b1020d04ae48e5fbae49c00723b33b70900a9f66bef6288ba182c`.

Read with [service report](../service-analysis.md),
[retained ingress repair](2026-10-10-shared-ingress-repair.md) and
[R201 command measurement](2026-10-10-mux-command-debug.md). Read before reuse
and refresh after source changes or actual replay. Root owns AGENTS/service/
ledger links, independent review and fresh native/source envelopes.

## Purpose and implementation

The service retains a shared recorder while SUB viewers park or switch to MAIN.
Root's normally retired run9d72 rendered low SUB for25.530762s/276frames, then
accepted HIGH MAIN start/offer/PLAYING before the background consumer closed.
The later heartbeat sees an already closed provider, and ordinary READ tracing
does not capture this background exception. These execution facts were supplied
by Root; this author did not inspect private run files or repeat hardware work.

Only two bridge sources change. `OriginalRecorderMaster` now captures its caught
background exception before its existing `_closed` assignment, parent fence and
owner stop. It projects one exact `NativeMuxIngressFailureRecord` and enqueues
through the existing optional diagnostic sink outside provider state locks.
Projection/sink failures, including BaseException, are isolated. Original
invocation/IO unwind, consumer completion, thread custody and cleanup remain.

The projection walks at most four cause/context nodes with cycle detection.
It uses BaseException descriptors, including the original instance dictionary,
so wrapper attribute hooks cannot supply or expose facts. Explicit cause takes
precedence; when absent, retained context is inspected even after `raise from
None`. Only exact `UnsupportedMuxPacket` objects with exact uint32 command and
byte route produce `cause=unsupported_packet`. Subclasses, missing/mutated/
malformed facts and unmatched chains produce fixed `cause=unknown` with null
command/route. No exception text, repr, traceback, frame locals or arbitrary
attributes are inspected or retained in the record.

The closed encoder emits `native_mux_ingress_failure`, version1, cause and paired
numeric/null fields, at most1024bytes. `NativeFirstKeySink` accepts this exact
record in its existing union, with unchanged128-record/64KiB limits and bounded
drop counter. Existing runtime publishing consumes its canonical bytes; no
runtime, filesystem, native callback, grant, wire, timer, queue or authority
interface change is added. No source locator is needed for this command-focused
measurement.

Ordering qualification: real IPC `pump` already fences and requests original
stop before its wrapper exception reaches the provider catch. R202 preserves
that behavior. The new record precedes provider closure and its own fence/stop,
not IPC's earlier stop. It is queued in the parent media worker and can survive
native-child termination; existing bounded worker publisher custody governs
later delivery. This is diagnostic evidence, never a cleanup or acceptance proof.

## Causal verification

RED: after correcting inert stop-spy setup, **11 failed/1 passed**. Four actual
parked consumer→callback→IPC→codec controls produced no background record; the
unknown control had no row and projection/schema helpers were absent. The sink
fault control was then strengthened to require one attempted emission. A
hostile malformed cause comparison additionally failed before a strict type
guard was added. GREEN: **12 passed** in0.22s on final source/test bytes.

Affected consumer/provider/terminal/first-key/R201 gate: **114 passed** in17.60s,
exit0. Final fixture import cleanup changed only test wiring; the final R202
12-case gate was rerun afterward. Two-source mypy and three-file Ruff/format
checks pass.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_background_debug.py tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py tests/contract/test_native_first_key_debug.py tests/contract/test_mux_command_debug.py tests/contract/test_local_live_mux_provider.py -q -p no:cacheprovider --tb=short
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_background_debug.py -q -p no:cacheprovider --tb=short
.venv/Scripts/mypy.exe --follow-imports=silent services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py
.venv/Scripts/ruff.exe check services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py tests/contract/test_mux_background_debug.py
.venv/Scripts/ruff.exe format --check services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py tests/contract/test_mux_background_debug.py
```

Controls cover unchanged rejection for2561/2562/2563/uint32-max, numeric evidence
before provider closure, original IPC-first stop ordering, unknown failures,
sink SystemExit isolation, descriptor traps, cycle/four-node traversal, malformed
and foreign facts, closed schema and128-record bounded publication. Numeric
values are synthetic; they do not establish the actual recorder opcode.

## Frozen candidate and remaining work

| Owned file | SHA256 |
| --- | --- |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py | `eafc1bea8c66b87d61e9729d1ab66020cba800bc6701d7ea296a4ddc9225e6fa` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py | `435398340278a576a9fb071f627835ae79a5ecd2dbe7080f64faccbcc35c8eb7` |
| tests/contract/test_mux_background_debug.py | `c7542866f8e787630ca28d776664276b8d8eda774519e3919ec5d14b91f5d2be` |

Author source is frozen pending independent review. No Core/codec/IPC/runtime/
native worker, policy, reference, receipt, private input, DB, device, browser,
commit or extra agent operation was performed. Prior broad7816 RED evidence is
unchanged. Tests use real callback/codec/parent/consumer and Python threads with
inert original/native/admission ports; no DLL or recorder acceptance ran.

Priority is fresh reviewed replay to measure the actual background command/route.
Unknown/malformed/out-of-chain facts and a full sink can still omit numbers;
the original initiating exception remains unmeasured until that replay. The
interleaved notification hypothesis, packet support decision, cold startup,
stable MAIN/SUB/Chrome and twelve-camera acceptance remain open. R202 changes
diagnostics only and claims no live repair.

Update log: 2026-10-10 R202 fixed background evidence and focused gates recorded.
