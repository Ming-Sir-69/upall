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
| Claude Desktop | Inventory only; updates belong to the desktop application |

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

