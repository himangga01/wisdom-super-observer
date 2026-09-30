# Private asset implementation and acceptance

T05A implements generic private JPEG/PNG upload, authenticated encrypted
storage, downloads and eventual physical cleanup. It remains in progress.
Contracts and bounded S3/crypto/image primitives are committed at `aedbe2d`.
The actual S3/HTTP baseline and all fourteen lifecycle acceptance cases remain
open. This work does not establish APK feature parity.

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

## Required remaining evidence

The sealed `6565929` baseline must first complete actual provider and authenticated
HTTP/CSRF preflight and then fail exactly at the missing POST route. The separate
strict GREEN gate requires all fourteen real lifecycle cases, including crypto
tampering, expiry/revocation, parent crops, genuine Celery restart, multipart
pagination, orphan cleanup and key rotation. Real PostgreSQL permission,
lock-wait and migration lifecycle checks are also required. Source/offline
results and ordinary foundation CI do not substitute for these gates.
