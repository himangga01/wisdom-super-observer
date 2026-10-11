# R198 retained shared ingress repair

Analysis date: 2026-10-10, Asia/Seoul. Author source baseline: immutable tree
`b829c5d5aaba3072f88df56b6fa3c47b4b817caa`, implementation worktree
`codex/superlive-web-service`, HEAD `6436748f37c799fd14ce03e1d72c86c79eda6b0f`
plus pre-existing uncommitted Stage1/2 and R193–R197 changes. No native runtime
was active at assignment. This repair owns four bridge files and two new tests;
other source, historical evidence and receipts are preserved.

Read this report with [parked ingress diagnosis](2026-10-10-parked-ingress-causal-diagnosis.md),
[service analysis](../service-analysis.md), the approved Stage2 spec/plan and
the R198 execution brief. Read before reuse and refresh after source changes or
actual acceptance. Root owns canonical AGENTS/service/ledger reconciliation and
fresh immutable native/source approvals.

## Purpose, architecture and implemented behavior

The service retains one original recorder epoch for shared SUB slots while
viewers can stop, switch to dedicated MAIN, or return with a fresh ingress cut.
The existing codec/parent pump validates FIFO provenance and refunds parked
frame credits. Previously no shared reader consumed callback traffic while all
SUB cuts were parked. The inert real-source control confirms the callback's
257th queued chunk fails; it does not establish the historical recorder cause.

`OriginalRecorderMaster` now retains one non-daemon ingress thread after shared
bootstrap. A frozen `_IngressConsumer` binds the exact thread, stop/completion/
start-outcome Events, parent, owner, custodian, IO mutex and epoch. The consumer
enters existing invocation/authority/IO barriers, skips occupied IO without
denial, and pumps only when an original slot has opened and all cuts are absent.
Each slice has at most 16 pump calls, a 50ms loop clip, a 250ms operation clip
further bounded by transport/parent expiry, and a 10ms idle wait. An individual
entered pump can use its clipped operation budget; timing is cooperative.
Active readers and foreground slot startup keep their existing consumption.
No raw buffer clear, synthetic cut/grant, queue increase or TTL change was added.

Close signals the retained original Event before native retirement. An entered
operation or unresolved thread start remains incomplete. Both `close` and
`issued_receipt` require positive original target completion, a completed start
attempt, original join and non-alive observation. Alias substitutions are
rejected before and after join. Existing original receipts and credit release
continue through the original custodian; they cannot bypass this consumer gate.

## Exact bounded terminal diagnostics

The native worker retains its exact drive `SafeResult` and original
`CallbackOwner` before callback installation. Serve terminal and cold failure
cleanup sample only seven primitive fields: epoch-bound, failed, closed, queued
chunks, queued bytes, ingress ordinal and capacity. Snapshotting adds no callback
lock, native call, borrowed-pointer read or callback I/O. FIFO counts are a
non-atomic sample and have no terminal-reason attribution.

One `_OriginalMuxTerminalPublisher` writes the same original private result
before native cleanup. It enforces the existing ACL, directory/file identities,
generation, closed result schema and 16KiB cap, validates the opened fd, checks
the full byte count, truncates/flushes and verifies original-file readback.
Publication failure is isolated from native cleanup/outcome/custody. The normal
final writer can update the same inode, now with bounded full write and truncate.
An early result records actual stage `live`; it claims neither native cleanup,
quiescence nor reap. The strict result parser allows that stage only with a
validated mux-terminal discriminator; the legacy capture-only restriction and
all existing bounds/type/field guards remain enforced.

After confirmed original retirement, master close attempts exactly one result
projection outside custody/state locks. `WindowsSocketProvider.original_mux_terminal`
requires the exact retained result owner/custodian, directory/file IDs and result
generation. The closed `native_mux_terminal` version-1 record uses the existing
`NativeFirstKeySink` and runtime publisher with unchanged 128-record/64KiB limits.
No SDK result is chosen by recency and no public diagnostics path was added.

The parent's immediate original kill can still beat terminal publication. A
missing, partial, replaced or malformed result yields no record. This is
unmeasured evidence, never proof that callback failure was absent or cleanup
completed. Optional diagnostic queue drops retain their existing meaning.

## Executed verification

