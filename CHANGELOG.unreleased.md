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

## Added
- Added the `wandb clean` command, which replaces `wandb sync --clean` (@timoffex in https://github.com/wandb/wandb/pull/12238)
- Method Api().sweep().log() appends log lines to the sweep using a batching filestream writer (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12261)
- Added support for gzip compression of filestream requests, reducing network traffic when logging metrics. It is currently opt-in and requires server support: set `x_file_stream_no_gzip=False` in `wandb.Settings` to enable it. Compression will become the default in a future release (@dmitryduev in https://github.com/wandb/wandb/pull/12262)

## Changed
- Hardened argument handling in `wandb launch` for the local-process resource so that job-supplied values are always shell-quoted (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12220)
- The launch agent now restricts a job's git source URL to https/ssh remotes and pins git's protocol allowlist when fetching it and updating submodules (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12221)
- Response parsing is now faster for many `wandb.Api` operations, including artifact and registry queries (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12213)

## Removed
- Releases no longer include 32-bit Windows (`win32`) wheels; use 64-bit Python on Windows (@dmitryduev in https://github.com/wandb/wandb/pull/12267)

## Fixed
- Registry search `registries(order=...).collections(order=...).versions()` now returns artifact versions in registry and/or collection order.  (@ibindlish in https://github.com/wandb/wandb/pull/12154)
- macOS x86_64 wheels now contain x86_64 builds of the `wandb-xpu` binary and the Rust parquet library, which previously shipped as arm64 and could not run or be loaded on Intel Macs (@dmitryduev in https://github.com/wandb/wandb/pull/12267)
