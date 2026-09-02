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

### Changed

- A run's first logged metrics now appear in the UI within seconds of `wandb.log()` instead of up to 15 seconds later. Uploads start every 2 seconds after the first `wandb.log()` and gradually slow back to the usual interval; set `x_file_stream_transmit_interval_initial` to at least `x_file_stream_transmit_interval` to disable this (@dmitryduev in https://github.com/wandb/wandb/pull/12170)

### Deprecated

- `wandb.sandbox` is deprecated and will be removed in a future release. Use the `cwsandbox` package directly instead.

### Fixed

- Fractional values of `x_file_stream_transmit_interval`, such as `0.5`, are now honored instead of falling back to the default (@dmitryduev in https://github.com/wandb/wandb/pull/12170)
- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- System metrics are now collected as soon as monitoring starts instead of after the first sampling interval (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
