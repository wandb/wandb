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

- `EvalTable(backend="ces")` takes `key_column`, which names a column that identifies each row's example, so that eval comparisons match rows by its values instead of by their inputs or position (@kelu-wandb in https://github.com/wandb/wandb/pull/13382)
- Offline runs can log `EvalTable(backend="ces")`, and `wandb sync` uploads the tables (@kelu-wandb in https://github.com/wandb/wandb/pull/13405)
