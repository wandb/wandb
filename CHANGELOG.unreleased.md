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

- Logging an artifact (whether via `WandbLogger` or `run.log_artifact`) now writes the manifest file to the artifact's staging directory instead of the OS temp dir (`$TMPDIR`), avoiding silent failures when `$TMPDIR` is missing or unwritable (@ibindlish in https://github.com/wandb/wandb/pull/11958)
