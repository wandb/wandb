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

### Changed

- Set default behavior to not create a W&B Job (@KyleGoyette in https://github.com/wandb/wandb/pull/8907)

### Removed

- Remove `wandb.Run.plot_table` method. The functionality is still available and should be accessed using `wandb.plot_table`, which is now the recommended way to use this feature. (@kptkin in https://github.com/wandb/wandb/pull/8686)
- Drop support for Python 3.7. (@kptkin in https://github.com/wandb/wandb/pull/8858)

### Fixed

- Fix `ultralytics` reporting if there are no positive examples in a validation batch. (@Jamil in https://github.com/wandb/wandb/pull/8870)
- Debug printing for hyperband stopping algorithm printed one char per line (@temporaer in https://github.com/wandb/wandb/pull/8955)
- Include the missing `log_params` argument when calling lightgbm's `wandb_callback` function. (@i-aki-y https://github.com/wandb/wandb/pull/8943)
