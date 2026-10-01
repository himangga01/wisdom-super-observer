# Private asset implementation and acceptance

T05A implements generic private JPEG/PNG upload, authenticated encrypted
storage, downloads and eventual physical cleanup. It remains in progress.
Contracts and bounded S3/crypto/image primitives are committed at `aedbe2d`.
The actual S3/HTTP baseline and all fourteen lifecycle acceptance cases remain
open. This work does not establish APK feature parity.

Reviews of the committed product source at `0deeb79` found no unresolved Critical
or Important findings. The separate fixture relay review’s three Important
findings were later addressed in fix round 1, as recorded below. The OpenAPI
metadata finding is resolved: upload declares required `X-Upload-Session` and
JPEG/PNG binary content; download declares the required `X-Asset-Ticket` and
JPEG/PNG binary success content. The fix adds no eager upload-body parsing or
buffering. These are reviewed source contracts, not
evidence of provider acceptance.

## Runtime configuration and database controls

The normal FastAPI application mounts the asset routes. Missing or invalid
asset settings leave those routes unavailable with private, uncached errors.
The API needs the separate application, identity and web-session database URLs;
maintenance needs only `WSO_ASSET_MAINTENANCE_DATABASE_URL`. The migration adds
the restricted `wso_asset_maintenance` LOGIN and `wso_asset_owner` NOLOGIN roles.
Local verification selects nine role URLs including the existing admin role.
Provisioning preserves the already saved credentials and PostgreSQL identity.

Use the `WSO_ASSET_*` entries in `.env.example`: installed namespace, HTTPS S3
endpoint, region, separate API/maintenance credentials, active key ID and a JSON
mapping from key IDs to absolute protected 32-byte key files. Keep retained keys
available for existing envelopes. Maintenance loads no API key or key-file map.
`python -m wso_api.assets.bootstrap maintenance --once` runs one cleanup batch;
omit `--once` for the loop. A local capability facade permits only list, delete
and multipart abort before helper dispatch; actual IAM enforcement is separately
tested against the provider. The fixture-only loopback HTTP flag requires the
explicit disposable Linux CI prerequisites and owned-resource verification.

Asset authorization uses separate bounded database pools and an independent
NullPool grant-redemption connection. One monotonic request budget covers cookie
lookup, identity, grant issuance/redemption and current tenant authorization;
control transactions use the shorter route/lease limit. Startup and maintenance
configuration transactions each get a fresh five-second deadline. Statement and
transaction caps are at most five seconds, lock waits at most one second, and
every subsequent operation checks the remaining budget. A new physical
connection with insufficient remaining budget is refused.

Role URLs must select one address. For DNS hostnames, provide the trusted numeric
`WSO_ASSET_DB_HOSTADDR`; the hostname remains available for TLS verification.
The bounded provider rejects every ambient process variable whose name starts
with `PG`, including otherwise harmless PostgreSQL deployment variables. Supply
explicit approved connection settings instead of ambient libpq service files or
defaults. Constructors do not read or mutate process environment. These driver
and server bounds do not replace the independent OS watchdog described below.

Private asset tables separate the migrator's DDL ownership from the function
owner's minimal DML grants and force row-level security. Cleanup emits a durable
private audit outbox in its transaction; a separate maintenance projection locks
the tenant first before writing the public audit. This avoids reversing the
business tenant-to-asset lock order. Public audit delivery is eventual; external
attention alerts remain an unimplemented deployment gate.

## Authority and namespace

Use a separate private bucket and distinct gateway/maintenance credentials for
each installation. Persist the installation UUID and bucket through the
migrator-only one-time installer; matching repeat installation is idempotent,
and changing either value is rejected. The protected getter returns exactly
two namespace columns and all thirteen `AssetPolicy` columns. Runtime startup
checks the current database role and exact namespace before loading keys or
constructing transport dependencies. Policy changes require an increased
version and an explicit runtime restart; requests do not silently reload.

