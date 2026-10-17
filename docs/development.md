# Architecture and development

The package is intentionally small and uses only Python's standard library at runtime.

| Module | Responsibility |
|---|---|
| discovery.py | Known catalog, executable resolution, package-manager/native provenance |
| models.py | Job snapshot data |
| engine.py | Version queries, explicit updater invocation, timeouts, process groups, install locks |
| terminal.py | Incremental keyboard decoder, input handling, responsive frame |
| util.py | Unicode display helpers, sanitized logs, private state and atomic reports |
| cli.py | Arguments, root lock, mode selection, output and batch lifecycle |
| __main__.py | Console/module entry and platform/error handling |

The check/update distinction belongs to the engine; rendering must not trigger an installation by itself. A completed check marks available jobs. Space/1 starts a new batch with those jobs only. Retry uses the current mode: recheck during checks, reinstall during an update retry.

Inventory writes to inventory/, leaving latest/ intact. A live process holds the root lock while it owns a check/update batch and its UI. A second process refuses to start a competing batch.

## Tests

Run python3 -m unittest discover -s tests -v. The runner invokes discovery, worker and PTY scenarios with isolated fake tools. Unit regression checks cover private state, symlink rejection, atomic replacement and terminal-control filtering.

The tests must not execute real software updates. The read-only --list and version-query smoke tests validate the actual host separately. Fixture coverage is not a claim of live validation for all vendors.

## Decisions

- A Chinese-first keyboard flow avoids making letter keys the sole way to leave a completed screen.
- Numbers stay visible even when an action is currently unavailable; pressing it gives feedback instead of silently renumbering.
- One Python renderer replaces shell subprocesses per frame. Updates remain vendor-specific.
- Provenance is a prerequisite to an updater: a Homebrew bin path can point into npm.
- Private persistent state replaces a predictable shared /tmp location for the public package.
- No global shell configuration is modified by the package installer.
- Hosted automation is not needed for this project's initial scale; local tests avoid consuming shared runner quotas.

The implementation originated as a personal macOS shell helper. Git history begins with the portable package, not with private machine configs or session logs.

## Adding a tool

Add catalog/package identities and bounded discovery. Define its current-version probe, target-channel query, explicit updater and version verification. Add fixtures for installed/missing/unknown provenance and the update path. Document network endpoints and whether support was tested live or through fixtures. Do not add automatic installation as a fallback.

Avoid changing compatibility entry points, the default check-first flow or unrelated adapters during a routine addition.

