# Remaining work against the original service and APK plans

Analysis date: **2026-10-08, Asia/Seoul**. Scope: the user's request to check the
original Markdown plans and identify remaining implementation and verification.
This is a source and saved-evidence audit; no implementation, device command,
server/browser run, Git integration or deployment was performed.

## 1. Source baseline and authority

The current implementation authority remains the separate worktree:

`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`

- Branch: `codex/superlive-web-service`.
- HEAD: `6436748f37c799fd14ce03e1d72c86c79eda6b0f`.
- Working tree: 63 tracked modifications and 79 untracked status entries,
  **142 status entries** total. Directory entries are not individual file counts.
- Cached upstream comparison: ahead 3, behind 0. No network fetch was run today.
- All **304 source paths** in the last browser source approval still match their
  recorded SHA256 values. This establishes source correspondence, not runtime
  acceptance or completeness of all application features.
- The primary checkout is `main` at `211d148`, with an existing AGENTS pointer
  edit. It lacks the latest live-media/multiview implementation.

Read the shared analysis policy, both checkouts' AGENTS, the active worktree's
canonical service report, reboot handoff, parity matrix, static parity ledger,
execution ledgers, actual acceptance guide and relevant source before this audit.
The current filesystem permissions allow report writes in the primary checkout
and read access to the implementation worktree. This report does not supersede
the worktree's source authority.

## 2. Original documents checked

| Document | Role | Current stored SHA256 |
| --- | --- | --- |
| `SERVICE_PLAN.md` | Original wider product specification | Read as the planning specification; its 2026-09-21 “implementation not started” header is historical |
| `docs/superpowers/plans/2026-09-21-wisdom-super-observer-implementation-plan.md` | Wider service, 34 task headings including T00A/T05A | `8ee02f8d8ee4f4db64f8add272bf7503798ff9217d7476bd3c9b7ffcc04337e7` |
| `docs/superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md` | APK feature replacement, W00–W25 | `01175370feb0e982d213f276b33aaa8d99031f71c5f17b0217c54a3fd95aec81` |
| `docs/superpowers/plans/2026-10-05-multiview-stage1-plan.md` | Follow-up for substreams and capacity | Read with dated stage1 acceptance and ledger |
| `docs/superpowers/plans/2026-10-06-multiview-stage2-shared-recorder-plan.md` | Follow-up for shared recorder transport | Read with source reviews, actual raw gates and latest handoff |

The paths above are relative to the implementation worktree. The APK plan is its
current stored revision, including later corrections, rather than a recovered
immutable first draft. Plan checkboxes are planning text; the ledgers and actual
receipts establish execution. Likewise, the static seed ledger's NOT_STARTED
build flags are not a current implementation inventory.

## 3. Service purpose, architecture and existing behavior

The wider product combines store surveillance, incident review/notifications,
sales analysis and product registration for multiple tenants. The APK plan adds
SuperLive Plus behavior across accounts, devices, media, controls, events, cloud,
files and conditional Tyco/household features.

Present architecture: React/Next.js/Tailwind frontend, Next BFF, Python/FastAPI,
PostgreSQL authorization/jobs/assets, an mTLS TVT bridge, Windows native provider
and media worker. Tenant/store/connection management and generic job/private
image infrastructure exist. TVT account and directory subsets, local serial/QR
image registration, actual device verification and live-video paths exist.

Stage2 Tasks1–11 and their final source reviews are complete in their defined
scope. Shared recorder transport, substream viewers, admission/cleanup logic,
wall/focus API and React behavior are implemented. This does not complete W08:
APK layouts/paging, named quality policies, snapshot/local recording and full
real-browser acceptance remain separate.

## 4. Immediate remaining work: current multiview slice

| Priority | Remaining task | Current evidence and completion requirement |
| --- | --- | --- |
| P0 | Finish old test-context cleanup | The original isolated Chrome has a saved exit0/reap receipt. The old protected context still exists. Confirm remaining ownership and remove that exact test context using its existing marker guard; preserve the expired run as FAILED |
| P0 | Start a fresh, bounded test run using a controllable Chrome profile | The last run expired during control-tool recovery. Default-profile GPT browser control later worked; its UI observations belong to that profile, not the isolated Chrome process |
| P0 | Verify twelve presented streams for a common **300 seconds** | Stage1 accepted nine simultaneous progressing streams. Stage2 raw two/four gates passed; twelve-camera shared browser playback has not been accepted |
| P0 | Measure stable **1/4/12** load windows | Actual SQL transactions, CPU, process memory, startup latency and drops. Preserve the required SQL budget (at most25 tx/s/live) and measured host headroom; configured credit/process caps are not measured memory |
| P0 | Exercise shared focus/return and lifecycle cases | Presented main→sub return while siblings progress; ten rapid pairs with separate attempted/accepted/presented/cancelled/settled counts; individual Stop, reattach with a fresh post-cut key, last-reference/StopAll and valid resolution changes |
| P0 | Complete final runtime acceptance | Actual applicable lease/slot/master/focus settlement; native/decoder/peer/process/Job retirement; observer COMPLETE/digest; owned DB/context removal; source preservation/private-output checks. Old exceptional/expired retirement is not a pass |
| P1 | Publish reviewed changes | The latest implementation remains uncommitted and main lacks it. Commit/push/integration and post-integration verification remain publication work after the applicable verification gates |

