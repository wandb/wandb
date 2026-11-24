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

- A metric defined with `step_sync` and a `step_metric` that starts with a dot now gets the latest logged value of that step. The dot is part of the first key, so `.foo` is the logged key `.foo`, and `.foo.bar` is the key `bar` nested in `.foo` (@geoffhardy in https://github.com/wandb/wandb/pull/13445)
