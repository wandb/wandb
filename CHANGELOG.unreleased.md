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

- Moved helper methods to check for server feature flags from the public API to the internal API (@ibindlish in https://github.com/wandb/wandb/pull/9561)

### Added

- Added support for fetching artifact files via the artifact membership, i.e. with additional artifact collection membership context (@ibindlish in https://github.com/wandb/wandb/pull/9551)

- Added support for building artifact file download urls using the new url scheme, with artifact collection membership context (@ibindlish in https://github.com/wandb/wandb/pull/9560)