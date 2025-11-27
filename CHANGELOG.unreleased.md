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

### Added

- Run console logs pane in W&B LEET TUI (`wandb beta leet` command, toggle with `l`). (@dmitryduev in https://github.com/wandb/wandb/pull/11345)
- System metrics pane in multi-run workspace mode in W&B LEET TUI (`wandb beta leet` command, toggle with `s`). (@dmitryduev in https://github.com/wandb/wandb/pull/11391)
- `ArtifactType.collections()` now supports filtering and ordering of collections. (@amusipatla-wandb in https://github.com/wandb/wandb/pull/11268)
- Warning message when `run.log_artifact` does not create a new version because the artifact content is identical to an existing version. (@pingleiwandb in https://github.com/wandb/wandb/pull/11340)
- `Project.collections()` to fetch filtered and ordered artifact collections in a project. (@amusipatla-wandb in https://github.com/wandb/wandb/pull/11319)
- `wandb purge-cache` command to clean up cached files (@jacobromero in https://github.com/wandb/wandb/pull/10996)
