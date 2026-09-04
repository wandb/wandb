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

### Notable Changes

Legacy `wandb sync` options have been removed. See `wandb sync --help`.

### Added

- LEET charts metrics against the custom x-axes set with `run.define_metric()`. A metric defined with a `step_metric`, directly or through a glob like `run.define_metric("train/*", step_metric="train/step")`, is plotted against that metric instead of the step counter, with the axis name shown as `[x: train/step]` in the chart header. Applies to runs viewed from local `.wandb` files. Each chart has a single x-axis, so a run that plots a metric against a different axis is not shown on that chart (@dmitryduev in https://github.com/wandb/wandb/pull/12568, https://github.com/wandb/wandb/pull/12728)
- The automations API now supports sending a prompt to ARIA (`SendPromptToAria`) as an automation action. (@gdecarvalhovaz-lgtm in https://github.com/wandb/wandb/pull/12594)

### Changed

- LEET loads long runs faster: while a run's history is loading, the charts are redrawn at most ten times a second instead of after every 1000 records, which made loading time grow with the square of the run's length. A 100-metric run with 400k steps now opens in about 0.3 s instead of 3.8 s (@dmitryduev in https://github.com/wandb/wandb/pull/12734)
- LEET is faster on long runs: a 50k-step run loads in about half the time, frames render about 30 percent faster, and live chart updates no longer re-render every point (@dmitryduev in https://github.com/wandb/wandb/pull/12535, https://github.com/wandb/wandb/pull/12536, https://github.com/wandb/wandb/pull/12537, https://github.com/wandb/wandb/pull/12538, https://github.com/wandb/wandb/pull/12539)
- System metrics from Apple Silicon Macs become available about 1.5 seconds sooner after monitoring starts (@dmitryduev in https://github.com/wandb/wandb/pull/12679)

### Deprecated

- `wandb.sandbox` is deprecated and will be removed in a future release. Use the `cwsandbox` package directly instead.

### Fixed

- `wandb leet` no longer sends usage telemetry when W&B is in offline or disabled mode (`WANDB_MODE=offline` or `WANDB_MODE=disabled`), like the rest of the SDK (@dmitryduev in https://github.com/wandb/wandb/pull/12733)
- `wandb leet` now prints an error message when it cannot start, for example when it is run without a terminal; previously it exited with status 1 and no output. Debug logs (`WANDB_DEBUG=true`) are written next to the LEET config file instead of the current directory (@dmitryduev in https://github.com/wandb/wandb/pull/12732)
- LEET now hides the workspace's run overview sidebar, and then the runs list, when together they would leave the charts fewer than 24 columns wide; previously an 80-column terminal showed the charts as a one-column sliver between the two sidebars. The single-run view, which already did this, uses the same 24-column minimum instead of 10 (@dmitryduev in https://github.com/wandb/wandb/pull/12731)
- `wandb.Image` masks are no longer silently corrupted when `mask_data` is a float array with values outside 0-255. The range check previously only ran for integer dtypes, so out-of-range class ids were written to the saved mask wrapped modulo 256; they now raise `TypeError` like their integer equivalents already did (@Kayvan-Zahiri in https://github.com/wandb/wandb/pull/12685)
- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- System metrics are now collected as soon as monitoring starts instead of after the first sampling interval (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
- Fixed noisy CPU utilization and frequency metrics and overstated power metrics on Apple Silicon Macs. They now cover the whole sampling interval instead of a snapshot of about 10 milliseconds (@dmitryduev in https://github.com/wandb/wandb/pull/12676)
- Fixed the memory size of Apple Silicon Macs with 256 GB or more of RAM being reported as 0 GB (@dmitryduev in https://github.com/wandb/wandb/pull/12677)
- Fixed CPU and GPU temperature metrics on Apple Silicon Macs being skewed by invalid sensor readings (@dmitryduev in https://github.com/wandb/wandb/pull/12678)
- Fixed the `ecpu_cores` count of Apple M5 Pro and M5 Max Macs being reported as 0 (@dmitryduev in https://github.com/wandb/wandb/pull/12680)
- Fixed CPU frequency metrics on the MacBook Neo being reported about 1000 times too high (@dmitryduev in https://github.com/wandb/wandb/pull/12681)
- Fixed missing CPU utilization and frequency metrics for the efficiency cores of Apple M5 Macs and the performance cores of M5 Pro and M5 Max Macs (@dmitryduev in https://github.com/wandb/wandb/pull/12682)
- `wandb.init()` and `wandb.Api()` no longer stall for up to 10 seconds when the W&B server is slow to respond. This was a regression in 0.29.0 (@mitja-kleider and @jacobromero in https://github.com/wandb/wandb/pull/12697)
- Fixed the top y-axis label of LEET charts being cut off when it is wider than the other labels, showing for example `+03` instead of `1.09e+03` (@dmitryduev in https://github.com/wandb/wandb/pull/12727)

### Removed

- All legacy options to `wandb sync` have been removed (@timoffex in https://github.com/wandb/wandb/pull/12686)
  - In particular, instead of `--sync-all`, use `wandb sync` with no arguments
