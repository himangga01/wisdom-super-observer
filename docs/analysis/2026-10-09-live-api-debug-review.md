# Bounded live API diagnostics source review

Review date: 2026-10-09 (Asia/Seoul). Verdict: **C0 / I0 / M0** for the
five frozen logging paths. No material correction is required in this scope.
This is source approval, not actual Windows ACL, current-run API file capture,
recorder playback, Chrome or twelve-camera acceptance.

## Scope, authority and baseline

Read before review: the shared `C:/Users/강지혜/.agents/analysis-policy.md`, this
worktree's `AGENTS.md`, latest `docs/service-analysis.md`, Stage 2 execution
ledger, established browser-runtime source review, and
`docs/analysis/2026-10-09-live-api-debug-logging.md`.
The author report SHA256 matched
`6354f422728a82f14e9e08f07363c07ff79753873883a92775ba393566a86e45`.
Reuse this review and the author report before changing the logger; refresh
affected findings and execution limits after source changes or actual capture.
The controller owns AGENTS/service bridges and runtime approvals.

Implementation authority:
`C:/Users/강지혜/.codex/worktrees/superlive-web-service/wisdom-super-observer`,
branch `codex/superlive-web-service`, actual Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with extensive retained Stage 1/2
working-tree changes and concurrent frontend work. Those unrelated changes were
not treated as this logger's diff or reopened for review. No source, index,
commit, private input, database, native worker or browser mutation was performed.

The controller's frozen BASE `5a15289d870f2295d307c5237c9c0194df887a2e` and
candidate `88ce5a413a607f154f97aef1438602534c1074c2` were independently checked
as Git **tree** objects; the candidate identifier is not the worktree's commit
HEAD. Their full difference contains concurrent work. The supplied scoped
`task-1912-review-r0.diff` isolates five paths, 691 insertions and 2 deletions;
its SHA256 matched
`3d7973b9aaca566541379fe74e6714582131c888557795796a365d6313fcd4cc`.
All five current raw file hashes matched `task-1912-frozen-hashes-r0.json`:

| Path | SHA256 |
| --- | --- |
| `services/api/src/wso_api/tvt/local_media_diagnostics.py` | `8580c141a1f22f7eb33e4af18fcc68effd9e98c0ddb4a1343b0c4ee544e1b125` |
| `services/api/src/wso_api/tvt/local_media.py` | `a9b630c0af10789692ab4d3f7b0dc8d70361a87487b17d0d3bec0cb677328103` |
| `scripts/test-local-devices/runtime.py` | `4706807aebe53f3199d89df717a5a3894c7c51b9ae801e4cbbe68513f68d2210` |
| `tests/tvt_parity/test_local_media_diagnostics.py` | `c4dde0531f5b8555aaed21d3124a0247f5cf5eeca0e4e453c4b2582ae0ffb028` |
| `tests/contract/test_local_media_debug_runtime.py` | `02bf0a9b6d84628afb109b25786fe413372900039a0893488854d201f7dd1c3e` |

## Purpose and implemented behavior

The local CCTV API authenticates and validates browser controls, authorizes a
tenant, issues application tickets and calls a separate worker. The supplied
actual diagnosis was a legacy connection-card start returning 422 before worker
startup because shared mode requires a wall and main mode also requires a focus
reference. The controller's historical inventory and 422 observations were read
as context; this reviewer did not execute them. The frontend repair has a
separate owner and review.

The logger adds one request-local structural result through `LocalMediaRoute`.
It identifies authentication, query, bounded body parsing, framework handler,
mode validation, worker selection, tenant, ticket, RPC and response phases.
Live-wall/focus and lease-read internals remain handler-level outcomes, as the
author report explicitly states. The optional runtime sink writes a fixed file
inside the current owned run's evidence directory. It introduces no new media
owner, worker, thread or cancellation path.

## Specification and quality assessment

