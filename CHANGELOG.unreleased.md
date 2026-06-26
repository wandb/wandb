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

### Changed

- Remove temporary Unix socket files and directories on shutdown (@geoffhardy in https://github.com/wandb/wandb/pull/12058)
- `wandb beta sync` now skips online runs by default like `wandb sync` (@timoffex in https://github.com/wandb/wandb/pull/12087)
- `wandb sync` now routes to `wandb beta sync` for supported parameter sets (@timoffex in https://github.com/wandb/wandb/pull/12093)
  - Restore original behavior with `--legacy`

### Fixed

- Saving a linked registry artifact (for example, when adding an alias) no longer fails when the caller lacks write access to the source project (@ibindlish in https://github.com/wandb/wandb/pull/12075)
- `np.float16`/`np.float32` NaN values logged with `Run.log()` are now recorded as `NaN` instead of being silently dropped, matching `np.float64` and native `float` (@dmitryduev in https://github.com/wandb/wandb/pull/12116)
