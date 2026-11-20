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

- `run.log_artifact()` and `wandb.Table` logging no longer fail with `AuthenticationError` when the run's internal API key check hits a transient network error. This was a regression in 0.27.1 (@joseph-shih-wandb in https://github.com/wandb/wandb/pull/XXXXX)
