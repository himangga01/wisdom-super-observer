# Registration and recovery web forms

Implementation date: 2026-10-02 (Asia/Seoul). Source baseline:
`1e9cd000732b7a424a9f59e3722ba6c4d2b3a7d7`. This incremental React UI uses
the approved [APK account-flow source](tvt-account-flows-source.md),
[protected worker](tvt-account-flow-service.md), and
[authenticated API and typed client](tvt-account-flow-api.md).
`MATCHED=0` and `release_ready=false`. Local component acceptance does not
prove handset or live TVT interoperability.

## Implemented behavior

The existing account page exposes login, registration, and password recovery.
Profile reads, refresh, TVT logout, and the required-fresh-image login latch
remain available. Registration and recovery use their own entry components and
one purpose-aware form. Existing Tailwind classes, cards, buttons, input styles,
and the reviewed country data are reused without a new dependency.

Both purposes support email and phone. Email starts omit `country_code`.
Phone starts keep the selected numeric country code and local digits separate;
the worker owns the APK country-code-plus-local wire binding. All 196 source
country rows remain selectable, including shared dial codes, blank locales, and
duplicate locale/label rows. Source row indices make option values unique.
Chinese duplicate labels use the existing English disambiguation pattern.

An explicit code request runs start, existence, then dynamic code issuance.
Boolean false is retained as false. **Web policy:** registration requires
`exists=false`, recovery requires `exists=true`, and a contrary result closes
the local attempt until an explicit fresh start. Flow creation alone never
satisfies this prerequisite. An existence
exception closes the unverified local attempt and clears its reference, timer
and inputs. Code, image and final operations require independently verified
purpose-appropriate existence; an explicit fresh attempt must check again.
This cleanup applies only before verification and final submission, and excludes
state reconciliation. A failed read of an uncertain submitted flow keeps its
reference, UNKNOWN status, final latch and explicit reconciliation control,
including after local expiry; it offers no fresh start without a definitive result.
The APK SDK has an existence operation but its inspected registration callback
does not establish this as a
mandatory precursor. This stricter web gate is not claimed as APK UI parity.

Registration requires explicit agreement acceptance, with terms/privacy links
from the current accepted bootstrap. The final password gate uses 8–16 UTF-16
code units and at least two of ASCII letters, digits, or the source's explicit
punctuation category. It does not classify every Unicode symbol as punctuation;
underscore and ASCII hyphen are not in that category. Other characters do not
contribute a category. Java regex line terminators are excluded to preserve the
helper's full-match behavior. Native NUL/supplementary characters are also
rejected by the reviewed typed request schemas before a final write is latched.
The registration source establishes the 8–16 and category gate. Applying the
same gate to recovery is **conservative local web password policy**; this slice
does not claim an independent exhaustive recovery-password-screen audit.

The small JADX ambiguity in `yg3.b` was resolved against the original local
`classes4.dex`: the punctuation Matcher result initializes the count; the
letter and digit matches each increment it; the final comparison requires two.
Private custody contains the exact strings, all 33 decoded instructions,
the code-item offset, DEX hash, decoder, and interpretation. No vendor
registration constants or private key material are published here.

`IMAGE_REQUIRED`, registration `IMAGE_REJECTED`, and `CODE_SENT` have distinct
UI paths. Image replies cannot complete an account. Registration enables the
image-assisted code request at six image-text characters, recovery at four.
Both final operations require exactly six dynamic-code characters under the
public contract. The image request includes only the current local challenge
UUID/generation and text. Replacement consumes the previous local image before
dispatch. Images are bounded canonical Base64, checked for declared PNG/JPEG
signatures, rendered using owned Blob URLs, and revoked on replacement, cancel,
expiry, and scope leave. They are never rendered as upstream URLs.

`CODE_SENT` starts a 120-second source resend countdown with one-second ticks,
using returned resend wait when supplied. Returned local flow expiry is bounded
to the earliest observed deadline. This is local UI/service lifetime and resend
policy, not proof of vendor dynamic-code expiry. Expiry clears secrets and image
ownership, stops timers, and requires an explicit new start. If a final write
was already dispatched, local expiry retains uncertainty instead of enabling
a fresh final submission. Nothing automatically resends or repeats a write.

