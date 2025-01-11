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

- Upgrade go version for `wandb-core` from 1.23.x to 1.24.x (@kptkin in https://github.com/wandb/wandb/pull/9590)
