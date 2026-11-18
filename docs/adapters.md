# Tool adapter support

Discovery checks PATH and bounded common installation directories, plus explicit overrides. UPALL_SEARCH_PATH disables fallback directory discovery. The first selected command is the target; UPALL does not silently upgrade every duplicate installation.

| Tool | Known automatic paths |
|---|---|
| Claude Code | Official native launcher, matching global npm package, known Homebrew cask |
| Codex | Matching global npm package, known Homebrew package, identified native path |
| Kimi Code | Known official script layout |
| Hermes | Source checkout resolved from its executable or simple forwarding launcher |
| Gemini CLI | Matching global npm package or known Homebrew formula |
| Grok Build | Matching global npm package or official native layout |
| OpenCode | Matching npm package, known Homebrew formula, official script layout |
| OpenClaw | Matching npm/Homebrew provenance; uses its own dry-run/update protocol |
| Pi | Known npm package namespace or known Homebrew formula |
| MiniMax Code | Matching npm package or known official installer root |
| Cursor Agent | Official native layout under ~/.local/share/cursor-agent/versions/; short name `agent` only when it resolves into that tree |
| KimiCU | App bundle KimiCU.app (bundle id ai.kimi.cu) in /Applications or ~/Applications |
| Kimi WebBridge | ~/.kimi-webbridge/bin/kimi-webbridge (official daemon layout) |
| iPhone Use | iphone-use inside iPhoneUse.app, or a PATH link to it |
| Agent Desktop | Matching global npm package agent-desktop |
| Mole | Official script install (lib/ next to the entry or pinned SCRIPT_DIR) or Homebrew formula |
| CC Switch | App bundle CC Switch.app (bundle id com.ccswitch.desktop) |

Tools are shown in groups: AI 编程工具 (cli), Agent 插件与技能 (agent), 效率与维护 (app) and 本机项目 (host). `upall agent` or `upall -g app` limits a batch to one group.

### Monitor kinds (orthogonal to groups)

Display groups are not the same as monitor kinds. Monitors select *what kind of capability* to check:

| Kind | Meaning | Default |
|---|---|---|
| `runtime` | Programming-tool binaries themselves | on |
| `plugin` | Host-extension plugins (placeholder this iteration) | off |
| `skill` | Skill sync / fingerprint checks | on |
| `mcp` | MCP cache / registry checks | on |

CLI: `upall --monitor runtime,skill,mcp` (comma-separated, repeatable). Combine with `-g/--group` when both filters are useful. Defaults come from `~/.config/upall/monitors.json` (`{"enabled":["runtime","skill","mcp"]}`), or a `monitors` field in the host tools JSON; missing config uses the AI default set above. Host tool entries may set `"monitor": "runtime"` (or another kind).

The default TUI stays check-first and thin: monitor toggles are not dumped onto the home list. Press **4 / S** for the settings panel (toggle kinds, see MCP/Skill layer status for this run). Also discoverable via `--monitor` and this doc (Sony-camera logic). Changes saved to `monitors.json` apply on the next `upall` launch. Missing tools stay missing; discovery never installs.

Unknown provenance and project-local dependencies are manual. A discovered executable that cannot run is a query failure rather than an instruction to reinstall. Source package aliases do not automatically migrate between namespaces.

## Network and execution

