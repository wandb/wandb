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

- The `wandb-summary.json`, `wandb-metadata.json`, `output.log` and `config.yaml` files are now generated even in offline mode (@timoffex in https://github.com/wandb/wandb/pull/11279)

### Fixed

- Sweep agents now exit gracefully when the sweep is deleted, instead of running indefinitely with repeated 404 errors (@domphan-wandb in https://github.com/wandb/wandb/pull/11226)
