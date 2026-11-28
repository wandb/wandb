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

### Changed

- `wandb.Api().artifact(...)` now defers fetching an artifact's collection membership aliases until `Artifact.aliases` is accessed, then fetches them in 1,000-alias pages (@ibindlish in https://github.com/wandb/wandb/pull/13183)

### Fixed

- Three error messages printed a literal placeholder instead of its value: the Launch S3 "bucket is not accessible" and GCP region errors, and the `PermissionError` raised when a file cannot be overwritten (@alleyxd in https://github.com/wandb/wandb/pull/13195)
