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

- `wandb agent` and `wandb.agent()` now accept a `forward_signals` flag (CLI: `--forward-signals/-f`) to relay SIGINT/SIGTERM and other catchable signals from the agent to its sweep child runs, enabling cleaner shutdowns when you interrupt an agent process (@kylegoyette, @domphan-wandb in https://github.com/wandb/wandb/pull/9651)

### Fixed

- Fixed `Run.__exit__` type annotations to accept `None` values, which are passed when no exception is raised.
- Fixed `Invalid Client ID digest` error when creating artifacts after calling `random.seed()`. Client IDs could collide when random state was seeded deterministically. (@pingleiwandb in https://github.com/wandb/wandb/pull/11039)
- Fixed regression for calling `api.run()` on a Sweeps run. (@willtryagain in https://github.com/wandb/wandb/pull/11088 and @kelu-wandb in https://github.com/wandb/wandb/pull/11097)
