# c11 native-open 502 diagnosis

Analysis date:2026-10-06 Asia/Seoul. Scope: read-only diagnosis of the two native
502 starts in retired run `local-devices-6480f49c264246779e1fd209d4a1b72b`, and
their relationship to R139 EOF/result recovery. Observer failure diagnosis is
owned separately by the observation author. No implementation, SDK/device/RPC/
SQL/Chrome call, source mutation or test rerun occurred.

Root reports normal original Chrome/coordinator exit0 and reap, context removal,
unchanged source/private0, and201 issued leases all CLOSED/cleanup-confirmed.
The runtime resources record independently says apiSettled/workerSettled/
contextRemoved/sourceUnchanged=true. Observation terminal remains FAILED with
writer_settled=true and6850 failures; that is not a COMPLETE observation claim.

## Conclusion

**The two observed502s are pre-login native connection/greeting failures, not
lost login-BUSY responses.** One original connected successfully but its native
greeting read returned something other than the required64 bytes. The other
original reported connection status-1. Neither sent a login request or reached
inventory/channel selection/live-open. R139 deliberately recovers only exact
handshake/rejected/0x20000030, so it does not reclassify these outcomes as BUSY.

The underlying network, NAT, recorder or load reason is not retained by these
results. In particular, code0 here is the unchanged/default native_error field,
not proof of a successful native operation. These records do not establish an
exact recorder login ceiling or justify mapping general transport failures to
BUSY429.

## Baseline and source provenance checked

The service creates one original native login/session per tile, obtains its
same-session inventory/live authority, then hands that owner to source/decoder/
WebRTC. R139 acts only on failed, unhanded-off originals after actual retirement.
Source-before, source-after and current worktree raw hashes match exactly:

| Source | SHA256 |
| --- | --- |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py | 4f550bcd88078bd682ac464ff612f9ca86bca6a816e3660306d9ab9432e9795d |
| services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py | 37bac55b2239170503d87f0bcabc87e2953a1397460478932e4201e6c4bb6c0d |
| services/tvt-bridge/src/wso_tvt_bridge/local_live_provider.py | cd39cce9e3e55c28fa13468575198b483c859a6cd92f48e562a1d7973dea302c |

Reads were repeated with `login:false`, an explicit active-worktree directory
and absolute evidence paths after Root identified a shell-profile cwd risk.
Get-Location confirmed the active worktree. The persisted media snapshot is
schema_version2,90 attempts/90 sources/9 peers,0 observation failures,65055 bytes,
SHA256 `783ef4bc22654cb23caa7db38d3dc412081f55e552ba095471ac75bac3965495`.
The resources terminal's schema_version1 is a separate expected terminal schema.
Full runtime/import provenance and the later observer discrepancy remain the
other author's scope; this report does not substitute a source hash for an
independent runtime import trace.

## Exact bounded evidence

The saved browser `sizing-evidence/c11-summary-initial.json` covers356.080s:
9 start200,32 start429/BUSY,2 start502/PROTOCOL_INVALID,9 presented first frames.
The two failed substream API durations are6.011s and2.539s. The saved source
observation identifies attempts11 and15, both recorder ordinal1/channel ordinal6,
as OPEN_FAILED with executor_start/protocol_invalid, elapsed5937ms and2452ms,
and no native-return or media milestones.

Existing private result files were selected only in the c11 UTC interval
2026-10-05T19:47:22Z through21:58:12Z. This corresponds to2026-10-06 Asia/Seoul.
There are203 original result files: two inventory starts plus201 live attempts,
consistent with Root's issued count. Of192 failed-live parent summaries,190
preserve exact handshake/rejected/0x20000030 BUSY and two remain generic denied.
All192 parent summaries have reaped=true, all192 have a nonempty child result
and an exact matching child/parent generation. Nine successful handoffs do not
have that failed-start parent summary. No failed-child result is empty in this
selected interval.

Only whitelisted safe fields, booleans, counts, UTC creation times and SHA256s
were projected from the original private staging files. No generation, device/
session/channel/task GUID, credential, serial, media or raw log was exported.

