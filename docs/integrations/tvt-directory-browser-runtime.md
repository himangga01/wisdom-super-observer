# Owned Windows directory browser runtime

Date: 2026-10-03. Source baseline: `756946ca73cff31d7ebb23141873088b470a96b4`. `MATCHED=0`; `release_ready=false`.

This explicit synthetic mode extends the existing account coordinator. It composes the real Next application, HTTPS FastAPI, restricted PostgreSQL web sessions and tenant admission, directory one-use tickets, verified shared mTLS bridge, `DirectoryAdmission`, `DirectoryWorkerExecutor`, `DirectoryClient`, and contained HTTPS transport. Only the identity provider and decoded upstream directory data are synthetic. Public directory API responses are produced by the published implementation.

The earlier account fixture used precreated sessions and Playwright cookie injection; it did **not** provide a signed issuer entrance. R77 authorizes a fifth file, `scripts/test-tvt-account/server.mjs`, so this mode can provide a normal signed login while preserving the existing coordinator and its custody. Default mode still uses the original W05 database and account scenarios.

## Root launch and stop contract

Root must review the source packet before executing these commands. Run from this worktree in the same PowerShell lifetime; retain `$directoryCoordinator` until it settles. Source the existing managed PostgreSQL environment silently. Do not provision, restart, migrate, reset, or rotate the shared source database.

```powershell
. .superpowers/runtime/postgresql17/env.ps1 | Out-Null
$directoryRoot = (Get-Location).Path
$directoryRun = [guid]::NewGuid().ToString('N')
$directoryFolder = Join-Path $directoryRoot "auth-state/tvt-account-$directoryRun"
$directoryState = Join-Path $directoryFolder 'context.json'
$directoryStart = [System.Diagnostics.ProcessStartInfo]::new()
$directoryStart.FileName = (Get-Command node).Source
$directoryStart.WorkingDirectory = $directoryRoot
$directoryStart.ArgumentList.Add('scripts/test-tvt-account/server.mjs')
$directoryStart.UseShellExecute = $false
$directoryStart.CreateNoWindow = $true
$directoryStart.RedirectStandardInput = $true
$directoryStart.RedirectStandardOutput = $true
$directoryStart.RedirectStandardError = $true
$directoryStart.Environment['WSO_TEST_ACCOUNT_BROWSER'] = '1'
$directoryStart.Environment['WSO_TEST_DIRECTORY_BROWSER'] = '1'
$directoryStart.Environment['WSO_TEST_W07_DIRECTORY_ACCEPTANCE'] = '1'
$directoryStart.Environment['WSO_TEST_W07_API_ACCEPTANCE'] = '1'
$directoryStart.Environment['WSO_TEST_W07_PARENT_SHA256'] = 'a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958'
$directoryStart.Environment['WSO_TVT_ACCOUNT_BROWSER_STATE_FILE'] = $directoryState
$directoryCoordinator = [System.Diagnostics.Process]::new()
$directoryCoordinator.StartInfo = $directoryStart
[void]$directoryCoordinator.Start()
$directoryStdout = $directoryCoordinator.StandardOutput.ReadToEndAsync()
$directoryStderr = $directoryCoordinator.StandardError.ReadToEndAsync()
```

The parent `auth-state` directory must exist. The unique `tvt-account-<run>` directory must not exist; the runtime creates it with private ACLs. Existing nine `WSO_TEST_*_DATABASE_URL` variables come only from the managed environment. Do not print the environment, private context, auth settings, session values, or certificate paths. `WSO_TEST_DIRECTORY_BROWSER` accepts only absence (W05) or the exact value `1` (directory).

Wait for the private `ready.json` sibling of `context.json` while checking the original coordinator has not exited. Startup retains the existing 60-second bound. Readiness means the coordinator verified HTTPS `https://localhost:3543/` with its own CA and observed its API/Next children. Root can read the safe readiness receipt privately; this is not Chrome acceptance.

Open `https://localhost:3543/api/auth/login` in direct GPT-controlled Chrome. The real Next OIDC flow redirects to the ephemeral loopback HTTPS issuer. Click **Sign in as synthetic directory staff**. The real callback validates state, nonce, PKCE, and RS256 signature, then the real API creates its protected PostgreSQL session and sets secure cookies normally. The browser returns to `/stores`; choose **Synthetic Directory Demo** if tenant selection appears, then open `https://localhost:3543/tvt/devices`. No DevTools cookie injection is needed.

