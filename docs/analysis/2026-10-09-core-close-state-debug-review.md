# R194 Core close-state diagnostics: scoped source review R0

Analysis date: **2026-10-09, Asia/Seoul**. Independent SPEC and QUALITY review.

**Verdict: C0 / I1 / M0.** One important publisher-custody finding requires a
narrow correction and a separate R1 review before refreshed source/native
closures or changed hardware execution. The remaining reviewed diagnostic
contract has no identified finding. This source verdict establishes no actual
SUB close cause, MAIN first-key cause, repaired playback or browser acceptance.

## Authority, source baseline and scope

Read before review: `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
[AGENTS.md](../../AGENTS.md), the latest 150 lines of the canonical
[service report](../service-analysis.md), the runtime appendices of the
[shared SUB diagnosis](2026-10-09-shared-sub-liveness-diagnosis.md), the frozen
[R194 runtime author report](2026-10-09-core-close-state-debug.md), and the
[native author report](2026-10-09-native-first-key-debug.md) with its frozen
[native source review](2026-10-09-native-first-key-debug-review.md).
The verification-before-completion skill was applied. Read this review with
those reports before reuse and refresh changed findings after correction or
actual acceptance. The controller owns AGENTS/service/handoff bridges and
execution receipts; this reviewer writes only this report.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Freshly checked branch `codex/superlive-web-service`, actual Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. Initial Git status contained retained
Stage 1/2/R193 tracked changes and untracked source, tests and reports. Those
changes were preserved. Source and index/HEAD were not edited by this reviewer.

Frozen package in
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/`:

- BASE source tree: `fbc7c55645cf6e784a1226b1ecd3ba13c504e481`.
- Candidate source tree: `d3a54afefbf2664b1833edd9c4c034be4cbb22a2`.
- `task-1942-review-r0.diff`, SHA256
  `e9ec09eac8be3bd185b5c53a09d93428018b15dbf2736d4d3ba35698ec6f337a`.
- `task-1942-frozen-hashes-r0.json`, SHA256
  `1fb79f2337c8ffb73b72a6346057658ce22f4a25f2b53f76ff6a912816e10fc1`.

These are snapshot trees, not changes to actual HEAD. The scoped package has
five paths, 1683 insertions and nine deletions. Current raw bytes matched the
frozen hash list before verification; all five newline-normalized candidate
blobs also matched independently:

| Scoped path | R0 raw SHA256 |
| --- | --- |
| `scripts/test-local-devices/runtime.py` | `2140c0352294f13e9ad387c8482c1d92451b8ad8e636ba3697981ba9f4960008` |
| `scripts/test-local-devices/core_state_debug.py` | `1d705892004167f539566dc251e32ef02230dac9e95abf16f4137b9bc2e524d7` |
| `tests/contract/test_local_media_core_state_debug.py` | `b809635bc84e002204b734fdd365cda6d3ba2d1e902a4881ce0a9c963332872d` |
| `tests/contract/test_local_media_core_state_runtime.py` | `b3da84472497b9f3e01e2f36bd9f8b465d410900c9db67c348822b6cde319030` |
| `docs/analysis/2026-10-09-core-close-state-debug.md` | `8eb35d0095a50b220ae97dcdf3bc1eab27d58499ef555685cdda96f7fed8cbf2` |

Protected Core service `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc`,
R193 admission `7e31d5cdd3ebd76d7d1788722e049a70233b370a3722a14e978029051c260999`
and prior `core_debug.py`
`582e511552961f1905ea42d3ed8472dc9153d0fa94028a3d9c0699fbc6e41a5b`
freshly matched their retained authorities.

Frozen native callback dependencies also matched:

| Dependency | SHA256 |
| --- | --- |
| `local_live_diagnostics.py` | `106dde9503a1207640fbb88b7322f404440e3787aabdd645268f0fa772359b47` |
| `local_live_ipc.py` | `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910` |
| `local_live_mux_provider.py` | `bbddd3e415900ce19a5a6182c9ce971eda5207b16b5c34f53320a539202e5339` |

Native review SHA256 is
`89822cabd5ea27381a5b126588f36c7f5215ecabf49b4c0bd72ad7a718230391`,
with its separate C0/I0/M0 verdict. That gate remains separate from this runtime
publisher finding. Native receipt/bootstrap guard bodies were not changed or
executed by this reviewer.

## Purpose, implemented structure and supplied actual evidence

The service supplies authorized local CCTV channels to Chrome. Shared SUB
retains recorder transports, channel slots and viewer authority; Core decides
fencing and viewer retirement before a retained provider callback schedules
worker/peer cleanup. Dedicated MAIN uses its own original native parent.
R194 measures these existing boundaries; it does not change TTL or authority.

