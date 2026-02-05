# Changelog

All notable changes to this project will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Starting with the 0.16.4 release on March 5, 2024, the format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Unreleased changes are in [CHANGELOG.unreleased.md](CHANGELOG.unreleased.md).

<!-- tools/changelog.py: insert here -->

## [0.24.2] - 2026-02-04

### Added

- wandb.Api() now supports Federated Auth (JWT based authentication). (@ryanbuccellato in https://github.com/wandb/wandb/pull/11243)

### Fixed

- Refresh presigned download url when it expires during artifact file downloads. (@pingleiwandb in https://github.com/wandb/wandb/pull/11242)

## [0.24.1] - 2026-01-29

### Notable Changes

Runs created with `wandb==0.24.0` may fail to upload some data, which this release fixes. Missing data is stored in the run's `.wandb` file and can be reuploaded with `wandb sync`.

### Added

- `download_history_exports` in `api.Run` class to download exported run history in parquet file format (@jacobromero in https://github.com/wandb/wandb/pull/11094)

### Changed

- When a settings file (such as `./wandb/settings` or `~/.config/wandb/settings`) contains an invalid setting, all settings files are ignored and an error is printed (@timoffex in https://github.com/wandb/wandb/pull/11207)

### Fixed

- After `wandb login --host <invalid-url>`, using `wandb login --host <valid-url>` works as usual (@timoffex in https://github.com/wandb/wandb/pull/11207)
  - Regression introduced in 0.24.0
- `wandb beta sync` correctly loads credentials (@timoffex in https://github.com/wandb/wandb/pull/11231)
  - Regression introduced in 0.24.0
  - Caused `wandb beta sync` to get stuck on `Syncing...`
- Fixed occasional unuploaded data in 0.24.0 (@timoffex in https://github.com/wandb/wandb/pull/11249)
  - All data is stored in the run's `.wandb` file and can be reuploaded with `wandb sync`

## [0.24.0] - 2026-01-13

### Notable Changes

This version removes the legacy, deprecated `wandb.beta.workflows` module, including its `log_model()`/`use_model()`/`link_model()` functions. This is formally a breaking change.

### Added

- `wandb agent` and `wandb.agent()` now accept a `forward_signals` flag (CLI: `--forward-signals/-f`) to relay SIGINT/SIGTERM and other catchable signals from the agent to its sweep child runs, enabling cleaner shutdowns when you interrupt an agent process (@kylegoyette, @domphan-wandb in https://github.com/wandb/wandb/pull/9651)
- `wandb beta sync` now supports a `--live` option for syncing a run while it's being logged (@timoffex in https://github.com/wandb/wandb/pull/11079)

### Removed

- Removed the deprecated `wandb.beta.workflows` module, including its `log_model()`, `use_model()`, and `link_model()` functions, and whose modern successors are the `Run.log_artifact`, `Run.use_artifact`, and `Run.link_artifact` methods, respectively (@tonyyli-wandb in [TODO: PR link])

### Fixed

- Fixed `Run.__exit__` type annotations to accept `None` values, which are passed when no exception is raised (@moldhouse in https://github.com/wandb/wandb/pull/11100)
- Fixed `Invalid Client ID digest` error when creating artifacts after calling `random.seed()`. Client IDs could collide when random state was seeded deterministically. (@pingleiwandb in https://github.com/wandb/wandb/pull/11039)
- Fixed CLI error when listing empty artifacts (@ruhiparvatam in https://github.com/wandb/wandb/pull/11157)
- Fixed regression for calling `api.run()` on a Sweeps run (@willtryagain in https://github.com/wandb/wandb/pull/11088 and @kelu-wandb in https://github.com/wandb/wandb/pull/11097)
- Fixed the "View run at" message printed at the end of a run which sometimes did not include a URL (@timoffex in https://github.com/wandb/wandb/pull/11113)
- Runs queried from wandb.Api() now display a string representation in VSCode notebooks instead of a broken HTML window (@jacobromero in https://github.com/wandb/wandb/pull/11040)

## [0.23.1] - 2025-12-03

### Added

- Regex support in metrics and run overview filters in W&B LEET TUI (@dmitryduev in https://github.com/wandb/wandb/pull/10919)
- Chart inspection in W&B LEET TUI: right-click and drag to show (x, y) at the nearest data point; hold Alt for synchronized inspection across all visible charts (@dmitryduev in https://github.com/wandb/wandb/pull/10989)
- The automations API now supports creating and editing automations that trigger on run states (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10848)
- The automations API now support basic zscore automation events (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10931)
- Simplified the syntax for creating z-score metric automation triggers in the automations API (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10953)
- `beta_history_scan` method to `Run` objects for faster history scanning performance with `wandb.Api` (@jacobromero in https://github.com/wandb/wandb/pull/10779)

### Changed

- `wandb.Api()` now raises a `UsageError` if `WANDB_IDENTITY_TOKEN_FILE` is set and an explicit API key is not provided (@timoffex in https://github.com/wandb/wandb/pull/10970)
  - `wandb.Api()` has only ever worked using an API key

### Deprecated

- Anonymous mode, including the `anonymous` setting, the `WANDB_ANONYMOUS` environment variable, `wandb.init(anonymous=...)`, `wandb login --anonymously` and `wandb.login(anonymous=...)` is deprecated and will emit warnings (@timoffex in https://github.com/wandb/wandb/pull/10909)

### Fixed

- `wandb.Image()` no longer prints a deprecation warning (@jacobromero in https://github.com/wandb/wandb/pull/10880)
- `Registry.description` and `ArtifactCollection.description` no longer reject empty strings (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10891)
- Instantiating `Artifact` objects is now significantly faster (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10819)
- `wandb.Run.save()` now falls back to hardlinks and, if needed, copying (downgrading the 'live' file policy to 'now', if applicable) when symlinks are disabled or unavailable (e.g., cross‑volume or no Developer Mode on Windows) (@dmitryduev in https://github.com/wandb/wandb/pull/10894)
- Artifact collection aliases are now fetched lazily on accessing `ArtifactCollection.aliases` instead of on instantiating `ArtifactCollection`, improving performance of `Api.artifact_collections()`, `Api.registries().collections()`, etc. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10731)
- Use explicitly provided API key in `wandb.init(settings=wandb.Settings(api_key="..."))` for login. Use the key from run when logging artifacts via `run.log_artifact` (@pingleiwandb in https://github.com/wandb/wandb/pull/10914)
- W&B LEET TUI correctly displays negative Y axis tick values and base/display units of certain system metrics (@dmitryduev in https://github.com/wandb/wandb/pull/10905)
- Fixed a rare infinite loop in `console_capture.py` (@timoffex in https://github.com/wandb/wandb/pull/10955)
- File upload/download now respects `WANDB_X_EXTRA_HTTP_HEADERS` except for [reference artifacts](https://docs.wandb.ai/models/artifacts/track-external-files) (@pingleiwandb in https://github.com/wandb/wandb/pull/10761)

## [0.23.0] - 2025-11-11

### Added

- Experimental `wandb beta leet` command - Lightweight Experiment Exploration Tool - a terminal UI for viewing W&B runs locally with real-time metrics visualization and system monitoring (@dmitryduev in https://github.com/wandb/wandb/pull/10764)
- The registry API now supports programmatic management of user and team members of individual registries. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10542)
- `Registry.id` has been added as a (read-only) property of `Registry` objects (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10785).

### Fixed

- `Artifact.files()` now has a correct `len()` when filtering by the `names` parameter (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10796)
- The numerator for file upload progress no longer occasionally exceeds the total file size (@timoffex in https://github.com/wandb/wandb/pull/10812)
- `Artifact.link()` now logs unsaved artifacts instead of raising an error, consistent with the behavior of `Run.link_artifact()` (@tonyyli-wandb in https://github.com/wandb/wandb/10822)
- Automatic code saving now works when running ipython notebooks in VSCode's Jupyter notebook extension (@jacobromero in https://github.com/wandb/wandb/pull/10746)
- Logging an artifact with infinite floats in `Artifact.metadata` now raises a `ValueError` early, instead of waiting on request retries to time out (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10845).

## [0.22.3] - 2025-10-28

### Added

- Settings `console_chunk_max_seconds` and `console_chunk_max_bytes` for size- and time-based multipart console logs file chunking (@dmitryduev in https://github.com/wandb/wandb/pull/10162)
- Registry API query methods (`Api.registries()`, `Registry.{collections,versions}()`, `Api.registries().{collections,versions}()`) now accept a `per_page` keyword arg to override the default batch size for paginated results (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10713).

### Changed

- API keys longer than 40 characters are now supported. (@jennwandb in https://github.com/wandb/wandb/pull/10688)

### Fixed

- `run.config` now properly returns a dict when calling `artifact.logged_by()` in v0.22.1 (@thanos-wandb in #10682)
- `wandb.Api(api_key=...)` now prioritizes the explicitly provided API key over thread-local cached credentials (@pingleiwandb in https://github.com/wandb/wandb/pull/10657)
- Fixed a rare deadlock in `console_capture.py` (@timoffex in https://github.com/wandb/wandb/pull/10683)
  - If you dump thread tracebacks during the deadlock and see the `wandb-AsyncioManager-main` thread stuck on a line in `console_capture.py`: this is now fixed.
- Fixed an issue where TensorBoard sync would sometimes stop working if the tfevents files were being written live (@timoffex in https://github.com/wandb/wandb/pull/10625)
- `Artifact.manifest` delays downloading **and** generating the download URL for the artifact manifest until it's first used. If the manifest has not been locally modified, `Artifact.size` and `Artifact.digest` can return without waiting to fetch the full manifest (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10680)
- Fixed uploading GCS folder references via `artifact.add_reference` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/10679)
- The SDK now correctly infers notebooks paths in Jupyter sessions, using th server's root directory, so code saving works in subdirectories (e.g. code/nested/<notebook>.ipynb) (@jacobromero in https://github.com/wandb/wandb/pull/10709)

## [0.22.2] - 2025-10-07

### Fixed

- Possibly fixed some cases where the `output.log` file was not being uploaded (@timoffex in https://github.com/wandb/wandb/pull/10620)
- Fixed excessive data uploads when calling `run.save()` repeatedly on unchanged files (@dmitryduev in https://github.com/wandb/wandb/pull/10639)

## [0.22.1] - 2025-09-29

### Added

- Optimize artifacts downloads re-verification with checksum caching (@thanos-wandb in https://github.com/wandb/wandb/pull/10157)
- Lazy loading support for `Api().runs()` to improve performance when listing runs. The new `lazy=True` parameter (default) loads only essential metadata initially, with automatic on-demand loading of heavy fields like config and summary when accessed (@thanos-wandb in https://github.com/wandb/wandb/pull/10034)
- Add `storage_region` option when creating artifacts. Users can use [CoreWeave AI Object Storage](https://docs.coreweave.com/docs/products/storage/object-storage) by specifying `wandb.Artifact(storage_region="coreweave-us")` when using wandb.ai for faster artifact upload/download on CoreWeave's infrastructure. (@pingleiwandb in https://github.com/wandb/wandb/pull/10533)

### Fixed

- `Api.artifact_exists()` and `Api.artifact_collection_exists()` now raise on encountering timeout errors, rather than (potentially erroneously) returning `False`. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10591)

## [0.22.0] - 2025-09-18

### Notable Changes

This version removes support of MacOS 10.

### Removed

- Remove a build targeting MacOS 10.x due to multiple security and supply chain considerations (@dmitryduev in https://github.com/wandb/wandb/pull/10529)

### Fixed

- Resuming a run with a different active run will now raise an error unless you call `run.finish()` first, or call `wandb.init()` with the parameter `reinit='create_new'` (@jacobromero in https://github.com/wandb/wandb/pull/10468)
- Fix `Api().runs()` for wandb server < 0.51.0 (when `project.internalId` was added to gql API) (@kelu-wandb in https://github.com/wandb/wandb/pull/10507)
- Sweeps: `command` run scripts that `import readline` whether directly or indirectly (e.g. `import torch` on Python 3.13) should no longer deadlock (@kelu-wandb in https://github.com/wandb/wandb/pull/10489)

## [0.21.4] - 2025-09-11

### Added

- Add DSPy integration: track evaluation metrics over time, log predictions and program signature evolution to W&B Tables, and save DSPy programs as W&B Artifacts (complete program or state as JSON/PKL) (@ayulockin in https://github.com/wandb/wandb/pull/10327)

## [0.21.3] - 2025-08-30

### Changed

- Updated `click` dependency constraint from `>=7.1` to `>=8.0.1` (@willtryagain in https://github.com/wandb/wandb/pull/10418)

### Fixed

- The message "Changes to your wandb environment variables will be ignored" is no longer printed when nothing changed (@timoffex in https://github.com/wandb/wandb/pull/10420)

## [0.21.2] - 2025-08-28

### Notable Changes

This version raises errors that would previously have been suppressed during calls to `Artifact.link()` or `Run.link_artifact()`. While this prevents undetected failures in those methods, it is also a breaking change.

### Added

- New settings for `max_end_of_run_history_metrics` and `max_end_of_run_summary_metrics` (@timoffex in https://github.com/wandb/wandb/pull/10351)
- New `wandb.integration.weave` module for automatically initializing Weave when a W&B run is active and `weave` is imported (@andrewtruong in https://github.com/wandb/wandb/pull/10389)

### Changed

- Errors encountered while linking an artifact are no longer suppressed/silenced, and `Artifact.link()` and `Run.link_artifact()` no longer return `None` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9968)
- The "Run history" and "Run summary" printed at the end of a run are now limited to 10 metrics each (@timoffex in https://github.com/wandb/wandb/pull/10351)

### Fixed

- Dataclasses in a run's `config` no long raise `Object of type ... is not JSON serializable` when containing real classes as fields to the dataclass (@jacobromero in https://github.com/wandb/wandb/pull/10371)
- `Artifact.link()` and `Run.link_artifact()` should be faster on server versions 0.74.0+, requiring 4-5 fewer unnecessary blocking GraphQL requests (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10393).

## [0.21.1] - 2025-08-07

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
- Artifact with large file (>2GB) uploads faster by using parallel hashing on system with more cores (@pingleiwandb in https://github.com/wandb/wandb/pull/10136)
- Remove the implementation of `__bool__` for the registry iterators to align with python lazy iterators. (@estellazx in https://github.com/wandb/wandb/pull/10259)

### Deprecated

- The `wandb.beta.workflows` module and its contents (including `log_model()`, `use_model()`, and `link_model()`) are deprecated and will be removed in a future release (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10205).

### Fixed

- Correct the artifact url for organization registry artifacts to be independent of the artifact type (@ibindlish in https://github.com/wandb/wandb/pull/10049)
- Suffixes on sanitized `InternalArtifact` names have been shortened to 6 alphanumeric characters (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10102)
- `wandb.Video` will not print a progress spinner while encoding video when `WANDB_SILENT`/`WANDB_QUIET` environment variables are set (@jacobromero in https://github.com/wandb/wandb/pull/10064)
- Fixed registries fetched using `api.registries()` from having an extra `wandb-registry-` prefix in the name and full_name fields (@estellazx in https://github.com/wandb/wandb/pull/10187)
- Fixed a crash that could happen when using `sync_tensorboard` (@timoffex in https://github.com/wandb/wandb/pull/10199)
- `Api().run(...).upload_file` no longer throws an error when uploading a file in a different path relative to the provided root directory (@jacobromero in https://github.com/wandb/wandb/pull/10228)
- Calling `load()` function on a public API run object no longer throws `TypeError`. (@jacobromero in https://github.com/wandb/wandb/pull/10050)
- When a Sweeps run function called by `wandb.agent()` API throws an exception, it will now appear on the logs page for the run. (This previously only happened for runs called by the `wandb agent` CLI command.) (@kelu-wandb in https://github.com/wandb/wandb/pull/10244)

## [0.21.0] - 2025-07-01

### Notable Changes

This version removes the legacy implementation of the `service` process. This is a breaking change.

### Added

- Setting `x_stats_track_process_tree` to track process-specific metrics such as the RSS, CPU%, and thread count in use for the entire process tree, starting from `x_stats_pid`. This can be expensive and is disabled by default (@dmitryduev in https://github.com/wandb/wandb/pull/10089)
- Notes are now returned to the client when resuming a run (@kptkin in https://github.com/wandb/wandb/pull/9739)
- Added support for creating custom Vega chart presets through the API. Users can now define and upload custom chart specifications that can be then reused across runs with wandb.plot_table() (@thanos-wandb in https://github.com/wandb/wandb/pull/9931)

### Changed

- Calling `Artifact.link()` no longer instantiates a throwaway placeholder run (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9828)
- `wandb` now attempts to use Unix sockets for IPC instead of listening on localhost, making it work in environments with more restrictive permissions (such as Databricks) (@timoffex in https://github.com/wandb/wandb/pull/9995)
- `Api.artifact()` will now display a warning while fetching artifacts from migrated model registry collections (@ibindlish in https://github.com/wandb/wandb/pull/10047)
- The `.length` for objects queried from `wandb.Api` has been deprecated. Use `len(...)` instead (@jacobromero in https://github.com/wandb/wandb/pull/10091)

### Removed

- Removed the legacy python implementation of the `service` process. The `legacy-service` option of `wandb.require` as well as the `x_require_legacy_service` and `x_disable_setproctitle` settings with the corresponding environment variables have been removed and will now raise an error if used (@dmitryduev in https://github.com/wandb/wandb/pull/9965)

- Removed the private `wandb.Run._metadata` attribute. To override the auto-detected CPU and GPU counts as well as the GPU type, please use the new settings `x_stats_{cpu_count,cpu_logical_count,gpu_count,gpu_type}` (@dmitryduev in https://github.com/wandb/wandb/pull/9984)

### Fixed

- Allow s3 style CoreWeave URIs for reference artifacts (@estellazx in https://github.com/wandb/wandb/pull/9979)
- Fixed rare bug that made Ctrl+C ineffective after logging large amounts of data (@timoffex in https://github.com/wandb/wandb/pull/10071)
- Respect `silent`, `quiet`, and `show_warnings` settings passed to a `Run` instance for warnings emitted by the service process (@kptkin in https://github.com/wandb/wandb/pull/10077)
- `api.Runs` no longer makes an API call for each run loaded from W&B (@jacobromero in https://github.com/wandb/wandb/pull/10087)
- Correctly parse the `x_extra_http_headers` setting from the env variable (@dmitryduev in https://github.com/wandb/wandb/pull/10103)
- `.length` calls the W&B backend to load the length of objects when no data has been loaded rather than returning `None` (@jacobromero in https://github.com/wandb/wandb/pull/10091)

## [0.20.1] - 2025-06-04

### Fixed

- `wandb.Image()` was broken in 0.20.0 when given NumPy arrays with values in the range [0, 1], now fixed (@timoffex in https://github.com/wandb/wandb/pull/9982)

## [0.20.0] - 2025-06-03

- wandb.Table: Added new constructor param, `log_mode`, with options `"IMMUTABLE"` and `"MUTABLE"`. `IMMUTABLE` log mode (default) is existing behavior that only allows a table to be logged once. `MUTABLE` log mode allows the table to be logged again if it has been mutated. (@domphan-wandb in https://github.com/wandb/wandb/pull/9758)
- wandb.Table: Added a new `log_mode`, `"INCREMENTAL"`, which logs newly added table data incrementally. (@domphan-wandb in https://github.com/wandb/wandb/pull/9810)

### Notable Changes

This version removes the ability to disable the `service` process. This is a breaking change.

### Added

- Added `merge` parameter to `Artifact.add_dir` to allow overwrite of previously-added artifact files (@pingleiwandb in https://github.com/wandb/wandb/pull/9907)
- Support for pytorch.tensor for `masks` and `boxes` parameters when creating a `wandb.Image` object. (@jacobromero in https://github.com/wandb/wandb/pull/9802)
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

## [0.19.11] - 2025-05-07

### Added

- Added creation, deletion, and updating of registries in the SDK. (@estellazx in https://github.com/wandb/wandb/pull/9453)
- `artifact.is_link` property to artifacts to determine if an artifact is a link artifact (such as in the Registry) or source artifact. (@estellazx in https://github.com/wandb/wandb/pull/9764)
- `artifact.linked_artifacts` to fetch all the linked artifacts to a source artifact and `artifact.source_artifact` to fetch the source artifact of a linked artifact. (@estellazx in https://github.com/wandb/wandb/pull/9789)
- `run.link_artifact()`, `artifact.link()`, and `run.link_model()` all return the linked artifact upon linking (@estellazx in https://github.com/wandb/wandb/pull/9763)
- Multipart download for artifact file larger than 2GB, user can control it directly using `artifact.download(multipart=True)`. (@pingleiwandb in https://github.com/wandb/wandb/pull/9738)
- `Project.id` property to get the project ID on a `wandb.public.Project` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9194).
- New public API for W&B Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9693, https://github.com/wandb/wandb/pull/8935, https://github.com/wandb/wandb/pull/9194, https://github.com/wandb/wandb/pull/9197, https://github.com/wandb/wandb/pull/8896, https://github.com/wandb/wandb/pull/9246)
  - New submodules and classes in `wandb.automations.*` to support programmatically managing W&B Automations.
  - `Api.integrations()`, `Api.slack_integrations()`, `Api.webhook_integrations()` to fetch a team's existing Slack or webhook integrations.
  - `Api.create_automation()`, `Api.automation()`/`Api.automations()`, `Api.update_automation()`, `Api.delete_automation()` to create, fetch, edit, and delete Automations.
- Create and edit automations triggered on `RUN_METRIC_CHANGE` events, i.e. on changes in run metric values (absolute or relative deltas). (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9775)
- Ability to collect profiling metrics for Nvidia GPUs using DCGM. To enable, set the `WANDB_ENABLE_DCGM_PROFILING` environment variable to `true`. Requires the `nvidia-dcgm` service to be running on the machine. Enabling this feature can lead to increased resource usage. (@dmitryduev in https://github.com/wandb/wandb/pull/9780)

### Fixed

- `run.log_code` correctly sets the run configs `code_path` value. (@jacobromero in https://github.com/wandb/wandb/pull/9753)
- Correctly use `WANDB_CONFIG_DIR` for determining system settings file path (@jacobromero in https://github.com/wandb/wandb/pull/9711)
- Prevent invalid `Artifact` and `ArtifactCollection` names (which would make them unloggable), explicitly raising a `ValueError` when attempting to assign an invalid name. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8773)
- Prevent pydantic `ConfigError` in Pydantic v1 environments from not calling `.model_rebuild()/.update_forward_refs()` on generated types with ForwardRef fields (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9795)
- `wandb.init()` no longer raises `Permission denied` error when the wandb directory is not writable or readable (@jacobromero in https://github.com/wandb/wandb/pull/9751)
- Calling `file.delete()` on files queried via `api.Runs(...)` no longer raises `CommError` (@jacobromero in https://github.com/wandb/wandb/pull/9748)
  - Bug introduced in 0.19.1

## [0.19.10] - 2025-04-22

### Added

- The new `reinit="create_new"` setting causes `wandb.init()` to create a new run even if other runs are active, without finishing the other runs (in contrast to `reinit="finish_previous"`). This will eventually become the default (@timoffex in https://github.com/wandb/wandb/pull/9562)
- Added `Artifact.history_step` to return the nearest run step at which history metrics were logged for the artifact's source run (@ibindlish in https://github.com/wandb/wandb/pull/9732)
- Added `data_is_not_path` flag to skip file checks when initializing `wandb.Html` with a sting that points to a file.

### Changed

- `Artifact.download()` no longer raises an error when using `WANDB_MODE=offline` or when an offline run exists (@timoffex in https://github.com/wandb/wandb/pull/9695)

### Removed

- Dropped the `-q` / `--quiet` argument to the `wandb` magic in IPython / Jupyter; use the `quiet` run setting instead (@timoffex in https://github.com/wandb/wandb/pull/9705)

### Deprecated

- The following `wandb.Run` methods are deprecated in favor of properties and will be removed in a future release (@kptkin in https://github.com/wandb/wandb/pull/8925):
  - `run.project_name()` is deprecated in favor of `run.project`
  - `run.get_url()` method is deprecated in favor of `run.url`
  - `run.get_project_url()` method is deprecated in favor of `run.project_url`
  - `run.get_sweep_url()` method is deprecated in favor of `run.sweep_url`

### Fixed

- Fixed ValueError on Windows when running a W&B script from a different drive (@jacobromero in https://github.com/wandb/wandb/pull/9678)
- Fix base_url setting was not provided to wandb.login (@jacobromero in https://github.com/wandb/wandb/pull/9703)
- `wandb.Html()` no longer raises `IsADirectoryError` with a value that matched a directory on the users system. (@jacobromero in https://github.com/wandb/wandb/pull/9728)

## [0.19.9] - 2025-04-01

### Added

- The `reinit` setting can be set to `"default"` (@timoffex in https://github.com/wandb/wandb/pull/9569)
- Added support for building artifact file download urls using the new url scheme, with artifact collection membership context (@ibindlish in https://github.com/wandb/wandb/pull/9560)

### Changed

- Boolean values for the `reinit` setting are deprecated; use "return_previous" and "finish_previous" instead (@timoffex in https://github.com/wandb/wandb/pull/9557)
- The "wandb" logger is configured with `propagate=False` at import time, whereas it previously happened when starting a run. This may change the messages observed by the root logger in some workflows (@timoffex in https://github.com/wandb/wandb/pull/9540)
- Metaflow now requires `plum-dispatch` package. (@jacobromero in https://github.com/wandb/wandb/pull/9599)
- Relaxed the `pydantic` version requirement to support both v1 and v2 (@dmitryduev in https://github.com/wandb/wandb/pull/9605)
- Existing `pydantic` types have been adapted to be compatible with Pydantic v1 (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9623)
- `wandb.init(dir=...)` now creates any nonexistent directories in `dir` if it has a parent directory that is writeable (@ringohoffman in https://github.com/wandb/wandb/pull/9545)
- The server now supports fetching artifact files by providing additional collection information; updated the artifacts api to use the new endpoints instead (@ibindlish in https://github.com/wandb/wandb/pull/9551)
- Paginated methods (and underlying paginators) that accept a `per_page` argument now only accept `int` values. Default `per_page` values are set directly in method signatures, and explicitly passing `None` is no longer supported (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9201)

### Fixed

- Calling `wandb.init()` in a notebook finishes previous runs as previously documented (@timoffex in https://github.com/wandb/wandb/pull/9569)
  - Bug introduced in 0.19.0
- Fixed an error being thrown when logging `jpg`/`jpeg` images containing transparency data (@jacobromero in https://github.com/wandb/wandb/pull/9527)
- `wandb.init(resume_from=...)` now works without explicitly specifying the run's `id` (@kptkin in https://github.com/wandb/wandb/pull/9572)
- Deleting files with the Public API works again (@jacobromero in https://github.com/wandb/wandb/pull/9604)
  - Bug introduced in 0.19.1
- Fixed media files not displaying in the UI when logging to a run with a custom storage bucket (@jacobromero in https://github.com/wandb/wandb/pull/9661)

## [0.19.8] - 2025-03-04

### Fixed

- Media file paths containing special characters (?, \*, ], [ or \\) no longer cause file uploads to fail in `wandb-core` (@jacobromero in https://github.com/wandb/wandb/pull/9475)

### Changed

- The system monitor now samples metrics every 15 seconds by default, up from 10 seconds (@kptkin in https://github.com/wandb/wandb/pull/9554)

## [0.19.7] - 2025-02-21

### Added

- Registry search api (@estellazx in https://github.com/wandb/wandb/pull/9472)

### Changed

- changed moviepy constraint to >=1.0.0 (@jacobromero in https://github.com/wandb/wandb/pull/9419)
- `wandb.init()` displays more detailed information, in particular when it is stuck retrying HTTP errors (@timoffex in https://github.com/wandb/wandb/pull/9431)

### Removed

- Removed the private `x_show_operation_stats` setting (@timoffex in https://github.com/wandb/wandb/pull/9427)

### Fixed

- Fixed incorrect logging of an "wandb.Video requires moviepy \[...\]" exception when using moviepy v2. (@Daraan in https://github.com/wandb/wandb/pull/9375)
- `wandb.setup()` correctly starts up the internal service process; this semantic was unintentionally broken in 0.19.2 (@timoffex in https://github.com/wandb/wandb/pull/9436)
- Fixed `TypeError: Object of type ... is not JSON serializable` when using numpy number types as values. (@jacobromero in https://github.com/wandb/wandb/pull/9487)

## [0.19.6] - 2025-02-05

### Added

- Prometheus API support for Nvidia DCGM GPU metrics collection (@dmitryduev in https://github.com/wandb/wandb/pull/9369)

### Changed

- Changed Nvidia GPU ECC counters from aggregated to volatile (@gritukan in https://github.com/wandb/wandb/pull/9347)

### Fixed

- Fixed a performance issue causing slow instantiation of `wandb.Artifact`, which in turn slowed down fetching artifacts in various API methods. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9355)
- Some errors from `wandb.Api` have better string representations (@timoffex in https://github.com/wandb/wandb/pull/9361)
- Artifact.add_reference, when used with file URIs for a directory and the name parameter, was incorrectly adding the value of `name` to the path of the file references (@ssisk in https://github.com/wandb/wandb/pull/9378)
- Fixed a bug causing `Artifact.add_reference()` with `checksum=False` to log new versions of local reference artifacts without changes to the reference URI. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9326)

## [0.19.5] - 2025-01-29

### Added

- Added `wandb login --base-url {host_url}` to login as an alias of `wandb login --host {host_url}`. (@jacobromero in https://github.com/wandb/wandb/pull/9323)

### Changed

- Temporarily disabled collecting per-core CPU utilization stats (@dmitryduev in https://github.com/wandb/wandb/pull/9350)

### Fixed

- Fixed a bug causing `offline` mode to make network requests when logging media artifacts. If you are using an older version of W&B Server that does not support offline artifact uploads, use the setting `allow_offline_artifacts=False` to revert to older compatible behavior. (@domphan-wandb in https://github.com/wandb/wandb/pull/9267)
- Expand sanitization rules for logged table artifact name to allow for hyphens and dots. This update brings the rules up-to-date with the current rules for artifact names. (Allowing letters, numbers, underscores, hyphens, and dots) (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/9271)
- Correctly handle run rewind settings `fork_from` and `resume_from`. (@dmitryduev in https://github.com/wandb/wandb/pull/9331)

## [0.19.4] - 2025-01-16

### Fixed

- Fix incorrectly reported device counts and duty cycle measurements for TPUs with single devices per chip / multiple devices on the host and make TPU metrics sampling more robust (@dmitryduev in https://github.com/wandb/wandb/pull/9266)
- Handle non-consecutive TPU device IDs in system monitor (@dmitryduev in https://github.com/wandb/wandb/pull/9276)

## [0.19.3] - 2025-01-13

### Fixed

- Fix `wandb.Settings` update regression in `wandb.integration.metaflow` (@kptkin in https://github.com/wandb/wandb/pull/9211)

## [0.19.2] - 2025-01-07

### Added

- Support JWT authentication in wandb-core (@elainaRenee in https://github.com/wandb/wandb/pull/8431)
- Add support for logging nested custom charts. (@jacobromero in https://github.com/wandb/wandb/pull/8789)

### Changed

- Calling `wandb.init(mode="disabled")` no longer disables all later runs by default. Use `wandb.setup(settings=wandb.Settings(mode="disabled"))` for this instead, or set `mode="disabled"` explicitly in each call to `wandb.init()`. (@timoffex in https://github.com/wandb/wandb/pull/9172)

### Fixed

- The stop button correctly interrupts runs whose main Python thread is running C code, sleeping, etc. (@timoffex in https://github.com/wandb/wandb/pull/9094)
- Remove unintentional print that occurs when inspecting `wandb.Api().runs()` (@tomtseng in https://github.com/wandb/wandb/pull/9101)
- Fix uploading large artifacts when using Azure Blob Storage. (@amulya-musipatla in https://github.com/wandb/wandb/pull/8946)
- The `wandb offline` command no longer adds an unsupported setting to `wandb.Settings`, resolving `ValidationError`. (@kptkin in https://github.com/wandb/wandb/pull/9135)
- Fix error when reinitializing a run, caused by accessing a removed attribute. (@MathisTLD in https://github.com/wandb/wandb/pull/8912)
- Fixed occasional deadlock when using `multiprocessing` to update a single run from multiple processes (@timoffex in https://github.com/wandb/wandb/pull/9126)
- Prevent errors from bugs in older versions of `botocore < 1.5.76` (@amusipatla-wandb, @tonyyli-wandb in https://github.com/wandb/wandb/pull/9015)
- Fixed various checks against invalid `anonymous` settings value. (@jacobromero in https://github.com/wandb/wandb/pull/9193)

### Removed

- The `wandb.wandb_sdk.wandb_setup._setup()` function's `reset` parameter has been removed. Note that this is a private function, even though there appear to be usages outside of the repo. Please `wandb.teardown()` instead of `_setup(reset=True)`. (@timoffex in https://github.com/wandb/wandb/pull/9165)
- In the private `wandb.wandb_sdk.wandb_setup` module, the `logger` and `_set_logger` symbols have been removed (@timoffex in https://github.com/wandb/wandb/pull/9195)

### Security

- Bump `github.com/go-git/go-git` version to 5.13.0 to address CVE-2025-21613. (@kptkin in https://github.com/wandb/wandb/pull/9192)
- Bump `golang.org/x/net` version to 0.33.0 to address CVE-2024-45338. (@kptkin in https://github.com/wandb/wandb/pull/9115)

## [0.19.1] - 2024-12-13

### Fixed

- Fixed bug where setting WANDB\_\_SERVICE_WAIT led to an exception during wandb.init (@TimSchneider42 in https://github.com/wandb/wandb/pull/9050)

### Changed

- `run.finish()` displays more detailed information in the terminal and in Jupyter notebooks (by @timoffex, enabled in https://github.com/wandb/wandb/pull/9070)
- Improved error message for failing tensorboard.patch() calls to show the option to call tensorboard.unpatch() first (@daniel-bogdoll in https://github.com/wandb/wandb/pull/8938)
- Add projectId to deleteFiles mutation if the server supports it. (@jacobromero in https://github.com/wandb/wandb/pull/8837)

### Security

- Bump `golang.org/x/crypto` version to 0.31.0 to address CVE-2024-45337. (@kptkin in https://github.com/wandb/wandb/pull/9069)

## [0.19.0] - 2024-12-05

### Notable Changes

This version drops Python 3.7 and removes the `wandb.Run.plot_table` method.
This version adds pydantic>=2.6,<3 as a dependency.

### Changed

- Set default behavior to not create a W&B Job (@KyleGoyette in https://github.com/wandb/wandb/pull/8907)
- Add pydantic>=2.6,<3 as a dependency (@dmitryduev in https://github.com/wandb/wandb/pull/8649 & estellazx
  in https://github.com/wandb/wandb/pull/8905)

### Removed

- Remove `wandb.Run.plot_table` method. The functionality is still available and should be accessed using `wandb.plot_table`, which is now the recommended way to use this feature. (@kptkin in https://github.com/wandb/wandb/pull/8686)
- Drop support for Python 3.7. (@kptkin in https://github.com/wandb/wandb/pull/8858)

### Fixed

- Fix `ultralytics` reporting if there are no positive examples in a validation batch. (@Jamil in https://github.com/wandb/wandb/pull/8870)
- Debug printing for hyperband stopping algorithm printed one char per line (@temporaer in https://github.com/wandb/wandb/pull/8955)
- Include the missing `log_params` argument when calling lightgbm's `wandb_callback` function. (@i-aki-y https://github.com/wandb/wandb/pull/8943)

## [0.18.7] - 2024-11-13

### Added

- Added `create_and_run_agent` to `__all__` in `wandb/sdk/launch/__init__.py` to expose it as a public API (@marijncv in https://github.com/wandb/wandb/pull/8621)

### Changed

- Tables logged in offline mode now have updated keys to artifact paths when syncing. To revert to old behavior, use setting `allow_offline_artifacts = False`. (@domphan-wandb in https://github.com/wandb/wandb/pull/8792)

### Deprecated

- The `quiet` argument to `wandb.run.finish()` is deprecated, use `wandb.Settings(quiet=...)` to set this instead. (@kptkin in https://github.com/wandb/wandb/pull/8794)

### Fixed

- Fix `api.artifact()` to correctly pass the `enable_tracking` argument to the `Artifact._from_name()` method (@ibindlish in https://github.com/wandb/wandb/pull/8803)

## [0.18.6] - 2024-11-06

### Added

- Add a boolean `overwrite` param to `Artifact.add()`/`Artifact.add_file()` to allow overwrite of previously-added artifact files (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8553)

### Fixed

- Add missing type hints of the `wandb.plot` module in the package stub (@kptkin in https://github.com/wandb/wandb/pull/8667)
- Fix limiting azure reference artifact uploads to `max_objects` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/8703)
- Fix downloading azure reference artifacts with `skip_cache=True` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/8706)
- Fix multipart uploads for files with no content type defined in headers (@amusipatla-wandb in https://github.com/wandb/wandb/pull/8716)
- Fixed tensorboard failing to sync when logging batches of images. (@jacobromero in https://github.com/wandb/wandb/pull/8641)
- Fixed behavior of `mode='x'`/`mode='w'` in `Artifact.new_file()` to conform to Python's built-in file modes (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8553)
- Do not ignore parameter `distribution` when configuring sweep parameters from SDK. (@temporaer in https://github.com/wandb/wandb/pull/8737)

### Changed

- Added internal method, `api._artifact()`, to fetch artifacts so that usage events are not created if not called by an external user. (@ibindlish in https://github.com/wandb/wandb/pull/8674)
- Changed default `mode` in `Artifact.new_file()` from `'w'` to `'x'` to accurately reflect existing default behavior (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8553)

## [0.18.5] - 2024-10-17

### Fixed

- Import `Literal` from `typing_extensions` in Python 3.7; broken in 0.18.4 (@timoffex in https://github.com/wandb/wandb/pull/8656)

## [0.18.4] - 2024-10-17

### Added

- Track detailed metrics for Apple ARM systems including GPU, eCPU, and pCPU utilization, power consumption, and temperature, and memory/swap utilization (@dmitryduev in https://github.com/wandb/wandb/pull/8550)
- Allow users to link Registry artifacts without inputting the organization entity name (@estellazx in https://github.com/wandb/wandb/pull/8482)
- Added a warning message indicating that the `fps` argument will be ignored when creating a wandb.Video object from a file path string or a bytes object. (@jacobromero in https://github.com/wandb/wandb/pull/8585)
- Update docstrings for `logged_artifacts` and `used_artifacts` methods in `Run` class (@trane293 in https://github.com/wandb/wandb/pull/8624)
- The `_show_operation_stats` setting enables a preview of a better `run.finish()` UX (@timoffex in https://github.com/wandb/wandb/pull/8644)

### Fixed

- Log power on AMD MI300X series GPUs (@dmitryduev in https://github.com/wandb/wandb/pull/8630)
- Fixed typing issue of `wandb.Api` (@bdvllrs in https://github.com/wandb/wandb/pull/8548)
- Ensure artifact objects are fully updated on `Artifact.save()` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8575)

### Changed

- Updated minimum version of `sentry-sdk` to 2.0.0 to address deprecation warnings. (@jacobromero in https://github.com/wandb/wandb/compare/WB-20890)

## [0.18.3] - 2024-10-01

### Added

- Add the ability to monitor the utilization metrics of Google's Cloud TPU devices (@dmitryduev in https://github.com/wandb/wandb/pull/8504)

### Fixed

- Capture Nvidia GPU stats on Windows (@dmitryduev in https://github.com/wandb/wandb/pull/8524)
- Fixed a regression introduced in v0.18.2 that affected capturing the names of Nvidia GPU devices (@dmitryduev in https://github.com/wandb/wandb/pull/8503)
- `run.log_artifact()` no longer blocks other data uploads until the artifact upload finishes (@timoffex in https://github.com/wandb/wandb/pull/8466)
- Fixed media dependency for rdkit updated from `rdkit-pypi` to `rdkit` (@jacobromero in https://github.com/wandb/wandb/compare/WB-20894)
- Saving an artifact with many large files no longer exhausts OS threads (@timoffex in https://github.com/wandb/wandb/pull/8518)

### Changed

- After `artifact = run.log_artifact()`, you must use `artifact.wait()` before operations that rely on the artifact having been uploaded. Previously, this wasn't necessary in some cases because `run.log_artifact()` blocked other operations on the run (@timoffex in https://github.com/wandb/wandb/pull/8466)

## [0.18.2] - 2024-09-27

### Added

- Add `upsert_run_queue` method to `wandb.Api`. (@bcsherma in https://github.com/wandb/wandb/pull/8348)
- Add `tags` parameter to `wandb.Api.artifacts()` to filter artifacts by tag. (@moredatarequired in https://github.com/wandb/wandb/pull/8441)

### Fixed

- Update the signature and docstring of `wandb.api.public.runs.Run.log_artifact()` to support artifact tags like `Run` instances returned by `wandb.init()`. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8414)
- Add docstring for `wandb.watch` to support auto-complete (@kptkin in https://github.com/wandb/wandb/pull/8425)
- Fix glob matching in define metric to work with logged keys containing `/` (@KyleGoyette in https://github.com/wandb/wandb/pull/8434)
- Allow `a\.b` syntax in run.define_metric to refer to a dotted metric name (@jacobromero in https://github.com/wandb/wandb/pull/8445)
  - NOTE: Not fixed if using `wandb.require("legacy-service")`
- Fix Unknown image format error when uploading a gif through tensorboard. (@jacobromero in https://github.com/wandb/wandb/pull/8476)
- Fix `OSError` from calling `Artifact.add_file` with file paths on mounted filesystems (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8473)
- Restored compatibility for macOS versions <= 10.15 for wandb-core. (@dmitryduev in https://github.com/wandb/wandb/pull/8487)

## [0.18.1] - 2024-09-16

### Fixed

- Allow all users to read cache files when core is enabled (@moredatarequired in https://github.com/wandb/wandb/pull/8362)
- Infinite scalars logged in TensorBoard are uploaded successfully rather than skipped (@timoffex in https://github.com/wandb/wandb/pull/8380)
- Properly respect `WANDB_ERROR_REPORTING=false`. This fixes a regression introduced in 0.18.0 (@kptkin in https://github.com/wandb/wandb/pull/8379)

### Changed

- Remove sentry logging for sendLinkArtifact (@ibindlish in https://github.com/wandb/wandb/pull/8422)
- Default to capturing requirements.txt in Run.log_code (@KyleGoyette in https://github.com/wandb/wandb/pull/7864)

## [0.18.0] - 2024-09-11

### Notable Changes

This version switches `wandb` to a new backend by enabling `wandb.require("core")` by default. This should not be a breaking change, but the new backend may have unexpected differences in behavior for legacy functionality and rare edge cases.

### Added

- Add support for artifact tags, via `Artifact.tags` and `Run.log_artifact()` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8085)

### Fixed

- Detect the notebook name in VS Code's built-in jupyter server (@dmitryduev in https://github.com/wandb/wandb/pull/8311)

### Changed

- The new "core" backend, previously activated using wandb.require("core"), is now used by default. To revert to the legacy behavior, add `wandb.require("legacy-service")` at the beginning of your script. Note: In a future minor release, the option to disable this new behavior will be removed (@kptkin in https://github.com/wandb/wandb/pull/7777)

## [0.17.9] - 2024-09-05

### Changed

- Changed the default system metrics sampling interval to 10 seconds without averaging, while allowing custom intervals via `wandb.init(settings=wandb.Settings(_stats_sampling_interval=...))` (@dmitryduev in https://github.com/wandb/wandb/pull/8208)

### Deprecated

- `define_metric(summary='best', goal=...)` is deprecated and soon will be removed, use `define_metric(summary='min')` or `define_metric(summary='min')` instead (@kptkin in https://github.com/wandb/wandb/pull/8219)

## [0.17.8] - 2024-08-28

### Added

- Capture SM (Streaming Multiprocessor), memory, and graphics clock speed (MHz), (un)corrected error counts, fan speed (%), and encoder utilization for Nvidia GPU devices when using core (@dmitryduev in https://github.com/wandb/wandb/pull/8144)
- Allow iterating over `wandb.Config` like a dictionary (@fsherry in https://github.com/wandb/wandb/pull/8129)
- PR curves, images and histograms are supported when using TensorBoard with core enabled (@timoffex in https://github.com/wandb/wandb/pull/8181, https://github.com/wandb/wandb/pull/8188, https://github.com/wandb/wandb/pull/8189)
- Added `wandb.require("legacy-service")` as the opt-out analog of `wandb.require("core")` (@timoffex in https://github.com/wandb/wandb/pull/8201)

### Fixed

- Avoid leaving behind wandb-core process if user hits Ctrl+C twice (@timoffex in https://github.com/wandb/wandb/pull/8153)
- Fix deprecation warnings arising from NumPy >= 2.1 by removing `newshape` argument from `numpy.reshape` by @phinate in https://github.com/wandb/wandb/pull/8167
- Skip uploading/downloading GCS reference artifact manifest entries corresponding to folders (@amusipatla-wandb in https://github.com/wandb/wandb/pull/8084)

### Deprecated

- Ability to disable the service process (`WANDB__DISABLE_SERVICE`) is deprecated and will be removed in the next minor release (@kptkin in https://github.com/wandb/wandb/pull/8193)

## [0.17.7] - 2024-08-15

### Fixed

- Ensure Nvidia GPU metrics are captured if `libnvidia-ml.so` is unavailable when using core (@dmitryduev in https://github.com/wandb/wandb/pull/8138)
- Allow `define_metric("x", step_metric="x")` when using core (@timoffex in https://github.com/wandb/wandb/pull/8107)
- Correctly upload empty files when using core (@timoffex in https://github.com/wandb/wandb/pull/8109)
- Fix occasional "send on closed channel" panic when finishing a run using core (@timoffex in https://github.com/wandb/wandb/pull/8140)

## [0.17.6] - 2024-08-08

### Added

- Specify job input schemas when calling manage_config_file or manage_wandb_config to create a nicer UI when launching the job (@TimH98 in https://github.com/wandb/wandb/pull/7907, https://github.com/wandb/wandb/pull/7924, https://github.com/wandb/wandb/pull/7971)
- Use the filesystem rather than protobuf messages to transport manifests with more than 100k entries to the core process (@moredatarequired in https://github.com/wandb/wandb/pull/7992)
- Adds the `box3d` constructor for `Box3D` (@timoffex in https://github.com/wandb/wandb/pull/8086)

### Changed

- `run.define_metric()` raises an error when given extraneous arguments (@timoffex in https://github.com/wandb/wandb/pull/8040)
- In disabled mode, use the `wandb.sdk.wandb_run.Run` class instead of `wandb.sdk.wandb_run.RunDisabled`, which has been removed (@dmitryduev in https://github.com/wandb/wandb/pull/8037)
- When `WANDB_MODE = offline` calling `artifact.download()` now throws an error instead of stalling (@trane293 in https://github.com/wandb/wandb/pull/8009)

### Fixed

- Correctly handle directory stubs when logging external artifact in azure storage account with Hierarchical Namespace enabled (@marijncv in https://github.com/wandb/wandb/pull/7876)
- Docstring in `api.runs()` regarding default sort order, missed in https://github.com/wandb/wandb/pull/7675 (@fellhorn in https://github.com/wandb/wandb/pull/8063)

## [0.17.5] - 2024-07-19

### Added

- When using wandb-core, support multipart uploads to S3 (@moredatarequired in https://github.com/wandb/wandb/pull/7659)

### Changed

- `run.finish()` may raise an exception in cases where previously it would `os._exit()` (@timoffex in https://github.com/wandb/wandb/pull/7921)
- `run.link_artifact()` can now surface server errors. (@ibindlish in https://github.com/wandb/wandb/pull/6941)

### Fixed

- Handle `path_prefix`es that don't correspond to directory names when downloading artifacts (@moredatarequired in https://github.com/wandb/wandb/pull/7721)
- Fix creating or updating an artifact with the `incremental=True` flag (@amusipatla-wandb in https://github.com/wandb/wandb/pull/7939)
- Use filled resource_arg macros when submitting W&B Launch jobs to AmazonSageMaker (@KyleGoyette in https://github.com/wandb/wandb/pull/7993)

## [0.17.4] - 2024-07-03

### Added

- Support queue template variables in launch sweep scheduler jobs (@KyleGoyette in https://github.com/wandb/wandb/pull/7787)

### Fixed

- Use `sys.exit()` instead of `os._exit()` if an internal subprocess exits with a non-zero code (@timoffex in https://github.com/wandb/wandb/pull/7866)
- Fix an occasional race condition when using `core` that could affect run logs (@timoffex in https://github.com/wandb/wandb/pull/7889)
- Fix OSError on `Artifact.download(skip_cache=True)` when encountering different filesystems (@tonyyli-wandb in https://github.com/wandb/wandb/pull/7835)

## [0.17.3] - 2024-06-24

### Fixed

- Correctly name the netrc file on Windows as `_netrc` (@dmitryduev in https://github.com/wandb/wandb/pull/7844)
- With core enabled, nested `tqdm` bars show up correctly in the Logs tab (@timoffex in https://github.com/wandb/wandb/pull/7825)
- Fix W&B Launch registry ECR regex separating tag on forward slash and period (@KyleGoyette in https://github.com/wandb/wandb/pull/7837)

## [0.17.2] - 2024-06-17

### Added

- Add prior runs when creating a sweep from the CLI by @TimH98 in https://github.com/wandb/wandb/pull/7803

### Fixed

- Fix issues with `numpy>=2` support by @dmitryduev in https://github.com/wandb/wandb/pull/7816
- Fix "UnicodeDecodeError: 'charmap'" when opening HTML files on Windows by specifying UTF-8 encoding by @KilnOfTheSecondFlame in https://github.com/wandb/wandb/pull/7730
- Ensure `Artifact.delete()` on linked artifacts only removes link, not source artifact by @tonyyli-wandb in https://github.com/wandb/wandb/pull/7742
- Sweep runs no longer appear to be resumed when they are not by @TimH98 https://github.com/wandb/wandb/pull/7684

### Changed

- Upgrade github.com/vektah/gqlparser/v2 from 2.5.11 to 2.5.16 by @wandb-kc in https://github.com/wandb/wandb/pull/7828

## [0.17.1] - 2024-06-07

### Added

- Added `api.runs().histories()` to fetch history metrics for runs that meet specified conditions by @thanos-wandb in https://github.com/wandb/wandb/pull/7690
- Display warning when Kubernetes pod fails to schedule by @TimH98 in https://github.com/wandb/wandb/pull/7576
- Added `ArtifactCollection.save()` to allow persisting changes by @amusipatla-wandb in https://github.com/wandb/wandb/pull/7555
- Added the ability to overwrite history of previous runs at an arbitrary step and continue logging from that step by @dannygoldstein in https://github.com/wandb/wandb/pull/7711
- Added new Workspace API for programatically editing W&B Workspaces by @andrewtruong in https://github.com/wandb/wandb/pull/7728
- Added `Artifact.unlink()` to allow programmatic unlinking of artifacts by @tonyyli-wandb in https://github.com/wandb/wandb/pull/7735
- Added basic TensorBoard support when running with `wandb.require("core")` by @timoffex in https://github.com/wandb/wandb/pull/7725
  - The TensorBoard tab in W&B will work.
  - Charts show up in W&B, possibly better than when running without core.
  - Not all types of data are supported yet. Unsupported data is not shown in charts.

### Fixed

- Fix `define_metric` behavior for multiple metrics in `shared` mode by @dmitryduev in https://github.com/wandb/wandb/pull/7715
- Correctly pass in project name to internal api from run while calling run.use_artifact() by @ibindlish in https://github.com/wandb/wandb/pull/7701
- Correctly upload console output log files when resuming runs enabled with `console_multipart` setting by @kptkin in https://github.com/wandb/wandb/pull/7694 and @dmitryduev in https://github.com/wandb/wandb/pull/7697
- Interpret non-octal strings with leading zeros as strings and not integers in sweep configs by @KyleGoyette https://github.com/wandb/wandb/pull/7649
- Support Azure repo URI format in Launch @KyleGoyette https://github.com/wandb/wandb/pull/7664
- Fix path parsing for artifacts with aliases containing forward slashes by @amusipatla-wandb in https://github.com/wandb/wandb/pull/7676
- Add missing docstrings for any public methods in `Api` class by @tonyyli-wandb in https://github.com/wandb/wandb/pull/7713
- Correctly add latest alias to jobs built by the job builder @KyleGoyette https://github.com/wandb/wandb/pull/7727

### Changed

- Option to change naming scheme for console output logs from `output.log` to `logs/YYYYMMDD_HHmmss.ms_output.log` by @kptkin in https://github.com/wandb/wandb/pull/7694
- Require `unsafe=True` in `use_model` calls that could potentially load and deserialize unsafe pickle files by @anandwandb https://github.com/wandb/wandb/pull/7663
- Update order in api.runs() to ascending to prevent duplicate responses by @thanos-wandb https://github.com/wandb/wandb/pull/7675
- Eliminate signed URL timeout errors during artifact file uploads in core by @moredatarequired in https://github.com/wandb/wandb/pull/7586

### Deprecated

- Deprecated `ArtifactCollection.change_type()` in favor of `ArtifactCollection.save()` by @amusipatla-wandb in https://github.com/wandb/wandb/pull/7555

## [0.17.0] - 2024-05-07

### Notable Changes

Renamed `wandb.plots` to `wandb.plot`, renamed all integrations from `wandb.<name>` to `wandb.integration.<name>`, and removed the `[async]` extra.

This version packages the `wandb-core` binary, formerly installed by the `wandb-core` Python package on PyPI. The `wandb-core` package is now unused and can be uninstalled.

### Added

- The `wandb` package now includes the `wandb-core` binary by @timoffex in https://github.com/wandb/wandb/pull/7381
  - `wandb-core` is a new and improved backend for the W&B SDK that focuses on performance, versatility, and robustness.
  - Currently, it is opt-in. To start using the new backend, add `wandb.require("core")` to your script after importing `wandb`.
- `wandb-core` now supports Artifact file caching by @moredatarequired in https://github.com/wandb/wandb/pull/7364 and https://github.com/wandb/wandb/pull/7366
- Added artifact_exists() and artifact_collection_exists() methods to Api to check if an artifact or collection exists by @amusipatla-wandb in https://github.com/wandb/wandb/pull/7483
- `wandb launch -u <git-uri | local-path> ` creates and launches a job from the given source code by @bcsherma in https://github.com/wandb/wandb/pull/7485

### Fixed

- Prevent crash on `run.summary` for finished runs by @dmitryduev in https://github.com/wandb/wandb/pull/7440
- Correctly report file upload errors when using wandb-core by @moredatarequired in https://github.com/wandb/wandb/pull/7196
- Implemented a stricter check for AMD GPU availability by @dmitryduev in https://github.com/wandb/wandb/pull/7322
- Fixed `run.save()` on Windows by @timoffex in https://github.com/wandb/wandb/pull/7412
- Show a warning instead of failing when using registries other than ECR and GAR with the Kaniko builder by @TimH98 in https://github.com/wandb/wandb/pull/7461
- Fixed `wandb.init()` type signature including `None` by @timoffex in https://github.com/wandb/wandb/pull/7563

### Changed

- When using `wandb-core` need to specify a required flag (`wandb.require("core")`) to enable it, before it was picked up automatically by @kptkin in https://github.com/wandb/wandb/pull/7228
- Use ETags instead of MD5 hashes for GCS reference artifacts by @moredatarequired in https://github.com/wandb/wandb/pull/7337

### Removed

- Removed the deprecated `wandb.plots.*` functions and top-level third-party integrations `wandb.[catboost,fastai,keras,lightgbm,sacred,xgboost]`. Please use `wandb.plot` instead of `wandb.plots` and `wandb.integration.[catboost,fastai,keras,lightgbm,sacred,xgboost]` instead of `wandb.[catboost,fastai,keras,lightgbm,sacred,xgboost]`. By @dmitryduev in https://github.com/wandb/wandb/pull/7552
- Removed the `[async]` extra and the `_async_upload_concurrency_limit` setting by @moredatarequired in https://github.com/wandb/wandb/pull/7416
- Removed undocumented settings: `_except_exit` and `problem` by @timoffex in https://github.com/wandb/wandb/pull/7563

## [0.16.6] - 2024-04-03

### Added

- Added support for overriding kaniko builder settings in the agent config by @TimH98 in https://github.com/wandb/wandb/pull/7191
- Added link to the project workspace of a run in the footer by @kptkin in https://github.com/wandb/wandb/pull/7276
- Added support for overriding stopped run grace period in the agent config by @TimH98 in https://github.com/wandb/wandb/pull/7281
- Added setting (`_disable_update_check`) to disable version checks during init by @kptkin in https://github.com/wandb/wandb/pull/7287
- `WandbLogger.sync` in the OpenAI Fine-Tuning integration gets a new `log_datasets` boolean argument to turn off automatic logging of datasets to Artifacts by @morganmcg1 in https://github.com/wandb/wandb/pull/7150
- Reduced default status print frequency of launch agent. Added verbosity controls to allow for increased status print frequency and printing debug information to stdout by @TimH98 in https://github.com/wandb/wandb/pull/7126

### Changed

- Limit policy option on artifact cli's put() to choices, ["mutable", "immutable"] by @ibindish in https://github.com/wandb/wandb/pull/7172
- Updated artifact public api methods to handle nullable Project field on the ArtifactSequence/ArtifactCollection type, based on gorilla server changes by @ibindlish in https://github.com/wandb/wandb/pull/7201

### Fixed

- Fixed `run.save()` not working with files inside `run.dir`, introduced in previous release
- Fixed rare panic during large artifact uploads by @moredatarequire in https://github.com/wandb/wandb/pull/7272
- Fixed wandb.login causing runs not to be associated with launch queue by @KyleGoyette in https://github.com/wandb/wandb/pull/7280
- Fixed job artifact download failing silently and causing run crash when using W&B Launch by @KyleGoyette https://github.com/wandb/wandb/pull/7285
- Fix handling of saving training files to Artifacts in the OpenAI Fine-Tuning integration by @morganmcg1 in https://github.com/wandb/wandb/pull/7150

## [0.16.5] - 2024-03-25

### Added

- Added feature to move staging files to cache (instead of copying) for mutable artifact file uploads when caching is enabled by @ibindlish in https://github.com/wandb/wandb/pull/7143
- Added support to skip caching files to the local filesystem while uploading files to artifacts by @ibindlish in https://github.com/wandb/wandb/pull/7098
- Added support to skip staging artifact files during upload by selecting a storage policy by @ibindlish in https://github.com/wandb/wandb/pull/7142
- Preliminary support for forking a run using `wandb.init(fork_from=...)` by @dannygoldstein in https://github.com/wandb/wandb/pull/7078
- `run.save()` accepts `pathlib.Path` values; by @timoffex in https://github.com/wandb/wandb/pull/7146

### Changed

- When printing the run link point to the workspace explicitly by @kptkin in https://github.com/wandb/wandb/pull/7132

### Fixed

- In case of transient server issues when creating the wandb API key kubernetes secret, we'll retry up to 5 times by @TimH98 in https://github.com/wandb/wandb/pull/7108

### Removed

- When printing run's information in the terminal remove links to jobs by @kptkin in https://github.com/wandb/wandb/pull/7132

## [0.16.4] - 2024-03-05

### Added

- Added ability to change artifact collection types by @biaslucas in https://github.com/wandb/wandb/pull/6971
- Add support for installing deps from pyproject.toml by @bcsherma in https://github.com/wandb/wandb/pull/6964
- Support kaniko build with user-provided pvc and docker config by @bcsherma in https://github.com/wandb/wandb/pull/7059
- Added ability to import runs between W&B instances by @andrewtruong in https://github.com/wandb/wandb/pull/6897

### Changed

- wandb-core rate-limits requests to the backend and respects RateLimit-\* headers
  by @timoffex in https://github.com/wandb/wandb/pull/7065

### Fixed

- Fix passing of template variables in the sweeps-on-launch scheduler by @dannygoldstein in https://github.com/wandb/wandb/pull/6959
- Link job artifact to a run to be specified as input by @kptkin in https://github.com/wandb/wandb/pull/6940
- Fix sagemaker entrypoint to use given entrypoint by @KyleGoyette in https://github.com/wandb/wandb/pull/6969
- Parse upload headers correctly by @kptkin in https://github.com/wandb/wandb/pull/6983
- Properly propagate server errors by @kptkin in https://github.com/wandb/wandb/pull/6944
- Make file upload faster by using parallelism by @kptkin in https://github.com/wandb/wandb/pull/6975
- Don't send git data if it's not populated by @kptkin in https://github.com/wandb/wandb/pull/6984
- Fix console logging resumption, avoid overwrite by @kptkin in https://github.com/wandb/wandb/pull/6963
- Remove hostname validation when using --host on wandb login by @Jamil in https://github.com/wandb/wandb/pull/6999
- Don't discard past visualizations when resuming a run by @timoffex in https://github.com/wandb/wandb/pull/7005
- Avoid retrying on conflict status code by @kptkin in https://github.com/wandb/wandb/pull/7011
- Fix visualization config merging for resumed runs in wandb-core by @timoffex in https://github.com/wandb/wandb/pull/7012
- Replace usage of standard library's json with `segmentio`'s by @kptkin in https://github.com/wandb/wandb/pull/7027
- Remove stderr as writer for the logs by @kptkin in https://github.com/wandb/wandb/pull/7022
- Disable negative steps from initialization by @kptkin in https://github.com/wandb/wandb/pull/7030
- Fix report loading in pydantic26 by @andrewtruong in https://github.com/wandb/wandb/pull/6988
- Revert "make upload request async to support progress reporting (#6497)" by @jlzhao27 in https://github.com/wandb/wandb/pull/7049
- Fix entrypoint specification when using a Dockerfile.wandb by @KyleGoyette in https://github.com/wandb/wandb/pull/7080
- Fix stream releasing probe handle too early by @jlzhao27 in https://github.com/wandb/wandb/pull/7056
- Always attempt to pull latest image for local container by @KyleGoyette in https://github.com/wandb/wandb/pull/7079

### New Contributors

- @Jamil made their first contribution in https://github.com/wandb/wandb/pull/6999

# 0.16.3 (Feb 6, 2024)

### :magic_wand: Enhancements

- feat(core): generate data type info in core by @dmitryduev in https://github.com/wandb/wandb/pull/6827
- feat(core): add support for Launch 🚀 by @kptkin in https://github.com/wandb/wandb/pull/6822
- feat(public-api): Added option to control number of grouped sampled runs in reports by @thanos-wandb in https://github.com/wandb/wandb/pull/6840
- feat(sdk): add shared mode to enable multiple independent writers to the same run by @dmitryduev in https://github.com/wandb/wandb/pull/6882
- perf(artifacts): Reduce artifact download latency via optional cache copy + threads by @biaslucas in https://github.com/wandb/wandb/pull/6878
- feat(artifacts): Add partial file downloads, via directory prefix by @biaslucas in https://github.com/wandb/wandb/pull/6911
- feat(integrations): Update the Diffusers Integration by @soumik12345 in https://github.com/wandb/wandb/pull/6804
- feat(integrations): Update Ultralytics Integration by @soumik12345 in https://github.com/wandb/wandb/pull/6796
- feat(integrations): Add Pytorch Lightning Fabric Logger by @ash0ts in https://github.com/wandb/wandb/pull/6919
- feat(core): update go packages by @kptkin in https://github.com/wandb/wandb/pull/6908

### :hammer: Fixes

- fix(launch): Remove project and runner fields from agent config by @KyleGoyette in https://github.com/wandb/wandb/pull/6818
- fix(launch): recognize deleted k8s jobs as failed by @bcsherma in https://github.com/wandb/wandb/pull/6824
- fix(launch): warn of extra fields in environment block instead of erroring by @bcsherma in https://github.com/wandb/wandb/pull/6833
- fix(sdk): entity override bug where ENVVAR is prioritized over kwargs by @biaslucas in https://github.com/wandb/wandb/pull/6843
- fix(launch): Local container runner doesn't ignore override args by @TimH98 in https://github.com/wandb/wandb/pull/6844
- fix(sdk): merge-update config with sweep/launch config by @dannygoldstein in https://github.com/wandb/wandb/pull/6841
- fix(sdk): fix retry logic in wandb-core and system_tests conftest by @dmitryduev in https://github.com/wandb/wandb/pull/6847
- fix(core): use RW locks in system monitor's assets management by @dmitryduev in https://github.com/wandb/wandb/pull/6852
- fix(launch): set build context to entrypoint dir if it contains Dockerfile.wandb by @bcsherma in https://github.com/wandb/wandb/pull/6855
- security(launch): Mount wandb api key in launch job pods from a k8s secret by @TimH98 in https://github.com/wandb/wandb/pull/6722
- fix(launch): wandb job create should not look for requirements.txt if Dockerfile.wandb is next to entrypoint by @bcsherma in https://github.com/wandb/wandb/pull/6861
- fix(sdk): fix \_parse_path when only id is passed to wandb.Api().run() by @luisbergua in https://github.com/wandb/wandb/pull/6858
- fix(media): Update video.py: Fix fps bug by @stellargo in https://github.com/wandb/wandb/pull/6887
- fix(sdk): clean up temp folders by @dmitryduev in https://github.com/wandb/wandb/pull/6891
- fix(artifacts): fix long artifact paths on Windows by @ArtsiomWB in https://github.com/wandb/wandb/pull/6846
- fix(sdk): Update Report API to work with pydantic2.6 by @andrewtruong in https://github.com/wandb/wandb/pull/6925
- fix(launch): fetch all commits to enable checking out by sha by @bcsherma in https://github.com/wandb/wandb/pull/6926
- fix(sweeps): dont swallow exceptions in pyagent by @dannygoldstein in https://github.com/wandb/wandb/pull/6927
- fix(artifacts): artifact file upload progress in nexus by @ibindlish in https://github.com/wandb/wandb/pull/6939
- fix(sdk): exercise caution in system monitor when rocm-smi is installed on a system with no amd gpus by @dmitryduev in https://github.com/wandb/wandb/pull/6938
- fix(cli): typo in cli.py by @eltociear in https://github.com/wandb/wandb/pull/6892
- fix(launch): remove deadsnakes from accelerator build step by @bcsherma in https://github.com/wandb/wandb/pull/6933

### :books: Docs

- docs(sdk): update sweep `docstrings` by @ngrayluna in https://github.com/wandb/wandb/pull/6830
- docs(sdk): Updates the Tables reference docs. by @katjacksonWB in https://github.com/wandb/wandb/pull/6880
- docs(sdk): Artifact docstrings PR by @ngrayluna in https://github.com/wandb/wandb/pull/6825

## New Contributors

- @biaslucas made their first contribution in https://github.com/wandb/wandb/pull/6843
- @stellargo made their first contribution in https://github.com/wandb/wandb/pull/6887
- @timoffex made their first contribution in https://github.com/wandb/wandb/pull/6916

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.16.2...v0.16.3

# 0.16.2 (Jan 9, 2024)

### :magic_wand: Enhancements

- feat(nexus): refactor store logic and add store writer by @kptkin in https://github.com/wandb/wandb/pull/6678
- feat(nexus): add AMD GPU monitoring by @dmitryduev in https://github.com/wandb/wandb/pull/6606
- feat(nexus): add console log file upload by @kptkin in https://github.com/wandb/wandb/pull/6669
- feat(launch): add registry uri field to builders by @bcsherma in https://github.com/wandb/wandb/pull/6626
- feat(core): add `wandb beta sync` feature to upload runs to W&B by @kptkin in https://github.com/wandb/wandb/pull/6620
- feat(launch): CLI supports allow-listed queue parameters by @TimH98 in https://github.com/wandb/wandb/pull/6679
- feat(core): add support for requirements and patch.diff by @kptkin in https://github.com/wandb/wandb/pull/6721
- feat(core): capture SLURM-related env vars in metadata by @dmitryduev in https://github.com/wandb/wandb/pull/6710
- feat(launch): --priority flag on `wandb launch` command to specify priority when enqueuing jobs. by @nickpenaranda in https://github.com/wandb/wandb/pull/6705
- feat(sdk): add verify feature to wandb login by @dmitryduev in https://github.com/wandb/wandb/pull/6747
- feat(launch): Sweeps on Launch honors selected job priority for sweep runs by @nickpenaranda in https://github.com/wandb/wandb/pull/6756
- feat(core): 🦀 commence operation SDKrab 🦀 by @dmitryduev in https://github.com/wandb/wandb/pull/6000
- feat(artifacts): make upload request async to support progress reporting by @jlzhao27 in https://github.com/wandb/wandb/pull/6497
- feat(core): add TensorBoard log dir watcher by @kptkin in https://github.com/wandb/wandb/pull/6769
- feat(core): upload wandb-summary.json and config.yaml files by @kptkin in https://github.com/wandb/wandb/pull/6781

### :hammer: Fixes

- fix(nexus): update error message and remove extra by @kptkin in https://github.com/wandb/wandb/pull/6667
- fix(nexus): clean up issues with file sending by @kptkin in https://github.com/wandb/wandb/pull/6677
- fix(core): add jitter to retry clients' backoff strategy by @dmitryduev in https://github.com/wandb/wandb/pull/6706
- fix(artifacts): only skip file download if digest matches by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6694
- fix(core): fix resume and add tests by @dmitryduev in https://github.com/wandb/wandb/pull/6714
- fix(launch): capture errors from the creation of k8s job from yaml by @bcsherma in https://github.com/wandb/wandb/pull/6730
- fix(launch): Get default entity before checking template vars by @TimH98 in https://github.com/wandb/wandb/pull/6745
- fix(artifacts): remove run creation for artifact downloads if not using core by @ibindlish in https://github.com/wandb/wandb/pull/6746
- fix(artifacts): Retrieve ETag for ObjectVersion instead of Object for versioned buckets by @ibindlish in https://github.com/wandb/wandb/pull/6759
- fix(artifacts): revert #6759 and read object version etag in place by @ibindlish in https://github.com/wandb/wandb/pull/6774
- fix(core): put back the upload file count by @kptkin in https://github.com/wandb/wandb/pull/6767
- fix(core): add send cancel request to sender by @dmitryduev in https://github.com/wandb/wandb/pull/6787
- fix(core): check errors in memory monitoring by @dmitryduev in https://github.com/wandb/wandb/pull/6790
- fix(sdk): add job_type flag in CLI to allow override of job_type by @umakrishnaswamy in https://github.com/wandb/wandb/pull/6523
- fix(integrations): Handle ultralytics utils import refactor by @jthetzel in https://github.com/wandb/wandb/pull/6741
- fix(core): download artifacts with wandb-core without an active run by @dmitryduev in https://github.com/wandb/wandb/pull/6798
- fix(sdk): fix error logging matplotlib scatter plot if the minimum version of plotly library is not met by @walkingmug in https://github.com/wandb/wandb/pull/6724
- fix(sdk): allow overriding the default .netrc location with NETRC env var by @dmitryduev in https://github.com/wandb/wandb/pull/6708

### :books: Docs

- docs(sdk): Corrected description for email field by @ngrayluna in https://github.com/wandb/wandb/pull/6716
- docs(core): update the `README-libwandb-cpp.md` doc by @NinoRisteski in https://github.com/wandb/wandb/pull/6794

## New Contributors

- @jthetzel made their first contribution in https://github.com/wandb/wandb/pull/6741
- @walkingmug made their first contribution in https://github.com/wandb/wandb/pull/6724

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.16.1...v0.16.2

# 0.16.1 (Dec 5, 2023)

### :magic_wand: Enhancements

- perf(artifacts): remove recursive download by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6544
- feat(nexus): add debounce summary in handler by @kptkin in https://github.com/wandb/wandb/pull/6570
- feat(integrations): fix bug in ultralytics import and version pinning by @soumik12345 in https://github.com/wandb/wandb/pull/6605
- feat(launch): Support template variables when queueing launch runs by @KyleGoyette in https://github.com/wandb/wandb/pull/6602
- feat(cli): add --skip-console option to offline sync cli command by @kptkin in https://github.com/wandb/wandb/pull/6557
- feat(nexus): add basic graphql versioning mechanism by @dmitryduev in https://github.com/wandb/wandb/pull/6624
- feat(nexus): add Apple M\* GPU stats monitoring by @dmitryduev in https://github.com/wandb/wandb/pull/6619
- feat(launch): add helper to load wandb.Config from env vars by @bcsherma in https://github.com/wandb/wandb/pull/6644
- feat(integrations): port OpenAI WandbLogger for openai-python v1.0 by @ayulockin in https://github.com/wandb/wandb/pull/6498
- feat(integrations): fix version check for openAI WandbLogger by @ayulockin in https://github.com/wandb/wandb/pull/6648
- feat(integrations): Diffusers autologger by @soumik12345 in https://github.com/wandb/wandb/pull/6561
- feat(sdk): Adding parameter to image to specify file type jpg, png, bmp, gif by @fdsig in https://github.com/wandb/wandb/pull/6280

### :hammer: Fixes

- fix(nexus): make offline sync work properly by @dmitryduev in https://github.com/wandb/wandb/pull/6569
- fix(launch): Fix run existence check to not depend on files being uploaded in the run by @KyleGoyette in https://github.com/wandb/wandb/pull/6548
- fix(launch): gcp storage uri verifaction failed due to improper async wrapping by @bcsherma in https://github.com/wandb/wandb/pull/6581
- fix(sdk): updating summary with nested dicts now doesn't throw an error by @ArtsiomWB in https://github.com/wandb/wandb/pull/6578
- fix(launch): Add prioritization mode to RunQueue create by @TimH98 in https://github.com/wandb/wandb/pull/6610
- fix(nexus): create symlink to the server logs in the runs folder by @kptkin in https://github.com/wandb/wandb/pull/6628
- fix(integrations): single value problem in wandb/wandb_torch.py::log_tensor_stats by @gmongaras in https://github.com/wandb/wandb/pull/6640
- fix(integrations): tmin vs tmax in wandb/wandb_torch.py::log_tensor_stats by @dmitryduev in https://github.com/wandb/wandb/pull/6641
- fix(nexus): minor fix up for non server cases by @kptkin in https://github.com/wandb/wandb/pull/6645
- fix(sdk): make old settings more robust by @dmitryduev in https://github.com/wandb/wandb/pull/6654
- fix(sdk): handle tags when resuming a run by @dmitryduev in https://github.com/wandb/wandb/pull/6660

### :books: Docs

- docs(integrations): fix doc-string typo in a keras callback by @evilpegasus in https://github.com/wandb/wandb/pull/6586

## New Contributors

- @evilpegasus made their first contribution in https://github.com/wandb/wandb/pull/6586
- @yogeshg made their first contribution in https://github.com/wandb/wandb/pull/6573
- @gmongaras made their first contribution in https://github.com/wandb/wandb/pull/6640

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.16.0...v0.16.1

# 0.16.0 (Nov 7, 2023)

### :magic_wand: Enhancements

- feat(nexus): add nested config support by @kptkin in https://github.com/wandb/wandb/pull/6417
- feat(nexus): finish artifact saver by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6296
- feat(nexus): add sync file counts in the footer by @dmitryduev in https://github.com/wandb/wandb/pull/6371
- feat(nexus): implement directory watcher and related functionality by @kptkin in https://github.com/wandb/wandb/pull/6257
- feat(launch): run agent on an event loop by @bcsherma in https://github.com/wandb/wandb/pull/6384
- feat(nexus): add sampled history by @kptkin in https://github.com/wandb/wandb/pull/6492
- feat(artifacts): prototype for models api by @ibindlish in https://github.com/wandb/wandb/pull/6205
- perf(launch): register sweep scheduler virtual agents async by @bcsherma in https://github.com/wandb/wandb/pull/6488
- feat(nexus): make file uploads work with local by @dmitryduev in https://github.com/wandb/wandb/pull/6509
- feat(sdk): allow users to log custom chart tables in a different section by @luisbergua in https://github.com/wandb/wandb/pull/6422
- feat(nexus): generalize uploader to filemanager to allow downloads by @ibindlish in https://github.com/wandb/wandb/pull/6445
- feat(sdk): drop python 3.6 support by @dmitryduev in https://github.com/wandb/wandb/pull/6493
- feat(artifacts): delete staging files in Nexus by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6529
- feat(artifacts): set up artifact downloads to use sdk nexus core by @estellazx in https://github.com/wandb/wandb/pull/6275
- feat(nexus): add file upload progress and make completion callback a list of callbacks by @kptkin in https://github.com/wandb/wandb/pull/6518
- feat(launch): add wandb.ai/run-id label to jobs by @bcsherma in https://github.com/wandb/wandb/pull/6543

### :hammer: Fixes

- fix(sdk): ensures that complete run.config is captured in SageMaker by @fdsig in https://github.com/wandb/wandb/pull/6260
- fix(sdk): Improve error handling for gitlib for FileNotFoundErrors by @j316chuck in https://github.com/wandb/wandb/pull/6410
- fix(sdk): increase max message size, handle errors by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6398
- fix(launch): Agent better balances multiple queues by @TimH98 in https://github.com/wandb/wandb/pull/6418
- fix(artifacts): remove versioning enabled check in GCS reference handler by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6430
- fix(launch): add google-cloud-aiplatform to launch shard by @bcsherma in https://github.com/wandb/wandb/pull/6440
- fix(nexus): add use_artifact as passthrough messages by @kptkin in https://github.com/wandb/wandb/pull/6447
- fix(launch): adjust vertex environment variables by @Hojland in https://github.com/wandb/wandb/pull/6443
- fix(artifacts): update artifacts cache file permissions for NamedTemporaryFile by @ibindlish in https://github.com/wandb/wandb/pull/6437
- fix(nexus): fix a number of issues by @dmitryduev in https://github.com/wandb/wandb/pull/6491
- fix(media): saving mlp figure to buffer and reading with PIL should specify format by @mova in https://github.com/wandb/wandb/pull/6465
- fix(nexus): send content-length, check response status code in uploader by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6401
- fix(sdk): fix step logic when resuming runs with no metrics logged by @luisbergua in https://github.com/wandb/wandb/pull/6480
- fix(sdk): hook_handle being set to list instead of dict on unhook by @vatsalaggarwal in https://github.com/wandb/wandb/pull/6503
- fix(launch): verify gcp credentials before creating vertex job by @bcsherma in https://github.com/wandb/wandb/pull/6537
- fix(launch): add load option to docker buildx by @KyleGoyette in https://github.com/wandb/wandb/pull/6508
- fix(artifacts): fix perf regressions in artifact downloads and fix file download location by @ibindlish in https://github.com/wandb/wandb/pull/6535
- fix(sdk): add warning when `log_code` can't locate any files by @umakrishnaswamy in https://github.com/wandb/wandb/pull/6532
- fix(sdk): adjust ipython hooks for v8.17 by @dmitryduev in https://github.com/wandb/wandb/pull/6563

### :books: Docs

- docs(media): fix `Graph` docstring by @harupy in https://github.com/wandb/wandb/pull/6458
- docs(public-api): Fix suggested command for uploading artifacts by @geke-mir in https://github.com/wandb/wandb/pull/6513

## New Contributors

- @j316chuck made their first contribution in https://github.com/wandb/wandb/pull/6410
- @harupy made their first contribution in https://github.com/wandb/wandb/pull/6458
- @Hojland made their first contribution in https://github.com/wandb/wandb/pull/6443
- @mova made their first contribution in https://github.com/wandb/wandb/pull/6465
- @geke-mir made their first contribution in https://github.com/wandb/wandb/pull/6513
- @luisbergua made their first contribution in https://github.com/wandb/wandb/pull/6422
- @vatsalaggarwal made their first contribution in https://github.com/wandb/wandb/pull/6503

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.12...v0.16.0

# 0.15.12 (Oct 3, 2023)

### :magic_wand: Enhancements

- feat(nexus): implement config debouncing mechanism by @kptkin in https://github.com/wandb/wandb/pull/6331
- feat(integrations): fix channel swapping on ultrlytics classification task by @soumik12345 in https://github.com/wandb/wandb/pull/6382
- feat(nexus): implement nexus alpha cpp interface by @raubitsj in https://github.com/wandb/wandb/pull/6358
- feat(nexus): expose system metrics in the run object (PoC) by @dmitryduev in https://github.com/wandb/wandb/pull/6238
- feat(integrations): Pin ultralytics version support to `v8.0.186` by @soumik12345 in https://github.com/wandb/wandb/pull/6391

### :hammer: Fixes

- fix(launch): get logs from failed k8s pods by @bcsherma in https://github.com/wandb/wandb/pull/6339
- fix(artifacts): Allow adding s3 bucket as reference artifact by @ibindlish in https://github.com/wandb/wandb/pull/6346
- fix(launch): Fix race condition in agent thread clean up by @KyleGoyette in https://github.com/wandb/wandb/pull/6352
- fix(artifacts): don't assume run and its i/o artifacts are in the same project by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6363
- fix(artifacts): fix wandb.Api().run(run_name).log_artifact(artifact) by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6362
- fix(sweeps): ValueError with None value in sweep by @gtarpenning in https://github.com/wandb/wandb/pull/6364
- fix(artifacts): fix typo in s3 handler by @ibindlish in https://github.com/wandb/wandb/pull/6368
- fix(artifacts): fix the argument order for new argument target_fraction by @moredatarequired in https://github.com/wandb/wandb/pull/6377
- fix(nexus): fix potential race in config debouncer by @dmitryduev in https://github.com/wandb/wandb/pull/6385
- fix(sdk): fix graphql type mapping by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6396
- fix(sdk): fix concurrency limit in uploader by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/6399

### :books: Docs

- docs(sdk): fix reference docs GH action by @dmitryduev in https://github.com/wandb/wandb/pull/6350
- docs(sdk): Update generate-docodile-documentation.yml by @ngrayluna in https://github.com/wandb/wandb/pull/6351

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.11...v0.15.12

# 0.15.11 (Sep 21, 2023)

### :magic_wand: Enhancements

- feat(nexus): add support for code saving in script mode by @kptkin in https://github.com/wandb/wandb/pull/6243
- feat(nexus): add support for `policy=end` in `wandb.save` by @kptkin in https://github.com/wandb/wandb/pull/6267
- feat(nexus): add system info to metadata by @dmitryduev in https://github.com/wandb/wandb/pull/6244
- feat(nexus): add nvidia gpu system info to metadata by @dmitryduev in https://github.com/wandb/wandb/pull/6270
- feat(launch): delete run queues with public api by @bcsherma in https://github.com/wandb/wandb/pull/6317
- feat(sdk): introduce custom proxy support for wandb http(s) traffic by @kptkin in https://github.com/wandb/wandb/pull/6300

### :hammer: Fixes

- fix(sdk): Fix logger when logging filestream exception by @KyleGoyette in https://github.com/wandb/wandb/pull/6246
- fix(launch): use watch api to monitor launched CRDs by @bcsherma in https://github.com/wandb/wandb/pull/6226
- fix(launch): forbid enqueuing docker images without target project by @bcsherma in https://github.com/wandb/wandb/pull/6248
- fix(sdk): add missing Twitter import for API users by @fdsig in https://github.com/wandb/wandb/pull/6261
- fix(artifacts): get S3 versionIDs from directory references by @moredatarequired in https://github.com/wandb/wandb/pull/6255
- fix(launch): make watch streams recover from connection reset by @bcsherma in https://github.com/wandb/wandb/pull/6272
- fix(public-api): use json.loads(..., strict=False) to ignore invalid utf-8 and control characters in api.Run.load by @dmitryduev in https://github.com/wandb/wandb/pull/6299
- fix(sdk): correctly identify colab as a jupyter-like env in settings by @dmitryduev in https://github.com/wandb/wandb/pull/6308
- fix(sdk): improve memory management for summary updates by @dmitryduev in https://github.com/wandb/wandb/pull/5569
- fix(artifacts): Add environment variable to configure batch size for download urls by @ibindlish in https://github.com/wandb/wandb/pull/6323
- fix(launch): fail rqis if no run is created by @bcsherma in https://github.com/wandb/wandb/pull/6324

### :books: Docs

- docs(sdk): fixes a broken link in Image docs. by @katjacksonWB in https://github.com/wandb/wandb/pull/6252
- docs(nexus): add docs on running nexus-related system tests locally by @dmitryduev in https://github.com/wandb/wandb/pull/6191
- docs(nexus): add user-facing Nexus docs for Beta release by @dmitryduev in https://github.com/wandb/wandb/pull/6276
- docs(nexus): fix pip install nexus instruction by @dmitryduev in https://github.com/wandb/wandb/pull/6309

### :nail_care: Cleanup

- Update README.md by @NinoRisteski in https://github.com/wandb/wandb/pull/6325

## New Contributors

- @katjacksonWB made their first contribution in https://github.com/wandb/wandb/pull/6252
- @NinoRisteski made their first contribution in https://github.com/wandb/wandb/pull/6325

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.10...v0.15.11

# 0.15.10 (Sep 6, 2023)

### :magic_wand: Enhancements

- feat(integrations): add async support to `Autologger` API and enable it for Openai by @parambharat in https://github.com/wandb/wandb/pull/5960
- feat(sdk): add official support for python 3.11 and drop support for python 3.6 by @dmitryduev in https://github.com/wandb/wandb/pull/4386
- feat(sdk): implement network logging and file pusher timeout for debugging by @dmitryduev in https://github.com/wandb/wandb/pull/5894
- feat(artifacts): set ttl(time to live) for artifact versions by @estellazx in https://github.com/wandb/wandb/pull/5859
- feat(nexus): add support for define metric by @kptkin in https://github.com/wandb/wandb/pull/6036
- feat(launch): Include agent version when creating launch agent by @TimH98 in https://github.com/wandb/wandb/pull/5970
- feat(launch): Runless git jobs can use requirements.txt in parent directories by @TimH98 in https://github.com/wandb/wandb/pull/6008
- feat(artifacts): retrieve the parent collection from an Artifact by @moredatarequired in https://github.com/wandb/wandb/pull/6019
- feat(nexus): improve file uploads by @dmitryduev in https://github.com/wandb/wandb/pull/6052
- feat(artifacts): Add run id option to artifact put method to log artifacts to existing runs by @ibindlish in https://github.com/wandb/wandb/pull/6074
- feat(public-api): add metadata property to Run object by @dmitryduev in https://github.com/wandb/wandb/pull/6100
- feat(launch): Support setting a custom Dockerfile in launch overrides by @TimH98 in https://github.com/wandb/wandb/pull/6104
- feat(nexus): add Nvidia GPU asset to system monitor by @dmitryduev in https://github.com/wandb/wandb/pull/6081
- feat(artifacts): enable deleting artifact collections from SDK by @moredatarequired in https://github.com/wandb/wandb/pull/6020
- feat(launch): Add dockerfile CLI param & use Dockerfile.wandb by default if present by @TimH98 in https://github.com/wandb/wandb/pull/6122
- feat(artifacts): extend cache cleanup to allow specifying a target fraction by @moredatarequired in https://github.com/wandb/wandb/pull/6152
- feat(artifacts): add an eval-able repr to ArtifactManifestEntry by @moredatarequired in https://github.com/wandb/wandb/pull/6132
- feat(nexus): enable docker-based wheel building for nexus by @dmitryduev in https://github.com/wandb/wandb/pull/6118
- feat(nexus): add Nvidia GPU asset to system monitor by @dmitryduev in https://github.com/wandb/wandb/pull/6131
- feat(artifacts): clear the cache on add to prevent overflow by @moredatarequired in https://github.com/wandb/wandb/pull/6149
- feat(sdk): capture disk i/o utilization in system metrics by @umakrishnaswamy in https://github.com/wandb/wandb/pull/6106
- feat(sdk): add disk io counters to monitor metrics by @dmitryduev in https://github.com/wandb/wandb/pull/6170
- feat(sdk): make paths for disk usage monitoring configurable by @dmitryduev in https://github.com/wandb/wandb/pull/6196
- feat(sweeps): Use `WANDB_SWEEP_ID` to include a run in an existing sweep by @gtarpenning in https://github.com/wandb/wandb/pull/6198
- feat(artifacts): Handle LinkArtifact calls made to Nexus Core by @ibindlish in https://github.com/wandb/wandb/pull/6160
- feat(nexus): fix retry logic for http clients and allow user customization by @kptkin in https://github.com/wandb/wandb/pull/6182
- feat(nexus): support user defined headers in the gql client transport by @kptkin in https://github.com/wandb/wandb/pull/6208
- feat(sdk): enable set types in wandb.Config by @fdsig in https://github.com/wandb/wandb/pull/6219
- feat(integrations): visualize images with bbox overlays for `ultralytics` by @soumik12345 in https://github.com/wandb/wandb/pull/5867
- feat(sdk): add exponential decay sampling utility for line_plot by @dmitryduev in https://github.com/wandb/wandb/pull/6228
- feat(sdk): always print the traceback inside of the `wandb.init` context manager by @kptkin in https://github.com/wandb/wandb/pull/4603
- feat(sdk): add setting to disable automatic machine info capture by @kptkin in https://github.com/wandb/wandb/pull/6230

### :hammer: Fixes

- fix(launch): Extend try in agent loop to cover all job handling by @KyleGoyette in https://github.com/wandb/wandb/pull/5923
- fix(sdk): guard against undefined filestream timeout by @dmitryduev in https://github.com/wandb/wandb/pull/5997
- fix(launch): error if code artifact underlying job has been deleted by @bcsherma in https://github.com/wandb/wandb/pull/5959
- fix(artifacts): use a unique name for the artifact created by `verify` by @moredatarequired in https://github.com/wandb/wandb/pull/5929
- fix(launch): Use resume=allow when auto requeuing by @TimH98 in https://github.com/wandb/wandb/pull/6002
- fix(launch): correct entrypoint path from disabled git repo subir by @gtarpenning in https://github.com/wandb/wandb/pull/5903
- fix(sweeps): override individual job resource_args by @gtarpenning in https://github.com/wandb/wandb/pull/5985
- fix(sdk): fix import issue to support python 3.6 by @kptkin in https://github.com/wandb/wandb/pull/6018
- fix(launch): Fix override entrypoint when using sweeps on launch without a scheduler job by @KyleGoyette in https://github.com/wandb/wandb/pull/6033
- fix(nexus): fix resume reference when nil by @kptkin in https://github.com/wandb/wandb/pull/6055
- fix(sdk): further speed up import time by @hauntsaninja in https://github.com/wandb/wandb/pull/6032
- fix(launch): Fix sample kubernetes agent manifest secret mount by @KyleGoyette in https://github.com/wandb/wandb/pull/6057
- fix(nexus): rm unused import by @dmitryduev in https://github.com/wandb/wandb/pull/6085
- fix(launch): watch to get kubernetes run statuses by @bcsherma in https://github.com/wandb/wandb/pull/6022
- fix(artifacts): prohibit saving artifacts to a different project than their base artifact by @moredatarequired in https://github.com/wandb/wandb/pull/6042
- fix(artifacts): require existing artifacts to save to their source entity/project by @moredatarequired in https://github.com/wandb/wandb/pull/6034
- fix(nexus): adjust system monitor start and stop functionality by @dmitryduev in https://github.com/wandb/wandb/pull/6087
- fix(artifacts): remove suspect characters when directory creation fails by @moredatarequired in https://github.com/wandb/wandb/pull/6094
- fix(launch): Default log_code exclusion behavior now correctly handles `wandb` in the root path prefix. by @nickpenaranda in https://github.com/wandb/wandb/pull/6095
- fix(launch): disallow project queue creation by @bcsherma in https://github.com/wandb/wandb/pull/6011
- fix(launch): catch all sweep set state errors by @gtarpenning in https://github.com/wandb/wandb/pull/6091
- fix(launch): create_job now works from jupyter notebook by @gtarpenning in https://github.com/wandb/wandb/pull/6068
- fix(nexus): fix race condition for defer and update control by @kptkin in https://github.com/wandb/wandb/pull/6125
- fix(sdk): improved handling and logging of tensor types by @kptkin in https://github.com/wandb/wandb/pull/6086
- fix(launch): launch cli command should exit with non-zero status if underlying launched run exits with non-zero status by @KyleGoyette in https://github.com/wandb/wandb/pull/6078
- fix(nexus): fix correctness for offline mode by @kptkin in https://github.com/wandb/wandb/pull/6166
- fix(sdk): reports api - fix media_keys json path by @laxels in https://github.com/wandb/wandb/pull/6167
- fix(sdk): Allow uint8 images to be logged as wandb.Image() by @nate-wandb in https://github.com/wandb/wandb/pull/6043
- fix(sdk): fall back to /tmp/username/.config/wandb in old settings by @dmitryduev in https://github.com/wandb/wandb/pull/6175
- fix(nexus): use UpsertBucketRetryPolicy in all gql.UpsertBucket calls by @dmitryduev in https://github.com/wandb/wandb/pull/6207
- fix(sdk): update report id validation and encoding by @jo-fang in https://github.com/wandb/wandb/pull/6203
- fix(sdk): add support for propagating messages from the internal process by @kptkin in https://github.com/wandb/wandb/pull/5803

### :books: Docs

- docs(nexus): add package level docstrings for filestream by @raubitsj in https://github.com/wandb/wandb/pull/6061
- docs(nexus): add basic developer guide by @kptkin in https://github.com/wandb/wandb/pull/6119
- docs(cli): Added more context for launch job describe description. by @ngrayluna in https://github.com/wandb/wandb/pull/6193

### :nail_care: Cleanup

- style(sdk): fix to new ruff rule E721 additions by @nickpenaranda in https://github.com/wandb/wandb/pull/6102

## New Contributors

- @geoffrey-g-delhomme made their first contribution in https://github.com/wandb/wandb/pull/5867
- @kooshi made their first contribution in https://github.com/wandb/wandb/pull/6086
- @umakrishnaswamy made their first contribution in https://github.com/wandb/wandb/pull/6106
- @jo-fang made their first contribution in https://github.com/wandb/wandb/pull/6203
- @wwzeng1 made their first contribution in https://github.com/wandb/wandb/pull/6228

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.9...v0.15.10

# 0.15.9 (Aug 28, 2023)

### :magic_wand: Enhancements

- feat(sweeps): launch sweep schedulers to team queues from UI by @gtarpenning in https://github.com/wandb/wandb/pull/6112
- feat(launch): make vertex launcher more customizable by @bcsherma in https://github.com/wandb/wandb/pull/6088
- feat(launch): default to noop builder if docker not installed by @bcsherma in https://github.com/wandb/wandb/pull/6137

### :hammer: Fixes

- fix(launch): Use built in entrypoint and args commands for sagemaker by @KyleGoyette in https://github.com/wandb/wandb/pull/5897
- fix(artifacts): copy parent source project info to new draft artifact by @moredatarequired in https://github.com/wandb/wandb/pull/6062
- fix(sdk): avoid error at end of run with bigints by @raubitsj in https://github.com/wandb/wandb/pull/6134
- fix(launch): manually created image jobs can rerun correctly by @gtarpenning in https://github.com/wandb/wandb/pull/6148

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.8...v0.15.9

# 0.15.8 (Aug 01, 2023)

### :magic_wand: Enhancements

- perf(sdk): use mutation createRunFiles to get uploadUrls by @harukatab in https://github.com/wandb/wandb/pull/5731
- feat(launch): add create_run_queue to public API by @nickpenaranda in https://github.com/wandb/wandb/pull/5874
- perf(sdk): add hidden option to use orjson instead of json by @dmitryduev in https://github.com/wandb/wandb/pull/5911
- feat(launch): Improve error message when building with noop builder by @TimH98 in https://github.com/wandb/wandb/pull/5925
- feat(launch): create launch agent includes agent config if present by @TimH98 in https://github.com/wandb/wandb/pull/5893
- feat(launch): Check if job ingredients exist before making job by @TimH98 in https://github.com/wandb/wandb/pull/5942
- feat(launch): Gracefully handle Kubernetes 404 error by @TimH98 in https://github.com/wandb/wandb/pull/5945

### :hammer: Fixes

- fix(sdk): only creating new project if it doesn't already exist by @mbarrramsey in https://github.com/wandb/wandb/pull/5814
- fix(launch): Support namespace in metadata key of resource args by @KyleGoyette in https://github.com/wandb/wandb/pull/5639
- fix(launch): use "" instead of None for project kwarg when no project given by @bcsherma in https://github.com/wandb/wandb/pull/5839
- fix(launch): add + to torch cpu regex + tests by @bcsherma in https://github.com/wandb/wandb/pull/5833
- fix(sdk): implement timeout for file_stream and add debug logs by @kptkin in https://github.com/wandb/wandb/pull/5812
- fix(artifacts): fix collection filtering when getting aliases by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5810
- fix(sdk): replace `dir_watcher` settings with SettingsStatic by @kptkin in https://github.com/wandb/wandb/pull/5863
- fix(artifacts): set correct base for incremental artifacts by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5870
- fix(launch): drop https from azure registries to ensure compatibility with ${image_uri} macro by @bcsherma in https://github.com/wandb/wandb/pull/5880
- fix(artifacts): handle None description correctly by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5910
- fix(launch): Don't create k8s secret if it already exists by @TimH98 in https://github.com/wandb/wandb/pull/5900
- fix(artifacts): drop S3 bucket versioning check by @moredatarequired in https://github.com/wandb/wandb/pull/5927
- fix(sdk): speed up import time and fix `pkg_resources` DeprecationWarning by @hauntsaninja in https://github.com/wandb/wandb/pull/5899

### :books: Docs

- docs(sdk): Add introspection section to CONTRIBUTING.md by @nickpenaranda in https://github.com/wandb/wandb/pull/5887
- docs(sdk): update GH action to generate reference docs and clean up docstrings by @dmitryduev in https://github.com/wandb/wandb/pull/5947
- docs(sdk): update `README.md` to unify the spelling of `Hugging Face` by @eltociear in https://github.com/wandb/wandb/pull/5891

### :nail_care: Cleanup

- revert(launch): revert job re-queuing implementation on pod disconnect by @KyleGoyette in https://github.com/wandb/wandb/pull/5811

## New Contributors

- @mbarrramsey made their first contribution in https://github.com/wandb/wandb/pull/5814
- @hauntsaninja made their first contribution in https://github.com/wandb/wandb/pull/5899
- @eltociear made their first contribution in https://github.com/wandb/wandb/pull/5891

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.7...v0.15.8

# 0.15.7 (July 25, 2023)

### :hammer: Fixes

- fix(sdk): images not syncing until the end run (revert #5777) by @raubitsj in https://github.com/wandb/wandb/pull/5951

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.6...v0.15.7

# 0.15.6 (July 24, 2023)

### :magic_wand: Enhancements

- feat(launch): add job link to wandb footer by @bcsherma in https://github.com/wandb/wandb/pull/5767
- feat(launch): re-implement job requeueing, fixed cancel behavior by @TimH98 in https://github.com/wandb/wandb/pull/5822
- feat(launch): manually create jobs from cli by @gtarpenning in https://github.com/wandb/wandb/pull/5661
- feat(launch): allow users to specify job name via the `job_name` setting by @bcsherma in https://github.com/wandb/wandb/pull/5791
- feat(sdk): Add an simplified trace API to log prompt traces by @parambharat in https://github.com/wandb/wandb/pull/5794
- feat(integrations): support `.keras` model format with `WandbModelCheckpoint` and TF 2.13.0 compatible by @soumik12345 in https://github.com/wandb/wandb/pull/5720
- feat(sdk): Initial support for migrating W&B runs and reports between instances by @andrewtruong in https://github.com/wandb/wandb/pull/5777

### :hammer: Fixes

- fix(integrations): make LightGBM callback compatible with 4.0.0 by @ayulockin in https://github.com/wandb/wandb/pull/5906
- fix(sdk): use default settings for project retrieval if available by @KyleGoyette in https://github.com/wandb/wandb/pull/5917

### :books: Docs

- docs(sdk): Add introspection section to CONTRIBUTING.md by @nickpenaranda in https://github.com/wandb/wandb/pull/5887

### :nail_care: Cleanup

- revert(launch): revert job re-queuing implementation on pod disconnect by @KyleGoyette in https://github.com/wandb/wandb/pull/5811

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.5...v0.15.6

## 0.15.5 (July 5, 2023)

### :magic_wand: Enhancements

- feat(launch): improve handling of docker image job names and tags by @gtarpenning in https://github.com/wandb/wandb/pull/5718
- feat(launch): support kaniko builds on AKS by @bcsherma in https://github.com/wandb/wandb/pull/5706
- feat(launch): allow kaniko builds to run in other namespaces by @bcsherma in https://github.com/wandb/wandb/pull/5637
- feat(artifacts): support access key for Azure references by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5729
- feat(launch): add information to failed run queue items, support warnings for run queue items by @KyleGoyette in https://github.com/wandb/wandb/pull/5612
- feat(launch): allow direct configuration of registry uri for all registries by @bcsherma in https://github.com/wandb/wandb/pull/5760
- perf(artifacts): enhance download URL fetching process with batch and retry logic by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5692
- feat(artifacts): add flag to skip missing S3 references in `Artifact.download` by @moredatarequired in https://github.com/wandb/wandb/pull/5778
- feat(launch): implement job requeueing when pod disconnects by @TimH98 in https://github.com/wandb/wandb/pull/5770
- feat(sdk): add setting to disable setproctitle by @raubitsj in https://github.com/wandb/wandb/pull/5805

### :hammer: Fixes

- fix(sdk): handle uri schemes in LogicalPath by @dmitryduev in https://github.com/wandb/wandb/pull/5670
- fix(artifacts): update object storage to include reference and prevent id reuse by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5722
- fix(sweeps): update click package version requirements by @gtarpenning in https://github.com/wandb/wandb/pull/5738
- fix(sdk): improve lazy import to be thread-safe by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5727
- fix(launch): change typo in kaniko image name by @bcsherma in https://github.com/wandb/wandb/pull/5743
- fix(integrations): correct date parsing in SageMaker configuration by @rymc in https://github.com/wandb/wandb/pull/5759
- fix(launch): make docker build non interactive to prevent region based questions by @KyleGoyette in https://github.com/wandb/wandb/pull/5736
- fix(launch): update "cuda" base image path to "accelerator" base image path by @KyleGoyette in https://github.com/wandb/wandb/pull/5737
- fix(artifacts): replace artifact name with placeholder to skip validation by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5724
- fix(launch): prevent jobs with large outputs from hanging on local-container by @KyleGoyette in https://github.com/wandb/wandb/pull/5774
- fix(launch): Ensure resume does not push sensitive info by @KyleGoyette in https://github.com/wandb/wandb/pull/5807
- fix(artifacts): fix handling of references when downloading by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5808
- fix(sweeps): correct launch sweep author to personal username by @gtarpenning in https://github.com/wandb/wandb/pull/5806
- refactor(artifacts): change artifact methods and attributes to private by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5790

### :books: Docs

- docs(sdk): update the product icons in README.md by @ngrayluna in https://github.com/wandb/wandb/pull/5713
- docs(artifacts): update docs by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5701
- docs(artifacts): fix comment about total retry time by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5751
- docs(sdk): expose WBTraceTree as data_types.WBTraceTree by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5788

## New Contributors

- @HipHoff made their first contribution in https://github.com/wandb/wandb/pull/5691
- @rymc made their first contribution in https://github.com/wandb/wandb/pull/5759

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.4...v0.15.5

## 0.15.4 (June 6, 2023)

### :magic_wand: Enhancements

- feat(sdk): set job source in settings by @TimH98 in https://github.com/wandb/wandb/pull/5442
- feat(sweeps): launch sweeps controlled by wandb run by @gtarpenning in https://github.com/wandb/wandb/pull/5456
- feat(integrations): add autolog for Cohere python SDK by @dmitryduev in https://github.com/wandb/wandb/pull/5474
- feat(launch): support launching custom k8s objects by @bcsherma in https://github.com/wandb/wandb/pull/5486
- perf(artifacts): conserve memory when hashing files by @moredatarequired in https://github.com/wandb/wandb/pull/5513
- feat(artifacts): add new_draft method to modify and log saved artifacts as new version by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5524
- feat(launch): don't install frozen reqs if there is a reqs file by @bcsherma in https://github.com/wandb/wandb/pull/5548
- feat(artifacts): don't remove temp files from artifacts cache by default by @moredatarequired in https://github.com/wandb/wandb/pull/5596
- feat(artifacts): add source_entity and update sequenceName handling by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5546
- feat(artifacts): add 'remove' to Artifacts API by @moredatarequired in https://github.com/wandb/wandb/pull/5370
- feat(sweeps): optuna scheduler for sweeps on launch by @gtarpenning in https://github.com/wandb/wandb/pull/4900
- feat(launch): support notebook job creation by @KyleGoyette in https://github.com/wandb/wandb/pull/5462
- feat(launch): enable launch macros for all runners by @bcsherma in https://github.com/wandb/wandb/pull/5624
- feat(integrations): add autologging for supported huggingface pipelines by @ash0ts in https://github.com/wandb/wandb/pull/5579
- feat(integrations): add usage metrics and table logging to OpenAI autologger by @parambharat in https://github.com/wandb/wandb/pull/5521
- feat(sdk): add support for monitoring AMD GPU system metrics by @dmitryduev in https://github.com/wandb/wandb/pull/5449
- feat(sdk): capture absolute GPU memory allocation by @dmitryduev in https://github.com/wandb/wandb/pull/5643

### :hammer: Fixes

- fix(integrations): ensure wandb can be used in AWS lambda by @dmitryduev in https://github.com/wandb/wandb/pull/5083
- fix(sdk): permit `LogicalPath` to strip trailing slashes by @moredatarequired in https://github.com/wandb/wandb/pull/5473
- fix(sdk): exercise caution when creating ~/.config/wandb/settings file by @dmitryduev in https://github.com/wandb/wandb/pull/5478
- fix(sdk): update custom chart query handling and add alternate constructor for table-based charts by @andrewtruong in https://github.com/wandb/wandb/pull/4852
- fix(artifacts): add s3 multipart uploading for artifact files by @estellazx in https://github.com/wandb/wandb/pull/5377
- fix(artifacts): handle incompatible artifact name strings by @andrewtruong in https://github.com/wandb/wandb/pull/5416
- fix(launch): docker runner always pull for image sourced jobs by @bcsherma in https://github.com/wandb/wandb/pull/5531
- fix(launch): improve error handling for package installation by @TimH98 in https://github.com/wandb/wandb/pull/5509
- fix(launch): custom k8s objects respect command/args overrides by @bcsherma in https://github.com/wandb/wandb/pull/5538
- fix(artifacts): remove entity, project from valid properties and adjust name handling by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5533
- fix(launch): use env var for launch agent base url by @KyleGoyette in https://github.com/wandb/wandb/pull/5482
- fix(artifacts): write to the cache defensively (catch OSError) by @moredatarequired in https://github.com/wandb/wandb/pull/5597
- fix(launch): handle exception in finish_thread_id and fail run queue items by @KyleGoyette in https://github.com/wandb/wandb/pull/5610
- fix(launch): add pull secrets for pre made images when registry is specified by @bcsherma in https://github.com/wandb/wandb/pull/5602
- fix(launch): read kaniko pod sa name from env var by @bcsherma in https://github.com/wandb/wandb/pull/5619
- fix(launch): misc gcp fixes by @bcsherma in https://github.com/wandb/wandb/pull/5626
- fix(launch): support local environment and registry declaration by @KyleGoyette in https://github.com/wandb/wandb/pull/5630
- fix(launch): support ssh git urls and submodules in agent by @KyleGoyette in https://github.com/wandb/wandb/pull/5635
- fix(sdk): update git repo handling for failure cases and rename to gitlib by @kptkin in https://github.com/wandb/wandb/pull/5437
- fix(sdk): unify offline and online mode during init and fix multiprocess attach by @kptkin in https://github.com/wandb/wandb/pull/5296
- fix(integrations): prevent errors by checking for `wandb.run` in Gym integration by @ash0ts in https://github.com/wandb/wandb/pull/5649
- fix(sdk): fix wandb tfevent sync issue by @eohomegrownapps in https://github.com/wandb/wandb/pull/5261

### :books: Docs

- docs(sdk): update contrib for yea-wandb changes by @kptkin in https://github.com/wandb/wandb/pull/5614

## New Contributors

- @eohomegrownapps made their first contribution in https://github.com/wandb/wandb/pull/5261

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.3...v0.15.4

## 0.15.3 (May 17, 2023)

### :hammer: Fixes

- fix(sdk): allow SDK to work if SA token can't be read by @wandb-zacharyblasczyk in https://github.com/wandb/wandb/pull/5472
- fix(sdk): clean up the k8s token discovery logic in util.py::image_id_from_k8s by @dmitryduev in https://github.com/wandb/wandb/pull/5518
- fix(integrations): Update `WandbTracer` to work with new langchain version by @parambharat in https://github.com/wandb/wandb/pull/5558
- revert(sdk): update summary for changed keys only by @dmitryduev in https://github.com/wandb/wandb/pull/5562

## New Contributors

- @wandb-zacharyblasczyk made their first contribution in https://github.com/wandb/wandb/pull/5472

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.2...v0.15.3

## 0.15.2 (May 5, 2023)

### :hammer: Fixes

- fix(integrations): update WandbTracer for new langchain release by @parambharat @tssweeney in https://github.com/wandb/wandb/pull/5467
- fix(integrations): fix error message in langchain wandb_tracer version check by @dmitryduev in https://github.com/wandb/wandb/pull/5490

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.1...v0.15.2

## 0.15.1 (May 2, 2023)

### :magic_wand: Enhancements

- feat(launch): implement new Kubernetes runner config schema by @TimH98 in https://github.com/wandb/wandb/pull/5231
- feat(launch): allow platform override for docker builder by @TimH98 in https://github.com/wandb/wandb/pull/5330
- feat(artifacts): get full name of artifact for easier artifact retrieval by @estellazx in https://github.com/wandb/wandb/pull/5314
- feat(artifacts): make default root for artifacts download configurable by @moredatarequired in https://github.com/wandb/wandb/pull/5366
- feat(artifacts): add Azure storage handler in SDK by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5317
- feat(media): add method to convert wandb.Table to pandas.DataFrame by @brunnelu in https://github.com/wandb/wandb/pull/5301
- feat(launch): sweeps on launch command args passed as params by @gtarpenning in https://github.com/wandb/wandb/pull/5315

### :hammer: Fixes

- fix(launch): don't assume keys in args and config refer to the same thing by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5183
- fix(launch): make ElasticContainerRegistry environment handle "ImageNotFoundException" gracefully by @bcsherma in https://github.com/wandb/wandb/pull/5159
- fix(launch): disable kaniko builder retry by @TimH98 in https://github.com/wandb/wandb/pull/5318
- fix(sdk): refine error message for auth error by @kptkin in https://github.com/wandb/wandb/pull/5341
- fix(launch): kubernetes runner does not respect override args by @KyleGoyette in https://github.com/wandb/wandb/pull/5303
- fix(sweeps): allow attr-dicts as sweeps configs by @moredatarequired in https://github.com/wandb/wandb/pull/5268
- fix(artifacts): checksum the read-only staging copy instead of the original file by @moredatarequired in https://github.com/wandb/wandb/pull/5346
- fix(launch): skip getting run info if run completes successfully or is from a different entity by @TimH98 in https://github.com/wandb/wandb/pull/5379
- fix(artifacts): default to project "uncategorized" instead of "None" when fetching artifacts by @szymon-piechowicz-wandb in https://github.com/wandb/wandb/pull/5375
- fix(integrations): add enabled check to gym VideoRecorder by @younik in https://github.com/wandb/wandb/pull/5230
- fix(artifacts): fix handling of default project and entity by @dmitryduev in https://github.com/wandb/wandb/pull/5395
- fix(sdk): update import_hook.py with latest changes in the wrapt repository by @kptkin in https://github.com/wandb/wandb/pull/5321
- fix(launch): fix support for local urls in k8s launch agent by @KyleGoyette in https://github.com/wandb/wandb/pull/5413
- fix(sdk): improve notebook environment detection and testing by @dmitryduev in https://github.com/wandb/wandb/pull/4982
- fix(sdk): implement recursive isinstance check utility for the Settings object by @dmitryduev in https://github.com/wandb/wandb/pull/5436
- fix(sdk): correctly parse edge cases in OpenMetrics filter definitions in System Monitor by @dmitryduev in https://github.com/wandb/wandb/pull/5329
- fix(sdk): update debug logs to include SDK's version by @kptkin in https://github.com/wandb/wandb/pull/5344
- fix(sdk): filter AWS Trainium metrics by local rank if executed with torchrun by @dmitryduev in https://github.com/wandb/wandb/pull/5142
- fix(integrations): inform users about WandbTracer incompatibility with LangChain > 0.0.153 by @hwchase17 in https://github.com/wandb/wandb/pull/5453

### :books: Docs

- docs(sdk): update README.md by @thanos-wandb in https://github.com/wandb/wandb/pull/5386
- docs(integrations): update docstrings of the Keras callbacks by @ayulockin in https://github.com/wandb/wandb/pull/5198
- docs(sdk): update the images in `README.md` by @ngrayluna in https://github.com/wandb/wandb/pull/5399

## New Contributors

- @szymon-piechowicz-wandb made their first contribution in https://github.com/wandb/wandb/pull/5183
- @thanos-wandb made their first contribution in https://github.com/wandb/wandb/pull/5386
- @brunnelu made their first contribution in https://github.com/wandb/wandb/pull/5301
- @younik made their first contribution in https://github.com/wandb/wandb/pull/5230
- @hwchase17 made their first contribution in https://github.com/wandb/wandb/pull/5453

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.15.0...v0.15.1

## 0.15.0 (April 19, 2023)

### :magic_wand: Enhancements

- feat(media): add support for LangChain media type by @tssweeney in https://github.com/wandb/wandb/pull/5288
- feat(integrations): add autolog for OpenAI's python library by @dmitryduev @parambharat @kptkin @raubitsj in https://github.com/wandb/wandb/pull/5362

### :hammer: Fixes

- fix(integrations): add function signature wrapper to the patched openai methods by @parambharat in https://github.com/wandb/wandb/pull/5369
- fix(integrations): adjust OpenAI autolog public API to improve user experience by @dmitryduev @kptkin @raubitsj in https://github.com/wandb/wandb/pull/5381

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.14.2...v0.15.0

## 0.14.2 (April 7, 2023)

### :hammer: Fixes

- fix(sdk): fix `wandb sync` regression by @kptkin in https://github.com/wandb/wandb/pull/5306

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.14.1...v0.14.2

## 0.14.1 (April 5, 2023)

### :magic_wand: Enhancements

- feat(artifacts): improve run.log_artifact() with default type and path references by @moredatarequired in https://github.com/wandb/wandb/pull/5131
- feat(artifacts): add opt-in support for async artifact upload by @speezepearson in https://github.com/wandb/wandb/pull/4864
- perf(sdk): update summary for changed keys only by @dmitryduev in https://github.com/wandb/wandb/pull/5150
- feat(sdk): use a persistent session object for GraphQL requests by @moredatarequired in https://github.com/wandb/wandb/pull/5075
- feat(sdk): allow setting of extra headers for the gql client by @dmitryduev in https://github.com/wandb/wandb/pull/5237
- feat(sdk): allow filtering metrics based on OpenMetrics endpoints by @dmitryduev in https://github.com/wandb/wandb/pull/5282

### :hammer: Fixes

- fix(artifacts): more informative message when failing to create staging artifact directory by @moredatarequired in https://github.com/wandb/wandb/pull/5067
- fix(launch): set default value for Kubernetes backoffLimit to 0 by @KyleGoyette in https://github.com/wandb/wandb/pull/5072
- fix(sdk): remove default sorting when dumping config into a yaml file by @kptkin in https://github.com/wandb/wandb/pull/5127
- fix(media): fix encoding for html types on windows by @kptkin in https://github.com/wandb/wandb/pull/5180
- fix(sdk): clean up auto resume state when initializing a new run by @kptkin in https://github.com/wandb/wandb/pull/5184
- fix(sdk): harden `wandb.init()` error handling for backend errors by @kptkin in https://github.com/wandb/wandb/pull/5023
- fix(sdk): fix system monitor shutdown logic by @dmitryduev in https://github.com/wandb/wandb/pull/5227
- fix(launch): allow users to specify pinned versions in requirements.txt by @KyleGoyette in https://github.com/wandb/wandb/pull/5226
- fix(sdk): make `wandb.log()` handle empty string values properly by @dannygoldstein in https://github.com/wandb/wandb/pull/5275
- fix(sdk): raise exception when accessing methods and attributes of a finished run by @kptkin in https://github.com/wandb/wandb/pull/5013

### :books: Docs

- docs(launch): add documentation for launch by @iveksl2 in https://github.com/wandb/wandb/pull/4596
- docs(sdk): add documentation for Object3D media type by @ssisk in https://github.com/wandb/wandb/pull/4810
- docs(sdk): remove duplicate docstring in keras integration by @Gladiator07 in https://github.com/wandb/wandb/pull/5289
- docs(artifacts): convert docstrings to Google convention by @moredatarequired in https://github.com/wandb/wandb/pull/5276

### :nail_care: Cleanup

- refactor(artifacts): use 'secrets' module instead of custom random token generator by @moredatarequired in https://github.com/wandb/wandb/pull/5050
- refactor(artifacts): move \_manifest_json_from_proto to sender.py by @moredatarequired in https://github.com/wandb/wandb/pull/5178

## New Contributors

- @iveksl2 made their first contribution in https://github.com/wandb/wandb/pull/4596
- @Gladiator07 made their first contribution in https://github.com/wandb/wandb/pull/5289

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.14.0...v0.14.1

## 0.14.0 (March 14, 2023)

### :magic_wand: Enhancements

- feat(launch): support cuda base image for launch runs by @KyleGoyette in https://github.com/wandb/wandb/pull/5044
- feat(launch): warn users of which packages failed to install during build process by @KyleGoyette in https://github.com/wandb/wandb/pull/5109
- feat(sdk): add support for importing runs from MLFlow by @andrewtruong in https://github.com/wandb/wandb/pull/4950
- feat(launch): mark queued runs that fail to launch as `FAILED` by @KyleGoyette in https://github.com/wandb/wandb/pull/5129

### :hammer: Fixes

- fix(sdk): temporarily remove local api key validation by @dmitryduev in https://github.com/wandb/wandb/pull/5095
- fix(launch): launch agent gracefully removes thread when it has an exception by @TimH98 in https://github.com/wandb/wandb/pull/5105
- fix(launch): give clear error message when cannot connect to Docker daemon by @TimH98 in https://github.com/wandb/wandb/pull/5092
- fix(launch): launch support for EKS instance roles by @bcsherma in https://github.com/wandb/wandb/pull/5112
- fix(launch): cleaner error messages when launch encounters docker errors and graceful fail by @TimH98 in https://github.com/wandb/wandb/pull/5124
- fix(launch): hash docker images based on job version and dockerfile contents by @KyleGoyette in https://github.com/wandb/wandb/pull/4996
- security(launch): warn when agent is started polling on a team queue by @TimH98 in https://github.com/wandb/wandb/pull/5126
- fix(sdk): add telemetry when syncing tfevents files by @raubitsj in https://github.com/wandb/wandb/pull/5141
- fix(sdk): fix regression preventing run stopping from working by @raubitsj in https://github.com/wandb/wandb/pull/5139
- fix(launch): instruct user how to handle missing kubernetes import when using kubernetes runner or kaniko builder by @TimH98 in https://github.com/wandb/wandb/pull/5138
- fix(launch): hide unsupported launch CLI options by @KyleGoyette in https://github.com/wandb/wandb/pull/5153
- fix(launch): make launch image builder install Pytorch properly with dependencies on different hardware by @bcsherma in https://github.com/wandb/wandb/pull/5147

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.11...v0.14.0

## 0.13.11 (March 7, 2023)

### :magic_wand: Enhancements

- feat(launch): improve launch agent logging by @TimH98 in https://github.com/wandb/wandb/pull/4944
- feat(sweeps): sweep run_cap now works for launch sweeps by @gtarpenning in https://github.com/wandb/wandb/pull/4937
- feat(sweeps): launch sweep jobs from image_uri by @gtarpenning in https://github.com/wandb/wandb/pull/4976
- feat(launch): add `num_workers` param to scheduler section in `launch_config` by @gtarpenning in https://github.com/wandb/wandb/pull/5035
- feat(artifacts): raise ArtifactNotLoggedError instead of ValueError by @moredatarequired in https://github.com/wandb/wandb/pull/5026
- feat(launch): launch agent uses thread pool to run jobs by @TimH98 in https://github.com/wandb/wandb/pull/5033
- feat(launch): make runners and builders use Environment & Registry classes by @bcsherma in https://github.com/wandb/wandb/pull/5011
- feat(sdk): add OpenMetrics support for System Metrics by @dmitryduev in https://github.com/wandb/wandb/pull/4899
- feat(sdk): add ability to filter system metrics consumed from OpenMetrics endpoints by @dmitryduev in https://github.com/wandb/wandb/pull/5034
- feat(sdk): add support for gymnasium env monitoring, in addition to gym by @dmitryduev in https://github.com/wandb/wandb/pull/5008
- feat(launch): add `max_scheduler` key to launch agent config by @gtarpenning in https://github.com/wandb/wandb/pull/5057
- feat(integrations): add an integration with `ultralytics` library for YOLOv8 by @parambharat in https://github.com/wandb/wandb/pull/5037

### :hammer: Fixes

- fix(sdk): clean up IPython's widget deprecation warning by @kptkin in https://github.com/wandb/wandb/pull/4912
- fix(sdk): add special Exceptions for the manager logic, when trying to connect to a gone service by @kptkin in https://github.com/wandb/wandb/pull/4890
- fix(sdk): fix issue where global config directory had to be writable to use Api by @KyleGoyette in https://github.com/wandb/wandb/pull/4689
- fix(sdk): make error message during run initialization more actionable and fix uncaught exception by @kptkin in https://github.com/wandb/wandb/pull/4909
- fix(sdk): add deepcopy dunder method to the Run class by @kptkin in https://github.com/wandb/wandb/pull/4891
- fix(launch): remove default to project always in sweep by @gtarpenning in https://github.com/wandb/wandb/pull/4927
- fix(sweeps): error out when trying to create a launch sweep without a job specified by @gtarpenning in https://github.com/wandb/wandb/pull/4938
- fix(launch): mkdir_exists_ok now (again) checks permission on existence by @gtarpenning in https://github.com/wandb/wandb/pull/4936
- fix(launch): only log the received job when launching something sourced from a job by @KyleGoyette in https://github.com/wandb/wandb/pull/4886
- fix(launch): fix issue where queued runs sourced from images would vanish in URI by @KyleGoyette in https://github.com/wandb/wandb/pull/4701
- fix(artifacts): add write permissions to copied artifacts by @moredatarequired in https://github.com/wandb/wandb/pull/4641
- fix(sweeps): improve `queue` argument parsing in `sweep` cli command by @gtarpenning in https://github.com/wandb/wandb/pull/4941
- fix(sdk): when in disable mode don't spin up service by @kptkin in https://github.com/wandb/wandb/pull/4817
- fix(launch): fix support for docker images with user specified entrypoint in local container by @KyleGoyette in https://github.com/wandb/wandb/pull/4887
- fix(artifacts): API - ArtifactFiles no longer errors when accessing an item by @vwrj in https://github.com/wandb/wandb/pull/4896
- fix(sweeps): verify job exists before starting the sweeps scheduler by @gtarpenning in https://github.com/wandb/wandb/pull/4943
- fix(sdk): handle system metrics requiring extra setup and teardown steps by @dmitryduev in https://github.com/wandb/wandb/pull/4964
- fix(sdk): fix a typo in `CONTRIBUTING.md` by @fdsig in https://github.com/wandb/wandb/pull/4984
- fix(sdk): correctly detect notebook name and fix code saving in Colab by @dmitryduev in https://github.com/wandb/wandb/pull/4987
- fix(artifacts): allow up to max_artifacts (fix off by 1 error) by @moredatarequired in https://github.com/wandb/wandb/pull/4991
- fix(sdk): exercise extra caution when starting asset monitoring threads by @dmitryduev in https://github.com/wandb/wandb/pull/5007
- fix(sdk): fix bug where boto3 dependency crashes on import when downl… by @fdsig in https://github.com/wandb/wandb/pull/5018
- fix(sweeps): verify `num_workers` cli arg is valid and default to 8 if not by @gtarpenning in https://github.com/wandb/wandb/pull/5025
- fix(artifacts): fix the file reference added to the verification artifact by @moredatarequired in https://github.com/wandb/wandb/pull/4858
- fix(launch): special handling for sweeps scheduler in agent by @gtarpenning in https://github.com/wandb/wandb/pull/4961
- fix(artifacts): only re-download or overwrite files when there are changes by @moredatarequired in https://github.com/wandb/wandb/pull/5056
- fix(sdk): avoid introspection in offline mode by @kptkin in https://github.com/wandb/wandb/pull/5002
- fix(sdk): topological ordering of `wandb.Settings` by @dmitryduev in https://github.com/wandb/wandb/pull/4022
- fix(sdk): avoid lazy loading for tensorboard patching by @kptkin in https://github.com/wandb/wandb/pull/5079

### :books: Docs

- docs(cli): formatted wandb.apis.public.Run.history docstring by @ngrayluna in https://github.com/wandb/wandb/pull/4973
- docs(sdk): update references to test file locations in documentation by @moredatarequired in https://github.com/wandb/wandb/pull/4875
- docs(sdk): fix docstrings to enable project-wide pydocstyle checks by @moredatarequired in https://github.com/wandb/wandb/pull/5036
- docs(sdk): fix missed docstring lint errors reported by ruff by @moredatarequired in https://github.com/wandb/wandb/pull/5047
- docs(sdk): update links for new docs by @laxels in https://github.com/wandb/wandb/pull/4894
- docs(artifacts): raise ArtifactFinalizedError instead of ValueError by @moredatarequired in https://github.com/wandb/wandb/pull/5061

### :nail_care: Cleanup

- style(sdk): fix bugbear B028 add stacklevel by @kptkin in https://github.com/wandb/wandb/pull/4960
- style(launch): move launch errors closer to the code by @kptkin in https://github.com/wandb/wandb/pull/4995
- style(sdk): move mailbox error closer to the code by @kptkin in https://github.com/wandb/wandb/pull/4997
- style(sdk): add unsupported error type by @kptkin in https://github.com/wandb/wandb/pull/4999
- style(sdk): add support for the ruff linter by @moredatarequired in https://github.com/wandb/wandb/pull/4945
- refactor(sweeps): cosmetic changes for readability by @gtarpenning in https://github.com/wandb/wandb/pull/5021
- refactor(launch): introduce environment and registry abstract classes by @bcsherma in https://github.com/wandb/wandb/pull/4916
- style(launch): fix unused union type in launch agent by @KyleGoyette in https://github.com/wandb/wandb/pull/5041
- refactor(artifacts): remove the artifact from the manifest by @moredatarequired in https://github.com/wandb/wandb/pull/5049
- style(artifacts): enable typechecking for interface.artifacts and add type hints / casts by @moredatarequired in https://github.com/wandb/wandb/pull/5052
- style(sdk): type-annotate `wandb_setup.py` by @dmitryduev in https://github.com/wandb/wandb/pull/4824
- style(sdk): remove unused #noqa directives by @moredatarequired in https://github.com/wandb/wandb/pull/5058
- chore(sdk): disable sentry tracking when testing by @kptkin in https://github.com/wandb/wandb/pull/5019

## New Contributors

- @fdsig made their first contribution in https://github.com/wandb/wandb/pull/4984
- @mrb113 made their first contribution in https://github.com/wandb/wandb/pull/4967
- @parambharat made their first contribution in https://github.com/wandb/wandb/pull/5037

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.10...v0.13.11

## 0.13.10 (February 7, 2023)

### :magic_wand: Enhancements

- perf(artifacts): reuse session for file upload requests by @speezepearson in https://github.com/wandb/wandb/pull/4708
- feat(artifacts): expose aliases list endpoint for artifact collections by @ibindlish in https://github.com/wandb/wandb/pull/4809
- feat(launch): include the username of the run's author in the environment variables by @TimH98 in https://github.com/wandb/wandb/pull/4851
- feat(launch): add support for local-container resource args by @KyleGoyette in https://github.com/wandb/wandb/pull/4846
- feat(sdk): add the ability to append to a run with `wandb sync --append` by @raubitsj in https://github.com/wandb/wandb/pull/4848
- feat(launch): add an escape hatch (`disable_job_creation`) to disable automatic job creation by @KyleGoyette in https://github.com/wandb/wandb/pull/4901

### :hammer: Fixes

- fix(launch): remove underscores from generated job name in kubernetes runner by @TimH98 in https://github.com/wandb/wandb/pull/4752
- fix(sweeps): sweep command args can once again be int type by @gtarpenning in https://github.com/wandb/wandb/pull/4728
- fix(artifacts): ensure prepared artifacts have the `latest` alias by @moredatarequired in https://github.com/wandb/wandb/pull/4828
- fix(artifacts): catch FileNotFoundError and PermissionError during cache.cleanup() by @moredatarequired in https://github.com/wandb/wandb/pull/4868
- fix(sdk): fix order of python executable resolves by @kptkin in https://github.com/wandb/wandb/pull/4839
- fix(sdk): fix console handling when forking and setting stdout==stderr by @raubitsj in https://github.com/wandb/wandb/pull/4877
- fix(launch): Fix issue where job artifacts are being logged without latest alias by @KyleGoyette in https://github.com/wandb/wandb/pull/4884
- fix(launch): Ensure job names do not exceed maximum allowable for artifacts by @KyleGoyette in https://github.com/wandb/wandb/pull/4889

### :books: Docs

- docs(sdk): fix broken reference link to W&B Settings page in Sweeps by @ngrayluna in https://github.com/wandb/wandb/pull/4820
- docs(sdk): Docodoile autogen docs by @ngrayluna in https://github.com/wandb/wandb/pull/4734

### :gear: Dev

- test(artifacts): ensure manifest version is verified by @moredatarequired in https://github.com/wandb/wandb/pull/4691
- test(sdk): add tests for custom SSL certs and disabling SSL by @speezepearson in https://github.com/wandb/wandb/pull/4692
- test(sdk): fix nightly docker builds by @dmitryduev in https://github.com/wandb/wandb/pull/4787
- chore(sdk): dont create universal py2/py3 package by @raubitsj in https://github.com/wandb/wandb/pull/4797
- chore(sdk): fix flake8-bugbear B028 and ignore B017 by @kptkin in https://github.com/wandb/wandb/pull/4799
- test(sdk): fix gcloud sdk version requested in nightly tests by @dmitryduev in https://github.com/wandb/wandb/pull/4802
- chore(artifacts): remove unused parameters in StorageHandler.load\_{path,file,reference} by @moredatarequired in https://github.com/wandb/wandb/pull/4678
- chore(sdk): split unit tests to system tests and proper unit tests by @kptkin in https://github.com/wandb/wandb/pull/4811
- test(sdk): address fixture server move from port 9010 to 9015 in local-testcontainer by @dmitryduev in https://github.com/wandb/wandb/pull/4814
- chore(sdk): add aliases to ac query response by @ibindlish in https://github.com/wandb/wandb/pull/4813
- test(sdk): run regression suite nightly by @dmitryduev in https://github.com/wandb/wandb/pull/4788
- test(sdk): fix broken lightning test by @kptkin in https://github.com/wandb/wandb/pull/4823
- chore(sdk): enable type checking for wandb_init.py by @dmitryduev in https://github.com/wandb/wandb/pull/4784
- chore(launch): deprecate defaulting to default queue in launch-agent command by @gtarpenning in https://github.com/wandb/wandb/pull/4801
- test(launch): add unit test for kubernetes runner with annotations by @TimH98 in https://github.com/wandb/wandb/pull/4800
- test(integrations): fix train_gpu_ddp test by @dmitryduev in https://github.com/wandb/wandb/pull/4831
- chore(sdk): fix docker testimage to pull amd64 version by @raubitsj in https://github.com/wandb/wandb/pull/4838
- chore(sdk): fix codeowners after test restructure by @raubitsj in https://github.com/wandb/wandb/pull/4843
- test(sdk): fix md5 test failures on Windows by @moredatarequired in https://github.com/wandb/wandb/pull/4840
- chore(sdk): split out relay server so it can be shared with yea-wandb by @raubitsj in https://github.com/wandb/wandb/pull/4837
- chore(sdk): fix a flake8 complaint in a test by @speezepearson in https://github.com/wandb/wandb/pull/4806
- test(integrations): fix several import tests by @dmitryduev in https://github.com/wandb/wandb/pull/4849
- test(sdk): don't use symlinks for SSL test assets, because Windows by @speezepearson in https://github.com/wandb/wandb/pull/4847
- test(sdk): add unit tests for filesync.Stats by @speezepearson in https://github.com/wandb/wandb/pull/4855
- chore(sdk): add async retry logic by @speezepearson in https://github.com/wandb/wandb/pull/4738
- test(artifacts): strengthen tests for ArtifactSaver, StepUpload by @speezepearson in https://github.com/wandb/wandb/pull/4808
- chore(launch): Agent logs full stack trace when catching exception by @TimH98 in https://github.com/wandb/wandb/pull/4861
- chore(sdk): swallow warning printed by neuron-ls by @dmitryduev in https://github.com/wandb/wandb/pull/4835
- build(sdk): pin pip and tox in development environments by @moredatarequired in https://github.com/wandb/wandb/pull/4871

### :nail_care: Cleanup

- refactor(sdk): strengthen StepUpload tests; make exception-handling more thorough in upload/commit by @speezepearson in https://github.com/wandb/wandb/pull/4677
- refactor(artifacts): refactor Artifact query to fetch entity and project by @vwrj in https://github.com/wandb/wandb/pull/4775
- refactor(sdk): replace more communicate calls with deliver by @raubitsj in https://github.com/wandb/wandb/pull/4841
- refactor(artifacts): internally use Future to communicate success/failure of commit, not threading.Event by @speezepearson in https://github.com/wandb/wandb/pull/4859
- refactor(sdk): use stdlib ThreadPoolExecutor in StepUpload instead of managing our own by @speezepearson in https://github.com/wandb/wandb/pull/4860

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.9...v0.13.10

## 0.13.9 (January 11, 2023)

### :hammer: Fixes

- fix(sdk): exercise extra caution when checking if AWS Trainium is available in the system by @dmitryduev in https://github.com/wandb/wandb/pull/4769
- fix(sdk): restore 'util.generate_id' for legacy / user code by @moredatarequired in https://github.com/wandb/wandb/pull/4776
- fix(sdk): replace `release` with `abandon` when releasing mailbox handle during init by @kptkin in https://github.com/wandb/wandb/pull/4766

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.8...v0.13.9

## 0.13.8 (January 10, 2023)

### :magic_wand: Enhancements

- feat(artifacts): keep uncommitted uploads in separate staging area by @moredatarequired in https://github.com/wandb/wandb/pull/4505
- perf(sdk): improve file descriptor management by @dmitryduev in https://github.com/wandb/wandb/pull/4617
- feat(launch): default to using model-registry project for agent and launch_add by @KyleGoyette in https://github.com/wandb/wandb/pull/4613
- feat(sdk): add `exist_ok=False` to `file.download()` by @janosh in https://github.com/wandb/wandb/pull/4564
- feat(launch): auto create job artifacts from runs with required ingredients by @KyleGoyette in https://github.com/wandb/wandb/pull/4660
- feat(sdk): add generalized response injection pattern for tests by @kptkin in https://github.com/wandb/wandb/pull/4729
- perf(sdk): replace multiprocessing.Queue's with queue.Queue's by @dmitryduev in https://github.com/wandb/wandb/pull/4672
- feat(sdk): use transaction log to cap memory usage by @raubitsj in https://github.com/wandb/wandb/pull/4724
- feat(integrations): support system metrics for AWS Trainium by @dmitryduev in https://github.com/wandb/wandb/pull/4671

### :hammer: Fixes

- fix(sdk): correct the type hint for wandb.run by @edwag in https://github.com/wandb/wandb/pull/4585
- fix(sdk): resume collecting system metrics on object restart by @dmitryduev in https://github.com/wandb/wandb/pull/4572
- fix(launch): fix env handling and node_selector handling by @KyleGoyette in https://github.com/wandb/wandb/pull/4555
- fix(public-api): fix Job.call() using the wrong keyword (queue vs queue_name) when calling launch_add. by @TimH98 in https://github.com/wandb/wandb/pull/4625
- fix(sweeps): sweeps schedulers handles multi word parameters by @gtarpenning in https://github.com/wandb/wandb/pull/4640
- fix(launch): allow spaces in requirements file, remove duplicate wandb bootstrap file by @TimH98 in https://github.com/wandb/wandb/pull/4647
- fix(artifacts): correctly handle url-encoded local file references. by @moredatarequired in https://github.com/wandb/wandb/pull/4665
- fix(artifacts): get digest directly instead of from the manifests' manifest by @moredatarequired in https://github.com/wandb/wandb/pull/4681
- fix(artifacts): artifact.version should be the version index from the associated collection by @vwrj in https://github.com/wandb/wandb/pull/4486
- fix(sdk): remove duplicate generate_id functions, replace shortuuid with secrets by @moredatarequired in https://github.com/wandb/wandb/pull/4676
- fix(integrations): fix type check for jax.Array introduced in jax==0.4.1 by @dmitryduev in https://github.com/wandb/wandb/pull/4718
- fix(sdk): fix hang after failed wandb.init (add cancel) by @raubitsj in https://github.com/wandb/wandb/pull/4405
- fix(sdk): allow users to provide path to custom executables by @kptkin in https://github.com/wandb/wandb/pull/4604
- fix(sdk): fix TypeError when trying to slice a Paginator object by @janosh in https://github.com/wandb/wandb/pull/4575
- fix(integrations): add `AttributeError` to the list of handled exceptions when saving a keras model by @froody in https://github.com/wandb/wandb/pull/4732
- fix(launch): remove args from jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/4750

### :books: Docs

- docs(sweeps): fix typo in docs by @gtarpenning in https://github.com/wandb/wandb/pull/4627
- docs(sdk): fix typo in docstring for data_types.Objects3D by @ngrayluna in https://github.com/wandb/wandb/pull/4543
- docs(sdk): remove less than, greater than characters from dosctrings… by @ngrayluna in https://github.com/wandb/wandb/pull/4687
- docs(sdk): update SECURITY.md by @dmitryduev in https://github.com/wandb/wandb/pull/4616
- docs(sdk): Update README.md by @ngrayluna in https://github.com/wandb/wandb/pull/4468

### :gear: Dev

- test(sdk): update t2_fix_error_cond_feature_importances to install scikit-learn by @dmitryduev in https://github.com/wandb/wandb/pull/4573
- chore(sdk): update base Docker images for nightly testing by @dmitryduev in https://github.com/wandb/wandb/pull/4566
- chore(sdk): change sklearn to scikit-learn in functional sacred test by @dmitryduev in https://github.com/wandb/wandb/pull/4577
- chore(launch): add error check for `--build` when resource=local-process by @gtarpenning in https://github.com/wandb/wandb/pull/4513
- chore(sweeps): update scheduler and agent resource handling to allow DRC override by @gtarpenning in https://github.com/wandb/wandb/pull/4480
- chore(sdk): require sdk-team review for adding or removing high-level… by @dmitryduev in https://github.com/wandb/wandb/pull/4594
- chore(launch): remove requirement to make target project match queue by @KyleGoyette in https://github.com/wandb/wandb/pull/4612
- chore(sdk): enhance nightly cloud testing process by @dmitryduev in https://github.com/wandb/wandb/pull/4602
- chore(sdk): update pull request template by @raubitsj in https://github.com/wandb/wandb/pull/4633
- chore(launch): return updated runSpec after pushToRunQueue query by @gtarpenning in https://github.com/wandb/wandb/pull/4516
- chore(launch): fix for run spec handling in sdk by @gtarpenning in https://github.com/wandb/wandb/pull/4636
- chore(sdk): remove test dependency on old fastparquet package by @raubitsj in https://github.com/wandb/wandb/pull/4656
- test(artifacts): fix dtype np.float (does not exist), set to python float by @moredatarequired in https://github.com/wandb/wandb/pull/4661
- chore(sdk): correct 'exclude' to 'ignore-paths' in .pylintrc by @moredatarequired in https://github.com/wandb/wandb/pull/4659
- chore(sdk): use pytest tmp_path so we can inspect failures by @raubitsj in https://github.com/wandb/wandb/pull/4664
- chore(launch): reset build command after building by @gtarpenning in https://github.com/wandb/wandb/pull/4626
- ci(sdk): rerun flaking tests in CI with pytest-rerunfailures by @dmitryduev in https://github.com/wandb/wandb/pull/4430
- chore(sdk): remove dead code from filesync logic by @speezepearson in https://github.com/wandb/wandb/pull/4638
- chore(sdk): remove unused fields from a filesync message by @speezepearson in https://github.com/wandb/wandb/pull/4662
- chore(sdk): refactor retry logic to use globals instead of dependency-injecting them by @speezepearson in https://github.com/wandb/wandb/pull/4588
- test(sdk): add unit tests for filesync.StepUpload by @speezepearson in https://github.com/wandb/wandb/pull/4652
- test(sdk): add tests for Api.upload_file_retry by @speezepearson in https://github.com/wandb/wandb/pull/4639
- chore(launch): remove fallback resource when not specified for a queue by @gtarpenning in https://github.com/wandb/wandb/pull/4637
- test(artifacts): improve storage handler test coverage by @moredatarequired in https://github.com/wandb/wandb/pull/4674
- test(integrations): fix import tests by @dmitryduev in https://github.com/wandb/wandb/pull/4690
- chore(sdk): make MetricsMonitor less verbose on errors by @dmitryduev in https://github.com/wandb/wandb/pull/4618
- test(sdk): address fixture server move from port 9003 to 9010 in local-testcontainer by @dmitryduev in https://github.com/wandb/wandb/pull/4716
- chore(sdk): vendor promise==2.3.0 to unequivocally rm six dependency by @dmitryduev in https://github.com/wandb/wandb/pull/4622
- chore(artifacts): allow setting artifact cache dir in wandb.init(...) by @dmitryduev in https://github.com/wandb/wandb/pull/3644
- test(sdk): temporary lower network buffer for testing by @raubitsj in https://github.com/wandb/wandb/pull/4737
- chore(sdk): add telemetry if the user running in pex environment by @kptkin in https://github.com/wandb/wandb/pull/4747
- chore(sdk): add more flow control telemetry by @raubitsj in https://github.com/wandb/wandb/pull/4739
- chore(sdk): add settings and debug for service startup issues (wait_for_ports) by @raubitsj in https://github.com/wandb/wandb/pull/4749
- test(sdk): fix AWS Trainium test by @dmitryduev in https://github.com/wandb/wandb/pull/4753
- chore(sdk): fix status checker thread issue when user process exits without finish() by @raubitsj in https://github.com/wandb/wandb/pull/4761
- chore(sdk): add telemetry for service disabled usage by @kptkin in https://github.com/wandb/wandb/pull/4762

### :nail_care: Cleanup

- style(sdk): use the same syntax whenever raising exceptions by @moredatarequired in https://github.com/wandb/wandb/pull/4559
- refactor(sdk): combine \_safe_mkdirs with mkdir_exist_ok by @moredatarequired in https://github.com/wandb/wandb/pull/4650
- refactor(artifacts): use a pytest fixture for the artifact cache by @moredatarequired in https://github.com/wandb/wandb/pull/4648
- refactor(artifacts): use ArtifactEntry directly instead of subclassing by @moredatarequired in https://github.com/wandb/wandb/pull/4649
- refactor(artifacts): consolidate hash utilities into lib.hashutil by @moredatarequired in https://github.com/wandb/wandb/pull/4525
- style(public-api): format public file with proper formatting by @kptkin in https://github.com/wandb/wandb/pull/4697
- chore(sdk): install tox into proper env in dev env setup tool by @dmitryduev in https://github.com/wandb/wandb/pull/4318
- refactor(sdk): clean up the init and run logic by @kptkin in https://github.com/wandb/wandb/pull/4730

## New Contributors

- @edwag made their first contribution in https://github.com/wandb/wandb/pull/4585
- @TimH98 made their first contribution in https://github.com/wandb/wandb/pull/4625
- @froody made their first contribution in https://github.com/wandb/wandb/pull/4732

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.7...v0.13.8

## 0.13.7 (December 14, 2022)

### :hammer: Fixes

- revert(artifacts): revert `Circular reference detected` change to resolve `Object of type Tensor is not JSON serializable` by @raubitsj in https://github.com/wandb/wandb/pull/4629

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.6...v0.13.7

## 0.13.6 (December 6, 2022)

### :magic_wand: Enhancements

- feat(sweeps): add `Sweep.expected_run_count` to public Api by @gtarpenning in https://github.com/wandb/wandb/pull/4434
- feat(launch): support volume mounts and security contexts in kubernetes runner by @KyleGoyette in https://github.com/wandb/wandb/pull/4475
- feat(launch): add a new `--build` flag for building and then pushing the image to a queue by @gtarpenning in https://github.com/wandb/wandb/pull/4061
- feat(integrations): add ability to log learning rate using WandbMetricsLogger by @soumik12345 in https://github.com/wandb/wandb/pull/4391
- feat(sdk): improve Report API in preparation for GA by @andrewtruong in https://github.com/wandb/wandb/pull/4499

### :hammer: Fixes

- fix(artifacts): add filter for `artifact_version` to only retrieve committed artifacts by @estellazx in https://github.com/wandb/wandb/pull/4401
- fix(cli): deflake `wandb verify` by @vanpelt in https://github.com/wandb/wandb/pull/4438
- fix(launch): fix the type of the override args passed through to a LaunchProject from a Job by @KyleGoyette in https://github.com/wandb/wandb/pull/4416
- fix(launch): remove extra colon from log prefix by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4450
- fix(sdk): add support for service running in a pex based environment by @kptkin in https://github.com/wandb/wandb/pull/4440
- fix(sdk): fix probing static IPU info by @dmitryduev in https://github.com/wandb/wandb/pull/4464
- fix(public-api): change `artifactSequence` to `artifactCollection` in public GQL requests by @tssweeney in https://github.com/wandb/wandb/pull/4531
- fix(integrations): fix TF compatibility issues with `WandbModelCheckpoint` by @soumik12345 in https://github.com/wandb/wandb/pull/4432
- fix(integrations): make Keras WandbCallback compatible with TF version >= 2.11.0 by @ayulockin in https://github.com/wandb/wandb/pull/4533
- fix(integrations): update gym integration to match last version by @younik in https://github.com/wandb/wandb/pull/4571
- fix(sdk): harden internal thread management in SystemMetrics by @dmitryduev in https://github.com/wandb/wandb/pull/4439

### :books: Docs

- docs(sdk): remove non-existent argument `table_key` from `plot_table()` doc string by @janosh in https://github.com/wandb/wandb/pull/4495
- docs(artifacts): correct parameter name in docstring example by @ngrayluna in https://github.com/wandb/wandb/pull/4528

### :gear: Dev

- chore(launch): improved git fetch time by specifying a `refspec` and `depth=1` by @gtarpenning in https://github.com/wandb/wandb/pull/4459
- chore(sdk): fix linguist rule to ignore grpc generated files by @raubitsj in https://github.com/wandb/wandb/pull/4470
- chore(launch): new shard for launch tests by @gtarpenning in https://github.com/wandb/wandb/pull/4427
- chore(public-api): upgrade Node 12 based GitHub Actions by @moredatarequired in https://github.com/wandb/wandb/pull/4506
- test(artifacts): skip flaky `artifact_metadata_save` test by @speezepearson in https://github.com/wandb/wandb/pull/4463
- test(artifacts): replace sleeps with flush when waiting on a file to write by @moredatarequired in https://github.com/wandb/wandb/pull/4523
- test(artifacts): use `tmp_path` fixture instead of writing local files during tests by @moredatarequired in https://github.com/wandb/wandb/pull/4521
- chore(launch): fix broken queue test by @gtarpenning in https://github.com/wandb/wandb/pull/4548
- test(artifacts): `skip` instead of `xfail` for test `test_artifact_metadata_save` by @speezepearson in https://github.com/wandb/wandb/pull/4550
- test(sdk): add many tests for InternalApi.upload_file by @speezepearson in https://github.com/wandb/wandb/pull/4539
- chore(artifacts): add artifact Sequence fallback for older servers by @tssweeney in https://github.com/wandb/wandb/pull/4565
- test(sdk): make protobuf version requirements more granular by @dmitryduev in https://github.com/wandb/wandb/pull/4479

### :nail_care: Cleanup

- fix(artifacts): when committing artifacts, don't retry 409 Conflict errors by @speezepearson in https://github.com/wandb/wandb/pull/4260
- refactor(artifacts): add programmatic alias addition/removal from SDK on artifacts by @vwrj in https://github.com/wandb/wandb/pull/4429
- fix(integrations): remove `wandb.sklearn.plot_decision_boundaries` that contains dead logic by @kptkin in https://github.com/wandb/wandb/pull/4348
- chore(sdk): adds an option to force pull the latest version of a test dev-container image by @kptkin in https://github.com/wandb/wandb/pull/4352
- feat(launch): noop builder by @KyleGoyette in https://github.com/wandb/wandb/pull/4275
- refactor(launch): remove unused attribute by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4497
- style(sdk): update `mypy` to 0.991 by @dmitryduev in https://github.com/wandb/wandb/pull/4546
- refactor(launch): add more robust uri parsing by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4498
- style(sdk): turn on linting for internal_api.py by @speezepearson in https://github.com/wandb/wandb/pull/4545
- build(sdk): remove dependency on six by modifying vendored libs by @dmitryduev in https://github.com/wandb/wandb/pull/4280

## New Contributors

- @moredatarequired made their first contribution in https://github.com/wandb/wandb/pull/4508
- @soumik12345 made their first contribution in https://github.com/wandb/wandb/pull/4391
- @younik made their first contribution in https://github.com/wandb/wandb/pull/4571

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.5...v0.13.6

## 0.13.5 (November 3, 2022)

### :magic_wand: Enhancements

- feat(artifacts): add an option to upload image references by @estellazx in https://github.com/wandb/wandb/pull/4303

### :hammer: Fixes

- fix(launch): generate more readable image names by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4379
- fix(artifacts): use hash(`etag`+`url`) instead of just `etag`, as key, in artifacts cache by @speezepearson in https://github.com/wandb/wandb/pull/4371
- fix(artifacts): wait for artifact to commit before telling the user it's ready when using `wandb artifact put` by @speezepearson in https://github.com/wandb/wandb/pull/4381
- fix(sdk): prefix vendor watchdog library by @raubitsj in https://github.com/wandb/wandb/pull/4389
- fix(artifacts): fix `Circular reference detected` error, when updating metadata with numpy array longer than 32 elements by @estellazx in https://github.com/wandb/wandb/pull/4221
- fix(integrations): add a random string to run_id on SageMaker not to break DDP mode by @dmitryduev in https://github.com/wandb/wandb/pull/4276

### :gear: Dev

- ci(sdk): make sure we dont shutdown test cluster before grabbing results by @raubitsj in https://github.com/wandb/wandb/pull/4361
- test(artifacts): add standalone artifact test to nightly cpu suite by @raubitsj in https://github.com/wandb/wandb/pull/4360
- chore(sdk): rename default branch to `main` by @raubitsj in https://github.com/wandb/wandb/pull/4374
- build(sdk): update mypy extension for protobuf type checking by @dmitryduev in https://github.com/wandb/wandb/pull/4392
- chore(sdk): update codeql-analysis.yml branch name by @zythosec in https://github.com/wandb/wandb/pull/4393
- ci(sdk): move functional import tests to nightly and expand python version coverage by @dmitryduev in https://github.com/wandb/wandb/pull/4395
- ci(sdk): add Slack notification for failed nightly import tests by @dmitryduev in https://github.com/wandb/wandb/pull/4403
- test(cli): fix broken CLI tests that attempt uploading non-existent artifacts by @dmitryduev in https://github.com/wandb/wandb/pull/4426

### :nail_care: Cleanup

- fix(launch): job creation through use_artifact instead of log_artifact by @KyleGoyette in https://github.com/wandb/wandb/pull/4337
- ci(sdk): add a GH action to automate parts of the release process by @dmitryduev in https://github.com/wandb/wandb/pull/4355
- fix(media): 3D Point Clouds now viewable in UI in all situations by @ssisk in https://github.com/wandb/wandb/pull/4353
- fix(launch): Git URLs were failing if fsmonitor is enabled by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4333
- style(sdk): ignore new proto generated file directories by @raubitsj in https://github.com/wandb/wandb/pull/4354
- chore(launch): fix a bug preventing Run Queue deletion in the SDK by @gtarpenning in https://github.com/wandb/wandb/pull/4321
- chore(launch): add support for `pushToRunQueueByName` mutation by @gtarpenning in https://github.com/wandb/wandb/pull/4292
- refactor(sdk): refactor system metrics monitoring and probing by @dmitryduev in https://github.com/wandb/wandb/pull/4213
- style(sdk): fix gitattribute for protobuf generated files by @raubitsj in https://github.com/wandb/wandb/pull/4400

## New Contributors

- @ssisk made their first contribution in https://github.com/wandb/wandb/pull/4353

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.4...v0.13.5

## 0.13.4 (October 5, 2022)

### :magic_wand: Enhancements

- feat(launch): show entity and project in k8s job names by @KyleGoyette in https://github.com/wandb/wandb/pull/4216
- feat(sweeps): add environment variable sweep command macro by @hu-po in https://github.com/wandb/wandb/pull/4200
- feat(media): add `from_*` constructors and scene camera and bounding box confidence scores to `Object3D` data type by @dmitryduev in https://github.com/wandb/wandb/pull/4319
- feat(artifacts): add simple progress indicator for artifact downloads by @speezepearson in https://github.com/wandb/wandb/pull/4255
- feat(integrations): add `WandbMetricsLogger` callback - a `Keras` dedicated metrics logger callback by @ayulockin in https://github.com/wandb/wandb/pull/4244
- feat(integrations): add `WandbModelCheckpoint` callback - a `Keras` model checkpointing callback by @ayulockin in https://github.com/wandb/wandb/pull/4245
- feat(integrations): add `WandbEvalCallback` callback - a `Keras` callback for logging model predictions as W&B tables by @ayulockin in https://github.com/wandb/wandb/pull/4302

### :hammer: Fixes

- fix(launch): cast agent's config max_jobs attribute to integer by @KyleGoyette in https://github.com/wandb/wandb/pull/4262
- fix(cli): correct the displayed path to the `debug-cli.log` (debug log) by @jamie-rasmussen in https://github.com/wandb/wandb/pull/4271
- fix(artifacts): catch retry-able request timeout when uploading artifacts to AWS by @nickpenaranda in https://github.com/wandb/wandb/pull/4304
- fix(sdk): improve user feedback for long running calls: summary, finish by @raubitsj in https://github.com/wandb/wandb/pull/4169
- fix(integrations): fix RuntimeError when using `keras.WandbCallback` with `tf.MirroredStrategy` by @ayulockin in https://github.com/wandb/wandb/pull/4310

### :gear: Dev

- ci(sdk): add code analysis/scanning with `codeql` by @dmitryduev in https://github.com/wandb/wandb/pull/4250
- ci(sdk): validate PR titles to ensure compliance with Conventional Commits guidelines by @dmitryduev in https://github.com/wandb/wandb/pull/4268
- chore(launch): harden launch by pining the build versions of `kaniko` and `launch-agent-dev` by @KyleGoyette in https://github.com/wandb/wandb/pull/4194
- test(sdk): add telemetry for the `mmengine` package by @manangoel99 in https://github.com/wandb/wandb/pull/4273
- chore(sdk): add the `build` type to our conventional commits setup by @dmitryduev in https://github.com/wandb/wandb/pull/4282
- test(sdk): add `tensorflow_datasets` requirement to `imports12` shard by @dmitryduev in https://github.com/wandb/wandb/pull/4316
- test(integrations): fix sb3 test by pinning upstream requirement by @dmitryduev in https://github.com/wandb/wandb/pull/4346
- build(sdk): make the SDK compatible with protobuf v4 by @dmitryduev in https://github.com/wandb/wandb/pull/4279
- chore(sdk): fix flake8 output coloring by @dmitryduev in https://github.com/wandb/wandb/pull/4347
- test(artifacts): fix artifact reference test asset directory by @raubitsj in https://github.com/wandb/wandb/pull/4350

### :nail_care: Cleanup

- style(sdk): fix type hint for `filters` argument in `public_api.runs` by @epwalsh in https://github.com/wandb/wandb/pull/4256
- style(artifacts): improve type annotations around artifact-file-creation by @speezepearson in https://github.com/wandb/wandb/pull/4259
- style(sdk): improve type annotations and VSCode config for public API by @speezepearson in https://github.com/wandb/wandb/pull/4252
- style(sdk): make type annotations more easily navigable in VSCode by @speezepearson in https://github.com/wandb/wandb/pull/4005
- style(artifacts): introduce str NewTypes and use them for various Artifact fields by @speezepearson in https://github.com/wandb/wandb/pull/4326
- style(artifacts): add type annotations to get better IDE hints for boto3 usage by @speezepearson in https://github.com/wandb/wandb/pull/4338

## New Contributors

- @epwalsh made their first contribution in https://github.com/wandb/wandb/pull/4256
- @mjvanderboon made their first contribution in https://github.com/wandb/wandb/pull/4309
- @jamie-rasmussen made their first contribution in https://github.com/wandb/wandb/pull/4271
- @nickpenaranda made their first contribution in https://github.com/wandb/wandb/pull/4304

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.3...v0.13.4

## 0.13.3 (September 8, 2022)

#### :nail_care: Enhancement

- Adds `raytune` examples / tests by @raubitsj in https://github.com/wandb/wandb/pull/4053
- Refactors `pytest` unit tests to run against real `wandb server` by @kptkin in https://github.com/wandb/wandb/pull/4066
- Adds Launch `kubernetes` support of taints and tolerations by @KyleGoyette in https://github.com/wandb/wandb/pull/4086
- Adds Sweeps on Launch on Kubernetes by @hu-po in https://github.com/wandb/wandb/pull/4035
- Adds parallelism to functional testing by @raubitsj in https://github.com/wandb/wandb/pull/4096
- Upgrades `mypy` to version `0.971` by @dmitryduev in https://github.com/wandb/wandb/pull/3952
- Adds Mailbox async internal process communication by @raubitsj in https://github.com/wandb/wandb/pull/3568
- Implements searching launch job in sweep config by @hu-po in https://github.com/wandb/wandb/pull/4120
- Improves performance when sending large messages by @raubitsj in https://github.com/wandb/wandb/pull/4119
- Vendors the latest `nvidia-ml-py-11.515.48` by @dmitryduev in https://github.com/wandb/wandb/pull/4109
- Improves performance by increase recv size on service socket by @raubitsj in https://github.com/wandb/wandb/pull/4122
- Adds isort support with black profile by @kptkin in https://github.com/wandb/wandb/pull/4136
- Implements pushing test-results to CircleCI for nightly tests by @raubitsj in https://github.com/wandb/wandb/pull/4153
- Adds debug mode for `pytest` unit tests by @dmitryduev in https://github.com/wandb/wandb/pull/4145
- Adds support for arguments in Launch Jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/4129
- Adds FetchRunQueueItemById query by @gtarpenning in https://github.com/wandb/wandb/pull/4106
- Adds telemetry for keras-cv by @manangoel99 in https://github.com/wandb/wandb/pull/4196
- Adds sentry session tracking by @raubitsj in https://github.com/wandb/wandb/pull/4157
- Adds the ability to log artifact while linking to registered model by @ibindlish in https://github.com/wandb/wandb/pull/4233

#### :broom: Cleanup

- Breaks gradient and parameters hooks by @kptkin in https://github.com/wandb/wandb/pull/3509
- Adds explicit error message for double uri/docker-image by @gtarpenning in https://github.com/wandb/wandb/pull/4069
- Tests that the wandb_init fixture args are in sync with wandb.init() by @dmitryduev in https://github.com/wandb/wandb/pull/4079
- Upgrades the GKE cluster used for nightly tests to `n1-standard-8` by @dmitryduev in https://github.com/wandb/wandb/pull/4065
- Moves service teardown to the end of tests by @kptkin in https://github.com/wandb/wandb/pull/4083
- Reduce the `pytest` job parallelism from 10 to 6 by @kptkin in https://github.com/wandb/wandb/pull/4085
- Removes service user doc by @kptkin in https://github.com/wandb/wandb/pull/4088
- Move `_timestamp` logic to the internal process by @kptkin in https://github.com/wandb/wandb/pull/4087
- Adds Launch `gitversion` error message by @gtarpenning in https://github.com/wandb/wandb/pull/4028
- Updates KFP machine VM image in CircleCI by @dmitryduev in https://github.com/wandb/wandb/pull/4094
- Upgrades sweeps to latest version by @hu-po in https://github.com/wandb/wandb/pull/4104
- Implements Sweep scheduler cleanup and better tests by @hu-po in https://github.com/wandb/wandb/pull/4100
- Adds a requirement for the sdk-team to approve API changes by @raubitsj in https://github.com/wandb/wandb/pull/4128
- Adds additional time for artifact commit by @raubitsj in https://github.com/wandb/wandb/pull/4133
- Implements tox configuration with dynamic resolution by @kptkin in https://github.com/wandb/wandb/pull/4138
- Removes `buildx` version pin for nightly builds by @dmitryduev in https://github.com/wandb/wandb/pull/4144
- Moves Launch run configs from entrypoint into params by @hu-po in https://github.com/wandb/wandb/pull/4164
- Removes Slack orb usage from Win job on CircleCI by @dmitryduev in https://github.com/wandb/wandb/pull/4171
- Adds heartbeat parsing for Launch run args using legacy agent by @hu-po in https://github.com/wandb/wandb/pull/4180
- Add better error handling when tearing down service by @kptkin in https://github.com/wandb/wandb/pull/4161
- Cleans up Launch job creation pipeline by @KyleGoyette in https://github.com/wandb/wandb/pull/4183
- Adds detail to error message when uploading an artifact with the wrong type by @speezepearson in https://github.com/wandb/wandb/pull/4184
- Adds optional timeout parameter to artifacts wait() by @estellazx in https://github.com/wandb/wandb/pull/4181
- Sanitizes numpy generics in keys by @raubitsj in https://github.com/wandb/wandb/pull/4146
- Removes reassignment of run function in public api by @martinabeleda in https://github.com/wandb/wandb/pull/4115
- Makes pulling sweeps optional when using public api to query for runs by @kptkin in https://github.com/wandb/wandb/pull/4186
- Updates ref docs for `wandb.init` to give more info on special characters by @scottire in https://github.com/wandb/wandb/pull/4191

#### :bug: Bug Fix

- Fixes Sweeps on Launch Jobs requirement by @hu-po in https://github.com/wandb/wandb/pull/3947
- Fixes Artifact metadata JSON-encoding to accept more types by @speezepearson in https://github.com/wandb/wandb/pull/4038
- Adjusts `root_dir` setting processing logic by @dmitryduev in https://github.com/wandb/wandb/pull/4049
- Prevents run.log() from mutating passed in arguments by @kptkin in https://github.com/wandb/wandb/pull/4058
- Fixes `05-batch5.py` test by @dmitryduev in https://github.com/wandb/wandb/pull/4074
- Allows users to control the `run_id` through the launch spec by @gtarpenning in https://github.com/wandb/wandb/pull/4070
- Fixes accidental overwrite in `config.yml` by @dmitryduev in https://github.com/wandb/wandb/pull/4081
- Ensures propagating overridden `base_url` when initializing public API by @dmitryduev in https://github.com/wandb/wandb/pull/4026
- Fixes Sweeps on Launch CLI launch config, relpath by @hu-po in https://github.com/wandb/wandb/pull/4073
- Fixes broken Launch apikey error message by @gtarpenning in https://github.com/wandb/wandb/pull/4071
- Marks flakey sweeps test xfail by @hu-po in https://github.com/wandb/wandb/pull/4095
- Fixes Launch `gitversion` error message by @gtarpenning in https://github.com/wandb/wandb/pull/4103
- Fixes `yea-wandb` dev release -> release by @raubitsj in https://github.com/wandb/wandb/pull/4098
- Cleans up outstanding issues after the client->wandb rename by @kptkin in https://github.com/wandb/wandb/pull/4105
- Fixes test precision recall by @kptkin in https://github.com/wandb/wandb/pull/4108
- Fixes functional sklearn test by @raubitsj in https://github.com/wandb/wandb/pull/4107
- Fixes hang caused by keyboard interrupt on windows by @kptkin in https://github.com/wandb/wandb/pull/4116
- Fixes default test container tag by @kptkin in https://github.com/wandb/wandb/pull/4137
- Fixes summary handling in conftest.py by @dmitryduev in https://github.com/wandb/wandb/pull/4140
- Fixes some small typos in cli output by @lukas in https://github.com/wandb/wandb/pull/4126
- Fixes issue triggered by colab update by using default file and catching exceptions by @raubitsj in https://github.com/wandb/wandb/pull/4156
- Fixes mailbox locking issue by @raubitsj in https://github.com/wandb/wandb/pull/4214
- Fixes variable inclusion in log string by @klieret in https://github.com/wandb/wandb/pull/4219
- Corrects `wandb.Artifacts.artifact.version` attribute by @ngrayluna in https://github.com/wandb/wandb/pull/4199
- Fixes piping of docker args by Launch Agent by @KyleGoyette in https://github.com/wandb/wandb/pull/4215
- Fixes RecursionError when printing public API User object without email fetched by @speezepearson in https://github.com/wandb/wandb/pull/4193
- Fixes deserialization of numeric column names by @tssweeney in https://github.com/wandb/wandb/pull/4241

## New Contributors

- @gtarpenning made their first contribution in https://github.com/wandb/wandb/pull/4069
- @estellazx made their first contribution in https://github.com/wandb/wandb/pull/4181
- @klieret made their first contribution in https://github.com/wandb/wandb/pull/4219
- @ngrayluna made their first contribution in https://github.com/wandb/wandb/pull/4199
- @martinabeleda made their first contribution in https://github.com/wandb/wandb/pull/4115
- @ibindlish made their first contribution in https://github.com/wandb/wandb/pull/4233
- @scottire made their first contribution in https://github.com/wandb/wandb/pull/4191

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.2...v0.13.3

## 0.13.2 (August 22, 2022)

#### :bug: Bug Fix

- Fix issue triggered by colab update by using default file and catching exceptions by @raubitsj in https://github.com/wandb/wandb/pull/4156

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.1...v0.13.2

## 0.13.1 (August 5, 2022)

#### :bug: Bug Fix

- Prevents run.log() from mutating passed in arguments by @kptkin in https://github.com/wandb/wandb/pull/4058

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.0...v0.13.1

## 0.13.0 (August 4, 2022)

#### :nail_care: Enhancement

- Turns service on by default by @kptkin in https://github.com/wandb/wandb/pull/3895
- Adds support logic for handling server provided messages by @kptkin in https://github.com/wandb/wandb/pull/3706
- Allows runs to produce jobs on finish by @KyleGoyette in https://github.com/wandb/wandb/pull/3810
- Adds Job, QueuedRun and job handling in launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3809
- Supports in launch agent of instance roles in ec2 and eks by @KyleGoyette in https://github.com/wandb/wandb/pull/3596
- Adds default behavior to the Keras Callback: always save model checkpoints as artifacts by @vwrj in https://github.com/wandb/wandb/pull/3909
- Sanitizes the artifact name in the KerasCallback for model artifact saving by @vwrj in https://github.com/wandb/wandb/pull/3927
- Improves console logging by moving emulator to the service process by @raubitsj in https://github.com/wandb/wandb/pull/3828
- Fixes data corruption issue when logging large sizes of data by @kptkin in https://github.com/wandb/wandb/pull/3920
- Adds the state to the Sweep repr in the Public API by @hu-po in https://github.com/wandb/wandb/pull/3948
- Adds an option to specify different root dir for git using settings or environment variables by @bcsherma in https://github.com/wandb/wandb/pull/3250
- Adds an option to pass `remote url` and `commit hash` as arguments to settings or as environment variables by @kptkin in https://github.com/wandb/wandb/pull/3934
- Improves time resolution for tracked metrics and for system metrics by @raubitsj in https://github.com/wandb/wandb/pull/3918
- Defaults to project name from the sweep config when project is not specified in the `wandb.sweep()` call by @hu-po in https://github.com/wandb/wandb/pull/3919
- Adds support to use namespace set user by the the launch agent by @KyleGoyette in https://github.com/wandb/wandb/pull/3950
- Adds telemetry to track when a run might be overwritten by @raubitsj in https://github.com/wandb/wandb/pull/3998
- Adds a tool to export `wandb`'s history into `sqlite` by @raubitsj in https://github.com/wandb/wandb/pull/3999
- Replaces some `Mapping[str, ...]` types with `NamedTuples` by @speezepearson in https://github.com/wandb/wandb/pull/3996
- Adds import hook for run telemetry by @kptkin in https://github.com/wandb/wandb/pull/3988
- Implements profiling support for IPUs by @cameron-martin in https://github.com/wandb/wandb/pull/3897

#### :bug: Bug Fix

- Fixes sweep agent with service by @raubitsj in https://github.com/wandb/wandb/pull/3899
- Fixes an empty type equals invalid type and how artifact dictionaries are handled by @KyleGoyette in https://github.com/wandb/wandb/pull/3904
- Fixes `wandb.Config` object to support default values when getting an attribute by @farizrahman4u in https://github.com/wandb/wandb/pull/3820
- Removes default config from jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/3973
- Fixes an issue where patch is `None` by @KyleGoyette in https://github.com/wandb/wandb/pull/4003
- Fixes requirements.txt parsing in nightly SDK installation checks by @dmitryduev in https://github.com/wandb/wandb/pull/4012
- Fixes 409 Conflict handling when GraphQL requests timeout by @raubitsj in https://github.com/wandb/wandb/pull/4000
- Fixes service teardown handling if user process has been terminated by @raubitsj in https://github.com/wandb/wandb/pull/4024
- Adds `storage_path` and fixed `artifact.files` by @vanpelt in https://github.com/wandb/wandb/pull/3969
- Fixes performance issue syncing runs with a large number of media files by @vanpelt in https://github.com/wandb/wandb/pull/3941

#### :broom: Cleanup

- Adds an escape hatch logic to disable service by @kptkin in https://github.com/wandb/wandb/pull/3829
- Annotates `wandb/docker` and reverts change in the docker fixture by @dmitryduev in https://github.com/wandb/wandb/pull/3871
- Fixes GFLOPS to GFLOPs in the Keras `WandbCallback` by @ayulockin in https://github.com/wandb/wandb/pull/3913
- Adds type-annotate for `file_stream.py` by @dmitryduev in https://github.com/wandb/wandb/pull/3907
- Renames repository from `client` to `wandb` by @dmitryduev in https://github.com/wandb/wandb/pull/3977
- Updates documentation: adding `--report_to wandb` for HuggingFace Trainer by @ayulockin in https://github.com/wandb/wandb/pull/3959
- Makes aliases optional in link_artifact by @vwrj in https://github.com/wandb/wandb/pull/3986
- Renames `wandb local` to `wandb server` by @jsbroks in https://github.com/wandb/wandb/pull/3793
- Updates README badges by @raubitsj in https://github.com/wandb/wandb/pull/4023

## New Contributors

- @bcsherma made their first contribution in https://github.com/wandb/wandb/pull/3250
- @cameron-martin made their first contribution in https://github.com/wandb/wandb/pull/3897

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.21...v0.13.0

## 0.12.21 (July 5, 2022)

#### :nail_care: Enhancement

- Fixes config not showing up until the run finish by @KyleGoyette in https://github.com/wandb/wandb/pull/3734
- Adds new types to the TypeRegistry to handling artifact objects in jobs and run configs by @KyleGoyette in https://github.com/wandb/wandb/pull/3806
- Adds new query to the the internal api getting the state of the run by @hu-po in https://github.com/wandb/wandb/pull/3799
- Replaces unsafe yaml loaders with yaml.safe_load by @zythosec in https://github.com/wandb/wandb/pull/3753
- Improves testing tooling by allowing to specify shards in manual testing by @dmitryduev in https://github.com/wandb/wandb/pull/3826
- Fixes ROC and PR curves in the sklearn integration by stratifying sampling by @tylerganter in https://github.com/wandb/wandb/pull/3757
- Fixes input box in notebooks exceeding cell space by @dmitryduev in https://github.com/wandb/wandb/pull/3849
- Allows string to be passed as alias to link_model by @tssweeney in https://github.com/wandb/wandb/pull/3834
- Adds Support for FLOPS Calculation in `keras`'s `WandbCallback` by @dmitryduev in https://github.com/wandb/wandb/pull/3869
- Extends python report editing by @andrewtruong in https://github.com/wandb/wandb/pull/3732

#### :bug: Bug Fix

- Fixes stats logger so it can find all the correct GPUs in child processes by @raubitsj in https://github.com/wandb/wandb/pull/3727
- Fixes regression in s3 reference upload for folders by @jlzhao27 in https://github.com/wandb/wandb/pull/3825
- Fixes artifact commit logic to handle collision in the backend by @speezepearson in https://github.com/wandb/wandb/pull/3843
- Checks for `None` response in the retry logic (safety check) by @raubitsj in https://github.com/wandb/wandb/pull/3863
- Adds sweeps on top of launch (currently in MVP) by @hu-po in https://github.com/wandb/wandb/pull/3669
- Renames functional tests dir and files by @raubitsj in https://github.com/wandb/wandb/pull/3879

#### :broom: Cleanup

- Fixes conditions order of `_to_dict` helper by @dmitryduev in https://github.com/wandb/wandb/pull/3772
- Fixes changelog broken link to PR 3709 by @janosh in https://github.com/wandb/wandb/pull/3786
- Fixes public api query (QueuedJob Api ) by @KyleGoyette in https://github.com/wandb/wandb/pull/3798
- Renames local runners to local-container and local-process by @hu-po in https://github.com/wandb/wandb/pull/3800
- Adds type annotations to files in the wandb/filesync directory by @speezepearson in https://github.com/wandb/wandb/pull/3774
- Re-organizes all the testing directories to have common root dir by @dmitryduev in https://github.com/wandb/wandb/pull/3740
- Fixes testing configuration and add bigger machine on `CircleCi` by @dmitryduev in https://github.com/wandb/wandb/pull/3836
- Fixes typo in the `wandb-service-user` readme file by @Co1lin in https://github.com/wandb/wandb/pull/3847
- Fixes broken artifact test for regression by @dmitryduev in https://github.com/wandb/wandb/pull/3857
- Removes unused files (relating to `py27`) and empty `submodules` declaration by @dmitryduev in https://github.com/wandb/wandb/pull/3850
- Adds extra for model reg dependency on cloudpickle by @tssweeney in https://github.com/wandb/wandb/pull/3866
- Replaces deprecated threading aliases by @hugovk in https://github.com/wandb/wandb/pull/3794
- Updates the `sdk` readme to the renamed (local -> server) commands by @sephmard in https://github.com/wandb/wandb/pull/3771

## New Contributors

- @janosh made their first contribution in https://github.com/wandb/wandb/pull/3786
- @Co1lin made their first contribution in https://github.com/wandb/wandb/pull/3847
- @tylerganter made their first contribution in https://github.com/wandb/wandb/pull/3757

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.20...v0.12.21

## 0.12.20 (June 29, 2022)

#### :bug: Bug Fix

- Retry `commit_artifact` on conflict-error by @speezepearson in https://github.com/wandb/wandb/pull/3843

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.19...v0.12.20

## 0.12.19 (June 22, 2022)

#### :bug: Bug Fix

- Fix regression in s3 reference upload for folders by @jlzhao27 in https://github.com/wandb/wandb/pull/3825

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.18...v0.12.19

## 0.12.18 (June 9, 2022)

#### :nail_care: Enhancement

- Launch: BareRunner based on LocalRunner by @hu-po in https://github.com/wandb/wandb/pull/3577
- Add ability to specify api key to public api by @dannygoldstein in https://github.com/wandb/wandb/pull/3657
- Add support in artifacts for files with unicode on windows by @kptkin in https://github.com/wandb/wandb/pull/3650
- Added telemetry for new packages by @manangoel99 in https://github.com/wandb/wandb/pull/3713
- Improve API key management by @vanpelt in https://github.com/wandb/wandb/pull/3718
- Add information about `wandb server` during login by @raubitsj in https://github.com/wandb/wandb/pull/3754

#### :bug: Bug Fix

- fix(weave): Natively support timestamps in Python Table Types by @dannygoldstein in https://github.com/wandb/wandb/pull/3606
- Add support for magic with service by @kptkin in https://github.com/wandb/wandb/pull/3623
- Add unit tests for DirWatcher and supporting classes by @speezepearson in https://github.com/wandb/wandb/pull/3589
- Improve `DirWatcher.update_policy` O(1) instead of O(num files uploaded) by @speezepearson in https://github.com/wandb/wandb/pull/3613
- Add argument to control what to log in SB3 callback by @astariul in https://github.com/wandb/wandb/pull/3643
- Improve parameter naming in sb3 integration by @dmitryduev in https://github.com/wandb/wandb/pull/3647
- Adjust the requirements for the dev environment setup on an M1 Mac by @dmitryduev in https://github.com/wandb/wandb/pull/3627
- Launch: Fix NVIDIA base image Linux keys by @KyleGoyette in https://github.com/wandb/wandb/pull/3637
- Fix launch run queue handling from config file by @KyleGoyette in https://github.com/wandb/wandb/pull/3636
- Fix issue where tfevents were not always consumed by @minyoung in https://github.com/wandb/wandb/pull/3673
- [Snyk] Fix for 8 vulnerabilities by @snyk-bot in https://github.com/wandb/wandb/pull/3695
- Fix s3 storage handler to upload folders when key names collide by @jlzhao27 in https://github.com/wandb/wandb/pull/3699
- Correctly load timestamps from tables in artifacts by @dannygoldstein in https://github.com/wandb/wandb/pull/3691
- Require `protobuf<4` by @dmitryduev in https://github.com/wandb/wandb/pull/3709
- Make Containers created through launch re-runnable as container jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/3642
- Fix tensorboard integration skipping steps at finish() by @KyleGoyette in https://github.com/wandb/wandb/pull/3626
- Rename `wandb local` to `wandb server` by @jsbroks in https://github.com/wandb/wandb/pull/3716
- Fix busted docker inspect command by @vanpelt in https://github.com/wandb/wandb/pull/3742
- Add dedicated sentry wandb by @dmitryduev in https://github.com/wandb/wandb/pull/3724
- Image Type should gracefully handle older type params by @tssweeney in https://github.com/wandb/wandb/pull/3731

#### :broom: Cleanup

- Inline FileEventHandler.synced into the only method where it's used by @speezepearson in https://github.com/wandb/wandb/pull/3594
- Use passed size argument to make `PolicyLive.min_wait_for_size` a classmethod by @speezepearson in https://github.com/wandb/wandb/pull/3593
- Make FileEventHandler an ABC, remove some "default" method impls which were only used once by @speezepearson in https://github.com/wandb/wandb/pull/3595
- Remove unused field from DirWatcher by @speezepearson in https://github.com/wandb/wandb/pull/3592
- Make sweeps an extra instead of vendoring by @dmitryduev in https://github.com/wandb/wandb/pull/3628
- Add nightly CI testing by @dmitryduev in https://github.com/wandb/wandb/pull/3580
- Improve keras and data type Reference Docs by @ramit-wandb in https://github.com/wandb/wandb/pull/3676
- Update `pytorch` version requirements in dev environments by @dmitryduev in https://github.com/wandb/wandb/pull/3683
- Clean up CircleCI config by @dmitryduev in https://github.com/wandb/wandb/pull/3722
- Add `py310` testing in CI by @dmitryduev in https://github.com/wandb/wandb/pull/3730
- Ditch `dateutil` from the requirements by @dmitryduev in https://github.com/wandb/wandb/pull/3738
- Add deprecated string to `Table.add_row` by @nate-wandb in https://github.com/wandb/wandb/pull/3739

## New Contributors

- @sephmard made their first contribution in https://github.com/wandb/wandb/pull/3610
- @astariul made their first contribution in https://github.com/wandb/wandb/pull/3643
- @manangoel99 made their first contribution in https://github.com/wandb/wandb/pull/3713
- @nate-wandb made their first contribution in https://github.com/wandb/wandb/pull/3739

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.17...v0.12.18

## 0.12.17 (May 26, 2022)

#### :bug: Bug Fix

- Update requirements to fix incompatibility with protobuf >= 4 by @dmitryduev in https://github.com/wandb/wandb/pull/3709

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.16...v0.12.17

## 0.12.16 (May 3, 2022)

#### :nail_care: Enhancement

- Improve W&B footer by aligning summary/history in notebook env by @kptkin in https://github.com/wandb/wandb/pull/3479
- Enable experimental history step logging in artifacts by @raubitsj in https://github.com/wandb/wandb/pull/3502
- Add `args_no_boolean_flags` macro to sweep configuration by @hu-po in https://github.com/wandb/wandb/pull/3489
- Add logging support for `jax.bfloat.bfloat16` by @dmitryduev in https://github.com/wandb/wandb/pull/3528
- Raise exception when Table size exceeds limit by @dannygoldstein in https://github.com/wandb/wandb/pull/3511
- Add kaniko k8s builder for wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3492
- Add wandb.init() timeout setting by @kptkin in https://github.com/wandb/wandb/pull/3579
- Do not assume executable for given entrypoints with wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3461
- Jupyter environments no longer collect command arguments by @KyleGoyette in https://github.com/wandb/wandb/pull/3456
- Add support for TensorFlow/Keras SavedModel format by @ayulockin in https://github.com/wandb/wandb/pull/3276

#### :bug: Bug Fix

- Support version IDs in artifact refs, fix s3/gcs references in Windows by @annirudh in https://github.com/wandb/wandb/pull/3529
- Fix support for multiple finish for single run using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3560
- Fix duplicate backtrace when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3575
- Fix wrong entity displayed in login message by @kptkin in https://github.com/wandb/wandb/pull/3490
- Fix hang when `wandb.init` is interrupted mid setup using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3569
- Fix handling keyboard interrupt to avoid hangs with wandb-service enabled by @kptkin in https://github.com/wandb/wandb/pull/3566
- Fix console logging with very long print out when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3574
- Fix broken artifact string in launch init config by @KyleGoyette in https://github.com/wandb/wandb/pull/3582

#### :broom: Cleanup

- Fix typo in wandb.log() docstring by @RobRomijnders in https://github.com/wandb/wandb/pull/3520
- Cleanup custom chart code and add type annotations to plot functions by @kptkin in https://github.com/wandb/wandb/pull/3407
- Improve `wandb.init(settings=)` to handle `Settings` object similarly to `dict` parameter by @dmitryduev in https://github.com/wandb/wandb/pull/3510
- Add documentation note about api.viewer in api.user() and api.users() by @ramit-wandb in https://github.com/wandb/wandb/pull/3552
- Be explicit about us being py3+ only in setup.py by @dmitryduev in https://github.com/wandb/wandb/pull/3549
- Add type annotations to DirWatcher by @speezepearson in https://github.com/wandb/wandb/pull/3557
- Improve wandb.log() docstring to use the correct argument name by @idaho777 in https://github.com/wandb/wandb/pull/3585

## New Contributors

- @RobRomijnders made their first contribution in https://github.com/wandb/wandb/pull/3520
- @ramit-wandb made their first contribution in https://github.com/wandb/wandb/pull/3552
- @idaho777 made their first contribution in https://github.com/wandb/wandb/pull/3585

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.15...v0.12.16

## 0.12.15 (April 21, 2022)

#### :nail_care: Enhancement

- Optimize wandb.Image logging when linked to an artifact by @tssweeney in https://github.com/wandb/wandb/pull/3418

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.14...v0.12.15

## 0.12.14 (April 8, 2022)

#### :bug: Bug Fix

- Fix regression: disable saving history step in artifacts by @vwrj in https://github.com/wandb/wandb/pull/3495

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.13...v0.12.14

## 0.12.13 (April 7, 2022)

#### :bug: Bug Fix

- Revert strictened api_key validation by @dmitryduev in https://github.com/wandb/wandb/pull/3485

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.12...v0.12.13

## 0.12.12 (April 5, 2022)

#### :nail_care: Enhancement

- Allow run objects to be passed to other processes when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3308
- Add create user to public api by @vanpelt in https://github.com/wandb/wandb/pull/3438
- Support logging from multiple processes with wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3285
- Add gpus flag for local launch runner with cuda by @KyleGoyette in https://github.com/wandb/wandb/pull/3417
- Improve Launch deployable agent by @KyleGoyette in https://github.com/wandb/wandb/pull/3388
- Add Launch kubernetes integration by @KyleGoyette in https://github.com/wandb/wandb/pull/3393
- KFP: Add wandb visualization helper by @andrewtruong in https://github.com/wandb/wandb/pull/3439
- KFP: Link back to Kubeflow UI by @andrewtruong in https://github.com/wandb/wandb/pull/3427
- Add boolean flag arg macro by @hugo.ponte in https://github.com/wandb/wandb/pull/3489

#### :bug: Bug Fix

- Improve host / WANDB_BASE_URL validation by @dmitryduev in https://github.com/wandb/wandb/pull/3314
- Fix/insecure tempfile by @dmitryduev in https://github.com/wandb/wandb/pull/3360
- Fix excess warning span if requested WANDB_DIR/root_dir is not writable by @dmitryduev in https://github.com/wandb/wandb/pull/3304
- Fix line_series to plot array of strings by @kptkin in https://github.com/wandb/wandb/pull/3385
- Properly handle command line args with service by @kptkin in https://github.com/wandb/wandb/pull/3371
- Improve api_key validation by @dmitryduev in https://github.com/wandb/wandb/pull/3384
- Fix multiple performance issues caused by not using defaultdict by @dmitryduev in https://github.com/wandb/wandb/pull/3406
- Enable inf max jobs on launch agent by @stephchen in https://github.com/wandb/wandb/pull/3412
- fix colab command to work with launch by @stephchen in https://github.com/wandb/wandb/pull/3422
- fix typo in Config docstring by @hu-po in https://github.com/wandb/wandb/pull/3416
- Make code saving not a policy, keep previous custom logic by @dmitryduev in https://github.com/wandb/wandb/pull/3395
- Fix logging sequence images with service by @kptkin in https://github.com/wandb/wandb/pull/3339
- Add username to debug-cli log file to prevent conflicts of multiple users by @zythosec in https://github.com/wandb/wandb/pull/3301
- Fix python sweep agent for users of wandb service / pytorch-lightning by @raubitsj in https://github.com/wandb/wandb/pull/3465
- Remove unnecessary launch reqs checks by @KyleGoyette in https://github.com/wandb/wandb/pull/3457
- Workaround for MoviePy's Unclosed Writer by @tssweeney in https://github.com/wandb/wandb/pull/3471
- Improve handling of Run objects when service is not enabled by @kptkin in https://github.com/wandb/wandb/pull/3362

## New Contributors

- @hu-po made their first contribution in https://github.com/wandb/wandb/pull/3416
- @zythosec made their first contribution in https://github.com/wandb/wandb/pull/3301

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.11...v0.12.12

## 0.12.11 (March 1, 2022)

#### :nail_care: Enhancement

- Add captions to Molecules by @dmitryduev in https://github.com/wandb/wandb/pull/3173
- Add CatBoost Integration by @ayulockin in https://github.com/wandb/wandb/pull/2975
- Launch: AWS Sagemaker integration by @KyleGoyette in https://github.com/wandb/wandb/pull/3007
- Launch: Remove repo2docker and add gpu support by @stephchen in https://github.com/wandb/wandb/pull/3161
- Adds Timestamp inference from Python for Weave by @tssweeney in https://github.com/wandb/wandb/pull/3212
- Launch GCP vertex integration by @stephchen in https://github.com/wandb/wandb/pull/3040
- Use Artifacts when put into run config. Accept a string to represent an artifact in the run config by @KyleGoyette in https://github.com/wandb/wandb/pull/3203
- Improve xgboost `wandb_callback` (#2929) by @ayulockin in https://github.com/wandb/wandb/pull/3025
- Add initial kubeflow pipeline support by @andrewtruong in https://github.com/wandb/wandb/pull/3206

#### :bug: Bug Fix

- Fix logging of images with special characters in the key by @speezepearson in https://github.com/wandb/wandb/pull/3187
- Fix azure blob upload retry logic by @vanpelt in https://github.com/wandb/wandb/pull/3218
- Fix program field for scripts run as a python module by @dmitryduev in https://github.com/wandb/wandb/pull/3228
- Fix issue where `sync_tensorboard` could die on large histograms by @KyleGoyette in https://github.com/wandb/wandb/pull/3019
- Fix wandb service performance issue during run shutdown by @raubitsj in https://github.com/wandb/wandb/pull/3262
- Fix vendoring of gql and graphql by @raubitsj in https://github.com/wandb/wandb/pull/3266
- Flush log data without finish with service by @kptkin in https://github.com/wandb/wandb/pull/3137
- Fix wandb service hang when the service crashes by @raubitsj in https://github.com/wandb/wandb/pull/3280
- Fix issue logging images with "/" on Windows by @KyleGoyette in https://github.com/wandb/wandb/pull/3146
- Add image filenames to images/separated media by @KyleGoyette in https://github.com/wandb/wandb/pull/3041
- Add setproctitle to requirements.txt by @raubitsj in https://github.com/wandb/wandb/pull/3289
- Fix issue where sagemaker run ids break run queues by @KyleGoyette in https://github.com/wandb/wandb/pull/3290
- Fix encoding exception when using %%capture magic by @raubitsj in https://github.com/wandb/wandb/pull/3310

## New Contributors

- @speezepearson made their first contribution in https://github.com/wandb/wandb/pull/3188

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.10...v0.12.11

## 0.12.10 (February 1, 2022)

#### :nail_care: Enhancement

- Improve validation when creating Tables with invalid columns from dataframes by @tssweeney in https://github.com/wandb/wandb/pull/3113
- Enable digest deduplication for `use_artifact()` calls by @annirudh in https://github.com/wandb/wandb/pull/3109
- Initial prototype of azure blob upload support by @vanpelt in https://github.com/wandb/wandb/pull/3089

#### :bug: Bug Fix

- Fix wandb launch using python dev versions by @stephchen in https://github.com/wandb/wandb/pull/3036
- Fix loading table saved with mixed types by @vwrj in https://github.com/wandb/wandb/pull/3120
- Fix ResourceWarning when calling wandb.log by @vwrj in https://github.com/wandb/wandb/pull/3130
- Fix missing cursor in ProjectArtifactCollections by @KyleGoyette in https://github.com/wandb/wandb/pull/3108
- Fix windows table logging classes issue by @vwrj in https://github.com/wandb/wandb/pull/3145
- Gracefully handle string labels in wandb.sklearn.plot.classifier.calibration_curve by @acrellin in https://github.com/wandb/wandb/pull/3159
- Do not display login warning when calling wandb.sweep() by @acrellin in https://github.com/wandb/wandb/pull/3162

#### :broom: Cleanup

- Drop python2 backport deps (enum34, subprocess32, configparser) by @jbylund in https://github.com/wandb/wandb/pull/3004
- Settings refactor by @dmitryduev in https://github.com/wandb/wandb/pull/3083

## New Contributors

- @jbylund made their first contribution in https://github.com/wandb/wandb/pull/3004
- @acrellin made their first contribution in https://github.com/wandb/wandb/pull/3159

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.9...v0.12.10

## 0.12.9 (December 16, 2021)

#### :bug: Bug Fix

- Fix regression in `upload_file()` exception handler by @raubitsj in https://github.com/wandb/wandb/pull/3059

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.8...v0.12.9

## 0.12.8 (December 16, 2021)

#### :nail_care: Enhancement

- Update contributing guide and dev env setup tool by @dmitryduev in https://github.com/wandb/wandb/pull/2968
- Improve `wandb_callback` for LightGBM (#2945) by @ayulockin in https://github.com/wandb/wandb/pull/3024

#### :bug: Bug Fix

- Reduce GPU memory usage when generating histogram of model weights by @TOsborn in https://github.com/wandb/wandb/pull/2927
- Support mixed classes in bounding box and image mask annotation layers by @tssweeney in https://github.com/wandb/wandb/pull/2914
- Add max-jobs and launch async args by @stephchen in https://github.com/wandb/wandb/pull/2925
- Support lists of Summary objects encoded as strings to wandb.tensorboard.log by @dmitryduev in https://github.com/wandb/wandb/pull/2934
- Fix handling of 0 dim np arrays by @rpitonak in https://github.com/wandb/wandb/pull/2954
- Fix handling of empty default config file by @vwrj in https://github.com/wandb/wandb/pull/2957
- Add service backend using sockets (support fork) by @raubitsj in https://github.com/wandb/wandb/pull/2892
- Send git port along with url when sending git repo by @KyleGoyette in https://github.com/wandb/wandb/pull/2959
- Add support raw ip addresses for launch by @KyleGoyette in https://github.com/wandb/wandb/pull/2950
- Tables no longer serialize and hide 1d NDArrays by @tssweeney in https://github.com/wandb/wandb/pull/2976
- Fix artifact file uploads to S3 stores by @annirudh in https://github.com/wandb/wandb/pull/2999
- Send uploaded file list on file stream heartbeats by @annirudh in https://github.com/wandb/wandb/pull/2978
- Add support for keras experimental layers by @KyleGoyette in https://github.com/wandb/wandb/pull/2776
- Fix `from wandb import magic` to not require tensorflow by @raubitsj in https://github.com/wandb/wandb/pull/3021
- Fix launch permission error by @KyleGoyette in https://github.com/wandb/wandb/pull/3038

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.7...v0.12.8

## 0.12.7 (November 18, 2021)

#### :bug: Bug Fix

- Fix issue where console log streaming was causing excessive network traffic by @vwrj in https://github.com/wandb/wandb/pull/2786
- Metaflow: Make optional dependencies actually optional by @andrewtruong in https://github.com/wandb/wandb/pull/2842
- Fix docstrings for wandb.watch and ValidationDataLogger by @charlesfrye in https://github.com/wandb/wandb/pull/2849
- Prevent launch agent from sending runs to a different project or entity by @KyleGoyette in https://github.com/wandb/wandb/pull/2872
- Fix logging pr_curves through tensorboard by @KyleGoyette in https://github.com/wandb/wandb/pull/2876
- Prevent TPU monitoring from reporting invalid metrics when not available by @kptkin in https://github.com/wandb/wandb/pull/2753
- Make import order dependencies for WandbCallback more robust by @kptkin in https://github.com/wandb/wandb/pull/2807
- Fix a bug in feature importance plotting to handle matrices of different shapes by @dannygoldstein in https://github.com/wandb/wandb/pull/2811
- Fix base url handling to allow trailing / by @kptkin in https://github.com/wandb/wandb/pull/2910
- Prevent wandb.agent() from sending too many heartbeats impacting rate limits by @dannygoldstein in https://github.com/wandb/wandb/pull/2923
- Redact sensitive information from debug logs by @raubitsj in https://github.com/wandb/wandb/pull/2931

#### :nail_care: Enhancement

- Add wandb.Molecule support for rdkit supported formats by @dmitryduev in https://github.com/wandb/wandb/pull/2902
- Add module-level docstrings for reference doc modules. by @charlesfrye in https://github.com/wandb/wandb/pull/2847
- Store launch metadata in file by @KyleGoyette in https://github.com/wandb/wandb/pull/2582
- Add Project.sweeps() public API call to view all sweeps in a project by @stephchen in https://github.com/wandb/wandb/pull/2729
- Ensures API key prompt remains captive when user enters nothing by @dannygoldstein in https://github.com/wandb/wandb/pull/2721
- Refactors wandb.sklearn into submodules by @charlesfrye in https://github.com/wandb/wandb/pull/2869
- Support code artifacts in wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/2860
- Improve launch agent (async, stop, heartbeat updates) by @stephchen in https://github.com/wandb/wandb/pull/2871
- Improve usage and error messages for anonymous mode by @kimjyhello in https://github.com/wandb/wandb/pull/2823
- Add example on how to find runs with wandb.Api().runs(...) matching a regex by @dmitryduev in https://github.com/wandb/wandb/pull/2926

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.6...v0.12.7

## 0.12.6 (October 27, 2021)

#### :bug: Bug Fix

- Fix sklearn `plot_calibration_curve()` issue breaking the provided model by @vwrj in https://github.com/wandb/wandb/pull/2791
- Fix CondaEnvExportError by redirecting stderr by @charlesfrye in https://github.com/wandb/wandb/pull/2814
- Fix `use_artifact()` when specifying an artifact from a different project by @KyleGoyette in https://github.com/wandb/wandb/pull/2832

#### :nail_care: Enhancement

- Add metric names to pr curve charts in tensorboard by @vanpelt in https://github.com/wandb/wandb/pull/2822

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.5...v0.12.6

## 0.12.5 (October 19, 2021)

#### :bug: Bug Fix

- Report errors for invalid characters in logged media keys on windows
- Handle errors when probing for TPUs in unsupported environments
- Fixed bug where `%%wandb` followed by wandb.init() does not display run links
- Fixed api.runs() to correctly return all runs for the current entity/project

#### :nail_care: Enhancement

- Add `wandb.require(experiment="service")` to improve multiprocessing support
- Add support for swappable artifacts in launch context
- Add `wandb.login(timeout=)` support for jupyter environments
- Add ability to disable git ref saving with `WANDB_DISABLE_GIT`
- Support newer versions of pytest-mock and PyYAML
- Add ability to delete artifacts with aliases: `artifact.delete(delete_aliases=True)`
- Add `unwatch()` method to the Run object

## 0.12.4 (October 5, 2021)

#### :bug: Bug Fix

- Fix regression introduced in 0.12.2 causing network access when `WANDB_MODE=offline`

## 0.12.3 (September 30, 2021)

#### :bug: Bug Fix

- Fixes the grid search stopping condition in the local controller

#### :nail_care: Enhancement

- New jupyter magic for displaying runs, sweeps, and projects `%wandb path/to/run -h 1024`
- We no longer display run iframe by default in jupyter, add `%%wandb` to a cell to display a run
- Makes api key prompting retry indefinitely on malformed input
- Invite users to teams via the api `api.team("team_name").invite("username_or_email")`
- Remove users from a team via the api `api.team("team_name").members[0].delete()`
- Create service accounts via the api `api.team("team_name").create_service_account("Description")`
- Manage api keys via the api `api.user("username_or_email").generate_api_key()`
- Add pytorch profiling trace support with `wandb.profiler.torch_trace_handler()`

## 0.12.2 (September 15, 2021)

#### :bug: Bug Fix

- Fix tensorboard_sync to handle ephemeral Sagemaker tfevents files
- Fix Reports query from the public api (broken pagination and report path)
- Fix `wandb.login()` when relogin is specified (only force login once)

#### :nail_care: Enhancement

- Clean up footer output of summary and history metrics
- Clean up error message from `wandb sweep --update`
- Add warning for `wandb local` users to update their docker
- Add optional argument log_learning_curve to wandb.sklearn.plot_classifier()
- Restore frozen pip package versions when using `wandb launch`
- Add support for jupyter notebooks in launch
- Add `wandb.login()` timeout option

## 0.12.1 (August 26, 2021)

#### :bug: Bug Fix

- Fix tensorflow/keras 2.6 not logging validation examples
- Fix metrics logged through tensorboard not supporting time on x-axis
- Fix `WANDB_IGNORE_GLOBS` environment variable handling
- Fix handling when sys.stdout is configured to a custom logger
- Fix sklearn feature importance plots not matching feature names properly
- Fix an issue where colab urls were not being captured
- Save program commandline if run executable was outside cwd

#### :nail_care: Enhancement

- Add Prodigy integration to upload annotated datasets to W&B Tables
- Add initial Metaflow support
- Add experimental wandb launch support
- Add warnings that public API requests are timing out and allow override
- Improve error handling in local controller sweeps engine

## 0.12.0 (August 10, 2021)

#### :hourglass: No Longer Supported

- Remove Python 3.5 support

#### :bug: Bug Fix

- Fix issue that could cause artifact uploads to fail if artifact files are being modified
- Fix issue where `wandb.restore()` wouldn't work with runs from a sweep

#### :nail_care: Enhancement

- Improve run execution time calculation

## 0.11.2 (August 2, 2021)

#### :bug: Bug Fix

- Restore vendored graphql-core library because of network regression

## 0.11.1 (July 29, 2021)

#### :hourglass: Deprecated

- Python 3.5 will not be supported as of `wandb==0.12.0`

#### :bug: Bug Fix

- Reduce Memory Footprint of Images In Tables
- Added a dependency on graphql-core>=2.3.0
- Removed urllib3 pin to avoid conflicts, if you see urllib3 related errors run `pip install --upgrade urllib3`
- Improved Public API HTTP error messages
- Set run.dir to the generated directory name in disabled mode

#### :nail_care: Enhancement

- Adds support for native Jax array logging
- Tables now support Molecule data type
- Improve Stable-Baselines3 API by auto log model's name and always upload models at the end of training
- Implements the sweep local controller using wandb/sweeps

## 0.11.0 (July 15, 2021)

#### :hourglass: No Longer Supported

- Remove Python 2.7 support

#### :bug: Bug Fix

- Fix issue where `wandb.watch()` broke model saving in pytorch
- Fix issue where uniform sweep parameters were parsed as int_uniform
- Fix issue where file_stream thread was killed on 4xx errors

#### :nail_care: Enhancement

- Improve performance of artifact logging by making it non-blocking
- Add wandb integration for Stable-Baselines3
- Improve keras callback validation logging inference logic
- Expose sweep state via the public API
- Improve performance of sweep run fetches via the API

## 0.10.33 (June 28, 2021)

#### :bug: Bug Fix

- Fix issue where wandb restore 404ed if the run did not have a diff.patch file
- Fix issue where wandb.log raised an Exception after trying to log a pandas dataframe
- Fix issue where runs could be marked finished before files were finished uploading

#### :nail_care: Enhancement

- Disable reloading of run metadata (such as command) in resumed runs
- Allow logging of pandas dataframes by automatically converting them to W&B tables
- Fix up `log_code()` exclude fn to handle .wandb dir
- Improve handling of PyTorch model topology
- Increase config debounce interval to 30s to reduce load on WB/backend
- Improve reliability of CLI in generating sweeps with names, programs, and settings

## 0.10.32 (June 10, 2021)

#### :bug: Bug Fix

- Make `log_artifact()` more resilient to network errors
- Removed Duplicate Artifact Dependencies
- Workaround urlib3 issue on windows
- Fix regression where ipython was hanging
- Allow logging of numpy high precision floating point values
- Reduce liklyhood of collisions for file backed media or artifact objects
- Fix wandb.watch() regression when logging pytorch graphs

#### :nail_care: Enhancement

- Add support for logging joined and partitioned table
- Handle schema validation warnings for sweep configs
- Improve wandb sync to handle errors
- Add ability to label scripts and repositories who use wandb

## 0.10.31 (May 27, 2021)

#### :bug: Bug Fix

- wandb.login() did not properly persist the host parameter
- Fix issue where step information was not synced properly when syncing tensorboard directories
- Fix some unicode issues with python2.7
- Fixed bug in `plot_calibration_curve` for ComplementNB
- Fall back to not using SendFile on some linux systems
- Fix console issues where lines were truncated
- Fix console issues where console logging could block

#### :nail_care: Enhancement

- Add support for preemptible sweeps
- Add command line for sweep control
- Add support to load artifact collection properties

## 0.10.30 (May 7, 2021)

#### :bug: Bug Fix

- Found and fixed the remaining issues causing runs to be marked crashed during outages
- Improved performance for users of `define_metric`, pytorch-lightning, and aggressive config saving
- Fix issue when trying to log a cuda tensor to config or summary
- Remove dependency on torch `backward_hooks` to compute graph
- Fix an issue preventing the ability to resume runs on sagemaker
- Fix issues preventing pdb from working reliably with wandb
- Fix deprecation warning in vendored library (user submission)
- Fix logging behavior where the library was accidently outputting logs to the console
- Fix disabled mode to not create wandb dir and log files
- Renamed types to prep for Tables launch

#### :nail_care: Enhancement

- Allow renaming groups with public api

## 0.10.29 (May 3, 2021)

#### :bug: Bug Fix

- Fix more network handling issues causing runs to be marked crashed (wandb sync to recover)
- Improve logging and exception handling to improve reporting and logging of crashed processes

## 0.10.28 (April 28, 2021)

#### :bug: Bug Fix

- Fix network handling issue causing runs to be marked crashed (wandb sync to recover)
- Use `register_full_backward_hook` to support models with Dict outputs
- Allow periods in table columns
- Fix artifact cache collisions when using forked processes
- Fix issue where custom charts do not display properly with pytorch-lightning

#### :nail_care: Enhancement

- Add experimental incremental artifact support
- Improve warnings when logging is being rate limited

## 0.10.27 (April 19, 2021)

#### :bug: Bug Fix

- Fix tensorboard_sync condition where metrics at end of short run are dropped
- Fix `wandb sync` when tensorboard files are detected
- Fix api key prompt in databricks notebook

#### :nail_care: Enhancement

- Integrate DSViz into Keras WandbCallback
- Add support for conda dependencies (user submit)

## 0.10.26 (April 13, 2021)

#### :bug: Bug Fix

- Fix network handling issue where syncing stopped (use wandb sync to recover)
- Fix auth problem when using sagemaker and hugginface integrations together
- Fix handling of NaN values in tables with non floats
- Lazy load API object to prevent unnecessary file access on module load

#### :nail_care: Enhancement

- Improve error messages when using public api history accessors

## 0.10.25 (April 5, 2021)

#### :bug: Bug Fix

- Fix possible artifact cache race when using parallel artifact reads
- Fix artifact reference when `checksum=False`

#### :nail_care: Enhancement

- Release `run.define_metric()` to simplify custom x-axis and more
- Add column operators `add_column`, `get_column`, `get_index` to `wandb.Table()`

## 0.10.24 (March 30, 2021)

#### :bug: Bug Fix

- Significant fixes to stdout/stderr console logging
- Prevent excessive network when saving files with policy=`live`
- Fix errors when trying to send large updates (most common with `wandb sync`)

#### :nail_care: Enhancement

- Automatically generate `run_table` artifact for logged tables
- Add bracket notation to artifacts
- Improve URL validation when specifying server url to `wandb login`

## 0.10.23 (March 22, 2021)

#### :bug: Bug Fix

- Fix logged artifacts to be accessible after wait()
- Fix spell.run integration
- Performance fix syncing console logs with carriage returns
- Fix confusion matrix with class names and unlabeled data

#### :nail_care: Enhancement

- Add the ability to save artifacts without creating a run
- Add Foreign Table References to wandb.Table
- Allow the same runtime object to be logged to multiple artifacts
- Add experimental `run._define_metric()` support
- Warn and ignore unsupported multiprocess `wandb.log()` calls

## 0.10.22 (March 9, 2021)

#### :bug: Bug Fix

- Fix system metric logging rate in 0.10.x
- Fix Audio external reference issue
- Fix short runs with tensorboard_sync
- Ignore `wandb.init(id=)` when running a sweep
- Sanitize artifact metadata if needed

#### :nail_care: Enhancement

- Allow syncing of tfevents with `wandb sync --sync-tensorboard`

## 0.10.21 (March 2, 2021)

#### :bug: Bug Fix

- Fix artifact.get() regression since 0.10.18
- Allow 0 byte artifacts
- Fix codesaving and program name reporting

#### :nail_care: Enhancement

- Added support for glb files for `wandb.Object3D()`
- Added support for external references for `wandb.Audio()`
- Custom chart support tensorboard `pr_curves` plugin
- Support saving entire code directory in an artifact

## 0.10.20 (February 22, 2021)

#### :bug: Bug Fix

- wandb.login() now respects disabled mode
- handle exception when trying to log TPUs in colab

#### :nail_care: Enhancement

- Add `WANDB_START_METHOD=thread` to support non-multiprocessing
- Add `group` and `job_type` to Run object in the export API
- Improve artifact docstrings

## 0.10.19 (February 14, 2021)

#### :bug: Bug Fix

- Fix artifact manifest files incorrectly named with patch suffix

## 0.10.18 (February 8, 2021)

#### :nail_care: Enhancement

- Add run delete and file delete to the public API
- Align steps between `tensorboard_sync` and wandb.log() history
- Add `WANDB_START_METHOD` to allow POSIX systems to use fork
- Support mixed types in wandb.Table() with `allow_mixed_types`

#### :bug: Bug Fix

- Fix potential leaked file due to log not being closed properly
- Improve `wandb verify` to better handle network issues and report errors
- Made file downloads more deterministic with respect to filesystem caches

## 0.10.17 (February 1, 2021)

#### :bug: Bug Fix

- Fix regression seen with python 3.5
- Silence vendored watchdog warnings on mac

## 0.10.16 (February 1, 2021)

#### :nail_care: Enhancement

- Artifacts now support parallel writers for large distributed workflows.
- Artifacts support distributed tables for dataset visualization.
- Improvements to PR templates
- Added more type annotations
- Vendored watchdog 0.9.0 removing it as a dependency
- New documentation generator
- Public api now has `file.direct_url` to avoid redirects for signed urls.

#### :bug: Bug Fix

- Allow `config-defaults.yaml` to be overwritten when running sweeps
- General bug fixes and improvements to `wandb verify`
- Disabled widgets in Spyder IDE
- Fixed WANDB_SILENT in Spyder IDE
- Reference file:// artifacts respect the `name` attribute.

## 0.10.15 (January 24, 2021)

#### :nail_care: Enhancement

- Add `wandb verify` to troubleshoot local installs

#### :bug: Bug Fix

- Fix tensorboard_sync issue writing to s3
- Prevent git secrets from being stored
- Disable verbose console messages when using moviepy
- Fix artifacts with checkpoints to be more robust when overwriting files
- Fix artifacts recycled id issue

## 0.10.14 (January 15, 2021)

#### :nail_care: Enhancement

- Add wandb.Audio support to Artifacts

#### :bug: Bug Fix

- Fix wandb config regressions introduced in 0.10.13
- Rollback changes supporting media with slashes in keys

## 0.10.13 (January 11, 2021)

#### :nail_care: Enhancement

- Add support for Mac M1 GPU monitoring
- Add support for TPU monitoring
- Add setting to disable sagemaker integration

#### :bug: Bug Fix

- Fix tensorboard_sync with tensorboardX and tf1
- Fix issues logging images with slashes
- Fix custom charts issues
- Improve error messages using `wandb pull`
- Improve error messages with `wandb.Table()`
- Make sure silent mode is silent
- Fix `wandb online` to renable logging
- Multiple artifact fixes

## 0.10.12 (December 3, 2020)

#### :nail_care: Enhancement

- Add Artifact.used_by and Artifact.logged_by
- Validate type consistency when logging Artifacts
- Enhance JoinedTable to not require downloaded assets
- Add ability to recursively download dependent artifacts
- Enable gradient logging with keras and tf2+
- Validate pytorch models are passed to wandb.watch()
- Improved docstrings for public methods / objects
- Warn when image sequences are logged with different sizes

#### :bug: Bug Fix

- Fix incorrectly generated filenames in summary
- Fix anonymous mode to include the api key in URLs
- Fix pickle issue with disabled mode
- Fix artifact from_id query
- Fix handling of Tables with different image paths

## 0.10.11 (November 18, 2020)

#### :nail_care: Enhancement

- Disable wandb logging with `wandb disabled` or `wandb.init(mode="disabled")`
- Support cloning an artifact when logging wandb.Image()

#### :bug: Bug Fix

- Multiple media artifact improvements and internal refactor
- Improve handling of artifact errors
- Fix issue where notebook name was ignored
- Extend silent mode for jupyter logging
- Fix issue where vendored libraries interfered with python path
- Fix various exceptions (divide by zero, int conversion, TypeError)

## 0.10.10 (November 9, 2020)

#### :nail_care: Enhancement

- Added confusion matrix plot
- Better jupyter messages with wandb.init()/reinit/finish

#### :bug: Bug Fix

- Fix for fastai 2.1.5 (removed log_args)
- Fixed media logging when directories are changed

## 0.10.9 (November 4, 2020)

#### :nail_care: Enhancement

- Added artifact media logging (alpha)
- Add scriptable alerts
- Add url attribute for sweep public api
- Update docstrings for wandb sdk functions

#### :bug: Bug Fix

- Fix cases where offline mode was making network connections
- Fix issues with python sweeps and run stopping
- Fix logging issue where we could accidently display an api key
- Fix wandb login issues with malformed hosts
- Allow wandb.restore() to be called without wandb.init()
- Fix resuming (reusing run_id) with empty summary
- Fix artitifact download issue
- Add missing wandb.unwatch() function
- Avoid creating spurious wandb directories
- Fix collections import issue when using an old version of six

## 0.10.8 (October 22, 2020)

#### :nail_care: Enhancement

- Allow callables to be serialized

#### :bug: Bug Fix

- Fix compatibility issue with python 3.9
- Fix `wandb sync` failure introduced in 0.10.6
- Improve python agent handling of failing runs
- Fix rare condition where resuming runs does not work
- Improve symlink handling when called in thread context
- Fix issues when changing directories before calling wandb.init()

## 0.10.7 (October 15, 2020)

#### :bug: Bug Fix

- Fix issue when checking for updated releases on pypi

## 0.10.6 (October 15, 2020)

#### :bug: Bug Fix

- Make sure code saving is enabled in jupyter environments after login
- Sweep agents have extended timeout for large sweep configs
- Support WANDB_SILENT environment variable
- Warn about missing python package when logging images
- Fix wandb.restore() to apply diff patch
- Improve artifact error messages
- Fix loading of config-defaults.yaml and specified list of yaml config files

## 0.10.5 (October 7, 2020)

#### :nail_care: Enhancement

- Add new custom plots: `wandb.plot.*`
- Add new python based sweep agent: `wandb.agent()`

#### :bug: Bug Fix

- Console log fixes (tqdm on windows, fix close exceptions)
- Add more attributes to the Run object (group, job_type, urls)
- Fix sagemaker login issues
- Fix issue where plots were not uploaded until the end of run

## 0.10.4 (September 29, 2020)

#### :bug: Bug Fix

- Fix an issue where wandb.init(allow_val_change=) throws exception

## 0.10.3 (September 29, 2020)

#### :nail_care: Enhancement

- Added warning when trying to sync pre 0.10.0 run dirs
- Improved jupyter support for wandb run syncing information

#### :bug: Bug Fix

- Fix artifact download issues
- Fix multiple issues with tensorboard_sync
- Fix multiple issues with juypter/python sweeps
- Fix issue where login was timing out
- Fix issue where config was overwritten when resuming runs
- Ported sacred observer to 0.10.x release
- Fix predicted bounding boxes overwritten by ground truth boxes
- Add missing save_code parameter to wandb.init()

## 0.10.2 (September 20, 2020)

#### :nail_care: Enhancement

- Added upload_file to API
- wandb.finish() can be called without matching wandb.init()

#### :bug: Bug Fix

- Fix issue where files were being logged to wrong parallel runs
- Fix missing properties/methods -- as_dict(), sweep_id
- Fix wandb.summary.update() not updating all keys
- Code saving was not properly enabled based on UI settings
- Tensorboard now logging images before end of program
- Fix resume issues dealing with config and summary metrics

## 0.10.1 (September 16, 2020)

#### :nail_care: Enhancement

- Added sync_tensorboard ability to handle S3 and GCS files
- Added ability to specify host with login
- Improved artifact API to allow modifying attributes

#### :bug: Bug Fix

- Fix codesaving to respect the server settings
- Fix issue running wandb.init() on restricted networks
- Fix issue where we were ignoring settings changes
- Fix artifact download issues

## 0.10.0 (September 11, 2020)

#### :nail_care: Enhancement

- Added history sparklines at end of run
- Artifact improvements and API for linking
- Improved offline support and syncing
- Basic noop mode support to simplify testing
- Improved windows/pycharm support
- Run object has more modifiable properties
- Public API supports attaching artifacts to historic runs

#### :bug: Bug Fix

- Many bugs fixed due to simplifying logic

## 0.9.7 (September 8, 2020)

#### :nail_care: Enhancement

- New sacred observer available at wandb.sacred.WandbObserver
- Improved artifact reference tracking for HTTP urls

#### :bug: Bug Fix

- Print meaningful error message when runs are queried with `summary` instead of `summary_metrics`

## 0.9.6 (August 28, 2020)

#### :nail_care: Enhancement

- Sub paths of artifacts now expose an optional root directory argument to download()
- Artifact.new_file accepts an optional mode argument
- Removed legacy fastai docs as we're now packaged with fastai v2!

#### :bug: Bug Fix

- Fix yaml parsing error handling logic
- Bad spelling in torch docstring, thanks @mkkb473

## 0.9.5 (August 17, 2020)

#### :nail_care: Enhancement

- Remove unused y_probas in sklearn plots, thanks @dreamflasher
- New deletion apis for artifacts

#### :bug: Bug Fix

- Fix `wandb restore` when not logged in
- Fix artifact download paths on Windows
- Retry 408 errors on upload
- Fix mask numeric types, thanks @numpee
- Fix artifact reference naming mixup

## 0.9.4 (July 24, 2020)

#### :nail_care: Enhancement

- Default pytorch histogram logging frequency from 100 -> 1000 steps

#### :bug: Bug Fix

- Fix multiple prompts for login when using the command line
- Fix "no method rename_file" error
- Fixed edgecase histogram calculation in PyTorch
- Fix error in jupyter when saving session history
- Correctly return artifact metadata in public api
- Fix matplotlib / plotly rendering error

## 0.9.3 (July 10, 2020)

#### :nail_care: Enhancement

- New artifact cli commands!

```shell
wandb artifact put path_file_or_ref
wandb artifact get artifact:version
wandb artifact ls project_name
```

- New artifact api commands!

```python
wandb.log_artifact()
wandb.use_artifact()
wandb.Api().artifact_versions()
wandb.Api().run.used_artifacts()
wandb.Api().run.logged_artifacts()
wandb.Api().Artifact().file()
```

- Improved syncing of large wandb-history.jsonl files for wandb sync
- New Artifact.verify method to ensure the integrity of local artifacts
- Better testing harness for api commands
- Run directory now store local time instead of utc time in the name, thanks @aiyolo!
- Improvements to our doc strings across the board.
- wandb.Table now supports a `dataframe` argument for logging dataframes as tables!

#### :bug: Bug Fix

- Artifacts work in python2
- Artifacts default download locations work in Windows
- GCS references now properly cache / download, thanks @yoks!
- Fix encoding of numpy arrays to JSON
- Fix string comparison error message

## 0.9.2 (June 29, 2020)

#### :nail_care: Enhancement

- Major overhaul of artifact caching
- Configurable cache directory for artifacts
- Configurable download directory for artifacts
- New Artifact.verify method to ensure the integrity of local artifacts
- use_artifact no longer requires `type`
- Deleted artifacts can now be be recommitted
- Lidar scenes now support vectors

#### :bug: Bug Fix

- Fix issue with artifact downloads returning errors.
- Segmentation masks now handle non-unint8 data
- Fixed path parsing logic in `api.runs()`

## 0.9.1 (June 9, 2020)

#### :bug: Bug Fix

- Fix issue where files were always logged to latest run in a project.
- Fix issue where url was not display url on first call to wandb.init

## 0.9.0 (June 5, 2020)

#### :bug: Bug Fix

- Handle multiple inits in Jupyter
- Handle ValueError's when capturing signals, thanks @jsbroks
- wandb agent handles rate limiting properly

#### :nail_care: Enhancement

- wandb.Artifact is now generally available!
- feature_importances now supports CatBoost, thanks @neomatrix369

## 0.8.36 (May 11, 2020)

#### :bug: Bug Fix

- Catch all exceptions when saving Jupyter sessions
- validation_data automatically set in TF >= 2.2
- _implements_\* hooks now implemented in keras callback for TF >= 2.2

#### :nail_care: Enhancement

- Raw source code saving now disabled by default
- We now support global settings on boot to enable code saving on the server
- New `code_save=True` argument to wandb.init to enable code saving manually

## 0.8.35 (May 1, 2020)

#### :bug: Bug Fix

- Ensure cells don't hang on completion
- Fixed jupyter integration in PyCharm shells
- Made session history saving handle None metadata in outputs

## 0.8.34 (Apr 28, 2020)

#### :nail_care: Enhancement

- Save session history in jupyter notebooks
- Kaggle internet enable notification
- Extend wandb.plots.feature_importances to work with more model types, thanks @neomatrix369!

#### :bug: Bug Fix

- Code saving for jupyter notebooks restored
- Fixed thread errors in jupyter
- Ensure final history rows aren't dropped in jupyter

## 0.8.33 (Apr 24, 2020)

#### :nail_care: Enhancement

- Add default class labels for semantic segmentation
- Enhance bounding box API to be similar to semantic segmentation API

#### :bug: Bug Fix

- Increase media table rows to improve ROC/PR curve logging
- Fix issue where pre binned histograms were not being handled properly
- Handle nan values in pytorch histograms
- Fix handling of binary image masks

## 0.8.32 (Apr 14, 2020)

#### :nail_care: Enhancement

- Improve semantic segmentation image mask logging

## 0.8.31 (Mar 19, 2020)

#### :nail_care: Enhancement

- Close all open files to avoice ResourceWarnings, thanks @CrafterKolyan!

#### :bug: Bug Fix

- Parse "tensor" protobufs, fixing issues with tensorboard syncing in 2.1

## 0.8.30 (Mar 19, 2020)

#### :nail_care: Enhancement

- Add ROC, precision_recall, HeatMap, explainText, POS, and NER to wandb.plots
- Add wandb.Molecule() logging
- Capture kaggle runs for metrics
- Add ability to watch from run object

#### :bug: Bug Fix

- Avoid accidently picking up global debugging logs

## 0.8.29 (Mar 5, 2020)

#### :nail_care: Enhancement

- Improve bounding box annotations
- Log active GPU system metrics
- Only writing wandb/settings file if wandb init is called
- Improvements to wandb local command

#### :bug: Bug Fix

- Fix GPU logging on some devices without power metrics
- Fix sweep config command handling
- Fix tensorflow string logging

## 0.8.28 (Feb 21, 2020)

#### :nail_care: Enhancement

- Added code saving of main python module
- Added ability to specify metadata for bounding boxes and segmentation masks

#### :bug: Bug Fix

- Fix situations where uncommitted data from wandb.log() is not persisted

## 0.8.27 (Feb 11, 2020)

#### :bug: Bug Fix

- Fix dependency conflict with new versions of six package

## 0.8.26 (Feb 10, 2020)

#### :nail_care: Enhancement

- Add best metric and epoch to run summary with Keras callback
- Added wandb.run.config_static for environments required pickled config

#### :bug: Bug Fix

- Fixed regression causing failures with wandb.watch() and DataParallel
- Improved compatibility with python 3.8
- Fix model logging under windows

## 0.8.25 (Feb 4, 2020)

#### :bug: Bug Fix

- Fix exception when using wandb.watch() in a notebook
- Improve support for sparse tensor gradient logging on GPUs

## 0.8.24 (Feb 3, 2020)

#### :bug: Bug Fix

- Relax version dependency for PyYAML for users with old environments

## 0.8.23 (Feb 3, 2020)

#### :nail_care: Enhancement

- Added scikit-learn support
- Added ability to specify/exclude specific keys when building wandb.config

#### :bug: Bug Fix

- Fix wandb.watch() on sparse tensors
- Fix incompatibilty with ray 0.8.1
- Fix missing pyyaml requirement
- Fix "W&B process failed to launch" problems
- Improved ability to log large model graphs and plots

## 0.8.22 (Jan 24, 2020)

#### :nail_care: Enhancement

- Added ability to configure agent commandline from sweep config

#### :bug: Bug Fix

- Fix fast.ai prediction logging
- Fix logging of eager tensorflow tensors
- Fix jupyter issues with logging notebook name and wandb.watch()

## 0.8.21 (Jan 15, 2020)

#### :nail_care: Enhancement

- Ignore wandb.init() specified project and entity when running a sweep

#### :bug: Bug Fix

- Fix agent "flapping" detection
- Fix local controller not starting when sweep is pending

## 0.8.20 (Jan 10, 2020)

#### :nail_care: Enhancement

- Added support for LightGBM
- Added local board support (Experimental)
- Added ability to modify sweep configuration
- Added GPU power logging to system metrics

#### :bug: Bug Fix

- Prevent sweep agent from failing continuously when misconfigured

## 0.8.19 (Dec 18, 2019)

#### :nail_care: Enhancement

- Added beta support for ray/tune hyperopt search strategy
- Added ability to specify max runs per agent
- Improve experience starting a sweep without a project already created

#### :bug: Bug Fix

- Fix repeated wandb.Api().Run(id).scan_history() calls get updated data
- Fix early_terminate/hyperband in notebook/python environments

## 0.8.18 (Dec 4, 2019)

#### :nail_care: Enhancement

- Added min_step and max_step to run.scan_history for grabbing sub-sections of metrics
- wandb.init(reinit=True) now automatically calls wandb.join() to better support multiple runs per process

#### :bug: Bug Fix

- wandb.init(sync_tensorboard=True) works again for TensorFlow 2.0

## 0.8.17 (Dec 2, 2019)

#### :nail_care: Enhancement

- Handle tags being passed in as a string

#### :bug: Bug Fix

- Pin graphql-core < 3.0.0 to fix install errors
- TQDM progress bars update logs properly
- Oversized summary or history logs are now dropped which prevents retry hanging

## 0.8.16 (Nov 21, 2019)

#### :bug: Bug Fix

- Fix regression syncing some versions of Tensorboard since 0.8.13
- Fix network error in Jupyter

## 0.8.15 (Nov 5, 2019)

#### :bug: Bug Fix

- Fix calling wandb.init with sync_tensorboard multiple times in Jupyter
- Fix RuntimeError race when using threads and calling wandb.log
- Don't initialize Sentry when error reporting is disabled

#### :nail_care: Enhancement

- Added best_run() to wandb.sweep() public Api objects
- Remove internal tracking keys from wandb.config objects in the public Api

## 0.8.14 (Nov 1, 2019)

#### :bug: Bug Fix

- Improve large object warning when values reach maximum size
- Warn when wandb.save isn't passed a string
- Run stopping from the UI works since regressing in 0.8.12
- Restoring a file that already exists locally works
- Fixed TensorBoard incorrectly placing some keys in the wrong step since 0.8.10
- wandb.Video only accepts uint8 instead of incorrectly converting to floats
- SageMaker environment detection is now more robust
- Resuming correctly populates config
- wandb.restore respects root when run.dir is set #658
- Calling wandb.watch multiple times properly namespaces histograms and graphs

#### :nail_care: Enhancement

- Sweeps now work in Windows!
- Added sweep attribute to Run in the public api
- Added sweep link to Jupyter and terminal output
- TensorBoard logging now stores proper timestamps when importing historic results
- TensorBoard logging now supports configuring rate_limits and filtering event types
- Use simple output mirroring stdout doesn't have a file descriptor
- Write wandb meta files to the system temp directory if the local directory isn't writable
- Added beta api.reports to the public API
- Added wandb.unwatch to remove hooks from pytorch models
- Store the framework used in config.\_wandb

## 0.8.13 (Oct 15, 2019)

#### :bug: Bug Fix

- Create nested directory when videos are logged from tensorboard namespaces
- Fix race when using wandb.log `async=True`
- run.summary acts like a proper dictionary
- run.summary sub dictionaries properly render
- handle None when passing class_colors for segmentation masks
- handle tensorflow2 not having a SessionHook
- properly escape args in windows
- fix hanging login when in anonymode
- tf2 keras patch now handles missing callbacks args

#### :nail_care: Enhancement

- Updates documentation autogenerated from docstrings in /docs
- wandb.init(config=config_dict) does not update sweep specified parameters
- wandb.config object now has a setdefaults method enabling improved sweep support
- Improved terminal and jupyter message incorporating :rocket: emojii!
- Allow wandb.watch to be called multiple times on different models
- Improved support for watching multiple tfevent files
- Windows no longer requires `wandb run` simply run `python script_name.py`
- `wandb agent` now works on windows.
- Nice error message when wandb.log is called without a dict
- Keras callback has a new `log_batch_frequency` for logging metrics every N batches

## 0.8.12 (Sep 20, 2019)

#### :bug: Bug Fix

- Fix compatibility issue with python 2.7 and old pip dependencies

#### :nail_care: Enhancement

- Improved onboarding flow when creating new accounts and entering api_key

## 0.8.11 (Sep 19, 2019)

#### :bug: Bug Fix

- Fix public api returning incorrect data when config value is 0 or False
- Resumed runs no longer overwrite run names with run id

#### :nail_care: Enhancement

- Added recording of spell.run id in config

## 0.8.10 (Sep 13, 2019)

#### :bug: Bug Fix

- wandb magic handles the case of tf.keras and keras being loaded
- tensorboard logging won't drop steps if multiple loggers have different global_steps
- keras gradient logging works in the latest tf.keras
- keras validation_data is properly set in tensorflow 2
- wandb pull command creates directories if they don't exist, thanks @chmod644
- file upload batching now asserts a minimum size
- sweeps works in python2 again
- scan_history now iterates the full set of points
- jupyter will run local mode if credentials can't be obtained

#### :nail_care: Enhancement

- Sweeps can now be run from within jupyter / directly from python! https://docs.wandb.com/sweeps/python
- New openai gym integration will automatically log videos, enabled with the monitor_gym keyword argument to wandb.init
- Ray Tune logging callback in wandb.ray.WandbLogger
- New global config file in ~/.config/wandb for global settings
- Added tests for fastai, thanks @borisdayma
- Public api performance enhancements
- Deprecated username in favor of entity in the public api for consistency
- Anonymous login support enabled by default
- New wandb.login method to be used in jupyter enabling anonymous logins
- Better dependency error messages for data frames
- Initial integration with spell.run
- All images are now rendered as PNG to avoid JPEG artifacts
- Public api now has a projects field

## 0.8.9 (Aug 19, 2019)

#### :bug: Bug Fix

- run.summary updates work in jupyter before log is called
- don't require numpy to be installed
- Setting nested keys in summary works
- notebooks in nested directories are properly saved
- Don't retry 404's / better error messaging from the server
- Strip leading slashes when loading paths in the public api

#### :nail_care: Enhancement

- Small files are batch uploaded as gzipped tarballs
- TensorBoardX gifs are logged to wandb

## 0.8.8 (Aug 13, 2019)

#### :bug: Bug Fix

- wandb.init properly handles network failures on startup
- Keras callback only logs examples if data_type or input_type is set
- Fix edge case PyTorch model logging bug
- Handle patching tensorboard multiple times in jupyter
- Sweep picks up config.yaml from the run directory
- Dataframes handle integer labels
- Handle invalid JSON when querying jupyter servers

#### :nail_care: Enhancement

- fastai uses a fixed seed for example logging
- increased the max number of images for fastai callback
- new wandb.Video tag for logging video
- sync=False argument to wandb.log moves logging to a thread
- New local sweep controller for custom search logic
- Anonymous login support for easier onboarding
- Calling wandb.init multiple times in jupyter doesn't error out

## 0.8.7 (Aug 7, 2019)

#### :bug: Bug Fix

- keras callback no longer guesses input_type for 2D data
- wandb.Image handles images with 1px height

#### :nail_care: Enhancement

- wandb Public API now has `run.scan_history` to return all history rows
- wandb.config prints helpful errors if used before calling init
- wandb.summary prints helpful errors if used before calling init
- filestream api points to new url on the backend

## 0.8.6 (July 31, 2019)

#### :bug: Bug Fix

- fastai callback uses the default monitor instead of assuming val_loss
- notebook introspections handles error cases and doesn't print stacktrace on failure
- Don't print description warning when setting name
- Fixed dataframe logging error with the keras callback
- Fixed line offsets in logs when resuming runs
- wandb.config casts non-builtins before writing to yaml
- vendored backports.tempfile to address missing package on install

#### :nail_care: Enhancement

- Added `api.sweep` to the python export api for querying sweeps
- Added `WANDB_NOTEBOOK_NAME` for specifying the notebook name in cases we can't infer it
- Added `WANDB_HOST` to override hostnames
- Store if a run was run within jupyter
- wandb now supports stopping runs from the web ui
- Handle floats passed as step to `wandb.log`
- wandb.config has full unicode support
- sync the main file to wandb if code saving is enabled and it's untracked by git
- XGBoost callback: wandb.xgboost.wandb_callback()

## 0.8.5 (July 12, 2019)

#### :bug: Bug Fix

- Fixed plotly charts with large numpy arrays not rendering
- `wandb docker` works when nvidia is present
- Better error when non string keys are sent to log
- Relaxed pyyaml dependency to fix AMI installs
- Magic works in jupyter notebooks.

#### :nail_care: Enhancement

- New preview release of auto-dataframes for Keras
- Added input_type and output_type to the Keras callback for simpler config
- public api supports retrieving specific keys and custom xaxis

## 0.8.4 (July 8, 2019)

#### :bug: Bug Fix

- WANDB_IGNORE_GLOBS is respected on the final scan of files
- Unified run.id, run.name, and run.notes across all apis
- Handle funky terminal sizes when setting up our pseudo tty
- Fixed Jupyter notebook introspection logic
- run.summary.update() persists changes to the server
- tensorboard syncing is robust to invalid histograms and truncated files

#### :nail_care: Enhancement

- preview release of magic, calling wandb.init(magic=True) should automatically track config and metrics when possible
- cli now supports local installs of the backend
- fastai callback supports logging example images

## 0.8.3 (June 26, 2019)

#### :bug: Bug Fix

- image logging works in Windows
- wandb sync handles tfevents with a single timestep
- fix incorrect command in overview page for running runs
- handle histograms with > 512 bins when streaming tensorboard
- better error message when calling wandb sync on a file instead of a directory

#### :nail_care: Enhancement

- new helper function for handling hyperparameters in sweeps `wandb.config.user_items()`
- better mocking for improved testing

## 0.8.2 (June 20, 2019)

#### :bug: Bug Fix

- entity is persisted on wandb.run when queried from the server
- tmp files always use the temporary directory to avoid syncing
- raise error if file shrinks while uploading
- images log properly in windows
- upgraded pyyaml requirement to address CVE
- no longer store a history of rows to prevent memory leak

#### :nail_care: Enhancement

- summary now supports new dataframe format
- WANDB_SILENT environment variable writes all wandb messages to debug.log
- Improved error messages for windows and tensorboard logging
- output.log is uploaded at the end of each run
- metadata, requirements, and patches are uploaded at the beginning of a run
- when not running from a git repository, store the main python file
- added WANDB_DISABLE_CODE to prevent diffing and code saving
- when running in jupyter store the name of the notebook
- auto-login support for colab
- store url to colab notebook
- store the version of this library in config
- store sys.executable in metadata
- fastai callback no longer requires path
- wandb.init now accepts a notes argument
- The cli replaced the message argument with notes and name

## 0.8.1 (May 23, 2019)

#### :bug: Bug Fix

- wandb sync handles tensorboard embeddings
- wandb sync correctly handles images in tensorboard
- tf.keras correctly handles single input functional models
- wandb.Api().runs returns an iterator that's reusable
- WANDB_DIR within a hidden directory doesn't prevent syncing
- run.files() iterates over all files
- pytorch recursion too deep error

#### :nail_care: Enhancement

- wandb sync accepts an --ignore argument with globs to skip files
- run.summary now has an items() method for iterating over all keys

## 0.8.0 (May 17, 2019)

#### :bug: Bug Fix

- Better error messages on access denied
- Better error messages when optional packages aren't installed
- Urls printed to the terminal are url-escaped
- Namespaced tensorboard events work with histograms
- Public API now retries on failures and re-uses connection pool
- Catch git errors when remotes aren't pushed to origin
- Moved keras graph collection to on_train_begin to handle unbuilt models
- Handle more cases of not being able to save weights
- Updates to summary after resuming are persisted
- PyTorch histc logging fixed in 0.4.1
- Fixed `wandb sync` tensorboard import

#### :nail_care: Enhancement

- wandb.init(tensorboard=True) works with Tensorflow 2 and Eager Execution
- wandb.init(tensorboard=True) now works with tb-nightly and PyTorch
- Automatically log examples with tf.keras by adding missing validation_data
- Socket only binds to localhost for improved security and prevents firewall warnings in OSX
- Added user object to public api for getting the source user
- Added run.display_name to the public api
- Show display name in console output
- Added --tags, --job_group, and --job_type to `wandb run`
- Added environment variable for minimum time to run before considering crashed
- Added flake8 tests to CI, thanks @cclauss!

## 0.7.3 (April 15, 2019)

#### :bug: Bug Fix

- wandb-docker-run accepts image digests
- keras callback works in tensorflow2-alpha0
- keras model graph now puts input layer first

#### :nail_care: Enhancement

- PyTorch log frequency added for gradients and weights
- PyTorch logging performance enhancements
- wandb.init now accepts a name parameter for naming runs
- wandb.run.name reflects custom display names
- Improvements to nested summary values
- Deprecated wandb.Table.add_row in favor of wandb.Table.add_data
- Initial support for a fast.ai callback thanks to @borisdayma!

## 0.7.2 (March 19, 2019)

#### :bug: Bug Fix

- run.get_url resolves the default entity if one wasn't specified
- wandb restore accepts run paths with only slashes
- Fixed PyYaml deprecation warnings
- Added entrypoint shell script to manifest
- Strip newlines from cuda version

## 0.7.1 (March 14, 2019)

#### :bug: Bug Fix

- handle case insensitive docker credentials
- fix app_url for private cloud login flow
- don't retry 404's when starting sweep agents

## 0.7.0 (February 28, 2019)

#### :bug: Bug Fix

- ensure DNS lookup failures can't prevent startup
- centralized debug logging
- wandb agent waits longer to send a SIGKILL after sending SIGINT

#### :nail_care: Enhancement

- support for logging docker images with the WANDB_DOCKER env var
- WANDB_DOCKER automatically set when run in kubernetes
- new wandb-docker-run command to automatically set env vars and mount code
- wandb.restore supports launching docker for runs that ran with it
- python packages are now recorded and saved in a requirements.txt file
- cpu_count, gpu_count, gpu, os, and python version stored in wandb-metadata.json
- the export api now supports docker-like paths, i.e. username/project:run_id
- better first time user messages and login info

## 0.6.35 (January 29, 2019)

#### :bug: Bug Fix

- Improve error reporting for sweeps

## 0.6.34 (January 23, 2019)

#### :bug: Bug Fix

- fixed Jupyter logging, don't change logger level
- fixed resuming in Jupyter

#### :nail_care: Enhancement

- wandb.init now degrades gracefully if a user hasn't logged in to wandb
- added a **force** flag to wandb.init to require a machine to be logged in
- Tensorboard and TensorboardX logging is now automatically instrumented when enabled
- added a **tensorboard** to wandb.init which patches tensorboard for logging
- wandb.save handles now accepts a base path to files in sub directories
- wandb.tensorflow and wandb.tensorboard can now be accessed without directly importing
- `wandb sync` will now traverse a wandb run directory and sync all runs

## 0.6.33 (January 22, 2019)

#### :bug: Bug Fix

- Fixed race where wandb process could hang at the end of a run

## 0.6.32 (December 22, 2018)

#### :bug: Bug Fix

- Fix resuming in Jupyter on kernel restart
- wandb.save ensures files are pushed regardless of growth

#### :nail_care: Enhancement

- Added replace=True keyword to init for auto-resuming
- New run.resumed property that can be used to detect if we're resuming
- New run.step property to use for setting an initial epoch on resuming
- Made Keras callback save the best model as it improves

## 0.6.31 (December 20, 2018)

#### :bug: Bug Fix

- Really don't require numpy
- Better error message if wandb.log is called before wandb.init
- Prevent calling wandb.watch multiple times
- Handle datetime attributes in logs / plotly

#### :nail_care: Enhancement

- Add environment to sweeps
- Enable tagging in the public API and in wandb.init
- New media type wandb.Html for logging arbitrary html
- Add Public api.create_run method for custom integrations
- Added glob support to wandb.save, files save as they're written to
- Added wandb.restore for pulling files on resume

## 0.6.30 (December 6, 2018)

#### :bug: Bug Fix

- Added a timeout for generating diffs on large repos
- Fixed edge case where file syncing could hang
- Ensure all file changes are captured before exit
- Handle cases of sys.exit where code isn't passed
- Don't require numpy

#### :nail_care: Enhancement

- New `wandb sync` command that pushes a local directory to the cloud
- Support for syncing tfevents file during training
- Detect when running as TFJob and auto group
- New Kubeflow module with initial helpers for pipelines

## 0.6.29 (November 26, 2018)

#### :bug: Bug Fix

- Fixed history / summary bug

## 0.6.28 (November 24, 2018)

#### :nail_care: Enhancement

- Initial support for AWS SageMaker
- `hook_torch` renamed to `watch` with a deprecation warning
- Projects are automatically created if they don't exist
- Additional GPU memory_allocated metric added
- Keras Graph stores edges

#### :bug: Bug Fix

- PyTorch graph parsing is more robust
- Fixed PyTorch 0.3 support
- File download API supports WANDB_API_KEY authentication

## 0.6.27 (November 13, 2018)

#### :nail_care: Enhancement

- Sweeps work with new backend (early release).
- Summary tracks all history metrics unless they're overridden by directly writing
  to summary.
- Files support in data API.

#### :bug: Bug Fix

- Show ongoing media file uploads in final upload progress.

## 0.6.26 (November 9, 2018)

#### :nail_care: Enhancement

- wandb.Audio supports duration

#### :bug: Bug Fix

- Pass username header in filestream API

## 0.6.25 (November 8, 2018)

#### :nail_care: Enhancement

- New wandb.Audio data type.
- New step keyword argument when logging metrics
- Ability to specify run group and job type when calling wandb.init() or via
  environment variables. This enables automatic grouping of distributed training runs
  in the UI
- Ability to override username when using a service account API key

#### :bug: Bug Fix

- Handle non-tty environments in Python2
- Handle non-existing git binary
- Fix issue where sometimes the same image was logged twice during a Keras step

## 0.6.23 (October 19, 2018)

#### :nail_care: Enhancement

- PyTorch
  - Added a new `wandb.hook_torch` method which records the graph and logs gradients & parameters of pytorch models
  - `wandb.Image` detects pytorch tensors and uses **torchvision.utils.make_grid** to render the image.

#### :bug: Bug Fix

- `wandb restore` handles the case of not being run from within a git repo.

## 0.6.22 (October 18, 2018)

#### :bug: Bug Fix

- We now open stdout and stderr in raw mode in Python 2 ensuring tools like bpdb work.

## 0.6.21 (October 12, 2018)

#### :nail_care: Enhancement

- Catastrophic errors are now reported to Sentry unless WANDB_ERROR_REPORTING is set to false
- Improved error handling and messaging on startup

## 0.6.20 (October 5, 2018)

#### :bug: Bug Fix

- The first image when calling wandb.log was not being written, now it is
- `wandb.log` and `run.summary` now remove whitespace from keys

## 0.6.19 (October 5, 2018)

#### :bug: Bug Fix

- Vendored prompt_toolkit < 1.0.15 because the latest ipython is pinned > 2.0
- Lazy load wandb.h5 only if `summary` is accessed to improve Data API performance

#### :nail_care: Enhancement

- Jupyter
  - Deprecated `wandb.monitor` in favor of automatically starting system metrics after the first wandb.log call
  - Added new **%%wandb** jupyter magic method to display live results
  - Removed jupyter description iframe
- The Data API now supports `per_page` and `order` options to the `api.runs` method
- Initial support for wandb.Table logging
- Initial support for matplotlib logging
