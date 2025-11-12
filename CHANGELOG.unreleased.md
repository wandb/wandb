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

## Notable Changes

The `wandb sync --clean` command now exits with code 1 and prints a hint to use `wandb clean`, which is the replacement.
`wandb login` now verifies credentials by default. This can be disabled with `wandb login --no-verify` or programmatically with `wandb.login(verify=False)`.

## Added

- Added support for gzip compression of filestream requests, reducing network traffic when logging metrics. It is currently opt-in and requires server support: set `x_file_stream_no_gzip=False` in `wandb.Settings` to enable it. Compression will become the default in a future release (@dmitryduev in https://github.com/wandb/wandb/pull/12262)
- Added a `--term-timeout` flag to `wandb agent` (@nathancy-wandb in https://github.com/wandb/wandb/pull/12246)
- Added `run.sync_dir` (@timoffex in https://github.com/wandb/wandb/pull/12319)
- The automations API now supports team and organization scopes. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12197, https://github.com/wandb/wandb/pull/12194)
- The automations API now supports creating and editing automations whose scope is a `Registry` object (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10867)

## Changed

- The new `wandb clean` command replaces `wandb sync --clean` (@timoffex in https://github.com/wandb/wandb/pull/12238)
- Hardened argument handling in `wandb launch` for the local-process resource so that job-supplied values are always shell-quoted (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12220)
- The launch agent now restricts a job's git source URL to https/ssh remotes and pins git's protocol allowlist when fetching it and updating submodules (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12221)
- Response parsing is now faster for many `wandb.Api` operations, including artifact and registry queries (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12213)
- `wandb.init()` now reports the error it was retrying (such as a network error) when it times out, instead of a generic timeout message. The `init_timeout` setting now also bounds the backend's retries during run initialization (@skhanna-cw in https://github.com/wandb/wandb/pull/12216)
- `wandb.Api().create_run_queue()`, `wandb.Api().create_custom_chart()`, and `wandb.Api().upsert_run_queue()` now raise `WandbApiFailedError` when the operation fails on the backend. (@jacobromero in https://github.com/wandb/wandb/pull/12307)
- `Api.{create,update}_automation()` now raise `UnsupportedError` instead of `CommError` when the server doesn't support the given automation (@tonyyli-wandb in https://github.com/wandb/wandb/pull/12194)

## Removed

- Releases no longer include 32-bit Windows (`win32`) wheels; use 64-bit Python on Windows (@dmitryduev in https://github.com/wandb/wandb/pull/12267)

## Fixed

- Registry search `registries(order=...).collections(order=...).versions()` now returns artifact versions in registry and/or collection order. (@ibindlish in https://github.com/wandb/wandb/pull/12154)
- macOS x86_64 wheels now contain x86_64 builds of the `wandb-xpu` binary and the Rust parquet library, which previously shipped as arm64 and could not run or be loaded on Intel Macs (@dmitryduev in https://github.com/wandb/wandb/pull/12267)
- `wandb.login(verify=True)` and `wandb login --verify` now verify federated identity (identity token) credentials, which were previously not verified (@dmitryduev in https://github.com/wandb/wandb/pull/12294)
- `wandb login` and `wandb verify` no longer update the system host settings when failing to login (@jacobromero in https://github.com/wandb/wandb/pull/12332)
- `wandb verify` now reports a failed check instead of crashing when an operation still fails after retries (@dmitryduev in https://github.com/wandb/wandb/pull/12360)
- Calling Sweeps agent with a custom `WANDB_DIR` will now respect it when dumping JSON output (@kelu-wandb in https://github.com/wandb/wandb/pull/12344)
- Fixed `wandb.Api(overrides={"base_url": ...})` failing to authenticate with federated identity (identity token) credentials when the specified server was not the default one, such as a dedicated cloud deployment, unless `WANDB_BASE_URL` was also set (@dmitryduev in https://github.com/wandb/wandb/pull/12340)
- When using federated identity, the identity token file is now re-read for each access token exchange instead of once at startup, so short-lived identity tokens re-minted to the same path keep working for runs that outlive them (@dmitryduev in https://github.com/wandb/wandb/pull/12341)
- When using federated identity, requests now fail immediately with the server's error message when the server rejects the identity token exchange, such as for an invalid or expired identity token. Previously, the rejected exchange was retried until requests timed out with a generic error (@dmitryduev in https://github.com/wandb/wandb/pull/12366)
- `wandb login` validates api keys prior to saving to the `.netrc` file (@jacobromero in https://github.com/wandb/wandb/pull/12347)
- The `global_step` metric created when syncing TensorBoard files is no longer prefixed, like `train/global_step`, so that it is easier to compare training and validation metrics (@timoffex in https://github.com/wandb/wandb/pull/12372)
- The TensorBoard integration now produces fewer W&B steps by merging data for the same `global_step` into one W&B step when possible (@timoffex in https://github.com/wandb/wandb/pull/12414)
