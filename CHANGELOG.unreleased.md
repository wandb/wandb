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

### Notable Changes

Runs created with `wandb==0.24.0` may fail to upload some data, which this release fixes. Missing data is stored in the run's `.wandb` file and can be reuploaded with `wandb sync`.

### Added

- `download_history_exports` in `api.Run` class to download exported run history in parquet file format (@jacobromero in https://github.com/wandb/wandb/pull/11094)

### Changed

- When a settings file (such as `./wandb/settings` or `~/.config/wandb/settings`) contains an invalid setting, all settings files are ignored and an error is printed (@timoffex in https://github.com/wandb/wandb/pull/11207)

### Fixed

- After `wandb login --host <invalid-url>`, using `wandb login --host <valid-url>` works as usual (@timoffex in https://github.com/wandb/wandb/pull/11207)
  - Regression introduced in 0.24.0
- `wandb beta sync` correctly loads credentials (@timoffex in https://github.com/wandb/wandb/pull/11231)
  - Regression introduced in 0.24.0
  - Caused `wandb beta sync` to get stuck on `Syncing...`
- Fixed occasional unuploaded data in 0.24.0 (@timoffex in https://github.com/wandb/wandb/pull/11249)
  - All data is stored in the run's `.wandb` file and can be reuploaded with `wandb sync`
