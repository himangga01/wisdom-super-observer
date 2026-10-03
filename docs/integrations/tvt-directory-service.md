# Protected readonly TVT directory service

Analysis/implementation date: 2026-10-02 (Asia/Seoul). Source baseline: `e2161339677e2f1ccc230682658de321a2f74821`; source-approved private adapter and APK 1.18.1 evidence are in [directory adapter](tvt-directory-adapter.md) and [device directory source](tvt-device-directory-source.md). **MATCHED=0; release_ready=false.** This slice supplies public models, protected SQL admission, and a worker executor. RPC, API routes, browser UI, inventory persistence, store/channel grants and vendor acceptance remain separate work.

Final review packet sealed on 2026-10-03. The source guard is based on approved publication `b25df5268a6ff7b524232c7c62cf52bb1583061d`; its literal roster is extended only by the directory table to canonical0011=66, or67 with the strictly validated optional recovery fixture. Linux partitioned/foreign table objects are rejected before row reads. The Windows36/OID16384/0003a branch and all27 existing flow cases are preserved. No prior SQL suites were replayed for this guard delta.

## Public contracts and handoff

`wso_contracts.tvt.directory` contains frozen, extra-forbidden `DirectoryReference(identity_id, region, brand)` and six request models. Identity/region/brand are selectors; they do not confer authority. Requests contain no actor, tenant, role, generation, session digest, credential, origin or profile override.

| Fixed method | Request model | Additional fields |
| --- | --- | --- |
| `device_list` | `DeviceListRequest` | `page_num=0`, `page_size=1000` |
| `channel_list` | `ChannelListRequest` | `sn_list` |
| `device_detail` | `DeviceDetailRequest` | `sn`, `return_chl=False` |
| `channel_detail` | `ChannelDetailRequest` | `sn`, `chl_index` |
| `sent_shares` | `SentSharesRequest` | page fields, `resource_types=()` |
| `received_shares` | `ReceivedSharesRequest` | page fields, `resource_types=()` |

Each model has its fixed literal `method`. Integer fields reject booleans/string coercion. Page zero and size zero remain source-compatible. Local ceilings are page size1000, SN list100, resource types16, signed native integer range (nonnegative page/index), distinct selectors and canonical JSON65536 bytes. SN is opaque, nonempty BMP text of at most4096 UTF-8 bytes without surrounding whitespace or controls. Empty resource types omit the upstream wire member. Constructors/model copies are revalidated before canonicalization and execution.

`DirectoryView` binds identity, region, brand, fixed method, managed generation and bounded request ID to `records: tuple[ObservationObject,...]`, `total: str | int | None`, `complete: None`, and `grants_operations: False`. Device totals stay strings; share totals stay integers. Detail results contain one object, channel-list results contain the observed device objects. There is no inferred pagination completion or removal instruction.

`ObservationObject.fields` contains `ObservationField(name, state, value, source_default, opaque_kind)`. Names are a fixed literal allowlist of decoded safe fields. State retains missing/null/value. Nested values use typed objects/tuples/scalars rather than raw maps. Java Object values preserve safe scalar values or shape-only `opaque_kind`; their arbitrary contents disappear. Unknown upstream fields are counted, then discarded by the private projection. Sent and received share schemas remain independent. Capability/auth/status observations never grant media, PTZ, Talk, ownership or a WSO role. Device IP strings are metadata, never origins.

## API and worker interfaces

API-side `DirectoryTicketIssuer(session: sqlalchemy.orm.Session, remaining: Callable[[], int]).issue(session_digest: str, method: str, body: DirectoryRequest) -> str` must run inside an actual consumed `require_tenant`/`tenant_session` transaction. The digest is computed from the authenticated T03 cookie server-side; it is never a browser field. Commit that transaction before calling the worker. Forward the same original public-path10000ms budget, not a new10000ms timeout at each hop. Never serialize the opaque ticket to the browser.

Worker-only `DirectoryAdmission(worker_url, policies: tuple[DirectoryPolicy,...], provider: KeyProvider)` uses the existing `wso_connection_worker` login role and fixed SQL functions. `DirectoryPolicy(region, brand, profile_id, consent_version)` is immutable trusted deployment configuration. Its `redeem(ticket, method, body)` returns a private sealed `DirectoryLease`; `claim(lease)` returns a private delegated `AccountLease` with purpose profile. `snapshot(lease) -> PrivateToken`, `check`, `publish`, and `dispose` operate on the exact lease/query/profile binding. Lease values, query internals, session digests and delegated refs are not public DTOs or representations.

`DirectoryWorkerExecutor(admission, endpoints: tuple[AccountEndpoint,...])` implements the `DirectoryWorker` protocol:

```python
execute(method: str, ticket: str, body: DirectoryRequest,
        *, deadline_ms: int, correlation_id: str) -> DirectoryView
close(*, deadline_ms: int = 1000) -> None
```

Trusted endpoints are the existing immutable `AccountEndpoint` records copied into a read-only mapping, with an exact `(region,brand)` match and the existing `OriginPolicy`. No result or public request can replace the origin. Worker factory/lifecycle owns admission resources; executor close cancels only its own readers. The API process must not construct this executor or receive worker URLs, key providers or decryption primitives.

## Protected authority and schema

