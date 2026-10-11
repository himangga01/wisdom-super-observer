# R194 public source receipt and native pin review

Analysis date: **2026-10-09, Asia/Seoul**. Narrow independent source/closure gate.

**Verdict: C0 / I0 / M0.** The fresh v3 public receipt, two native pin literals
and appended provider-guide qualification satisfy this scope. All 43 public
source/dependency byte-and-hash bindings match. No critical, important or minor
finding was identified. This verdict does not create private native/runtime
approval or establish actual R194 recorder, MAIN, SUB or Chrome acceptance.

## Authority, scope and baseline

Read before review: `C:/Users/강지혜/.agents/analysis-policy.md`, worktree
[AGENTS.md](../../AGENTS.md), current canonical
[service report](../service-analysis.md), the established
[R193 native pin review](2026-10-09-dedicated-main-native-pin-review.md), and the
current public receipt and provider-guide appendix. Reuse the frozen R194
[native review](2026-10-09-native-first-key-debug-review.md), runtime
[R0 review](2026-10-09-core-close-state-debug-review.md) and
[R1 review](2026-10-09-core-close-state-debug-review-r1.md) as source authority.
Read these before changing receipt/pin references and refresh affected evidence
after source or actual acceptance. The controller owns AGENTS/service bridges,
private approvals and execution; this reviewer writes only this report.

