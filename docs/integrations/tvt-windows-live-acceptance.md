# Windows native live acceptance

Analysis and execution date: **2026-10-04, Asia/Seoul**. The bounded native objective is achieved: both supplied stores returned actual channel metadata and four usable decoded camera frames. **This is not continuous browser playback, current SaaS authority or full APK parity. MATCHED=0; release_ready=false.**

Read-before authority: shared analysis policy, project AGENTS, [service analysis](../service-analysis.md), and the existing provider, inventory, raw-live and decoder guides. HEAD was freshly checked as `36fc954e4754d69721596e190c35f9cf14de3e4c`; executable published baseline remains `756946ca73cff31d7ebb23141873088b470a96b4`. Work used the existing `codex/superlive-web-service` Windows worktree with unpublished native and other agents' changes. No clean-tree or published-CI acceptance is inferred. Root owns shared report/AGENTS/publication updates.

## Implemented path and accepted source

The private path is supplied encrypted local credentials → one original Windows process/Job/TVT connection → accepted login and same-session BASIC/channel-detail/USER reads → one selected actual channel and one stream1 open → four source-validated compressed frames beginning at a keyframe → source close Send and original process retirement → separate owned Windows decoder → private RGB/PNG output.

Both actual USER responses contain a genuinely empty authGroupId element. The source skips its permission-group query in that branch. Metadata branch completion therefore takes three reads; permissions_complete and inventory_complete remain false while serial match, complete roster, USER observation and metadata_branch_complete are true. No group, admin privilege or service grant is synthesized. Group-present integration is deliberately restricted to observed selected-GUID @lp; admin-only group shortcuts are denied.

Actual media uses route0 without a received task GUID. Admission is limited to an explicitly opted-in fresh original connection with its first and only stream1 task, accepted matching open ACK, actual channel/stream and current original-owner checks. The callback owner has a non-resetting first-live claim. A new codec on an old/reused connection does not meet this contract. Route1 remains unsupported; ordinary route2 retains exact received-task checking. Source bytes are not rewritten. Local task identity and absent wire-task provenance are recorded separately.

Exact accepted receipts in the implementation-plan SDD directory:

| Boundary | Receipt SHA256 |
| --- | --- |
| Inventory XML Fix3/Fix1 | `2b8b158ef441ec374dc237c21157562c4fe02ce8fdcd76dadfe78cf8df686e9e` |
| Raw-live taskless first-task qualified source | `8039ff625abdb21c34214014af129286ee8becc3ed102986920b7289a1ae0b75` |
| Current provider source | `187373903dd57829fec51e46b9715c81b312ec29a449f1685bf3b87ac5f65c3e` |
| Windows decoder Fix1 | `6f3b4950560689cf3b4b23c4f6957a392b5ddad392986036560d91c7614f15e3` |
| Windows runtime R90 override | `77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d` |

Current provider review is C0/I0/M0; current raw-live source has zero blocking/new findings and retains its historical I1 command-custody qualification. Original packets and failed/intermediate outcomes remain intact. The final provider rebind inspected ten focused cases and static checks; its Root closure checked61 changed/current/dependency files and61 private textual scans. Historical suites and hundreds of unchanged artifacts were not replayed for this rebind.

## Actual two-store evidence

Times below are UTC on2026-10-03; add nine hours for2026-10-04 KST. All listed fresh capture attempts ended with failure=none, one open attempt/accepted ACK, one close Send, confirmed original process retirement and four captured frames. No phone, audio, PTZ, configuration or password guessing was used.

| Evidence | Store1 | Store2 |
| --- | --- | --- |
| Original generation | `40428dca928f44e18bcac71e4afdc5a2` | `d18d16163f1b44dd8acd7a4cf7987342` |
| Actual complete roster |8 channels|4 channels|
| Selected inventory position |2|1|
| Capture time |19:51:02–19:51:04|19:50:52–19:50:55|
| Metadata Sends/replies |3/3|3/3|
| Compressed frames/bytes |4 /163216|4 /101911|
| Live received bytes |164048|102711|
| Codec and dimensions |HEVC1280×1936|HEVC1280×1936|
| Decode time |19:57:19–19:57:20|19:57:27–19:57:28|
| Decoded frames |4|4|
| Per-input batches and flush |1,1,1,1,0|1,1,1,1,0|
| Separate decoder exit/reap |0 /confirmed|0 /confirmed|

Each RGB frame is7434240 bytes. Exact source device timestamp and ordinal mappings matched all eight fresh decoded pictures. Both fresh first PNGs were visually inspected: clear real store interiors, shelves/freezers and source camera overlays. This establishes usable camera images, not only nonempty buffers or ACKs. Images, source identities, raw wire data and credentials remain outside Git in protected private generation folders.

