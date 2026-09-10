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

- `wandb.beta.LocalApi` reads runs from a local wandb directory without a W&B server, API key or network: list the runs with their state, and read a run's config, summary, history rows (as dicts or a pandas or polars DataFrame) and console logs, including while the run is still writing. It is experimental and may change in any release (@dmitryduev in https://github.com/wandb/wandb/pull/12745, https://github.com/wandb/wandb/pull/12766)

### Changed

- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