Implementation worktree:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`.
Freshly checked branch `codex/superlive-web-service`, actual HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with retained Stage 1/2/R193/R194
changes. Pre-pin R1 snapshot tree:
`31d57e085bf9976c315cfa678c38f195781b3d58`. This is a comparison tree, not a
HEAD/index change. Scoped status showed the Windows provider modified and public
v2/v3 receipts/provider guide untracked in the actual checkout. Direct byte
comparison verified the existing guide's append-only content; its untracked
index state is not a filesystem deletion.

The assigned scope is the new public receipt, the two Windows-provider pin
values and the provider-guide R194 appendix. Prior implementation reviews and
launcher behavior remain frozen. No application source, test, index or HEAD was
edited by this reviewer.

## Service purpose and exact reviewed changes

The service presents authorized local CCTV channels in Chrome. Reviewed R194
adds optional exact-parent MAIN first-key counters and runtime Core close-origin
records. The runtime publisher retains its original thread and unknown startup
custody, drains outside authority locks, and applies independent output budgets.
This gate brings those accepted source bytes into the existing public receipt
reference without changing native execution/retirement bodies.

| Artifact | Fresh SHA256 |
| --- | --- |
| `docs/integrations/receipts/tvt-local-live-mux-stage2-source-v3.json` | `72e32b40c075f407d64713f741a4d7dc2b7b4213000a9ce08f1a451dc092b875` |
| `services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py` | `9be24918b774567949c5e1ec62dc99b0389695ba1c434a9872be59c764f6896f` |
| `docs/integrations/tvt-local-live-mux-provider.md` | `b7f5ee2ceb7edb8e121fd1cc9fb1ca364bab676e41cbecfa4f7fc189ef1a18ab` |

`windows_socket.py:57` changes `LIVE_RECEIPT` from the historical v2 path to
`docs/integrations/receipts/tvt-local-live-mux-stage2-source-v3.json`. Its
accepted SHA256 at line 62 changes from
`0aec9097b0e132e34532dbcbfc0681da62f2e21a222ab972a302a0948efb0879`
to the v3 hash above. Each changed literal appears exactly once. Reversing only
those two literals recovers the exact previous raw provider SHA256
`32cd642a8e2ec74a7afefdaae14c365ad89a016db5ac21337e291bd5c4dae2cd`
and exact normalized source/AST of the pre-pin snapshot. All native guard,
manifest, bootstrap, parser, timer, authority and cleanup bodies are unchanged
by this pin update.

The v3 JSON contains **27 files / 16 dependencies**. All **43** referenced
current raw byte counts and SHA256 values matched independently. Duplicate JSON
keys, overlapping file/dependency paths and paths outside the project were
checked; none were present. Relative to v2:

- Seven file entries are added: native IPC/helper/diagnostic test and four
  runtime/helper/Core-state test references. The provider is the fourth native
  source/test reference and was already present in v2.
- Only two existing file bindings change: the separately reviewed R194 mux
  provider and the appended provider guide. All other prior file bindings stay
  identical.
- Five R194 author/review report dependencies are added. All eleven prior
  dependency bindings remain identical.

The native four-path and runtime R1 source/test hashes remain those accepted
by their frozen reviews. The five new report bindings freshly matched:

| R194 report | SHA256 |
| --- | --- |
| Native author | `30a4b918f03dc07f59b948a937b93c509ba17924f9d635e5b004511bc9479bc6` |
| Native review | `89822cabd5ea27381a5b126588f36c7f5215ecabf49b4c0bd72ad7a718230391` |
| Runtime R1 author | `470daf455e4f12909f4202f70b7235c2bcf0ea16c3460404410337c9b6a10416` |
| Runtime R0 review | `f875e419a0bb01141efcf3f8f65f5701d290d6c61a553c05ce7995bcc618c4de` |
| Runtime R1 review | `ed2564222c2c36a5e013be67a307b16dc782e366a8602cb3f2696ad6527f8b98` |

The primary native-review and supplemental runtime-R1 references match those
exact dependency hashes. The included historical R0 I1 remains preserved;
runtime R1 resolves it. The zero current blocking/source finding counts therefore
describe the accepted current gates rather than rewriting historical evidence.

The status remains
`SOURCE_ACCEPTED_WITH_EVIDENCE_QUALIFICATION_UNPUBLISHED`. Actual shared-recorder
frames, Windows-profile and Chrome-acceptance flags are all **false**. The
qualification explicitly states parent-only/non-atomic/bounded measurement,
unchanged timer/parser/authority behavior, preserved historical artifacts, and
unestablished actual Core-close cause, MAIN/Chrome, twelve-camera duration/
performance and APK equality. Those flags are source-receipt qualifications,
not fresh observations of a device run.

The provider guide is append-only relative to the pre-pin tree. Its new R194
section states default-off exact-parent diagnostics, fixed primitive state,
one original authority-check delegation and callback delivery outside owner
locks. It retains parent-only/protocol-self-clear/concurrent-terminal limits,
separates queue occupancy from runtime 128-record/64-KiB attempted output
budgets, references the reviewed uncertain-start correction and source C0
qualification, and requires fresh public/native/source references. It claims
no actual MAIN-key, SUB-close-cause, twelve-camera or APK acceptance.

**Exact findings: none. C0 / I0 / M0.**

## Fresh verification and preservation evidence

One successful read-only stdin probe ran through
`.venv/Scripts/python.exe -B -`, exit **0**. It checked the new receipt hash,
all 43 current raw bindings, the exact receipt extension, closed source status/
actual flags, review/report hash references, exact two-literal provider reversal,
pre-pin normalized AST equality and append-only qualified guide content.
`ast.parse` and `compile(..., 'exec')` succeeded without executing the native
module. Fresh `git rev-parse HEAD`, branch/status and direct bounded reads were
also performed.

Historical public v1 remains
`96aa2b0a979fb22f286a72699a5d2eec18cf3544863c216fe5bef94fe2387a02`;
v2 remains
`0aec9097b0e132e34532dbcbfc0681da62f2e21a222ab972a302a0948efb0879`.
Both normalized raw bodies and the R193 native pin review match the pre-pin tree.
The R194 launcher remains exactly
`307634df575aeb4b317fa8e6106c8410596844385e44f2a206f6ee3b24829fc1`;
its two earlier substitutions were already accepted in the frozen runtime R0
review and were not broadened or executed here. Frozen R193 and R194 review
dependencies were preserved.

No tests or optional suites, DB/SQL operations, SDK/native child/Job, recorder,
browser, private native approval, live input, source/test/index/HEAD mutation,
staging, commit, push or nested agent were performed. Only this report was
written. Historical inert/SQL/device evidence stays attributed to its original
reports; this gate adds source byte/AST/reference evidence only.

## Remaining gates and open questions

Priority P1: the controller creates fresh separately qualified private native
and immutable runtime-source approval closures for these exact accepted bytes,
then executes the authorized bounded diagnostic run and normal original
retirement. The public source pin verdict alone does not establish private
manifest runtime acceptance, SDK first-key arrival, browser frame advance,
repaired MAIN, first unexpected SUB close cause, twelve-camera performance or
APK parity. No additional product choice is introduced by these references.

Update log: 2026-10-09 — narrow R194 pin/closure C0/I0/M0; 43 raw byte/hash
bindings, exact two native literals, unchanged original AST, append-only guide,
source-only flags and frozen historical/report/launcher bytes verified.
Private approval materialization and actual execution remain controller gates.
Freeze this report after its final hash is supplied.