Earlier qualified outcomes are preserved: Store1 position1 accepted the live open but sent only ACK/heartbeats before the60-second deadline; it is not labeled offline or rejected. Store2's first attempt stopped at the previous route0 policy after receiving actual media. Its same archive was replayed with zero new Sends and independently decoded into one usable1280×1936 frame before the fresh four-frame attempts. That earlier live attempt remains unsupported; its later offline decode does not rewrite it as successful live capture.

## Framing, clocks and resource ownership

For each fresh payload, Root checked the accepted capture/parent receipt, private file identity/hash/ACL, original channel and exact raw header/body/extension/payload/alignment lengths. The HEVC sequence is VPS/SPS/PPS followed by one IDR VCL in the first source frame; each following frame contains one TRAIL_R VCL. Every picture begins with an Annex B start code and one first-slice marker; layer/header fields agree with the supported single-picture source-delimited branch. No invented extradata, payload rewrite or arrival-order timestamp was used.

Private framing-proof.json files bind every payload and metadata hash. The selected decoder timestamp is the packet's device_timestamp in microseconds, preserving the exact source conversion and ordinal. The four timestamps are distinct; observed intervals are approximately99–109ms. Device, ECMS and envelope raw clocks are retained separately. **APK NewPlayer internal PTS equivalence, synchronized device clocks and end-to-end latency are unverified.**

The decoder ran in its own original Job/process after the TVT process had retired, never inside the TVT Job1 or a native callback. All134 installed PyAV Python/native code files matched the pinned19.0.1 wheel SHA256 `906fc3db09288319a75ea23ffefb59961c7dbe0d1c074601507a89de7d8593d8`; FFmpeg9.0.2 is the preserved runtime. This current file comparison is not production dependency/distribution approval. Parent source checks, bounds, current capture-read checks and retirement completion precede success. Close Send is not a close ACK, and native callback quiescence remains unproved.

## Private inventory export and service boundary

A zero-Send replay of each same successful generation now preserves an explicit private historical observation in private-inventory-observation.json:8/4 actual channel GUID/raw/window/position/name mappings, same-original-session and serial-match facts, USER/group provenance, permission availability and confirmed parent process/Job/stream cleanup. No password, key, raw serial or login token is copied into that observation. These are historical facts with current_sql_authority=false and native_external_current_callback_enforced=false. They must not be published as current OWNER verification merely because the counts or files exist.

The current executable provider still returns diagnostic SafeResult and private captures. The next native M1 port must produce an immutable typed same-session inventory observation, synchronously ask the parent service's current SQL authority immediately before actual Sends and final publication, propagate cancellation to the exact original owner, honor one absolute service deadline and expose no credential/handle in its result. Static operator opt-ins and callback-generation checks alone do not implement that service contract.

The [local service integration design](tvt-local-service-integration.md) records separate TVT_DEVICE admission, safe inventory, worker-only configuration and default-unavailable behavior. Its M0 contracts/SQL/core/API work is a separate concurrent slice. No cloud USER token or TvtIdentity is fabricated. Native M1 wiring and real current OWNER verification remain unexecuted here.

Continuous live requires a separate credential-free owned session and typed bounded FramePipe, ongoing current actor/store/channel revalidation, cancellation/expiry/reconnect semantics, actual browser codec/signaling and UI delivery. The current60-second provider/four-frame and30-second decoder tasks are bounded diagnostics. No browser live player, multiview, audio, playback or recording acceptance follows from these pictures. Production runtime qualification, native pointer/quiescence and broader device/protocol variants remain open.

## Reproducible safe evidence and commands

Root-owned utilities are in `.superpowers/verification/windows-native-root/`:

- `run-provider-root.py --mode live --store store2 --channel-position 1` and the equivalent store1/position2 produced the two generation-specific safe result JSONs.
- `inspect-live-annexb-root.py` emitted structural NAL facts only. Private framing proofs additionally verified source envelope/channel/timestamp and exact file bindings.
- `decode-live-capture-root.py --store store1|store2` produced `decoded-live-store1-40428dca928f44e18bcac71e4afdc5a2-195720226623.json` and `decoded-live-store2-d18d16163f1b44dd8acd7a4cf7987342-195728785067.json`.
- `decode-archived-store2-first-frame-root.py` produced `offline-first-frame-store2-20261003T194642253336.json`, explicitly qualified as offline archival decode after an unsupported original attempt.

The wrappers were statically read by Root before native decoder execution; the final four-frame wrapper SHA256 is `564ea2875a8115f06e0711b7069b9a96a05b7b9b46508aca718dfd16ad7abb60`, and the single-frame wrapper is `d014344c2b4a9dcdd8c7cd4e610eec9fb6bd6b5c62d8ad99f21126898ba78d1d`. No broad test replays were used to substitute for device acceptance.

Update log:2026-10-04 — actual two-store same-session metadata, bounded fresh capture and eight fresh usable Windows-decoded frames; independent earlier archived first-frame proof; private historical roster export; current service and continuous-live limits retained.
