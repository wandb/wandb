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

- `Sweep.name` property will now return user-edited display name if available (falling back to
  original name from sweep config, then sweep ID as before).

### Fixed

- Correct the artifact url for organization registry artifacts to be independent of the artifact type. (@ibindlish in https://github.com/wandb/wandb/pull/10049)
