# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

* Added - for new features.
* Changed  - for changes in existing functionality.
* Deprecated - for soon-to-be removed features.
* Removed - for now removed features.
* Fixed - for any bug fixes.
* Security -  in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Added

- Added `create_and_run_agent` to `__all__` in `wandb/sdk/launch/__init__.py` to expose it as a public API (@marijncv in https://github.com/wandb/wandb/pull/8621)

### Changed

- Tables logged in offline mode now have updated keys to artifact paths when syncing. To revert to old behavior, use setting `allow_offline_artifacts = False`. (@domphan-wandb in https://github.com/wandb/wandb/pull/8792)

### Deprecated

- The `quiet` argument to `wandb.run.finish()` is deprecated, use `wandb.Settings(quiet=...)` to set this instead. (@kptkin in https://github.com/wandb/wandb/pull/8794)

### Fixed

- Fix `api.artifact()` to correctly pass the `enable_tracking` argument to the `Artifact._from_name()` method (@ibindlish in https://github.com/wandb/wandb/pull/8803)
