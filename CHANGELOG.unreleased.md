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

## Changed
- Hardened argument handling in `wandb launch` for the local-process resource so that job-supplied values are always shell-quoted (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12220)
- The launch agent now validates a job's git source URL and pins git's protocol allowlist when fetching it and updating submodules (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/XXXXX)
