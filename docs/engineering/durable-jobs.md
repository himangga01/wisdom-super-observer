# Durable jobs

T05 supplies the shared job execution foundation for later service domains.
PostgreSQL owns requests, results, cancellation, execution fences and redispatch;
Celery/Valkey delivers references at least once. A broker acknowledgment is not
domain completion. Actual Linux recovery acceptance is pending; current local
PostgreSQL evidence and the earlier broker persistence smoke are distinct.

## Persistence and authority

Migration `0003_jobs` follows `0002_connections`. Enqueue validates its kind and
scope, computes a canonical payload digest, and commits the job, connection
snapshots, outbox and minimal dispatch projection together. Same scoped
idempotency key with a different payload conflicts. Tenant jobs need no store;
store jobs require a real active authorized store.

| Role | Boundary |
| --- | --- |
| `wso_app` | Existing protected tenant context; authorized enqueue, creator/current-owner status/items and cancellation functions |
| `wso_dispatcher` | Functions-only projection claim/ACK/nack; cannot read job payloads, memberships or credentials |
| `wso_dispatch_owner` | NOLOGIN owner of the dispatch projection/functions; no job or credential table privileges |
| `wso_job_worker` | Persisted single-job PID/XID context, generation/lease fences and current actor authorization; no generic tenant context or ciphertext access |
| `wso_job_owner` | NOLOGIN definer owner with only the metadata/function privileges needed for protected job authority |
| `wso_connection_worker` | Separate committed job-bound secret capability redemption/use; trusted callback boundary from T04 |

Every tenant/private job table uses forced RLS. Caller-set tenant GUCs are not
authority. Sorted authorization/connection/store locks stay held through each
bounded effect. Membership/assignment changes, tenant epoch, inactive store,
connection replacement/revocation, cancellation and stale execution generations
prevent later effects. A current role/assignment re-added later does not revive
the queued authority removed by a lifecycle change.

## Delivery and outcomes

The six-field broker reference contains only schema version, job/outbox/tenant
IDs, kind and dispatch generation (wire field `lease_generation`). Claim issues
a separate execution generation and token. Payloads and secret handles are absent.
The dispatcher publishes on the protected DB queue and refuses registry queue
drift. Application/job services compare all registered security metadata with
the database before use.

Local effect and COMPLETED inbox state commit in one database transaction.
PROCESSING remains reclaimable after rollback/expired lease; only COMPLETED
suppresses execution. Publisher ACK retains a watchdog until a terminal or
blocked database outcome, so an empty broker can be rebuilt from PostgreSQL.
Bounded retries/backoff use database timing settings inaccessible to runtime
roles. Stale attempts cannot heartbeat, record items or complete a new lease.

External writes persist a submitted intent before calling the external handler.
After a lost response/process, only reconciliation may run. Unresolved or
exhausted reconciliation remains NEEDS_USER_INPUT/UNKNOWN_REMOTE_STATE and
blocks another write. Cancellation preserves submitted uncertainty. This is
not an exactly-once guarantee for an external service. PARTIAL requires actual
mixed item outcomes; unavailable handlers fail explicitly.

The supported secret primitive flow is committed claim → fresh 30-second
one-use job-bound handle → separate secret callback → fenced completion.
Nested secret operations inside a held job step are rejected before SQL.
Generic credential-using handlers currently fail CAPABILITY_UNSUPPORTED; a
future domain executor must implement the separate workflow. Production
KMS/key rotation and real vendor execution remain pending.

## API and reserved kinds

Authenticated routes are GET `/api/v1/jobs/{id}?tenant_id=...`, GET
`/api/v1/jobs/{id}/items?tenant_id=...&limit=1..100&cursor=...`, and POST
`/api/v1/jobs/{id}/cancel?tenant_id=...`. Cancellation requires exact-origin
CSRF. Status/items require creator or current owner and active store access
when applicable. Inaccessible IDs return 404. Responses and errors are
no-store with Vary: Cookie; payloads, secret/lease tokens and transport details
are absent. Cursors are bound to the requested job.

IMPORT (TENANT) and REGISTRATION (STORE) are reserved prerequisite schemas,
with no production handlers or public job-creation endpoint. Their presence
does not implement photo intake, device registration or TVT account login.
Owning domain APIs enqueue validated requests inside their domain transaction.

## Runtime and checks

Configure explicit `WSO_BROKER_URL` (Redis/Valkey),
`WSO_DISPATCH_DATABASE_URL` (dispatcher) and `WSO_JOB_DATABASE_URL` (job worker).
No administrator URL or guessed AMQP endpoint is used by these processes.
The broker must have an explicit Redis/Rediss hostname and a valid port when
specified. Startup rejects conflicting `CELERY_BROKER_URL`,
`CELERY_BROKER_READ_URL` or `CELERY_BROKER_WRITE_URL` values and any nonempty
`CELERY_RESULT_BACKEND`. Matching broker overrides and empty overrides are allowed;
runtime environments must remain stable after startup. Both processes share these
checks and disable result storage. Dispatch requires only its own database URL.
Run dispatcher with `python -m wso_core.job_runtime dispatch`; run one worker
per intended queue with `python -m wso_core.job_runtime worker --queue <queue>`.
Allowed queues are wso.default, wso.browser, wso.cli and wso.media; use separate
worker pools for isolation. Production defaults are JSON-only, late ACK,
worker-loss rejection, prefetch one, task soft/hard limits 25/30 seconds and
transport visibility 3,600 seconds. Handlers must bound their I/O and transaction.

The local PostgreSQL verifier requires all eight explicit test-role URLs or
loads the ignored managed runtime when none are supplied. Partial configuration
fails. Ordinary offline tests may skip absent PG; explicitly selected PG rejects
integration skips. Windows does not establish Celery process acceptance.

`-WithJobBroker` requires Linux CI and `-WithPostgres`; its JUnit checker requires
every one of the ten frozen recovery cases with zero skips/errors/failures.
Fixtures use owned loopback-only containers and actual elapsed lease/transport
restoration, not eager tasks, in-memory queues, edited timestamps or fake ACKs.
See [Linux CI](linux-ci.md) for the recorded runtime digests and actual run status.
