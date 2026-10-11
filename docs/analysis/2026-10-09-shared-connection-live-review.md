# R191 shared connection-card live playback: independent source review

Review date: **2026-10-09, Asia/Seoul**. Scope: the ten frozen R191 frontend
files only. Verdict: **C0 / I1 / M0; source approval withheld pending I1**.
No application source was edited and no tests, hardware, Chrome, database,
credential, SDK or runtime/process operation was executed for this review.

## Authority and baseline

Read-before authorities: the shared personal analysis policy, this worktree's
`AGENTS.md`, current `docs/service-analysis.md`, the approved Stage 2
shared-recorder design and plan, and
`docs/analysis/2026-10-09-shared-connection-live-fix.md`.
Root owns the canonical service report and project instruction updates.

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch supplied for this review: `codex/superlive-web-service`.
Observed HEAD: `6436748f37c799fd14ce03e1d72c86c79eda6b0f`.
The working tree already contains reviewed Stage 1/2 changes and concurrent,
separately owned R191 diagnostics/runtime work. This review does not reopen
those changes or treat the full HEAD-to-working-tree diff as the author's patch.

Frozen bounded comparison:

- BASE tree: `5a15289d870f2295d307c5237c9c0194df887a2e`.
- Candidate tree: `88ce5a413a607f154f97aef1438602534c1074c2`.
- Review diff: `.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan/task-1911-review-r0.diff`.
- Frozen manifest: the same directory's `task-1911-frozen-hashes-r0.json`.
- Author report SHA-256, independently matched:
  `fc6ec82c2474291efa659d95c24daafedc9a4142284dc07d56f62b1d339f4867`.
- All ten current source/test files matched their frozen manifest SHA-256.
  The diff file measured 40,501 bytes in this review; the dispatch's 39,697-byte
  figure differs. Source/hash agreement, rather than that byte-size description,
  identifies the reviewed candidate. Root's previously established legacy
  source-envelope and connection-page line-ending qualifications remain intact.

## Purpose and implemented structure

The service provides OWNER access to authorized local recorder inventories and
selected-channel CCTV playback. Root's historical actual browser run established
login and eight/four-channel inventory access, followed by card POST 422
`LOCAL_DEVICE_INPUT_INVALID` with no worker startup attempt. It did not establish
playback acceptance. The causal frontend mismatch was the standalone card's
legacy request while shared mode requires a server-issued wall and a main-focus
reference.

This patch extracts the unchanged owned-profile validator into a server-only
helper and passes its flag through the connections page, view, inventory and
panel. The shared panel owns a private `LiveWallGroupController` and consumes the
existing wall runtime, player and video component. The wall runtime diff consists
of three export modifiers only. Legacy mode remains the default.

The existing runtime supplies sub bootstrap, FORWARD before sub Stop/main start,
RETURN before main Stop/sub replacement, bounded focus intent cancellation,
heartbeat and exact-current-player event checks. The new adapter adds channel
selection, quality controls and a module-level set intended to retain cleanup
across inventory/credential remounts and full card unmounts.

## I1 — fulfilled STOPPING cleanup is forgotten across a card remount

**Important, P1; blocks source approval.** Primary changed location:
`apps/web/src/features/connections/shared-local-live-panel.tsx:13–19`, with
cleanup at lines 46–49 and replacement startup at lines 56–63.

`retain()` removes an original from the global set whenever its promise
fulfills. That is not sufficient evidence of terminal wall cleanup for the
reused runtime contract:

1. `apps/web/src/lib/tvt/live-wall-group.ts:167–194` retains `fenced` and
   `closing` when the server returns `wall.state === 'STOPPING'`, but line 184
   returns normally. The promise therefore fulfills while original cleanup
   remains unresolved.
2. `apps/web/src/features/monitoring/live-wall.tsx:376–386` also fulfills its
   aggregate Stop promise after that group promise. Its `stopping` property
   still reflects the original group's fence at lines 374 and 399.
3. The new adapter deletes that fulfilled aggregate at line 16. The old mounted
   card remains disabled through its local `stopping` state, which is correct.
   However, a new inventory revision, credential/CSRF key, or full unmount/remount
   replaces that runtime with a fresh group (panel key at
   `local-live-panel.tsx:9–11`; adapter construction at line 35).
