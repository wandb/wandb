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

This version raises errors that would previously have been suppressed during calls to `Artifact.link()` or `Run.link_artifact()`. While this prevents undetected failures in those methods, it is also a breaking change.

### Changed

- Errors encountered while linking an artifact are no longer suppressed/silenced, and `Artifact.link()` and `Run.link_artifact()` no longer return `None` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9968)
