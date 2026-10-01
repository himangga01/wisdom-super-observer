# Account runtime deployment and development proof

The API application lifespan creates one `create_account_worker_client()` from the bridge base package and publishes it as `app.state.tvt_account_worker`. Application construction performs no RPC connection. Shutdown clears admission through the app state and calls the owned client's close once. Close is isolated in a daemon thread and the lifespan waits at most one second; a stuck dependency can leave that daemon thread pending until process exit. Asset admission and database providers still receive their existing cleanup, including startup failure after acquisition. Operational process supervision remains required.

The API requires only these account RPC settings:

| Setting | Meaning |
| --- | --- |
| `WSO_TVT_BRIDGE_ENDPOINT` | Trusted RPC DNS hostname or IP plus port; no HTTP URL or custom resolver |
| `WSO_TVT_BRIDGE_CA_FILE` | CA PEM used for ordinary worker certificate and hostname verification |
| `WSO_TVT_BRIDGE_CLIENT_CERT_FILE` | API client certificate PEM |
| `WSO_TVT_BRIDGE_CLIENT_KEY_FILE` | API client TLS private key PEM |

Missing, incomplete or rejected client configuration leaves the account worker absent and routes return the canonical `ACCOUNT_UNAVAILABLE` 503 after their existing authentication, Origin and CSRF checks. A configured channel's transport uncertainty retains the bridge `UNKNOWN_OUTCOME` behavior. Configuration is read at application startup; restart the application after changing it. Existing `/health/ready` behavior is unchanged and must receive deployment readiness checks; this wiring does not add an upstream account health probe or login retry.

Run the separate worker with `python -m wso_tvt_bridge` from an installation selected as `wso-tvt-bridge[worker]`. The API selects the bridge base dependency. The bridge base requires contracts, core, grpc, protobuf and cryptography; only its optional worker extra requires the API package containing `AccountWorkerExecutor`. There is no mandatory package dependency cycle.

The worker additionally requires `WSO_TVT_BRIDGE_BIND`, `WSO_TVT_BRIDGE_SERVER_CERT_FILE`, `WSO_TVT_BRIDGE_SERVER_KEY_FILE`, `WSO_TVT_BRIDGE_CLIENT_SANS_JSON` (an explicit JSON array of permitted client SAN identities), its CA file, `WSO_WORKER_DATABASE_URL`, `WSO_CONNECTION_KEY_FILE`, and `WSO_TVT_ACCOUNT_PROFILE_FILE`. The worker alone constructs the account executor, TokenVault and saved-token key provider. Keep these account worker settings and protected key/profile mounts out of the API deployment. The API still has pre-existing T04 connection-write encryption configuration and transitive imports of account implementation modules; this change does not relocate those modules or prove OS privilege isolation. The API's client TLS key is intentionally a separate API-owned credential.

The profile writer uses the same `load_account_endpoints` validator as worker startup. Run it from the project environment, with a pre-existing deployment-owned directory:

```powershell
python scripts/dev/write_tvt_account_profile.py `
  --root C:/deployment/account-worker `
  --output-name account-profile.json `
  --endpoint REGION BRAND HTTPS_ORIGIN LANGUAGE COUNTRY APP_VERSION
```

Replace every uppercase argument with explicitly selected trusted deployment values. Repeat `--endpoint` for additional region/brand pairs. Optional `--customer-app-id` and `--customer-mark` apply to every entry in that invocation and are omitted from JSON when empty. There is no default origin, region, brand, locale or version. HTTPS origins must use the existing transport canonical form, optionally ending in `/mobile_v1.0`. Browser URLs and DC redirect hints are not deployment authority. The writer performs no network request.

The output is deterministic UTF-8 JSON, bounded at 65,536 bytes. Duplicate region/brand pairs, control characters, invalid origins and unsafe targets are rejected. The output must be a dedicated JSON filename immediately under the explicit root. Existing symlinks/reparse points, hard links, directories, secret/key/environment filenames and arbitrary JSON documents cannot be replaced. `--overwrite` is required for replacing an existing validated account profile. Installation is atomic using a same-directory temporary file and either an exclusive hard link or replace. Keep the root under a trusted deployment identity; concurrent hostile mutation of its directory entries is outside this CLI's operating model.

Source-derived field names and request behavior come from the implemented APK account protocol and existing session contracts, not a vendor SDK inference. CLI validation establishes only that the current worker accepts the profile structure. It does not establish server availability, region correctness, DC acceptance, TLS deployment readiness or APK/device parity.

The opt-in `tests/integration/test_tvt_account_rpc.py` fixture requires `WSO_TEST_ACCOUNT_RPC_RUNTIME=1` and the existing guarded development PostgreSQL role URLs. Without explicit activation it skips. It creates a uniquely named database on the verified existing cluster, upgrades exactly to accepted `0007_tvt_account_sessions`, and checks its name, OID, owner and ownership comment before dropping only that database. It never upgrades an unreviewed migration head or resets the source database. Source table contents and database identity are checked before and after.

The fixture executes real T03 sessions and SQL tickets, the API lifespan client, a separate mTLS worker created by `create_server_from_environment`, concrete AccountWorkerExecutor/TokenVault/AccountClient, and real isolated HTTPS transport children against a local synthetic HTTPS server. The server decodes and validates all six operations. The only upstream trust seam is an explicitly approved fixture bootstrap wrapper around `ProcessAccountTransport._environment`: it preserves the actual sanitized child environment and adds exactly `SSL_CERT_FILE` for the owned ephemeral test CA. No TLS checks, hostname checks or RPC SAN checks are disabled, and no operating system CA store is modified. Wrong CA and wrong hostname cases fail before sending an HTTP request. Default production child CA selection is not verified as deployed by this fixture.

The development proof covers login, account profile projection, nonrotating USER refresh, logout while retaining WSO authentication, image challenge ownership and single consumption, revoked tickets, and cancellation after upstream admission followed by drained worker shutdown with no late SQL session publication. Synthetic fixtures are not upstream acceptance. `MATCHED=0`; `release_ready=false`. Linux production supervision and certificate rotation, deployment OS users/mount ACLs, actual APK/device/native behavior, avatar retrieval, frontend parity and later W06 work remain separate gates.

The FastAPI acceptance client runs in the fixture coordinator interpreter, which also provisions the owned database and therefore holds test administrator credentials. Forbidden-construction guards verify the API code does not construct account worker capabilities; this harness does not establish a separate operating system identity for the API. Dedicated API/worker identities and mount permissions remain required deployment verification.