COMPLETE clears the form and returns to login. It does not call login or create
an identity. UNKNOWN_OUTCOME shows a fixed actionable message, clears secrets,
blocks final submission, and offers an explicit state read. A state read never
repeats registration/recovery; even a nonterminal read cannot release the
submitted-write latch. FAILED/CLOSED/EXPIRED clear local bindings and inputs and
offer an explicit fresh start. The backend's durable uncertainty hold remains
authoritative after local cancellation or navigation.

## Authority, cleanup, and errors

The boundary provides a typed flow client, safe policy links, and an authority
epoch alongside its existing account context. Actor, tenant, profile, region,
brand, consent, identity-list and CSRF scope changes replace that boundary.
Selected-identity changes replace forms. Navigation, including reselecting the
current purpose, aborts pending signals and remounts the form. Authority requery
temporarily removes secret controls; web logout and pagehide remove them too.
The existing required-fresh-image login latch stays in the active scope.

Account, mode, country, or registration agreement changes invalidate the local
generation immediately, abort requests, discard flow references, clear secrets,
revoke images, and dispose timers. Both successful callbacks and finally cleanup
must still own the dispatch controller, form generation, and authority epoch.
An obsolete finally cannot clear replacement inputs.

Explicit cancel cleans locally first. An owned live flow may then receive one
best-effort cancel with a 1500 ms signal bound under current authority. Its result
is ignored; it cannot delay local cleanup or update a replacement form.
Unmount/scope revocation does not send a cancel through revoked authority.

Inputs are labeled, buttons work through keyboard-native controls, errors use
focused alerts, and countdown/challenge notices use status roles. Busy guards
prevent overlapping operations. Account selectors remain operable to cancel an
in-flight attempt. Errors are reduced again through the closed typed-client
safe vocabulary rather than displaying supplied exception text. A final
transport/deadline error stays UNKNOWN; authentication/authorization failures
also enter the boundary's authority check. Passwords, codes, account names and
image payloads have no storage, URL, cache, telemetry, console or snapshot path.

## Executed evidence and limits

48 UI tests exercise real SessionBoundary and form components with controlled
typed API promises. They cover both purposes and modes, exact email/phone
bodies, false existence, agreement/password gates, source image differences,
completion navigation, one-second resend/expiry, terminal/unknown handling,
explicit state reconciliation, invalid media, cancel without awaiting the
backend, local and authority scope races, late final/finally cleanup, repeated
purpose selection, profile logout requery and web logout. The unchanged account
suite adds 57 existing login/profile regressions: **93 tests passed** in the
original scoped combined checkpoint (36 UI plus 57 account tests).
Fix1 reran the amended UI file alone: **44 tests passed**, including eight
existence-exception regressions across both purposes and subsequent code/image
attempts. Each password rejection case now refills its six-character code before
submission, and a positive control completes registration. SessionBoundary and
the entry wrappers retain their reviewed original bytes. Full frontend
TypeScript and scoped ESLint were run for Fix1; existing account tests were not
repeated because the boundary was unchanged.
Fix2 reran the UI file alone: **48 tests passed**. Its four added timer/promise
cases submit registration/recovery near local expiry, expire a pending final,
reject an explicit state read with unavailable/protocol failures, preserve
uncertainty and single final dispatch, ignore the late final result, and allow
a later explicit successful state read. Fix2 frontend TypeScript and changed-file
ESLint also pass. The original and Fix1 execution records remain historical.
Exact native exits, full command outputs, RED/GREEN history, frozen source
hashes/diff and private18 guard evidence are retained in the ignored W06 UI
report packet.

These tests substitute the typed API boundary; they do not execute SQL,
mTLS/RPC, real vendor transport, native Android, real registration/reset, or
Chrome. Root owns the requested direct Chrome operation and final acceptance.
Live key admission, vendor challenge consumption/expiry, actual account
creation, changed-password login and handset comparison remain unexecuted.
Authoritative reconciliation of uncertain final intents remains an open
product decision described by the protected service.
