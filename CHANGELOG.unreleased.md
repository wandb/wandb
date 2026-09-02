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

- LEET charts metrics against the custom x-axes set with `run.define_metric()`. A metric defined with a `step_metric`, directly or through a glob like `run.define_metric("train/*", step_metric="train/step")`, is plotted against that metric instead of the step counter, with the axis name shown as `[x: train/step]` in the chart header. Applies to runs viewed from local `.wandb` files (@dmitryduev in https://github.com/wandb/wandb/pull/12568)

### Changed

- LEET is faster on long runs: a 50k-step run loads in about half the time, frames render about 30 percent faster, and live chart updates no longer re-render every point (@dmitryduev in https://github.com/wandb/wandb/pull/12535, https://github.com/wandb/wandb/pull/12536, https://github.com/wandb/wandb/pull/12537, https://github.com/wandb/wandb/pull/12538, https://github.com/wandb/wandb/pull/12539)

### Deprecated

- `wandb.sandbox` is deprecated and will be removed in a future release. Use the `cwsandbox` package directly instead.

### Fixed

- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- System metrics are now collected as soon as monitoring starts instead of after the first sampling interval (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
- Fixed noisy CPU utilization and frequency metrics and overstated power metrics on Apple Silicon Macs. They now cover the whole sampling interval instead of a snapshot of about 10 milliseconds (@dmitryduev in https://github.com/wandb/wandb/pull/12676)
- Fixed the memory size of Apple Silicon Macs with 256 GB or more of RAM being reported as 0 GB (@dmitryduev in https://github.com/wandb/wandb/pull/12677)
- Fixed CPU and GPU temperature metrics on Apple Silicon Macs being skewed by invalid sensor readings (@dmitryduev in https://github.com/wandb/wandb/pull/12678)
