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

- wandb.Api() now supports Federated Auth (JWT based authentication). (@ryanbuccellato in https://github.com/wandb/wandb/pull/11243)

### Fixed

- Refresh presigned download url when it expires during artifact file downloads. (@pingleiwandb in https://github.com/wandb/wandb/pull/11242)
