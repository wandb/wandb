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

### Changed

- `wandb.Api().artifact(...)` now fetches an artifact's collection membership aliases a 100-alias page at a time instead of all at once, fetching further pages lazily only if something reads `Artifact.aliases`. This avoids multi-second to 19-plus-second response times for artifacts with many aliases (@ibindlish in https://github.com/wandb/wandb/pull/13183)

### Fixed

- In LEET, a remote run opened before it logged any history did not update its state, summary or system metrics while it was running (@dmitryduev in https://github.com/wandb/wandb/pull/13221)
- `wandb leet symon` scaled the GPU PCIe and NVLink throughput charts and the Trainium memory charts by 1024³ on top of the bytes that the monitor reports, so their y-axis labels read like `7.67e+09GB/s` instead of `7.67GB/s` (@dmitryduev in https://github.com/wandb/wandb/pull/13191)
- System metrics were not collected when `TMPDIR` was longer than about 60 characters or on a filesystem without Unix socket support (@dmitryduev in https://github.com/wandb/wandb/pull/13200)
- System metrics were not collected when the temp directory was missing or not writable (@dmitryduev in https://github.com/wandb/wandb/pull/13204)
- Reduced artifact upload request batch sizes to lower the risk of backend timeouts when logging artifacts with many files (@pinglei in https://github.com/wandb/wandb/pull/13198).
