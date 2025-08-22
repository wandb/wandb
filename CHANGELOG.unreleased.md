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

### Added

- New settings for `max_end_of_run_history_metrics` and `max_end_of_run_summary_metrics` (@timoffex in https://github.com/wandb/wandb/pull/10351)

### Changed

- Errors encountered while linking an artifact are no longer suppressed/silenced, and `Artifact.link()` and `Run.link_artifact()` no longer return `None` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9968)
- The "Run history" and "Run summary" printed at the end of a run are now limited to 10 metrics each (@timoffex in https://github.com/wandb/wandb/pull/10351)

### Fixed
- Dataclasses in a run's `config` no long raise `Object of type ... is not JSON serializable` when containing real classes as fields to the dataclass (@jacobromero in https://github.com/wandb/wandb/pull/10371)
