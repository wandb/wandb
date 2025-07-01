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

This version removes the legacy implementaion of the `service` process. This is a breaking change.

### Added

- Setting `x_stats_track_process_tree` to track process-specific metrics such as the RSS, CPU%, and thread count in use for the entire process tree, starting from `x_stats_pid`. This can be expensive and is disabled by default (@dmitryduev in https://github.com/wandb/wandb/pull/10089)
- Notes are now returned to the client when resuming a run (@kptkin in https://github.com/wandb/wandb/pull/9739)
- Added support for creating custom Vega chart presets through the API. Users can now define and upload custom chart specifications that can be then reused across runs with wandb.plot_table() (@thanos-wandb in https://github.com/wandb/wandb/pull/9931)

### Changed

- Calling `Artifact.link()` no longer instantiates a throwaway placeholder run. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9828)
- `wandb` now attempts to use Unix sockets for IPC instead of listening on localhost, making it work in environments with more restrictive permissions (such as Databricks) (@timoffex in https://github.com/wandb/wandb/pull/9995)
- `Api.artifact()` will now display a warning while fetching artifacts from migrated model registry collections. (@ibindlish in https://github.com/wandb/wandb/pull/10047)
- The `.length` for objects queried from `wandb.Api` has been deprecated. Use `len(...)` instead.

### Removed

- Removed the legacy python implementation of the `service` process. The `legacy-service` option of `wandb.require` as well as the `x_require_legacy_service` and `x_disable_setproctitle` settings with the corresponding environment variables have been removed and will now raise an error if used (@dmitryduev in https://github.com/wandb/wandb/pull/9965)

- Removed the private `wandb.Run._metadata` attribute. To override the auto-detected CPU and GPU counts as well as the GPU type, please use the new settings `x_stats_{cpu_count,cpu_logical_count,gpu_count,gpu_type}` (@dmitryduev in https://github.com/wandb/wandb/pull/9984)

### Fixed

- Allow s3 style CoreWeave URIs for reference artifacts. (@estellazx in https://github.com/wandb/wandb/pull/9979)
- Fixed rare bug that made Ctrl+C ineffective after logging large amounts of data (@timoffex in https://github.com/wandb/wandb/pull/10071)
- Respect `silent`, `quiet`, and `show_warnings` settings passed to a `Run` instance for warnings emitted by the service process (@kptkin in https://github.com/wandb/wandb/pull/10077)
- `api.Runs` no longer makes an API call for each run loaded from W&B. (@jacobromero in https://github.com/wandb/wandb/pull/10087)
- Correctly parse the `x_extra_http_headers` setting from the env variable (@dmitryduev in https://github.com/wandb/wandb/pull/10103)
- `.length` calls the W&B backend to load the length of objects when no data has been loaded rather than returning `None` (@jacobromero in https://github.com/wandb/wandb/pull/10091)
