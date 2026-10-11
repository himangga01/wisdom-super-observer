# R198 shared ingress repair: independent SPEC and QUALITY review

Review date: 2026-10-10, Asia/Seoul. **SPEC C0/I0/M0; QUALITY C0/I0/M0.**
No blocking or nonblocking source findings in the seven frozen paths. This
verdict permits Root's fresh combined source/native closure and bounded replay;
it does not establish recorder or browser acceptance.

## Scope and baseline

Reviewed the R198 brief, frozen diff and seven-path hash manifest against the
current implementation worktree on `codex/superlive-web-service`, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. The frozen delta is from immutable
tree `b829c5d5aaba3072f88df56b6fa3c47b4b817caa` to
`d6e8d5878292e38e55afffb7437a54b83015a886`. The starting worktree already
contained substantial uncommitted Stage1/2 and diagnostic changes. All seven
current file hashes match the supplied manifest.

Read with [author report](2026-10-10-shared-ingress-repair.md),
[parked-ingress diagnosis](2026-10-10-parked-ingress-causal-diagnosis.md),
[service report](../service-analysis.md), project [AGENTS](../../AGENTS.md),
the shared analysis policy, and approved Stage2 design/plan ownership, cut,
credit and cleanup requirements. Reuse this report before changes and refresh
after source or actual acceptance. Root owns the AGENTS/service handoff update.
R199 runtime tracing and unrelated existing broad-suite failures are outside
this source review.

The service carries authenticated camera views through retained original
recorder epochs. R198 adds a consumer for the all-SUB-parked interval and exact
private terminal metadata while preserving the existing foreground reader path.

## SPEC checks

- `local_live_mux_provider.py:210,248,311,968,1005`: the original Thread,
  stop/completion/start-outcome Events, parent, owner, custodian, IO lock and
  epoch are retained before start. Receipt paths require actual target finish,
  completed start attempt, original join and non-alive observation; aliases are
  rechecked after join. Unknown start, failed join and entered pump retain
  custody. Close signals the original stop Event before native retirement.
  Neither the existing custodian receipt nor bootstrap-credit release bypasses
  the consumer/operation barrier through the reviewed master API.
- `local_live_mux_provider.py:263`: opportunistic IO acquisition treats a busy
  foreground/refresh owner as contention. Invocation and authority barriers
  precede pumping. The original parent's opened-slot/no-cut predicate is checked
  under the same IO lock as attach, park and refresh. Existing parent codec,
  FIFO provenance, pre-cut filtering and reserve/rollback remain responsible
  for every consumed packet. No viewer grant, raw-buffer clear or limit change
  is introduced. Sixteen calls, a 50ms slice, 250ms operation clip and 10ms wait
  bound cooperative scheduling; active cuts hand pumping back to readers.
- `windows_socket_worker.py:1467`: terminal sampling binds the original drive
  result and callback identities, generation and bound dispatcher epoch.
  Primitive sampling runs outside callback execution without a new callback
  lock, native call or borrowed-pointer read. Counts are explicitly non-atomic.
  The finite diagnostic sink accepts the closed terminal union without adding
  arbitrary data or enlarging its record/byte limits.
- `windows_socket_worker.py:1309`: early publication validates schema,
  generation, ACLs, directory/file identities, opened descriptor identity,
  complete bounded write and original readback before native cleanup. Publisher
  failure does not change cleanup/custody. `windows_socket.py:1404` projects
  only the retained retired original result. Missing evidence remains unknown.
- `windows_socket.py:495`: exact fields/types and existing result bounds remain
  enforced. The capture-only stage exception requires validated mux terminal
  metadata and stage `live`. The early result does not claim COMPLETE, native
  cleanup, quiescence or reap. Removing the discriminator restores rejection
  of the same legacy-invalid result.

## QUALITY evidence and verification limits

Fresh reviewer execution, exit 0: **12 passed, 14 deselected in 0.51s**.

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py -q --tb=short -k 'blocked_original_pump or finished_target_during_unreturned or receipt_cannot_adopt or busy_refresh_barrier or active_cut_handoff or original_terminal_is_written or cold_callback_terminal or failed_join'
```

These controls cover blocked original pump, target completion before start
returns, four substituted thread/Event aliases, interrupted join, occupied
refresh barrier, active/fresh-cut handoff, foreign callback rejection, and
original early publication while native cleanup is blocked, including replaced
file rejection. Tests use inert native/grant/child ports and temporary result
files; the ACL port in early-publication tests is substituted. Source review
also followed the existing parent pump, RPC, credit and custodian paths.

The author's 321 passed/1 deselected provider gate, 21 passed Windows selection,
mypy/Ruff and causal RED history are **reported author evidence**, not rerun
here. The one omitted baseline ownership expectation remains documented in
the linked author/triage reports; this review makes no whole-suite green claim.
No new tests, source edits, private input, database, hardware, browser, native
DLL operation, commit or source-envelope mutation was performed.

Remaining priority is the bounded actual replay: verify sustained parked
delivery, foreground/refresh latency and terminal/cold-read evidence using the
new combined closure. Cooperative timing cannot preempt a blocked existing
native/authority operation; such an operation must continue to prevent cleanup
settlement. Parent termination can beat the optional early write. Actual
twelve-camera throughput, the historical initiating callback failure and the
distinct cold SUB failure remain open product acceptance questions.

## Frozen hashes

| Path | SHA256 |
| --- | --- |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py | `6a5bec30a88f993021a29bb83aacb132247a7958b33822281ffb68c6b37ffd95` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py | `69356a812a5b1020d04ae48e5fbae49c00723b33b70900a9f66bef6288ba182c` |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py | `d5c581950c4f6f1132506e48d6331fe845f66be6f6ad4235f06a98c438de159b` |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py | `ea54c3265ec3c5d67adcc637e28b1d7b849d922981f3952a0a93e42cfe2e2153` |
| tests/contract/test_shared_ingress_consumer.py | `b15d7486b4e94f3586568dd0b16234780c8f2f1143908f480d3a2ed62a736364` |
| tests/contract/test_mux_terminal_result.py | `7034a590e495345d24f69dcd1714dc80d6f1f01f1af9180618e09f70c5aaa901` |
| docs/analysis/2026-10-10-shared-ingress-repair.md | `37b5a5cb54b28d2719e17f812a5c3c67eafddc7df4f2626fbd2248c4076af576` |

Update log: 2026-10-10 independent frozen R0 SPEC/QUALITY review saved; scoped
source approval only, actual acceptance pending.
