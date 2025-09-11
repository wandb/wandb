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

- Add DSPy integration: track evaluation metrics over time, log predictions and program signature evolution to W&B Tables, and save DSPy programs as W&B Artifacts (complete program or state as JSON/PKL) (@ayulockin in https://github.com/wandb/wandb/pull/10327)

### Fixed

- Sweeps: `command` run scripts that `import torch` should no longer freeze on Python 3.13 in non-Mac-default Python environments. (@kelu-wandb in https://github.com/wandb/wandb/pull/10489)
