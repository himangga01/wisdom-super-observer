# Project instructions

## Personal working preferences on this Windows PC

- Keep completing requested work. Prefer purpose-built or direct filesystem tools for routine inspection and edits.
- Do not reinstall Orca or its Claude/OpenCode status hooks unless explicitly requested.
- Keep application source, tests, dependency manifests/locks and project reports tracked. Ignore generated/runtime/private files through `.gitignore`; do not hide unfinished source changes with ignore rules. `pnpm typecheck` regenerates the ignored Next.js declarations before checking types.

## Analysis reports and cross-agent handoff

- Canonical service-analysis report: `docs/service-analysis.md`.
- Established Windows TVT library analysis: `docs/integrations/tvt-windows-native-options.md`; recovered raw transport ABI: `docs/integrations/tvt-windows-socket-abi.md`.
- Windows private provider implementation/verification reference: `docs/integrations/tvt-windows-socket-provider.md`; use the canonical service report for current source-review and actual-execution outcomes.
- Established local APK connection-source analysis: `docs/integrations/tvt-local-device-connection-source.md`; local credential codec reference: `docs/integrations/tvt-local-n9000-codec.md`.
- Private local channel/identity/permission codec reference: `docs/integrations/tvt-local-inventory-codec.md`. Source review alone does not establish current actor binding or live authority; use the canonical service report for actual execution.
- Private raw live wire codec reference: `docs/integrations/tvt-local-live-codec.md`. Keep source-review qualifications, conservative receive bounds and actual frame/decode acceptance separate in the canonical service report.
- Windows decoder implementation reference: `docs/integrations/tvt-windows-decode.md`. Native synthetic proof, independent source acceptance and actual CCTV decoding are separate; read the canonical service report for current open review findings.
- Local device credential registration and browser QR input reference: `docs/integrations/tvt-local-device-registration.md`. Reuse it before changes and update affected evidence afterward; encrypted storage, actual device verification and web live playback remain separate outcomes in the canonical service report.
- Local TVT public service integration design and milestone reference: `docs/integrations/tvt-local-service-integration.md`. Read it with the canonical service report and registration guide before changes; update affected source and execution evidence afterward. Keep proposed contracts, implemented code, native execution and browser acceptance separate.
- Local device API/RPC implementation reference: `docs/integrations/tvt-local-device-api.md`; real Windows capture/decode acceptance: `docs/integrations/tvt-windows-live-acceptance.md`. Read these with the canonical service report before changing their layers, then update affected evidence. Bounded native captures do not establish continuous browser playback.
- Windows-hosted Android runtime evidence: `docs/integrations/tvt-windows-android-runtime.md` and `docs/integrations/tvt-windows-aosp-arm-runtime.md`. Use the service report for current executed status; preserve the guides' dated source evidence.
- Before every requested substantive analysis, read `C:/Users/강지혜/.agents/analysis-policy.md`, this file and the relevant existing analysis report.
- Owned local-device OWNER browser runtime: `docs/integrations/tvt-local-device-browser-runtime.md`. Read with the canonical service report before reuse, then update actual Chrome, source stability and resource cleanup outcomes; fixture readiness alone is not device acceptance.
- Use `docs/code-analysis.md` for a new code-analysis report and `docs/analysis/<topic>.md` for other new analyses when no established report exists. Record additional canonical paths here when created.
- For later service-analysis requests, start with this English Markdown report, verify its source baseline, current working-tree changes and newer evidence, and refresh affected sections.
- Before the final reply, update the relevant portable project Markdown report with the current findings, evidence, verification commands, actual limits and a dated update log. A chat-only answer or ignored scratch evidence is insufficient.
- Include analysis date, source baseline, service purpose, architecture, implemented behavior, risks, priorities, open product questions, evidence and actual verification limits.
- Distinguish planned behavior from implemented code and executed acceptance. Never include secret values or API key contents.
- Preserve unrelated instructions and historical review evidence.
- Other agent entry points should link to this file and the canonical reports using a short bridge; portable project Markdown remains the common analysis authority.