Backend TLS and hostname verification remain enabled. The fixture certificates are private self-signed test certificates; no certificate is installed into a system/browser trust store. No security warning bypass or Chrome security change is authorized by this document. If normal Chrome navigation requires a trust handoff, root must report that concrete boundary and handle it with the user/tool before asserting browser success.

Stop cooperatively through the original handle:

```powershell
$directoryCoordinator.StandardInput.WriteLine('close')
$directoryCoordinator.StandardInput.Flush()
$directorySettled = $directoryCoordinator.WaitForExit(130000)
if (-not $directorySettled) {
    throw 'Cleanup reporting deadline exceeded; retain the original coordinator handle and inspect safe receipts.'
}
if ($directoryCoordinator.ExitCode -ne 0) {
    throw 'Owned coordinator reported failure; inspect safe receipts.'
}
if (Test-Path -LiteralPath $directoryFolder) {
    throw 'Private runtime state remains; inspect owned cleanup receipts.'
}
```

Alternatively, create the private `shutdown.json` sibling; the original Node coordinator observes its existence. Never kill a process tree, select a process by port, reuse a foreign listener, or delete the private folder to simulate cleanup. Next retains its existing 20-second budget; Python retains its 100-second reporting budget within the 120-second coordinator deadline and the 130-second observer margin. An overrun leaves the custodian holding the original child handles until actual settlement.

## Synthetic scope and six interactions

The actor is a newly seeded STAFF principal whose random subject is restricted to the synthetic issuer. The selected tenant is **Synthetic Directory Demo**; **Synthetic Other Tenant** has no seeded linked directory identity. The TVT identity is newly generated and has only the existing account-read grants. Its USER and P2P values are invented and encrypted with the same private random file key used by the real worker. No genuine account/device data is consumed. The trusted region/brand is `test` / `SuperLivePlus`, profile `browser-fixture`, consent `fixture-v1`. Current startup terms/privacy references are retained and `/tvt/devices` is explicitly enabled. Accepted consent and the enabled directory policy are seeded only inside the guarded owned database.

| UI interaction | Real readonly source path | Expected synthetic observation |
| --- | --- | --- |
| **기기 목록 조회** | `/resource/device/list` | Synthetic directory recorder; opaque SN `synthetic:opaque:SN-7`; string total `1` |
| Select that device, **채널 목록 조회** | `/resource/channel/list` | Native indices `7` and `42`, never array positions |
| **기기 상세 조회** | `/resource/device/detail` | Name value, model null, version missing, shape-only account reference |
| Select channel 7 or 42, **채널 상세 조회** | `/resource/channel/detail` | Selected native index preserved; index 42 name null |
| **보낸 공유**, then **보낸 공유 조회** | `/resource/channel/share/to-other/list` | Synthetic recipient and sent-specific fields |
| **받은 공유**, then **받은 공유 조회** | `/resource/channel/share/from-other/list` | Synthetic owner and received-specific fields |

Record desktop/mobile screenshots, the absence of `DIRECTORY-SENSITIVE-MARKER`, retained missing/null/value distinctions, and absence of live/control/sharing-write authority. Unknown password markers and object contents exist only at the synthetic upstream boundary and are discarded by the real projection. These records never grant media, PTZ, Talk, ownership or sharing operations.

To test a real refresh failure, wait for all requests to settle, then write the following bounded UTF-8 JSON to the private `directory-control.json` sibling (never an API endpoint): `{"op":"upstream","deny":true}`. Wait for `directory-control-applied.json` containing `{"deny":true}`, then click **기기 새로고침** after a successful list. The upstream actually returns HTTP 503 through the real transport/API; the UI should show its error while retaining the prior observation. Restore with `{"op":"upstream","deny":false}` and wait for the matching acknowledgement. No public DTO is fabricated. The ordinary session-rotation control is refused in directory mode; use normal logout/login for a new signed session.

## Source, custody and verification boundaries

Before opening a database, `verify_directory_source_gate` checks exact activation, the accepted raw parent0010 hash, and all fixed19 sources through the strict approved local composition receipt (or existing approved CI fixture on its separately authorized platform). It neither rewrites receipt hashes nor accepts computed live source identities. All existing W05 canonical pins and migration raw aliases remain intact.

