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

- Added support for creating custom Vega chart presets through the API. Users can now define and upload custom chart specifications that can be then reused across runs with wandb.plot_table() (@thanos-wandb in https://github.com/wandb/wandb/pull/9931)

### Removed

- Removed the legacy python implementation of the `service` process. The `legacy-service` option of `wandb.require` as well as the `x_require_legacy_service` and `x_disable_setproctitle` settings with the corresponding environment variables have been removed and will now raise an error if used (@dmitryduev in https://github.com/wandb/wandb/pull/9965)
