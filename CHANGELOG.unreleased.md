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
- Added new `wandb.sdk.automations` subpackage to support programmatic management of W&B Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8935).
- Added `Api.integrations()` to fetch existing integrations for an entity, as well as `Api.slack_integration()`, `Api.webhook_integration()` for convenience (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9197).

### Changed

- Paginated methods (and underlying paginators) that accept a `per_page` argument now only accept `int` values.  Default `per_page` values are set directly in method signatures, and explicitly passing `None` is no longer supported.
