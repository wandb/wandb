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
- Run filtering by metadata in multi-run workspace mode in W&B LEET TUI (`wandb beta leet` command, activate with `f`) (@dmitryduev in https://github.com/wandb/wandb/pull/11497 and https://github.com/wandb/wandb/pull/11534)
- Run overview displays tags and notes in W&B LEET TUI (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11523)
- Per-chart log-scale (Y-axis) support in W&B LEET TUI (`wandb beta leet` command, toggle on a selected chart with `y`) (@dmitryduev in https://github.com/wandb/wandb/pull/11523)

### Changed

- JSON serialization and deserialization now use `orjson` for improved performance (@jacobromero in https://github.com/wandb/wandb/pull/11163)
- Improved system metrics UX with multi-series overlays, inspection, and live/history zoom in W&B LEET TUI (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11512)
- Artifact file download now uses a new download URL format in the absensce of the directUrl from the file's manifest entry. (@ibindlish in https://github.com/wandb/wandb/pull/11407)

### Fixed

- Fixed artifact client ID collisions in forked child processes by reseeding the fast ID generator after `fork()` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11491)
