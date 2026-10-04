# Private successful login and renewal SID acquisition

Analysis date: **2026-10-03 (Asia/Seoul)**. Root-supplied source baseline:
`756946ca73cff31d7ebb23141873088b470a96b4`, including the reviewed private
security adapter Fix1. **MATCHED=0; release_ready=false.** This interface supplies
private source evidence to a later protected worker. Current authorization,
credential publication, encrypted vault lineage and server acceptance are not
implemented by this slice.

## Source and representation

The [completed SID source](tvt-account-security-source-completion.md#sid-and-token-id-key-state)
and [flow source](tvt-account-flows-source.md) establish `sid` and `tokenId` as
string members of operation data. The native callback's object-data branch
invokes `getAESEncryptKeyFromJson` before Java business classification
(`apk-followup/native-callback.txt:1050–1178`, `N:0x2ce324`). Its JSON-text string
branch does not run that extraction. The extractor/setter/getter are
`N:0x2d28d8` / `0x2d893c` / `0x2d8fe4` in the complete retained
`apk-account-flows/native-security.txt`.

Capture accepts object data only. It parses one outer JSON value using the
existing duplicate-member, nonfinite-number and recursion protections; trailing
JSON values and JSON-text data are rejected. It preserves the original bytes;
it never creates a normalized second response. HTTP 2xx and business 200 must
agree with a fresh parse of that response and its existing token projection.
The AccountClient's existing configured body bound is still enforced in its
sole process/TLS/deadline boundary. Revalidation also enforces the inherited
protocol ceiling of 1,048,576 bytes and 4,096 UTF-8 bytes per key string.
NUL, surrogate and supplementary characters retain the existing private
protocol policy. These bounds are web policy, not vendor acceptance claims.

Password login's temporary material is **lowercase MD5 of the exact raw UTF-8
password**, including whitespace; it is not the SHA-512 login proof, the USER
token, the P2P token or the UUID. Provider login's source temporary input is
MD5(provider code), and registration's MD5(dynamic code) is a separate source
side effect. This helper exposes only the password input. A later provider
worker needs its own admitted, one-use provider input; it cannot route a token
through the password configuration merely because both are strings.

The reviewed [SecurityKeyState interface](tvt-security-private-adapter.md) retains
the source trailing-`=` Base64 heuristic, AES ECB and whole decrypted-block text
representation. Source previous-key fallback copies the existing key's text,
not arbitrary decoded key bytes. Only a separately admitted prior key for the
same protected identity/region/brand and checked lineage may supply that
fallback. The native global cache, stale persisted reload after failed setter,
and account-token-derived keys are not admitted worker inputs.

## Exact private interface

`AccountTokens(account_token, p2p_token, private_body=b"")` adds one private,
repr-hidden original-response field. Existing two-argument constructors remain
valid. `AccountRenewal` already has that private field. Successful `_login`
decoding now retains the bounded body; token extraction, P2P `tid` fallback,
renewal without replacement, error codes and transport lifecycle are unchanged.
Rejected HTTP/business responses do not produce a successful token value.

The private `wso_core.tvt.sid_capture` interface is:

```python
capture_login(scope, result, *, known_identity=None) -> UnboundSidCapture | None
capture_renewal(scope, current_user_token, result) -> UnboundSidCapture | None
capture.binding(scope, identity, actual_generation, published_user_token) -> KeyBinding
capture.password_temporary_config(binding, published_user_token, raw_password)
capture.admit(existing_security_key_state, binding, published_user_token) -> None
```

`None` means no usable SID capture: absent/empty `sid` or absent/empty `tokenId`.
A valid USER/P2P token login may therefore continue in a SID-free state. Present
non-string or overbound fields, malformed response/projection, unsuccessful or
spoofed status, or inconsistent scope/token raise a fixed private protocol
error. Capture failure must not be treated as a key, identity grant or successful
password-write prerequisite. Old synthetic token constructors without original
response bytes cannot provide successful capture evidence.

`UnboundSidCapture` is a frozen, repr-hidden private record. It contains copied
scalar scope/known-identity snapshots, a SHA-256 USER-token association, exact
private token-ID and bounded original AccountResponse. It contains no grant,
generation, public success flag, raw password, provider code or admitted key.
Neither `userId` nor `tokenId` is used to invent an account identity. A later
worker can bind a prelogin capture to its actual newly published identity; a
capture with a known identity cannot silently move to another identity.

`binding` revalidates scope and USER identity/token association, requires a
positive exact integer generation, completes the prelogin identity slot, and
returns an independent **structural** KeyBinding. A caller-supplied generation
is not checked against SQL here. Every bind/admit call still requires protected
worker current-state admission. Mutable Pydantic scope/identity instances are
never retained by reference; returned binding mutations cannot change capture
or password configuration snapshots.

`password_temporary_config` implements the existing SecurityKeyConfig port,
retains only lowercase MD5 bytes and independent scope/identity/generation/ID
snapshots, and refuses mismatched bindings. It keeps no raw credential input.
The worker creates a SecurityKeyState with that configuration or its separately
admitted scoped previous-key configuration, then feeds the captured original
response through `admit`. Structural capture alone does not prove ciphertext
validity: the reviewed key state enforces canonical representation, ciphertext
alignment and final AES material length. Any capture association/admission
failure closes the supplied state; no stale key is restored.

All returned objects are private. Their repr/str and fixed errors omit raw
SID/token-ID/body/password/temporary/key material. They are not public DTOs and
must never be passed to arbitrary `dataclasses.asdict`, logs, RPC or JSON dumps.
Dropping references is not Python memory zeroing. The worker must release the
capture and temporary configuration promptly; successful state admission drops
the state's temporary reference, not every separate caller reference.

## States and next worker/vault obligations

| Private evidence state | Meaning | Protected publication/write requirement |
| --- | --- | --- |
| Token success, SID-free | Valid existing token login/renewal, no key capture | Token publication may follow existing policy; password write remains unavailable |
| Unbound SID capture | Successful bounded original reply with typed SID/ID and token association | Publish/check actual identity and USER generation before structural binding |
| Bound structural evidence | Scope, identity, actual supplied generation and token association agree locally | Independently admit current protected actor/membership/consent/identity/generation |
| Admitted SecurityKeyState | Reviewed source crypto accepted the original reply and binding | Atomically publish encrypted key lineage together with the matching credentials |

Token and key publication must be atomic or fail closed before any password
write can observe a token with an unrelated/stale key. Persisted SID/key metadata
must be encrypted and bound to tenant, actor, identity, region, brand, USER kind,
actual generation, exact token association and token-ID. No constructor supplies
this database authority. A renewal with a replacement binds the replacement
token; a renewal without replacement binds only the explicitly supplied current
USER token. Missing new key evidence cannot silently copy old metadata into a
different token or generation. A separately admitted previous key may be used
for source rotation only after checking its lineage against the current state.

The worker must close/drop pending captures and states on cancellation, failed
renewal, UNKNOWN outcome, logout, revocation, password terminal outcome and
identity replacement; revoke or mark the appropriate persisted lineage
unavailable before protected reuse. A failed native-style setter must not reload
stale persisted material. Same nonempty token-ID short-circuit remains confined
to an already admitted matching state; it supplies no cross-generation/global
cache authority. Publication and cleanup require separate worker/SQL review.

## Executed evidence and limits

The SDD `W06-private-SID-capture-*` packet freezes the exact five owned files,
preimages, full owned diff, readsets, command argv/times/native exits/output
hashes, manifests and an exact known18 raw/stored secret scan. Focused tests
exercise success, SID absence, malformed/type/duplicate/nonfinite/depth/bounds,
spoofed status, original token/P2P projections, replacement/no-replacement,
scope mutation, generation/configuration association, raw-password MD5 and
capture-to-existing-state admission. Scoped Ruff/format/strict mypy and affected
existing login/renewal regressions supply local evidence.

The change adds no unresolved transport consequence: only one successful private
decode gains existing bounded bytes. Client tests use the existing synthetic
slow-boundary double while preserving real serializers/status/parser/lifecycle.
No new HTTPS server or broad unchanged securitycrypto/native suite was needed.
Earlier contained HTTPS/security evidence remains historical. No Git, CI, SQL,
database, browser, Android/JNI, ADB, vendor, provider or real-account action was
executed. Actual SID availability, server token/key rotation, protected atomic
publication and accepted password changes remain unexecuted.
