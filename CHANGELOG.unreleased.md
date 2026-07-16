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
- New sweep parameter to `Api().create_run()` and `Run().create()` that manually creates a run as part of the sweep (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12223)

### Changed
- Runs associated with a sweep via `Api().create_run()`, `Run.create()`, or `wandb.init(settings=Settings(sweep_id=...))` must include run config (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12223)