### Saved actual results inspected today

- Raw2 run `0899e1adda99428b93b2a120ba1f2bbb`: COMPLETE, two channels, normal
  worker/native/observer/DB/context/source/privacy flags.
- Raw4 run `10cec96c431e42a2b0aeb7be5c3d9798`: COMPLETE, four channels, the same
  normal final flags and exact prior-two association.
- Each raw slot produced at least two validated post-cut HEVC frames. These
  results establish bounded raw ingress, rather than decoder/browser capacity.
- The last Chrome run verified eight/four inventories through the actual web
  interface, but expired before the required streaming acceptance.
- Newly checked `chrome-owner-receipt.json` reports original Chrome exit0/reap.
  The earlier “please close this Chrome” instruction is therefore obsolete.
  Its `root-owner-receipt.json` remains coordinator exit1/state_removed=false.
- Live listening-port inspection failed with `CimException` under the current
  environment. This audit makes no claim that those ports/processes are free now.

## 5. Remaining work in the APK plan: W00–W25

| Work package | Present subset | Remaining deliverable |
| --- | --- | --- |
| W00–W01 evidence and protocol handoff | APK static audits, inventories, case/checker tooling and several decoded adapters | Resolve each remaining operation's fields/callbacks; establish applicable account/device/brand/entitlement matrices and runtime comparison evidence |
| W02 contracts and persistence | Domain types, tenant controls and generic operation/job primitives | Concrete per-feature executors/readback, API/BFF/React wiring and schema/role tests for the remaining domains |
| W03 startup | Consent, locale/timezone and authenticated shell/navigation | Onboarding, deep links, remaining conditional entry paths and reference-design acceptance |
| W04 bridge | Account/flow/directory RPC and real Windows inventory/live transport | Remaining media/audio/event/control/cloud/Tyco operation families and production runtime/configuration acceptance |
| W05 account | Login/challenge/profile/refresh/logout paths | Real configured-account acceptance, session variants and APK-versus-web comparison |
| W06 account security | Registration/recovery UI/API subsets; private security/SID/crypto work | Full profile/contact/password workflows, avatar, third-party linking, account QR/removal and authoritative state readback |
| W07 devices and sharing | Directory/share reads, local serial/QR image enrollment, eight/four-channel device verification | IP/DDNS/LAN discovery and other onboarding modes, device-management branches, sorting/favorites and sharing create/revoke/readback |
| W08 live video | Continuous live path; sub/main selection; monitoring wall and shared transport source | Current twelve-camera acceptance, exact APK split/paging/presets, capture and local recording, remaining live states and production wiring |
| W09 audio/doorbell | Analysis/contracts | Listening, two-way Talk, microphone/codecs, answer/reject/hangup and custom audible clips |
| W10 recording search | Analysis/models | Recorder calendar/timeline, channel/date/event filters and recording-search UI/API |
| W11 playback/export | Generic job/asset primitives | Recorded-media playback, seeking/speed/audio/frame controls, export/backup, download integrity and expiry recovery |
| W12 browser/gateway onboarding | Browser QR-image input subset | Camera/mic/notification permissions, live QR scan, LAN/AP/Wi-Fi onboarding and applicable background/closed-client behavior |
| W13 alarms/push | Models/static analysis | Real event ingress/deduplication/replay, message inbox/detail/read/delete/navigation, subscriptions and push delivery |
| W14 controls/settings | Generic operation primitives/static analysis | PTZ/presets/cruise, fisheye/lens/light/siren/wiper/unlock, defense/schedules/sensors and remote settings with capability/readback checks |
| W15 sensitive operations | Intent/fencing/unknown-result primitives | Concrete delete/restart/power/firmware operations, confirmation/readback/reconciliation and prevention of duplicate uncertain submissions |
| W16 AI/face/plate | Models/static analysis | Search/history/results, text/speech/picture/face/plate workflows and permitted enrollment/library operations |
| W17 cloud | Models/static analysis | Entitlements, cloud recording/media, download/delete/encryption settings and actual bytes/rights/expiry behavior |
| W18 VAS/payment | Generic operation primitives | Catalog/order/subscription/renewal/payment-return flows and authoritative reconciliation |
| W19 Tyco | Separate domain models/static analysis | Separate identity, panel/device/partition/output operations, events/users/settings/notifications |
| W20 local files | Private JPEG/PNG/storage primitives | User album/file manager, general video formats, playback/download/share/delete and storage/retention error behavior |
| W21 preferences | Locale/timezone subset | Auto-connect, OSD/orientation/gestures, capture/record options, favorites/start screen/cache/domain preferences and actual effects |
| W22 help/H5 | Bundled policy pages | Help/About/version/experience, delivered remote pages and conditional household/resident actions |
| W23 security/recovery | Existing tenant/CSRF/encryption/mTLS controls | Apply and verify controls, audit/metrics, expiry/offline/reconnect and orphan reconciliation across every remaining feature |
| W24 comparative acceptance | Static ledger/checker | Same-state APK and web runs for every reachable applicable case, success/error/offline/permission/expiry variants and independent review |
| W25 production release | Generic infrastructure/CI primitives | Standard service deployment, production identity/keys/certificates, Windows provider/gateway packaging, backup/restore, upgrade/rollback, monitoring and final release decision |

