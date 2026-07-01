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
This version drops compatibility with server versions older than 0.67.0.

### Changed

- Remove temporary Unix socket files and directories on shutdown (@geoffhardy in https://github.com/wandb/wandb/pull/12058)
- `wandb beta sync` now skips online runs by default like `wandb sync` (@timoffex in https://github.com/wandb/wandb/pull/12087)
- `wandb sync` now routes to `wandb beta sync` for supported parameter sets (@timoffex in https://github.com/wandb/wandb/pull/12093)
  - Restore original behavior with `--legacy`
- Dropped support for protobuf v4 (@jacobromero in https://github.com/wandb/wandb/pull/12115)

### Removed

- Removed legacy support for listing and downloading artifact files on W&B Server releases older than `v0.67.0`, which are past EOL. This affects `Artifact.files()` and `Artifact.download()` for any artifact, as well as `Artifact.get_entry()` / `Artifact.get_path()` file downloads for non-reference artifacts. To keep using these operations, upgrade your W&B Server to `v0.67.0` or newer. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12109)

### Fixed

- Saving a linked registry artifact (for example, when adding an alias) no longer fails when the caller lacks write access to the source project (@ibindlish in https://github.com/wandb/wandb/pull/12075)
- `np.float16`/`np.float32` NaN values logged with `Run.log()` are now recorded as `NaN` instead of being silently dropped, matching `np.float64` and native `float` (@dmitryduev in https://github.com/wandb/wandb/pull/12116)
- `Run.upload_file()` (via `wandb.Api().run(...)`) now registers the uploaded file with the run on self-hosted servers. Previously the file's bytes were uploaded but never committed, so the file did not appear on the run on deployments without object-store notifications (@dmitryduev in https://github.com/wandb/wandb/pull/12117)
