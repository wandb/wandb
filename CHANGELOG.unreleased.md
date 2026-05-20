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

### Removed

- Removed the unsupported `wandb.apis.importers` API (@dmitryduev in https://github.com/wandb/wandb/pull/11923)

### Fixed

- `api.Run.beta_scan_history` no longer throws `Step column '_step' not found in schema` error when called with a `keys` list that does not include `_step` (@jacobromero in https://github.com/wandb/wandb/pull/11924)
