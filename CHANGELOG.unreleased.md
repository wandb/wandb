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

The default ordering for `Api().runs(...)` and `Api().sweeps(...)` is now ascending order based on the runs `created_at` time.

### Added

- Support `first` summary option in `define_metric` (@kptkin in https://github.com/wandb/wandb/pull/10121)
- Add support for paginated sweeps (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/10122)
- `pattern` parameter to `Api().run().files` to only get files matching a given pattern from the W&B backend (@jacobromero in https://github.com/wandb/wandb/pull/10163)
- Add optional `format` key to Launch input JSONSchema to specify a string with a secret format (@domphan-wandb in https://github.com/wandb/wandb/pull/10207)

### Changed

- `Sweep.name` property will now return user-edited display name if available (falling back to original name from sweep config, then sweep ID as before) (@kelu-wandb in https://github.com/wandb/wandb/pull/10144)
- `Api().runs(...)` and `Api().sweeps(...)` now returns runs in ascending order according to the runs `created_at` time. (@jacobromero in https://github.com/wandb/wandb/pull/10130)

### Fixed

- Correct the artifact url for organization registry artifacts to be independent of the artifact type (@ibindlish in https://github.com/wandb/wandb/pull/10049)
- Suffixes on sanitized `InternalArtifact` names have been shortened to 6 alphanumeric characters (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10102)
- `wandb.Video` will not print a progress spinner while encoding video when `WANDB_SILENT`/`WANDB_QUIET` environment variables are set (@jacobromero in https://github.com/wandb/wandb/pull/10064)
- Fixed registries fetched using `api.registries()` from having an extra `wandb-registry-` prefix in the name and full_name fields (@estellazx in https://github.com/wandb/wandb/pull/10187)
- Fixed a crash that could happen when using `sync_tensorboard` (@timoffex in https://github.com/wandb/wandb/pull/10199)
- `Api().run(...).upload_file` no longer throws an error when uploading a file in a different path relative to the provided root directory (@jacobromero in https://github.com/wandb/wandb/pull/10228)
- Calling `load()` function on a public API run object no longer throws `TypeError`. (@jacobromero in https://github.com/wandb/wandb/pull/10050)
- When a Sweeps run function called by `wandb.agent()` API throws an exception, we will now log that exception server-side. (This previously only happened for runs called by the `wandb agent` CLI command.) (@kelu-wandb in https://github.com/wandb/wandb/pull/10244)
