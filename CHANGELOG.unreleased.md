# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

- Added - for new features.
- Changed - for changes in existing functionality.
- Deprecated - for soon-to-be removed features.
- Removed - for now removed features.
- Fixed - for any bug fixes.
- Security - in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Added

- Support JWT authentication in wandb-core (@elainaRenee in https://github.com/wandb/wandb/pull/8431)

### Fixed

- The stop button correctly interrupts runs whose main Python thread is running C code, sleeping, etc. (@timoffex in https://github.com/wandb/wandb/pull/9094)
