# Contributing to UPALL

Use an issue to describe a reproducible bug or a scoped feature, then a feature branch and pull request. Do not attach raw provider configs, credentials, or personal session history.

## Local checks

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
~~~

The integration scenarios create fake tools in temporary directories and use PTYs. Never substitute a real npm install, CLI update, or GUI keystroke test. Read-only live version checks are optional and should be labeled as such.

For packaging, use uv build, then install the resulting wheel in an empty virtual environment and check upall --version and upall --demo --json. Build artifacts are not committed.

## Compatibility

- Check automatically; install only after an update action or --update.
- Preserve Space/1 update, Enter/0 exit, 2 retry, 3 logs, full-width keys and legacy letter aliases.
- Do not infer manager ownership only from a bin directory name. Unknown/local sources require manual handling.
- Add both discovery and updater fixtures for a new adapter. Keep the runtime dependency-free.
- Preserve signal cleanup, locks, JSON status identifiers and separate inventory reports.
- Explain any new network endpoint or executed command in docs/adapters.md.
- Update CHANGELOG.md for user-visible changes.

## Reviews and release

Keep main releasable, use squash merges, and resolve review conversations. The maintainer may merge a self-authored PR without a second approval. Do not force-push or delete main.

Before a release: run tests and a clean wheel-install smoke test, inspect the tracked diff for secrets/private paths, review command/file/network trust boundaries, and update the version and changelog together.

No hosted CI or automatic deployment is configured. Do not enable Actions, Pages, Packages or other metered services as part of a routine contribution.

Contributions are under the MIT license.

