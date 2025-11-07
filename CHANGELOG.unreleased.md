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
- `Artifact.files()` now has a correct `len()` when filtering by the `names` parameter (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10796)
- The numerator for file upload progress no longer occasionally exceeds the total file size (@timoffex in https://github.com/wandb/wandb/pull/10812)
- `Artifact.link()` now logs unsaved artifacts instead of raising an error, consistent with the behavior of `Run.link_artifact()` (@tonyyli-wandb in https://github.com/wandb/wandb/10822)
- Automatic code saving now works when running ipython notebooks in VSCode's Jupyter notebook extension (@jacobromero in https://github.com/wandb/wandb/pull/10746)
- Logging an artifact with infinite floats in `Artifact.metadata` now raises a `ValueError` early, instead of waiting on request retries to time out (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10845).

### Added
- The registry API now supports programmatic management of user and team members of individual registries. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10542)
- `Registry.id` has been added as a (read-only) property of `Registry` objects (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10785).
