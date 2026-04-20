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

- Made `wandb.init(id=run_id, reinit="create_new")` raise an error when another run in the same script with the same `run_id` is still running (@timoffex in https://github.com/wandb/wandb/pull/11759)
