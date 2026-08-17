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

- The automations API now supports team and organization scopes. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12197, https://github.com/wandb/wandb/pull/12194)
- The automations API now supports creating and editing automations whose scope is a `Registry` object (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10867)
- LEET line charts now show a dotted grid by default. Press `g` to cycle between the dotted grid, horizontal guides aligned with axis ticks, and no grid; the choice is saved and can also be set with `chart_grid` in `wandb leet config`. (@dmitryduev in https://github.com/wandb/wandb/pull/12463)

### Changed

- `Api.{create,update}_automation()` now raise `UnsupportedError` instead of `CommError` when the server doesn't support the given automation (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12194)
- The message format used to communicate between internal processes has slightly changed. If you use `wandb beta core`, restart the service after upgrading `wandb`, as some operations may fail if the SDK and service versions differ. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12374)
- `wandb.sandbox` now allows GPU resource requests for sandboxes instead of rejecting `resources.gpu` client-side (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12455)
