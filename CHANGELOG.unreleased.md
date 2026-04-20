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

- Unified keyboard navigation in W&B LEET TUI (`wandb beta leet` command): `wasd` and arrow keys are now interchangeable within each focused pane (chart focus in grids, item/page nav in lists), and `Home`/`End`/`PgUp`/`PgDn` work universally; the media pane retains its deliberate split where arrows scrub and `wasd` selects tiles (@dmitryduev in https://github.com/wandb/wandb/pull/11756)