The accepted `directory_database` generator preserves Windows `wso_test` / OID16384 / revision0003a /36-table source rows and owners, creates only a unique marked owned database, verifies its0010↔0011 roundtrip, and checks name/OID/owner/comment before drop. Its source-after comparison and cleanup receipts remain authoritative. Directory browser mode does not run broad/native suites.

The original accepted worker fixture still owns its exact process, certificates, upstream and drain/reap receipt. A scoped adapter adds only the optional private directory profile and seeds the encrypted identity before starting that worker. The shared `_Service._execute` admission counter also covers directory RPC methods. API, issuer and worker activity use the same private gate; no gate/SQL transaction spans network work. New HTTPS source/issuer connections have bounded handshakes and request reads, joined request threads and retained original listener/thread references. The issuer bounds one-use codes to 60 seconds and16 pending codes; signed sessions expire at the real API's verified token limit. The issuer accepts only the fixed callback/client and fixed synthetic actor.

FastAPI receives only APP/IDENTITY/SESSION role URLs, the old four bridge client settings, and its ordinary auth/startup configuration. Its account and directory worker/decryption constructors are forbidden. The optional directory profile and key stay worker-only. The only API CA override is the owned issuer CA; Next uses its existing owned CA at process startup. No HTTP TLS bypass, hostname override or production auth modification is added.

New receipts and source snapshots go to `W07-directory-browser-runtime-evidence` in the established SDD directory. The original W05 packets stay historical. Private state/certificates are removed after API, issuer, worker and upstream teardown; unique database absence and source equality are verified by the accepted generator. Safe receipts record source hashes, process exit/drain, decoded path names/counts, encrypted-row counts and migration revision. Root must check these actual receipts after running.

The implementation author ran offline host contracts, actual source serializers/projections with in-memory HTTP handler calls, signed issuer state checks, isolated Node configuration checks, and scoped static checks only. No database, listening server, real browser, CI, vendor account, APK or native replay was executed by this author. Offline contracts do not establish real startup, browser acceptance or cleanup. Root owns source review, actual Windows launch, direct Chrome interactions and final cleanup verification.

## 2026-10-04: login publication timing and trusted local HTTPS

Root's direct normal signed login reached `/stores`, the seeded STAFF store and accepted consent, but `/tvt/devices` showed no linked TVT account. Both issuer and seed used the same fixed STAFF actor. The account publication occurred around 03:26 KST; login occurred around 03:32 KST. Migration 0007 gives the account-read identity grant, upstream observation and capability snapshot five minutes from publication. The unchanged startup account query excludes expired authority. Persistent consent and store membership therefore remained visible after the startup-seeded TVT account had disappeared from that query. This finding is based on current source and root's observed timestamps/UI; this author performed no live database query.

Fix1 keeps policy, consent, tenant names and membership seeding at startup, and publishes a fresh synthetic TVT identity only after a valid one-use issuer code exchange passes client, redirect, expiry and PKCE checks. It issues the real protected account-login ticket using the fixed actor's **current signed issuer**, fixed STAFF subject and fixed tenant; the historical `https://w02.test` fixture helper cannot resolve that actor after its issuer binding changes. The unchanged `TokenVault.redeem/publish` encrypts the invented USER/P2P values with the owned worker key and starts the original five-minute authority lifetime. Production TTL, SQL, filters, account API and worker paths remain unchanged. Invalid, expired and replayed issuer exchanges do not publish. A refused publication prevents signed tokens from being returned, and the one-use code remains consumed.

The publication callback runs within the original issuer API admission. It freezes new API/worker admission and requires exactly that one issuer entry and no active worker entry, then writes the newly published identity ID into the private context. It releases the freeze on every outcome. No request can select actor, tenant, profile, key or origin for the callback. Each valid subsequent normal login creates a fresh synthetic identity; prior identities retain their normal expiry and are not resurrected or force-deleted. Root should reload bootstrap and select the current context's identity after login, completing the six interactions within its normal authority lifetime. This is fixture composition, not real vendor login or a production renewal strategy.

