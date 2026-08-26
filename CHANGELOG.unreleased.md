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
- Drag the separator lines between LEET's run overview sections to resize them with the mouse. The proportions are saved per view; press `0` to reset them along with the other pane sizes (@dmitryduev in https://github.com/wandb/wandb/pull/12525)
- Registry API version queries (`Api.registries().versions()`, `Api.registries().collections().versions()`, `Registry.versions()`, `Registry.collections().versions()`) now accept an optional `order` string as a keyword argument for organizations with advanced search. The API supports ordering versions by `created_at`, `artifact_size`, and `linked_at` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/12489)
- Added `Artifact.linked_at` which returns when the version was linked to the relevant portfolio. This is valid only for linked versions, and for source artifacts returns `None` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/12490)
- `wandb.Artifact` now accepts a `digest_algorithm` argument (`"MD5"` or `"XXH128"`, defaulting to `"MD5"`). Passing `digest_algorithm="XXH128"` opts the artifact into XXH128 hashing when possible. For artifacts created with `digest_algorithm="XXH128"`, `artifact.verify()` will fail for SDK versions older than 0.29.0. (@amusipatla-wandb in https://github.com/wandb/wandb/pull/12564)

### Changed

- The run overview sections in LEET (Environment, Config, Summary) now share the sidebar height proportionally and use all of the available space; previously they stopped growing at fixed sizes, leaving the bottom of tall terminals empty (@dmitryduev in https://github.com/wandb/wandb/pull/12523)
- `Api.{create,update}_automation()` now raise `UnsupportedError` instead of `CommError` when the server doesn't support the given automation (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12194)
- The message format used to communicate between internal processes has slightly changed. If you use `wandb beta core`, restart the service after upgrading `wandb`, as some operations may fail if the SDK and service versions differ. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12374)
- `wandb.sandbox` now allows GPU resource requests for sandboxes instead of rejecting `resources.gpu` client-side (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12455)
- Registry search methods (`Api.registries()`, `.collections()`, `.versions()`) now validate filter field names, rejecting unsupported field names. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12182)

### Removed

- Removed `wandb.tensorboard.log()` / `wandb.tensorflow.log()` (@timoffex in https://github.com/wandb/wandb/pull/12423)
- The deprecated `RunDisabled` class. `wandb.init(mode="disabled")` has returned a regular `wandb.Run` since v0.17.6 (@dmitryduev in https://github.com/wandb/wandb/pull/12586)

### Fixed

- `Artifact.new_file` now works for artifacts uploaded with `wandb sync` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/12437)
- At certain pane widths, such as while dragging a sidebar edge, LEET drew metric charts wider than the space available, pushing the right sidebar off screen (@dmitryduev in https://github.com/wandb/wandb/pull/12513)
- `wandb leet config` now works on short terminal windows: the field list scrolls with the selection and Space toggles boolean settings (@dmitryduev in https://github.com/wandb/wandb/pull/12529)
- `Run.scan_history(keys=...)` no longer fails for runs with nested values. (@mameikagou in https://github.com/wandb/wandb/pull/12542)

### Security

- Reject file or artifact name that contain relative path when downloading artifacts via `artifact.files()`, `artifact.checkout()` (@pingleiwandb in https://github.com/wandb/wandb/pull/12516)
