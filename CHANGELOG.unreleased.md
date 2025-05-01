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

- `is_link` property to artifacts to determine if an artifact is a link artifact (such as in the Registry) or source artifact. (@estellazx in https://github.com/wandb/wandb/pull/9764)
- Multipart download for artifact file larger than 2GB, user can control it directly using `artifact.download(multipart=True)`. (@pingleiwandb in https://github.com/wandb/wandb/pull/9738)
- `Project.id` property to get the project ID on a `wandb.public.Project` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9194).
- New public API for W&B Automations (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9693, https://github.com/wandb/wandb/pull/8935, https://github.com/wandb/wandb/pull/9194, https://github.com/wandb/wandb/pull/9197, https://github.com/wandb/wandb/pull/8896, https://github.com/wandb/wandb/pull/9246)
  - New submodules and classes in `wandb.automations.*` to support programmatically managing W&B Automations.
  - `Api.integrations()`, `Api.slack_integrations()`, `Api.webhook_integrations()` to fetch a team's existing Slack or webhook integrations.
  - `Api.create_automation()`, `Api.automation()`/`Api.automations()`, `Api.update_automation()`, `Api.delete_automation()` to create, fetch, edit, and delete Automations.
- Ability to collect profiling metrics for Nvidia GPUs using DCGM. To enable, set the `WANDB_ENABLE_DCGM_PROFILING` environment variable to `true`. Requires the `nvidia-dcgm` service to be running on the machine. Enabling this feature can lead to increased resource usage. (@dmitryduev in https://github.com/wandb/wandb/pull/9780)

### Fixed

- `run.log_code` correctly sets the run configs `code_path` value. (@jacobromero in https://github.com/wandb/wandb/pull/9753)
- Correctly use `WANDB_CONFIG_DIR` for determining system settings file path (@jacobromero in https://github.com/wandb/wandb/pull/9711)
- Prevent invalid `Artifact` and `ArtifactCollection` names (which would make them unloggable), explicitly raising a `ValueError` when attempting to assign an invalid name. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/8773)
- Prevent pydantic `ConfigError` in Pydantic v1 environments from not calling `.model_rebuild()/.update_forward_refs()` on generated types with ForwardRef fields (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9795)
