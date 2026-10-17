# Changelog

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

