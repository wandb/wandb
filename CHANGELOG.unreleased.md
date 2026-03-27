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

This version drops compatibility with server versions older than 0.63.0 (for Dedicated Cloud and Self-Managed W&B deployments).

### Added

- `wandb beta core start|stop` commands to run a detached `wandb-core` service and reuse it across multiple processes via the `WANDB_SERVICE` env var (@dmitryduev in https://github.com/wandb/wandb/pull/11418)
- Run filtering by metadata in multi-run workspace mode in W&B LEET TUI (`wandb beta leet` command, activate with `f`) (@dmitryduev in https://github.com/wandb/wandb/pull/11497 and https://github.com/wandb/wandb/pull/11534)
- Run overview displays tags and notes in W&B LEET TUI (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11523)
- Per-chart log-scale (Y-axis) support in W&B LEET TUI (`wandb beta leet` command, toggle on a selected chart with `y`) (@dmitryduev in https://github.com/wandb/wandb/pull/11523)
- Standalone system monitor mode in W&B LEET TUI (`wandb beta leet symon` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11559)
- Bucketed heatmap chart mode for system metrics expressed as percentages (e.g. GPU utilization) in W&B LEET TUI (`wandb beta leet` command, cycle chart mode on a selected chart with `y`) (@dmitryduev in https://github.com/wandb/wandb/pull/11568 and https://github.com/wandb/wandb/pull/11607)
- Colorblind-friendly `dusk-shore` (gradient) and `clear-signal` (cycle) color schemes in W&B LEET TUI (`wandb beta leet` command, configure with `wandb beta leet config`) (@dmitryduev in https://github.com/wandb/wandb/pull/11578)
- `disable_git_fork_point` to prevent calculating git diff patch files closest ancestor commit when no upstream branch is set (@jacobromero in https://github.com/wandb/wandb/pull/10132)

### Changed

- JSON serialization and deserialization now use `orjson` for improved performance (@jacobromero in https://github.com/wandb/wandb/pull/11163)
- Improved system metrics UX with multi-series overlays, inspection, and live/history zoom in W&B LEET TUI (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11512)
- Prevent run base color collisions in W&B LEET TUI's workspace (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11567)

### Fixed

- Fixed artifact client ID collisions in forked child processes by reseeding the fast ID generator after `fork()` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11491)
- Fixed `WANDB__EXTRA_HTTP_HEADERS` not being applied to presigned object-store upload and download requests (@pingleiwandb in https://github.com/wandb/wandb/pull/11620)
