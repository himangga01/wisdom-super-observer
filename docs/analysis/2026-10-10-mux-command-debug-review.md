# R201 fixed mux command diagnostic review

2026-10-10, Asia/Seoul. Independent **SPEC PASS, QUALITY PASS; C0/I0/M0**.
This approves the minimal rejection measurement source, not new packet
acceptance or an actual opcode/notification repair.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, preserving uncommitted Stage1/2 and
R193-R200 changes. Frozen three-path review delta: base
`97080d7b5e639d360912ec2f7c5b42d99a8fc178`, candidate
`6e409df4fa97d0e31edb7de70c099b929427bab5`; these are review trees, not new
branch commits. Read shared policy/project instructions, service retired e0b6
evidence, [R200 review](2026-10-10-shared-read-deep-debug-review.md), exact
diff/hash manifest, codec/base-exception/catch source, finalized
[author report](2026-10-10-mux-command-debug.md) and local handoff.

The service provides authenticated TVT video through Core/native/media owners.
Actual R200 evidence locates unsupported command/route rejection at `_parse621`;
the numeric pair remains needed before selecting packet handling.

Only that existing rejection raises new `UnsupportedMuxPacket`, a subtype of
`UnsupportedLive`. The condition and packet processing stay unchanged; inherited
fixed message and existing UnsupportedLive/LiveError base catches remain valid.
The subtype retains only parsed command uint32 and route byte, checking exact
int types/ranges. It is appended after existing codec code, preserving parser
line references. All other rejection conditions remain generic. Existing codec
failure/closed-state behavior continues.

Only READ projection recognizes the exact subtype, within the existing four-node
chain traversal. It revalidates both primitive attributes and emits a paired
`wire_command`/`wire_route` only when valid. Subclasses, missing/mutated malformed
attributes and facts outside the chain bound are omitted. The closed event codec
requires both fields together, only on VIEWER_READ_EXCEPTION, and validates their
uint32/byte ranges again. No frame locals, messages, IDs, arbitrary types or
private bytes are inspected/exported.

Original active-reader identity, READ32/eight-output bounds, HEARTBEAT8 and its
field set, queue byte/counter caps, publisher custody, close/error semantics and
failure isolation remain preserved. No SQL, authority, native callback, IO or
cleanup invocation is added. No material source finding was identified.

Independent fresh affected verification: **173 passed in 1.12 seconds, exit0**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_command_debug.py tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_live_mux.py -q -p no:cacheprovider --tb=short
```

New controls exercise actual codec rejection/Core read cleanup, numeric bounds,
earlier generic rejection, forged/malformed/out-of-chain facts and HEARTBEAT
exclusion. Existing codec and diagnostic tests cover supported behavior and
custody. Author RED14 and static gates were read as author evidence, not replayed.
Synthetic commands 2561/2562/2563 are not evidence of the actual runtime opcode.

Independent raw hashes match frozen source and finalized reports:

| Artifact | SHA256 |
| --- | --- |
| Codec | `bbccd5496bf7866bc0990dc1cd56ced24a8662baf7bf580093c6a987d07fd5fd` |
| Runtime helper | `67bef6eb988049bfc011f1d8a8ef233251db3e05eb25aa33b53f9b350a053e78` |
| New tests | `f3a8c6bf5572f066761fe3ab81207a75725dda3f6046448241c31459ce83cb97` |
| Portable author report | `1ec2c07f1aa2969689ace329f44e50fb5e34be1887f87b49cd18e4cb28b4a283` |
| Local author handoff | `ce32471c48b49b6f00b7700efef6b3d9538ad37e923f93c3e0b69f1857742bb3` |

Only this report was written. No source/pin/private/receipt edit, DB/hardware/
browser/runtime operation, optional broad suite, commit or agent was performed.
Root owns canonical links, immutable closure and actual numeric capture.
Earlier generic rejection or finite chain/queue limits can omit facts; missing
fields do not prove benign packets. Stable shared playback, opcode policy,
twelve-camera capacity and APK parity remain open. No product decision is
needed for measurement; notification acceptance requires actual opcode evidence.

Update log: 2026-10-10, frozen R201 source review and independent 173-case gate
C0/I0/M0. Read before diagnostic or packet-policy changes; refresh after source
or actual owned evidence, preserving historical failed runtime conclusions.
