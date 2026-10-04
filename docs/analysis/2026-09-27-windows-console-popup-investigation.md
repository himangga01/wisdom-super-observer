# Windows Console Popup Investigation (2026-09-27)

## Observations

- The user saw visible console windows during a five-command test run through `exec_command` with `cmd.exe`, `login: false`, and `tty: false`. Earlier default PowerShell calls also opened visible windows. All five commands completed successfully; successful execution did not imply a quiet launch.
- The locally installed npm package `@openai/codex` reports version `0.157.1` in its `package.json`.
- The user observed a new daemon startup message when launching Codex.
- A residual OpenCode Orca status plugin and empty Orca folders were removed. Checks found no remaining Orca entries in the examined Claude/Codex settings, startup entries, PowerShell profiles, scheduled tasks, or environment variables. The popup persisted after that cleanup.

## Likely cause and evidence

The observations align with a reported Windows Codex CLI `0.157.1` regression in which the daemon-backed session flashes visible child console windows. The upstream report says `codex --no-daemon` stopped the flashing in its reproduction. This is a close match, not proof that every popup on this PC has the same parent process.

- [Codex issue #48422: Windows console windows on 0.157.1](https://github.com/openai/codex/issues/48422)
- [Codex issue #48070: startup and command popups on 0.156.x/0.157.0](https://github.com/openai/codex/issues/48070)
- [Codex issue #26613: desktop background PowerShell console flashes](https://github.com/openai/codex/issues/26613)

## Changes made

- Set `[features] daemon_auto_start = false` in the global `C:\Users\강지혜\.codex\config.toml`. A direct file read confirmed exactly one `[features]` section and the new value.
- Updated the global `C:\Users\강지혜\.codex\AGENTS.md` to forbid both PowerShell and CMD routes through `exec_command` on this host until a quiet path is verified.
- Continued inspection and edits through non-shell tools, without another console command.

## Verification and remaining check

The configuration and instruction files were verified by direct reads. The active Codex session may retain its existing daemon connection, so the popup fix has **not** been confirmed on this PC. To check the reported workaround, exit the current CLI session and start a new session from the existing terminal with `codex --no-daemon`, then perform normal work and observe whether another console window appears. Do not terminate the active daemon from this session because it may be serving other work.

Disabling automatic daemon startup may not prevent a new CLI session from attaching to an already running daemon. The explicit `--no-daemon` flag is the more reliable check for the next launch. The desktop app may have separate popup paths documented in issue #26613.

## Post-reconnect tool check

After the user reconnected, three non-shell operations completed: repository listing, direct reads and SHA-256 hashing of three project documents, and direct reads of the Codex setting and Git `HEAD`. The setting still reads `daemon_auto_start = false`, and `HEAD` points to `refs/heads/main`. These checks establish that routine read work can proceed without invoking PowerShell or CMD. Whether any visible window appeared is for the user to confirm; no command execution or popup-free claim is implied.

A second check completed four further direct reads: analysis-directory listing, report inspection, persistent setting inspection, and Git reference inspection. The user confirmed that no new PowerShell/CMD window appeared during this second check after reconnecting with `--no-daemon`. This verifies the observed result for non-shell work in the new session; shell-command execution remains untested under the standing no-popup instruction.

## Cross-app resume warning

When the user ran `codex resume --last --no-daemon`, the terminal displayed: “This conversation is open in another app. Close it there and press R to continue here.” The message indicates that the selected conversation is already open in another app. The official [developer commands documentation](https://learn.chatgpt.com/docs/developer-commands) says `resume --last` selects the most recent chat in the current working directory. Since this conversation is open in the desktop app, selecting it from the CLI is a plausible cause. The screenshot alone does not establish any failure of `--no-daemon` or a return of the console-popup problem.

To continue the same conversation in the CLI, close this conversation in the other app, then press `R` in the waiting CLI. To stay in the desktop app, dismiss the waiting CLI instead. This handoff has not been tested on this PC; do not claim it is resolved until the user confirms the result.