Migration `0011_tvt_directory_read_tickets` adds exactly one table, `wso_private.tvt_directory_tickets`, owned by the existing NOLOGIN `wso_account_owner`, with ENABLE/FORCE RLS and explicit owner/migrator policies. Existing W05 six-purpose and W06 eight-purpose functions/tables remain unchanged. Runtime roles have no direct new-table privileges. APP can execute only directory issue; worker can execute only redeem/context/claim/secret/publish/dispose. Internal selector/query/live/check/retirement helpers have no runtime execute grant.

SQL issue derives the actor, tenant, role and current account authority from protected PID/XID tenant facts. It requires a real unrevoked/unexpired WSO session matching that actor; current membership role; current accepted consent decision/time/version; selected identity/region/brand; managed session owner and READY state; active identity; USER generation; idle renewal state and renewal sequence; and existing identity/upstream/capability/connection credential authority. SQL independently validates the exact query schema even when APP directly invokes the issuer function.

The protected region/brand→profile/version/revision mapping currently reuses `tvt_flow_policies` from0010. Deployments must provision an enabled row for the trusted profile and consent version. Directory admission **does not read, compare or require the W06 HMAC key**; the mapping table's commitment belongs to W06 only. The worker additionally matches profile/version against its configured `DirectoryPolicy`. Policy revision/version/consent changes invalidate existing directory requests. This explicit table dependency avoids accepting caller-selected consent versions.

Issue privately creates and redeems one W05 profile ticket, preserving the managed credential primitive. Its delegated lease is stored only in the protected directory row. Outer requests bind exact method and canonical JSON query, plus actual session/current authority. Redemption and claim are atomic one-use transitions. A standalone W05 profile or W06 flow ticket cannot redeem directory authority. Current facts are checked at issue, redemption, before credential use, before network, and publication. Post-network checks include both current directory facts and the existing account credential primitive. Session, consent and expiry are rechecked after credential-lock waits, and the final publication UPDATE repeats that decision atomically. This closes the observed race where session/consent revocation committed during a credential wait. Token-invalid business codes fail with `DIRECTORY_REAUTHENTICATION_REQUIRED` and fence the same tenant/identity/generation locally; they do not revoke another user's token or silently retry.

Publication is one-use. Disposal removes the directory row and only its privately delegated profile ticket/capability. Issue retires at most128 expired rows and their delegated references per admission. SQL local capacity is128 unexpired pending requests globally and4 per actor. No upstream writes or durable business-write intent is needed for these reads.

## Budget, lifecycle and verification limits

`DirectoryAdmission.snapshot` reuses the existing `SecretCipher` envelope and the unchanged managed account secret/current-authority SQL functions. Its fixed directory-secret function first verifies the exact claimed outer request. The admission owns a `NullPool` engine, so no shared vault pool queue exists. The snapshot transaction ends before the real `DirectoryClient` invokes the sole `AccountClient`/`ProcessAccountTransport` transport. Python references are discarded on exits; guaranteed Python memory zeroing is not claimed. Post-network decryption is unnecessary. No SQL transaction or row lock is intentionally held across HTTPS.

The executor reserves one of32 owned reader slots before SQL redemption, then enforces4 readers per actor once protected identity is known. Pending SQL admission participates in close/custody; a late redemption cannot allocate a client after close. Each read gets one fresh owned `DirectoryClient`. The original budget follows SQL, snapshot, adapter and projection. Connect timeout, statement timeout and lock timeout are derived from remaining time; every blocking return is checked before later decryption, network or publication. Synchronous libpq connection waits have whole-second/minimum timeout granularity and cannot be forcibly cancelled by this Python boundary: a blocked call may return after the original budget, but it cannot dispatch or publish a late result. Guaranteed wall-clock termination of arbitrary driver/kernel blocking is not claimed. Close has a bounded aggregate deadline (default1000ms, maximum5000ms), also obeys any inherited remaining budget, and never restarts cleanup deadlines. Unproved cleanup/transport settlement permanently quarantines the executor and retains resource custody; it cannot return success or reuse a healthy slot. The result becomes terminal only after cleanup: custody release, settlement signaling, and the final shutdown/quarantine/deadline decision share one lifecycle lock. A close or original deadline that wins during SQL disposal discards the prepared view. There is no module-global process sweep.

Executed synthetic worker tests prove typed input/method binding, all six concrete serializers and safe projections, inherited budget propagation, transaction-before-network composition, post-network authority refusal, token-invalid identity fencing, actor concurrency, close/cancel and quarantine custody. Actual PostgreSQL tests use all nine roles retargeted to a unique marked database, guard source identity/owner/OID/revision, roundtrip0010→0011→0010→0011, compare parent rows/owners/function bodies/ACLs/policies, and verify source custody afterward. Actual real-DB worker tests replace only process I/O, assert no worker idle transaction at outbound dispatch, and revoke the WSO session inside that dispatch to prove publication denial. Synthetic transport is not vendor parity or an actual vendor HTTPS request.

No RPC/API/browser, APK/phone, real account/device, native media, Linux execution or CI dispatch was performed in this task. The ignored `W07-protected-directory-service-report.md` and `.superpowers/verification/directory-service/` retain exact commands, RED/GREEN output, private18 redaction checks, unique-database receipts, frozen source manifests and review limits. Previously recorded W05/W06/W07 evidence is preserved.
