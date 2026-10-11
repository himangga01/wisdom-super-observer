# Dedicated MAIN: R194 evidence and next isolated measurement

Analysis date: **2026-10-09, Asia/Seoul**. This is a read-only continuation of
[the first NO_SIGNAL diagnosis](2026-10-09-dedicated-main-no-signal-diagnosis.md).
That report remains byte-identical because it is pinned by the active run.
**No source cause or wire mismatch is established. The parent receives an
accepted MAIN ACK and no complete video frame; its current checks and IPC
continue. An existing legacy service run can test MAIN availability alone, but
cannot conclusively isolate shared-master coexistence.**

## Authority, baseline and limits

Read: shared analysis policy, worktree [AGENTS](../../AGENTS.md), latest
[service report](../service-analysis.md), original diagnosis, R193 authorities,
R194 [author](2026-10-09-native-first-key-debug.md) and
[review](2026-10-09-native-first-key-debug-review.md), runtime composition,
raw-probe source/review, native live acceptance and established APK codec guide.
Systematic debugging and completion verification workflows are reused. Root
owns canonical report/AGENTS updates and all runtime/native operations. Read
this continuation before an availability comparison or worker telemetry change;
update it after the corresponding source or actual evidence.

Fresh branch `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with 180 retained Git status entries.
The actual authority is the implementation worktree, not primary main. Active
controller run `6d2c380f` uses frozen 336-source envelope `05ed91b9` and native
`0fb88c6a`. No pinned file, source, test, index, ref, private input, SDK, native
resource, database or browser was edited/read as runtime input/launched here.
Only this separate unpinned Markdown report is created. No tests are needed for
this source inspection, and none were run.

Fresh raw hashes: runtime `2140c0352294f13e9ad387c8482c1d92451b8ad8e636ba3697981ba9f4960008`;
raw probe `f2db7a05e322867997a9623896328b7c222e24bb5e68d6bd199e31f93f77370e`;
Windows provider `9be24918b774567949c5e1ec62dc99b0389695ba1c434a9872be59c764f6896f`;
worker `cba9407fcde2956a3dc48c0596bd2a74a51b101bfd9f4553c83a01f91170cdaf`;
legacy live provider `cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c`;
parent IPC `8571477a55d9b7d8760fddaf8aeb6369cc536179fe9c3fa6323e5afc6eac7910`;
diagnostic helper `106dde9503a1207640fbb88b7322f404440e3787aabdd645268f0fa772359b47`;
original diagnosis `de49cf4a96545224e6e2a15224b522bdfed93c36e64cf9c399c3ad48a976aa36`.

## New actual evidence, supplied by Root

Cold default HIGH followed SUB start/focus/SUB STOP 200. MAIN returned
NO_SIGNAL 504 after **14187 ms**. Validated typed parent summary:

| Observation | Value |
| --- | --- |
| Open ACK | true, MAIN command 1281, at 3875 ms |
| First frame/key times | absent |
| Parsed frames/non-keys/keys | 0 / 0 / 0 |
| Codec parsed packets/received bytes | 4 / 388 |
| Partial buffer/assembly/fragment/queue | all zero |
| IPC messages/decisions/envelopes/bytes | 399 / 399 / 4 / 40093 |
| Next sequence/last completed purpose | 400 / frame |
| Original authority checks/max elapsed | 1398 / 16 ms |
| Worker observation | false |

The Core records identify intentional viewer/wall cleanup after failure, with
no relevant native-current failure. These are controller execution observations,
not an independently operated run. The parent data rules out observed parsed
non-key/late-key and retained parent partial assembly in this attempt. It does
not prove worker callback or recorder silence. Four parsed packets are not four
video frames; do not assign unrecorded packet categories from the counts alone.
The 16 ms maximum measures enclosing checks, not isolated SQL or worker latency.

## Existing harnesses and what they can establish

The CCTV service separates SQL admission, native ownership/readiness and media
delivery. In `scripts/test-local-devices/runtime.py:1399`, the existing nonshared
media branch composes real `LocalMediaAdmission` → `LocalMediaExecutor` →
`NativeLocalLiveProvider` → `LocalMediaWorker`. Select media mode and leave shared
mode absent, through a separately approved launcher/profile. The owned fixture
uses migration 0015 instead of 0016. `NativeLocalLiveProvider.open_session` still
uses current/cancel/caller deadline, the same Windows worker, MAIN 1281/stream 1,
same source codec and existing 10-second ACK-to-first-key bound. No guard change,
bare `current=True`, direct decrypt, fake lease or master replacement is needed.

**Lowest source-change comparison:** after the active originals retire, Root
may materialize a fresh schema-2 `owned-local-device-media-browser-only` approval
for the current reviewed bytes and run one sole MAIN on the same privately
selected recorder/channel with current inventory. Confirm all other original
native sessions have retired, measure start/offer/presented frame/stop and keep
normal original/owned-DB/source/private receipts. The current schema-3 envelope
cannot be reused merely by flipping shared mode: `verify_source_approval:478`
checks exact schema, scope, profile and private/source bindings. Old Stage 1
approvals likewise do not authorize changed current source bytes.

If sole MAIN is ready within the unchanged first-key bound, it proves current
MAIN availability under legacy service conditions and narrows the problem to a
difference in shared composition/coexistence. It does **not** alone prove that
the recorder suppresses MAIN beside a shared master: SQL/coordinator/custody
paths also differ. If sole MAIN repeats ACK/no media, shared-master coexistence
is not necessary to reproduce that outcome; common receive/availability remains
open. This is a targeted comparison, not new sustained MAIN or twelve-camera
acceptance.

There is **no existing unchanged exact coexistence A/B harness**:

- Dedicated startup selection requires the retained shared master and pending
  focus; removing them changes or fails the established authority contract.
- Legacy `WindowsSocketProvider.run:1424` admits coexistence only beside healthy
  `LiveParentAuthority` originals. A mux master has different service custody;
  this path cannot run alongside it without changing that guard. Dedicated MAIN
  uses the separate accepted mux-custodian coexistence predicate.
- `mux-probe.py:304` explicitly requires every request to be SUB and implements
  two/four SUB slots. Relabeling a MAIN request would change its reviewed scope.
- The historical raw four-frame diagnostic has different operator authority and
  capture timing. It can establish bounded MAIN data after fresh admission, but
  cannot substitute for the unchanged service first-key/coexistence comparison.

The worker MAIN wire path still matches the established APK source: MAIN uses
1281 even for peer capability at least five, ll2 stream 1 and the same validated
source channel-number mapping. Both dedicated and legacy service calls enter
`LiveRemoteAuthority` → `drive` → `serve_live`. Parent setup/ACK success confirms
those selection checks passed. No source-backed serializer correction is found.

## Minimum worker evidence if the shared boundary remains unresolved

Priority **P1** after retirement: one reviewed, default-off, bounded worker
progress record on **the same original**. Capture immediately after its accepted
ACK, on first post-ACK drain, and immediately **before** each original envelope
forward needed for startup. Retain a final bounded startup snapshot outside the
native callback before cleanup clears state. The transport must preserve exact
run/generation/file custody and make omissions/write failure explicit; a missing
record cannot be interpreted as zero progress. Suggested fixed primitive fields:

- Accepted ACK/MAIN branch; relative ACK/first post-ACK batch/first complete
  media/first key times; drained batch/byte counts after ACK.
- Complete envelope categories limited to ACK, heartbeat, fragment, notification,
  media and other; original codec validated media/key/non-key counts.
- Forward attempts/completions and last fixed IPC purpose, existing exchange
  count/max wait; measure original calls once, without extra authority checks.
- Current transport/codec partial and assembly byte lengths, fragment-pending
  boolean, callback failed/closed and queue bytes/chunks. No raw header, wire
  identifiers, frame index/timestamp, payload or exception string is exported.

This distinguishes callback/drain absence, partial assembly, pre-forward valid
media and IPC forwarding delay. In particular worker validated-media >0 with
parent parsed-media 0 selects the worker-to-parent boundary. Complete post-ACK
heartbeats with no worker media and empty partial state supports no accepted
video during this original interval; it still does not label the camera offline.

The existing `WSO_TEST_LOCAL_MEDIA_TRACE` hook is **legacy-only** (`:1404`) and
captures child exceptions, not these progress counters. Enabling it in the
current shared profile supplies no worker progress. Extending it or modifying
worker telemetry is new executable source work and requires review. R194's
record deliberately rejects `worker_observed=True`; preserve its v1 contract
and use a separately typed event/record for genuine worker data.

**Closure cost:** worker/body, diagnostic helper and selected transport/control
edits invalidate their exact source/native bindings. Review only that diagnostic
delta and preservation/privacy/omission controls; refresh public LIVE receipt,
its two Windows pins, private native OWNED/dependency closure and immutable
runtime envelope for new bytes. If runtime/bootstrap tracing is chosen instead,
review its exact injected executable code and refresh the dependent runtime
closure; the old trace flag is not approval for a new hook. Reusing historical
SDK ABI evidence is appropriate because no export signature, calling convention,
observer layout, native Send or callback contract needs to change. There is no
reason to repeat ABI recovery or unchanged feature reviews. Transport must not
fabricate native envelopes or reuse `result.json` as a progress/control channel.

Open questions remain current MAIN data availability, shared-coexistence effects
and worker receive/forward progress. No timer/guard relaxation or product change
is supported. Repaired MAIN/browser, SUB liveness, sustained multichannel,
twelve-camera and APK equality remain separate gates.

Update log: 2026-10-09 — R194 zero-parent-media actual evidence qualified;
existing sole-MAIN service comparison and its schema-2 approval requirement
verified by source; exact coexistence A/B limitations and worker evidence/closure
contract saved. Original pinned diagnosis and all application sources preserved.

## Post-retirement source-only legacy control closure — 2026-10-09

Root subsequently confirmed run6d2 normally retired: originalexit0/reaped,
API/worker/context/source/private gates normal, PostgreSQL alone running. Root
chooses sole legacy MAIN availability before worker telemetry implementation.
The original diagnosis was then appended with the actual record and this
qualified next step; its historical de49 identity remains prior receipt evidence.

Inspected executable controls only, without executing them or reading private
approval/input files:

- Current materializer: `.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/create-shared-source-approval-r194.py`,
  exact SHA256 `9b0cda9e5d2dea83c92e6f47ffd3862622f3f1f1281ae56b0f0f463fcbc405f2`.
- Current launcher: same directory `run-media-development-r194-20261009.py`,
  exact SHA256 `307634df575aeb4b317fa8e6106c8410596844385e44f2a206f6ee3b24829fc1`.
- Historical `create-c12-approval.py` was read only for schema2/closure shape.
  Its native/runtime/source pins are obsolete and must not be used.

### Exact schema2 and private bindings

The current validator's exact top-level key set is:

```json
{
  "schema_version": 2,
  "root_explicitly_accepted": true,
  "scope": "owned-local-device-media-browser-only",
  "sources": {"reviewed/repository/relative/path": "CURRENT_APPROVED_RAW_SHA256"},
  "private_sources": {
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_SOURCE_REVIEW": {"path": "EXACT_LAUNCH_PATH", "sha256": "ACCEPTED_NATIVE_DIGEST"},
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_RUNTIME_REVIEW": {"path": "EXACT_LAUNCH_PATH", "sha256": "ACCEPTED_RUNTIME_DIGEST"},
    "WSO_TVT_WINDOWS_DECODER_PYTHON": {"path": "EXACT_LAUNCH_PATH", "sha256": "APPROVED_EXECUTABLE_DIGEST"}
  }
}
```

This is a proposed shape with placeholders, not approval. Omit `shared_profile`
entirely. Every private path must exactly equal its launch environment value,
and its bytes must hash to the separately accepted digest. Source paths remain
current raw byte pins, contained/non-symlink/non-junction, <=1024 entries; the
materializer preserves its <=64KiB output bound and create-new writes.

Keep current private references unchanged in both new controls:

- `source-approved-shared-mux-diagnostics-r194-v1.json`, accepted native
  SHA256 `0fb88c6a3f9f0fc32d69c74be1fe86860a46a3a749fe33a0e900434329cb43fe`.
- `runtime-approved-shared-mux-stage2-v1.json`, accepted policy
  SHA256 `77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d`.
- The existing reviewed Windows decoder executable, native bundle/staging,
  `ProviderConfig(...,20,runtime_path)`, fourteen-package check, private ACL and
  runtime-override checks.

Compatibility is established by validator source, **not a newly executed
metadata gate**: `windows_socket.verify_review:676` validates exact OWNED/files/
dependencies/status with no shared-mode or mux-profile selector; `runtime_override`
checks the exact77eb policy and returns allowedOverrides, with no mux requirement.
Receipt filenames do not select native mode. With shared absent, the existing
`NativeLocalLiveProvider` creates a non-custodian `WindowsSocketProvider`; current
reviewed source supports that path. Root must still execute unchanged source/
ACL/manifest/runtime checks against the actual files before any live input/DB.
Any mismatch blocks the run; it is not a reason to alter a guard.

### Minimal proposed fresh controls

Suggested new names in the current Stage2 control directory:
`create-legacy-main-source-approval-r194.py` and
`run-media-legacy-main-r194-20261009.py`. Neither is implemented by this analysis.

Clone current materializer9b0 and change only the profile metadata/control:
schema2, legacy scope, remove `shared_profile`, explicitly remove
`WSO_TEST_LOCAL_MEDIA_SHARED` from its environment, and use fresh legacy output/
summary names with schema2. Retain the existing full reviewed source superset
(`OWN|BORROWED|MEDIA_SOURCES|SHARED_SOURCES`, current imported production graph,
native files/dependencies, relevant reviews and self/extra helper paths). The
validator permits this superset; removing shared source pins is unnecessary.
Keep immutable creation, tags, path containment, size/hash/source/native gates.
Include both new control files and this report as reviewed extra paths.

Clone launcher307 and make two required behavior substitutions: remove the
`WSO_TEST_LOCAL_MEDIA_SHARED:1` fixed-environment entry; replace readiness's
equality with `runtime.shared_context(True)` by strict absence of `sharedMedia`
in the owned context. Preserve the environment scrub so inherited shared flags
cannot leak back in. Preserve runtimeSHA2140/serverSHA5982, exact0fb/77eb/decoder
refs, self-approval gate, private-read ordering, HTTPS/CA, original Node/Chrome
identity and retained handles, durable shutdown, source/private/DB receipts,
the existing acceptance/development bounds and failure retention. Inherited
TRACE remains scrubbed; no injected child tracing is needed for this comparison.

Illustrative CLI shapes after fresh source-only control review:

```text
python -B <new-materializer> <fresh-tag> <new-launcher-relative-path> <review-report-relative-path>
python -B <new-launcher> runtime --source-approval <fresh-absolute-schema2-file> --source-sha256 <accepted-digest>
```

The materializer writes a new legacy approval filename; the launcher receives
that exact FILE+SHA. `runtime` retains the existing bounded acceptance lifecycle;
Root may normally retire as soon as the sole MAIN observation is collected.
No source change to runtime2140, Core, SQL, codec, Windows provider/worker,
native ABI, timer or policy is required by these controls. Fresh metadata/closure
and exact delta review are required; creating hashes does not itself approve
new control code. Existing nonshared API/worker/Next environment builders and
server context guard already select absence consistently. The runtime's
already reviewed legacy owned-DB branch selects0015 and original cleanup.

Verification in this continuation: source reads, branch/HEAD/status count and
raw hash readings all exited0; supplied control hashes matched. No fixture,
private metadata gate, SDK, DB, browser or native process was run. Remaining
gate is Root's concrete new controls/review/current closure and actual sole MAIN
comparison. Worker telemetry stays deferred until that evidence selects need.
