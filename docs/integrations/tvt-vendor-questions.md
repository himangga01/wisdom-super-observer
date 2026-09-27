# Questions for TVT and related service owners

Prepared 2026-09-27. **Contact status: not sent; no answer, refusal or license received.** This document is a question set for an authorized product/vendor contact. The date and source of every future answer, refusal or nonresponse must be appended here. Do not infer permission from public marketing text.

Official pages checked 2026-09-27: [TVT's support page](https://cn.tvt.net.cn/contactSale/index44.html) directs device-SDK requests to sales; [TVT's camera API specification](https://en.tvt.net.cn/products/1840.html) advertises TVT SDK/ONVIF; [TVT's management server page](https://en.tvt.net.cn/products/1061.html) advertises several device access methods. None identifies the APK's `com.tvt.protocol_sdk.TVTOpenSDK` package or grants its server redistribution. The [APK-specific public-source check](apk-audit/00-tvtopensdk-web-check.md) and [protocol feasibility review](apk-audit/11-protocol-feasibility.md) explain that distinction.

| Topic | Exact question and requested artifact | Status |
| --- | --- | --- |
| Product identity | What official SDK/API corresponds to SuperLive Plus 1.18.1 account, device, P2P, cloud and push behavior? Is it the APK's `TVTOpenSDK`, the device SDK, or separate products? Provide names, versions, API manuals and sample applications. | No response |
| Rights | May we host, modify, wrap and redistribute each SDK or Android component in a multi-tenant server or managed gateway? Clarify territories, brands, account access, source/binary redistribution, update obligations, sublicensing and production/support terms in writing. | No response |
| Runtime | Which OS/architecture and headless lifecycle are supported? For Android gateways, specify service/background execution, process restart, update behavior, concurrent identities/devices, session limits and callback thread rules. | No response |
| Authentication | Provide login/challenge/error examples for email/phone and provider/QR, region/DC selection, and the ownership, lifetime, renewal, revocation and storage rules for user, P2P and device-access tokens. Will a browser-issued provider authorization code be accepted? | No response |
| Device access | Provide list/channel/capability, owner/share-recipient permissions, bind/unbind, QR, local discovery, control and readback schemas. Explain LAN, P2P, relay and NAT behavior, with offline/unsupported/denied errors and callback correlation. | No response |
| Media and Talk | Document live/playback/search/seek/export, codec, frame timestamps, audio sync, key frames, encryption, full-duplex Talk, doorbell answer/reject/hangup and cleanup. Which paths support 16 simultaneous views, and what are capacity/latency limits? | No response |
| Alarm/push | Document authenticated socket/vendor-push ingress, event subtypes/IDs, replay cursor, duplicate handling, offline and app-closed delivery, token rotation and read/delete state. Are server-to-browser notifications allowed? | No response |
| Cloud/VAS/payment | Identify separate cloud object/OSS encryption and refresh APIs, catalog/eligibility, order/renew/cancel/auto-renew, signed payment return, sandbox products and authoritative uncertain-order query. State merchant and data-processing rights. | No response |
| Tyco/H5 | Identify Tyco's API owner and approved access terms, token/cookie lifecycle, task polling and output/arm readback. Provide the delivered household/remote-settings H5 action inventory, JS bridge contract, allowed origins, cookies and CSP rules. | No response |
| Support | What compatibility matrix covers region, brand, model, firmware and API version? Provide deprecation notice period, vulnerability process, rate limits, SLA and test environment. | No response |

Answers must include dated primary documentation, written terms and reproducible fixtures. A generic SDK availability statement, device RTSP listing or sample login alone does not close G-P1.
