# Asset parent read denial

The protected download functions now return SQLSTATE `P0002` when the live
asset lock finds an expired asset or an unavailable parent. The existing asset
error translator exposes this as HTTP 404 `ASSET_NOT_FOUND`. This covers ticket
redemption and download lease revalidation, including a parent that changes
state after the lease was admitted. No read manifest or new lease is returned
for a denied redemption.

Migration `0009_asset_read_denial` changes only those two read functions. It
wraps their calls to `wso_asset_lock(..., true)` in a narrow exception block.
That lock raises `55000` for child expiry, parent state other than `READY`, or
parent expiry. Its authorization failures still retain their own SQLSTATEs.
The later `wso_asset_manifest` lease check can also raise `55000`; this remains
HTTP 409 `ASSET_CONFLICT`, as do upload and write state conflicts. The shared
translator is unchanged.

The migration checks the reviewed original function bodies and the live lock's
body, owner, ACL, `SECURITY DEFINER`, `search_path`, language, and volatility
before replacement. `CREATE OR REPLACE FUNCTION` keeps the function OIDs and
grants. Downgrade requires the exact changed bodies and restores the original
body text. Both directions fail closed on drift. The original `0003a_assets`
migration is unchanged.

Online execution and Alembic offline emission use the same guarded server-side
`DO` block. Offline SQL is executable and performs the catalog checks on its
target database; emission does not bypass those checks. The focused test
executes the emitted upgrade and downgrade, compares them with the online
roundtrip, and rejects read-body, lock-body, security-definer and ACL drift in
both modes and directions. It also asserts successful ordinary lease
revalidation after upgrade while the parent remains ready.

The focused PostgreSQL test uses a guarded, uniquely named disposable database
and actual protected functions. It verifies a normal read, parent `DELETING`
and `DELETED`, expiry, revalidation after parent change, ticket identity and
deadline denials, unchanged write conflict mapping, and exact
downgrade/upgrade recovery. This is local SQL acceptance evidence. The frozen
Linux HTTP/provider acceptance case still requires execution after source
publication; its allowed denial statuses remain 401/403/404/410.
