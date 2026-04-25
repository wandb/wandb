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

- TPU system metadata now includes topology details such as JAX-compatible device kind, process counts, slice counts, and devices per slice; runs on GCP/GKE also capture project, zone, region, instance, orchestrator, and GKE workload metadata (@dmitryduev in https://github.com/wandb/wandb/pull/11792)
- The `stop_on_fatal_error` setting to stop a run (using `stop_fn`) after a fatal error that prevents it from uploading metrics (@timoffex in https://github.com/wandb/wandb/pull/11774)
- New `wandb.sandbox` package and the `wandb beta sandbox` cli for using wandb sandbox (@pingleiwandb in https://github.com/wandb/wandb/pull/11606)
- The `finish_timeout` and `finish_timeout_raises` settings (@timoffex in https://github.com/wandb/wandb/pull/11737)
