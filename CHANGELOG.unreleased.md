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

### Fixed

- Add DSPy integration: track evaluation metrics over time, log predictions and program signature evolution to W&B Tables, and save DSPy programs as W&B Artifacts (complete program or state as JSON/PKL) (@ayulockin in https://github.com/wandb/wandb/pull/10327)
- Resuming a run with a different active run will now raise an error unless you call `run.finish()` first, or call `wandb.init()` with the parameter `reinit='create_new'` (@jacobromero in https://github.com/wandb/wandb/pull/10468)
- Sweeps: `command` run scripts that `import readline` whether directly or indirectly (e.g. `import torch` on Python 3.13) should no longer deadlock. (@kelu-wandb in https://github.com/wandb/wandb/pull/10489)
