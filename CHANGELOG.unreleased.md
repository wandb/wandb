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

- Added support for fetching artifact files via the artifact membership, i.e. with additional artifact collection membership context (@ibindlish in https://github.com/wandb/wandb/pull/9551)

### Changed

- Boolean values for the `reinit` setting are deprecated; use "return_previous" and "finish_previous" instead (@timoffex in https://github.com/wandb/wandb/pull/9557)

- Moved helper methods to check for server feature flags from the public API to the internal API (@ibindlish in https://github.com/wandb/wandb/pull/9561)
