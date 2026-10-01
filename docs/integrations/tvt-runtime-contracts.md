# TVT runtime contract and capture protocol

Date: 2026-09-27. Scope: W01's static **seed** for the SuperLive Plus 1.18.1 baseline, not a captured-runtime protocol. The 2026-10-02 correction below supplies separate source-derived development authority. The [77-case inventory](apk-audit/12-functional-parity-contracts.md) is the source of case IDs and static entry evidence; [§3.5 of the implementation plan](../superpowers/plans/2026-09-27-superlive-plus-web-parity-implementation-plan.md) defines the runtime handoff.

## APK-derived development authority — 2026-10-02

No separate vendor SDK/API documentation exists for this task. The user directed implementation from the analyzed APK; [APK-derived adapter contracts](apk-derived-adapter-contracts.md) supply account HTTP route C and packaged Android helper route B with explicit source identities, serializers, JNI/callback/parser fields and remaining decode work. W01 iterates targeted decode and later captures acceptance evidence; vendor questions are historical optional leads. Development does not wait for vendor acquisition or `CONTRACT_CAPTURED`.

`SOURCE_DERIVED` is a prose description of static development evidence only. It is not written into the existing machine-readable status enum. Keep the frozen 199 operation tuples, 77 cases, coverage/fixture fields and `runtime_proof=NO` unchanged until authentic runtime evidence satisfies promotion. An `UNMAPPED` or `BLOCKED` runtime row can have an implementation under development; record its decoded boundary and unresolved fields separately. Source-derived serializers, synthetic proof vectors, mocks, JNI exports and parser fixtures do not establish server acceptance, G-P1 PASS, MATCHED or release readiness.

The development handoff names the exact APK/ABI/library hash, Java path or native offset, decoded request/response/callback field types, adapter B/C route and explicit undecoded branches. Missing remote fields require targeted APK analysis rather than fabricated constants. The existing complete runtime envelope below remains required before captured-runtime promotion and runtime/production enablement. Android hosting/load/classloader/lifecycle, binary-use terms, real token/transport/frame behavior and operation success/error/readback remain later acceptance gates. Independent W02 contracts/adapters may proceed during T05A full14; foundation/runtime/storage/security acceptance still requires its actual gates.

## Machine-readable files

`tvt-operation-contracts.yaml` is serialized as JSON, a YAML 1.2 subset, so stdlib-only validation can read it. It has exactly one case object per P ID and one or more operation objects per case. `tvt-adapter-coverage.csv` mirrors those 199 operation IDs for review and assignment. Candidate operation labels describe **needed behavior**, not observed TVT routes. A compound case may need further splitting after a trace. The `static_reachability` value comes from the audit's C/D/L prefix; it is not a runtime `REACHABLE` verdict. `UNKNOWN` is deliberate, not an inferred default. `NOT_APPLICABLE` is currently used only for six local-only bridge boundaries identified in the static inventory; it does not mean the whole parity case passed.

Each operation records `case_id`, `matrix_id`, `source_apk_hash`, `entry_path`, `upstream_operation`, `transport_and_endpoint_class`, `request_schema`, `response_schema`, `error_map`, `callback_sequence`, `callback_terminal_condition`, `token_kind`, `deadline_and_retry_rule`, `success_condition`, `authoritative_readback`, `media_format`, `adapter_path`, `deployment_os_abi`, `rights_reference`, `fixture_digest`, `reviewer`, and `status`. It also carries `operation_id`, `candidate_operation`, `account_role`, `model_applicability`, `model_firmware`, `outcome_digest`, `capture_variants`, `reviewed_at` when promoted, and local-only evidence. The known APK hash comes from the [static baseline](apk-audit/00-coverage-baseline.md); it is not a runtime artifact hash.

## Frozen operation baseline and amendment

The [frozen operation baseline](tvt-frozen-operation-baseline.csv) independently pins the original 199 tuples of case ID, operation ID and candidate label from the 77-case static seed. Its canonical representation is the tuples sorted lexically, each encoded as UTF-8 case ID, tab, operation ID, tab, candidate label, newline. SHA-256 of those bytes is 971c1a5d0aa5d4b34b55b43c47d18ce6d45a01f8eea1c691154656ab77c8be93, pinned in the schema test. CI requires all 199 original tuples to remain in both the handoff and coverage CSV even if those two files are edited together. It also rejects a changed baseline manifest. Static route/JNI inventories directly link only 26 distinct seed operation IDs; the other 173 remain protected by this baseline while their upstream edges are unresolved.

Runtime discoveries may append a new operation under an existing case with a fresh stable operation ID, or add a new case with a suffix under the relevant P case when a newly delivered H5 or conditional branch reveals atomic behavior. Record source APK hash, discovery evidence, matrix/reachability, owner and new candidate label; add the row to the handoff, coverage CSV and parity ledger in the same change. Start it at UNMAPPED or a specifically evidenced BLOCKED status. It increases the applicable denominator and cannot inherit a MATCHED result. Obtain independent product-owner review of the expanded matrix and run the schema/coverage tests before runtime acceptance consumes it; independent source-derived development keeps the added boundary explicit without assigning captured or matched status.

Do not delete, rename or recycle a frozen ID because a static candidate later proves unused or changes meaning. Record the finding and its evidence in that row, then use an explicit reachability/status decision; retain its history. If a corrected APK baseline or formally approved scope correction truly requires changing a frozen tuple, create a new versioned baseline and ledger while preserving this one, cite the source and reviewer, invalidate affected parity results, update the pinned digest and tests in a reviewable change, and recalculate release coverage. Silent synchronized edits to YAML and CSV are rejected.

