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

- `wandb leet inspect --summary` prints a run's state, latest metric values, config and last console lines from its local `.wandb` file, a quick way for a script or a coding agent to check on a run (@dmitryduev in https://github.com/wandb/wandb/pull/12951)
- `wandb leet inspect --json` prints a run's records, one JSON object per line, or its `--summary` as one JSON object, and `--follow` (`-f`) keeps printing records as a running run writes them until it exits or its file goes `--idle-timeout` (10 minutes by default) without a write (@dmitryduev in https://github.com/wandb/wandb/pull/12952)
- In W&B LEET TUI, `ctrl+a` selects every run matching the runs filter after you confirm with `y`, and `x` deselects all runs except the pinned one (@dmitryduev in https://github.com/wandb/wandb/pull/12904)
- In W&B LEET TUI, selected and pinned runs are remembered per wandb directory and selected again the next time you open it, skipping runs that have since been deleted. The newest run is selected as well if it started since the last session (@dmitryduev in https://github.com/wandb/wandb/pull/12887)
- It is now possible to use resume="must" for offline runs. Syncing will fail if there's no run to resume (@geoffhardy in https://github.com/wandb/wandb/pull/12110)
- Added a `--max-consecutive-failed-runs` flag to `wandb agent`, which shuts an agent down once that many runs have failed consecutively at any point in the agent's life (@nathancy-wandb in https://github.com/wandb/wandb/pull/12821)
- System metrics now include `proc.cpu.throttledPercent`, the percentage of CPU scheduler periods in which the container's CPU limit throttled the run (@dmitryduev in https://github.com/wandb/wandb/pull/PRNUM)

### Changed

- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)
- Reduced the size of the `wandb-core` binary by about a third, from 52 MB to 35 MB on Linux x86_64 (@dmitryduev in https://github.com/wandb/wandb/pull/12923)

### Removed

- Removed the undocumented `wandb.set_trace()`. Use Python's built-in `breakpoint()` instead (@dmitryduev in https://github.com/wandb/wandb/pull/12985)

### Fixed

- `wandb leet inspect` no longer prints "skipped corrupt data" forever when its output is piped and the file is not a `.wandb` log it can read; it now exits with an error (@dmitryduev in https://github.com/wandb/wandb/pull/12950)
- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
- `wandb beta sync` no longer overwrites the earlier history of a resumed run when the backend reports a stale step. The starting step is now reconciled against the summary `_step`, the history tail `_step`, and the history row count (@geoffhardy in https://github.com/wandb/wandb/pull/12668)
- Fixed a memory leak where every `wandb.Api()` object permanently retained a few MiB in the background service process after it was garbage collected (@dmitryduev in https://github.com/wandb/wandb/pull/12920)
- `Run.scan_history(keys=...)` no longer fails with `403 Forbidden` on W&B deployments that store run history in Amazon S3 (@dmitryduev in https://github.com/wandb/wandb/pull/12930)
- Per-process GPU metrics (`gpu.process.*`) are logged again for NVIDIA GPUs used by the process that called `wandb.init()`. Since v0.18.2, they were logged only when a subprocess used the GPU (@dmitryduev in https://github.com/wandb/wandb/pull/12978)
- `network.sent` and `network.recv` system metrics no longer count loopback traffic, or count traffic twice through bonded and bridged interfaces (@dmitryduev in https://github.com/wandb/wandb/pull/13000)
