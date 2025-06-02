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

- wandb.Table: Added new constructor param, `log_mode`, with options `"IMMUTABLE"` and `"MUTABLE"`. `IMMUTABLE` log mode (default) is existing behavior that only allows a table to be logged once. `MUTABLE` log mode allows the table to be logged again if it has been mutated. (@domphan-wandb in https://github.com/wandb/wandb/pull/9758)
- wandb.Table: Added a new `log_mode`, `"INCREMENTAL"`, which logs newly added table data incrementally. (@domphan-wandb in https://github.com/wandb/wandb/pull/9810)

### Notable Changes

This version removes the ability to disable the `service` process. This is a breaking change.

### Added

- Added `merge` parameter to `Artifact.add_dir` to allow overwrite of previously-added artifact files (@pingleiwandb in https://github.com/wandb/wandb/pull/9907)
- Support for pytorch.tensor for `masks` and `boxes` parameters when creating a `wandb.Image` object. (jacobromero in https://github.com/wandb/wandb/pull/9802)
- `sync_tensorboard` now supports syncing tfevents files stored in S3, GCS and Azure (@timoffex in https://github.com/wandb/wandb/pull/9849)
  - GCS paths use the format `gs://bucket/path/to/log/dir` and rely on application-default credentials, which can be configured using `gcloud auth application-default login`
  - S3 paths use the format `s3://bucket/path/to/log/dir` and rely on the default credentials set through `aws configure`
  - Azure paths use the format `az://account/container/path/to/log/dir` and the `az login` credentials, but also require the `AZURE_STORAGE_ACCOUNT` and `AZURE_STORAGE_KEY` environment variables to be set. Some other environment variables are supported as well, see [here](https://pkg.go.dev/gocloud.dev@v0.41.0/blob/azureblob#hdr-URLs).
- Added support for initializing some Media objects with `pathlib.Path` (@jacobromero in https://github.com/wandb/wandb/pull/9692)
- New setting `x_skip_transaction_log` that allows to skip the transaction log. Note: Should be used with caution, as it removes the gurantees about recoverability. (@kptkin in https://github.com/wandb/wandb/pull/9064)
- `normalize` parameter to `wandb.Image` initialization to normalize pixel values for Images initialized with a numpy array or pytorch tensor. (@jacobromero in https://github.com/wandb/wandb/pull/9883)

### Changed

- Various APIs now raise `TypeError` instead of `ValueError` or other generic errors when given an argument of the wrong type. (@timoffex in https://github.com/wandb/wandb/pull/9902)
- Various Artifacts and Automations APIs now raise `CommError` instead of `ValueError` upon encountering server errors, so as to surface the server error message. (@ibindlish in https://github.com/wandb/wandb/pull/9933)
- `wandb.sdk.wandb_run.Run::save` method now requires the `glob_str` argument (@dmitryduev in https://github.com/wandb/wandb/pull/9962)

### Removed

- Removed support for disabling the `service` process. The `x_disable_service`/`_disable_service` setting and the `WANDB_DISABLE_SERVICE`/`WANDB_X_DISABLE_SERVICE` environment variable have been deprecated and will now raise an error if used (@kptkin in https://github.com/wandb/wandb/pull/9829)
- Removed ability to use `wandb.docker` after only importing `wandb` (@timoffex in https://github.com/wandb/wandb/pull/9941)
  - `wandb.docker` is not part of `wandb`'s public interface and is subject to breaking changes. Please do not use it.
- Removed no-op `sync` argument from `wandb.Run::log` function (@kptkin in https://github.com/wandb/wandb/pull/9940)
- Removed deprecated `wandb.sdk.wandb_run.Run.mode` property (@dmitryduev in https://github.com/wandb/wandb/pull/9958)
- Removed deprecated `wandb.sdk.wandb_run.Run::join` method (@dmitryduev in https://github.com/wandb/wandb/pull/9960)

### Deprecated

- The `start_method` setting is deprecated and has no effect; it is safely ignored (@kptkin in https://github.com/wandb/wandb/pull/9837)
- The property `Artifact.use_as` and parameter `use_as` for `run.use_artifact()` are deprecated since these have not been in use for W&B Launch (@ibindlish in https://github.com/wandb/wandb/pull/9760)

### Fixed

- Calling `wandb.teardown()` in a child of a process that called `wandb.setup()` no longer raises `WandbServiceNotOwnedError` (@timoffex in https://github.com/wandb/wandb/pull/9875)
  - This error could have manifested when using W&B Sweeps
- Offline runs with requested branching (fork or rewind) sync correctly (@dmitryduev in https://github.com/wandb/wandb/pull/9876)
- Log exception as string when raising exception in Job wait_until_running method (@KyleGoyette in https://github.com/wandb/wandb/pull/9607)
- `wandb.Image` initialized with tensorflow data would be normalized differently than when initialized with a numpy array (@jacobromero in https://github.com/wandb/wandb/pull/9883)
- Using `wandb login` no longer prints a warning about `wandb.require("legacy-service")` (@timoffex in https://github.com/wandb/wandb/pull/9912)
- Logging a `Table` (or other objects that create internal artifacts) no longer raises `ValueError` when logged from a run whose ID contains special characters. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9943)
- `wandb.Api` initialized with the `base_url` now respects the provided url, rather than the last login url (@jacobromero in https://github.com/wandb/wandb/pull/9942)
