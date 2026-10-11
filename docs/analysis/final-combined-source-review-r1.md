# Final combined correction — scoped independent re-review R1

Date: **2026-10-06, Asia/Seoul**. Reviewer: `final_combined_source_review`.

**SPEC: compliant for this correction. QUALITY: approved. Critical 0 / Important 0 / Minor 0.**

R0 I1–I4 are resolved in the frozen ten-path correction. No residual defect or
new blocking breakage was identified in its inspected composition. This closes
the four source-review findings; it does not grant actual Windows/native/runtime
execution authority or establish recorder/Chrome acceptance.

## Scope, purpose, and correspondence

Read the R1 brief first, reused the complete prior [R0 review](final-combined-source-review-r0.md),
read the complete [author correction report](final-combined-fix-report.md), current
AGENTS/canonical continuation and shared analysis policy. Inspected the complete
ten-path diff, current changed implementation, all new composition tests and
changed existing tests, and the immediate unchanged admission/IPC/observer/media
callers relevant to these corrections. The R0 whole-branch scope and earlier
qualified per-task evidence remain the starting authority; unrelated production
code and generated files were not audited again.

The service remains an OWNER wall with immutable substream tasks on two recorder
originals, separately scoped transport/slot/viewer grants, one dedicated main
lane, local decoder/peer ownership, bounded media credit and exact original
retirement. These changes repair startup handoff, source-thread settlement and
heartbeat/authority serialization without changing that product scope.

Root-supplied BASE: `b03ae924b1817be7f7dfceb61a64e96858659c13`.
Frozen candidate: `623dd8316e818347cbeac4b759664c690dea5c7f`.
The active worktree retains the uncommitted Stage 1/2 work on Root-reported
checkout HEAD `6436748`, branch `codex/superlive-web-service`. No Git command was
used. Root remains the sole canonical-report, ledger, source-approval and actual
execution owner.

Fresh raw SHA-256 verification matched **all ten changed files** and six selected
unchanged authorities. CRLF-only normalized Git blob hashes, computed directly
with Python without Git, matched all ten target indexes in the supplied package.
Raw hashes were not normalized.

| Package/report | Verified identity |
| --- | --- |
| R0 report | `d322c00f11d7bd6bee903e5a8c78628b14d30c779beac3bc4f89bf5d3a9def54` |
| Author fix report | `22849eb4ca21279a3f7b55e1c9320b813d9650fc3cf5696e4a64665bbdde8541` |
| `task-999-review-r1.diff` | 81,420 bytes; `2d5b2a0d0b8ec42efb901826fbc194c9d2e3ee08c52ec1eb9f12d450f78df670` |
| Actual diff payload | **80,635 bytes**, after 785-byte prefix; `3ce115569504e14e3be70c453db7f07963d702770ba729be7c4d3c0fa2f5d480` |
| `task-999-frozen-hashes-r1.json` | `65e5408be4389c382ad65309effaa648a2b27c1a75ec05769e10eba07840f825` |

## Finding dispositions

| R0 finding | R1 disposition | Relevant source |
| --- | --- | --- |
| I1 — missing local retirement supplier after native startup | Resolved: original local owner/supplier is retained and attached before viewer start; preparation remains owned through cancellation. | `worker.py:173`, `:206`, `:283`, `:539`; Core `local_media_mux_service.py:1066`, `:1553`, `:2191` |
| I2 — uncertain source thread treated as never created | Resolved: each start attempt requires positive target entry/exit and exact join; only never-attempted stages settle without a target. | `native_source.py:510`, `:543`, `:730`, `:1156` |
| I3 — healthy channel construction causes heartbeat BUSY/Stop All | Resolved: bounded wait precedes real scope renewal; existing frontend terminal handling remains appropriate for actual failure. | Core `local_media_mux_service.py:1777`; added wall-group test |
| I4 — immutable grant replacement races provider/IPC checks | Resolved: original IO barrier precedes invalidation, drains prior checks and covers replacement; Core binding retries only a proven same-original refresh generation. | Provider `local_live_mux_provider.py:236`, `:288`; Core `:1777`, `:2257` |

### I1: early supplier and asynchronous preparation remain one owned lifecycle

The optional private `retain_local` callback is passed from the real media worker
through `MuxMediaExecutor.start` to both shared and dedicated attachment paths.
Core retains the exact provider object and registration, captures that object's
retirement-attachment callable, obtains the worker supplier, and attaches it
before the provider's start. Capturing the callable before invoking the supplier
prevents a later method lookup from redirecting that attachment. The unchanged
observer preparation facade returns the actual instrumented original before
Core captures these methods; no wrapper identity is substituted at this seam.

