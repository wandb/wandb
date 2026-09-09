# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed
sections:

- Added - for new features.
- Changed - for changes in existing functionality.
- Deprecated - for soon-to-be removed features.
- Removed - for now removed features.
- Fixed - for any bug fixes.
- Security - in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Changed

- More informative errors are raised from `Api.artifacts()` and related artifact paginators when the artifact path is invalid or inaccessible (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11813)

### Fixed

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
