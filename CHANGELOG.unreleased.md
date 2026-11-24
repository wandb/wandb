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

### Fixed

- `wandb sync` stored a run's environment info in the config under a newly generated writer ID instead of the ID of the process that wrote the run (@dmitryduev in https://github.com/wandb/wandb/pull/13129)
