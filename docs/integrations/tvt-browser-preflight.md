# TVT browser platform preflight — candidate v0

**G-P4a status: OPEN / PARTIALLY PROBED (2026-09-27).** A read-only Playwright probe ran in fresh headless desktop Chrome and Edge contexts on Windows 11. It establishes API presence and advertised codec support on `http://127.0.0.1` only. The candidate handset/PWA matrix, permission results, actual media, Push delivery and closed-client behavior remain `UNTESTED`. No APK/web parity row is `MATCHED` from this probe. Product-owner review of the support matrix is pending.

## Desktop run and observed results

Command: `pnpm exec playwright test tests/tvt_parity/e2e/platform-preflight.spec.ts` from the repository root. Playwright 1.63.0 ran 2 tests with 0 failures after the root Playwright dependency was installed. Host: Microsoft Windows 11 Pro 64-bit, build 26200; locale `en-US`, time zone `Asia/Seoul`. Each test started a temporary HTTP server on `127.0.0.1`, which browsers treated as a secure context. This is not an HTTPS handset result. The command prints one `TVT_PREFLIGHT` JSON record per browser and attaches `browser-capabilities.json` to each test.

| Probe | Headless Chrome 153.0.8010.54 | Headless Edge 154.0.4258.37 |
| --- | --- | --- |
| Local origin / secure context | `http://127.0.0.1:65314`; `isSecureContext=true` | `http://127.0.0.1:60625`; `isSecureContext=true` |
| Camera/microphone | `navigator.mediaDevices.getUserMedia` present; `getDisplayMedia` present | Same |
| MediaRecorder | API present; `isTypeSupported=true` for all six types listed below | Same |
| WebRTC | `RTCPeerConnection` present; sender codec lists include VP8, H264, AV1, VP9 and Opus; Chrome also reports H265 | Same listed codecs except H265 was absent |
| Service worker / Push | `navigator.serviceWorker`, `PushManager`, `Notification` present; notification permission reads `default` | Same |
| IndexedDB / storage | IndexedDB, local/session storage, file picker and Web Share APIs present; estimate 3 GiB quota, 0 B usage; persistent storage `false` | Same API presence; estimate 10 GiB quota, 0 B usage; persistent storage `false` |
| Tab visibility | Initial `visible`; after second tab focused still `visible`; resumed `visible`; no `visibilitychange` event | Same |

The six `MediaRecorder.isTypeSupported` inputs were `video/webm;codecs=vp8,opus`, `video/webm;codecs=vp9,opus`, `video/webm;codecs=h264,opus`, `video/mp4;codecs=avc1.42E01E,mp4a.40.2`, `audio/webm;codecs=opus`, and `audio/mp4;codecs=mp4a.40.2`. A `true` flag does not demonstrate successful recording, playback, bandwidth, or TVT device codec compatibility. The storage quotas are estimates for temporary test profiles, not durable retention guarantees. Headless tab switching did not produce a hidden state, so **background lifecycle is unverified**; the observed `visible` state is recorded rather than reclassified as a pass.

## Candidate client matrix

| Matrix profile | Status | Remaining evidence |
| --- | --- | --- |
| Desktop Chrome, Windows, headless localhost | API/codec preflight observed; permission and media workflows `UNTESTED` | Valid-certificate HTTPS, camera/mic grant and denial, actual encoding/playback, service-worker registration and Push delivery, foreground/background/closed behavior |
| Desktop Edge, Windows, headless localhost | API/codec preflight observed; permission and media workflows `UNTESTED` | Same, including denied notification permission |
| Android Chrome tab | `UNTESTED` — no Android browser/device in this run | Exact OS/browser/device, HTTPS, permission, media, Push, storage/download, background and closed tab |
| Android Chrome installed PWA | `UNTESTED` — no installed PWA/phone in this run | Install state, locked/closed doorbell invite, click/answer/reject and audio start |
| iOS Safari Home Screen web app | `UNTESTED` — no iOS browser/device in this run | Exact iOS/Safari, installed state, HTTPS, permission, Push, media, closed/locked doorbell flow |

No camera or microphone permission was requested; no real stream or device was accessed. Service workers were not registered, Push subscriptions were not created, IndexedDB was not written, and no TVT account or hardware was contacted. Therefore camera/mic grant, denial and revocation; offer/answer/ICE or decoded frames; service-worker update/restart; Push token rotation/delivery/click; storage eviction/file integrity; doorbell expiry; and Wi-Fi/AP provisioning are all `UNTESTED`. Native Android full-screen lock-screen calls, automatic Wi-Fi/AP switching and raw TCP 9008 are not inferred from API detection.

## Gate decision

G-P4a remains open until each proposed OS/browser/PWA profile is measured on a valid HTTPS origin with permission, codec, Push, storage and lifecycle evidence. G-P4b later requires working APK/web flow comparisons on the approved account/device matrix. A missing platform or unsupported result stays visible; this desktop API probe cannot close either gate or support a 100% parity claim. See [the parity ledger](tvt-parity-ledger.md) and [platform constraints](apk-audit/13-web-platform-constraints.md).
