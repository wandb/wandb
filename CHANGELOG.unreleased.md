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

### Notable Changes

This version drops support for protobuf v4, and requires protobuf v5 or newer.
This version drops compatibility with server versions older than 0.70.0.

### Added

- New filters parameter to `Api().project().sweeps()` matching the runs filter format (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12059)
- Added `Run.stop()` to the public API (`wandb.Api().run(...).stop()`) to programmatically request that an active run stop gracefully, like the "Stop run" button in the W&B App UI (@dmitryduev in https://github.com/wandb/wandb/pull/12159)
- Added `wandb.Api().organization()` to fetch an `Organization` by name, or the current default organization for the user (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12196)

### Changed

- Remove temporary Unix socket files and directories on shutdown (@geoffhardy in https://github.com/wandb/wandb/pull/12058)
- `wandb beta sync` now skips online runs by default like `wandb sync` (@timoffex in https://github.com/wandb/wandb/pull/12087)
- `wandb sync` now routes to `wandb beta sync` for supported parameter sets (@timoffex in https://github.com/wandb/wandb/pull/12093)
  - Restore original behavior with `--legacy`
- Dropped support for protobuf v4 (@jacobromero in https://github.com/wandb/wandb/pull/12115)
- `wandb.sandbox` now defaults serverless sandboxes to a 12-hour max lifetime (`max_lifetime_seconds=43200`); override per sandbox with `max_lifetime_seconds` or via `SandboxDefaults` (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12136)
- `wandb.Api().runs()` now raises a `RunNotFoundError` when unable to load data for a run, such as when a run is deleted prior to fully loading run data (@jacobromero in https://app.graphite.com/github/pr/wandb/wandb/12176)
- `wandb.save` now has an option `glob=False` that disables glob expansion (`*`, `?`, `[...]`) for file paths; updated docs for improved explanation (@geoffhardy in https://github.com/wandb/wandb/pull/12192)

### Removed

- Removed legacy fallback implementations for downloading artifact files on older EOL W&B Server releases. The following will no longer work on EOL servers: `Artifact.files()` and `Artifact.download()` on any artifact, as well as `Artifact.get_entry()` / `Artifact.get_path()` file downloads on non-reference artifacts. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12109)
  - To continue using these operations, upgrade your W&B Server to `v0.70.0` or newer.
- Removed legacy fallback implementations for fetching an artifact by name on older EOL W&B Server releases. The following will no longer work on EOL servers: `wandb.Api().artifact(...)` and other methods that fetch artifact(s) by their path. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12112)
  - To continue using these operations, upgrade your W&B Server to `v0.70.0` or newer.
- Removed the `GitPython` dependency. Git metadata is collected by invoking the `git` executable directly; the `GIT_PYTHON_GIT_EXECUTABLE` environment variable is still honored for locating it (@dmitryduev in https://github.com/wandb/wandb/pull/11983)

### Fixed

- Saving a linked registry artifact (for example, when adding an alias) no longer fails when the caller lacks write access to the source project (@ibindlish in https://github.com/wandb/wandb/pull/12075)
- `np.float16`/`np.float32` NaN values logged with `Run.log()` are now recorded as `NaN` instead of being silently dropped, matching `np.float64` and native `float` (@dmitryduev in https://github.com/wandb/wandb/pull/12116)
- `Run.upload_file()` (via `wandb.Api().run(...)`) now registers the uploaded file with the run on self-hosted servers. Previously the file's bytes were uploaded but never committed, so the file did not appear on the run on deployments without object-store notifications (@dmitryduev in https://github.com/wandb/wandb/pull/12121)
- Sweep agents will now allow the in-progress run to complete before exiting when the sweep is deleted or Api() returns 404 (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/11880)
- Fixed some deadlocks introduced in 0.25.1 (@timoffex in https://github.com/wandb/wandb/pull/12114 and https://github.com/wandb/wandb/pull/12159)
  - Reported when using PyTorch with Python < 3.14 (which uses the "fork" `multiprocessing` start method by default)
  - May have also happened during GC when using some `wandb.Api` functionality
