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

- The `stop_on_fatal_error` setting to stop a run (using `stop_fn`) after a fatal error that prevents it from uploading metrics (@timoffex in https://github.com/wandb/wandb/pull/11774)
- New `wandb.sandbox` package and the `wandb beta sandbox` cli for using wandb sandbox (@pingleiwandb in https://github.com/wandb/wandb/pull/11606)
- The `finish_timeout` and `finish_timeout_raises` settings (@timoffex in https://github.com/wandb/wandb/pull/11737)

### Changed

- Changed CPU and memory system metric percentages in Linux containers to use cgroup resource limits instead of host node totals. Set the private `x_stats_use_cgroup_resource_limits` setting to `False` to opt out.
