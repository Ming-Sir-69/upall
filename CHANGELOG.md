# Changelog

## 0.4.0 — 2026-10-30

- Give every tool a distinctive brand mark in its brand color (Claude Code's coral ✳, OpenAI green ❯, xAI 𝕏, π for Pi, and so on) across the TUI, the exit summary and plain output; truecolor terminals get exact colors, others get the nearest xterm-256 entry.
- Show a pixelated portrait rendered from the real macOS app icon in the log pane for Claude Desktop and ChatGPT (regenerate with tools/make_icons.py).

## 0.3.1 — 2026-10-30

- Show installed desktop applications (Claude Desktop, ChatGPT) in the default run as read-only "installed" entries instead of hiding them behind --list/--all; they no longer count as needing manual action.

## 0.3.0 — 2026-10-30

- Add the ChatGPT desktop app to the inventory next to Claude Desktop; desktop applications stay read-only and update themselves.
- Collapse by default: the exit summary prints one compact line when nothing failed and expands to the grouped digest only when failures exist; the log pane starts folded and unfolds on the first failure, while 3 still toggles it manually.

## 0.2.0 — 2026-10-30

- Print a grouped static summary (status, versions, elapsed time, failure detail) after the interactive UI exits, so results stay in the terminal scrollback and in unattended logs.
- Focus the first failed tool automatically when a round ends, and mark the log pane as paused while it is scrolled back.
- Color the overall progress bar by outcome (failures turn it red, a fully finished run turns it green) and inline each active or failed tool's latest log line into wide rows.
- Fall back to ASCII borders, spinners and status icons outside UTF-8 locales or when `UPALL_ASCII=1`.

## 0.1.1 — 2026-10-17

- Align state configuration with XDG: ignore a relative XDG_STATE_HOME, while preserving the explicit host override.
- Add a regression test for default/XDG/host configuration precedence.
- Document the official specifications and same-scenario extraction guidance behind repository, package, version and host integration decisions.

## 0.1.0 — 2026-10-17

- Publish the personal updater as an installable, dependency-free Python package.
- Discover known AI CLIs and their installation provenance; leave missing tools uninstalled.
- Check automatically, update with Space/1, exit with Enter/0, retry with 2 and toggle logs with 3.
- Support full-width keys, responsive layouts, per-tool logs and structured reports.
- Preserve original manager prefixes and verify installed versions after updates.
- Bound concurrent checks and serialize installs sharing a package-manager prefix.
- Isolate discovery/worker/PTY tests from real installations.
- Store state in a private per-user directory with exclusive atomic report writes.
- Add contribution, security and development documentation. Hosted Actions remain disabled.
- Define extracted-module ownership, environment configuration, commit pinning, host acceptance and rollback conventions for larger consuming projects.

