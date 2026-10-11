# Shared connection-card live playback fix

Analysis and implementation date: **2026-10-09, Asia/Seoul**. Frontend source
and focused synthetic verification; actual recorder/Chrome acceptance remains
Root-owned and is not claimed here. Read this report before changing connection
card shared playback, and refresh its evidence after implementation or actual
acceptance. Canonical service and project instruction updates remain Root-owned.

**Latest checkpoint: fix round 1 is frozen for one scoped re-review.** The
initial review found I1: a fulfilled wall Stop could still be STOPPING and its
cross-remount cleanup promise was removed too early. The correction and its
132-test focused verification are recorded at the end of this report. The
initial 103-test checkpoint and hash table below remain historical evidence.

## Baseline, purpose and causal evidence

Worktree: `C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Branch: `codex/superlive-web-service`; HEAD:
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, plus the already reviewed uncommitted
Stage 1/2 implementation. The starting tree was dirty, including the monitoring
wall, local player, API client, connection panel and their existing tests. Those
changes were preserved; the hashes below identify the current complete files,
not a claim of authorship of their preexisting changes.

The service lets an OWNER inspect an authorized local recorder and play a
selected channel on its connection card. Root's preceding bounded actual run
confirmed login and the two saved inventories, but card playback returned
`422 LOCAL_DEVICE_INPUT_INVALID` before any worker attempt. The shared API
requires `wall_id` and, for main, `focus_ref_id`; the card always constructed the
legacy request and received no server shared-mode flag. This is the causal
frontend gap. Root reports that actual run has normally retired; this author
did not start or inspect a running hardware session.

Read-before sources: project `AGENTS.md`, shared analysis policy, current
`docs/service-analysis.md`, approved Stage 2 shared-recorder spec and plan,
`apps/web/src/features/monitoring/live-wall.tsx`, wall group, scheduler, player,
wall/live API clients, and existing panel/wall/inventory tests. Planned Stage 2
behavior and historical actual receipts remain qualified by those authorities.

## Implemented behavior and architecture

1. The existing `ownedSharedMode` validator was moved without validation changes
   from the monitoring server page to a `server-only` helper. Both server pages
   consume it. Missing mode retains legacy behavior; malformed mode/context or a
   mismatched exact profile fails closed. Client input does not select the mode.
2. `ConnectionsPage -> ConnectionsView -> LocalDeviceInventory -> LocalLivePanel`
   passes that server flag. The legacy panel remains the default. The panel key
   includes connection generation, inventory revision, device/store/tenant,
   CSRF and mode, so a changed scope retires the previous component.
3. The small shared card adapter uses the existing `createWallRuntime`,
   `LiveWallGroupController`, `LocalLivePlayer` and `LiveVideo`. The existing
   runtime implementation gained only export modifiers for its factory and two
   public types. Its focus and original-player lifecycle was not rewritten.
4. Low quality creates its private server wall and starts scoped sub. Default
   high quality first starts sub; only its accepted current lease can trigger
   a real `FORWARD` reservation. The main replacement uses that reference and
   awaits the original player's Stop. Switching live high to low uses a real
   `RETURN` reservation and the corresponding sub replacement.
5. Stop and terminal failed startup retire the card wall. A failed startup is
   terminal until manual Play. Pending Play is fenced synchronously on Stop;
   repeated clicks cannot replace a pending player. Quality changes use the
   existing runtime's intent cancellation. Channel selection remains disabled
   until the previous playback and wall stop settle.
6. Original card cleanup promises are retained at the adapter module boundary
   across keyed generation/credential remounts and full card unmounts. A new
   card's Play awaits all those retained original Stops. Rejected cleanup stays
   fenced; it cannot be concealed by a replacement. This conservative barrier
   may delay another card while a previous card is retiring.

No API validator, grant/auth guard, SQL admission, native transport or private
identity contract was relaxed or changed by this author. No random client wall
or focus ID is generated, and no link substitutes for the existing card feature.

## RED, GREEN and verification

The first nine behavioral regressions were written before production changes.
`pnpm --filter @wso/web test tests/shared-connection-live.test.tsx` returned
**9 failures / 9 tests**, exit 1: the existing card ignored the shared flag,
created no wall and no injected shared player. This included the causal complete
connection-card flag chain regression. The RED output was inspected.

The first combined implementation run had 5 remaining test failures. Its
pending-wall test clicked Stop before the asynchronous creation request had
actually begun, and the cancellation fake lacked a closed settlement response.
The tests were corrected to wait for that explicit boundary and provide the
complete settlement DTO. These corrections retain assertions against actual
card/runtime behavior. The nine original tests then passed. Additional scoped
tests cover the outgoing real player's `wall_id`, selected channel, full
unmount barriers, rejected Stop fence, both server pages and invalid profiles.

Final commands executed against the frozen source:

```text
pnpm --filter @wso/web test tests/shared-connection-live.test.tsx tests/owned-shared-mode-pages.test.tsx tests/local-live-panel.test.tsx tests/live-wall.test.tsx tests/live-wall-group.test.ts tests/local-device-inventory.test.tsx
  6 files PASS; 103 tests PASS; exit 0

