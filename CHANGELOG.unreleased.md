# Unreleased changes

Add here any changes made in a PR that are relevant to end users. Allowed sections:

- Added - for new features.
- Changed - for changes in existing functionality.
- Deprecated - for soon-to-be removed features.
- Removed - for now removed features.
- Fixed - for any bug fixes.
- Security - in case of vulnerabilities.

Section headings should be at level 3 (e.g. `### Added`).

## Unreleased

### Added

- Settings `console_chunk_max_seconds` and `console_chunk_max_bytes` for size- and time-based multipart console logs file chunking (@dmitryduev in https://github.com/wandb/wandb/pull/10162)
- Experimental `wandb beta leet` command - Lightweight Experiment Exploration Tool - a terminal UI for viewing W&B runs locally with real-time metrics visualization and system monitoring (@dmitryduev in https://github.com/wandb/wandb/pull/10496)

### Changed

- API keys longer than 40 characters are now supported. (@jennwandb in https://github.com/wandb/wandb/pull/10688)

### Fixed

- `run.config` now properly returns a dict when calling `artifact.logged_by()` in v0.22.1 (@thanos-wandb in #10682)
- `wandb.Api(api_key=...)` now prioritizes the explicitly provided API key over thread-local cached credentials (@pingleiwandb in https://github.com/wandb/wandb/pull/10657)
- Fixed a rare deadlock in `console_capture.py` (@timoffex in https://github.com/wandb/wandb/pull/10683)
  - If you dump thread tracebacks during the deadlock and see the `wandb-AsyncioManager-main` thread stuck on a line in `console_capture.py`: this is now fixed.
- Fixed an issue where TensorBoard sync would sometimes stop working if the tfevents files were being written live (@timoffex in https://github.com/wandb/wandb/pull/10625)
- `Artifact.manifest` delays downloading **and** generating the download URL for the artifact manifest until it's first used.  If the manifest has not been locally modified, `Artifact.size` and `Artifact.digest` can return without waiting to fetch the full manifest (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10680)
