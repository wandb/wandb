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

- `Api` methods returning artifacts, registries, automations, and related paginators now accept an optional `start` argument to resume iteration from a saved cursor (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11651)

### Changed

- Unified keyboard navigation in W&B LEET TUI (`wandb beta leet` command): `wasd` and arrow keys are now interchangeable within each focused pane (chart focus in grids, item/page nav in lists), and `Home`/`End`/`PgUp`/`PgDn` work universally; the media pane retains its deliberate split where arrows scrub and `wasd` selects tiles (@dmitryduev in https://github.com/wandb/wandb/pull/11756)

### Fixed

- Made `wandb.init(id=run_id, reinit="create_new")` raise an error when another run in the same script with the same `run_id` is still running (@timoffex in https://github.com/wandb/wandb/pull/11759)
- `wandb.Api` no longer raises an error for some api operations when offline mode is enabled via the `WANDB_MODE` environment variable or the `mode` setting. (@jacobromero in https://github.com/wandb/wandb/pull/11762)
