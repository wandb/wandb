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

### Changed

- The Optuna and Ax sweep schedulers reject `int_uniform` parameters with fractional `min` or `max`, and `q_log_uniform_values` parameters with `q` other than 1 or `min` below 1, instead of sampling values W&B would not. Optuna sampled floats for these (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13064)

### Fixed

- Linking an artifact to a registry that doesn't exist raises an error that names the registry and organization and explains how to create it with `wandb.Api().create_registry()` or in the W&B App, instead of claiming registries can only be created in the UI (@mrobers1982 in https://github.com/wandb/wandb/pull/13330)