pnpm typecheck
  next typegen and tsc --noEmit PASS; exit 0

pnpm --filter @wso/web exec eslint src/features/connections/shared-local-live-panel.tsx src/features/connections/local-live-panel.tsx src/features/connections/local-device-inventory.tsx src/features/connections/connections-view.tsx src/features/monitoring/live-wall.tsx src/app/connections/page.tsx src/app/monitoring/page.tsx src/lib/tvt/owned-shared-mode.ts tests/shared-connection-live.test.tsx tests/owned-shared-mode-pages.test.tsx
  PASS without warnings; exit 0
```

An intermediate lint invocation caught a ref assignment during render and an
effect-cleanup ref warning; those were fixed before the final clean gate.
Verification used the real React adapter, wall runtime, group and scheduler;
synthetic player and network/filesystem boundaries replace hardware and private
server context. The full frontend suite and build were not run: Root explicitly
bounded this correction to focused regressions and static gates.

## Exact author scope and frozen SHA-256

Paths below are repository-relative. Each hash covers the entire current file.

| File | This author's change | SHA-256 |
| --- | --- | --- |
| `apps/web/src/app/connections/page.tsx` | Helper import and validated flag prop | `7f6259c8e3c6af8a734a77be201d4bc36a308ffde8990131916a10070427c09f` |
| `apps/web/src/app/monitoring/page.tsx` | Extract validator, consume shared helper | `570bbd3ee568c9be07d5e9c5431e2978367cc496fd6cd46670d4672ad398c2c8` |
| `apps/web/src/features/connections/connections-view.tsx` | Flag forwarding | `43bf2ee5d827f7738020c5104027d0b15bb15adf30e876c26bbd28f6956201e6` |
| `apps/web/src/features/connections/local-device-inventory.tsx` | Flag forwarding | `c666d04e20f23f3fa5ba0cf47dfe5483ad0d2794fab8749c8519d1ccf7bcb7fe` |
| `apps/web/src/features/connections/local-live-panel.tsx` | Shared branch and scope key | `80aaa06f9b16485917c75fa420d7d5b913a19836d07b823f6d9a9b8081ffcb28` |
| `apps/web/src/features/connections/shared-local-live-panel.tsx` | New adapter | `5d9b1121d222118b9b11888767a6ba674486d82df01cf5e44c907b8dbb9d9250` |
| `apps/web/src/features/monitoring/live-wall.tsx` | Three export modifiers only | `c300c1436208ed6a466e0755dc15d05b2192d0ef9a8ef63479161c6812db6220` |
| `apps/web/src/lib/tvt/owned-shared-mode.ts` | New shared server helper, identical validator | `744b7ec031200eb70d43f15236bf469babac73500957525cb588a40c4935d73a` |
| `apps/web/tests/shared-connection-live.test.tsx` | New 12 card regressions | `112ea64a57f615635ad395970965c22b519d3e09aae8e509d41264c8ebd33c5c` |
| `apps/web/tests/owned-shared-mode-pages.test.tsx` | New 3 server regressions | `88e7fc4aed0d24c27ca5dffc8b0f7b2b67c7e19f64d02cab0d0c598ef51bcb63` |

This report is the additional author-owned documentation file. Root owns
`AGENTS.md` and the service report; this author did not edit either. Existing
large Git diffs for monitoring/player source are inherited Stage 1/2 work and
must not be mistaken for this bounded patch. No Git index, commit, process
control, database or credential operation was performed.

## Risks, priorities, open questions and acceptance limits

- **P1:** Fresh independent source review of these exact files precedes new
  immutable source approval and real browser/device acceptance.
- **P1:** Actual card sub/main/return, first presented frame, real original
  Stop and wall cleanup require a new Root-owned bounded Windows/Chrome run.
  Synthetic tests do not establish recorder decoding, runtime sizing or the
  twelve-camera monitoring acceptance gate.
- **P2:** Rejected original card cleanup intentionally fences subsequent card
  starts in this client module. Safe recovery from unresolved actual cleanup
  remains a Root/backend decision; this patch supplies no fabricated receipt.
- **Open product question:** Production enablement remains beyond the existing
  owned test bootstrap. This patch preserves its explicit exact-profile gate.
- **Open product question:** Separate private card walls remain subject to the
  existing server actor/wall/main quotas; tests do not prove multi-card focus
  capacity or cross-tab behavior.

Update log: 2026-10-09 — causal 422/frontend gap documented; bounded shared card
adapter implemented, 9-test RED witnessed, final 103 focused tests/type/lint
GREEN, current file hashes frozen and actual acceptance left explicitly open.

## Fix round 1 — original STOPPING wall remains fenced

Date: 2026-10-09, Asia/Seoul. Read and verified independent review
`docs/analysis/2026-10-09-shared-connection-live-review.md`, SHA-256
`b60653e2b71022cdda7e60e4c24d8a58c1298885e5e04874a97f925f06d5702f`,
verdict C0/I1/M0. Its I1 matches the existing controller contract: group and
runtime Stop promises can fulfill on STOPPING while the group stays fenced.
The adapter's initial promise-only retention was therefore insufficient across
a new component/runtime. This supersedes the initial claim that any fulfilled
aggregate Stop was enough to release the card replacement barrier.

The three new causal tests (inventory, CSRF and full unmount replacement) were
run against the initial frozen implementation and all failed: a second wall
was created while the original Stop had returned STOPPING. Command:

```text
pnpm --filter @wso/web test tests/shared-connection-live.test.tsx -t 'retains fulfilled STOPPING'
  RED: 3 failed / 3 selected; each expected one original create and observed two