The controller supplied retired run `6c40be51` evidence: the first SUB's earliest
retained failure was `peer/explicit_close` at 26984 ms, 245 encoded frames, with
no earlier failure or manual Stop/HIGH and zero reported omissions. A second SUB
reached sampled Chrome time 203.709536 s and 2038 decoded frames with continuing
wall/lease 200 responses and no Stop/focus requests before intentional Stop.
Final observation recorded 3025 frames and closure concurrent with intentional
Stop at 305234 ms; both original viewer receipts returned. Observer COMPLETE,
original coordinator exit 0/reap and source/private/owned-DB normal retirement
were supplied controller evidence, not execution independently read or performed
by this reviewer. The repeat contradicts an unconditional 30-second expiry
explanation. It does not establish the initiating transient cause.

`compose_shared_media` constructs the original coordinator, installs six
instance hooks, retains/starts its runtime diagnostic owner, then constructs
the executor whose monitor starts in its constructor. No prepared owner,
`binding_for`, receipt supplier, issuer or retirement callback is wrapped.
Hooks enqueue canonical bytes; a single retained publisher drains outside
authority locks. Normal worker shutdown closes server/media/native/admission
before publisher retirement and final flush. The fixed private files reuse the
existing ACL, exclusive creation, regular-file/device/inode and 65536-byte
writer checks.

| Requirement | Assessment outside I1 |
| --- | --- |
| Exact original calls and final current result | Each hook retains its original bound method and invokes it once with unchanged arguments/keywords. Exact return values survive, and original exceptions use bare re-raise. Only final coordinator `False`/exception is recorded after its existing refresh loop. |
| Synchronous close origin | First fence/viewer-close entries capture pre-call state and bounded callchain before invoking original retirement, preserving the origin across scheduled worker cleanup. Repeated entries increment suppressed counters. |
| No added authority/supplier calls | State projection reads exact retained dataclass/dictionary fields. It makes no SQL, current, renewal, cleanup, owner-clock, binding or receipt call. Expiry is observed only for the ordinary monotonic clock; custom-clock expiry is omitted. |
| Refresh qualification | `snapshot_atomic=false` marks the deliberately non-atomic snapshot. `holder_replaced` requires a different exact expected grant in an existing holder; closed alone is not labelled superseded. The actual inert superseded-viewer control preserves refresh overlap without fencing. |
| Closed privacy projection | Strict exact primitive types, fixed enums, at most eight inspected frames and allowlisted module/function/line fields prevent identifiers, messages, arguments, locals, filenames, source text, headers or media from entering output. No frames or exceptions are retained in the queue. |
| Finite queues and attempted-byte budgets | Core reserves at most 127 event rows plus one summary and 64 KiB attempted bytes. Native queue occupancy is separately bounded, and the runtime independently limits all drains to 128 accepted records/64 KiB attempted bytes, including failed writes. |
| Default off and setup fault isolation | Existing explicit API debug/observation opt-in controls configuration. With both absent, configuration returns no owner and retains methods unchanged. Optional writer/helper setup `BaseException` does not prevent original media construction. |
| Frozen native wiring | The exact new `NativeFirstKeySink` is passed as `NativeLocalMuxProvider(first_key_debug=...)` and attached to the same publisher. Drain uses its frozen canonical byte API; original prepared methods and callback identities remain intact. |
| Normal retirement and join faults | The runtime retains the publisher owner before `start()`. A known started original is joined; uncertain join returns false and retains ownership. The normal original-server/media/native/admission-before-final-flush control passes. Pre-bootstrap start uncertainty is the I1 exception below. |

## Exact finding

### I1 — do not certify retirement while original thread startup is uncertain

Priority: **important**. R0 source anchors:
`scripts/test-local-devices/core_state_debug.py:468` (start), `:488` (identity
test), `:490` (liveness test), `:496` (final settlement), and `:529` (status).

`start()` catches `BaseException` and retains the original Thread, but does not
retain whether acquisition/startup is known. `close()` skips join when
`ident is None`, accepts `is_alive() == False`, flushes and sets `_final=True`.
For a Thread acquired by the platform but not yet through Python bootstrap,
both observations can still have those values. A `KeyboardInterrupt` while the
original `Thread.start()` waits on `_started` therefore permits `close() == True`
and `publisher_settled == True` before original startup/retirement is proved.
The runtime's cleanup loop then stops waiting and can publish a normal worker
receipt while that original is still pending. Retaining a reference alone does
not establish settlement.

An independent stdin probe used the real Python Thread startup path. It delayed
the already acquired platform thread's bootstrap behind a separate Event and
raised `KeyboardInterrupt` from the original `_started.wait`. Before releasing
bootstrap, the exact retained original had no identity and was not yet reported
alive. R0 output was:

```json
{"close_return":true,"reported_settled":true,"original_ident_unavailable":true,"start_failed":true}
```

The probe then released the gate, restored the wait method and joined that exact
original; no thread remained. It used no native process, SDK, database, browser
or private input. The existing uncertainty test interrupts only after
`super().start()` has completed and an identity is visible; it misses this
pre-bootstrap case.

