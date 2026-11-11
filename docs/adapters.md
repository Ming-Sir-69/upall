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
| KimiCU | App bundle KimiCU.app (bundle id ai.kimi.cu) in /Applications or ~/Applications |
| Kimi WebBridge | ~/.kimi-webbridge/bin/kimi-webbridge (official daemon layout) |
| iPhone Use | iphone-use inside iPhoneUse.app, or a PATH link to it |
| Agent Desktop | Matching global npm package agent-desktop |
| Mole | Official script install (lib/ next to the entry or pinned SCRIPT_DIR) or Homebrew formula |
| CC Switch | App bundle CC Switch.app (bundle id com.ccswitch.desktop) |

Tools are shown in groups: AI 编程工具 (cli), Agent 插件与技能 (agent), 效率与维护 (app) and 本机项目 (host). `upall agent` or `upall -g app` limits a batch to one group.

Unknown provenance and project-local dependencies are manual. A discovered executable that cannot run is a query failure rather than an instruction to reinstall. Source package aliases do not automatically migrate between namespaces.

## Network and execution

- Global npm: query package metadata using npm view; update the same package with the same npm prefix.
- Homebrew: query brew info; update the detected formula/cask only.
- Claude native: query the appropriate npm distribution channel; run the detected claude update. Stable/latest settings are read without exporting provider configuration.
- Kimi script: query https://code.kimi.com/kimi-code/latest and download the official installer from https://code.kimi.com/kimi-code/install.sh only during an update.
- Hermes source: invoke its own source-check module and update --yes, preserving its configured channel.
- OpenClaw: invoke update --dry-run --json to find its target and update --yes to apply.
- OpenCode native: invoke upgrade --method curl.
- Grok native: invoke update.
- KimiCU: read https://cdn.kimi.com/kimi-computer-use/latest/version.json; during an update download that package only from cdn.kimi.com, require its sha256, a strict code signature and the same Developer ID team as both the manifest and the installed copy, swap the bundle (previous copy kept under the state root's backups/), then restart its launchd service.
- CC Switch: read the GitHub latest release of farion1231/cc-switch; download its -macOS.zip from github.com, require a strict signature from the installed copy's team, quit the running app politely, swap the bundle and reopen it in the background.
- Kimi WebBridge: read `kimi-webbridge status` (daemon version, update_available, version_mismatch pairing with the browser extension) and run `kimi-webbridge upgrade`; skill copies that were symlinks are restored as symlinks afterwards.
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


## Host-defined tools

Projects the host maintains itself (forks, overlays, custom install layouts) are declared in an owner-only JSON file, $UPALL_CONFIG or $XDG_CONFIG_HOME/upall/tools.json. A definition with the id of a built-in tool replaces it. See [local modifications](local-modifications.md) for the format and how UPALL decides between upstream and our own changes. Isolated runs (UPALL_SEARCH_PATH set) never read the default file.
