# TVT parity fixture boundary

This directory may contain sanitized JSON fixtures only. The current W01 seed has no runtime fixture, and every remote operation remains UNMAPPED.

Keep original packet captures, media, screenshots with identifying details, credentials, tokens, serial numbers, device addresses and unredacted callback payloads in the approved private audit workspace outside Git. The source APK also stays outside Git. Do not copy a raw trace here, even temporarily.

Before adding a fixture:

1. Use an authorized test account/device and the approved matrix. Perform read-only capture by default. Payment, deletion, firmware, audible output and other writes require their own scoped authorization.
2. Redact or replace secret and personal values while preserving field names, types, units, callback order and error semantics. Use explicit redaction markers; do not use production-looking dummy credentials.
3. Save UTF-8 JSON under this directory with sanitized=true, operation ID, APK hash, matrix ID, entry path, account role, model/firmware when applicable, request/response/error schemas, callback terminal condition, token kind, rights reference, deployment OS/ABI, authoritative readback and outcome digest. Include observations for two successes, authorization failure, offline/unsupported result and post-submit timeout where applicable. Record the private raw artifact SHA-256 without the raw bytes.
4. Compute SHA-256 of the exact sanitized JSON file bytes and put its relative path and digest in the matching operation handoff. Update the mirrored coverage CSV and obtain an independent review with ID/time before changing status to CONTRACT_CAPTURED.
5. Run the fixture schema test and inspect the file manually for values the automated scanner cannot identify. A passing schema test does not establish that a capture is authentic, that rights permit deployment, or that browser parity is achieved.

The validator rejects a missing file, a path outside this directory, a hash mismatch, a captured APK hash different from the frozen 1.18.1 baseline, absent metadata/variants and obvious key, credential or embedded media material. The operation handoff remains the source of truth; CSV mirrors its coverage fields.

Use outcome_digest for the normalized successful semantic result. The overall fixture value and the two success observation values must agree with the operation handoff. Give each failure/timeout observation its own 64-hex digest; it may differ from success. Keep raw artifact hashes separate from these outcome hashes, and document normalization rules before promotion.
