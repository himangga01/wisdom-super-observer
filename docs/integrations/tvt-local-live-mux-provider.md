# Shared original Windows live provider

Date: **2026-10-06, Asia/Seoul**. Task 7 R2 candidate, awaiting independent scoped
re-review. Baseline source tree `d89808cfbcb5db2eb66525e86f1a882527afa97a` on the
retained `codex/superlive-web-service` worktree, HEAD `6436748`. This guide is
source evidence, not native or twelve-camera acceptance. Read it with
[service analysis](../service-analysis.md), [mux codec](tvt-local-live-mux-codec.md),
[Windows provider](tvt-windows-socket-provider.md), and the approved Stage 2 plan.
Root owns the canonical report, AGENTS pointers and actual execution receipts.

## Review correction R2

The R1 scoped review (`task-7-review-r1.md`, C0/I1/M1) resolved original I1-I3,
but found a remaining dedicated-launch fallback bypass (I4) and an exceptional
frame-refund accounting race (M1). R2 is frozen for their scoped re-review; the
prior reports remain historical evidence.

A mux-owned dedicated launch now applies `mux_owner_can_coexist` to **every**
pending original. The legacy ready/handoff branch is evaluated only for a true
non-mux legacy launch. Dedicated-start tests now directly reject unregistered,
foreign, substituted, expired and cancelled pending originals, while retaining
a valid exact-custody control and the existing non-mux legacy policy.

A denied read refunds its returned frames under the captured original IO lock.
Its invocation token remains retained throughout the refund, and no provider
state lock covers that cleanup callback. A concurrent next-frame reservation
now leaves per-parent usage, shared slot usage and retained frames consistent.
The common ledger implementation and resolved I1-I3 code are unchanged.

R2 author verification: **230 selected tests passed** (the prior222 scope plus
8 new cases), Ruff check/format eight paths, mypy five production paths. The
new cases use only inert retained custodians, in-memory callbacks and a throwing
source-review sentinel before any OS acquisition. No actual native acceptance
is implied; see the unchanged real execution gates below.

## Review correction R1 (historical)

The first independent review (`task-7-review-r0.md`, C0/I4/M0) found a startup
expiry mismatch, provider state locks covering suppliers, incomplete current
postchecks, and a false acquisition barrier for prepared or dedicated siblings.
The R1 source candidate corrects these issues; it has not yet passed independent
re-review. Exact evidence and hashes are in the execution workspace's
`task-7-fix-r1-report.md`; the original Task 7 report remains historical.

The parent initially binds the exact child startup deadline. Any extension is
sent through correlated renewal under that old deadline and the original caller
budget. A retained caller operation covers slot registration, canonical request
preparation, send and ACK observation, including cancellation after each step.

Provider state locks now protect snapshots and invocation tokens only. Current,
native/IPC and retirement suppliers run outside those state locks. Original IO
remains serialized separately, while Stop can publish its fence without waiting
for that IO lock or a supplier. Active operations retain their original tuple,
cut and cleanup obligations; cleanup returns pending until they settle. Ready
publication checks the stop fence again before becoming visible.

Authority predicates capture the grant, original owner, child, custodian and
parent before admission, then repeat exact identity, custody, child liveness,
expiry and stop checks afterwards. Binding and viewer publication retain those
same originals across supplier calls.

The global acquisition barrier recognizes only a budget-registered exact empty
prepared sibling or a fully retained healthy original. An explicit acquisition
marker distinguishes the empty state from an uncertain attempt. A dedicated
legacy original must retain its exact LiveParentAuthority, endpoints, child,
current deadline and uncancelled handoff state. Unknown, expired, substituted
or interrupted originals continue to fence acquisition.

Final R1 author verification: 222 selected tests passed (the previous 203-case
scope plus 19 new correction/control cases), Ruff check/format for eight paths,
and mypy for five production paths. The actual provider-to-worker transition
uses in-memory endpoints and an inert Popen-shaped original whose constructor
is never invoked; it creates no OS child or Job. Real native and recorder gates
below remain open.

