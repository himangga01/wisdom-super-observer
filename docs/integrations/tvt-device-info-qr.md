# Private device information QR import

Analysis date: **2026-10-03, Asia/Seoul**. Source baseline: SuperLive Plus
**1.18.1**, base APK SHA-256
`f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.
Root supplied executable baseline `756946c`, documentation HEAD `36fc954`;
this task did not independently inspect Git. **MATCHED=0; release_ready=false.**

`packages/core/src/wso_core/tvt/device_qr.py` implements a private, bounded
parser for the device information family `<sn>…</sn><user>…</user>`. It returns
serial and username as an immutable `DeviceInfoQr`, whose representation omits
both fields and whose status is always `not_connected`. It does not contain a
password, credential token, device grant, account binding, or connection result.
No actual user QR, device identifier or credential is included in this document
or its tests.

## Source evidence and strict subset

`J:` denotes the private `jadx-full/sources/` extraction. Source hashes and
original file paths are retained in the ignored W07 review packet.

| Original source | Observed behavior |
| --- | --- |
| `J:com/tvt/devicemanager/DeviceQrcodeActivity.java:125–129` | Concatenates the two lowercase tags with the device serial and username; no password is emitted. The source's logging of serials is deliberately excluded from this implementation. |
| `J:com/tvt/devicemanager/a.java:2018–2042,2077–2091` | Actual minified consumer `N1`/`O1` extracts serial and user via `GlobalUnit.x0.l`. `O1` also accepts uppercase SN and unrelated broader QR fields and defaults a missing/empty user to `admin`. Those branches are outside this strict two-tag subset; missing user is rejected here. A file or class named `AddDevQRScanActivity` was not present in the inspected extraction. |
| `J:com/tvt/network/GlobalUnitItem.java:1064–1067` | Extracts a literal substring between delimiters. It does not trim, normalize Unicode or decode XML entities. |
| `J:com/tvt/network/GlobalUnit.java:1713–1715` | Classifies SN text with `^[a-zA-Z0-9]{1,128}$`. This is not address, DNS or URL validation. |
| `J:com/tvt/dev_share/AddDeviceActivity.java:98–125,154–184` | A separate local-add path preserves username and requires a separately supplied password; source SN classification selects serial versus address/port behavior. This does not demonstrate account binding or successful device authentication. |
| [Device access source completion](tvt-device-access-source-completion.md) | The `NetClientProtocal.ConnectDevByToken` route reaches `CNetComWrapper::ConnectByToken N:0x232088`, which copies at most 32 device-ID bytes. This route's boundary is narrower than Java's SN classifier. Manual/LAN/share routes require independent mapping. |

The accepted input contains exactly one `<sn>` tag followed immediately by
exactly one `<user>` tag, with both values nonempty. Serial text must match the
source ASCII classifier. Tags, attributes, duplicates, other fields, leading or
trailing text, malformed closing tags and nested markup are rejected. Usernames
remain exact literal text: spaces, valid Unicode, combining characters and
literal `&amp;` are retained without conversion. Angle brackets in the username
are rejected to prevent ambiguous tag structure. There is no XML parser, DTD,
external entity, file fetch, entity expansion or network access.

Input is an exact Python `str` or `bytes`; bytes require strict UTF-8. NUL,
unpaired surrogates and malformed UTF-8 are rejected. A **4096-byte total UTF-8
input cap** bounds decoding and parsing. This is a local safety policy, not an
APK generation limit, username native maximum or server contract. The parser
checks character length before encoding string input and byte length before
decoding byte input. Username size is bounded by the total payload policy; its
native ABI limit remains unproved.

The separate QR10 local-device sharing family has a JSON version signature and
may contain password-bearing data. A bounded JSON-like QR10 version signature
raises `UnsupportedDeviceQr`, a subtype of `DeviceInfoQrError`. This is signature
classification only; the parser does not parse, base64-decode or decrypt QR10.
See [Device directory source contracts](tvt-device-directory-source.md).

## Private worker integration boundary

Inside an independently authorized private worker, call
`parse_device_info_qr(private_text_or_bytes)` and select the actual connection
route using independently authorized credentials and the applicable adapter.
For the `NetClientProtocal.ConnectDevByToken` account-device-token route, call
`validate_connect_by_token_device_info(parsed)` before dispatch. It returns the
same private input only when its serial fits that route's observed **32-byte**
device-ID boundary. A 33–128 character ASCII serial still parses successfully;
this check rejects it only for ConnectDevByToken. The serial is never truncated
or rewritten as an address.

Manual QR connections use the separate `NatTraveral` library. This module does
not validate manual QR, LAN or sharing route ABI limits; each selected adapter
must enforce its independently reviewed route constraints. No universal serial
byte limit or acceptance on those routes follows from this check. Username
constraints also remain the selected adapter's responsibility before native I/O.
The manual route's source contract has not completed independent review; this
document makes no manual device-ID byte-bound or interoperability claim.

The result supplies a selector and username only. Actual connection needs a
separately authorized device password or account-derived device credential,
current actor/tenant/store/channel authorization, the selected adapter's native
checks, and genuine authentication/callback evidence. Import does not grant
authority, persist credentials, bind ownership or publish device access. The
module performs no transport, database, native, browser or phone operation.

Validation errors use fixed messages without raw payload, serial, username or
Unicode decoder exception context. Ordinary `repr` and `str` suppress private
fields. Fields remain readable to the private worker, so callers must not log,
serialize, publish or expose them through public APIs or analytics. Dataclass
serialization and debugger/local-frame capture are not secrecy boundaries;
Python memory zeroing is not guaranteed.

## Executed verification and limits

Only invented fixtures are used in `tests/tvt_parity/test_device_qr.py`, including
two distinct store-like serial/username pairs. Tests exercise causal missing
implementation failures before production code, exact source ranges,
ConnectDevByToken-specific 32/33-byte separation, literal username preservation,
malformed and duplicate
tags, DTD/CDATA rejection, QR10 separation, NUL, invalid Unicode/UTF-8, exact total
byte cap, private errors and immutable repr-suppressed results. Scoped tests,
Ruff, formatter and mypy results are recorded with commands/exits and frozen
source hashes in the ignored original `W07-device-info-qr-report.md` and current
`W07-device-info-qr-Fix1-report.md` review packets. Fix1 scopes the validator to
ConnectDevByToken and changes the integration guidance to select the route first;
parser acceptance and its `not_connected` result are unchanged.

This parser has not been executed against supplied private QR records, a live
device, vendor account, native SDK or API/RPC/browser integration. All such
acceptance and the independently reviewed authenticated worker composition
remain separate tasks. Parsing success is never a device connection claim.
