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

- Fixed bug where setting WANDB__SERVICE_WAIT led to an exception during wandb.init (@TimSchneider42 in https://github.com/wandb/wandb/pull/9050)

### Changed

- `run.finish()` displays more detailed information in the terminal and in Jupyter notebooks (by @timoffex, enabled in https://github.com/wandb/wandb/pull/9070)
- Improved error message for failing tensorboard.patch() calls to show the option to call tensorboard.unpatch() first (@daniel-bogdoll in https://github.com/wandb/wandb/pull/8938)
- Add projectId to deleteFiles mutation if the server supports it. (@jacobromero in https://github.com/wandb/wandb/pull/8837)
