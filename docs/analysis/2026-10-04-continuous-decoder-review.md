# Independent continuous Windows decoder review

**Current scoped result: C0 / I0 / M0 after the targeted timeout correction.**
The initial minor finding below is retained as historical evidence.

Review date: **2026-10-04, Asia/Seoul**. Coordinator-supplied source baseline:
`211d1484aa16eb30f5d362758f149f98dec9dfdf`, branch
`codex/superlive-web-service`, active `superlive-web-service` worktree plus the
uncommitted decoder extension and parallel disjoint service work. No Git calls
or application source edits were performed by this reviewer.

Read before reuse and update after changes: [project instructions](../../AGENTS.md),
[canonical service report](../service-analysis.md),
[approved Phase 2 design](../integrations/tvt-local-service-integration.md),
and the dated **Explicit continuous mode** section of
[Windows decoder guide](../integrations/tvt-windows-decode.md). The shared Windows
analysis policy also applies. Historical bounded CCTV decoding does not establish
this new continuous decoder's device/browser acceptance.

## Scope, purpose and architecture

Reviewed only `packages/core/src/wso_core/tvt/windows_decode.py`,
`windows_decode_worker.py`, `tests/tvt_parity/test_windows_decode.py` and the
latest guide section. The intended extension removes diagnostic cumulative
quotas from authorized live decoding while retaining one exact original isolated
PyAV 19 worker, Windows Job, codec and private decode binding.

Implemented WDC2 is explicitly selected by `continuous=True`; WDC1 remains the
default with its original wire bytes and cumulative limits. WDC2 converts packet
and output lifetime quotas into per-packet/per-response limits and bounds the
unresolved PTS map. It renews a maximum five-second inactivity deadline on fresh
unexpired authority. The worker independently renews after complete bounded input.
`wait_closed` observes actual original resource retirement rather than treating
the bounded return from `close` as successful settlement.

## Findings: C0 / I0 / M1

### M1 — invalid huge integer timeout escapes the fixed decoder error

In `WindowsDecoder.wait_closed`, `math.isfinite(timeout)` runs outside the
method's `OverflowError` normalization. The API accepts `int | float`; an integer
too large for conversion (`10**400`) raises raw **OverflowError** rather than the
documented fixed `DecodeError` for an invalid timeout.

Executed without spawning any process:

```python
d = object.__new__(WindowsDecoder)
d._closed = True
d._retire_done = threading.Event()
d._retire_done.set()
d.wait_closed(10**400)  # OverflowError
```

Normalize numeric conversion/finite validation inside the fixed error boundary
and add this inert timeout regression. This minor exception-contract finding
does not demonstrate false settlement or authority bypass.

## Source conclusions and remaining integration risks

- Parent renewal checks literal-True exact binding authority and the old deadline
  while holding the deadline lock. An expired/closed owner cannot be renewed.
  The event wakes the original watchdog after renewal; watchdog expiry fences
  under the same lock before disposal. Invalid packets, scope substitution,
  revocation and later attempts after close cannot replace or revive the owner.
- Continuous input PTS and ordinals strictly increase. Both processes bound
  unresolved mappings by `max_packets` and remove entries when matching decoded
  frames resolve. The worker's historical timestamp set remains empty in WDC2;
  lifetime byte/frame counters are not accumulated. Sequence/ordinal retain
  fixed wire ranges and do not reset.
- Compressed packet bytes, RGB dimensions/picture bytes, response frame count,
  response RGB bytes and original Job memory remain bounded. Pixel/reference
  state also remains subject to codec pixel settings and process/Job limits.
  Per-response/per-packet caps win over looser configuration limits.
- Exact binding, sequence, dimensions, PTS/opaque tuple and ordinal are checked
  at both ends. Fresh authority is checked after exchange before publishing RGB.
  No source PTS is fabricated. Initial WDC2 deliberately rejects non-monotonic
  encoded-order PTS/B-frame fixtures; WDC1 retains the reordering/flush fixture.
- `wait_closed=True` requires the original retirement event after process reap,
  started feed/drain completion and joins, pipe closure and Job release. A timeout
  leaves the retained retirement owner/handles supervised; it does not report
  clean disposal. Caller/source integration must retain that decoder until true.
- This decoder assumes one caller thread serialized with live authority changes.
  Aggregate sessions, source queues, downstream backpressure, browser delivery,
  actual orphan safety and service shutdown coordination are separate owners.
  Five seconds is an implemented inactivity bound, not accepted CCTV safety or
  measured startup/encoding capacity. The guide retains earlier load-sensitive
  startup/deadline failures instead of hiding them.

Priority: correct M1, retain the original decoder until confirmed retirement,
then execute the authorized continuous CCTV/browser and orphan-cleanup gates.
Open product questions remain measured startup allowance, multiview memory/CPU
capacity and support for non-monotonic source PTS; none blocks this minor fix.

## Fresh execution and actual limits

Reviewer ran the complete scoped decoder selection with inert synthetic inputs:

```powershell
$env:WSO_WINDOWS_DECODE_NATIVE='1'
.venv/Scripts/python.exe -m pytest -q --confcutdir=tests/tvt_parity tests/tvt_parity/test_windows_decode.py --tb=short
```

**71 passed, zero skipped, 24.77 seconds.** This independently reruns real
isolated Windows PyAV 19 H264/HEVC execution, original Job/process/IO retirement,
WDC1 regression and the two continuous proofs: **260 640-by-544 frames per codec**,
exact PTS/ordinal mapping, one original decoder and **271,564,800 cumulative RGB
bytes per codec**, with one-frame response and four unresolved-map bounds.
The separate huge-timeout reproduction produced the M1 exception above.

Ruff/mypy passes are author-reported and were not rerun by this reviewer. No TVT
SDK, device, credentials, SQL, private capture, certificates or browser calls were
used. Synthetic proof lasts seconds and exceeds a deliberately short diagnostic
deadline; it is not a 60-plus-second CCTV soak, long-duration leak/performance
acceptance, browser render proof, full-project test pass or release readiness.
Root's actual 60-plus-second CCTV execution was still pending at handoff.

Update log: 2026-10-04 — independent scoped WDC2 review, fresh 71-case selected
Windows synthetic execution and inert huge-timeout reproduction; C0/I0/M1 before
correction. Separate core correction rereview remains in
[local media core review](2026-10-04-local-media-core-review.md).

### Minor correction closeout — 2026-10-04: C0 / I0 / M0

M1 is closed. Numeric type/finite/range validation now runs inside the same
`OverflowError`/`ValueError` normalization as the retirement event wait, so huge
integer timeouts produce the fixed `DecodeError`. The new inert regression also
confirms that valid zero/None waits still observe the original settlement event.
Reviewer read the changed handler/regression and ran only
`test_wait_closed_oversized_integer_timeout_is_fixed_error`:
**one passed, 71 deselected, 0.04 seconds**. The 71-case native synthetic run above
was not repeated for this numeric-validation-only correction. Actual CCTV/browser
acceptance and all stated verification limits remain separate.
