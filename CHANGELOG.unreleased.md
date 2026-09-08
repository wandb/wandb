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

- `wandb.InternalApi`, the `wandb.PublicApi` and `wandb.apis.PublicApi` aliases, and the `wandb.apis.internal` and `wandb.sdk.internal.internal_api` modules have been removed. Use `wandb.Api()` instead.
- `wandb.api` and `wandb.ensure_configured()` are deprecated. Use `wandb.login(prompt=False)` to check whether the user is logged in, and `wandb.Api()` for everything else.
- The legacy `wandb sync` options have been removed. Run `wandb sync` with no arguments instead of `wandb sync --sync-all`, and use `--job-type` instead of `--job_type`. See `wandb sync --help`.

### Added

- `wandb.login(prompt=False)` uses the configured credentials when there are any and returns `False` otherwise, without asking for an API key or switching to offline mode. Use it to check whether the user is logged in without blocking (@dmitryduev in https://github.com/wandb/wandb/pull/12741)
- The automations API supports sending a prompt to ARIA as an automation action with `SendPromptToAria` (@gdecarvalhovaz-lgtm in https://github.com/wandb/wandb/pull/12594)
- W&B LEET TUI:
  - Charts with custom x-axes set with `run.define_metric(...)`, including glob definitions such as `run.define_metric("train/*", step_metric="train/step")`. The axis name is shown as `[x: train/step]` in the chart header. Applies to runs opened from local `.wandb` files (@dmitryduev in https://github.com/wandb/wandb/pull/12568, https://github.com/wandb/wandb/pull/12728)
  - Filter console logs: with the logs pane focused, press `/` and type a pattern (regex, or glob after `Tab`) to show only the matching lines. New matches are followed as they arrive, and `ctrl+/` clears the filter (@dmitryduev in https://github.com/wandb/wandb/pull/12736)
  - The metrics, system metrics and runs filters are remembered for each wandb directory and applied again the next time you open it, in both the workspace and the single-run view. They are stored in `.wandb-leet.json` inside the directory. Clearing a filter forgets it (@dmitryduev in https://github.com/wandb/wandb/pull/12735)
  - The border or separator line you drag to resize a pane or sidebar is highlighted while you drag it (@dmitryduev in https://github.com/wandb/wandb/pull/12617)

### Changed

- `wandb status --settings` no longer prints the API key, and `wandb projects` no longer prints project descriptions (@dmitryduev in https://github.com/wandb/wandb/pull/12723)
- System metrics on Apple Silicon Macs start about 1.5 seconds sooner after a run starts (@dmitryduev in https://github.com/wandb/wandb/pull/12679)
- W&B LEET TUI is faster on long runs: a run with 100 metrics and 400k steps opens 10 times faster, frames render about 30 percent faster, and live chart updates no longer redraw every point (@dmitryduev in https://github.com/wandb/wandb/pull/12535, https://github.com/wandb/wandb/pull/12536, https://github.com/wandb/wandb/pull/12537, https://github.com/wandb/wandb/pull/12538, https://github.com/wandb/wandb/pull/12539, https://github.com/wandb/wandb/pull/12734)

### Deprecated

- `wandb.api` and `wandb.ensure_configured()` are deprecated and will be removed in a future release. `wandb.api` now only provides `api_key`, `default_entity` and `viewer()`. Use `wandb.login(prompt=False)` to check whether the user is logged in, and `wandb.Api()` for the rest (@dmitryduev in https://github.com/wandb/wandb/pull/12715)
- `wandb.sandbox` and the `wandb beta sandbox` commands are deprecated and will be removed in a future release. Use the `cwsandbox` package directly (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/12647, https://github.com/wandb/wandb/pull/12689)

### Removed

- Removed `wandb.InternalApi`, the `wandb.PublicApi` and `wandb.apis.PublicApi` aliases, and the `wandb.apis.internal` and `wandb.sdk.internal.internal_api` modules. Use `wandb.Api()` instead (@dmitryduev in https://github.com/wandb/wandb/pull/12715, https://github.com/wandb/wandb/pull/12716, https://github.com/wandb/wandb/pull/12724)
- Removed the legacy `wandb sync` options. Run `wandb sync` with no arguments instead of `wandb sync --sync-all`, and use `--job-type` instead of `--job_type` (@timoffex in https://github.com/wandb/wandb/pull/12686)

### Fixed

- File uploads and downloads that take longer than 20 seconds no longer fail with `CommError: Failed to execute API request: the service process is busy and did not respond in time`. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
- `wandb.init()` and `wandb.Api()` no longer stall for up to 10 seconds when the W&B server is slow to respond. This was a regression in 0.29.0 (@mitja-kleider and @jacobromero in https://github.com/wandb/wandb/pull/12697)
- Requests rejected with HTTP 402 Payment Required, such as plan and quota limits including artifact usage limits, are no longer retried. The error is reported right away (@Vedant527 in https://github.com/wandb/wandb/pull/12628)
- Syncing a run whose artifacts were already uploaded no longer fails when the artifact files are no longer on disk. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12750)
- A failed artifact upload no longer deletes the files it was uploading, so `wandb sync` can retry it. After a successful upload, only files in the artifact's staging directory are cleaned up (@dmitryduev in https://github.com/wandb/wandb/pull/12749)
- `wandb sync` now explains when a `.wandb` file ends with an incomplete record, which happens while the run is still writing or after it was killed mid-write, and how to retry, instead of reporting an internal error (@dmitryduev in https://github.com/wandb/wandb/pull/12751)
- Passing `aliases` or `tags` to `Run.log_artifact()` in the public API no longer fails with a server error (@dmitryduev in https://github.com/wandb/wandb/pull/12719)
- `wandb.Image` masks given as float arrays with values outside 0-255 now raise `TypeError`, as integer arrays already did, instead of being saved with wrong class ids (@Kayvan-Zahiri in https://github.com/wandb/wandb/pull/12685)
- System metrics are collected as soon as a run starts instead of one sampling interval (15 seconds by default) later, so short runs record system metrics and system charts no longer start with a gap (@dmitryduev in https://github.com/wandb/wandb/pull/12649)
- `wandb.init()` no longer waits up to 5 seconds for the GPU and TPU metrics collector to start (@dmitryduev in https://github.com/wandb/wandb/pull/12651)
- In Jupyter notebooks, system metrics are collected while a cell runs and paused between cells. Since 0.19.10 the two were swapped, so system metrics were only collected while the notebook was idle (@timoffex in https://github.com/wandb/wandb/pull/12646)
- On machines with AMD GPUs, system metrics monitoring no longer runs `rocm-smi` up front, which took 1 to 3 seconds, and no longer crashes when `rocm-smi` reports no GPUs (@dmitryduev in https://github.com/wandb/wandb/pull/12652)
- System metrics on Apple Silicon Macs:
  - CPU utilization, frequency and power now cover the whole sampling interval instead of a snapshot of about 10 milliseconds, which made utilization and frequency noisy and overstated power by about 25 percent (@dmitryduev in https://github.com/wandb/wandb/pull/12676)
  - Macs with 256 GB or more of RAM no longer report a memory size of 0 GB (@dmitryduev in https://github.com/wandb/wandb/pull/12677)
  - CPU and GPU temperatures are no longer skewed by invalid sensor readings (@dmitryduev in https://github.com/wandb/wandb/pull/12678)
  - M5 Pro and M5 Max Macs no longer report 0 efficiency cores (@dmitryduev in https://github.com/wandb/wandb/pull/12680)
  - CPU frequencies on the MacBook Neo are no longer reported about 1000 times too high (@dmitryduev in https://github.com/wandb/wandb/pull/12681)
  - CPU utilization and frequency are now collected for the efficiency cores of M5 Macs and the performance cores of M5 Pro and M5 Max Macs, which were missing (@dmitryduev in https://github.com/wandb/wandb/pull/12682)
- W&B LEET TUI:
  - `wandb leet` prints an error when it cannot start, for example without a terminal, instead of exiting with status 1 and no output. Debug logs (`WANDB_DEBUG=true`) are written next to the LEET config file instead of the current directory (@dmitryduev in https://github.com/wandb/wandb/pull/12732)
  - `wandb leet` no longer sends usage telemetry in offline or disabled mode (`WANDB_MODE=offline` or `WANDB_MODE=disabled`), like the rest of the SDK (@dmitryduev in https://github.com/wandb/wandb/pull/12733)
  - In narrow terminals, the workspace hides the run overview sidebar, and then the runs list, when they would leave the charts fewer than 24 columns wide. An 80-column terminal previously showed the charts as a one-column sliver between the two sidebars (@dmitryduev in https://github.com/wandb/wandb/pull/12731)
  - The top y-axis label of a chart is no longer cut off when it is wider than the other labels, showing for example `+03` instead of `1.09e+03` (@dmitryduev in https://github.com/wandb/wandb/pull/12727)
