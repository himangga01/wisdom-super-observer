# Protected account registration and recovery worker

Analysis and implementation date: 2026-10-02. Source baseline:
`08b3ffd5c5d56d6f26d5ab4b6e90459f637579ac`. This service composes the reviewed
W06 prelogin adapter and public models with current PostgreSQL authority.
APK-derived source evidence is in [tvt-account-flows-source.md](tvt-account-flows-source.md).
No real account registration, password recovery, device command, or handset
comparison is acceptance evidence for this implementation. `MATCHED=0` and
`release_ready=false` remain in force.

## Composition interface

`wso_api.tvt.flow_service.AccountFlowWorker` is a separate protocol from the
existing account worker. `AccountFlowWorkerExecutor` implements eight methods:
`start`, `state`, `existence`, `image`, `issue_code`, `register`, `recover`,
`cancel`. Each takes `(ticket, body, *, deadline_ms, correlation_id)` and returns
the exact base `AccountFlowView`. The request model is respectively
`AccountFlowStart`, `AccountFlowReference` for state/existence/image,
`AccountDynamicCodeRequest`, `AccountRegistrationSubmit`,
`AccountRecoverySubmit`, and `AccountFlowCancel`.

The later RPC factory must inject all four constructor arguments:

* `FlowAdmission(worker_url, key_commitment)` using the existing
  `wso_connection_worker` URL and the lowercase SHA-256 hex commitment of the
  configured binding key. Only that commitment enters SQL, never the key.
* The approved tuple of `AccountEndpoint` values, including region, brand,
  origin, language, country, and customer app ID.
* An exact selection mapping to `FlowEndpointConfig(default_domain,
  terminal_id="")`. `default_domain` is the trusted, unhashed APK configuration
  value. It is independent of `AccountEndpoint.customer_mark`; the adapter
  performs its required MD5. An explicitly present empty default_domain is
  valid: register sends MD5(empty), while issue_code omits customerMark. A
  missing mapping is denied. Browser URLs and redirects cannot supply it.
* One stable, private 32-byte binding HMAC key, shared across worker instances
  and restarts. Missing configuration denies construction. Provision this via
  the existing deployment secret lifecycle. This change creates no secret
  store, environment URL, generic decrypt grant, or login role. A worker whose
  actual key commitment differs from protected policy/flow metadata denies
  admission before private state construction or any upstream dispatch.

The API must authenticate the real T03 session and CSRF as appropriate, enter
the existing protected tenant transaction, and call
`FlowTicketIssuer(session, remaining).issue(session_digest, operation, body)`.
`session_digest` is `token_digest()` of the authenticated request cookie,
computed by the server; it must never be a body field. Commit ticket issuance
before RPC. Enclose issuance, dispatch, worker execution and response handling
in the caller's original total deadline; each worker call supports 1–20000 ms
and composes with `token_budget`/`remaining_budget` rather than resetting it.
Never expose tickets or worker leases to the browser.

The API/RPC/main/React wiring is deliberately a separate integration task.
This module does not register routes or construct a default permissive worker.

## SQL authority and policy provisioning

Revision `0010_tvt_account_flows` follows reviewed `0009_asset_read_denial`.
It owns exactly four private tables: `tvt_flows`, `tvt_flow_tickets`,
`tvt_flow_intents`, and `tvt_flow_policies`. All are owned by the existing
`wso_account_owner`, with FORCE RLS, explicit owner/migrator policies and no
runtime direct-table grants. Named SECURITY DEFINER functions have
`search_path=pg_catalog`, closed execution ACLs and fixed lock bounds. The app
can only issue; the existing worker can redeem, inspect, claim and publish.
Private helpers are not executable by runtime roles.

The only additional reads for `wso_account_owner` are SELECT and named
`flow_authority_read` RLS policies on `public.web_sessions` and
`wso_private.tvt_user_consents`. Existing app, worker and web session direct
table denials remain. Downgrade removes these additions and all owned tables
and functions without deleting original auth, account, consent or tenant rows.

There is no existing SQL region/brand-to-consent mapping. Deployment must
provision `tvt_flow_policies` through the migrator with an exact region, brand,
startup profile ID, required consent version, 32-byte key commitment, positive policy revision and
`enabled=true`. Empty/missing/disabled policy denies. Increment the revision
when changing policy. Current enabled mapping, exact profile/version/revision,
and the original accepted consent decision timestamp must still match at every
authority check. Browser-supplied role or consent booleans have no effect.

