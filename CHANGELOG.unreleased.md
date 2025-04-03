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

### Changed

- Upgrade go version for `wandb-core` from 1.23.x to 1.24.x (@kptkin in https://github.com/wandb/wandb/pull/9590)

### Fixed

- Fixed ValueError on Windows when running a W&B script from a different drive (@jacobromero in https://github.com/wandb/wandb/pull/9677)