The user explicitly requested permanent warning-free localhost development HTTPS on 2026-10-04. Root owns `scripts/dev/setup-local-https.ps1`, which installs the checksum-pinned official mkcert tool in a private dedicated directory, generates a localhost leaf and private local CA, and installs that CA in `CurrentUser/Root`. Root separately verified normal Windows chain validation and direct Chrome navigation on both localhost and 127.0.0.1 without browser validation flags. These are root-provided execution results; the implementation author reviewed the script read-only and did not install or trust certificates.

For that reviewed setup, add this option to the root coordinator environment before launching:

```powershell
$directoryStart.Environment['WSO_TEST_BROWSER_TLS_DIR'] = 'C:/wso-private/wso-local-dev-tls/server'
```

The explicit directory must contain exactly the required inputs `ca.pem`, `server.pem`, and `server.key`; other inputs, including the CA private key, are never copied. The runtime validates bounded PEM inputs, absolute non-reparse source/owned destination directories and files, CA/leaf validity, CA and leaf signatures, BasicConstraints, leaf/key match, serverAuth and SANs localhost, 127.0.0.1 and ::1. It validates all inputs before copying only those three files into its already-private coordinator directory. Optional TLS without explicit account fixture activation, invalid material or missing inputs fails closed. With the option absent, the original `certs(folder)` behavior remains for CI. The Node coordinator already forwards the option to Python; no parent change is needed.

Next, API and synthetic signed issuer use that coordinator leaf and CA. The accepted RPC worker's separate certificate directory and bridge mTLS environment remain unchanged. HTTPS peer and hostname validation, secure cookies, OIDC state/nonce/PKCE/signature checks, authority expiry, admission, ownership and cooperative custody cleanup remain enabled. The source does not install trust or suppress Chrome warnings; trust setup is the separately user-authorized root action.

Offline causal RED observed missing late publication and failure to block token issuance; scoped GREEN then passed the login publication cases. The TLS option likewise had a missing-helper RED, then passed valid-copy, wrong-key/signature/expiry/SAN/PEM/path/activation rejection and unchanged-default cases. Final focused account/directory host verification passed **81 tests**, with scoped Ruff and format checks passing. This author ran no listening server, protected PostgreSQL, browser, vendor, native, CI or broad suite. The publication timing test is a controlled offline seam model; actual SQL grant freshness and the six directory browser interactions still require root's fresh runtime.

Root cooperatively stopped the preceding run and retained its failed exit: runtime's source-equality guard correctly detected concurrent edits to `windows_socket.py` and `windows_socket_worker.py`, while children settled and private state was removed. That proof drift is separate from account expiry. Root must coordinate a stable source window with the native owner for the new run; the source guard remains unchanged. Fix1 freezes changed3/current5 and original source/report preimages in `W07-directory-browser-runtime-Fix1-evidence`. The shared canonical analysis remains `docs/service-analysis.md`; root records actual browser, cleanup and acceptance outcomes there. `MATCHED=0`; `release_ready=false`.

## Fix2: optional leaf BasicConstraints — 2026-10-04

Root's fresh trusted-TLS runtime failed before Next/browser because mkcert 1.4.4's valid end-entity leaf omits BasicConstraints. Read-only inspection of the actual public certificates confirmed CA OIDs `2.5.29.15/19/14` with CA=true, and leaf OIDs `2.5.29.15/37/35/17` with BasicConstraints absent. Requiring that extension on the leaf was an implementation mistake. [RFC 5280 section 4.2.1.9](https://www.rfc-editor.org/rfc/rfc5280#section-4.2.1.9) gives an absent extension the same non-CA interpretation as an unasserted cA flag. Fix2 accepts that leaf shape and still rejects an explicit CA=true leaf; the issuer CA must retain explicit CA=true. Signature, validity, private-key match, SAN, serverAuth, path bounds and activation checks remain unchanged.

A generated inert leaf without the extension reproduced the failure (RED: 1 failed/1 passed); after the scoped correction all 12 affected TLS/default cases passed. The actual public certificate hashes/OIDs are safe shape evidence only; no real private key was copied into the packet. The accepted Fix1 packet remains preserved. Root's failed run `75dacc180db549edbc5aa86dca24bb2e` settled with owned state/database removed and no browser acceptance. Fix2 still requires independent source review and a fresh root runtime/browser run; the implementation author executed no server, protected database or browser. `MATCHED=0`; `release_ready=false`.
