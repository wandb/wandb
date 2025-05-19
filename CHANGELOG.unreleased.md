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

This version removes the ability to disable the `service` process. This is a breaking change.

### Added

- Support for pytorch.tensor for `masks` and `boxes` parameters when creating a `wandb.Image` object. (jacobromero in https://github.com/wandb/wandb/pull/9802)
- `normalized` parameter to `wandb.Image` initialization to normalize pixel values for Images initialized with a numpy array or pytorch tensor. (@jacobromero in https://github.com/wandb/wandb/pull/9786)
- Added support for initializing some Media objects with `pathlib.Path` (@jacobromero in https://github.com/wandb/wandb/pull/9692)

### Removed

- Removed support for disabling the `service` process. The `x_disable_service`/`_disable_service` setting and the `WANDB_DISABLE_SERVICE`/`WANDB_X_DISABLE_SERVICE` environment variable have been deprecated and will now raise an error if used (@kptkin in https://github.com/wandb/wandb/pull/9829)

### Deprecated

- The `start_method` setting is deprecated and has no effect; it is safely ignored (@kptkin in https://github.com/wandb/wandb/pull/9837)

### Fixed

- Calling `wandb.teardown()` in a child of a process that called `wandb.setup()` no longer raises `WandbServiceNotOwnedError` (@timoffex in https://github.com/wandb/wandb/pull/9875)
    - This error could have manifested when using W&B Sweeps
- Offline runs with requested branching (fork or rewind) sync correctly (@dmitryduev in https://github.com/wandb/wandb/pull/9876)
