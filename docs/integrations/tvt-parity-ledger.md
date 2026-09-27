# TVT parity evidence ledger — static seed v0

Baseline: SuperLive Plus 1.18.1 (20267), base APK SHA-256 `f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281` ([audit baseline](apk-audit/00-coverage-baseline.md)). This ledger seeds 77 atomic contracts from [audit 12](apk-audit/12-functional-parity-contracts.md), with [audit 14](apk-audit/14-reachability-and-route-gaps.md) corrections. It contains **static inspection only**. No login, live device, payment, browser lab, APK/web comparison, or independent runtime review has been performed for these rows. `MATCHED` count is **0**; the 100% release gate is open.

`C` denotes a conditional click/call path identified in APK code; `L` denotes an APK-local path; `D` denotes a declaration without a proved UI call path. All 77 rows remain `DECLARED`: static code paths do not establish that an app user actually reached the entry. `REACHABLE` requires an authorized APK runtime entry trace, redacted digest and reviewer. `DECLARED` cases cannot be dropped without runtime reachability analysis and reviewed gate proof. Every row is `NOT_STARTED` and `UNTESTED`. The `Source` link leads to the row's exact APK code references. `—` in runtime evidence means no signed redacted run artifact exists yet.

## Seed cases

<!-- PARITY_CASES_START -->
| Case | Feature | Owner | Gate | Static path | Reachability | Build | Parity | Source | Runtime evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01.1 | F01 | W03/W22 | G | C | DECLARED | NOT_STARTED | UNTESTED | [12:P01.1](apk-audit/12-functional-parity-contracts.md) | — |
| P01.2 | F01 | W03/W22 | G/U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P01.2](apk-audit/12-functional-parity-contracts.md) | — |
| P02.1 | F02 | W05/W06 | G/U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P02.1](apk-audit/12-functional-parity-contracts.md) | — |
| P02.2 | F02 | W05/W06 | G | C | DECLARED | NOT_STARTED | UNTESTED | [12:P02.2](apk-audit/12-functional-parity-contracts.md) | — |
| P02.3 | F02 | W05/W06 | G | C | DECLARED | NOT_STARTED | UNTESTED | [12:P02.3](apk-audit/12-functional-parity-contracts.md) | — |
| P02.4 | F03 | W05/W06 | G+B | C | DECLARED | NOT_STARTED | UNTESTED | [12:P02.4](apk-audit/12-functional-parity-contracts.md) | — |
| P02.5 | F03 | W05/W06 | U | D | DECLARED | NOT_STARTED | UNTESTED | [12:P02.5](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P03.1 | F04 | W07/W08 | O/R/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P03.1](apk-audit/12-functional-parity-contracts.md) | — |
| P03.2 | F04 | W07/W08 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P03.2](apk-audit/12-functional-parity-contracts.md) | — |
| P04.1 | F05 | W08/W09 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P04.1](apk-audit/12-functional-parity-contracts.md) | — |
| P04.2 | F08 | W08/W09 | O/R/N+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P04.2](apk-audit/12-functional-parity-contracts.md) | — |
| P05.1 | F06 | W08/W14 | O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P05.1](apk-audit/12-functional-parity-contracts.md) | — |
| P05.2 | F10 | W08/W14 | O/R/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P05.2](apk-audit/12-functional-parity-contracts.md) | — |
| P05.3 | F10 | W08/W14 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P05.3](apk-audit/12-functional-parity-contracts.md) | — |
| P06.1 | F04 | W07/W09/W14/W15 | O/R | C | DECLARED | NOT_STARTED | UNTESTED | [12:P06.1](apk-audit/12-functional-parity-contracts.md) | — |
| P06.2 | F10 | W07/W09/W14/W15 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P06.2](apk-audit/12-functional-parity-contracts.md) | — |
| P06.3 | F10 | W07/W09/W14/W15 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P06.3](apk-audit/12-functional-parity-contracts.md) | — |
| P07.1 | F07 | W10/W11 | O/R/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P07.1](apk-audit/12-functional-parity-contracts.md) | — |
| P07.2 | F07 | W10/W11 | O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P07.2](apk-audit/12-functional-parity-contracts.md) | — |
| P08.1 | F14 | W12/W16 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P08.1](apk-audit/12-functional-parity-contracts.md) | — |
| P08.2 | F14 | W12/W16 | O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P08.2](apk-audit/12-functional-parity-contracts.md) | — |
| P08.3 | F14 | W12/W16 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P08.3](apk-audit/12-functional-parity-contracts.md) | — |
| P08.4 | F14 | W12/W16 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P08.4](apk-audit/12-functional-parity-contracts.md) | — |
| P09.1 | F15 | W16 | O/N+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P09.1](apk-audit/12-functional-parity-contracts.md) | — |
| P09.2 | F15 | W16 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P09.2](apk-audit/12-functional-parity-contracts.md) | — |
| P10.1 | F11 | W07/W12/W15 | G/U/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P10.1](apk-audit/12-functional-parity-contracts.md) | — |
| P10.2 | F11 | W07/W12/W15 | U/O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P10.2](apk-audit/12-functional-parity-contracts.md) | — |
| P10.3 | F11 | W07/W12/W15 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P10.3](apk-audit/12-functional-parity-contracts.md) | — |
| P11.1 | F11 | W07/W14/W15 | O/R/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P11.1](apk-audit/12-functional-parity-contracts.md) | — |
| P11.2 | F11 | W07/W14/W15 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P11.2](apk-audit/12-functional-parity-contracts.md) | — |
| P11.3 | F11 | W07/W14/W15 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P11.3](apk-audit/12-functional-parity-contracts.md) | — |
| P11.4 | F11 | W07/W14/W15 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P11.4](apk-audit/12-functional-parity-contracts.md) | — |
| P12.1 | F09 | W09/W12/W14 | O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P12.1](apk-audit/12-functional-parity-contracts.md) | — |
| P12.2 | F09 | W09/W12/W14 | O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P12.2](apk-audit/12-functional-parity-contracts.md) | — |
| P12.3 | F09 | W09/W12/W14 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P12.3](apk-audit/12-functional-parity-contracts.md) | — |
| P12.4 | F09 | W09/W12/W14 | O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P12.4](apk-audit/12-functional-parity-contracts.md) | — |
| P13.1 | F23 | W14 | O/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P13.1](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P14.1 | F13 | W13 | U/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P14.1](apk-audit/12-functional-parity-contracts.md) | — |
| P14.2 | F13 | W13 | O/R | C | DECLARED | NOT_STARTED | UNTESTED | [12:P14.2](apk-audit/12-functional-parity-contracts.md) | — |
| P14.3 | F13 | W13 | U | D | DECLARED | NOT_STARTED | UNTESTED | [12:P14.3](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P15.1 | F13 | W13 | U/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P15.1](apk-audit/12-functional-parity-contracts.md) | — |
| P15.2 | F13 | W13 | U+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P15.2](apk-audit/12-functional-parity-contracts.md) | — |
| P16.1 | F02 | W05/W06 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P16.1](apk-audit/12-functional-parity-contracts.md) | — |
| P16.2 | F02 | W05/W06 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P16.2](apk-audit/12-functional-parity-contracts.md) | — |
| P16.3 | F03 | W05/W06 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P16.3](apk-audit/12-functional-parity-contracts.md) | — |
| P16.4 | F02 | W05/W06 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P16.4](apk-audit/12-functional-parity-contracts.md) | — |
| P17.1 | F12 | W07 | O/U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P17.1](apk-audit/12-functional-parity-contracts.md) | — |
| P17.2 | F12 | W07 | O/U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P17.2](apk-audit/12-functional-parity-contracts.md) | — |
| P17.3 | F12 | W07 | U/R | C | DECLARED | NOT_STARTED | UNTESTED | [12:P17.3](apk-audit/12-functional-parity-contracts.md) | — |
| P17.4 | F12 | W07 | O/R | C | DECLARED | NOT_STARTED | UNTESTED | [12:P17.4](apk-audit/12-functional-parity-contracts.md) | — |
| P17.5 | F12 | W07 | O | D | DECLARED | NOT_STARTED | UNTESTED | [12:P17.5](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P17.6 | F12 | W07 | O/R+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P17.6](apk-audit/12-functional-parity-contracts.md) | — |
| P18.1 | F16 | W17 | U/V/O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.1](apk-audit/12-functional-parity-contracts.md) | — |
| P18.2 | F16 | W17 | V/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.2](apk-audit/12-functional-parity-contracts.md) | — |
| P18.3 | F17 | W18 | G/U/V+B | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.3](apk-audit/12-functional-parity-contracts.md) | — |
| P18.4 | F17 | W18 | V | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.4](apk-audit/12-functional-parity-contracts.md) | — |
| P18.5 | F17 | W17/W18 | V/O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.5](apk-audit/12-functional-parity-contracts.md) | — |
| P18.6 | F17 | W18 | V | D | DECLARED | NOT_STARTED | UNTESTED | [12:P18.6](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P18.7 | F17 | W17 | V/O | D | DECLARED | NOT_STARTED | UNTESTED | [12:P18.7](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P18.8 | F16 | W17 | V/O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.8](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P18.9 | F16 | W17 | V/O | C | DECLARED | NOT_STARTED | UNTESTED | [12:P18.9](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P19.1 | F19 | W20 | U/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P19.1](apk-audit/12-functional-parity-contracts.md) | — |
| P19.2 | F19 | W20 | U/O+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P19.2](apk-audit/12-functional-parity-contracts.md) | — |
| P19.3 | F19 | W20 | U | D | DECLARED | NOT_STARTED | UNTESTED | [12:P19.3](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P19.4 | F19 | W20 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P19.4](apk-audit/12-functional-parity-contracts.md) | — |
| P20.1 | F20 | W21 | U/O | L | DECLARED | NOT_STARTED | UNTESTED | [12:P20.1](apk-audit/12-functional-parity-contracts.md) | — |
| P20.2 | F20 | W21 | U/O+F | L | DECLARED | NOT_STARTED | UNTESTED | [12:P20.2](apk-audit/12-functional-parity-contracts.md) | — |
| P21.1 | F21 | W14/W21 | O/N+B | C | DECLARED | NOT_STARTED | UNTESTED | [12:P21.1](apk-audit/12-functional-parity-contracts.md) | — |
| P22.1 | F18 | W19 | T+B | C | DECLARED | NOT_STARTED | UNTESTED | [12:P22.1](apk-audit/12-functional-parity-contracts.md) | — |
| P22.2 | F18 | W19 | T | C | DECLARED | NOT_STARTED | UNTESTED | [12:P22.2](apk-audit/12-functional-parity-contracts.md) | — |
| P22.3 | F18 | W19 | T | C | DECLARED | NOT_STARTED | UNTESTED | [12:P22.3](apk-audit/12-functional-parity-contracts.md) | — |
| P22.4 | F18 | W19 | T | C | DECLARED | NOT_STARTED | UNTESTED | [12:P22.4](apk-audit/12-functional-parity-contracts.md) | — |
| P22.5 | F18 | W19 | T+F | C | DECLARED | NOT_STARTED | UNTESTED | [12:P22.5](apk-audit/12-functional-parity-contracts.md) | — |
| P23.1 | F22 | W04/W21/W22/W25 | G/U+B | C | DECLARED | NOT_STARTED | UNTESTED | [12:P23.1](apk-audit/12-functional-parity-contracts.md) | — |
| P23.2 | F22 | W04/W21/W22/W25 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P23.2](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P23.3 | F22 | W04/W21/W22/W25 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P23.3](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
| P24.1 | F24 | W22 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P24.1](apk-audit/12-functional-parity-contracts.md), [14](apk-audit/14-reachability-and-route-gaps.md) | — |
<!-- PARITY_CASES_END -->

