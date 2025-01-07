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

### Removed

- The `wandb.wandb_sdk.wandb_setup._setup()` function's `reset` parameter has been removed. Note that this is a private function, even though there appear to be usages outside of the repo. Please `wandb.teardown()` instead of `_setup(reset=True)`. (@timoffex in https://github.com/wandb/wandb/pull/9165)
- In the private `wandb.wandb_sdk.wandb_setup` module, the `logger` and `_set_logger` symbols have been removed (@timoffex in https://github.com/wandb/wandb/pull/9195)