Gateway credentials have object authority under the installed prefix. The
maintenance identity can list/delete/abort within its assigned authority and
has no object-read or key capability. Normal object listing uses a prefix IAM
condition; object mutations and multipart abort use prefix resource authority.
Standard S3 `ListBucketMultipartUploads` has no `s3:prefix` IAM condition:
its raw authority is bucket-wide. The adapter still fixes the installed prefix
and rejects caller-selected namespaces, but raw credentials may enumerate
incomplete-upload metadata within that dedicated bucket. A shared production
bucket would expose that metadata and fails the installation requirements.
See the [AWS S3 action/condition reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html).

## Provider fixture candidate

**Current disposition:** MinIO `RELEASE.2025-04-22T22-12-26Z` is rejected for the required native installed-prefix multipart pagination and durable restart/orphan discovery contract. RustFS 1.0.0 is the approved transition design; fixture source/checker reviews and root's offline aggregate are approved, pending final documentation and publication gates. It is not runtime/provider acceptance or production selection. The artifact metadata and earlier experiments below are historical; they do not imply current candidate approval.

### RustFS transition status — 2026-10-01

The frozen design is `rustfs-inert-acl-dedicated-bucket-v1`, based on official
RustFS source commit `d47f54bfb2f39f48bd1adda334bd27e151fe85b8`. The verified
official Linux x86_64 musl archive is 194,469,895 bytes, SHA-256
`c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8`; its exact
`rustfs` server member is 264,596,736 bytes, SHA-256
`222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad`. The
source/archive and static ELF were inspected read-only; the executable has not
been run. The plan uses the server member only, without `rustfs-cli` or `mc`.
This is a fixture pin, not a production image approval.

The design retains the exact 13-key receipt and the normal fixture import of
the pure standard-library `scripts.asset_provider_receipt` module, with an
explicit package import for the standalone CLI mode. The checker component is
READY: its 216 focused contracts passed in 1.31 seconds, with Ruff, formatting
and scoped mypy passing; fresh independent review is approved with 0 Critical,
0 Important and 0 Minor findings. The original fixture source review first
reported six Important findings; all six were addressed in one owner fix batch.
Fresh scoped review is approved with 0 Critical, 0 Important and 0 Minor. The
final fixture owner run passed 676 profile/safety cases in 4.98 seconds; the
independent helper run passed 201 cases in 0.41 seconds. Root's single amended
aggregate passed 1,093 cases in 7.26 seconds with no skips, comprising 676 +
201 + 216. Ruff check/format across nine files, configured mypy across 40
product files and explicit pure-checker mypy across two files passed. These are
offline source/contract facts, not RustFS or sealed-fixture behavior.

The frozen profile specifies 63 private-effect checks, the exact 24-control
table, four true public-access-block readbacks, synthetic ACL characterization,
and two native administrator denial probes outside that table. Native
ownership-control responses of 501 are unsupported operations, not IAM denials.
Administrator no-effect observation uses 20 root-read-only snapshot calls and
compares complete export, user-info and policy-info observable metadata; hidden
identity/version, transient state and clock limits remain explicit. Gateway
authority covers object PUT/GET but not delete; cleanup covers delete and
multipart abort without GET, HEAD, PUT or key access. A dedicated bucket remains
required because multipart-upload listing authority exposes bucket-wide
metadata.

The restart proof requires the same owned container ID, image, network, volume
and configuration, settled old transport and a healthy stop/start. Only the
fresh network endpoint ID/IP and relay lifetime may change. It requires native and gateway
markers, same-key multipart uploads, raw-cursor resume and on-disk durability,
without reseeding, fabricated cursors or known SQL inventory. Planned
containment is nonroot UID/GID 65532, data and private tmp mode 0700, 64 MiB
logs/tmp budget, internal bridge without host publication, read-only root,
capability drop, protected mode-0600 environment file and independent 20/40
hex credential pairs. These remain design/source gates pending actual execution.

