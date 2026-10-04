# Private N9000 channel and identity inventory

Analysis/implementation: 2026-10-03, Asia/Seoul. Root supplied executable baseline `756946ca73cff31d7ebb23141873088b470a96b4` and documentation HEAD `36fc954e4754d69721596e190c35f9cf14de3e4c`; Git was not used. Exact source APK: SuperLive Plus1.18.1/code20267, SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`. Implementation is `packages/core/src/wso_core/tvt/local_inventory.py`, extending the private [ordinary login codec](tvt-local-n9000-codec.md). **Source/synthetic verification only: MATCHED=0; release_ready=false.**

This pure codec parses login-tail serial/channel inventory and four fixed source-supported metadata reads. It neither connects a device nor grants channel control, authentication or live access. No full cw3 client, configuration/script startup, credential retrieval, provider/DLL/ADB/network/database/browser, PTZ, talk, audio, live-open or decoder is invoked.

## Binary login tail

`cw3.B8:456–494` calls C7/t7. `ServerNVMSHeader.w:2125–2153` is an eight-byte extension header; `.i:785–811` is the channel record. All short fields are signed little endian, exactly as `lk2.c` returns.

| Offset | Extension field |
| ---: | --- |
| 0 | int16 kind:1 channel list,2 returned serial |
| 2 | opaque int16 auxiliary field b, read as signed little endian and discarded for the proven known kind1/2 shapes; C7/t7 do not use it |
| 4 | int16 bytes per record c |
| 6 | int16 record count d |
| 8 | c×d bytes, checked against the complete remaining tail before any record loop |

Channel kind1 requires tested record width20. Its four signed bytes are channel type at0, window index at1, raw channel index at2, and unused fourth byte at3 (selected helper variant0). Bytes4–19 are exact GUID16 wire bytes: Data1 uint32/Data2–3 uint16 little endian plus eight unchanged Data4 bytes (`GUid.k/l`). Type0=analog,1=digital; source maps every other byte to recorder, while this helper deliberately supports tested type2=recorder and marks all other types unsupported. Zero GUIDs, duplicate GUID/window/raw indices and malformed lengths/counts reject. Unknown record-reserved fields, record widths or extension kinds produce explicit UNSUPPORTED_TAIL with withheld channel completeness; they cannot establish authority.

Auxiliary correction dated2026-10-04: the original helper's aux0-only completeness rule was conservative helper policy, not APK behavior. It is superseded for the existing proven kind1/channel width20 and kind2/serial count1 supported layouts. Full C7/t7/B8/w-reader and relevant consumer tracing shows the reader assigns signed16 b, C7/t7 consume only a/c/d, and B8 receives only the serial/list rather than this auxiliary. The exact source search finds no other ServerNVMSHeader.w consumer in the extracted APK. Auxiliary0,1,−32768 and32767 are inertly verified; no status/version/permission meaning is assigned or retained. Unknown kinds/shapes are still unsupported, never generally skipped or made complete. Root supplied safe structural facts (208 bytes, serial width32/count1 and8 analog width20 records, auxiliary1); the author reused only that structure with invented GUID/serial bytes. The archived real body was not read or replayed here.

The tail has no channel name. `B8` assigns `.iz0.v = i.b` and `.iz0.r = i.c`. Comparator `cw3.b:285–294` sorts **signed window index**, then `ca:6085–6138` assigns public positions starting1. Public position, window index, raw channel index and GUID are separate private fields. GUID joins are mandatory; a position is never a wire channel ID. Names remain None until verified channel-detail XML arrives, and no name is synthesized.

Serial kind2 is tested with count1 and width0–64. The selected C7 body reads the first c bytes; helper count/length checks prevent its unchecked traversal behavior. Source B8 applies Java trim (characters≤U+0020), skips exact mismatch checking for GlobalUnit.i0/j0 address forms, and otherwise compares a nonempty result. Here edge padding including NUL is removed like Java trim, strict UTF8 and ASCII alphanumeric1–63 are required for a nonblank result, and ASCII case is canonicalized to uppercase. Canonical case/length/termination rules are deliberate helper policy, not an APK validator claim. The admitted expected serial follows the same rule. A mismatch always rejects: the source address bypass is never copied. GlobalUnit.i0 uses URL-prefix removal, GlobalUnitItem.I port removal, IPv4/host patterns and ni1; j0 follows the IPv6 parser. Those source address forms cannot make an arbitrary mismatched serial the same device.

Missing or blank returned serial remains SERIAL_UNVERIFIED. A later BASIC reply with missing/blank SN also stays explicitly unverified and clears prior permission/user claims, rather than manufacturing a fresh match from expected input. Login reply acceptance, key extraction, proof verification, serial match, channel completeness, permission metadata and command authorization are separate facts.

## Stable private API

```python
session = InventorySession(
    login=retained_login_result,       # exact approved LoginResult, private
    generation=current_generation,
    expected_serial=admitted_serial,
    username=retained_username,
    security=negotiated_security,
    peer_version=negotiated_version,  # default3; actual source-supported6 tested
    read_authority=current_actor_metadata_authority, # callable(generation)->bool
)
evidence = session.inventory
wire = session.build_query(ReadQuery.BASIC, sequence=sequence, generation=generation)
evidence = session.accept_reply(exact_complete_ordinary_wire, generation=generation)
session.close()
```

The integrating private caller must bind the exact retained LoginResult, username, negotiated fields and generation from the same attempt. The approved LoginResult has no generation/sequence provenance field; this module cannot attest that initial provenance independently. Every new evidence record carries its retained generation, and every subsequent request/reply fences it strictly. There is one pending query; sequences cannot repeat within the generation and history is bounded. Stale generation/sequence, unrelated or unsolicited command/action, failed reply, invalid identity/schema or lost authority terminates the session. A terminal session cannot resume. Root's actual unsolicited command2563 is not a query reply and cannot populate this inventory.

Reply admission rechecks the same generation/current actor immediately after successful parsing and before replacing inventory, clearing the pending query or publishing ready state. Revocation, closure or a throwing supplier at that point terminalizes with fixed sanitized error, leaves the previous inventory object unchanged and returns no new evidence. This callback fence does not claim an atomic external-store transaction or arbitrary thread safety; the production owner must serialize revocation/publication and enforce current actor scope. Inspectable evidence after close is historical private data and cannot alone serve as current admission.

`read_authority` is an external current-actor/store/generation metadata-read admission, not an authority issued by parsing. It is checked on both request and reply. Only exact True admits; provider errors become fresh fixed diagnostics without supplier text in messages/cause/context. Proof or key flags alone never admit a request. Security0 metadata reads under an explicit external admission do not convert unverified server proof into live/channel authority. New private channel/user/permission/evidence records are immutable slots, redact repr, reject pickle and are not dataclasses; generic public DTO/JSON/dataclass conversion must not be introduced. The approved LoginResult and PrivateWire remain private original types. Close releases owned username/login/provider references; immutable Python byte/text erasure cannot be promised.

Evidence availability is IDENTITY_AVAILABLE, SERIAL_UNVERIFIED, CHANNELS_UNAVAILABLE or UNSUPPORTED_TAIL. It includes private serial, generation, channels, proof/key flags, user metadata, channel permission symbols and explicit system claims. `authorized` and `live` are always false. Parsed `@lp/@ptz/@spr/@ad`, admin labels, capability flags, empty metadata or asynchronous app success notifications are not command authority. Current service/store/channel authorization and runtime acceptance remain integrating gates.

## Four fixed read commands

`cw3.n7→o7→p7:7206–7374` builds command2331; logical IDs select app reply parsers and are not sent as the outer wire command. The security0 request body is exact f7 username64 + URL64, followed by UTF8 XML. `cw3.m7:6940–6965` writes the eight-byte gg0 plus16-byte wz0 headers: magic825307441, outer length16+body, client version3, flags0, encoding1, command2331, retained sequence and actual body length. No arbitrary URL, body or opcode is accepted.

| ReadQuery / URL | Verified source and logical routing | Exact content |
| --- | --- | --- |
| BASIC / queryBasicCfg | cw3.k9 logical4096 → b8 identity fields; excludes b8's subsequent d9 side effects | empty |
| CHANNELS / queryNodeList | cw3.E9 logical8193 → D8 channel detail; same GUID/name/index fields as Za | `<nodeType type="nodeType">chls</nodeType><requireField><name/><ip/><chlIndex/><chlType/><winIndex/><presetCount/><cruiseCount/></requireField>` |
| USER / doLogin | cw3.u9 logical4155 → e8 current userId/authGroupId/admin/system metadata | empty |
| PERMISSIONS / queryAuthGroup | cw3.i9 logical4147 → Q7 channel/system metadata | `<condition><authGroupId>RETAINED_GROUP</authGroupId></condition><requireField><chlAuth/><systemAuth/></requireField>` |

The group identifier comes only from this generation's accepted USER reply and is structurally checked before insertion. Caller-supplied arbitrary XML/group selection is unavailable. Non-BASIC reads require an actual serial match; permission reads additionally require complete channel inventory and an observed group. The `doLogin` name is the selected app's current-user metadata query after binary login: no password field or user edit is sent here. No full b8/d9/e9/f9 workflow runs. Those source startup methods contain configuration/script side effects, which this boundary excludes.

Security1/2 source `sb/rb` calls native AES128 string-by-key helpers with L4 and Base64 conversion; the exact key/cipher interpretation has not been independently recovered in this slice. These branches return UnsupportedBranch(encrypted_xml), rather than guessed cryptography. The currently root-observed legacy greeting6/security0 branch is implemented, but this author did not execute that device branch. Fragmented metadata replies are explicitly unsupported; the approved login-only Packet/N9000Stream reject non-login opcodes and remain unchanged. A bounded transport owner must collect one ordinary frame, skip heartbeats and dispatch unrelated messages separately.

Incoming metadata framing accepts the tested client version3 or the explicitly retained positive peer version (6 tested), rather than assuming every peer header is3. Flags0 and encoding0/1, exact command2331 reply/failure action, sequence and body/outer lengths are checked. XML Fix3 supersedes the earlier unsupported plain-body assumption: cw3.Z9 case2331 passes rb(body) through Java trim, finds the first `<?xml` declaration and discards the preceding opaque text before b9. Security0 helper performs the same bounded first-declaration selection without decoding or assigning a layout to discarded bytes, then Java-edge trim and strict UTF8 parsing of the selected XML. No fixed116 offset or guessed f7 reply structure is imposed. With no declaration marker, the whole trimmed body must itself be valid XML. A failure action uses checked oz0 width268/message-length≤246 and exposes only its uint32 code, discarding supplier message bytes.

## XML, identity and permissions

The received body byte bound precedes prefix selection, allocation and decoding; selected XML is strict UTF8. DTD, external/custom entities and malformed XML are rejected by explicit Expat handlers, without network/file resolution. Standard predefined/numeric escaped text, CDATA and comments are supported within the same decoded-text/node/depth/attribute/byte bounds. The earlier blanket ampersand/CDATA/comment rejection was helper policy rather than the source DOM behavior and is superseded. Unqualified XML names include catalog punctuation; namespace-qualified protocol names remain outside the tested contract.

Source b9 dispatches the retained logical query and wire sequence. It does not use response `cmdUrl`, `cmdId`, `clientType`, the older helper's invented response `url`, or `content@id` as device/user/group joins. These attributes are bounded and discarded; absent IDs are not invented and supplied opaque attrs do not confer authority. Root `types` and supplemental fields ignored by b8/D8/e8/Q7 remain structurally parsed/bounded but are not semantic errors or evidence. Duplicate **consumed** status/content/serial/user/group/permission fields are rejected as a deliberate single-reply service binding. BASIC retains SN only; BASIC child `<id>` is source-ignored and discarded, and no GUID mapping is established. Existing latest-BASIC missing/blank serial policy remains conservative unverified admission, not a claim that b8 clears an earlier source value.

Actual item@id GUIDs are source-established by D8/Q7 and remain required, nonzero/canonical, duplicate-checked and joined to the actual retained inventory. Source D8 does not read content total/count/id: those attrs are discarded rather than required or interpreted as page/roster counts; actual items remain bounded. Existing tail records supply missing channel type/window/raw index facts, and a partial detail response updates only known GUIDs without erasing the remaining actual tail records. If the tail omitted channels, explicit observed type/window/raw fields may supply private partial facts, but this selected E9/8193→D8 detail path never proves the absent complete roster. Catalog-only/empty or explicit partial detail stays CHANNELS_UNAVAILABLE, channels_complete=false, and cannot enable permission queries. Source missing-tail roster acquisition is the separate e8→l9/logical4097→O7→Za→ca path, which remains unimplemented here. No ignored count attrs or APK default indices/types are used to manufacture completeness. Names remain None until supplied. Unconsumed detail fields and supplier IP are discarded and never become targets. USER retains observed userId/authGroupId metadata; absent user identity stays unavailable, with no fabricated user/group. The permission request selects only the group observed in that current-generation USER reply. Q7 descendant chlAuth/systemAuth selectors are confined to admitted content, excluding sibling catalog definitions; actual item GUIDs, exact supported symbols and explicit system booleans remain checked. No container ID or ignored count attr replaces those joins.

`e8` current-user fields and Q7 symbols/system booleans are retained as private metadata. The source's admin / !Z3 bypass and Q7 presence-based global permission expansion are recorded evidence and intentionally never become grants. Unknown supported-symbol variants are typed unsupported. Missing system permission metadata leaves permissions_complete false; default_admin does not supply a missing group. Actual permission items are bounded; source-ignored count/container attrs are not interpreted as completeness proofs. `xa` application callbacks/timestamps do not establish live success here.

| Retained check or behavior | Source evidence / explicit service policy |
| --- | --- |
| First declaration selection, Java edge trim | Z9 case2331; rb/qa selects security0 raw bytes |
| Query dispatch and fixed four URLs | b9 pending W2 plus sequence; k9/E9/u9/i9, request p7/m7 |
| Prefix/root/content attrs/types/extra fields discarded | Z9 substring; b8/D8/e8/Q7 consume selected values, not those IDs/catalogs |
| One status/content and no duplicate consumed claims | Service binding narrows source descendant/multiple-field behavior for one pending reply |
| Serial canonical comparison | Actual C7/B8/b8 values plus documented stricter ASCII/mismatch/latest-missing policy |
| Actual item GUID/type/index/name fields | D8/i/ca; immutable tail GUID joins preserve real facts, no generated missing IDs |
| USER group selects permission request | e8→i9; Q7 joins actual permission item GUIDs, not content attrs |
| Item/text/byte/depth/node/attribute limits and known symbols | Explicit bounded service admission; source is not claimed to enforce these limits |
| Standard XML escapes versus DTD/external refusal | Source DOM text behavior; stricter explicit service parser safety |
| Pre/post current actor, generation, sequence and no grants | Existing private service contract, beyond APK UI callbacks/admin bypasses |

Default helper policy: tail/XML65512 bytes, channels256, extensions64, XML depth16/nodes2048, per-node text512 UTF8 bytes, query history16. Configurable hard ceilings: channels4096, extensions1024, depth64, nodes16384, text4096, history256; tail/XML never exceed65512. These are service admission bounds, not claims about original APK validation. Binary signed byte indices are preserved; XML indices are helper-bounded−128..65535. Malformed totals are checked before list construction or loops.

## Evidence and actual limits

The SDD packet is W04-local-channel-identity-report/owned.diff/source-manifest/artifact-manifest/READY and W04-local-channel-identity-evidence. Exact source reads were frozen before implementation. An inert JDK21 oracle compiled unchanged GUid/lk2/f7/gg0/wz0, extracted unchanged ServerNVMSHeader.w/i, and cw3.C7/t7 bodies with only standalone static modifiers plus inert dependencies. Its byte vectors and method/file hashes establish Java/Python agreement for tail parsing and all four request packets; self-contained tests retain those vectors. No full cw3 startup or vendor library ran. The causal generation-guard mutant admits a stale reply and fails the test; untouched/restored real code passes. All actual commands/captures and source hashes are recorded in the task report.

Outstanding for this auxiliary correction: independent root source review, separate parent-provider dependency rebind, current private actor/store binding, actual accepted inventory/metadata on both devices, encrypted/fragmented metadata if negotiated, actual permission joins and separately authorized live/media/frame acceptance. Root reported an archived success replay accepted login/key/serial under its reviewed login-field codec, with0 new sends after the original connection closed and proof_verified=false. Only safe structural facts were supplied to this author; no real body/identifiers/keys were read or replayed here. The earlier aux0 helper-policy failure was not an empty-device channel list. Root's separate Windows/native accomplishments and archived replay do not establish current-session metadata or frame acceptance. No actual execution may occur during parent dependency drift, and no SDK/phone request or presumed RTSP URL is part of this implementation.

Update log: 2026-10-03 — initial bounded source-derived inventory/plain metadata implementation and synthetic verification; MATCHED0/release_ready=false retained.

2026-10-03 Fix1 — final post-parse generation/actor fence; causal revocation/throw/closure and successful-scope checks; source-ignored BASIC child ID interpretation qualified. Original source/oracle packet retained; actual runtime acceptance still belongs to root.

2026-10-04 auxiliary Fix2 — discarded source-ignored signed16 auxiliary for proven known shapes; original aux0 helper policy retained as historical evidence; targeted inert/source-reader and guard-mutation verification. Parent provider remains pinned to the old inventory receipt until root approves and separately rebinds; no actual execution during dependency drift.

2026-10-04 XML Fix3 — corrected unsupported raw-XML/attribute/fieldset/count assumptions against full receive/dispatch/four-consumer source. All four prefixed source-shaped inert replies, escaped text and actual item joins verified; original packets/history retained. Root alone may replay the same saved BASIC without Send after source review, then separately approve the parent pin before another live query.

2026-10-04 XML Fix3 Fix1 — retained no-tail roster incompleteness through detail-only replies; known complete tail partial updates unchanged. Catalog/partial detail cannot open permission prerequisites; source roster path remains a separate unsupported contract. Original Fix3 review and frozen packet preserved.
