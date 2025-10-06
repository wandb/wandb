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

- Possibly fixed some cases where the `output.log` file was not being uploaded (@timoffex in https://github.com/wandb/wandb/pull/10620)
- Fixed excessive data uploads when calling `run.save()` repeatedly on unchanged files (@dmitryduev in https://github.com/wandb/wandb/pull/10639)