Required correction: retain the startup outcome independently of identity and
liveness. After an ambiguous acquired start, keep returning false and keep the
exact original owner until its actual startup/retirement can be proved. Never
infer that it was never acquired solely from `ident is None`/not alive. Add a
causal pre-bootstrap interruption control and retain the already tested known
started/join-fault behavior. The controller accepted this finding and resumed
the author for a narrow helper/test/report correction while this R0 was being
written. Corrected source belongs to a new freeze and separate R1; this report
does not review or approve those later bytes.

**Other exact findings: none. C0 / I1 / M0.**

## Fresh verification, launcher reference check and limits

Executed from the implementation worktree, with bytecode and pytest cache
writes disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -B -m pytest tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_state_runtime.py tests/contract/test_local_media_core_debug.py tests/contract/test_local_media_debug_runtime.py tests/tvt_parity/test_local_media_diagnostics.py tests/contract/test_native_first_key_debug.py -q -p no:cacheprovider
git diff --check fbc7c55645cf6e784a1226b1ecd3ba13c504e481 d3a54afefbf2664b1833edd9c4c034be4cbb22a2 -- scripts/test-local-devices/runtime.py scripts/test-local-devices/core_state_debug.py tests/contract/test_local_media_core_state_debug.py tests/contract/test_local_media_core_state_runtime.py docs/analysis/2026-10-09-core-close-state-debug.md
```

Both commands exited **0**. Pytest: **61 passed in 1.25 s**, no failures/skips.
These are inert source controls, including ordinary joined Python publisher
threads and temporary fixed files with the ACL helper mocked. They are not an
actual Windows ACL or native recorder execution gate.

Two independent `.venv/Scripts/python.exe -B -` stdin probes exited **0**:

- The causal real-Thread interruption probe reproduced I1, then normally joined
  its exact original. Successful probe exit means the finding was reproduced
  and its temporary thread settled; it does not mean the candidate is correct.
- **18 independent preservation controls** covered all six hooks with exact
  arbitrary return, false and original exception identity, while diagnostic
  first/capture/counter methods raised `BaseException`. **29 independent closed
  field rejections** covered every top-level field, ten state booleans and
  three callsite fields. A failed native writer across five drains attempted
  103 records/65508 bytes, wrote zero, recorded 103 failures, omitted 412 and
  recorded 125 queue drops; all 640 submitted records were accounted for.
  Fresh raw hashes and normalized candidate blobs matched all five paths.

The controller separately requested a literal-reference check for its ignored
R194 development launcher. Its SHA256 matched
`307634df575aeb4b317fa8e6106c8410596844385e44f2a206f6ee3b24829fc1`.
Reversing exactly one runtime SHA change (`35c8a604…` to the R0 `2140c035…`) and
one private source-review filename change to
`source-approved-shared-mux-diagnostics-r194-v1.json` recovered the exact prior
R193 bytes. Prior launcher SHA256 freshly matched
`5bc91257e9dccf4a2c1e012aa0a771336b22db1bc2e090907d36ae3cd87af562`.
This is a two-literal source reference check, not launcher execution or a broad
launcher review. The private referenced file was not opened or created.

Author-reported Ruff/format on four paths and helper mypy remain author evidence
and were not rerun. No broad suite, SQL/DB operation, SDK/native child/Job,
recorder, browser, private approval/input, source/test/index/HEAD mutation,
staging, commit, push or nested agent was used. Only this portable report was
written. All independent controls preceded the author's correction wave and
apply to the frozen R0 hashes above.

## Priorities, risks and open questions

Priority P1 is I1 correction, a fresh scoped source freeze and separate R1
review. After an accepted runtime gate, the controller refreshes public/native
source closures and the immutable runtime envelope before changed execution.
The native source gate alone does not authorize the changed runtime.

Finite bounds, first-entry suppression, unknown frames, integer identity reuse,
non-atomic snapshots and optional setup/writer failures can omit evidence.
Empty logs do not prove absence of a fault. A blocking private writer can delay
normal retained publisher retirement; join uncertainty must stay qualified.
Admission false during replacement/refresh is an observation rather than a
proven terminal cause. Native records remain parent-only and cannot establish
recorder silence or worker callback/forwarding absence.

Open measurement questions remain the first actual Core current/fence/close
entry that initiates unexpected SUB cleanup, and the parent MAIN key/partial/
IPC/check pattern before NO_SIGNAL. TTL, reconnect and authority policy changes
are not selected by these source diagnostics. Actual MAIN/Chrome playback,
return/reconnect, sustained multichannel/twelve-camera and APK parity gates
remain open.

Update log: 2026-10-09 — frozen R194 runtime SPEC+QUALITY R0 C0/I1/M0;
61 scoped tests, 18 independent preservation controls, 29 primitive rejections,
native failed-writer lifetime bound, five raw/candidate hashes and two launcher
literal references verified. I1 reproduced using an acquired delayed original
Thread and reported promptly; no actual hardware acceptance claimed. Freeze
this R0 report after the final hash is supplied; corrections receive R1.