The recorded feature matrix contains **141** rows: 2 ACCEPTED_REAL,
12 IMPLEMENTED_UNACCEPTED, 14 PARTIAL, 109 MISSING and4 NOT_APPLICABLE. This audit
recounted those rows after stripping Markdown formatting. It did not rebuild
the APK inventory or reclassify every row. The counts are the retained inventory,
not a weighted completion percentage. Several multiview notes in that report
still describe the earlier per-tile-login limitation; current shared source and
raw2/raw4 evidence supersede that implementation statement, while the missing
twelve-camera browser/complete W08/APK comparison gates remain real.

The frozen comparison seed contains **77 cases and0 MATCHED**. Its NOT_STARTED
build column is static and stale as an implementation status. The lack of
MATCHED evidence and `release_ready=false` remain valid: a real CCTV acceptance
is not an APK equivalence comparison. Conditional/not-applicable features still
need the original plan's reviewed applicability decision before release.

## 6. Remaining work in the wider original service plan

T01–T05 have implemented/reviewed foundation subsets. T05A has private
upload/image/storage primitives and some passed evidence, with recorded full
provider/runtime failures still requiring resolution. The current core modules,
API registration and app/service directory tree do not expose the following
planned end-to-end user workflows:

| Tasks | Remaining wider service capability |
| --- | --- |
| T00/T00A | APK acquisition/static analysis was done; remaining external/runtime capability proofs stay operation-specific |
| T06–T09 | OrderQueen read connector/catalog, history/backfill/manual refresh, product metrics and sales dashboard |
| T10–T16 | Text/product candidates and review, approved new-product registration/reconciliation, wholesale login/page/history adapters, barcode/OCR photo intake |
| T17/T18/T31 | Generic camera/edge deployment and evidence lifecycle; complete APK-informed TVT P2P scope, production integration and runtime acceptance. Existing local Windows live transport is a subset |
| T19–T20 | Detector/tracking/temporal zones, incident review, visual rules and staff mode |
| T21–T22 | Isolated Codex/Claude CLI inference runner and incident summaries; generic asset subprocess custody is not this feature |
| T23–T25 | Durable web/mobile notifications, mobile application and explicitly approved TTS/camera broadcast. `apps/mobile` is absent |
| T26–T29 | Help/behavior rules, visit/payment association, recurrent-pattern analysis, feedback datasets and controlled model releases |
| T30 | Full service observability/recovery and pilot acceptance |

This is route/module and plan-level gap evidence, not a fresh detailed audit of
every future protocol. Generic jobs/assets/storage can be reused but do not
constitute implemented sales, incidents, mobile or registration workflows.

## 7. Priorities, risks and open questions

Recommended execution order:

1. Finish the shared live slice's fresh Chrome/cleanup/measurement gate.
2. Complete recorder search/playback/export, snapshot/recording and listen/Talk;
   advance decoded device/sharing/control branches with their actual readback.
3. Implement account-security, alarm/push, files/onboarding/preferences/help gaps.
4. Implement applicable AI/cloud/VAS/Tyco/household domains, with scoped execution
   for real writes/payments/output. Missing vendor documentation does not block
   unrelated APK-derived implementation.
5. Execute W24's actual APK/web comparisons and W25/T30 deployment/pilot gates.
6. Track the wider sales/intake/detection/mobile tasks explicitly if delivering
   the full original platform; do not drop them because the recent work focused
   on CCTV.

Material risks: confusing source reviews with device/browser acceptance;
presenting stale plan checkboxes or static ledger flags as current status;
assuming raw2/raw4 establishes twelve decoded browser streams; considering a
test fixture production deployment; publishing the main checkout without its
uncommitted worktree implementation; and marking conditional features excluded
without proof. No new scope question was resolved in this audit. Applicable
models/firmware/roles/regions/entitlements, deployment configuration and scoped
authorization for sensitive live tests remain the existing plan questions.

## 8. Verification and limits

Executed read-only checks: `git status`, `git log`, `git rev-parse`, cached
`git rev-list`; plan/task-heading extraction and hashes; source/API/app-tree
inspection; Markdown matrix/seed counts; all304 approved source hashes;
sanitized readback of raw2/raw4 and Chrome/coordinator receipts. No tests were
rerun and no APK comparison/device call/browser action occurred. A broad ignored
artifact search hit ACL-denied historical temporary fixture directories; exact
canonical documents and relevant receipt paths remained readable. CIM listening
port inspection failed and its result was not converted into a “ports free” claim.

Update log: 2026-10-08 — compared both original plans with current worktree
source/evidence, recorded all remaining domains and current multiview gates,
corrected the obsolete Chrome-close prerequisite, and preserved historical
counts/failures with their actual verification limits.