| Field | First non-BUSY original | Second non-BUSY original |
| --- | --- | --- |
| Original result creation UTC | 19:50:56.194187 | 19:51:13.471186 |
| Child stage/failure | greeting / greeting | connect / connect |
| loaded / initialized | true / true | true / true |
| transport | true | false |
| connect_status | 1 | -1 |
| greeting_bytes | 0 | 0 |
| native_error | 0 | 0 |
| send_count / received_bytes | 0 / 0 | 0 / 0 |
| reply_accepted | false | false |
| inventory queries / live-open attempts | 0 / 0 | 0 / 0 |
| cleanup_attempted | true | true |
| Matching parent stage/failure/code | validated / denied /0 | validated / denied /0 |
| Matching parent reaped | true | true |
| Parent summary creation UTC | 19:51:02.064676 | 19:51:15.867101 |

Exact evidence hashes, allowing the originals to be located without publishing
their private generation paths:

- Greeting child: `6c2f930376e1c736984bb0863de4d09a2d3941641c0b49d1b88f42921e89c679`.
  Matching parent: `5219900d1059b00a26b69ccac21dedbe959403865cf69407f0101ab1c71bad82`.
- Connection child: `7a8f0cb7f78b1f097a21ee84c46445c5232367eb2ea883e685ae06b4df937e1c`.
  Matching parent: `fb7f97af4ddcfb0d768bc80cc42c2dde0db62f0d90f75940b42530d44625a4cd`.

The private child→parent generation match is exact. Mapping those two originals
to public-safe attempt11/15 uses the run interval, unique non-BUSY failure count,
ordering and matching durations; the observer intentionally exports no native
generation key. Do not claim a cryptographic public-ordinal→native-generation
binding that the schema does not contain.

## Current control flow and R139 ordering

`windows_socket_worker.py` drive sets connect_status from the native
connect_result result. The observed-1 takes its explicit failure branch before
transport acceptance. For the other original, status1 plus connected() accepts
transport; stage becomes greeting. The greeting call writes greeting_bytes=64
only after its return count equals64. A non64 return produces failure=greeting
with greeting_bytes still0. Its exact return count and the supplier's deeper
error reason are not stored. Both paths precede callback registration and the
login request, consistent with send_count0 and no inventory/live-open.

The worker still closes its private service pipe before writing result.json.
The parent pumps authority before its ordinary receipt read, so EOF can produce
protocol denial first and its coarse SafeResult becomes validated/denied.
R139 then performs a bounded exact-original result read after confirmed reap,
with retained directory/file identities, generation and existing parse_result.
Only `is_login_busy` may replace the coarse parent result. Greeting/connect
results fail that narrow predicate and the provider's existing generic failure
remains502. The inspected parent/child pairs and public502 outcomes match this
current path; no failed custody or missing child result is required to explain it.

The close-before-write ordering retains a structural race: if the parent stops
the child before its receipt is written, a post-reap read cannot recover missing
data. **That is not the measured cause of these two c11 failures:** their
nonempty child results contain explicit non-BUSY causes, and no failed-live
child result in the selected c11 interval is empty. No speculative ordering fix
or broadened BUSY mapping is warranted by these two cases alone.

## Priorities, open questions and limits

Preserve R139's exact login-BUSY guard. If Root chooses a follow-up change, the
useful distinction is a bounded original-native connect/greeting failure versus
a genuine protocol parser error. Its public status/diagnostic projection is a
product decision; it must not invent BUSY or silently add reconnects. An optional
fixed stage/status and bounded greeting-return classification could improve
future explanation, but no extra SDK call or observer change is implemented here.

The supplier reason for connect_status-1 or non64 greeting remains unknown.
Concurrent recorder/session load may be relevant context but is not established
as the cause. The evidence cannot establish full12-tile capacity, total long-hold
frame progression, or final complete observation. Root's resource cleanup and
the saved356s browser window remain separate from the FAILED observer terminal.

The observer failure question was handed to its assigned author with the exact
65055-byte saved snapshot, schema2 and borrowed writer's65536-byte bound. This
report makes no independent claim that all6850 increments have been attributed;
use that author's report and Root's canonical update for the completed finding.

2026-10-06 — Created from the shared policy/project instructions, prior c9/R139
analysis, exact current/before/after native hashes, safe c11 browser/source
projections and private same-original result pairs. No code or test changed.
