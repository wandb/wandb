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

### Deprecated

- `wandb.sandbox` is deprecated and will be removed in a future release. Use the `cwsandbox` package directly instead.

### Fixed

- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- Single-element NumPy arrays stored in run config are now converted to native scalar values instead of strings. (@tandede, https://github.com/wandb/wandb/issues/1184)
- System metrics are now collected as soon as monitoring starts instead of after the first sampling interval (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
