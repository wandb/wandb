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

- In W&B LEET TUI, `ctrl+a` selects every run matching the runs filter after you confirm with `y`, and `x` deselects all runs except the pinned one (@dmitryduev in https://github.com/wandb/wandb/pull/12904)
- In W&B LEET TUI, selected and pinned runs are remembered per wandb directory and selected again the next time you open it, skipping runs that have since been deleted. The newest run is selected as well if it started since the last session (@dmitryduev in https://github.com/wandb/wandb/pull/12887)
- It is now possible to use resume="must" for offline runs. Syncing will fail if there's no run to resume (@geoffhardy in https://github.com/wandb/wandb/pull/12110)
- Added a `--max-consecutive-failed-runs` flag to `wandb agent`, which shuts an agent down once that many runs have failed consecutively at any point in the agent's life (@nathancy-wandb in https://github.com/wandb/wandb/pull/12821)

### Changed

- The default W&B server is now CoreWeave Forge at `https://forge.coreweave.com/api/wandb`, and run, project, sweep and login links point to `https://forge.coreweave.com/wandb`. Existing API keys stored for `api.wandb.ai` keep working without logging in again, and an explicitly configured `base_url`, including `https://api.wandb.ai`, is used as before (@dmitryduev in https://github.com/wandb/wandb/pull/PRNUM)
- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)
- Reduced the size of the `wandb-core` binary by about a third, from 52 MB to 35 MB on Linux x86_64 (@dmitryduev in https://github.com/wandb/wandb/pull/12923)

### Fixed

- Downloading run files with `File.download()` and `wandb.restore()`, and reading `Run.metadata`, no longer fail with a 404 when the W&B server URL includes a path (@dmitryduev in https://github.com/wandb/wandb/pull/PRNUM)
- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
- `wandb beta sync` no longer overwrites the earlier history of a resumed run when the backend reports a stale step. The starting step is now reconciled against the summary `_step`, the history tail `_step`, and the history row count (@geoffhardy in https://github.com/wandb/wandb/pull/12668)
- Fixed a memory leak where every `wandb.Api()` object permanently retained a few MiB in the background service process after it was garbage collected (@dmitryduev in https://github.com/wandb/wandb/pull/12920)
- `Run.scan_history(keys=...)` no longer fails with `403 Forbidden` on W&B deployments that store run history in Amazon S3 (@dmitryduev in https://github.com/wandb/wandb/pull/12930)
