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

- When a settings file (such as `./wandb/settings` or `~/.config/wandb/settings`) contains an invalid setting, all settings files are ignored and an error is printed (@timoffex in https://github.com/wandb/wandb/pull/11207)

### Fixed

- After `wandb login --host <invalid-url>`, using `wandb login --host <valid-url>` works as usual (@timoffex in https://github.com/wandb/wandb/pull/11207)
  - Regression introduced in 0.24.0
- Fixes a race condition where preempted Sweeps runs sometimes did not result in run being queued for the next agent request to pick up. (@kelu-wandb in https://github.com/wandb/wandb/pull/11256)