## Composition and ownership

`NativeLocalMuxProvider(native, budget=..., admission=...)` consumes **the same**
`MuxOriginalBudget` object supplied to `DeviceEpochCoordinator`. Preparation
calls that budget's `prepare` and registers an empty exact `ChildOwner` before
any native acquisition. A prepared object can retire without creating a child;
an interrupted acquisition with no returned original remains charged.

The shared original launches through the existing isolated, Job-admitted
Windows bootstrap. The strict private mux packet selects `NativeMuxWorker`.
The existing login and inventory codecs validate actual same-original login,
serial, retained inventory login object and callback generation. Each permitted
channel is derived from `live_basis`, including only the supported explicit
`lp` or missing/empty group branches. Wire session identity comes from that
login. SQL `native_generation` is never substituted for it.

The original bootstrap pipe remains retained throughout transition to
`MuxParentAuthority`. An independent bootstrap watchdog can stop the original
while a caller supplier is blocked. Original cleanup waits for active bootstrap
or dedicated operations, the retained callback/process, pipe endpoints, Job,
writer, output handles and watchdogs. Unknown or substituted originals cannot
produce an epoch receipt.

## Immutable slots and publication

Each channel gets one immutable stream-2 task for the original epoch. Parent
`prepare_open` retains the exact codec-produced command; `send_open` consumes it
once. The child reconstructs the canonical command using the reviewed pure
codec and checks registration, channel number, epoch, task, request GUID and
sequence before invoking SDK Send outside its control lock. This is command
construction only; the child does not add a second media parser or fabricate
ACKs. Actual correlated ACK parsing remains in the original parent codec.

A viewer is retained before its ingress cut is acquired. `MuxSlotViewer` uses
that exact cut, slot and registration, checks current authority again after
callbacks, and retains references to the exact returned tuple until
`release_frames`. It adds no encoded FIFO and performs no second encoded-frame
reservation. Stopped viewers may return credit for cleanup but cannot publish.
A media retirement callback's sealed receipt is retained verbatim only after
its matching registration and outstanding returned batches have settled.
Never-started registrations can certify their own absence of media resources.

Transport, slot control/retention and viewer authority use their separate
retained grants and admission predicates. Keepalive requests verify every
retained slot's current retention authority, including parked slots, before
and after the transport operation. Parking keeps the immutable native task;
its incoming media continues to be validated and discarded until a new cut.

## Common memory and dedicated main

Root rulings R167-R169 authorized narrow IPC/custodian extensions. Module-level
`reserve_media_credit`, `release_media_credit` and `media_credit_usage` share
the original IPC lock and counters: 1 GiB host total, 64 MiB encoded total,
16 encoded frames and 4 MiB per slot (or per dedicated registration). Tokens
are immutable and only their exact issued object can release credit. RGB,
conversion and conservative raw staging consume the host total. Original IPC
returned frames remain charged until their original release; media must not
reserve those bytes again.

Bootstrap and dedicated raw staging are charged before allocation. Dedicated
main continues through the existing exclusive live worker/codec and retained
`LiveParentAuthority`, with distinct native and viewer receipt issuers. Its
native quota is released only by the original custodian's epoch receipt.
Coordinator MAIN_ACTIVE settlement/current checks remain the R166 authority;
provider lease-current alone does not establish that settlement.

The legacy R139 classification is retained. Additional mux/dedicated recovery
accepts only the bounded, captured original result file with the original
owner, directory/file identities and generation, after confirmed reap. It
recognizes only the exact known login-BUSY outcome. Caller cancellation,
expiry and current authority take precedence; unknown, malformed, foreign,
substituted or unreaped results never become BUSY.

## Verification and open gates

The execution workspace's `task-7-report.md` records exact final source hashes,
commands and counts. Tests use synthetic native responses, in-memory pipes and
retained empty custodians. One synthetic login/inventory session opens twelve
immutable slots; post-cut identity, callback revocation, exact credit return,
common pressure, five-second sibling stall and partial original cleanup are
covered. Scoped existing legacy/native tests are selected to avoid actual OS
process/Job probes. No DLL, credentials, recorder, database or Chrome was used.