- Global npm: query package metadata using npm view; update the same package with the same npm prefix via `upall.installers.npm_global` (shared prepare → install → one layout-conflict retry). Leftover `lib/node_modules/.<slug>-*` rename dirs and broken `prefix/bin` links are cleared before install so ENOTEMPTY/EEXIST from a prior failed upgrade cannot stick. Per-tool extras (allow-scripts) live in `NPM_INSTALL_OPTIONS`. Try direct networking first, then the inherited proxy environment.
- Homebrew: query brew info; update the detected formula/cask only.
- Claude native: query the appropriate npm distribution channel, then download the exact target from the vendor's versioned manifest. Use aria2c's eight connections when available, prefer the official zstd package when zstd is installed, verify both compressed and uncompressed sha256/size, and run the verified binary's install command for the same target version. Stable/latest settings are read without exporting provider configuration.
- Kimi script: query the official `@moonshot-ai/kimi-code` latest metadata at registry.npmjs.org using curl (npm is not required), then validate the exact version's native manifest at https://code.kimi.com/kimi-code/binaries/VERSION/manifest.json for this platform. The native `/latest` marker can lag published releases. Download the official installer from https://code.kimi.com/kimi-code/install.sh only during an update; pin its `--version` and install directory to the checked version and detected installation. Unavailable or malformed release metadata fails the check instead of falling back to an old version.
- Hermes source: invoke its own source-check module and update --yes, preserving its configured channel.
- OpenClaw: invoke update --dry-run --json to find its target and update --yes to apply.
- OpenCode native: invoke upgrade --method curl.
- Grok native: invoke update.
- Cursor Agent native: invoke `about --format json` for `cliVersion` / `latestVersion`, then `update`.
- KimiCU: read https://cdn.kimi.com/kimi-computer-use/latest/version.json; during an update download that package only from cdn.kimi.com, require its sha256, a strict code signature and the same Developer ID team as both the manifest and the installed copy, swap the bundle (previous copy kept under the state root's backups/), then restart its launchd service.
- CC Switch: read the GitHub latest release of farion1231/cc-switch; download its -macOS.zip from github.com, verify its published sha256 when present, require a strict signature from the installed copy's team, quit the running app politely, swap the bundle and reopen it in the background.
- Kimi WebBridge: read `kimi-webbridge status` (daemon version, update_available, version_mismatch pairing with the browser extension) and run `kimi-webbridge upgrade`; skill copies that were symlinks are restored as symlinks afterwards. When the `skill` monitor is on, a confirmed upgrade also aligns drifted *copied* WebBridge skill trees across hosts (symlinks / self-maintained trees stay untouched).
- MCP / Skill layers (`upall.layers`): with monitors `mcp` / `skill` enabled, `report.json` gains a `layers` object — npx MCP cache vs npm registry (check-only, never rewrites MCP config) and WebBridge skill fingerprints / sync plan. Not a TUI switch wall; discover via `--monitor` and JSON.
- iPhone Use: `iphone-use upgrade --json` to check and `iphone-use upgrade` to apply.
- Mole: newest V<x.y.z> GitHub release of tw93/Mole (prereleases and platform tags ignored); `mo update` for script installs, brew upgrade for Homebrew.
- MiniMax script: download https://filecdn.minimax.chat/public/install.sh; retain the detected install root and suppress persistent PATH edits.

Official upstream references:
[Claude](https://code.claude.com/docs/en/setup),
[Gemini](https://geminicli.com/docs/get-started/installation/),
[OpenCode](https://opencode.ai/docs/cli/),
[OpenClaw](https://docs.openclaw.ai/cli/update),
[Pi](https://pi.dev/),
[MiniMax](https://github.com/MiniMax-AI/minimax-code).

## Validation limits

The initial live environment validated Claude, Codex, Kimi and Hermes detection/checks; one Claude update was observed during personal use. Other adapters have fixture coverage, not a full matrix of real operating systems, installation variants and network policies.

Strict revision equality for Hermes and fast-moving release channels can need refinement if a new release appears between check and installation. No downgrade is intended. Compare the exact target in the log before reporting an updater bug.

When the installed version is newer than the queried channel, the job keeps both version values and reports `AHEAD` (本机较新). This can mean the chosen stable channel lags the installation or its metadata is stale; it does not prove that no newer release exists. Neither the default check nor an explicit update downgrades these jobs.


## Host-defined tools

Projects the host maintains itself (forks, overlays, custom install layouts) are declared in an owner-only JSON file, $UPALL_CONFIG or $XDG_CONFIG_HOME/upall/tools.json. A definition with the id of a built-in tool replaces it. See [local modifications](local-modifications.md) for the format and how UPALL decides between upstream and our own changes. Isolated runs (UPALL_SEARCH_PATH set) never read the default file.
