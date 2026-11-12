# UPALL development

- Preserve the default contract: discover and check automatically, Space/1 updates available items, Enter/0 exits, 2 retries failures, 3 toggles logs. Support full-width aliases and existing letter keys.
- Runtime dependencies stay in the Python standard library. macOS is the tested platform; do not claim untested native Windows support.
- Never run real software installations, updates, or desktop input automation as part of tests. Use isolated fixtures and PTYs. Read-only live version checks are allowed.
- Preserve installation provenance: use the detected executable, package and manager prefix. Unknown/local installs require manual handling; missing tools must stay missing.
- When changing command execution, downloads, state files or discovery, add relevant tests and re-check the trust boundaries listed in docs/security-review.md yourself. Treat logs and remote metadata as untrusted.
- Run `python3 -m unittest discover -s tests -v` and the package build/install smoke test before release. `main` is branch-protected (PR required, zero approvals, linear history, resolved conversations): push a feature branch, open a PR and merge it yourself; keep main releasable.
- Keep personal paths, credentials, provider settings and runtime reports out of Git. Validation is local: Actions, Pages, Packages, Codespaces and paid scanning are off because they are metered.
- Update CHANGELOG.md and relevant docs when user-visible behavior changes. Use MIT-compatible contributions and credit sources; do not copy third-party implementation without its license.
- This repository is an extracted reusable module. Parent-project configs, absolute paths, credentials, private records and deployment locks stay outside it. The public module is the sole implementation source; bump a consuming project's pinned revision once its own integration check passes. See docs/module-integration.md.
