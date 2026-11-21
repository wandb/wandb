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

- In W&B LEET TUI, `wandb leet <project-url>` browses the runs of a W&B project, Esc on a run opened by its URL goes to its project, and remote runs that are still running update every 15 seconds (@jacobromero, @dmitryduev in https://github.com/wandb/wandb/pull/12942)
- LEET shows the system metrics of runs opened from a W&B server with `wandb leet <run-url>` or from a project view (@jacobromero, @dmitryduev in https://github.com/wandb/wandb/pull/13217)
- In LEET, the system metrics of a remote run that is still running update every 15 seconds along with its history (@dmitryduev in https://github.com/wandb/wandb/pull/13219)
- The TPU system metadata of runs on multi-host or multislice GKE TPU pods now includes the host's worker index and count within its slice and the slice index and count (`tpu.worker_id`, `tpu.worker_count`, `tpu.slice_id`, `tpu.num_slices`), read from the `TPU_WORKER_ID`, `TPU_WORKER_HOSTNAMES`, `MEGASCALE_SLICE_ID` and `MEGASCALE_NUM_SLICES` environment variables (@dmitryduev in https://github.com/wandb/wandb/pull/11792)
- System metrics and hardware metadata are collected on Google TPU 8t and TPU 8i hosts (@dmitryduev in https://github.com/wandb/wandb/pull/13340)
- The automations API supports sandbox events: `OnSandboxState` fires when a W&B sandbox in a project or team is created, completes or fails, filtered with `SandboxEvent.state` (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/13281)
- `backup_sync_dir_fn` setting to run a function when during `run.finish` this can be used to save run sync data when a run is complete or gets cancelled (@jacobromero in https://github.com/wandb/wandb/pull/13371)
- `wandb leet`: `shift+↑` and `shift+↓` scroll the rows of a heatmap system chart that has more series than fit, so every CPU core or GPU can be inspected (@dmitryduev in https://github.com/wandb/wandb/pull/13189)
- `EvalTable` backed by the new CoreWeave Evaluation Service is now in public preview. See: https://docs.wandb.ai/models/evaltables (@kelu-wandb in https://github.com/wandb/wandb/pull/13173)

### Changed

- The Optuna and Ax sweep schedulers reject `int_uniform` parameters with fractional `min` or `max`, and `q_log_uniform_values` parameters with `q` other than 1 or `min` below 1, instead of sampling values W&B would not. Optuna sampled floats for these (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/13064)

### Fixed

- Made the `wandb-summary.json` file have the correct contents again. This was a regression in 0.31.1 (@timoffex in https://github.com/wandb/wandb/pull/13425)
