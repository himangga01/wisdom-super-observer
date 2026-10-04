# Codex CLI Status Line Configuration

Date: 2026-09-27

The global `C:\Users\강지혜\.codex\config.toml` now contains:

```toml
[tui]
status_line = ["current-dir", "model-with-reasoning", "context-used", "context-remaining", "five-hour-limit", "weekly-limit"]
```

This orders the footer as current directory, model with reasoning effort, context used, context remaining, five-hour limit, and weekly limit. The identifiers were checked against the installed Codex CLI 0.157.1 binary. A direct file read confirmed one `status_line` entry and preserved `daemon_auto_start = false`. No shell command was launched for this change.

OpenAI documentation describes `/statusline` and the `tui.status_line` configuration key: [Developer commands](https://learn.chatgpt.com/docs/developer-commands), [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). The current TUI may require its interactive `/statusline` command or a restart to redraw after an external config edit; live reload was not tested.