The provider phase budget remains twelve minutes split into 6/3/3-minute phases,
with three minutes for cleanup and one minute for the API/HTTP reserve; all
existing call caps remain unchanged and new calls must fit them.
The full fourteen-case aging plan is gated and not activated. The 11th MinIO
attempt remains the latest actual provider run and failed setup as recorded
below. No RustFS acceptance, authenticated HTTP, genuine sealed-656 RED,
full14 GREEN, W02 reopening or APK parity is established.

Root has defined one conditional RustFS probe12, but has not activated it. Its
condition requires final four-doc spec/quality approval, the staged private18
guard, exact 14-file no-drift/whitespace/source-hash checks, one reviewed
curated commit and one combined push, then verified remote SHA equality. If
activated after those gates, it permits at most one automatic cold probe using
the existing 20-minute sealed656 overlay12 workflow and foundation workflow.
There is no manual retry, product overlay or budget increase. The cold runtime
assertions must pass before an authenticated missing-route RED can count.

The two actual SeaweedFS 4.47 probes failed setup; neither is meaningful
missing-feature RED. At that earlier stage, the proposed replacement was an
unmodified official Linux binary packaged into an owned local scratch image:

| Artifact | Exact version | SHA256 |
| --- | --- | --- |
| MinIO | RELEASE.2025-04-22T22-12-26Z | 53e2a2cb16c5366ea6fbbc479c19ddb4c6a0948273e752f740fb1fbf27bb817c |
| mc | RELEASE.2025-04-16T18-13-26Z | ac90da87a35641be5a0ac75d49de5161ddb47d629b5ba01261b0ae9e00aea15f |

The receipt records both hashes, server source commit
`0d7408fc9969caf07de6a8c3a84f9fbb10a6739e`, and the actual local image ID.
A local image ID is not an official container registry digest. These historical
artifacts are a fixture candidate, without production image or security approval.

The proposed profile `minio-inert-acl-dedicated-bucket-v1` accepts inert ACL
behavior only when actual signed bytes remain private and anonymous GET/HEAD
are denied after every valid public ACL/grant attempt, including new PUT and
completed multipart writes. An unsupported response alone proves no privacy.
Gateway/maintenance public bucket-policy mutations must actually be denied.
Versioning and Object Lock must be off. Foreign-bucket listing, foreign object
delete and foreign multipart abort must be denied; controlled foreign objects
and uploads must remain intact. Real multipart pagination, signed retrieval,
expiry and exact cleanup are required.

This profile does not claim AWS PublicAccessBlock or BucketOwnerEnforced API
compatibility. Known pinned MinIO control-query routing is characterized
explicitly: GET is unsupported, and runtime mutation queries must be denied
without changing the owned bucket or object privacy. Administrator mutation
queries that may match bucket creation/deletion routes are omitted. Public
object ACL attempts still run with administrator and both runtime identities.
All source-based expectations need actual provider confirmation.

### Current owned Linux probe and relay status