```

The fix injects a card-specific Stop API into its existing wall group. A normal
CLOSED Stop returns directly. A STOPPING result keeps that original Stop
pending while a bounded readback polls the exact original wall/tenant until
CLOSED. The original group/runtime thus never fulfill this card Stop on a
nonterminal view. Disposal does not substitute `isFenced` for cleanup proof:
the proof comes from the exact server wall response.

The backend and BFF already expose GET for an exact wall. Root approved only
the small missing typed client exposure and bounded transport reuse:
`readLocalWall` validates tenant/wall UUIDs, uses a same-origin GET with no body
or CSRF write header, and validates response correlation, exact tenant, wall
and the strict public schema. The existing request transport gained an optional
closed GET/POST method argument; default POST behavior, error/body bounds,
25-second request bound and cancellation remain intact.

Readback has one independent 25-second deadline after the original Stop POST,
checks immediately, and waits 500ms between still-STOPPING views. Each GET also
consumes that same original deadline signal; the delay cancels on expiry.
There is no new native or backend lifetime extension. Readback captures the
original tenant/wall arguments; a new card's CSRF, channel, inventory or scope
cannot retarget it. It uses the existing cookie/session authorization and never
swaps private credentials or treats an inaccessible view as closed.

Repeated STOPPING, 503, expiry, foreign scope, ACTIVE/unknown cleanup and
rejected original Stop keep the cross-remount retained fence. If readback fails,
the same rejected original remains retained; replacement is prevented and the
card uses the existing public failure copy. Successful exact CLOSED releases
the barrier only after the runtime's other original Stop/ref/operation waits
settle. A late wall returned after cancelled creation also uses this same Stop
supplier. The wall group, wall runtime, backend API/Core/SQL/native guards were
not changed in this fix round.

Additional controls verify real GET serialization and abort/scope rejection,
cancel/remount while original deadline readback is pending, 503/expiry/foreign
scope/ACTIVE quarantine, repeated STOPPING followed by exact CLOSED, the earlier
delayed CLOSED positive controls and the existing rejected-player-Stop control.
The new typed-read test initially failed because its client function was absent;
the causal three-test RED above establishes the actual lifecycle defect.

Final executed gates against this freeze:

```text
pnpm --filter @wso/web test tests/shared-connection-live.test.tsx tests/shared-connection-cleanup-failure.test.tsx tests/local-live-wall-api.test.ts tests/local-live-api.test.ts tests/live-wall-group.test.ts tests/live-wall.test.tsx tests/local-live-panel.test.tsx tests/local-device-inventory.test.tsx tests/owned-shared-mode-pages.test.tsx
  9 files PASS; 132 tests PASS; exit 0

