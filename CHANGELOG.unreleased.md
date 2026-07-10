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

### Changed

- Remove temporary Unix socket files and directories on shutdown (@geoffhardy in https://github.com/wandb/wandb/pull/12058)
- `wandb beta sync` now skips online runs by default like `wandb sync` (@timoffex in https://github.com/wandb/wandb/pull/12087)
- `wandb sync` now routes to `wandb beta sync` for supported parameter sets (@timoffex in https://github.com/wandb/wandb/pull/12093)
  - Restore original behavior with `--legacy`
- Dropped support for protobuf v4 (@jacobromero in https://github.com/wandb/wandb/pull/12115)
- `wandb.sandbox` now defaults serverless sandboxes to a 12-hour max lifetime (`max_lifetime_seconds=43200`); override per sandbox with `max_lifetime_seconds` or via `SandboxDefaults` (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12136)

### Removed

- Removed legacy fallback implementations for downloading artifact files on older EOL W&B Server releases. The following will no longer work on EOL servers: `Artifact.files()` and `Artifact.download()` on any artifact, as well as `Artifact.get_entry()` / `Artifact.get_path()` file downloads on non-reference artifacts. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12109)
  - To continue using these operations, upgrade your W&B Server to `v0.70.0` or newer.
- Removed legacy fallback implementations for fetching an artifact by name on older EOL W&B Server releases. The following will no longer work on EOL servers: `wandb.Api().artifact(...)` and other methods that fetch artifact(s) by their path. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12112)
  - To continue using these operations, upgrade your W&B Server to `v0.70.0` or newer.

### Removed

- Removed the `GitPython` dependency. Git metadata is collected by invoking the `git` executable directly; the `GIT_PYTHON_GIT_EXECUTABLE` environment variable is still honored for locating it (@dmitryduev in https://github.com/wandb/wandb/pull/11983)

### Fixed

- Saving a linked registry artifact (for example, when adding an alias) no longer fails when the caller lacks write access to the source project (@ibindlish in https://github.com/wandb/wandb/pull/12075)
- `np.float16`/`np.float32` NaN values logged with `Run.log()` are now recorded as `NaN` instead of being silently dropped, matching `np.float64` and native `float` (@dmitryduev in https://github.com/wandb/wandb/pull/12116)
- `Run.upload_file()` (via `wandb.Api().run(...)`) now registers the uploaded file with the run on self-hosted servers. Previously the file's bytes were uploaded but never committed, so the file did not appear on the run on deployments without object-store notifications (@dmitryduev in https://github.com/wandb/wandb/pull/12121)
- Registry search `registries(order=...).collections(order=...).versions()` now returns artifact versions in registry and/or collection order.  (@ibindlish in https://github.com/wandb/wandb/pull/12154)
- Ordered registry search now scopes per-registry collection and version queries with a decoded project id (`id` on servers with advanced registry search, `project_id` otherwise), in addition to registry name (@ibindlish in https://github.com/wandb/wandb/pull/12188)
