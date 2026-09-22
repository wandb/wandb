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
- Added a `--max-consecutive-failed-runs` flag to `wandb agent`, which shuts an agent down once that many runs have failed consecutively at any point in the agent's life. (@nathancy-wandb in https://github.com/wandb/wandb/pull/12821)

### Changed

- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- `wandb login` links to the authorize page under the app URL's path instead of the host root when `WANDB_APP_URL` includes a path (@dmitryduev in https://github.com/wandb/wandb/pull/12928)
- Downloading run files with the public API, `wandb.restore()` and `Run.metadata` no longer fail when the W&B server URL includes a path prefix (@dmitryduev in https://github.com/wandb/wandb/pull/12926)
- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
- `wandb beta sync` no longer overwrites the earlier history of a resumed run when the backend reports a stale step. The starting step is now reconciled against the summary `_step`, the history tail `_step`, and the history row count (@geoffhardy in https://github.com/wandb/wandb/pull/12668)
- Fixed a memory leak where every `wandb.Api()` object permanently retained a few MiB in the background service process after it was garbage collected (@dmitryduev in https://github.com/wandb/wandb/pull/12920)
