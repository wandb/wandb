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

- Resuming a run with a different active run will now raise an error unless you call `run.finish()` first, or call `wandb.init()` with the parameter `reinit='create_new'` (@jacobromero in https://github.com/wandb/wandb/pull/10468)
