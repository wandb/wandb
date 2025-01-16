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

### Fixed

- Fix incorrectly reported device counts and duty cycle measurements for TPUs with single devices per chip / multiple devices on the host and make TPU metrics sampling more robust (@dmitryduev in https://github.com/wandb/wandb/pull/9266)
- Handle non-consecutive TPU device IDs in system monitor (@dmitryduev in https://github.com/wandb/wandb/pull/9276)