## Frozen baseline and outcome digest

Captured rows must use the frozen SuperLive Plus 1.18.1 APK SHA-256 f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281 from the [static baseline](apk-audit/00-coverage-baseline.md). A different APK needs a separately versioned ledger and contract set. A 64-character hash shape alone does not establish baseline identity.

In a captured handoff, outcome_digest is the SHA-256 of the **normalized successful semantic outcome** for the specified operation and matrix, not a raw response, packet or media hash. The sanitized fixture's overall outcome_digest and both success_1 and success_2 observation outcome digests must equal it. Normalize nonce and time fields only under a documented comparator rule; if two successes differ semantically, keep the operation UNMAPPED or BLOCKED and investigate. Authorization, offline/unsupported and post-submit-timeout observations each carry their own 64-hex outcome digest and need not equal the successful digest. These digests do not replace artifact digests or authoritative readback.

## Static route and JNI reconciliation

The [request-route inventory](tvt-request-route-inventory.csv) and [JNI declaration inventory](tvt-jni-declaration-inventory.csv) reproduce all 281 request-class rows and all 299 TVTOpenSDK native-declaration rows from the [static protocol audit](apk-audit/02-protocol-api.md). Each row gives its audit line and, where that table supplies one, its Java declaration line. MAPPED means only a static semantic link to a candidate operation ID. UNREFERENCED means the cited static audit found no generated route or app entry for that specific row; it does not prove runtime inaccessibility. BROKEN_STUB is restricted to cited empty Java paths or the five verified zero-return NAT bodies. UNKNOWN leaves the edge unresolved. Every row has runtime_proof=NO; neither inventory is a contract fixture or a G-P1 pass.

The operation handoff includes fixture_path and owner in addition to the fields below. The [fixture rules](../../tests/tvt_parity/fixtures/README.md) describe the private/raw versus sanitized/Git boundary. Promotion to CONTRACT_CAPTURED requires an actual sanitized UTF-8 JSON file under that directory, the SHA-256 of its bytes, matching metadata and observation variants, and independent review. Automated checks reject obvious embedded secrets or media; they cannot establish that a capture is authentic or that deployment rights exist.

## Status and gate rules

- `UNMAPPED`: candidate behavior has no captured-runtime upstream contract/acceptance decision; source-derived development selection does not promote it. This is the default for remote rows.
- `BLOCKED`: a concrete reason prevents capture or operation; record the exact account, device, browser, vendor, rights or transport reason and date before using it.
- `CONTRACT_CAPTURED`: the exact call and result have a sanitized, replayable success/error/timeout fixture on a specified account/device/region matrix; rights and deployment runtime are identified; an independent reviewer signs it.
- `NOT_APPLICABLE`: no upstream call is required for this local boundary, with cited evidence. It does not establish browser equivalence.

Neither an APK route name nor a candidate label may be promoted. No remote row has `CONTRACT_CAPTURED`; no family passes G-P1. This remains an acceptance boundary, not a development barrier. A full family decision additionally requires every mandatory reachable operation to replay in the chosen runtime under its permitted rights, including LAN/P2P/relay or Talk where the reference app uses them. `DECLARED` candidates require a runtime entry-path check before being counted reachable or excluded.

## Required capture envelope

For each applicable account role and entitlement, brand/region, device model/firmware and capability, network mode, browser/OS, permissions and locale/time zone, create a matrix ID before testing. For every operation, record:

1. Reset-state proof, APK hash/build, web/bridge build, user action, UI entry and static call-site reference.
2. Redacted destination class/method and request/response/error **field names, types and units**; no actual credentials, serials, private addresses or media bytes in Git.
3. Token **kind**, issuing/renewal owner and lifetime; callback ID, order/thread and terminal condition; deadline, retry and cancellation behavior.
4. The actual success outcome plus independent device/server readback, denied result, offline or unsupported result and post-submit timeout. A write timeout stays `UNKNOWN_OUTCOME` until authoritative readback resolves it.
5. Two successful observations to separate stable fields from nonce/time fields. Store sanitized artifact SHA-256 and outcome digest, reviewer ID/time, rights reference, adapter path and target OS/ABI.

Capture credentials, raw packets and media only in the private audit workspace. Use approved identities/devices; run read-only observations by default. Deletion, payment, firmware, audible output, relay/unlock and other writes require separate scoped test authorization. The fixture validator rejects a premature `CONTRACT_CAPTURED` row with absent evidence fields; later W01 work must add real replay fixtures and their schema-specific validation before promotion.

## Boundary questions that must remain separate

TVT user, P2P and device-access tokens have different roles in the [static protocol review](apk-audit/11-protocol-feasibility.md); renewal cannot be copied between them by name. `NetClientProtocal` and `NatTraveral` are distinct from five zero-return `TVTOpenSDK` NAT stubs. Cloud object access and Tyco REST have separate credentials and rights. H5 pages are downloaded and may add atomic actions beyond the 77-case seed. Browser media, Web Push, microphone and closed-client doorbell behavior need their own measured outcomes after the upstream adapter is proven.

Validation: `python -m unittest discover -s tests/tvt_parity -p test_runtime_fixture_schema.py -v`. The W01 plan's `uv run pytest` command can be used when the T01 Python workspace and dependencies exist.
