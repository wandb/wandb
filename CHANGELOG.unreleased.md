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

## Added
- Added the `wandb clean` command, which replaces `wandb sync --clean` (@timoffex in https://github.com/wandb/wandb/pull/12238)

## Changed
- Hardened argument handling in `wandb launch` for the local-process resource so that job-supplied values are always shell-quoted (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12220)
- `wandb.init()` now honors `mode="offline"` and `resume="..."` instead of logging a warning and ignoring the `resume` option. The requested mode is reconciled against the backend when the run is later synced with `wandb beta sync`. (@geoffhardy in https://github.com/wandb/wandb/pull/12110)
- The launch agent now restricts a job's git source URL to https/ssh remotes and pins git's protocol allowlist when fetching it and updating submodules (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12221)
- Response parsing is now faster for many `wandb.Api` operations, including artifact and registry queries (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12213)

## Fixed
- Registry search `registries(order=...).collections(order=...).versions()` now returns artifact versions in registry and/or collection order.  (@ibindlish in https://github.com/wandb/wandb/pull/12154)