The old legacy fixture's unsolicited startup notification chain is deliberately
excluded from the accepted twelve-slot synthetic case: the reviewed shared
codec rejects unknown control traffic. The actual recorder notification shape,
route-0/route-2 ACK behavior, substream adaptation and sustained twelve-camera
playback remain **Task 12 probe gates**. Native send/quiescence behavior,
bootstrap transitions on real Windows handles, common memory under real decode,
and main/sub focus acceptance also remain unexecuted.

The Windows native `OWNED` manifest now includes this mux closure. A fresh Root
source review and newly pinned native receipt are required before actual native
execution; historical Stage 1 receipts do not authorize these changed bytes.

## Update log

- 2026-10-06: Task 7 source candidate and synthetic verification documented;
  R167 native open/bootstrap, R168 common credits, R169 dedicated/bootstrap
  original custody integrated. Independent review and actual execution pending.

- 2026-10-06: R1 corrects all four source-review findings; 222 selected source cases pass. Scoped independent re-review and all native acceptance remain pending.

- 2026-10-06: R2 removes the dedicated legacy fallback bypass and serializes exceptional original-frame refunds; 230 selected source cases pass. Scoped I4/M1 re-review and native acceptance remain pending.


## R193 dedicated startup authority correction (2026-10-09)

The approved MAIN transfer now uses current_dedicated_startup with the exact
known lease, retained registration/issuers and complete expected MAIN selection.
Existing0016 selection validates current wall/pending FORWARD focus/master and
actor/session/device/secret/channel scope while LOGIN/CLAIMED; startup no longer
asks the activated-only hot observer. No activated cache entry or grant is issued
by this short query, and its checkout returns before native IO. Ordinary activated
current/freshness/sticky-denial remains unchanged. Source reviewc3102fe6 accepted
the production correction; the test-only expiry margin correction has its own
R1 review. Guarded owned SQL run7b616a1a passed8/8 with normal original/DB/source
cleanup/private0; earlier e592dd93 failed expiry fixture setup and is preserved.

Normal native startup refuses settled native/viewer receipts. Proven original
login-BUSY classification after the same close_native return may supply only
that issued REAPED EpochCleanupReceipt with exact lease/worker/native binding
and all original startup guards. IO callbacks never supply that readback option.
One-shot SQL registration plus retained equality is preserved; selection does
not project SQL registration equality. See the Oct9 diagnosis/fix/R0/R1 reports
in docs/analysis and canonical service report for current actual playback gates.
This source/SQL qualification is not repaired recorder/Chrome or12-camera proof.


## R194 optional first-key diagnostics (2026-10-09)

Native IPC/mux provider now supports a default-off, exact-parent first-key
summary. It snapshots fixed primitive ACK/key/non-key/IPC/parser/partial state
before terminaldeny clears it; enclosing authority-check timing delegates the
original once. Preparedstartup emits once after original startup/cleanup outside
owner locks. It changes no timer, parser acceptance or R193 startup/BUSY guard.
Parent-only measurement cannot prove worker/recorder silence; worker_observed
is fixedfalse, protocol self-clear and concurrent-terminal success limits remain.

Native source review89822cab C0/I0/M0 verified15tests/8delegation-fault/31field
negativecontrols and exactoriginal AST afterdiagnostic removal. Runtimewiring
uses privateboundedCore/native queues and a retained originalpublisher thread;
its uncertain-start correction passes scopedR1, separate from hardware.
Queueoccupancy caps are not run-total caps; the runtime adds independent
128record/64KiB attempted output budgets and finalomitted/failure counters.
See Oct9author/reviewreports and canonicalserviceanalysis for latestactual
execution. Freshpublic/native/source references are required; no actualR194
MAINkey, SUBclose-cause,12-camera orAPKacceptance is established by these gates.
