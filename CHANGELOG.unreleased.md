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

- `EvalTable` backed by the new CoreWeave Evaluation Service is now in public preview. See: https://docs.wandb.ai/models/evaltables (@kelu-wandb in https://github.com/wandb/wandb/pull/13173)

### Changed

- The Optuna and Ax sweep schedulers reject `int_uniform` parameters with fractional `min` or `max`, and `q_log_uniform_values` parameters with `q` other than 1 or `min` below 1, instead of sampling values W&B would not. Optuna sampled floats for these (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13064)

### Fixed

- Made the `wandb-summary.json` file have the correct contents again. This was a regression in 0.31.1 (@timoffex in https://github.com/wandb/wandb/pull/13425)
