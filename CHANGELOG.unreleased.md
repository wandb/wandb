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

### Added

- The Optuna and Ax sweep schedulers support `log_uniform` parameters, and `q_log_uniform` parameters with `q: 1` (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13363)

### Changed

- The Optuna and Ax sweep schedulers reject `int_uniform` parameters with fractional `min` or `max`, and `q_log_uniform_values` parameters with `q` other than 1 or `min` below 1, instead of sampling values W&B would not. Optuna sampled floats for these (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13064)

### Fixed

- The Optuna and Ax sweep schedulers sample `q_uniform` parameters at the multiples of `q` that W&B samples instead of at steps of `q` from `min`, as integers whenever `q` is a whole number (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13363)
