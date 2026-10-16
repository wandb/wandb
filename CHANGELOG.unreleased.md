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

- The default W&B server is now CoreWeave Forge at `https://api.forge.coreweave.com`, and run links point to `https://forge.coreweave.com/wandb`. Existing API keys stored for `api.wandb.ai` keep working without logging in again.

### Added

- Python 3.15 is now supported (@dmitryduev in https://github.com/wandb/wandb/pull/13167)
- `wandb.init(resume="must")` now works for offline runs. `wandb sync` fails if there is no run to resume (@geoffhardy in https://github.com/wandb/wandb/pull/12666)
- `wandb sweep-scheduler [entity/project/]sweep_id` runs a sweep's search locally with Optuna or Ax as the optimizer, configured in a `scheduler` block of the sweep config. `wandb sweep` prints the command for sweeps that set one (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12900)
- `wandb agent --max-consecutive-failed-runs N` shuts the agent down once N runs in a row have failed (@nathancy-wandb in https://github.com/wandb/wandb/pull/12821)
- `wandb sync` warns when a run was logged with a newer version of `wandb` than the one syncing it (@timoffex in https://github.com/wandb/wandb/pull/12808)
- W&B LEET TUI:
  - `wandb leet inspect --summary` prints a run's state, latest metric values, config and last console lines from its local `.wandb` file, a quick way for a script or a coding agent to check on a run. `--json` prints the records, or the summary, as JSON, and `--follow` keeps printing records as a running run writes them (@dmitryduev in https://github.com/wandb/wandb/pull/12951, https://github.com/wandb/wandb/pull/12952)
  - `l` links the console logs to the charts in the single-run view: with the logs pane focused, the charts show a crosshair at the time the selected line was logged, and inspecting a chart with the mouse selects the console line logged nearest to that point. `l` again unlinks (@dmitryduev in https://github.com/wandb/wandb/pull/12737)
  - `ctrl+a` selects every run matching the runs filter, and `x` deselects all runs except the pinned one (@dmitryduev in https://github.com/wandb/wandb/pull/12904)
  - Selected and pinned runs are remembered per wandb directory and selected again the next time you open it. The newest run is selected as well if it started since the last session (@dmitryduev in https://github.com/wandb/wandb/pull/12887)
  - The `CPU Core (%)` chart opens as a heatmap with one row per core; `y` switches it back to lines (@dmitryduev in https://github.com/wandb/wandb/pull/13014)
- `wandb leet symon`, the live system monitor:
  - Shows the utilization of every CPU core, the CPU temperature and swap usage on Linux, and the hostname, uptime and load average in its header (@dmitryduev in https://github.com/wandb/wandb/pull/13012, https://github.com/wandb/wandb/pull/13015)
  - Charts network and disk throughput in bytes per second instead of totals, and opens with the CPU, memory, network and disk charts ahead of the rest (@dmitryduev in https://github.com/wandb/wandb/pull/13013, https://github.com/wandb/wandb/pull/13014)
  - Has a sidebar with the machine's chip, cores, memory and GPUs, live meters for CPU, memory, swap, disk and GPU use, and the processes using the most CPU. `t` sorts the processes by memory, `f` filters them by name or PID, `Tab` moves between the process list and the charts, and `[` hides the sidebar. The sidebar can be resized by dragging its border, and `0` restores the default width (@dmitryduev in https://github.com/wandb/wandb/pull/13016, https://github.com/wandb/wandb/pull/13017, https://github.com/wandb/wandb/pull/13018, https://github.com/wandb/wandb/pull/13021)
- New system metrics:
  - PCIe throughput (`gpu.N.pcieTxBytes`, `gpu.N.pcieRxBytes`) for NVIDIA GPUs older than Hopper (@dmitryduev in https://github.com/wandb/wandb/pull/12989)
  - Each GPU's cumulative energy consumption in joules as `gpu.N.energyJoules`, for NVIDIA and AMD GPUs (@dmitryduev in https://github.com/wandb/wandb/pull/12991)
  - `proc.cpu.throttledPercent`, the percentage of CPU scheduler periods in which the container's CPU limit throttled the run (@dmitryduev in https://github.com/wandb/wandb/pull/13001)
  - `proc.memory.oomKills`, how many processes in the run's container the out-of-memory killer has killed since the run started (@dmitryduev in https://github.com/wandb/wandb/pull/13002)
  - `network.tcpRetransmits`, the number of TCP segments retransmitted since the run started (@dmitryduev in https://github.com/wandb/wandb/pull/13003)
  - The CPU and memory used by W&B's own background processes, as `wandb.cpu` and `wandb.memory.rssMB`. They are off by default; turn them on with the `x_stats_self_usage` setting (@dmitryduev in https://github.com/wandb/wandb/pull/13004, https://github.com/wandb/wandb/pull/13038)
- Run metadata now records the CPU model and, for each NVIDIA GPU, its PCI bus ID and, on Linux, its NUMA node (@dmitryduev in https://github.com/wandb/wandb/pull/13005, https://github.com/wandb/wandb/pull/13157)

### Changed

- The default W&B server is now CoreWeave Forge at `https://api.forge.coreweave.com`. Run, project, sweep and login links point to `https://forge.coreweave.com/wandb`, also when `base_url` is set to `https://api.wandb.ai` or `https://forge.coreweave.com/api/wandb`. Existing API keys stored for `api.wandb.ai` keep working without logging in again (@dmitryduev in https://github.com/wandb/wandb/pull/13077)
- The helper process that collects system metrics is now `wandb-symon` instead of `wandb-xpu` (@dmitryduev in https://github.com/wandb/wandb/pull/13165)
- `import wandb` and the `wandb` CLI start about twice as fast (@dmitryduev in https://github.com/wandb/wandb/pull/13144, https://github.com/wandb/wandb/pull/13145, https://github.com/wandb/wandb/pull/13146, https://github.com/wandb/wandb/pull/13147, https://github.com/wandb/wandb/pull/13148)
- The `wandb` package is smaller: `wandb-core` shrank by about a third, from 52 MB to 35 MB on Linux x86_64, and the parquet reader and the system metrics helper by more than half (@dmitryduev in https://github.com/wandb/wandb/pull/12921, https://github.com/wandb/wandb/pull/12922, https://github.com/wandb/wandb/pull/12923, https://github.com/wandb/wandb/pull/12924, https://github.com/wandb/wandb/pull/12937, https://github.com/wandb/wandb/pull/12939)
- Runs write their data to the local `.wandb` file at least every 15 seconds, so `wandb leet` shows recent data sooner for runs that log infrequently (@dmitryduev in https://github.com/wandb/wandb/pull/12742)
- The `cpu` system metric reports the monitored process's CPU utilization over the sampling interval instead of its average since the process started (@dmitryduev in https://github.com/wandb/wandb/pull/13101)
- NVIDIA GPM system metrics such as `gpu.N.smActive` and `gpu.N.dramActive` are now averaged over the whole interval between samples instead of a 200 ms window (@dmitryduev in https://github.com/wandb/wandb/pull/12987)
- AMD GPU system metrics are read through the ROCm SMI library (`librocm_smi64.so`) instead of running the `rocm-smi` tool on every sample. Readings a GPU does not provide are left out instead of reported as 0 (@dmitryduev in https://github.com/wandb/wandb/pull/12990)
- OpenMetrics and DCGM exporter endpoints are scraped once per sampling interval for all runs on the machine instead of once per run, and all runs use the same `openmetrics.<endpoint>.<metric>.<index>` index for the same metric labels (@dmitryduev in https://github.com/wandb/wandb/pull/13103)

### Removed

- Removed the undocumented `wandb.set_trace()`. Use Python's built-in `breakpoint()` instead (@dmitryduev in https://github.com/wandb/wandb/pull/12985)

### Fixed

- Resumed runs no longer report a huge or negative `_runtime` and run duration. This was a regression in 0.30.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12999)
- Offline runs show warnings again, such as when `run.log()` data is ignored because its step is lower than the current step. This was a regression in 0.27.0 (@willtryagain in https://github.com/wandb/wandb/pull/13037)
- Per-process GPU metrics (`gpu.process.*`) are logged again for NVIDIA GPUs used by the process that called `wandb.init()`. Since 0.18.2 they were logged only when a subprocess used the GPU (@dmitryduev in https://github.com/wandb/wandb/pull/12978)
- Runs that print thousands of console lines per second no longer spend minutes of CPU time uploading them and finishing (@dmitryduev in https://github.com/wandb/wandb/pull/12405)
- Runs that finish right after they initialize, for example when `wandb sync` uploads a short run, no longer risk exiting before their final data and exit status are uploaded (@dmitryduev in https://github.com/wandb/wandb/pull/13153)
- `wandb sync` no longer overwrites the earlier history of a resumed run when the server reports a stale step (@geoffhardy in https://github.com/wandb/wandb/pull/12668)
- Calling `wandb.init()` after `wandb.agent(sweep_id, function=...)` returns creates a new run instead of reusing and overwriting the last sweep run (@nathancy-wandb in https://github.com/wandb/wandb/pull/12970)
- `wandb.Api(overrides={"base_url": ...})` no longer changes the W&B server URL used by `wandb.init()` and other W&B calls later in the same process (@dmitryduev in https://github.com/wandb/wandb/pull/13125)
- Every `wandb.Api()` object no longer permanently retains a few MiB of memory after it is garbage collected (@dmitryduev in https://github.com/wandb/wandb/pull/12920)
- `Run.scan_history(keys=...)` no longer fails with `403 Forbidden` on W&B deployments that store run history in Amazon S3 (@dmitryduev in https://github.com/wandb/wandb/pull/12930)
- Passing a run's `config` to `wandb.init(config=...)` or `run.config.update()` copies its keys. Previously each pass nested the config one level deeper under an `_items` key (@asg0451 in https://github.com/wandb/wandb/pull/13134)
- `wandb verify` no longer hangs on its final sweep check against W&B Server instances that deduplicate sweep run configs (@rsong9527 in https://github.com/wandb/wandb/pull/13136)
- `linked_at` is accepted as a filter field in `api.registries().collections().versions(filter={"linked_at": ...})`, matching the existing `linked_at` order field (@ibindlish in https://github.com/wandb/wandb/pull/13161)
- The Docker image ID recorded for runs inside Kubernetes no longer loses the start of the image name and the end of the digest (@David-Wu1119 in https://github.com/wandb/wandb/pull/13035)
- Integrations:
  - The CatBoost `WandbCallback` logs every evaluation, including the last one, at the iteration CatBoost makes it. With `metric_period > 1` it used to log each value one evaluation late and drop the final ones (@David-Wu1119 in https://github.com/wandb/wandb/pull/13155)
  - `wandb.tensorflow.WandbHook` works again with TensorFlow 2.16 and newer (@dmitryduev in https://github.com/wandb/wandb/pull/13139)
  - `wandb.integration.ultralytics` imports again with `ultralytics` 8.3.200 and newer (@dmitryduev in https://github.com/wandb/wandb/pull/13139)
  - `wandb.integration.huggingface.autolog()` no longer requires the `pytz` package (@dmitryduev in https://github.com/wandb/wandb/pull/13139)
  - Calling a pipeline that `wandb.integration.diffusers.autolog()` does not support no longer raises an error; the call is not logged (@dmitryduev in https://github.com/wandb/wandb/pull/13139)
  - Importing `wandb.integration.lightning.fabric` or `wandb.integration.ultralytics` without the libraries they need fails with an `ImportError` naming the missing package (@dmitryduev in https://github.com/wandb/wandb/pull/13139)
- System metrics:
  - The `x_stats_gpu_device_ids` setting limits which GPUs are reported for every vendor, including AMD and Apple GPUs, as documented. It applied only to NVIDIA GPUs (@dmitryduev in https://github.com/wandb/wandb/pull/13079)
  - GPU, TPU and Apple accelerator metrics resume when the helper process that collects them exits or fails to start; they used to stop for the rest of the run (@dmitryduev in https://github.com/wandb/wandb/pull/13098)
  - NVIDIA PCIe and NVLink throughput metrics from GPM (`gpu.N.pcieTxBytes`, `gpu.N.pcieRxBytes`, `gpu.N.nvlinkTxBytes`, `gpu.N.nvlinkRxBytes`) are reported in bytes per second as their names say. They were in mebibytes per second (@dmitryduev in https://github.com/wandb/wandb/pull/12988)
  - `network.sent` and `network.recv` no longer count loopback traffic, or count traffic twice through bonded and bridged interfaces (@dmitryduev in https://github.com/wandb/wandb/pull/13000)
  - NVIDIA GPM metrics such as `gpu.N.smActive` are averaged over each run's own sampling interval. When several runs shared one process, each run's value covered only the time since any run's previous sample (@dmitryduev in https://github.com/wandb/wandb/pull/13080)
  - Sampling system metrics no longer costs more with the number of runs in a process (@dmitryduev in https://github.com/wandb/wandb/pull/13080, https://github.com/wandb/wandb/pull/13101)
  - Run metadata on AWS Trainium records the Neuron device and NeuronCore counts; they were always 0 (@dmitryduev in https://github.com/wandb/wandb/pull/13156)
- W&B LEET TUI:
  - The system metrics filter applies to whichever run is highlighted, not only the run it was typed on. `Space` and `Enter` work in the runs list right after you filter runs with `f` from another pane (@dmitryduev in https://github.com/wandb/wandb/pull/12533)
  - Changing the system metrics grid rows or columns, including in `wandb leet symon`, no longer crashes and takes effect immediately (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
  - `wandb leet inspect` exits with an error when the file is not a `.wandb` log it can read, instead of printing "skipped corrupt data" forever when its output is piped (@dmitryduev in https://github.com/wandb/wandb/pull/12950)

### Security

- The `wandb/launch-agent` Docker image is built on an updated base image that fixes the CVEs reported against the 0.30.0 image (@nicholaspun-wandb and @w-mclaughlin in https://github.com/wandb/wandb/pull/12771, https://github.com/wandb/wandb/pull/13114)
