# Changelog

## 0.9.0 — 2026-10-30

- Desktop packages now download with aria2c's segmented multi-connection transfers when it is installed (8 connections, resumable via its control file); single connections to the vendor CDN were throttled to KB/s while segments reach MB/s. The retrying curl downloader remains as the fallback.
- Desktop updates show live download progress in the table (downloaded MB, feed-advertised total, once-a-second speed sample), so a slow or stuck transfer is visible instead of looking dead.

## 0.8.1 — 2026-10-30

- Harden desktop downloads against flaky routes: retries with backoff, resume of partial downloads and a longer connect timeout replace the previous single-attempt download that died on the first SSL timeout. Update-feed checks get the same retry treatment.
- Size table columns to content and terminal width: tool names and versions keep their natural width when the frame allows it (Claude Desktop is no longer truncated at 80 columns), the label column shrinks first when space is tight, and the inline log tail uses the remaining room.

## 0.8.0 — 2026-10-30

- Desktop applications can now be updated directly with Space/1: a newer Claude Desktop or ChatGPT release with a trustworthy package URL becomes AVAILABLE instead of a manual hint. upall downloads the app's own official update package, verifies it (sha256 for Claude; exact size plus a pinned vendor download host for both), swaps the application bundle, and confirms the new version afterwards.
- Updating a desktop app requires it to be quit first (a running app is left untouched with a retry hint). The previous bundle is moved to the Trash, never deleted.

## 0.7.0 — 2026-10-30

- Desktop applications now check for updates: Claude Desktop via its releases.claude.com feed, ChatGPT via its Sparkle appcast. Up-to-date apps report CURRENT with the feed version; a newer release becomes a manual entry asking to update inside the app. upall still never installs desktop updates itself, and inventory mode stays offline.
- Update-feed requests use a fresh anonymous id per call and remote version metadata is validated before use.

## 0.6.0 — 2026-10-30

- Return to the plain 0.3.x presentation: no per-tool glyphs, pixel portraits or brand colors; the table, exit summary and plain output use status-colored text only, as before the brand-mark experiments.

## 0.5.0 — 2026-10-30

- Drop all icon artwork: tools are told apart by brand color alone. Tool labels now carry the brand color in the TUI, the exit summary and plain output, replacing the per-tool glyphs.
- Remove the log pane's pixelated app-icon portraits along with the offline icon-generation tooling.

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

