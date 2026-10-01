# SuperLivePlus bundled policies and startup profile

Analysis and implementation date: 2026-10-02. Source implementation baseline:
`3d982b0f94311324aa79a5ca83580d695a34572a` with the reviewed W03 startup
contracts and frontend present as working-tree inputs. These pages describe
**SuperLivePlus**, rather than new Wisdom Super Observer terms. They are derived
from the user-provided `com.tvt.superliveplus` APK, version **1.18.1**, code 20267,
SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281`.

## Public documents

| Source language | Agreement | Privacy statement |
| --- | --- | --- |
| English (`en`) | `/tvt/policies/en/terms` | `/tvt/policies/en/privacy` |
| Simplified Chinese (`zh-Hans`) | `/tvt/policies/zh-Hans/terms` | `/tvt/policies/zh-Hans/privacy` |

The four routes serve the same bundled content to every reader and are available
before login or consent. Unknown locale or policy kind returns `notFound`.
The route reads no cookie, session, tenant, query parameter, browser preference,
vendor data center or remote source. Content is rendered by React text nodes and
semantic headings, paragraphs, lists and tables. No HTML is injected.

## Source provenance and regeneration

Private source root: `C:\wso-private\superliveplus\1.18.1-2026-09-27`.
Only these four assets are accepted; each is verified by exact bytes and SHA-256
before conversion. Startup policy references retain the `agreement/` filename.

| Asset under `apktool/assets/agreement/` | Bytes | Source SHA-256 |
| --- | ---: | --- |
| `ServiceTerms_en.html` | 158863 | `7973f409b90d62127488bf496de299dc537c32832b1c27b9d37f020ce2525544` |
| `PrivacyStatement_en.html` | 47981 | `e2f542f723b332188db98d428a49b15d5430b4b3e2722338b2df8aed31882f1b` |
| `ServiceTerms_zh-Hans.html` | 196817 | `9580039561c539e348a2a45f6682b54fe3f2681749817baceb3e99e6fc9f3965` |
| `PrivacyStatement_zh-Hans.html` | 38500 | `ff1a8d79ee2ee6b2b095129a0187a54f7e39c83f2b8e233b71988a72e513028d` |

From the repository root in PowerShell, with its existing Python environment:

```powershell
& .\.venv\Scripts\python.exe scripts/generate_tvt_policy_content.py `
  --apk-root 'C:\wso-private\superliveplus\1.18.1-2026-09-27'
```

The generator writes
`apps/web/src/features/tvt/policies/generated-content.json`. Its schema version is
1 and derivation is `visible-body-structured-v1`. Each document includes its source
language, kind, filename, original byte count, source digest and content digest.
The content digest hashes the blocks as UTF-8 JSON with sorted keys, no optional
whitespace and unescaped Unicode. Repeated generation produces identical bytes.

Source CSS, Word spans/fonts, bold/underline presentation, original page title/head
metadata and active content are discarded. Heading levels are shifted below the
reader's own h1. Whitespace is collapsed; explicit source line breaks are retained.
The English privacy source puts some paragraphs directly inside lists, outside
`li`; the converter attaches them after the preceding item in source order without
adding bullets. Tables retain row/cell order and scroll inside the card on narrow
screens. The visible labels of the two actual privacy hyperlinks are retained as
inert text; click navigation to AboutCookies.org and WeChat support is omitted.
Scripts `common.js` and `language.js` are discarded. No source resource is fetched.
An independent flat-body comparison verified that all four source documents retain
every visible non-whitespace character in order; that does not prove identical
typography or screen layout.

## Configure before API startup

Use the actual server-configured `WSO_PUBLIC_ORIGIN`; it must be HTTPS with an
ASCII hostname or valid IPv6 host, optional valid port and no credentials, path,
query or fragment. No hostname or vendor region is discovered from a browser.
Choose an explicit deployment region code (for example `KR`, or an operator's
uppercase subdivision label), default policy/formatting locale (`en` or
`zh-Hans`) and valid IANA timezone. A region label does not enable a vendor data
center, provider or capability.

The current web interface copy is Korean (`ko`). This is separate from the policy
language and the startup profile's default locale for preferences/date formatting.
The optional `--ui-locale` defaults to `ko` and only accepts `ko` until actual
interface translations are included. No new UI-locale contract field is emitted.

Run the generator **before** starting the API. The ignored SDD directory below
already exists for this implementation plan. Substitute your reviewed deployment
values; do not use example origins for a deployment.

```powershell
$profileRoot = (Resolve-Path '.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan').Path
$profilePath = Join-Path $profileRoot 'W03-policy-profile-local.json'
$publicOrigin = $env:WSO_PUBLIC_ORIGIN
if ([string]::IsNullOrWhiteSpace($publicOrigin)) { throw 'Set the actual WSO_PUBLIC_ORIGIN before generation.' }

& .\.venv\Scripts\python.exe scripts/dev/write_tvt_startup_profile.py `
  --public-origin $publicOrigin `
  --region KR `
  --default-locale en `
  --timezone Asia/Seoul `
  --output-root $profileRoot `
  --output $profilePath
if ($LASTEXITCODE -ne 0) { throw 'Startup profile generation failed.' }
$env:WSO_TVT_STARTUP_PROFILE = [System.IO.File]::ReadAllText($profilePath, [System.Text.Encoding]::UTF8)
# Start the API using the project's existing command in this same process environment.
```

The output path must end in `.json`, resolve inside the explicit existing output
root, have an existing parent and not be a symlink. An existing file is rejected;
use `--replace` only when intentionally replacing that reviewed JSON configuration.
The writer validates the real `wso_core.tvt.startup.StartupProfile`, keeps its
16 KiB loader bound and atomically replaces a temporary file. It writes no `.env`
or secret, and does not load JSON into the environment automatically.

The profile's terms/privacy URLs point to the chosen source-language routes on
the configured public origin. Supported policy/formatting locales are precisely
`en` and `zh-Hans`. Changing user preferences does not dynamically replace these
profile policy references; both language variants are reachable in the reader.
The deterministic consent version is `slp-1.18.1-` plus the first 40 hexadecimal
characters of SHA-256 over newline-delimited app/version, APK digest, derivation
and all four `locale:kind:source-digest:content-digest` records in `en` then
`zh-Hans`, terms then privacy order. It is independent of origin/default locale,
and changes when a reviewed source policy or its transformed content changes.

## Settings and validation limits

`local_routes` defaults to an empty list. After reviewing the included settings
route, explicitly add `--enable-settings` to allow only `/tvt/settings` in the
existing startup menu. No other menu, provider or device/media capability is
enabled. The flag checks that the existing TVT web route is included; it does not
claim that browser acceptance or APK comparison has passed.

Without valid `WSO_TVT_STARTUP_PROFILE`, the existing authenticated startup logic
continues to return fixed `503 startup_unavailable`; generation does not change
that server behavior. Focused Python and React SSR tests, static checks, exact
source verification and deterministic regeneration are implementation evidence.
Actual HTTPS serving, desktop/mobile keyboard and visual review, first-run
consent acceptance against the APK, provider/device execution and runtime parity
remain pending. No `MATCHED` case or release promotion is asserted here.
