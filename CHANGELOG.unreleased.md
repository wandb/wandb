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

### Added

- `owner` property on `wandb.apis.public.Project` to access the project owner's user information. (@jacobromero in https://github.com/wandb/wandb/pull/11278)

### Changed

- Python 3.8 is no longer supported (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11198, https://github.com/wandb/wandb/pull/11290, https://github.com/wandb/wandb/pull/11164)
- Pydantic V1 is no longer supported (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11165)

### Fixed

- Sweep agents now exit gracefully when the sweep is deleted, instead of running indefinitely with repeated 404 errors (@domphan-wandb in https://github.com/wandb/wandb/pull/11226)
- `wandb-core` crashes no longer produce extremely long, repetitive tracebacks in older Python versions (@timoffex in https://github.com/wandb/wandb/pull/11284)