## Candidate support matrix v0 — review pending

These are candidate profiles to resolve **before** feature implementation. IDs are placeholders, not approved applicable rows or evidence of browser support. W01/W12 must record exact APK hash, region/brand, account grants and entitlement, model/firmware/capability snapshot, browser/OS/PWA build, secure origin, permission state, network path and locale/time zone for every executable row. Product-owner review and a versioned applicability map are pending. Do not compute 100% from this table.

| Candidate | FE client/state | Account / device fixture | Branches to probe | Evidence state |
| --- | --- | --- | --- | --- |
| M01 | Desktop Chrome, Windows, foreground | Unsigned guest and ordinary TVT account | Consent, auth, content, denied device access | Unmeasured |
| M02 | Desktop Edge, Windows, foreground/background | Owner IPC and restricted share recipient | Live, Talk, controls, role isolation, expired/revoked token | Unmeasured |
| M03 | Android Chrome tab, foreground/background/closed | Owner IPC/NVR, online/offline/unsupported | Camera, microphone, Push, relay/P2P/LAN, files | Unmeasured |
| M04 | Android Chrome installed PWA, foreground/background/closed | Owner doorbell, normal/expired token | Invite, answer/reject, Wi-Fi/AP gateway, mic/notification denied | Unmeasured |
| M05 | iOS Safari Home Screen web app, foreground/background/closed | Owner doorbell and restricted recipient | Push and lock-screen invite, media/codec, permission denied | Unmeasured |
| M06 | Desktop Chrome/Edge with alternate observed region/brand | Tyco-enabled and VAS-entitled accounts; NVR | Brand/provider visibility, Tyco, VAS/cloud and payment sandbox | Unmeasured |

