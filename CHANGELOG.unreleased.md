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

- changed moviepy constraint to >=1.0.0 (@jacobromero in https://github.com/wandb/wandb/pull/9419)
- `wandb.init()` displays more detailed information, in particular when it is stuck retrying HTTP errors (@timoffex in https://github.com/wandb/wandb/pull/9431)

### Removed

- Removed the private `x_show_operation_stats` setting (@timoffex in https://github.com/wandb/wandb/pull/9427)

### Fixed

- Fixed incorrect logging of an "wandb.Video requires moviepy \[...\]" exception when using moviepy v2. (@Daraan in https://github.com/wandb/wandb/pull/9375)
- `wandb.setup()` correctly starts up the internal service process; this semantic was unintentionally broken in 0.19.2 (@timoffex in https://github.com/wandb/wandb/pull/9436)
- Fixed `TypeError: Object of type ... is not JSON serializable` when using numpy number types as values. (@jacobromero in https://github.com/wandb/wandb/pull/9487)
