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

- `Artifact.download()` no longer raises an error when using `WANDB_MODE=offline` or when an offline run exists (@timoffex in https://github.com/wandb/wandb/pull/9695)

### Removed

- Dropped the `-q` / `--quiet` argument to the `wandb` magic in IPython / Jupyter; use the `quiet` run setting instead (@timoffex in https://github.com/wandb/wandb/pull/9705)

### Deprecated

- The following `wandb.Run` methods are deprecated in favor of properties and will be removed in a future release (@kptkin in https://github.com/wandb/wandb/pull/8925):
    - `run.project_name()` is deprecated in favor of `run.project`
    - `run.get_url()` method is deprecated in favor of `run.url`
    - `run.get_project_url()` method is deprecated in favor of `run.project_url`
    - `run.get_sweep_url()` method is deprecated in favor of `run.sweep_url`


### Fixed

- Fixed ValueError on Windows when running a W&B script from a different drive (@jacobromero in https://github.com/wandb/wandb/pull/9678)
- Fix base_url setting was not provided to wandb.login (@jacobromero in https://github.com/wandb/wandb/pull/9703)