Two later MinIO attempts still failed during fixture setup. Run
[36751745062](linux-ci.md#fourth-private-asset-probe-data-volume-mode-rejected)
observed the nonroot data-volume directory as UID/GID `65532:65532`, mode
`0755`, and stopped at the required private-mode check. Run
[36754155359](linux-ci.md#fifth-private-asset-probe-loopback-publication-check-failed)
passed the volume gate at `0700`, then failed the loopback-publication check.
The latter run's actual port fields were not captured, so their shape remains
unknown. Neither run reached HTTP or established provider privacy/IAM behavior;
both strict RED receipts were rejected.

Pinned [Moby v28.0.4 source](https://github.com/moby/moby/blob/v28.0.4/daemon/network.go#L860)
skips port-mapping options for an Internal network. This is consistent with the
publication failure, but does not establish what port fields that run returned.
The accepted fixture-only design removes Docker host publication and specifies
a bounded opaque TCP relay from literal `127.0.0.1` to the owned MinIO numeric
address on the Internal bridge. The original scoped review found three Important
deadline-validity findings. The author’s fix round 1 addressed I1/I2/I3 and
received scoped approval with no new Critical or Important findings. Its
covering selection passed 120 tests in 1.15 seconds, Ruff, formatting of four
files, and configured-source mypy for 40 files; a fresh root run passed 120 tests
in 1.11 seconds with Ruff and formatting also passing. This source fix approval
does not establish actual Linux connectivity. The relay is not a production
proxy or provider-security approval.

### Fixture-only MinIO control profile v2

The reviewed fixture design is `minio-inert-acl-dedicated-bucket-v2`; its
two-file source change and two-file strict consumer change each received
independent scoped approval with zero Critical, Important or Minor findings.
The consumer retains the original 77-case profile surface.
The implementation is source-reviewed, while actual Linux/provider acceptance
remains pending. It preserves schema 1, the exact eleven
receipt fields, pinned binary/release/source inputs, and the existing
capability string. It supersedes the v1 unsupported-control-PUT expectation;
valid v1 and SeaweedFS receipts are refused. Gateway performs runtime object
reads; gateway and cleanup perform control checks, while cleanup retains no
read capability. Bootstrap remains trusted configuration and is excluded from
control PUT/DELETE and ordinary CreateBucket probes.

The v2 control profile requires four valid AWS control PUT attempts to return
exact HTTP 400 / `MalformedXML`, plus two ordinary CreateBucket attempts against
the existing owned bucket to return exact HTTP 403 / `AccessDenied`. The latter
only tests that existing bucket/action; it proves no general new-bucket or
ownership authority. All six unsupported GET checks and the 63-effect
public-grant matrix remain unchanged; the normal control sequence has 24
attempts. Each parser/CreateBucket attempt requires signed original bytes and
HEAD, private object and bucket ACL, exact absent policy 404 / `NoSuchBucketPolicy`,
anonymous GET/HEAD denial, and the owned bucket remaining present. Supported
mutation denials and control DELETEs remain exact 403 / `AccessDenied`; the
unsupported GETs remain exact 501 / `NotImplemented`. A parser 400 is not an
IAM denial. Unexpected responses require bounded effects diagnostics, and failed
effects readback cannot produce an acceptance receipt. No provider acceptance
follows from this design or from the setup attempt below.

The v2 producer’s 251-case GREEN selection passed in 1.58 seconds; the root’s
fresh selection passed 251 in 1.73 seconds. Ruff, formatting of four files, and
configured product-source mypy on 40 files passed. A separate optional
three-file public-proof addition received independent scoped approval with zero
findings; its 82-case selection passed in 0.39 seconds, the root’s fresh
selection passed 82 in 0.44 seconds, Ruff/formatting of two files and script
mypy passed. When enabled, this optional flag retains an exact validated
canonical receipt and fixed minimal DERIVED JUnit only after strict actual RED
success. Default behavior and rejection behavior are unchanged; the workflow
only adds the flag and uploads no artifacts or changes to acceptance criteria.
These are source-contract and local test results, not proof of provider
behavior.

The sixth sealed baseline attempt, [run 36765314359](linux-ci.md#sixth-sealed-private-asset-baseline-probe-control-route-setup-failed), reached relay S3 control preflight but stopped when the shared-gateway administrative bucket-route mutation returned 400 / `MalformedXML`. This did not establish IAM denial or provider compatibility. The first ownership PUT is a source inference; the run did not capture the operation trace. The two ordinary CreateBucket checks and remaining control/effects checks were not accepted as complete; authenticated HTTP/CSRF preflight and genuine missing-route RED were not reached. This attempt predates the independently reviewed v2 source changes above.

The seventh [attempt](linux-ci.md#seventh-sealed-private-asset-baseline-attempt-inert-put-effect-unclassified) reported one setup error in 21.59 seconds after a typed gateway `put_object` variant-1 response of HTTP 200 / accepted inert candidate; the subsequent effects bundle failed, but its target and component were not retained. This is neither privacy acceptance nor an accepted receipt. Source order places it at the 26th scheduled public-matrix entry, but no prior 25 independent receipts, full 24-control profile, or 63-effect matrix verification can be inferred. A diagnostic-only two-file source amendment received independent scoped approval with no Critical/Important/Minor findings. The author’s final 306-case selection passed in 1.80 seconds and root’s fresh 306-case selection passed in 1.73 seconds; Ruff/format of four files and configured mypy 40 passed. The review confirmed only seven declared methods changed; relay, safety, checker and workflow hashes are unchanged. These diagnostics preserve assertions and only identify a bounded failure stage; the component and cause remain unknown. Exact two-path staging, private 18-value guard, and no-drift checks passed; diagnostic source commit `3bcf178a9eb93d296658a11a2cedf03e833e02f3` was pushed and remote-verified; the later eighth attempt is recorded below and remains unresolved. No behavior fix or provider acceptance is claimed.

### Integrated product Linux evidence and remaining T05A gates

The distinct [0deeb79 foundation receipt](linux-ci.md#linux-foundation-run-36760448179) at product HEAD `0deeb79024fccf6bb7e6e3157aceadd39674da77` passed 1200 ordinary Python cases and ten actual Celery/Valkey recovery cases, both with zero skips. Its ordinary pytest invocation included the isolated `0003a_assets` migration and nine-role integration; the published evidence is aggregate only. The separate [f79c83e foundation receipt](linux-ci.md#linux-foundation-run-36765314386) passed 1375 ordinary Python cases and ten actual recovery cases, both with zero skips, but predates and excludes v2 control-profile and optional public-proof changes. The separate [406f47e foundation receipt](linux-ci.md#linux-foundation-run-36774933005) passed 1512 ordinary Python cases and ten actual recovery cases, both with zero skips, and covers those reviewed v2/public-proof changes. The [dff9ec7 foundation receipt](linux-ci.md#linux-foundation-run-36782405311) passed 1567 ordinary Python cases and ten actual recovery cases, both with zero skips, and covers source commit `3bcf178a9eb93d296658a11a2cedf03e833e02f3`; it predates and excludes diagnostic source commit `cddeee3e438ccfa7a51f817b24d2781e51be2495`. All are aggregate foundation receipts: none establishes actual provider privacy/IAM, authenticated baseline RED, or full fourteen-case acceptance.

The [ee9c11b foundation receipt](linux-ci.md#linux-foundation-run-36789932368) passed 1642 ordinary Python cases and ten actual Celery/Valkey recovery cases, both with zero skips. It is a distinct historical receipt covering `cddeee3` and the docs at `ee9c11b`; it predates `3048067` and later updates. The preceding [0a033bc foundation receipt](linux-ci.md#linux-foundation-run-36795275636) passed 1703 ordinary Python cases and ten actual recovery cases, both with zero skips. Ruff/mypy 40, frontend typecheck/lint/build and 15 unit cases, twenty canonical exports twice, TVT checker 77 audit cases / 77 ledger rows / zero errors, HTTPS Chrome 26, Valkey smoke and owned PostgreSQL cleanup passed. It covers reviewed source `3048067` and the published docs at `0a033bc`, and excludes the later idle-retirement source implementation and this draft. These historical receipts are aggregate foundation evidence; none establishes provider privacy/IAM, authenticated HTTP, sealed-656 genuine RED, full14 or parity acceptance.

The eighth [attempt](linux-ci.md#eighth-sealed-private-asset-baseline-attempt-anonymous-get-transport-error-and-cleanup-failure) ended with one setup error in 21.04 seconds. The retained mutation was gateway `create_multipart_upload`, variant 1, HTTP 200 / accepted inert candidate; the subsequent original-object `anonymous_get` returned `TRANSPORT_ERROR`, null status, and code `TRANSPORT_ERROR`. The HTTP exception kind/phase and provider-close category remain unknown; the label does not prove an HTTPX/socket failure or anonymous HTTP 200. Workflow-owned PostgreSQL cleanup succeeded, while fixture-local provider close failed. Source order identifies the 27th scheduled entry only, not 26 accepted bundles, full 24 controls, or full 63 effects. Diagnostic source commit `cddeee3e438ccfa7a51f817b24d2781e51be2495` received scoped Astra approval with no findings after a fix round; it adds bounded error and relay/close diagnostics without changing behavior or acceptance. That source commit and the reviewed docs were pushed in one branch update resulting in `ee9c11b2c14a409b1d055e3b62a1359abb93c718`; remote SHA was verified and the tree was clean. Neither the review nor the eighth receipt established its cause, provider acceptance, authenticated RED, public proof or full14 acceptance.

The ninth [attempt](linux-ci.md#ninth-sealed-private-asset-baseline-attempt-anonymous-head-transport-error) used source `ee9c11b2c14a409b1d055e3b62a1359abb93c718` and ended with one setup error in 22.04 seconds. Its accepted-inert gateway multipart mutation was followed by a new-object `anonymous_head` effect reporting `HTTPX_READ_ERROR` in `HTTP_REQUEST`, with `TRANSPORT_ERROR`, null status and code `TRANSPORT_ERROR`. The closed relay diagnostic recorded `RELAY_TRANSPORT`, `CLOSED`, `failed=true`, zero tracked connections/sockets/workers, first stage `PUMP_CUTOFF`, and first kind `UNKNOWN`. These counts do not prove quiescence or that the cutoff caused the HTTP failure; exact cutoff reason and chronology are unknown. Workflow-owned PostgreSQL cleanup succeeded, but fixture-local close refused. No public proof, provider/authenticated HTTP acceptance, genuine sealed656 RED, or full14 acceptance was reached. Diagnostic commit `3048067bd515bcd86a2a41f48c1de56874e26785` and its reviewed docs were published in the `0a033bc` update. It preserves current behavior and does not identify the ninth cause.

The tenth [attempt](linux-ci.md#tenth-sealed-private-asset-baseline-attempt-anonymous-head-read-error) used source `0a033bce6733e0a15ffd8f8e2180c1e2d7c39e05` and ended with one setup error in 22.79 seconds. The gateway `put_object_acl` variant-4 mutation returned HTTP 403 / `AccessDenied`; the original-object `anonymous_head` effect then recorded `HTTPX_READ_ERROR` / `HTTP_REQUEST`, null status and `TRANSPORT_ERROR`. Before the request, the relay was RUNNING and not failed, with 4 connections, 9 sockets and 5 workers. At failure it remained RUNNING but failed, with 2 connections, 5 sockets and 5 workers; first stage/kind were `PUMP_CUTOFF` / `IDLE_CUTOFF`. Close recorded `RELAY_TRANSPORT`, CLOSED, failed true, zero counts and the same first stage/kind. The private log was 59,653 bytes (SHA-256 `5d7a911e121a6345d7a6993fcf8c853eccc346fbe36088cd8e841a99a335a56a`). The snapshots do not prove same-connection causality, freshness, quiescence, expiry chronology or the cause of the HTTP error. No provider privacy/IAM or 24/63 receipt, authenticated HTTP, sealed656 genuine RED, full14 GREEN or APK parity was established. Workflow-owned PostgreSQL cleanup succeeded; fixture-local provider close refused. The accepted idle-retirement implementation is independently approved and locally committed as `52343d410755ceb1190e979557d0bc6bcb0b153f`; it does not establish or explain this attempt. The conditional eleventh authority was consumed by actual run 36801780564. No same-provider retry, manual retry or twelfth run is authorized.

The accepted idle-retirement implementation is confined to the fixture worker and safety contracts. A typed idle cutoff during validated forwarding retires only that connection without poisoning the relay; pump cutoff, absolute/tie cutoff, byte limits, forged provenance, unknown errors and native transport/control faults remain fatal. Finalization attempts both owned handles, retaining any handle and its slot reservation if close raises. Pending first-origin publication and STOPPING metadata suppression remain intact. The original source review recorded 0 Critical / 1 Important / 1 Minor; its Important teardown and Minor fragmented-request findings were addressed in fix round 1 and independently approved with 0 Critical / 0 Important / 0 Minor. Targeted fix RED failed 3 cases (135 deselected); final author verification passed 465 and root’s fresh run passed 465. Ruff passed; formatting reported two unchanged files; the configured mypy40 result remains applicable because only untyped tests changed. The reviewed source commit `52343d410755ceb1190e979557d0bc6bcb0b153f` and docs were published together at `d5aaba84fd1f456bb93e0d40b600203c1ee6877f`; remote SHA matched and the worktree was clean. The conditional eleventh authority was consumed by run `36801780564`; no same-provider retry, manual retry or twelfth run is authorized. Owned-socket contracts do not verify configured idle/absolute timing against a real provider. No provider acceptance, explanation of the tenth failure, authenticated HTTP, genuine sealed656 RED or full14 acceptance follows from these source tests.

A later two-file receipt-safety correction passed 247 scoped cases
and received an independent review with zero Critical or Important findings. It
improves result-gate validation only and does not prove provider behavior. A
separate four-file fixture relay fix round then addressed the three Important
findings and received scoped approval with no new Critical or Important findings.
These scoped changes do not establish actual provider privacy/IAM, authenticated
baseline RED, full fourteen-case GREEN, or actual relay connectivity. The older
`0deeb79` receipt predates them; the newer foundation aggregate does not replace
their provider-specific gates.

## Local helper containment

Each S3 operation and image decode uses an explicitly owned child, private
bounded IPC, a fixed work cutoff set before creation, and an exception-safe
reaper. A late startup return permits no SDK/body dispatch or successful result.
Unsettled local resources poison admission instead of increasing capacity.
Normal runtime instances share exactly two upload and two read slots; permits
remain held until local buffers/helpers/streams settle.

Synchronous OS/runtime process creation or control can block beyond the cutoff.
The unsupervised caller has no hard return/reap wall-time guarantee under that
condition. Production containment requires an independent watchdog owning the
entire worker group, verified Linux cgroup v2 or Windows Job Object inheritance,
nonsecret deadlines registered before startup, and removal/reaping before
replacement. This deployment gate is unimplemented. Its intended two-second
reaction applies on a responsive host and may abort concurrent requests.
Neither a local kill nor one later absence observation proves a remote write
stopped; durable cleanup retains uncertain outcomes until authoritative proof.

Before an SDK multipart completion, the coordinator commits a monotonic SQL
completion-dispatched fence under the matching unexpired write lease. An unknown
SQL acknowledgment prevents that SDK call. For an incomplete attempt whose fence
is false, cleanup can finish after lease/grace, fully paginated abort/absence
checks and an atomic tombstone that forbids later completion authorization. This
proves completion was never dispatched; it does not cancel delayed remote create
or part operations. Periodic namespace reconciliation must still remove their
later multipart orphans. Dispatched or uncertain completions remain conservative
until authoritative observation or stronger quiescence evidence.

The latest [d5aaba8 foundation receipt](linux-ci.md#linux-foundation-run-36801780609) passed 1726 ordinary Python cases with zero skips in 134.54 seconds and ten actual Celery/Valkey recovery cases with zero skips in 250.61 seconds; the exact-ten gate passed. Configured mypy 40, frontend 15 and typecheck/lint/build, twenty exports twice, TVT checker 77 audit cases / 77 ledger rows / zero errors, HTTPS Chrome 26, Valkey smoke and owned PostgreSQL provision/removal succeeded. Its complete private log was 89,980 bytes, SHA-256 `935a412757df60a0fe7cf848ad3117836c052a454206cfc73854b3e8d42f56c2`. It covers source `52343d4` and docs at `d5aaba8`; it is foundation evidence, not provider acceptance.

The eleventh [sealed baseline attempt](linux-ci.md#eleventh-sealed-private-asset-baseline-native-listing-contract-failure) at run `36801780564` / job `110177497442` ended with one setup error in 36.28 seconds. Checkout/overlay/dependency sync/PostgreSQL provision and workflow PostgreSQL removal succeeded. The combined forced-pagination/filter checkpoint failed; the 57,773-byte private log SHA-256 is `9571f6a737c502421f6bcde711d21f67198f42f03a3097d2e3f5b241d276ecb5`. Bounded extraction found zero public-proof prefixes, zero validated ACL failure records and zero provider-close diagnostic records. Its fixed disjunction requires four object identities, three child-key multipart identities, at least two pages in both listings and exact set equality. Actual page/row counts, equality results and the predicate that failed were not retained; do not infer them. By source order, authenticated object operations and the privacy profile, presigned and expired checks, maintenance and foreign-authority checks, foreign-key multipart observation, child-key object/multipart/list-parts operations and both listing helpers returned before the aggregate checkpoint. This progress does not produce a provider receipt, authenticated HTTP result, genuine sealed656 RED or full14 acceptance. No cleanup refusal is indicated by retained markers; workflow PostgreSQL removal remains a separate successful result.

Root rejected the pinned MinIO candidate for this required capability. Its `ListMultipartUploads` implementation treats its nonempty `Prefix` as one exact object ([`erasure-sets.go`](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-sets.go#L881)) and multipart listing visits that object's multipart directory rather than enumerating arbitrary child keys ([`erasure-multipart.go`](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-multipart.go#L254)). The empty-prefix cache path does not supply bounded, durable inventory after restart ([`erasure-server-pool.go`](https://github.com/minio/minio/blob/0d7408fc9969caf07de6a8c3a84f9fbb10a6739e/cmd/erasure-server-pool.go#L1696)). This source-supported incompatibility is distinct from the unretained actual predicate. The conditional eleventh authority is consumed; no same-provider diagnostic retry, manual retry or twelfth run is authorized. Read-only primary-source investigations are complete. RustFS 1.0.0 is chosen only as a transition-design candidate under review; no provider is selected for acceptance, no runtime or source implementation is authorized, and no retry authority exists.

## Required remaining evidence

The sealed `6565929` baseline must first complete actual provider and authenticated
HTTP/CSRF preflight and then fail exactly at the missing POST route. The separate
strict GREEN gate requires all fourteen real lifecycle cases, including crypto
tampering, expiry/revocation, parent crops, genuine Celery restart, multipart
pagination, orphan cleanup and key rotation. Real PostgreSQL permission,
lock-wait and migration lifecycle checks are also required. The isolated Windows
migration round trip has one passing execution. The `0deeb79` foundation receipt
predates the relay deadline fix; the newer `f79c83e` receipt predates and excludes
the v2 control-profile and optional public-proof source changes. Neither
foundation aggregate substitutes for provider and lifecycle acceptance. The
original fourteen-case design review was zero Critical / three Important / one
Minor. Fix 1’s scoped review was zero Critical / three Important / zero Minor;
it closed original I2 and M1, while I1 and I3 were partial and the
`CREATE_MULTIPART`/`UPLOAD_PART` selector mismatch remained. Original-author
design fix 2 then received scoped Astra review approval with zero Critical /
Important / Minor findings and all three Important findings addressed; original
job/alias closure is retained. This is design review only, not source or actual
provider/full-lifecycle acceptance. Root accepts the fixture-only broker-factory
direction and six conditional future paths only behind genuine RED-gated source
work. No full fourteen-case GREEN result exists.
