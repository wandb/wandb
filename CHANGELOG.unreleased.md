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

- Added creation, deletion, and updating of registries in the SDK. (@estellazx in https://github.com/wandb/wandb/pull/9453)
- `is_link` property to artifacts to determine if an artifact is a link artifact (such as in the Registry) or source artifact. (@estellazx in https://github.com/wandb/wandb/pull/9764)


### Fixed

- `run.log_code` correctly sets the run configs `code_path` value. (@jacobromero in https://github.com/wandb/wandb/pull/9753)
- Correctly use `WANDB_CONFIG_DIR` for determining system settings file path (@jacobromero in https://github.com/wandb/wandb/pull/9711)
- Prevent invalid `Artifact` and `ArtifactCollection` names (which would make them unloggable), explicitly raising a `ValueError` when attempting to assign an invalid name. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8773)
