# Private asset implementation and acceptance

T05A implements generic private JPEG/PNG upload, authenticated encrypted
storage, downloads and eventual physical cleanup. It remains in progress.
Contracts and bounded S3/crypto/image primitives are committed at `aedbe2d`.
The actual S3/HTTP baseline and all fourteen lifecycle acceptance cases remain
open. This work does not establish APK feature parity.

Scoped implementation review/fix rounds currently have zero unresolved Critical
or Important findings. The OpenAPI metadata finding is resolved: upload declares
required `X-Upload-Session` and JPEG/PNG binary content; download declares the
required `X-Asset-Ticket` and JPEG/PNG binary success content. The fix adds no
eager upload-body parsing or buffering. These are reviewed source contracts, not
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

The two actual SeaweedFS 4.47 probes failed setup; neither is meaningful
missing-feature RED. The replacement is an unmodified official Linux binary
packaged into an owned local scratch image:

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
address on the Internal bridge. The relay implementation and actual Linux
connectivity are still in progress and unverified. It is not a production proxy
or provider-security approval.

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

## Required remaining evidence

The sealed `6565929` baseline must first complete actual provider and authenticated
HTTP/CSRF preflight and then fail exactly at the missing POST route. The separate
strict GREEN gate requires all fourteen real lifecycle cases, including crypto
tampering, expiry/revocation, parent crops, genuine Celery restart, multipart
pagination, orphan cleanup and key rotation. Real PostgreSQL permission,
lock-wait and migration lifecycle checks are also required. The isolated Windows
migration round trip has one passing execution, but the current product delta has
not yet been exercised on Linux. Source/offline results, foundation CI and
design-only relay acceptance do not substitute for these gates.
