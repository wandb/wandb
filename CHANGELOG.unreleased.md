# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

* Added - for new features.
* Changed  - for changes in existing functionality.
* Deprecated - for soon-to-be removed features.
* Removed - for now removed features.
* Fixed - for any bug fixes.
* Security -  in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Removed

- Remove `wandb.Run.plot_table` method. The functionality is still available and should be accessed using `wandb.plot_table`, which is now the recommended way to use this feature. (@kptkin in https://github.com/wandb/wandb/pull/8686)
