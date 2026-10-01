# TVT bridge decision — evidence gate

Checked 2026-09-27 for the SuperLive Plus 1.18.1 APK (SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`). This is a feasibility decision, not a bridge implementation. No vendor contact, login, device command, packet capture, payment, or runtime pilot occurred in this slice. **G-P1 is BLOCKED for every remote family.**

## Active development decision — 2026-10-02

The user confirmed that no separate vendor SDK/API documentation exists and directed implementation from the analyzed APK. Development uses the [APK-derived adapter contracts](apk-derived-adapter-contracts.md): account HTTP route C and device/media route B through the packaged Android `NetClientProtocal` JNI helper. This supersedes the historical acquisition order and `CONTRACT_CAPTURED` prerequisite for development. `SOURCE_DERIVED` is a prose evidence description, not a new machine-readable enum. The 199-operation/77-case baseline and existing runtime statuses remain unchanged; current G-P1 remote families remain BLOCKED and `MATCHED` remains 0.

| Family | Current development route | Pending acceptance |
| --- | --- | --- |
| Account/login/profile/renewal/logout | C: native `/user/*` POST JSON, exact envelope types and conditional fields, independent password/UUID proofs, region/DC state and separate account/P2P tokens | Scoped success/error/timeout, expiry/logout and response/readback comparison; unfinished register/recovery and signing branches need targeted APK decode |
| Device/media/playback/Talk | B: chosen packaged ABI, exact class/declarations/callbacks, positive handle/task gating, generation-scoped lifecycle and bounded 44/24-byte post-native parser | Android load/classloader/lifecycle/hosting and binary-use terms, actual transport/frames/audio/crypto, task close/restart/capacity, playback and Talk |
| Sharing/control/event/cloud/VAS/Tyco/H5 | Develop from each reviewed APK call/serializer boundary; retain separate identities and explicit undecoded branches | Per-operation captured fixtures, permitted deployment, definitive writes/readback and browser outcomes; no family-wide inferred pass |

Implement Python scoped ports and fake-worker/source parser slices now. Account HTTP can run in the Python service; Android JNI runs in a managed Android helper, never as a Linux Python extension. Generic RTSP cannot replace required TVT account/P2P/media behavior. Opaque NAT/N9000/control/wire branches are targeted decode work items, not guessed constants or a vendor-contact detour. Exact hosting, licensing, library load/lifecycle and runtime tests remain acceptance work.

Independent W02 contract/adapter development proceeds while T05A full14 executes. Integration acceptance still requires the foundation: one nested `{error:{code,message,details?},request_id}` serializer; delegated T04 capability checks at issue/redeem/use with the protected real actor and legacy OWNER behavior; fixed domain job kinds and checked enqueue/read/cancel/claim/use; actor-key uniqueness and server-derived cross-actor business holds preserving durable `UNKNOWN_OUTCOME`; provenance integrity without byte grants and separately reviewed future TVT admission/ingress through every existing AssetStore route. Development does not close these foundation/security/runtime gates.

## Historical decision record — 2026-09-27

The sections below preserve the original dated feasibility findings, candidate table and optional vendor leads. Their “None” selections, acquisition ordering and prohibition on W04 consumption before capture describe the 2026-09-27 runtime-evidence boundary; the active development decision above supersedes those development prerequisites. The historical absence of runtime proof remains valid.

## What the available evidence establishes

The [static protocol feasibility review](apk-audit/11-protocol-feasibility.md) identifies the APK's Java-to-JNI request router, separate device/media native path, cloud path, and Tyco REST path. Its `/sdk/*` names are in-process dispatch identifiers, not a documented web API. The [public-source review](apk-audit/00-tvtopensdk-web-check.md) found no confirmed externally redistributable copy of this exact `TVTOpenSDK`. Five packaged `TVTOpenSDK` NAT methods return zero; 31 native signatures lack conventional matching exports in the audited ABIs. The separate native device path may work, but static symbols do not prove its wire protocol or server deployment rights.

Official TVT material, checked 2026-09-27, distinguishes a **device SDK** from the APK-specific account wrapper. [TVT's support page](https://cn.tvt.net.cn/contactSale/index44.html) says to contact sales for a device SDK. [A TVT camera product page](https://en.tvt.net.cn/products/1840.html) lists TVT SDK, ONVIF and RTSP support for that device, and [a TVT management-server page](https://en.tvt.net.cn/products/1061.html) lists private protocol, SDK, ONVIF and RTSP device access. These product capabilities do not establish SuperLive account, P2P, cloud, Talk, alarm, payment or Tyco compatibility, nor permission to host or redistribute the APK libraries. **Inference:** an official device-access SDK may cover a subset of operations, but its identity and scope must be confirmed with TVT.

## Family decision

| Family and seed cases | A: official web/server API or SDK | B: TVT Android SDK in managed gateway | C: independent protocol | Current selection / G-P1 |
| --- | --- | --- | --- | --- |
| TVT account/provider, P02/P16 plus account gates | Ask for exact API, token roles, regions and code exchange; no package or responses received | No headless lifecycle or reuse rights established | No auth wire trace or crypto/session schema | **None / BLOCKED** |
| Device, share and controls, P03/P05/P06/P10–P13/P17/P21 | Device SDK is advertised only at product level; account/share scope unknown | No service capacity, callback or restart pilot | No per-command readback and uncertain-write trace | **None / BLOCKED** |
| Media and Talk, P03–P05/P07/P12 | Codec, LAN/P2P/relay, playback and duplex Talk coverage unknown | Packaged Android JNI is not licensed or headless proven | No stream framing, keys, audio direction or cleanup bound | **None / BLOCKED** |
| Alarm and push, P12/P14/P15 | Socket/push ingress, replay, dedupe and rights unknown | No app-closed/background pilot | No authenticated event schema or browser equivalence | **None / BLOCKED** |
| Cloud, VAS and payment, P18 | OSS, entitlement and merchant APIs/rights unknown | Native cloud library does not prove checkout or server use | No object crypto or authoritative order outcome trace | **None / BLOCKED** |
| Tyco and dynamic web, P21–P24 | Tyco/H5 are distinct services; obtain their own terms and APIs | Embedding a WebView is not an action contract | Delivered H5 commands, redirects and Tyco task schemas uncaptured | **None / BLOCKED** |

The six rows follow the adapter order in §3.2 of the [implementation plan](../superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md). An A/B/C route becomes selected **per operation and family** only after written rights, deployed OS/ABI, replayable success/error/timeout fixtures and an independent reviewer are recorded. A candidate rejected for an unsupported mode, unknown redistribution terms, or an unknowable timed-out write stays listed in the operation ledger while the next candidate is investigated. Local-only case operations are marked `NOT_APPLICABLE` to an upstream bridge; their web parity still needs comparison.

## Static declaration reconciliation

The [request-route](tvt-request-route-inventory.csv) and [JNI declaration](tvt-jni-declaration-inventory.csv) inventories account for all 281 request classes and 299 native declarations listed in the static audit. They link only evidence-backed candidate operations; every other declaration has an explicit unknown, unreferenced or stub disposition. These dispositions do not establish runtime behavior or pass G-P1.

## Frozen seed integrity

The [frozen 199-operation baseline](tvt-frozen-operation-baseline.csv) and its pinned canonical digest prevent a seed operation from disappearing or being renamed when the handoff and coverage CSV are changed together. The [runtime contract](tvt-runtime-contracts.md) defines append-only discovery and versioned correction. A static candidate with no direct route/JNI mapping remains a visible work item; it is not silently removed from G-P1 coverage.

## Deployment and capacity decision

There is no approved SDK binary, version, image digest, OS/ABI, license, service capacity, concurrency limit, restart behavior or maximum orphan-session duration. Linux server use of the Android `.so` files is unsupported by this evidence. The bridge interface can be designed around operation and media leases, but W04 cannot consume a row until its status is `CONTRACT_CAPTURED`. Do not route a TVT account case through generic RTSP, equate a device SDK with `TVTOpenSDK`, or report 100% parity from this decision.

The machine-readable seed is [tvt-operation-contracts.yaml](tvt-operation-contracts.yaml) with [adapter coverage](tvt-adapter-coverage.csv). It contains 77 cases and 199 **candidate** operation boundaries, including six local-only boundaries. Candidate names are work-item labels, not observed wire method names. See [runtime contracts](tvt-runtime-contracts.md) for promotion criteria and [vendor questions](tvt-vendor-questions.md) for missing primary evidence.
