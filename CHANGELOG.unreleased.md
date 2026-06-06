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

### Fixed

- `wandb.Api().viewer` (and `Api().user()` / `Api().users()`) no longer fail with `WandbApiFailedError: relogin required` for some API keys, a regression in `0.27.1` (@dmitryduev in https://github.com/wandb/wandb/pull/12009)