Each candidate branches by locale/time zone, granted/denied permissions, online/offline and token state where applicable. Add observed brand, firmware, entitlement and H5 branches to the denominator; do not use a Cartesian product of impossible gates. Actual case × matrix applicability and test fixture IDs require W01 capture and product-owner sign-off. No browser/OS version is asserted yet.

## Comparison rules v0

A `MATCHED` run requires the same authorized starting state and input; APK and web build IDs; fixture/action digest; UI, callback and network/device or file readback; representative success and error/denial observations; signed redacted artifact digest; comparator version; and independent reviewer/time. For writes, a callback or toast is insufficient without an authoritative readback and unknown-outcome handling. `NOT_APPLICABLE` requires proved absent gate and reviewer reason **for one case × matrix row**; a model-A absence cannot exclude model B. `BLOCKED` requires a concrete vendor, device or browser constraint; neither status may be inferred from a static route list.

Identity, authorization, side effects, errors, file contents and security failures have zero tolerance. Locale/time-zone display may normalize only after semantic timestamps are verified. Numeric media latency, image/audio similarity and push-delay thresholds remain **unfrozen** pending W01 APK baseline distributions and review, before web implementation uses them. A later APK, firmware, schema or tolerance change creates a versioned ledger amendment; it cannot overwrite a previous run.

