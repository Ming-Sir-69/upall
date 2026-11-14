# Initial publication review

Reviewed on 2026-10-17 for the 0.1.0 source package. This is a local implementation review with regression tests, not an independent audit.

## Reviewed boundaries

- Default argument handling, keyboard update authorization and noninteractive output.
- Installation provenance, package/prefix selection, remote version parsing and argv-based subprocess execution.
- Downloaded official installer execution, inherited environment and updater trust.
- Local report/log directories, lock acquisition, report replacement and concurrent batches.
- Terminal control sequences, Unicode formatting, fragmented UTF-8 and Escape sequences.
- Child process groups, cancellation, terminal restoration and packaging contents.

## Findings addressed before publication

The personal helper used a predictable shared temporary state directory. The public package uses a per-user persistent state root, verifies ownership, rejects symlink directories and locks, and restricts directory permissions. Report replacement uses exclusively-created temporary files rather than predictable names.

Display sanitization was extended to remove C1 controls and Unicode formatting controls, including bidirectional overrides, in addition to ANSI/OSC sequences.

The source distribution was checked to include its integration scenarios, launcher, documentation and example assets. Public files were inspected for private machine paths and credential markers; none were found in the publication set.

## Evidence

- Eight unittest cases passed, including three integration scenario runners.
- Discovery fixtures covered provenance, unknown/local sources and empty environments without installation.
- Worker scenarios covered default/JSON check-only behavior, explicit updates, ten CLI fixtures, rejected malformed version metadata, ineffective updates, failed-only retry and cancellation.
- PTY scenarios covered Space/number/full-width update actions, Enter/Esc exit, stable key mapping, logs, resize, fragmented input, locks and terminal restoration.
- State regression cases covered owner-only permissions, symlink rejection, atomic report replacement without following a target, and terminal control/bidi filtering.
- A clean wheel installation exposed both console commands and passed version/demo/inventory smoke tests.
- The bundled source distribution ran the same eight tests successfully after extraction into a fresh directory.

No real vendor upgrade was executed as a publication test.

## Remaining limits

Programs selected from PATH and official updater scripts remain trusted executable code. UPALL is not a sandbox or signature-verification system for every upstream release. Logs may contain sensitive vendor output, even though UPALL does not read sign-in stores or API-key configuration. Real IME behavior, all install variants and platforms beyond the tested macOS environment remain outside the verified matrix.

The first release keeps existing channel/version-verification behavior. Fast-moving channels and custom launchers need additional real-world validation before support can be widened. See SECURITY.md and the roadmap for the maintained scope.

## 0.1.1 configuration follow-up

The XDG specification requires absolute base-directory values. The previous state-path fallback accepted a relative XDG_STATE_HOME; version 0.1.1 ignores that invalid value and uses the home-directory fallback. The explicit UPALL_LOG_ROOT host override remains separate. A regression case covers relative/absolute XDG values and override precedence. The full nine-case unittest suite passed after this change.

## 0.11.0 plugins, app bundles and host tools

- App bundle replacement downloads only from pinned hosts (cdn.kimi.com, github.com), requires the manifest sha256 when published, a strict `codesign --verify --deep` result and a Developer ID team equal to the installed copy (and to the manifest's team). The bundle id and version inside the archive must match. The old bundle is renamed into the owner-only state root, and is renamed back if the swap fails.
- A running app is asked to quit through its own Apple Event and reopened afterwards; nothing is force-killed. Background services are restarted with `launchctl kickstart` only when registered.
- Host config is executable configuration: it must be owned by the user, not group/world-writable, and use absolute program paths; argv is never passed through a shell. Isolated runs ignore the default file. Adapter output is parsed as JSON and sanitized before display.
- Git convergence backs up refs before moving them, never touches a dirty work tree, aborts a failed rebase and only deletes branches whose every commit upstream already carries (archived under refs/upall/archive/).
- Preserved paths are copied into the owner-only state root; restore never follows symlinks out of the recorded path.

## 0.13.0 resilient downloads and history

- Download hosts and release targets remain pinned by the existing adapters. Switching between aria2c and curl does not relax URL, bundle-id, version, strict-signature or Developer ID team checks. A failed downloader's partial output is removed before the other downloader starts.
- Native Claude Code uses the vendor's versioned manifest. The compressed package must match its own sha256 and size; the decompressed binary must independently match the uncompressed manifest before it is made executable or run. Invalid metadata or a checksum mismatch never reaches installation.
- npm direct/proxy fallback changes only transport environment variables; the detected package, manager, prefix and channel are unchanged. Proxy credentials are not copied into structured network events.
- Network events are local untrusted diagnostic data, sanitized before display. The append-only history uses an owner-only state directory and no-follow file creation; latest-report replacement remains atomic.

## 0.14.0 Cursor Agent

- Discovery only accepts the official `~/.local/share/cursor-agent/versions/` tree. The short `agent` name is used only when it resolves into that tree; an unrelated `agent` binary stays missing.
- Version probes use the vendor's `about --format json`; only `cliVersion` / `latestVersion` drive status. Vendor JSON (and any account fields it may contain) is treated as untrusted log/metadata, same as other adapter output.
- Updates invoke only the detected executable's `update` command; missing installs stay missing.

## 0.14.1 release-source checks

- Kimi metadata comes from the fixed official npm package endpoint; no npm executable or package-manager migration is introduced. Versions are validated before interpolation into a fixed HTTPS native-manifest URL. The manifest must match that version and platform, with an exact filename and valid sha256 field. Remote metadata supplies no executable command or arbitrary download URL.
- The official native installer still performs binary checksum verification. Its exact version and installation root are explicitly pinned; inherited KIMI_VERSION/KIMI_INSTALL_DIR cannot silently redirect the update. PATH edits remain disabled.
- Native package unavailability or invalid metadata produces a failed check, never a fallback to a stale marker. A newer local installation preserves the actual remote value and cannot reach the installer. Regression fixtures cover these boundaries without executing a real vendor update.
