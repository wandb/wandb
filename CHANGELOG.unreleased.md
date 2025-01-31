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

- Prometheus API support for Nvidia DCGM GPU metrics collection (@dmitryduev in https://github.com/wandb/wandb/pull/9369)

### Changed

- Changed Nvidia GPU ECC counters from aggregated to volatile (@gritukan in https://github.com/wandb/wandb/pull/9347)

### Fixed

- Fixed a performance issue causing slow instantiation of `wandb.Artifact`, which in turn slowed down fetching artifacts in various API methods. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9355)
- Some errors from `wandb.Api` have better string representations (@timoffex in https://github.com/wandb/wandb/pull/9361)
