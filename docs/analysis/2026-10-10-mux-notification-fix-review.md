# R203 ordinary mux notification repair: independent review

2026-10-10, Asia/Seoul. **SPEC C0/I1/M0; QUALITY C0/I1/M0**, one shared
Important finding. **R0 is not approved.** Operational preparation identified
an isolated-import regression after the preliminary protocol review; this
reviewer independently reproduced it before final handoff. The 61 passing
protocol/diagnostic controls do not clear the native import boundary.

## Scope and evidence

Reviewed four-path delta from immutable tree
`5df75b9d4a9ced3aa2838d3ce63f9a2d8a3e89bd` to
`e288ed3b78cb5308b20d34eb4f141d154d547895`, against the implementation worktree
`codex/superlive-web-service`, Git HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`. The worktree already contained
uncommitted Stage1/2 and R193-R202 changes; the four reviewed paths are
untracked relative to that Git HEAD. All four current hashes match the frozen
manifest. No source or historical evidence was changed by this review.

Read before reuse with [author report](2026-10-10-mux-notification-fix.md),
[full-path control research](2026-10-10-mux-interleaved-control-packets.md),
[service report](../service-analysis.md), and [AGENTS](../../AGENTS.md).
Shared analysis policy and established Stage2 ownership/cut/credit requirements
apply. Refresh after source or actual acceptance; Root owns canonical handoff
updates. The service carries authenticated recorder media through retained
native originals and bounded shared codec/parent pipelines.

The Root-confirmed historical run6a366e9c records command2563/route0 at the
unsupported mux parse guard after LOW start/offer/PLAYING succeeded. Its full
ordinary header/body shape was not measured. The saved full-path research and
current source show that legacy `serve_live` intercepts exact ordinary
2561/2562/2563 through the authenticated N9000 stream, while mux previously
rejected them. This supports the narrow compatibility repair; it does not prove
the historical packet satisfies every newly checked field. This reviewer did
not reopen private runtime logs or execute hardware.

## SPEC and QUALITY assessment

### I1: shared validator import breaks the isolated codec boundary

`local_live_mux.py:42` imports the pure helper from the full `local_n9000`
module, whose lines19-20 import `cryptography`. With only `core/src` available,
`.venv/Scripts/python.exe -I -S -B -` now fails while importing
`wso_core.tvt.local_live_mux`, with `ModuleNotFoundError: No module named
'cryptography'`. The approved Stage2 plan Task1 explicitly requires wire types
to remain stdlib/pure-codec compatible with the native isolated bootstrap.
Installed-site-package pytest execution conceals this regression.

Operational author reported the failing gate; reviewer independently ran:

```python
import sys
sys.path.insert(0, 'packages/core/src')
from wso_core.tvt.local_live_mux import MultiplexLiveCodec
```

Root authorized extracting the unchanged constants and pure predicate into a
stdlib-only notification helper, with N9000 re-exporting its existing names
and mux importing that helper. R1 must verify exact predicate/constants
equivalence, the isolated import gate and affected wire controls. Do not
advance R0 into runtime approval. The checks below describe protocol findings
only and remain useful evidence for the narrow correction.

- `local_live_mux.py:590`: only exact commands2561/2562/2563 enter the new branch.
  The unchanged pure `local_n9000._is_startup_header` requires sequence0,
  route/flags0, encoding0 and exact body lengths92/40/36. Added checks require
  ordinary eight-byte outer framing, magic825307441, actual outer length,
  positive signed-short version1..32767 and declared-equals-actual body length.
  This matches the greeting-bound legacy profile. Bodies remain opaque; no
  recording/channel callback or permission effect is introduced.
- `local_live_mux.py:54,346,522`: the private enum cannot be confused with
  `None`, which continues to retain a blocked head. A validated ordinary control
  increments the existing packet counter, consumes its original spans and
  bytes, then continues. It emits no public ACK/frame and reserves no encoded
  media credit. Coalesced media still receives its original ingress span and
  one-item credit-mode handoff. Received/packet counter bounds remain active.
- The new branch does not change pending ACK state, slot activation, timestamp
  calibration, task identity, cuts, grants or timers. A notification cannot
  satisfy an open ACK or authorize a media slot. `_deliver` retains pending-slot
  checks; the existing original parent checks transport authority before and
  after codec work. Generation/cancel/deadline and media slot checks remain in
  their existing owners. Controls grant no authority of their own.
- Fragment assembly retains its existing bounded ownership. Completed fragment
  outer headers cannot satisfy the new eight-byte ordinary check, and the
  assembled path explicitly rejects the consumed enum. Unknown commands,
  action-prefixed variants and malformed recognized controls still fail.
  `UnsupportedMuxPacket` preserves R201 numeric rejection diagnostics.

## Fresh reviewer verification

Both commands exited0:

```powershell
.venv/Scripts/python.exe -B -m pytest tests/tvt_parity/test_mux_notifications.py tests/contract/test_mux_notification_ingress.py -q -p no:cacheprovider --tb=short
# 55 passed in 0.29s
.venv/Scripts/python.exe -B -m pytest tests/contract/test_mux_command_debug.py -q -p no:cacheprovider --tb=short -k 'real_unknown_packet_still_rejects or only_existing_parse_rejection'
# 6 passed, 8 deselected in 0.09s
```

The 55 cases cover three families and version boundaries, every byte split,
coalesced controls/media with denied then granted credit, pending ACK and slot
clock continuity, original ingress spans, 1000-control byte/packet accounting,
counter overflow, malformed/unknown/action-prefixed/fragmented rejection, and
actual inert retained callback/parent/consumer drain with zero media credit or
terminal diagnostic rows. The six existing controls verify typed numeric
rejection and earlier unrelated rejection behavior. Source inspection also
compared the legacy N9000 ordinary validator/framer and actual legacy worker
intercept, plus original parent authority/credit boundaries.

The author's 401 affected passes and static checks are retained author
evidence, not rerun here. The broad7816 gate remains RED; no whole-suite green
claim is made. No additional tests, runtime, private input, DB, browser, native
DLL operation, agent, commit or source-envelope mutation was performed.

Priority: correct I1 and review R1, then fresh native/source closure and
LOW/HIGH duration, stop/reconnect and original cleanup acceptance. Actual packet shape, five-minute stability,
twelve-camera capacity and APK parity remain execution questions. A packet
outside the supported strict shape must still reject and retain diagnostics.

## Frozen source hashes

| Path | SHA256 |
| --- | --- |
| packages/core/src/wso_core/tvt/local_live_mux.py | `c72745e274a8ece0ddb346f017885a4c063653e6220d9f3b150f474d58d83596` |
| tests/tvt_parity/test_mux_notifications.py | `707752917a3bbb3bf96041582fef29c7e6e7acf310209fdf5a6451ad9ebd4d62` |
| tests/contract/test_mux_notification_ingress.py | `63523afa3c021767d0fea7f6306422b40d39dfe80714e63cdaef839591a93ae0` |
| docs/analysis/2026-10-10-mux-notification-fix.md | `579744fda88f83c50cf573115517d1ac390b45ab58583460089ed7bfd6dcbbc0` |

Unchanged inspected validator dependency `local_n9000.py` SHA256:
`d53238cf2d6eda58995d1dc0c427ca28d226f7c44b730f85411d3c4b6bd509f4`.

Update log: 2026-10-10 preliminary protocol review passed61 targeted controls.
Before final handoff, operational isolated-import RED was independently
reproduced and I1 added. R0 approval withheld; correction and actual acceptance
remain pending.
