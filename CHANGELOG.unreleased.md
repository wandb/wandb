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

- changed moviepy constraint to >=1.0.0 (@jacobromero in https://github.com/wandb/wandb/pull/9419)

### Fixed

- Fixed incorrect logging of an "wandb.Video requires moviepy \[...\]" exception when using moviepy v2. (@Daraan in https://github.com/wandb/wandb/pull/9375)