pnpm typecheck
  PASS; exit 0

pnpm --filter @wso/web exec eslint src/features/connections/shared-local-live-panel.tsx src/lib/tvt/local-live-api.ts src/lib/tvt/local-live-wall-api.ts src/lib/tvt/owned-shared-mode.ts tests/shared-connection-live.test.tsx tests/shared-connection-cleanup-failure.test.tsx tests/local-live-wall-api.test.ts
  PASS without warnings; exit 0
```

### Fix-round-1 frozen SHA-256

These seven files changed from the initial review freeze. The other seven files
in the full fourteen-file author scope retain their original hashes above.
The helper change only removes the review-noted extra blank line at EOF.

| File | Current SHA-256 |
| --- | --- |
| `apps/web/src/features/connections/shared-local-live-panel.tsx` | `2431dbc806d7356562c5b743acea6dac6aef8008f5ea4aa32653f1caaacb8d79` |
| `apps/web/src/lib/tvt/local-live-api.ts` | `66e03169ea649aa94025813a92abc810d2e2cef33c32c940d0bb0c71a0551408` |
| `apps/web/src/lib/tvt/local-live-wall-api.ts` | `77389acda14b888276079efbf0ce7864cf0289d1d297a2079256cf32ab2d04ac` |
| `apps/web/src/lib/tvt/owned-shared-mode.ts` | `22852e9f7f222a00b16114a43b46c91e0bfbc3d44a808e24999ffa3442346c56` |
| `apps/web/tests/shared-connection-live.test.tsx` | `8791fb4769e3d1e183d9cbd2dc904d8cd0fc58c99cbde80340e41878684131d6` |
| `apps/web/tests/shared-connection-cleanup-failure.test.tsx` | `074b82bb726fcecde340a5df04dd7487ae696cfccda0ed6b674af2fc2f593eda` |
| `apps/web/tests/local-live-wall-api.test.ts` | `6ae8c898511e29361350fa2208bb6d2492228043dbd5486d894a39ee07fc289d` |

Limits/priorities remain: one scoped independent I1 re-review, fresh immutable
source approval, then Root-owned bounded Windows/Chrome recorder acceptance.
No actual hardware, process control, DB, credential or Git-index operation was
performed in this fix round. The full frontend suite/build were not run under
the explicitly focused correction scope. A readback timeout/error intentionally
leaves this client fence quarantined; recovery UX remains an open product/backend
decision and no automatic replacement is supplied.

Update log: 2026-10-09 — I1 verified, 3 causal STOPPING/remount RED failures
witnessed, exact-wall readback barrier implemented, final 132 focused tests and
type/lint gates GREEN, fix-round-1 hashes frozen for one scoped re-review.
