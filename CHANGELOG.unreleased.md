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

- Improved error message for failing tensorboard.patch() calls to show the option to call tensorboard.unpatch() first (@daniel-bogdoll in https://github.com/wandb/wandb/pull/8938)
- Add projectId to deleteFiles mutation if the server supports it. (@jacobromero in https://github.com/wandb/wandb/pull/8837)

### Fixed

- Update docs for `Artifact.used_by()` to clarify the upper limit on returned runs, and emit a `UserWarning` if returning the maximum number of results. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9042)
