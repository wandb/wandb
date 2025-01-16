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

### Fixed

- Fixed a bug causing `offline` mode to make network requests when logging media artifacts. If you are using an older version of W&B Server that does not support offline artifact uploads, use the setting `allow_offline_artifacts=False` to revert to older compatible behavior. (@domphan-wandb in https://github.com/wandb/wandb/pull/9267)
- Update sanitization rules for logged table artifact name to match artifact name constraints (as defined in sdk/artifacts/artifact.py) (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/9271)
