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

### Fixed
- Correct the artifact url for organization registry artifacts to be independent of the artifact type. (@ibindlish in https://github.com/wandb/wandb/pull/10049)
- Suffixes on sanitized `InternalArtifact` names have been shortened to 6 alphanumeric characters. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10102)
