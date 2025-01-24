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

### Added

- Added `wandb login --base-url {host_url}` to login as an alias of `wandb login --host {host_url}`. (@jacobromero in https://github.com/wandb/wandb/pull/9323)

### Fixed

- Fixed a bug causing `offline` mode to make network requests when logging media artifacts. If you are using an older version of W&B Server that does not support offline artifact uploads, use the setting `allow_offline_artifacts=False` to revert to older compatible behavior. (@domphan-wandb in https://github.com/wandb/wandb/pull/9267)
- Expand sanitization rules for logged table artifact name to allow for hyphens and dots. This update brings the rules up-to-date with the current rules for artifact names. (Allowing letters, numbers, underscores, hyphens, and dots) (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/9271)
- Correctly handle run rewind settings `fork_from` and `resume_from`. (@dmitryduev in https://github.com/wandb/wandb/pull/9331)
