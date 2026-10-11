# R200 bounded deep READ projection review

2026-10-10, Asia/Seoul. Independent **SPEC PASS, QUALITY PASS; C0/I0/M0**.
Narrow diagnostic source approval; actual codec cause and playback remain open.

Baseline: implementation worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, preserving existing uncommitted
Stage1/2/R193-R199 changes. Frozen two-path diff compares tree
`d6e8d5878292e38e55afffb7437a54b83015a886` with candidate
`97080d7b5e639d360912ec2f7c5b42d99a8fc178`; these are review references, not
a new branch commit. Read shared analysis policy/project instructions, current
service run05f2 evidence, [R199 review](2026-10-10-shared-read-inner-debug-review.md),
exact diff/hash manifest, and finalized
[author report](2026-10-10-shared-read-deep-debug.md) plus local handoff.

The service supplies authenticated TVT video through Core/native/media owners.
R199's actual trace reached codec `feed:332` but omitted its rejecting inner
condition. R200 changes only runtime projection and read tests; it changes no
media acceptance or authority policy.

The READ projection explicitly selects `inspection_limit=32, deepest=True`.
The shared inspected counter limits unknown and allowlisted traceback frames
to 32 total across at most four exception-chain nodes. Output retains the last
eight allowlisted primitive frames of that finite traversal. Dropping a selected
frame sets `truncated`; unvisited frames/nodes or cycles also set it. These bounds
do not claim an unbounded traceback or guaranteed root cause.

Exact actual read code/source eligibility and the same active reader in the
handled exception's own traceback remain unchanged. Eligibility is established
before output selection and survives eviction of the reader's exported frame.
HEARTBEAT uses the unchanged default eight-frame inspection and its separate
allowlist. Original close invocation, args/results/errors, normal Stop exclusion,
failure isolation and existing close/current mapping remain preserved.

Added read mappings are closed exact mux-codec helper names and exact live-codec
`_integer`, `_guid`, `_raw_timestamp` names. No arbitrary text/types, messages,
locals, arguments, IDs, paths or media escape projection. The unchanged codec
still enforces eight output frames and canonical bytes; existing event/byte
caps, queue accounting and retained publisher custody apply. No new authority,
SQL, native callback, IO, frame operation or cleanup call was added.

Independent fresh verification, exit 0: **72 passed in 0.94 seconds**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_heartbeat_debug.py tests/contract/test_local_media_read_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_debug_runtime.py -q -p no:cacheprovider --tb=short
```

Controls include actual Core read through twelve inert wrappers into actual
codec generation rejection, capture of `_feed:351` at chain1, deepest-eight
retention/truncation and omission of a known codec leaf beyond 32 unknown frames.
Prior R199/R196 preservation and queue/custody cases also pass. The author's
RED2/10 and static results are reported author evidence, not replayed here.
Synthetic generation rejection is not attribution of the historical fault.

Current raw hashes match the frozen manifest:

| Path | SHA256 |
| --- | --- |
| `scripts/test-local-devices/core_state_debug.py` | `9da4554fa730e0970f07686f6f04473a12046667f438c11919aa45d3d067981b` |
| `tests/contract/test_local_media_read_debug.py` | `384f4536b9813c90746a9f58b02f32db19856d99236faffaea436841b938906d` |

Only this report was written. No other source/pin/receipt/private input,
hardware, DB, browser, commit, extra agent or optional broad suite was touched.
Root retains broad-suite RED authority and owns AGENTS/service cross-links,
fresh immutable approvals and actual capture. Missing evidence can still result
from the finite budget or queue saturation; summary-write accounting limits
remain unchanged. Actual rejecting condition, native background terminal cause,
stable shared playback, twelve-camera and APK acceptance remain open. No new
product choice is required for this default-off measurement.

Update log: 2026-10-10, frozen R200 review and fresh 72-case gate C0/I0/M0.
Read before projection changes; refresh after source or actual owned evidence.
