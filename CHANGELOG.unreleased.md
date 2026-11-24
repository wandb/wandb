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

### Fixed

- The XGBoost and LightGBM callbacks now record the best value of metrics such as `ndcg@5`, `map@3`, `error@0.6` and LightGBM's `binary_error` in the run summary, instead of the last one (@David-Wu1119 in https://github.com/wandb/wandb/pull/13102)
