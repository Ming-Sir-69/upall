# Security

UPALL 0.1.x is an early macOS-first tool. Fixes target the current version.

For a security issue, use the repository's private vulnerability reporting option if available, or contact the maintainer through the profile at https://github.com/Ming-Sir-69 before posting exploit details. Do not put credentials or unredacted logs in a public issue.

## Trust boundaries

- Default checks never intentionally invoke an installer. Space/1 and --update authorize update commands.
- Executables found in PATH and the configured search path are trusted local programs. Running --version also executes a program; UPALL cannot make an untrusted PATH safe.
- Remote version metadata and local tool output are untrusted. Terminal control/bidirectional formatting characters are removed before rendering. Package names are chosen from the known catalog.
- Updaters and downloaded official installation scripts run as the current user. UPALL does not sandbox those vendors' code or add sudo. npm lifecycle scripts may execute during an authorized update.
- State roots must be owned by the current user, are restricted to mode 0700, and cannot be symlinks. Locks refuse symlinks. Reports use exclusive temporary files and atomic replacement.
- Reports include executable paths and logs may include vendor diagnostics. They are not intended for public upload.

Do not run UPALL with elevated privileges. Review a program's provenance before adding it to your search path.

## Scope and limits

Cross-user attacks on local state, accidental installation during checks, shell injection from version metadata, wrong-prefix updates, process cleanup and terminal injection are relevant boundaries.

A malicious tool already selected by the user, compromised upstream releases, same-user filesystem tampering, OS input-method interception, and unverified platform variants are not solved by UPALL. Inventory is a bounded known-tool catalog, not a complete device audit.

The initial review and regression coverage are documented in docs/security-review.md. They do not establish an exhaustive security guarantee.

