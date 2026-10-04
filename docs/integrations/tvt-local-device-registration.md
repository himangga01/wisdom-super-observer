# Local TVT device registration

Updated: 2026-10-04, Asia/Seoul. Source baseline supplied by Root:
documentation HEAD `36fc954e4754d69721596e190c35f9cf14de3e4c`, published
executable baseline `756946ca73cff31d7ebb23141873088b470a96b4`.
This guide describes the current unpublished W07/W12 registration slice in the
existing Windows worktree. Read this guide and `docs/service-analysis.md` before
later analysis; verify current source and refresh affected findings afterward.
Root owns the canonical service report and the AGENTS.md reference update.

## Purpose and implemented behavior

The existing `/connections` React/Tailwind form now registers a local TVT device
using a private device number, country, username and password, with the existing
public connection name, location and optional store associations. PNG/JPEG/WebP
QR screenshots can fill the device number and username locally in the browser.
The password is entered separately. The image is never included in an HTTP
request. The human location is never filled from the device number.

Saving stores encrypted input and returns `NOT_VERIFIED`, with no last-success
timestamp. It does not perform a vendor login, create a native session, populate
inventory, admit actor/channel permissions, or deliver CCTV video. Those worker
and native integrations remain separate. `MATCHED=0`; release readiness is false.

## API contract and protected storage

`POST /api/v1/connections` retains the existing username/password fields. For
`kind=TVT_DEVICE`, the additional strict private `device` object is required:

| Field | Contract |
| --- | --- |
| `serial` | 1–63 ASCII letters/digits; canonical uppercase |
| `country` | Known uppercase country from the reviewed bootstrap resource; defaults to KR |
| `qr_payload` | Optional bounded device-information QR text, independently parsed on the server |

The QR must match the supplied serial (after uppercase conversion) and username
exactly. QR10 sharing payloads, malformed text and contradictions are rejected.
Unknown fields, including a caller-supplied source type or vendor URL, are rejected.
`TVT_ACCOUNT` and `TYCO_ACCOUNT` retain their existing username/password JSON;
they reject a device selector. Country validation reuses the exact membership
list in `local_bootstrap._AREAS`, without a fabricated runtime context or fallback
for unknown countries.

`PATCH` derives the kind from the existing row inside the protected tenant scope.
A TVT_DEVICE credential replacement requires the full selector and both
username/password fields. A selector without a credential pair is rejected.
Legacy TVT_DEVICE rows with the old username/password blob remain editable for
public metadata; worker parsing of their old blob requires new input. No serial
is inferred from the public location. The existing OWNER, CSRF, tenant/store and
expected-generation checks continue to control writes. There is no secret read
or decrypt operation on this API path.

Before the SQL metadata mutation, username, password, device and generation are
excluded from metadata data. The existing `SecretStore` seals only the canonical
private payload, bound to tenant/connection/version AAD. It contains exactly
`schema_version=1`, `kind=TVT_DEVICE`, `serial`, `country`, `username`, `password`.
Neither QR text nor image bytes are persisted. Public DTOs and statuses keep their
existing schema. The API's fixed validation response does not include raw inputs.

`packages/core/src/wso_core/tvt/local_credentials.py` supplies the private worker
parser and immutable slotted type. It rejects duplicate JSON keys, unknown keys,
incorrect types/schema/kind, malformed UTF-8 and noncanonical or legacy blobs.
It uses the existing N9000 credential policy: nonempty username/password, no NUL,
strict UTF-8 and at most 63 encoded bytes each. Repr and errors are fixed; pickle,
`vars` and dataclass export are unavailable. `to_encrypt_bytes()` is an explicit
encrypt-only export. Worker callers still own authorization and lifetime.

## Browser handling and design

The form uses the established card/input tokens and ordinary Korean labels:
장치번호, 국가, QR 이미지 선택, 아이디, 비밀번호. Country entry is a two-letter
code with KR explained in the form. The server is authoritative for known
country validation. Account forms retain their original limits.

The exact production dependency is `jsqr@1.4.0` (Apache-2.0); pnpm generated
the lockfile. Reference: [official npm package](https://www.npmjs.com/package/jsqr).
Images are restricted to 10 MiB, dimensions no greater than 4096, and at most
4,000,000 decoded pixels. Bounds are checked before canvas allocation. The
browser must decode the image header/bitmap before its dimensions are known;
the bounds do not claim prevention of all decoder allocations. Every acquired
ImageBitmap is closed and canvas dimensions are cleared on success/failure.
No object URLs, localStorage or sessionStorage are used by the QR/form code.

Private DOM fields and the QR payload reference are cleared before submit, on
cancel, type/replacement changes, store selection changes and scope cleanup.
Generation guards discard late QR completion after a new image, scope change
or unmount. This is reference/DOM cleanup; JavaScript and Python do not guarantee
physical memory zeroization. Request-local values exist while the encrypted
registration request is processed.

## Executed verification and limits

The focused portable Python run passed **102 tests** (42 new storage/API-input
cases plus 60 existing QR-parser cases). The focused frontend run passed **21
tests**, including the existing proxy/privacy boundary, real jsQR decoding of an
inert QR matrix, the file/canvas cleanup path, manual/device validation and stale
async form completion. The real pixel decoder is exercised; jsdom tests simulate
ImageBitmap/canvas acquisition. Actual browser PNG decoder, visual layout and
mobile screenshot acceptance have not been executed in this slice.

Root's explicitly owned PostgreSQL/auth fixture passed **3 tests, zero skips**
against the current dedicated integration test: protected kind/legacy metadata,
actual encrypted worker roundtrip and public/audit redaction, OWNER/CSRF/tenant/
store isolation and generation conflict. Root verified the owned database was
removed and the source database unchanged. No legacy DSNs or real device inputs
were read by the implementation agent. This is synthetic registration acceptance,
not a CCTV credential or connection acceptance.

Selected Ruff/ESLint, Python mypy and web TypeScript checks passed; the final
Next.js production build passed. Receipts, frozen sources, preimages, dependency
readsets and deltas are in the W07-local-device-registration packet under
`.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/`.
Initial intentional TDD failures and subsequent corrected fixture/type/lint
failures remain in the evidence. No broad unrelated suite or real device call
was made. Root independently reviews and scans before publication.

## Remaining priorities and product questions

1. Integrate the private parser with the authorized worker/native adapter and
   preserve current tenant/store/channel admission before actual device use.
2. Execute an approved HTTPS browser flow and visual/mobile check using inert
   data; browser bounds do not constitute hostile image decoder sandboxing.
3. Confirm whether the country code field should become a localized country
   picker. The current server validation and storage contract support that later
   presentation change without accepting arbitrary vendor endpoints.

Legacy device credential replacement requires the user to re-enter the device
number and both credentials. There is no migration or saved-secret autofill.
