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

- `wandb beta core start|stop` commands to run a detached `wandb-core` service and reuse it across multiple processes via the `WANDB_SERVICE` env var (@dmitryduev in https://github.com/wandb/wandb/pull/11418)

### Changed

- JSON serialization and deserialization now use `orjson` for improved performance (@jacobromero in https://github.com/wandb/wandb/pull/11163)

### Fixed

- git diff patch files are now generated for the closest ancestor commit when no upstream branch is set (@jacobromero in https://github.com/wandb/wandb/pull/10132)
    - bug introduced in v0.18.0
