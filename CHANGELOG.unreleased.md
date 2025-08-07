# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

- Added - for new features.
- Changed - for changes in existing functionality.
- Deprecated - for soon-to-be removed features.
- Removed - for now removed features.
- Fixed - for any bug fixes.
- Security - in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Notable Changes

This release uses [orjson](https://github.com/ijl/orjson) by default for serializing/deserializing JSON objects. This may cause some issues in edge cases with `NaN`, `+Infinity`, `-Infinity` values.
You can use `_WANDB_USE_JSON` environment variable to revert back to using the previous JSON serialization library.

### Changed
-  `orjson` is now used by default for serializing/deserializing JSON objects.
