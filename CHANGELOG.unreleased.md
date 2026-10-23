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
- `wandb leet history --keys 'train/loss,val/*'` prints the metric series of a run from its local `.wandb` file as one JSON object: the logged rows, or with `--bins N` their min, max, average and last value per bin. `--last`, `--min-step`/`--max-step` and `--after` select rows, and `--follow` keeps printing new rows as a running run writes them (@dmitryduev in https://github.com/wandb/wandb/pull/13234)
- `wandb leet runs` lists the runs of a local wandb directory as one JSON object, newest first, with each run's state, exit code, last step, tags and notes, whether LEET has it selected or pinned, and with `--summary-keys 'val/loss,train/*'` its latest summary values. `--filter` takes the same queries as the runs filter of the LEET sidebar (@dmitryduev in https://github.com/wandb/wandb/pull/13235)
- `wandb leet summary` prints a run's state, latest metrics, config, the keys it logged with their last values and its last 50 console lines as one JSON object, and `wandb leet console` prints its console output with ANSI escapes stripped: `--grep` and `--since` select lines, `--last` keeps the last N of them, `--after` pages through them and `--follow` keeps printing new lines as a running run writes them (@dmitryduev in https://github.com/wandb/wandb/pull/13236)
- `wandb leet system` prints the system metrics of a run (CPU, memory, GPU, disk, network) from its local `.wandb` file as one JSON object: the samples over time, or with `--bins N` their min, max, average and last value per bin with each metric's title and unit. `--keys 'system.gpu.*'`, `--since 10m` and `--last N` select samples (@dmitryduev in https://github.com/wandb/wandb/pull/13237)
- `wandb leet session` steers the LEET a user has open on a wandb directory, so a script or an agent can show what it found: `wandb leet session runs.select --params '{"filter": "cfg.lr>=0.001"}'` selects runs, `filter.set`, `metrics.focus`, `step.goto` and `runs.open` set a filter, focus a chart, put the crosshair on a step and open a run, `action` presses a key binding by name, and `status` reports what LEET shows (@dmitryduev in https://github.com/wandb/wandb/pull/13238)
- `wandb mcp` runs an MCP server for local W&B runs over stdio, so an agent in an MCP host can list the runs of a wandb directory, read their metric series, summary, console output and system metrics, and steer the LEET a user has open, with the same JSON as the `wandb leet` commands (@dmitryduev in https://github.com/wandb/wandb/pull/13239)
- In MCP hosts that render apps, the `leet_view` tool of `wandb mcp` shows LEET charts: a list of the runs of a wandb directory and a chart per metric for the selected runs, which you can toggle by clicking and which refresh every 15 seconds while a run is still running. The agent sees which runs and metrics you are looking at (@dmitryduev in https://github.com/wandb/wandb/pull/13240)
- `wandb leet runs`, `wandb leet summary` and `wandb leet console` accept the URL of a W&B project or run and read it from the W&B server, so the same JSON works for local and remote runs, and the `wandb mcp` tools accept the same URLs for the server you are logged in to (@dmitryduev in https://github.com/wandb/wandb/pull/13241)
- `wandb leet history` and `wandb leet system` accept the URL of a W&B run and read its metrics from the W&B server, as do the `wandb mcp` tools `leet_history` and `leet_system`; the system metrics of a remote run come in bins, so pass `--bins N` (@dmitryduev in https://github.com/wandb/wandb/pull/13242)

### Fixed

- In LEET, a remote run opened before it logged any history did not update its state, summary or system metrics while it was running (@dmitryduev in https://github.com/wandb/wandb/pull/13221)
- `wandb leet symon` scaled the GPU PCIe and NVLink throughput charts and the Trainium memory charts by 1024³ on top of the bytes that the monitor reports, so their y-axis labels read like `7.67e+09GB/s` instead of `7.67GB/s` (@dmitryduev in https://github.com/wandb/wandb/pull/13191)
- System metrics were not collected when `TMPDIR` was longer than about 60 characters or on a filesystem without Unix socket support (@dmitryduev in https://github.com/wandb/wandb/pull/13200)
- System metrics were not collected when the temp directory was missing or not writable (@dmitryduev in https://github.com/wandb/wandb/pull/13204)
- Reduced artifact upload request batch sizes to lower the risk of backend timeouts when logging artifacts with many files (@pinglei in https://github.com/wandb/wandb/pull/13198).
