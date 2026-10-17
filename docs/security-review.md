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
