# Changelog

## 0.14.1 — 2026-11-15

- Fix missed Kimi Code releases when the native download site's `latest` marker trails the official npm channel. Query the official package metadata without requiring npm, validate the matching native platform manifest, and pass the exact checked version and detected install directory to the official installer.
- Keep the actual remote version visible when the installed version is newer. Report `AHEAD` (本机较新) instead of replacing the target with the installed version and incorrectly saying 已是最新. Such installations are never downgraded.

## 0.14.0 — 2026-11-13

- Add Cursor Agent to AI 编程工具: discover the official `~/.local/share/cursor-agent/versions/` layout (and the short `agent` name only when it resolves into that tree), check with `cursor-agent about --format json` (`cliVersion` / `latestVersion`), and update with the vendor's `cursor-agent update`.

## 0.13.0 — 2026-11-14

- Make downloads resilient on routes with slow single connections: aria2c uses eight resumable connections when installed, with a clean curl retry fallback. Native Claude Code updates download the vendor's versioned manifest and binary through the same path, prefer the smaller official zstd package when available, and verify both compressed and uncompressed checksums before installation.
- npm version checks and installations try a direct connection first, then retry through the inherited proxy environment. Existing package managers, prefixes and release channels are preserved.
- Record every metadata request, version check, download and npm installation in the tool log and the job's structured `network` report, including route, tool, attempt, elapsed time, bytes, throughput and failure reason. Append each run to `history.jsonl`; `latest/report.json` remains the latest-run view.
- Verify CC Switch's GitHub-published sha256 digest when the release provides one, in addition to the existing bundle signature and Developer ID team checks.

## 0.12.0 — 2026-11-12

- Host config gains `after_update`: a command run after a tool's successful update to re-apply only our modification on top of the new release. Unlike `preserve`, which freezes a whole copy (vendor files included) at the old release, this keeps our change ours and lets everything else follow upstream. Hooked tools count in the 本地修改 column.

## 0.11.3 — 2026-11-12

- Fix grouped scrolling: the repeated group header at the top of a scrolled list no longer pushes the selected tool off the bottom (the last tool of the last group could not be seen), and the list budget now counts the table header line, so the 空格/1 更新 hint is no longer cut in medium-height panes.

## 0.11.2 — 2026-11-11

- The 本地修改 column shows 无 when nothing local remains instead of repeating the detail note.

## 0.11.1 — 2026-11-11

- Git convergence also archives the feature branch it leaves when upstream has absorbed all of its commits, instead of leaving a redundant branch behind.

## 0.11.0 — 2026-11-11

- Agent plugins and maintenance tools join the catalog: KimiCU, Kimi WebBridge, iPhone Use, Agent Desktop, Mole and CC Switch, each through its vendor's own update channel. App bundles (KimiCU, CC Switch) are swapped only after sha256 (when published), strict code-signature and same-team checks, with the previous bundle kept as a rollback copy.
- The table is grouped: AI 编程工具, Agent 插件与技能, 效率与维护 and 本机项目, each header showing its count and how many can update. `upall agent` / `-g app` limit a batch to a group. Up to four checks run in parallel.
- Host-defined tools in an owner-only JSON config (adapter commands or git checkouts) and a new 本地修改 column: UPALL tells which local modifications upstream has absorbed (use upstream) and which are still ours (keep them), predicts conflicts and leaves conflicting work untouched. See docs/local-modifications.md.
- Customised copies listed under `preserve` (for example a slimmed agent skill) survive an upstream refresh; symlinked skill copies stay symlinks after Kimi WebBridge upgrades.

## 0.10.0 — 2026-10-30

- Remove the desktop application module (by owner decision): Claude Desktop and ChatGPT leave the catalog, so upall is CLI-only again. The download speed of desktop packages was dominated by the local network route and the feature was not worth its complexity.
- Content-sized table columns and the retrying download behavior for CLI tools are unchanged.

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