Every issue, redemption, context read, operation claim, use and publication
checks current membership/role, exact actor-owned unrevoked unexpired WSO
session, selection and purpose. Tickets bind flow ID and generation. Changing
tenant, actor, selection, purpose, session, membership role, consent or policy
invalidates them. A new WSO session never adopts an old flow. Flow lifetime is
at most 300 seconds and no longer than the WSO session; operation tickets are
at most 30 seconds. State/cancel tickets can inspect a locally expired flow
while the same WSO session and other authority remain current.

No transaction spans network I/O. A claim commits before the adapter runs;
publication uses a new transaction and rechecks current authority. Revocation
after an admitted write prevents public publication and preserves uncertainty.
Claim and publication also compare ticket expiry with `clock_timestamp()`
after acquiring the flow row lock, before any ticket/flow/intent mutation.
Expiry during that wait denies a claim without consuming the final or creating
a witness, and denies publication without settling its UNKNOWN hold or advancing
generation. An operation budget that remains available cannot extend a ticket.

## Private lifecycle and safe projection

The private registry permits at most 128 active slots and four per tenant/actor.
Per-flow locks reject overlap. Expired unlocked slots may be settled and
discarded; active or uncertain final work is never silently evicted. Closing,
terminal settlement and local invalidation remove the owned private instance
and its account, key and native challenge references after safe settlement.
Unproved native resources stay owned in explicit quarantine and stop new
admission, rather than being silently discarded.

The concrete executor also exposes the local lifecycle method
`close(*, deadline_ms=1000) -> None` (1–5000 ms). The wire protocol remains eight
operations. Close immediately stops admission and clears owned HMAC/config
references. Native flow.close is invoked once per slot, including cancel and
concurrent shutdown races. At most128 daemon cancellation tasks avoid serial
per-flow waits; one common deadline covers cancellation and active operation
settlement and intersects an existing token budget. Repeated close cannot
restart that deadline or launch new cleanup tasks. If settlement is unproved,
it raises fixed ACCOUNT_QUARANTINED and retains pending ownership. The RPC
factory must retain a quarantined executor and dispose its separately owned
FlowAdmission/vault independently; executor.close does not assume ownership
of those injected services. No late result is published after shutdown.

The existing `PreloginAccountFlow` serializes native requests. Phone bindings
use `country_code + '+' + local_number`; email bindings remain distinct.
Runtime RSA, native `idCode`, account, password and verification code stay in
the private instance or immediate exchange, never in SQL. `project_image`
validates private media before the worker supplies bounded Base64 with a fresh
local challenge UUID and generation. Image text can only use the exact current
pair; replacement or clearing invalidates previous pairs before dispatch.

Existence requires a decoded strict boolean. Missing or null values are a
protocol failure. Recovery business 1005 is a failure, never IMAGE_REJECTED.
CODE_SENT carries `resend_wait_seconds=120`, an explicit local resend policy,
not upstream expiry evidence. Completion requires the adapter's decoded HTTP
2xx/business 200 result and returns to login; it creates no TVT identity or
session. Outputs contain no original business text, body, native image ID,
SQL handle, account, code, password or key. Request IDs must be canonical and
are preserved exactly. Validation failures are reduced to fixed codes without
raw Pydantic input/error serialization.

## Final intent and uncertainty

Before final register/reset I/O, SQL commits a consumed final state and a
durable intent witness. Its discriminator is a server HMAC-SHA256 over a
versioned canonical JSON tuple containing tenant, purpose, account mode and
canonical binding. Actor, flow UUID, WSO session, password, dynamic code and
browser idempotency values are excluded. Email case variants conservatively
share one intent; native wire spelling remains unchanged. Region/brand changes
cannot bypass a hold for the same tenant/account/purpose.

