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

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)

### Added
- Added `wandb sweep-scheduler`, which runs a sweep's search locally while wandb-core drives the runs, so you can plug in your own optimizer (@kmikowicz in https://github.com/wandb/wandb/pull/12560)
- `wandb sweep-scheduler` can search a sweep with Optuna, including its pruners and any stopping rule you supply (@kmikowicz in https://github.com/wandb/wandb/pull/12561)
- `wandb sweep-scheduler` can search a sweep with Ax, including its early stopping and any stopping rule you supply. Requires Python 3.11 or newer (@kmikowicz in https://github.com/wandb/wandb/pull/12562)