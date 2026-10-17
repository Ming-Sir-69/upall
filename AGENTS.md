# UPALL development

- Preserve the default contract: discover and check automatically, Space/1 updates available items, Enter/0 exits, 2 retries failures, 3 toggles logs. Support full-width aliases and existing letter keys.
- Runtime dependencies stay in the Python standard library. macOS is the tested platform; do not claim untested native Windows support.
- Never run real software installations, updates, or desktop input automation as part of tests. Use isolated fixtures and PTYs. Read-only live version checks are allowed.
- Preserve installation provenance: use the detected executable, package and manager prefix. Unknown/local installs require manual handling; missing tools must stay missing.
- Changes to command execution, downloads, state files or discovery require security review and relevant tests. Treat logs and remote metadata as untrusted.
- Run `python3 -m unittest discover -s tests -v` and the package build/install smoke test before release. Use a feature branch and PR for subsequent changes; keep main releasable.
- Keep personal paths, credentials, provider settings and runtime reports out of Git. Do not enable Actions, Pages, Packages, Codespaces, paid scanning or other metered services without explicit authorization.
- Update CHANGELOG.md and relevant docs when user-visible behavior changes. Use MIT-compatible contributions and credit sources; do not copy third-party implementation without its license.
- This repository is an extracted reusable module. Parent-project configs, absolute paths, credentials, private records and deployment locks stay outside it. The public module is the sole implementation source; update a consuming project's pinned revision only after its own integration acceptance. See docs/module-integration.md.
