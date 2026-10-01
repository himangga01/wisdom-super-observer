# SuperLivePlus startup reference brief

Date: 2026-10-02. Applies to F01 startup, consent, local preferences and safe navigation.
Source: [inspected dashboard reference](https://ref.theseeker.io/r/2437) and
[frozen observations](2026-09-30-dashboard-reference.md). The supplied reference was previously inspected; this task reuses that evidence.

| Screen or state | Reference mapping and implementation |
| --- | --- |
| Startup | Existing WSO 232px sidebar, 64px header, 24px desktop padding; brand and factual region, account and environment panels |
| Consent | White 14px card, current policy links, visible version, keyboard reachable accept/decline, busy disabled controls and live status |
| Settings | Labelled locale and IANA timezone fields, 8px input radius, server confirmed values, retained inputs on failed save |
| Unknown route or missing menu | Fixed accessible error and tenant scoped home link; only authoritative local settings entry enables settings |
| Signed out / expired / unavailable | Login or retry/selection actions; no personalized bootstrap while signed out and no invented account/device data |
| Mobile | Existing collapsible native details menu; 16px outer padding, 12px card spacing, one column panels and wrapping actions |

The desktop panel ratio is 2:1. Colors reuse WSO background #F7F8FA,
surface #FFFFFF, text #1C1C1E, muted #626973, border #E7EAEE and accent
#5AA7E0/#DCEAFA. Scoped Tailwind `@theme` adds TVT card/input spacing,
focus #226594 and error #8C2424. System fonts retain Korean fallbacks.
Focus rings, labelled controls, semantic headings, alert/status regions and
textual account/consent state do not rely on color alone.

TVT identity and OIDC service login remain distinct. Consent never claims
Android or browser camera/microphone permission. No camera, media, provider,
Tyco or remote settings feature is invented from the reference artwork.

Browser visual review: **PENDING**. Desktop/mobile screenshots, actual HTTPS
integration and G-P8 visual signoff were not executed in this component/proxy
task. Component tests cover behavior, not pixel or runtime APK acceptance.
