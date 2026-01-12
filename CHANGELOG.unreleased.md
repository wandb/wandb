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

### Notable Changes

This version drops support for Python 3.8.

This version drops support for Pydantic V1.

### Changed

- Python 3.8 is no longer supported (@tonyyli-wandb in
  https://github.com/wandb/wandb/pull/11198,
  https://github.com/wandb/wandb/pull/11164)
- Pydantic V1 is no longer supported (@tonyyli-wandb in
  https://github.com/wandb/wandb/pull/11165)
- When a settings file (such as `./wandb/settings` or
  `~/.config/wandb/settings`) contains an invalid setting, all settings files
  are ignored and an error is printed (@timoffex in
  https://github.com/wandb/wandb/pull/11207)

### Fixed

- After `wandb login --host <invalid-url>`, using
  `wandb login --host <valid-url>` works as usual (@timoffex in
  https://github.com/wandb/wandb/pull/11207)
  - Regression introduced in 0.24.0