`_LocalStartup` separates preparation completion from local source/peer closure.
Its receipt is issued only when both events are established, for the same lease
and registration. Shared caller cancellation no longer cancels the original
preparation future. `_prepare` sets its completion event in a finally block;
`_close_entry` waits for that event, then rereads the retained source/peer before
disposal. Failure before preparation dispatch marks only the known unscheduled
preparation complete. Missing, uncertain or held work is not converted into an
empty-pipeline receipt. Existing provider outstanding-operation/batch and missing
supplier checks remain unchanged.

The new tests inspect genuine `MuxSlotViewer` startup at before-hook, after-hook
and before-prepare shutdown boundaries using the actual worker and executor
with an inert coordinator seam. The held-factory cancellation case keeps the
same supplier and retained local entry until both original preparation and held
source close complete. Its local receipt does not certify master retirement.
These are meaningful source lifecycle controls; they do not exercise a real
recorder/decoder pipeline or independently execute the real SQL coordinator.

### I2: no cleanup inference from absent thread identity

The source records attempted, entered, exited and joined state for each original
ingress/decoder/authority thread. The attempted bit is set before calling the
captured start callable. Failure while obtaining that callable precedes an
attempt; a throw from the call itself remains uncertain. Target wrappers signal
entry/exit, and source close waits for startup completion and all attempted
targets before joining the retained thread objects. `ident=None` and
`is_alive(False)` no longer establish absence. `_ended` is set only after the
source's own join bookkeeping completes.

Stop between starts settles only later never-attempted stages. Positive target
completion remains required for an already attempted start, including late
entry on a stopped source. The existing stopped-path target finalizers preserve
decoder/read ownership and media release. Closed-loop notification failure does
not replace positive thread/join proof.

Six new controls cover all three interrupted positions in legacy and shared
source modes through actual worker close bookkeeping; three controls cover
failure before obtaining the start callable. They assert receipt/capacity remains
pending until original targets settle and join. Existing partial-start fixtures
now explicitly release the same stopped original target. The binding-clock-only
fixture starts no stage; it no longer pretends a no-op start is a completed
thread acquisition. The changed closed-loop assertion correctly waits for the
source's own close bookkeeping.

### I3: heartbeat waits for construction and still performs renewal

The coordinator now waits outside its state lock while the wall's original is
STARTING or has pending reservation/attachment/open/refresh work. Each iteration
checks the original budget/cancellation, wall/worker terminal state, master state
and retained transport expiry. It claims refresh state under a short lock only
after the construction boundary is ready. Success follows actual per-purpose
transport, slot and viewer refresh and final budget/state checks. Failure does
not fabricate an acknowledgement or extend the caller budget.

The same-wall frontend controller still owns one heartbeat promise, so its
existing cadence does not overlap that bounded wait. Its new test checks no
failed event or Stop All during a pending heartbeat or after its successful
response. The production frontend is unchanged. Actual coordinator tests hold
the first constructor or a later slot open, keep an established sibling current,
then assert one original and three/five real facade-model renewal calls.
Deadline, cancellation, expiry, denial and Stop controls cannot report renewal.

### I4: IO serialization spans invalidation and publication

Core enters the provider's `refresh_grants` context before admission invalidates
any old grant. The provider's original reentrant IO operation mutex is also taken
before transport, slot, viewer and binding authority snapshots. An existing check
therefore completes before refresh, and subsequent checks wait until replacement
has reached the retained provider and coordinator holders. Native nested checks
use that same operation mutex reentrantly. SQL/supplier callbacks remain outside
the short provider/coordinator state locks.

Waits check original transport/parent/operation/supplier expiry and cancellation,
the supplied heartbeat budget, Stop and retained parent state. Partial refresh
failure fences the original before waiting checks resume through the normal
context path. Admission still denies old/copied/foreign grants and IPC False is
still a sticky failure; no transient blanket allow was added. Viewer reads now
capture their grant/cut only after entering original IO serialization.

The final Core change covers a media binding snapshot that straddles healthy
replacement. Retry requires the same retained record, master and handle plus an
observed refresh-version transition. Stop, closed/inactive master, original
expiry and scope/issuer/lease/slot/registration replacement validation still deny.
A failure without the generation change is not retried. The next attempt still
passes the unchanged current/binding checks; version change is not publication
authority.

The tests use the genuine admission grant lifecycle and provider/IPC methods,
with inert SQL observation and native endpoints. They cover before/after each
purpose replacement, already-entered checks, old/copy/foreign rejection and
revocation/deadline/cancel/Stop. The final actual media-binding control adds
healthy, Stop, denial and copied-grant outcomes. No new concrete uncertainty in
these inspected boundaries required another reviewer execution.

## Exact changed sources and unchanged authorities

