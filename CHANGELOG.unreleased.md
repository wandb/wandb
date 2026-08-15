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
- Press `g` in LEET to draw guides behind line charts: a dotted background or horizontal lines aligned with the axis ticks. The choice is saved and can also be set with `chart_guides` in `wandb leet config`. (@dmitryduev in https://github.com/wandb/wandb/pull/12463)

### Changed

- `Api.{create,update}_automation()` now raise `UnsupportedError` instead of `CommError` when the server doesn't support the given automation (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12194)
- The message format used to communicate between internal processes has slightly changed. If you use `wandb beta core`, restart the service after upgrading `wandb`, as some operations may fail if the SDK and service versions differ. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12374)
- `wandb.sandbox` now allows GPU resource requests for sandboxes instead of rejecting `resources.gpu` client-side (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12455)
- Registry search methods (`Api.registries()`, `.collections()`, `.versions()`) now validate filter field names, rejecting unsupported field names. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12182)
- `wandb.init()` now honors `mode="offline"` and `resume="..."` instead of logging a warning and ignoring the `resume` option. The requested mode is reconciled against the backend when the run is later synced with `wandb beta sync`. (@geoffhardy in https://github.com/wandb/wandb/pull/12110)
- New `.wandb` transaction logs are written with format version 1, reflecting the history-step on-disk change in wandb PR #12110. Current wandb readers accept both version 0 (legacy) and version 1 files; older wandb releases reject version 1 files. Sync version-1 offline runs with an upgraded `wandb beta sync`. (@geoffhardy)
- Shared-mode runs persist `shared_mode` on the transaction log's `RunRecord` at init time. `wandb beta sync` reads it so shared history uploads omit the step axis instead of inventing `_step` values. Pre-existing shared logs without the flag still get invented `_step` on sync. (@geoffhardy https://github.com/wandb/wandb/pull/????)

### Fixed

- `Artifact.new_file` now works for artifacts uploaded with `wandb sync` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/12437)
