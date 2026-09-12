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

- It is now possible to use resume="must" for offline runs. Syncing will fail if there's no run to resume. (@geoffhardy in https://github.com/wandb/wandb/pull/12110)


### Changed

- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- Single-element NumPy arrays stored in run config are now converted to native scalar values instead of strings. (@tandede, https://github.com/wandb/wandb/issues/1184)
- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
