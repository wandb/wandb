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

- `wandb.Image` masks are no longer silently corrupted when `mask_data` is a float array with values outside 0-255. The range check previously only ran for integer dtypes, so out-of-range class ids were written to the saved mask wrapped modulo 256; they now raise `TypeError` like their integer equivalents already did (@Kayvan-Zahiri in https://github.com/wandb/wandb/pull/12685)
- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- System metrics are now collected as soon as monitoring starts instead of after the first sampling interval (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
