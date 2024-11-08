# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

* Fixed
* Changed
* Added
* Deprecated

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Fixed

- Fix `api.artifact()` to correctly pass the `enable_tracking` argument to the `Artifact._from_name()` method (@ibindlish in https://github.com/wandb/wandb/pull/8803)

### Added

- Added `create_and_run_agent` to `__all__` in `wandb/sdk/launch/__init__.py` to expose it as a public API (@marijncv in https://github.com/wandb/wandb/pull/8621)

### Deprecated

- The `quiet` argument to `wandb.run.finish()` is deprecated, use `wandb.Settings(quiet=...)` to set this instead. (@kptkin in https://github.com/wandb/wandb/pull/8794)
