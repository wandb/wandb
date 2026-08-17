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

- Added `run.console_logs()` to the public API for reading the console output that W&B captured for a run — the whole log, or only the last N lines with `run.console_logs(last=N)`, for finished and still-running runs alike. Reading from the beginning requires W&B Server 0.77 or newer (@dmitryduev in https://github.com/wandb/wandb/pull/12442)
- The automations API now supports team and organization scopes. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12197, https://github.com/wandb/wandb/pull/12194)
- The automations API now supports creating and editing automations whose scope is a `Registry` object (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10867)

### Changed

- `Api.{create,update}_automation()` now raise `UnsupportedError` instead of `CommError` when the server doesn't support the given automation (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12194)
- The message format used to communicate between internal processes has slightly changed. If you use `wandb beta core`, restart the service after upgrading `wandb`, as some operations may fail if the SDK and service versions differ. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12374)
- `wandb.sandbox` now allows GPU resource requests for sandboxes instead of rejecting `resources.gpu` client-side (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12455)
