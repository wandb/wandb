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

- `Registry.save()` no longer saves other staged changes when a rename is rejected, such as when the name is already taken (@gdecarvalhovaz-lgtm in https://github.com/wandb/wandb/pull/13376)
