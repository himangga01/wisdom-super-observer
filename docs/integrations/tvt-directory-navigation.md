# Protected devices startup navigation

Implementation date: 2026-10-03 (Asia/Seoul). Historical task baseline: `d1ce6b148bb88656f656c3e529a2898bb152bef4`. This additive navigation stage consumes the current root accepted directory API/proxy, worker/RPC and UI Fix1 source checkpoints. The frozen evidence records the exact consumed hashes and the approved generated contract preimages.

The existing protected `/tvt/[[...path]]` entry now composes the actual React `DirectoryPage` on `/tvt/devices`. Startup still derives its user, selected tenant and CSRF from the existing server authority. The shell retains its existing QueryClient lifetime, consent updates, startup requery and authorization teardown. It passes its actual `userId`, authoritative `bootstrap`, `csrf`, and `requery: () => Promise<Bootstrap>` to the directory component.

## Trusted deployment opt-in

Devices is unavailable by default. An operator must review the complete existing `StartupProfile` and explicitly include `/tvt/devices` in its `local_routes`. For a deployment that registers all three existing local surfaces, the relevant profile field is:

```json
{"local_routes": ["/tvt/settings", "/tvt/account", "/tvt/devices"]}
```

This is a fragment of deployment configuration, not an HTTP request body or a complete usable profile. Existing APK source binding, HTTPS policy references, consent revision, brand, region, locales and timezone validation still apply. This implementation does not change or activate runtime configuration. Missing `local_routes` remains an empty list; profiles that only opt into settings/account retain those entries. Duplicates, unknown paths, trailing slashes, query-bearing paths and lists over three entries are rejected. Provider flags and URL parameters cannot enable devices.

Startup publishes the exact third tuple `local-devices` / `Devices` / `/tvt/devices`. The browser bootstrap parser checks the tuple as a unit and rejects cross pairing, duplicates and excess entries. The Korean `장치` link and deep-link resolver independently require all three tuple members. Links preserve the selected tenant and identify the active page accessibly. The existing wrapping navigation and WSO card/button tokens remain in use.

## Data and authority boundaries

An unregistered direct devices deep link renders the existing safe unavailable page and mounts no DirectoryPage. Signed out users and users without a selected tenant make no personalized startup or directory request. Opt-in users without accepted current consent or a linked account make no directory request. Even an admitted directory waits for explicit linked identity selection and an explicit query. Startup publishes only existing account references; it adds no token, credential, provider capability or native data.

The tuple permits navigation only. The approved DirectoryPage enforces current consent/identity and uses the existing six readonly directory client operations. API and worker boundaries continue to enforce current web session, tenant, identity and generation authority. Requery calls the existing startup fetch using the current shell scope; a 401/403 still cancels and clears the shell. It does not fabricate refreshed data or introduce another session, QueryClient, transport or alternate public page. A user or tenant scope change remounts the existing provider and directory lifetime.

## Verification and limits

The navigation report and evidence packet under `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/` record causal Python/browser RED, focused GREEN, command argv/timestamps/exits, full typecheck, scoped ESLint/Ruff/format/strict mypy and exact source inputs. Shell checks use real DirectoryPage, directory client and startup client with synthetic HTTP responses to demonstrate selected tenant, linked identity, CSRF, explicit query and current-authority requery. They cover exact pairing, rejected direct links, missing consent/identity, vendor flag non-enabling, current user scope and old settings/account navigation. The four existing PostgreSQL persistence cases are intentional opt-in skips; no DB acceptance is required or executed for this additive route.

Actual app OpenAPI and the pinned existing 21-contract export set are generated twice. Only `StartupMenuEntry` enums and `StartupBootstrap.menu.maxItems` evolve; existing paths and all other schemas, including directory/account/phone, remain structurally equal. Only the transferred `openapi.json` and `tvt.ts` may change; the other 19 exports are byte identical to their consumed preimages.

This is source and synthetic unit verification. Root must still independently review/publish this lane, configure a reviewable runtime profile, and perform direct Windows server/Chrome acceptance. Browser rendering, live vendor/device/APK comparison and release acceptance are not established here. `MATCHED=0`; `release_ready=false`.