| Changed production path | Raw SHA-256 |
| --- | --- |
| `services/tvt-media/src/wso_tvt_media/worker.py` | `83dbb7e868122e9e3ad07c27f028664fc72a4a1810ef22137dfd21eecda9e5ea` |
| `services/tvt-media/src/wso_tvt_media/native_source.py` | `85b1c1195c61149af7883c0fe29c48dd3c508956ef54bdce23939c96661bd6ac` |
| `packages/core/src/wso_core/tvt/local_media_mux_service.py` | `9d0551019c0ceb8053dfbe89020c6e238379774ccf381693861d35db6d4169dc` |
| `services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py` | `280046300d56a939f2050d95ec7d4a3014a97850b09754153dce1685ec0e1f8f` |

All six changed test hashes match the R1 manifest and author table. The new
composition module is `766c4f70f17a9f37c2970088f1027fc8127eefc76d4f33b855c6eee566fcf373`.
Selected unchanged files independently matched the R0 manifest: admission
`0a4162c6...`, SQL `64e28f20...`, IPC `5d9209d3...`, observer `6a473a5f...`, approved
specification `036908e3...`, and plan `122796f6...`. Their previous security,
recovery, wire, observer and product-scope conclusions are not replaced here.

## Verification and limits

Reviewer verification was direct source/diff/test/report inspection, fresh raw
hash checks, exact package/payload sizing and normalized target-blob computation
with `.venv/Scripts/python.exe -`, followed by writing/checking this report.
`superpowers:verification-before-completion` was used to keep verification and
claims separate. No test/static suite, additional reproduction, Git command,
source/test edit, SQL/private credential access, SDK/DLL/native Popen/Job,
service, Chrome, installation or subagent occurred in this re-review.

Author-run evidence remains attributed and separated by its actual source state:

| Evidence | Disposition |
| --- | --- |
| Initial causal module | Seven expected failures across I1–I4, after correcting an earlier helper-import collection error. |
| Earlier failed affected gate | 407 pass / 5 fail; ordinary inert decoder test thread remained held and the tool session required Ctrl-C. Not normal cleanup or a passing gate. |
| Corrected affected gate before final Core binding change | 416 pass, tool session `94254`, normal exit 0. Not a whole-suite claim on final Core bytes. |
| Final binding causal/control | One causal failure, then corrected binding/Core controls. |
| Final frozen selection | 166 pass: 40 composition + 98 Core + 28 media mux-source cases; normal exit 0. |
| Intermediate final selection | 165 pass / 1 rotation-fixture race failure; the test now waits for actual decoder input-credit release after publication. Production credit rules were not relaxed. |
| TypeScript controller | 15 pass with installed `vitest.CMD`; prior missing `pnpm` command ran no tests and installed nothing. |
| Static | Author reports Ruff on nine changed Python paths and mypy on four production files passing. Not rerun by reviewer. |

The fix report's intermediate enum/clock-fixture failures and interrupted fake
thread/offload setup run remain historical qualifications. The 416/166/15 counts
overlap and must not be summed. Ordinary Python worker/event-loop/watchdog/test
threads and installed media libraries in the author's tests are explicitly
distinct from fake interrupted-thread originals and from actual Windows process
custody. Their final normal exits do not repair earlier failed-run cleanup claims.

Root's unchanged final SQL receipt `cd80d4f2380f41ceb00c71cd228d8f38` remains
90 passing cases for its own source scope; the prior 89/1 stale-fixture failure
remains failed history. No new SQL execution is claimed. All R0 actual limits,
including the permanent reservation-journal ceiling and missing general recovery
after original custody is lost, remain unchanged.

## Handoff and remaining gates

No source fix or product decision is requested by this scoped re-review.
Root may record I1–I4 resolved and proceed to preparation/review of fresh immutable
source/native/runtime/bootstrap authority. Historical Stage 1 receipts cannot
authorize these new source bytes.

Actual Windows worker/child/nested-Job memory profile and host headroom,
two/four-channel native wire probes, twelve-tile common-five-minute Chrome
playback, focus/return and normal full retirement remain required and unexecuted
for this candidate. The new serialization's actual scheduling/throughput cost
must be measured there; source approval does not establish an RSS, latency or
twelve-camera capacity guarantee. Uncertain thread acquisition deliberately
remains charged until positive original settlement.

Declined-to-judge behaviors: actual OS/SDK/recorder/decoder/browser performance
and physical cleanup (required later execution gates), and unrelated product
features expressly outside the approved Stage 2 scope. No load-bearing source
finding from this correction was set aside.

Root owns registration of this portable report in AGENTS and propagation into
the canonical service report and execution ledger. Preserve R0 and all failed
receipts; use R0 plus this R1 before any later related change.

Update log: 2026-10-06 — completed the prescribed single scoped re-review of the
complete correction wave; ten changed hashes, six unchanged authorities and ten
candidate blobs matched; I1–I4 resolved, SPEC compliant / QUALITY approved /
C0 I0 M0 for source scope. Actual execution authority and acceptance stay separate.