Unknown transport, non-2xx HTTP, protocol, deadline or cancellation outcomes
retain UNKNOWN_OUTCOME and cannot automatically replay. A worker restart or
lost private registry cannot reconstruct keys or challenges. A final witness
does not expire merely because its flow, ticket or WSO session does. No release
endpoint or invented reconciliation exists. Future reconciliation must use
authoritative upstream evidence, explicit product policy and separate audited
authorization before resolving an uncertain hold. Key commitments are bound
to policy, flow and final witness, and every worker capability call supplies
the configured commitment for independent SQL comparison. A protected policy
trigger rejects inserting/replacing a commitment while any unsettled witness
uses another key. It serializes with initial final claims through one short
transaction advisory lock. Current authority additionally denies a flow when
an unsettled witness exists under another commitment, including flows created
before rotation on another selection. Thus a different worker key, new policy
or new selection cannot bypass an old uncertain hold. Rotation requires
settlement/reconciliation of all old pending intents first; this is a global
conservative deployment boundary, not a per-tenant bypass. Settled witnesses
retain their original commitments and consumed flow history after rotation.

The initial submitted phase is already UNKNOWN_OUTCOME, so the unique active
hold covers the entire admitted exchange. Validated COMPLETE or a known HTTP
2xx business rejection settles that hold while preserving the original
consumed flow and witness. A later legitimate recovery may then start a new
intent. Business 404/DC hints remain uncertain and cannot settle a hold. The
only local exception allowed to settle after admission is the reviewed
adapter's `FlowError(FLOW_KEY_MISSING)`: its sole raise site is the RSA
precondition before `_client._run` and before request construction or transport.
A focused real-adapter test proves zero dispatch on that branch. A generic
exception label or timeout is never evidence of zero I/O.

Each final witness is keyed by its flow ID; a partial unique index on the
intent digest applies while outcome is UNKNOWN_OUTCOME. Settling the outcome
leaves admission time, generation, flow, tenant, purpose, commitment and digest
in the original witness. A claimed operation with a lost registry is projected
as UNKNOWN_OUTCOME from durable busy metadata, including a lost read exchange.

## Verification limits and next integration

Focused synthetic tests execute the real private flow, native parser and safe
projection with substituted SQL and isolated upstream boundaries. These prove
source composition and fixed local policy, not actual upstream interoperability.
The separate guarded PostgreSQL module creates only a uniquely named owned
database, checks its exact OID/owner/comment before dropping it, retargets every
role URL, and compares source `wso_test` OID/owner/revision/content before and
after. It is disabled until root supplies the reviewed parent revision hash.
Executed counts, native exit codes, roundtrip results and exact frozen hashes
are recorded in the W06 protected service report/READY packet. The reviewed
parent gate was cleared against SHA-256
`3a2fc52bb33a86058d5f13d36f6112986f1ef4117032c64cc268e2e88f61572e`.
The historical full checkpoint passed 64 tests:40 synthetic worker tests,22 real PG
authority/composition cases,one revision check and the affected offline SQL
emission check. Upgrade/downgrade/reupgrade preserved parent rows, owners,
function bodies, ACLs and policies. Source wso_test OID16384/ownerpostgres/
revision0003a and all36 table hashes matched before/after; owned DB cleanup was
verified. Ruff, formatting and strict targeted mypy pass. The earlier54-pass
checkpoint and its two equivalent receipt-only lint edits are preserved in the
report; that64-pass execution includes the RPC lifecycle hardening. Independent
review then found missing post-lock ticket-expiry checks. Fix1 reproduced both
expired paths against real PostgreSQL (2 failed,2 valid controls passed), added
the two post-lock guards, and passed14 affected PostgreSQL cases plus the
offline DDL check. These cover expired/valid lock-wait paths and current
authority/one-use/revocation/deadline behavior. Both Fix1 DBs were removed and
source36 hashes preserved. Ruff/format pass for the changed migration/test;
unchanged worker/core/unit bytes retain their prior verification. The full64
suite was not repeated for this narrow SQL correction. Fix1 evidence is separate
from the preserved original packet and awaits the same reviewer's acceptance.

SQL failures are reconstructed outside the contextmanager call boundary so
private SQL exception objects do not survive in public exception context.
Deadline checks also run after terminal/state projection and local cleanup;
late output is withheld even when no upstream operation was needed.

Remaining acceptance includes RPC transport and factories, API/CSRF/tenant
composition, React lifecycle integration, live comparison against the actual
APK, and a product decision for authoritative reconciliation of uncertain
final intents. Service-source tests do not claim these later stages complete.
