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

- Boolean values for the `reinit` setting are deprecated; use "return_previous" and "finish_previous" instead (@timoffex in https://github.com/wandb/wandb/pull/9557)

- The server now supports fetching artifact files by providing additional collection information; updated the artifacts api to use the new endpoints instead (@ibindlish in https://github.com/wandb/wandb/pull/9551)

- The server now supports passing in collection information to the artifact file download url endpoint (@ibindlish in https://github.com/wandb/wandb/pull/9560)
