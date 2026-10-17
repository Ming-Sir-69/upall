# Integrating UPALL as an extracted module

UPALL originated inside a larger private workspace. The open-source repository is the authoritative source of the reusable module, while the original project continues as a consumer. Extraction does not make the parent project public or move its configuration into the module.

## Ownership and repository boundaries

| Public module repository | Consuming parent project |
|---|---|
| Generalized implementation, CLI/JSON contracts, adapter catalog | Shell shortcuts, installation location, private local settings |
| Isolated tests, build metadata, public examples and documentation | Dependency lock, deployment receipt and host-specific acceptance |
| Module version, license, public changelog and issue/PR workflow | Personal observations, work history, provider configuration and credentials |
| Environment-variable interface and platform defaults | Actual environment-variable values for that host |

There is one implementation source. Do not maintain a copied implementation in both repositories and synchronize changes in two directions. A host-specific workaround belongs in a thin host adapter until it can be generalized, tested and merged upstream.

The MIT license applies to the published module contents. It does not publish or license undistributed files from its parent workspace.

## Recommended checkout and installation model

Use a separate UPALL checkout for module development. Install a pinned upstream revision into an isolated tool environment for the parent project. Its shell shortcut invokes the installed console command instead of a private copy of module internals.

~~~text
private parent project
  integration/upall.lock.json     # upstream URL, version, full commit, host acceptance
  local shell/config adapter     # private values and stable command entry
           |
           +--> isolated upall-cli installation pinned to a full commit

public upall repository
  src/upall/                     # sole implementation source
  tests/                         # isolated module tests
  docs/                          # public contracts, not private host values
~~~

For example, with an actual reviewed commit substituted for COMMIT:

~~~sh
uv tool install 'git+https://github.com/Ming-Sir-69/upall.git@COMMIT'
upall --version
upall --demo --json
upall --list --json
~~~

The lock should include the repository URL, module version and full commit SHA. A release tag is a human-readable reference; the commit is the immutable dependency identity. The parent lock is a host deployment record, not a configuration file that UPALL automatically reads.

Use an editable installation only as an explicit development override. Normal host use should not silently follow changes to a local checkout or main. Restore a pinned install when development validation finishes.

If the parent already uses Git and wants a vendored checkout, a submodule can pin the dependency with a separate upstream remote. Do not add a submodule by default to a parent with no Git repository. Avoid subtree/copy-based integration unless the parent has a documented need and one-way update procedure.

## Configuration contract

UPALL does not edit shell profiles or load a private parent-project config file. The host supplies configuration through its launcher environment.

| Setting | Effect and owner |
|---|---|
| CLI --check / --update | Check-only is the default; only explicit update authorizes unattended upgrades |
| CLI tool names | Restrict the batch to named tools |
| UPALL_LOG_ROOT | Host-selected private state root; overrides the XDG default |
| XDG_STATE_HOME | Default state base when UPALL_LOG_ROOT is absent; otherwise ~/.local/state |
| UPALL_SEARCH_PATH | Restrict discovery; disables fallback common-directory search |
| NO_COLOR | Disable terminal color |
| TERM=dumb, --plain, --json | Noninteractive output; finish without a key wait |

CLI arguments choose the operation. For the state path, the order is UPALL_LOG_ROOT, then XDG_STATE_HOME/upall, then ~/.local/state/upall. Actual absolute paths and credentials stay in the host environment, not in public defaults or examples.

Provider credentials remain owned by the provider tools. Do not add API keys, sign-in stores, proxy secrets or conversation history to the module or deployment lock. An environment variable that UPALL reads is an integration interface; it is not permission to copy the host's entire environment into a report.

## Upgrade and acceptance procedure

1. Create a module branch/PR; run isolated tests and a clean package-install smoke test.
2. Review compatibility and security changes. Keep check-first behavior and key/JSON mappings stable unless a documented breaking change is intended.
3. Select a release/full commit. In the parent project, prepare a dependency-lock change from the previous commit to the candidate.
4. Install the candidate in an isolated environment. Check both direct console commands and the parent's actual shortcut/launcher.
5. Accept a host check/demo/PTY result without using a real vendor upgrade as a test. For a real upgrade requested by the owner, record it separately.
6. Update the parent's pinned commit and deployment receipt together. Record previous/candidate versions, tested environment, actual result and rollback command.

Module test success does not imply host integration success. A parent-shell issue can belong to the host adapter; a generic key decoder or updater bug belongs upstream.

## Rollback and versioning

Rollback re-installs the prior full commit and restores the parent lock. It should not delete provider settings, logs or production data. The checkout and tool installation may live in different locations; removing a development checkout is not a rollback procedure.

For example, substitute the previous reviewed commit and run:

~~~sh
uv tool install --force 'git+https://github.com/Ming-Sir-69/upall.git@PREVIOUS_COMMIT'
upall --version
~~~

Use patch versions for compatible fixes, minor versions for compatible additions, and a clearly documented breaking-version boundary for incompatible CLI, key, JSON or configuration changes. During 0.x development, explicitly document any breaking minor release. Do not silently change a host's pin because upstream released a new version.

Public changelogs describe module behavior. Host-specific deployment history stays with the parent. Local paths and private acceptance notes must not leak into an upstream PR.

## Publication checks

Publish an explicit tracked-file set, not the parent workspace. Review the diff and packaged source distribution for credentials, local paths, symlinks into private trees, runtime reports and copied private documentation. Provide generic examples and keep public assets free of real account or machine data.

Hosted CI/deploy/registry publication is a separate choice. This repository keeps Actions disabled and uses local validation; neither extraction nor integration automatically authorizes paid services or quota-consuming automation.
