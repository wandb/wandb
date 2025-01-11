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
- Added `wandb.public.Project.id` property to support fetching the project ID on a `wandb.public.Project` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9194).
- Added new programmatic API for W&B Automations, including:
  - New submodules in the `wandb.automations` namespace to support programmatic management of W&B Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8935).
  - `Api.integrations()`, `Api.slack_integrations()`, `Api.webhook_integrations()` to fetch existing integrations for an entity (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9197).
  - `Api.automation()`, `Api.automations()` to fetch existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.create_automation()` to create new Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.delete_automation()` to delete existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.update_automation()` to edit existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9246).

### Changed

- `Artifact.download()` no longer raises an error when using `WANDB_MODE=offline` or when an offline run exists (@timoffex in https://github.com/wandb/wandb/pull/9695)

### Removed

- Dropped the `-q` / `--quiet` argument to the `wandb` magic in IPython / Jupyter; use the `quiet` run setting instead (@timoffex in https://github.com/wandb/wandb/pull/9705)

### Fixed

- Fixed ValueError on Windows when running a W&B script from a different drive (@jacobromero in https://github.com/wandb/wandb/pull/9678)
- Fix base_url setting was not provided to wandb.login (@jacobromero in https://github.com/wandb/wandb/pull/9703)
