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

- `wandb.sklearn.plot_silhouette` now plots every cluster, including noise (`-1`) and labels that do not start at 0 (@David-Wu1119 in https://github.com/wandb/wandb/pull/13116)
