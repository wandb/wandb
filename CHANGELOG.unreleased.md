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

- Added `wandb.public.Project.id` property to support fetching the project ID on a `wandb.public.Project` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9194).
- Added new programmatic API for W&B Automations, including:
  - New submodules in the `wandb.sdk.automations` namespace to support programmatic management of W&B Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8935).
  - `Api.integrations()`, `Api.slack_integrations()`, `Api.webhook_integrations()` to fetch existing integrations for an entity (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9197).
  - `Api.automation()`, `Api.automations()` to fetch existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.create_automation()` to create new Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.delete_automation()` to delete existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8896).
  - `Api.update_automation()` to edit existing Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9246).

### Changed

- changed moviepy constraint to >=1.0.0 (@jacobromero in https://github.com/wandb/wandb/pull/9419)
- `wandb.init()` displays more detailed information, in particular when it is stuck retrying HTTP errors (@timoffex in https://github.com/wandb/wandb/pull/9431)
- Paginated methods (and underlying paginators) that accept a `per_page` argument now only accept `int` values.  Default `per_page` values are set directly in method signatures, and explicitly passing `None` is no longer supported (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9201)

### Removed

- Removed the private `x_show_operation_stats` setting (@timoffex in https://github.com/wandb/wandb/pull/9427)

### Fixed

- Fixed incorrect logging of an "wandb.Video requires moviepy \[...\]" exception when using moviepy v2. (@Daraan in https://github.com/wandb/wandb/pull/9375)
- `wandb.setup()` correctly starts up the internal service process; this semantic was unintentionally broken in 0.19.2 (@timoffex in https://github.com/wandb/wandb/pull/9436)