4. Cleanup calls `created.dispose()`, which returns the same fulfilled original
   Stop chain for this case (`live-wall.tsx:482`). Retaining that promise again
   also removes it on fulfillment. The new card's `waitOriginalStops()` can then
   finish and issue a new wall/player request despite the old wall's unresolved
   original custody. Its fresh runtime cannot see the previous group's fence.

This is an adapter integration defect, not a request to weaken the existing
controller or backend gates. Server quota/ownership checks may still reject the
replacement, but they do not make the card's promised original cleanup barrier
correct. A new card must not conceal unresolved cleanup by discarding the old
controller state.

The existing source tests explicitly document the underlying contract:
`apps/web/tests/live-wall-group.test.ts:49–54` awaits a fulfilled STOPPING result
and confirms the original group remains fenced; `apps/web/tests/live-wall.test.tsx:420–431`
checks the retained in-instance STOPPING fence. New card tests exercise delayed
CLOSED and rejected Stop, but their wall fixture only supplies ACTIVE/CLOSED and
does not cover fulfilled STOPPING across remount.

**Minimal correction:** retain the original runtime/group's nonterminal fence
as well as its promise. Release the cross-remount barrier only when that exact
original cleanup is established terminal/CLOSED by the existing same-original
cleanup supplier or a narrowly scoped authoritative readback. Fulfilled STOPPING,
rejection and unknown cleanup remain quarantined and charged. Preserve the
current API/native/Core authorization contracts. A plain post-dispose
`isFenced`/`stopping` check needs care: disposed itself also fences a successfully
closed group, so disposal must not be mistaken for unresolved cleanup or vice
versa. If no terminal supplier exists in the bounded adapter, conservative
retention is preferable to inventing one.

**Required causal regressions:** start and Stop with a fulfilled STOPPING wall
response, then change inventory/credentials or fully unmount/remount; assert no
replacement wall creation or player start. Include cancellation/remount during
that cleanup, terminal CLOSED positive controls and the existing rejected Stop
control. Test the actual adapter and reused controller/runtime boundary. No
hardware test is needed to demonstrate this source defect.

## Other scoped review results

- The shared-mode helper retains the former monitoring validator's checks,
  including exact profile and owned path validation, and adds `server-only`.
  Both pages consume it. The flag chain addresses the reported 422 cause without
  introducing client-selected mode or fabricated wall/focus IDs.
- The new runtime bindings use the selected inventory channel, connection,
  generation, revision, store, device and tenant. Keyed remounts cover changed
  scope. The global set is a conservative cleanup barrier, not an authority or
  media pool; it does not merge those bindings.
- Sub/main replacement and current-player frame admission continue through the
  existing runtime guards. No additional scoped defect was identified in those
  paths. Existing callback/focus/heartbeat behavior is consumed here, not newly
  accepted as a whole-branch review.
- The new outgoing-request regression uses the real default player and checks
  the serialized shared sub `wall_id`. High/return tests check the real runtime's
  focus sequence and replacement bindings using synthetic players. Actual main
  recorder frames and original hardware cleanup remain unverified.
- `git diff --check` for the bounded comparison returned exit 1 solely for a
  new blank line at EOF in `owned-shared-mode.ts:58`; this is nonblocking
  formatting, not an additional C/I/M finding.

## Verification and limits

Executed only read-only source inspection, `git rev-parse HEAD`, working-tree
status, bounded `git diff`, `git diff --check`, `Get-Item` and SHA-256 comparison.
The inspected source files matched the ten manifest values. No tests were run
by this reviewer, as explicitly scoped by Root.

The author's nine-test causal RED, final six-file/103-test GREEN, typecheck and
ten-path lint outcomes are report-provided evidence, not independently rerun
results. The review traced the I1 sequence directly against current functions
and the documented STOPPING test contract; it does not claim a newly executed
reproduction. Actual Windows/Chrome playback, first frame, recorder cleanup,
twelve-camera acceptance and APK parity remain separate Root-owned gates.

Priority is one bounded I1 correction and scoped re-review before a fresh
immutable source approval or changed-code runtime. Product enablement beyond
the existing owned bootstrap and recovery UX for unresolved cleanup remain open;
neither is authorized or answered by this source review.

Update log: 2026-10-09 — initial independent frozen R191 source review completed;
all ten hashes matched; one important cross-remount STOPPING ownership defect
recorded; no runtime or source mutation performed.