- **Privacy:** `checked_record` requires exactly the closed field set, exact
  primitive types, fixed route/phase/stream/error enums and bounded numeric
  fields. Routes come from registered templates. Selector information is only
  stream enum and presence booleans. Known exception labels are fixed; unknown
  classes become `unexpected`. No request correlation identifier is emitted,
  so there is no correlation value to redact or hash. Request headers, bodies,
  identifiers, cookies, tokens, secrets, SDP, SQL, media, exception repr/text and
  stacks are excluded from the serialized record.
- **Bounds:** every accepted record is at most 1024 bytes. A lock serializes
  writes and reserves count/bytes before calling the writer, including failed
  attempts. The sink allows at most 128 attempts and 65536 attempted bytes.
  The runtime also checks actual file size before each append. Later omission
  after a cap is deliberate and cannot be read as absence of an HTTP request.
- **Failure isolation:** the route re-raises its original exception after
  optional finalization. Both finalization and the bounded writer catch
  `BaseException` from the sink. Existing authentication, query/body bounds,
  strict shared-mode validation, ticket issuance, worker dispatch, ownership
  response checks and original cancellation/custody behavior remain intact in
  the scoped diff. Ordinary optional setup errors disable the sink; invalid
  explicit flags remain configuration errors by design.
- **Runtime wiring:** production configuration initializes the sink to `None`.
  Explicit API debug `1` requires media mode and operates independently of
  observation; observation can also opt in. Invalid explicit debug values are
  rejected. `api_environment` adds the flag after the reviewed environment
  filter, and `api_process` configures the actual app before serving.
- **File custody:** the filename is fixed to `media-api-debug.jsonl` under
  `EVIDENCE_ROOT / folder.name`, using an absolute current owned context with
  the expected run name and parent. Setup checks directory link boundaries,
  calls the existing private-directory helper and creates exclusively. Appends
  reject links, a nonregular descriptor, a changed original device/inode and
  excess size before writing; descriptors close in `finally`. The reviewed
  borrowed helper's existing Windows ACL operations are reused. Native
  bootstrap/TRACE configuration and original process ownership are unchanged.

No critical, important or minor actionable defect was established in these
frozen changes. No unrelated whole-branch change is requested.

## Verification and causal evidence

Independent reviewer execution, exit 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/tvt_parity/test_local_media_diagnostics.py tests/contract/test_local_media_debug_runtime.py -q
```

Result: **13 passed in 0.63s**. These focused offline tests cover the actual
shared-mode 422 guard, RPC phase progress, authentication preservation under a
failed writer, query/body distinction, private field/string rejection,
concurrent/failing-attempt caps, successful response completion, unknown
exception omission, template classification, callback `KeyboardInterrupt`,
independent opt-in, app wiring and fixed temporary JSONL output.

Also executed read-only `Get-FileHash`, `git status --short`, `git rev-parse HEAD`,
`git cat-file -t` and bounded source/diff inspections. Every scoped hash and the
author-report hash matched the supplied freeze. The author reports initial
causal RED for missing mode/RPC/query evidence, independent wiring, wall
classification and callback `BaseException`, followed by **126 focused passing
tests**, scoped Ruff/format and strict mypy for the two API modules. Those larger
and static results are author evidence; this reviewer did not rerun or expand
them. The reviewer’s successful 13-test run does not independently recreate the
historical RED.

## Limits, priorities and open questions

The temporary file test substitutes the ACL callback. It is filesystem/wiring
evidence, not a real Windows private ACL receipt. No actual API/worker service,
PostgreSQL, SDK, recorder or Chrome was launched for this review. Real current-run
file capture, ACL enforcement, corrected card playback and normal original-owner
cleanup remain controller acceptance gates. This change does not reset,
extend or recreate an expired formal media observer; an observation-disabled
development run cannot establish twelve-camera acceptance.

Priority: preserve these frozen bytes, obtain the controller's new immutable
source envelope and launcher review, then verify actual bounded capture and
cleanup in the new owned development run. A full sink silently omits records,
and filesystem failure can leave evidence absent while original request results
remain authoritative. Broader production diagnostics, log rotation, correlation
and detailed mux-internal phases remain product questions outside this scope.

Update log: 2026-10-09 — fresh frozen five-path source review C0/I0/M0;
independent 13 focused offline tests passed; actual Windows/API/browser gates
remain open.
