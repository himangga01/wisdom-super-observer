# R202 background ingress diagnostic review

2026-10-10, Asia/Seoul. Independent **SPEC PASS, QUALITY PASS; C0/I0/M0**.
This approves bounded background measurement, not packet handling or actual
opcode/playback acceptance.

Implementation worktree: `codex/superlive-web-service`, HEAD6436748 plus retained
uncommitted Stage1/2/R193-R201. Exact frozen delta uses base tree
`6e409df4fa97d0e31edb7de70c099b929427bab5` and candidate
`5df75b9d4a9ced3aa2838d3ce63f9a2d8a3e89bd`; review trees are not new branch
commits. Read shared policy/project instructions, current service run9d72
evidence, [R198 review](2026-10-10-shared-ingress-repair-review.md),
[R201 review](2026-10-10-mux-command-debug-review.md), exact frozen diff/manifest,
full affected catch/sink, final [author report](2026-10-10-mux-background-debug.md)
and local handoff. Existing unrelated source/reports remain preserved.

The service retains authenticated recorder epochs while SUB views park or
switch to MAIN. Existing READ tracing misses exceptions in the retained
background consumer; R202 adds one fixed evidence record at that catch.

The new optional emission occurs after original invocation/authority/IO unwind
and IO-lock release, outside provider state locks, before existing provider
`_closed`, fence and owner-stop operations. Projection or sink BaseException is
isolated. Existing stop-event condition, consumer completion Event, original
thread/custody and cleanup sequence remain unchanged. No extra authority,
SQL, native callback wrapping, frame operation, IO or cleanup call is added.

Projection inspects at most four cause/context nodes with cycle detection,
using BaseException cause/context and instance-dictionary descriptors. It
does not access traceback/frame locals or wrapper attribute hooks. Only exact
`UnsupportedMuxPacket` and exact validated uint32-command/byte-route values
produce `unsupported_packet`; unmatched/subclass/missing/malformed/out-of-bound
facts become fixed `unknown` with null fields. Records retain no exception,
frame, arbitrary text/ID or private bytes.

The exact frozen dataclass/encoder forms a closed primitive union. Encoding
revalidates cause and paired numeric/null facts, emits fixed version/event
canonical JSON bytes and limits the row to 1,024 bytes. Existing NativeFirstKeySink
accepts that exact record alongside prior types without changing its 128-row/
64-KiB caps or bounded drop counter. Runtime publishing remains separate from
this queue-only producer.

Ordering is correctly qualified: IPC pump may already fence/request original
stop before the provider catch. The record precedes the provider's own closure/
fence/stop, not IPC's earlier stop. The parent worker retains the queued bytes;
native-child termination does not itself prove publication or original cleanup.
No material source finding was identified.

Independent fresh verification:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_background_debug.py -q -p no:cacheprovider --tb=short
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_background_debug.py tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py tests/contract/test_native_first_key_debug.py -q -p no:cacheprovider --tb=short
```

Results: **12 passed in0.22s** and **53 passed in16.74s**, both final exit0.
Controls exercise actual parked consumer/callback/parent/codec with inert native
ports, IPC-first ordering, unknown/Sink-SystemExit isolation, descriptor traps,
four-node/cycle scope, exact types, bounded sink and prior custody/terminal/first-key
behavior. Synthetic opcode values do not identify the real recorder packet.
Author 114-case/static/RED evidence was read, not relabeled as reviewer execution.

Current raw SHA256 matches every frozen path:

| Artifact | SHA256 |
| --- | --- |
| Provider | `eafc1bea8c66b87d61e9729d1ab66020cba800bc6701d7ea296a4ddc9225e6fa` |
| Diagnostics | `435398340278a576a9fb071f627835ae79a5ecd2dbe7080f64faccbcc35c8eb7` |
| New tests | `c7542866f8e787630ca28d776664276b8d8eda774519e3919ec5d14b91f5d2be` |
| Author report | `68925d5f69671ad1c373572abc03dd78f2a0ddffe666172153d00339f47cae6b` |

Only this report was written. No source/private/pin/receipt edit, SDK/recorder,
DB/browser/runtime operation, optional broad suite, commit or agents occurred.
Root owns canonical links and fresh public/native/source approvals; actual
replay waits for the reference gate. Unknown facts, finite chain bounds, shutdown
skip or sink saturation can leave opcode unavailable. Broad-suite RED evidence
remains unchanged. Actual opcode, notification policy, stable shared duration,
twelve-camera capacity and APK parity remain open; measurement introduces no
new product choice.

Update log: 2026-10-10, frozen R202 SPEC+QUALITY C0/I0/M0 with independent
12/53 affected cases. Read before tracing changes; refresh after source or
actual owned evidence while preserving earlier retired-run limits.
