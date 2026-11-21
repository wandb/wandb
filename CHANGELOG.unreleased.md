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

- Interactive `wandb init` and the `wandb projects` command no longer crash with `TypeError: object of type 'Projects' has no len()` when listing an entity's projects (@inchang-ing in https://github.com/wandb/wandb/pull/13336)