### Frozen matrix and verified run contract

The code embeds the exact 77 seed IDs and test-compares them with [audit 12](apk-audit/12-functional-parity-contracts.md). Runtime-discovered suffix IDs need a discovery digest and reviewer and expand the required set. A release calculation also requires every case to be mapped to an applicable matrix row or a reviewed gate exclusion. `SupportMatrix.frozen_digest` is SHA-256 over canonical JSON of its version, sorted case IDs per matrix and sorted per-row gate proofs; review name/time and digest must be present and consistent. The candidate M01–M06 descriptions above are **not** a frozen matrix.

Each run has a unique ID plus an explicit attempt number and time. The latest attempt number controls the verdict regardless of input order; duplicate numbers or a time order conflict are rejected. A later `DIFFERENT` cannot be erased by passing an older `MATCHED` last. The case input digest must equal that run's fixture digest.

A `ComparisonReceipt` binds run ID, case ID, matrix ID, attempt, APK/web builds, fixture and redacted artifact digests, frozen matrix digest, tolerance digest, comparator version and verdict. A `GateProofReceipt` binds the proposed exclusion to its case ID, matrix ID, matrix digest, proof digest and reviewer. W00 can check these bindings but cannot authenticate their issuer, verify the underlying artifact or confirm semantic comparison. A plausible SHA-256 label and self-reported reviewer are insufficient. `calculate_parity` therefore treats every proposed gate exclusion and `MATCHED` receipt as **unverified**, counts neither toward parity, and has no caller-supplied verifier callback. It rejects run keys outside the listed cases or matrix. The static ledger checker likewise rejects every `MATCHED` and case-level `NOT_APPLICABLE` row. W24 must define the signed run/gate registry format, key and issuer trust, semantic comparator, artifact and gate verification, then add an independently validated integration before either status can count. No such registry or verifier exists in this W00 slice; release readiness remains false.

## Open evidence and anomaly register

- G-P0 remains open until 77 reachability decisions are reviewed against runtime paths; W01 has to map the 281 request classes, 299 native declarations and 25 ELF files as protocol inventory, not user-case count.
- G-P1 TVT bridge, rights and per-operation handoffs remain unproved; [operation contracts](tvt-operation-contracts.yaml) and [adapter coverage](tvt-adapter-coverage.csv) are static candidates.
- G-P4a browser platform preflight remains unverified; see [browser preflight](tvt-browser-preflight.md).
- P02.5, P14.3, P17.5, P18.6–P18.7 and P19.3 remain declaration-only. P13.1, P23.2–P23.3 and P24.1 have conditional code paths but no runtime result. P18.8–P18.9 have call sites with unresolved callback/results. [Audit 14](apk-audit/14-reachability-and-route-gaps.md) records each path.
- The [protocol and native audit](apk-audit/11-protocol-feasibility.md) flags the `/sdk/getDeviceLocalStorageStatus` route overwrite, empty image-code and VAS switch executors, empty cloud callbacks, five NAT zero-return stubs, unresolved JNI names/signatures and FCM refresh action mismatch. W01 must show each actual call edge or working alternate route; none is counted as an implemented or matched case from declaration alone.
- Downloaded household H5, remote settings H5, cloud/VAS payment and provider pages may expose additional atomic actions. Add discovered cases with stable suffix IDs, source, gate, owner and test evidence; never collapse them into an existing `MATCHED` row.
- Raw traces, credentials, device identifiers, media and signed evidence remain outside Git. This file will contain only redacted artifact digests and links when authorized runs exist.
