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

- `wandb job create` code artifacts now support customizable exclude lists via `--exclude` CLI flag, `WANDB_LAUNCH_CODE_EXCLUDE` environment variable, and `.wandbignore` file in the source directory. Common virtual environment and cache directories (`.venv`, `__pycache__`, etc.) are excluded by default. (Fixes #11427)
- Run console logs pane in W&B LEET TUI (`wandb beta leet` command, toggle with `l`). (@dmitryduev in https://github.com/wandb/wandb/pull/11345)
- System metrics pane in multi-run workspace mode in W&B LEET TUI (`wandb beta leet` command, toggle with `s`). (@dmitryduev in https://github.com/wandb/wandb/pull/11391)
- System metrics filtering in W&B LEET TUI (`wandb beta leet` command, toggle with `\`). (@dmitryduev in https://github.com/wandb/wandb/pull/11391)
- `ArtifactType.collections()` now supports filtering and ordering of collections. (@amusipatla-wandb in https://github.com/wandb/wandb/pull/11268)
- Warning message when `run.log_artifact` does not create a new version because the artifact content is identical to an existing version. (@pingleiwandb in https://github.com/wandb/wandb/pull/11340)
- `Project.collections()` to fetch filtered and ordered artifact collections in a project. (@amusipatla-wandb in https://github.com/wandb/wandb/pull/11319)
- `wandb purge-cache` command to clean up cached files (@jacobromero in https://github.com/wandb/wandb/pull/10996)

### Fixed

- Fixed a rare deadlock caused when GC triggers at an unlucky time and runs a `__del__` method that prints (@timoffex in https://github.com/wandb/wandb/pull/11402)
- `api.Run.user` raising `AttributeError` when accessing runs from an `api.Runs` iteration (@jacobromero in https://github.com/wandb/wandb/pull/11439)
