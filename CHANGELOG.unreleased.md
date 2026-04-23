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

- `run.write_logs()` method to write text directly to the Logs tab to give users more control over logged output over what console capture alone previously provided. Includes `WandbLoggerHandler` as a convenience integration for Python's logging module (@itstania in https://github.com/wandb/wandb/pull/11702)
