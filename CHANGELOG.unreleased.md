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

- When a `wandb.Image` carrying multiple `box` or `mask` keys with distinct `class_labels` is logged inside a `wandb.Table`, each key's labels are now preserved. The next server release will contain a corresponding frontend fix to use these values. In addition, we also concat all labels with the same key as a fallback for old servers. (@kelu-wandb in https://github.com/wandb/wandb/pull/11901)
