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

This version drops support for Python 3.9.

### Added

- The `stop_on_fatal_error` setting to stop a run (using `stop_fn`) after a fatal error that prevents it from uploading metrics (@timoffex in https://github.com/wandb/wandb/pull/11774)
- New `wandb.sandbox` package and the `wandb beta sandbox` cli for using wandb sandbox (@pingleiwandb in https://github.com/wandb/wandb/pull/11606)
- The `finish_timeout` and `finish_timeout_raises` settings (@timoffex in https://github.com/wandb/wandb/pull/11737)

### Changed

- Changed CPU and memory system metric percentages in Linux containers to use cgroup v2 resource limits instead of host node totals. Set the private `x_stats_no_cgroup` setting to `True` to opt out (@dmitryduev in https://github.com/wandb/wandb/pull/11796)
- Python 3.9 is no longer supported (@dmitryduev in https://github.com/wandb/wandb/pull/11841)