- Causal RED: original callback without consumer fails at queued chunk 257;
  six new consumer requirements initially fail with the missing production
  consumer, without teardown errors. READY/no-open-slot, four substituted
  thread/Event aliases, same-generation foreign callback, original projection,
  finite sink union and missing early publisher each had observed failure before
  their corresponding corrections. The blocked-cleanup early write also exposed
  and verified the narrow real mux result-schema correction.
- Final focused provider/IPC/pressure/ownership/callback/registry/BUSY/R197/
  diagnostics/consumer/terminal/handoff gate: **321 passed, 1 deselected**, 40.36s,
  exit 0. It exercises 1,024 parked frames with zero parked frame credits,
  pre-cut partial rejection/fresh key handoff, busy refresh serialization,
  late/failed/unreturned start, failed join, blocked pump, original alias custody,
  original result/file replacement, finite diagnostics and blocked native cleanup.
- The deselected `test_current_cut_after_job_admission_releases_no_private_input`
  was executed in an earlier focused gate and failed because it expects
  `owner.confirmed=False`. This exact pre-existing expectation is documented in
  [broad test triage](2026-10-10-broad-test-failure-triage.md). It was not changed.
- Windows callback/mux selection: **21 passed, 330 deselected**, exit 0.
- Four-source mypy with `--follow-imports=silent`: success. Scoped Ruff check
  passes; format check reports six files formatted. `git diff --check` passes
  with existing repository LF/CRLF notices.

Commands used, from the implementation worktree:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py tests/contract/test_local_live_mux_provider.py tests/contract/test_local_live_mux_ipc.py tests/contract/test_local_live_mux_pressure.py tests/contract/test_local_mux_ownership.py tests/contract/test_local_mux_callback.py tests/contract/test_local_owner_registry.py tests/contract/test_local_login_busy.py tests/contract/test_mux_replacement_transport_retirement.py tests/contract/test_native_first_key_debug.py tests/contract/test_final_mux_handoff_refresh.py -q --tb=short -k 'not current_cut_after_job_admission_releases_no_private_input'
.venv/Scripts/python.exe -B -m pytest tests/contract/test_windows_socket.py -q --tb=short -k 'callback or mux'
.venv/Scripts/mypy.exe services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py --follow-imports=silent
.venv/Scripts/ruff.exe check services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py
.venv/Scripts/ruff.exe format --check services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py tests/contract/test_shared_ingress_consumer.py tests/contract/test_mux_terminal_result.py
git diff --check
```

## Frozen author hashes

| Touched file | SHA256 |
| --- | --- |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py | `6a5bec30a88f993021a29bb83aacb132247a7958b33822281ffb68c6b37ffd95` |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_diagnostics.py | `69356a812a5b1020d04ae48e5fbae49c00723b33b70900a9f66bef6288ba182c` |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py | `d5c581950c4f6f1132506e48d6331fe845f66be6f6ad4235f06a98c438de159b` |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py | `ea54c3265ec3c5d67adcc637e28b1d7b849d922981f3952a0a93e42cfe2e2153` |
| tests/contract/test_shared_ingress_consumer.py | `b15d7486b4e94f3586568dd0b16234780c8f2f1143908f480d3a2ed62a736364` |
| tests/contract/test_mux_terminal_result.py | `7034a590e495345d24f69dcd1714dc80d6f1f01f1af9180618e09f70c5aaa901` |

## Limits, priorities and open questions

This is author source verification, pending independent review and fresh native
approval. Tests use real callback/codec/pump and Python threads with inert child,
native and grant ports; existing ownership cases may launch their own inert
children. Early publication uses real temporary files with a substituted ACL
port. No private input, device/DB/browser/live runtime, DLL load, twelve-camera
acceptance, commit or policy/receipt modification was performed.

Priority: review this exact source, then Root's bounded actual A/B replay should
capture terminal and cold-read evidence. Does the recorder retain SUB delivery
after park, what original condition terminates the actual callback, and does this
budget keep up with real twelve-camera rates? Does the distinct cold SUB failure
come from read budget, authority, cut, codec or native terminal state? These
remain open. This repair does not claim all historical failures are overflow or
that cold SUB startup/MAIN focus/browser acceptance is complete.

Update log: 2026-10-10 R198 author implementation and focused gates recorded.
