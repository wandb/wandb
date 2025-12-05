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

### Notable Changes

This version removes the legacy, deprecated `wandb.beta.workflows` module, including its `log_model()`/`use_model()`/`link_model()` functions. This is formally a breaking change.

### Added

- `wandb agent` and `wandb.agent()` now accept a `forward_signals` flag (CLI: `--forward-signals/-f`) to relay SIGINT/SIGTERM and other catchable signals from the agent to its sweep child runs, enabling cleaner shutdowns when you interrupt an agent process (@kylegoyette, @domphan-wandb in https://github.com/wandb/wandb/pull/9651)
- `wandb beta sync` now supports a `--live` option for syncing a run while it's being logged (@timoffex in https://github.com/wandb/wandb/pull/11079)

### Removed

- Removed the deprecated `wandb.beta.workflows` module, including its `log_model()`, `use_model()`, and `link_model()` functions, and whose modern successors are the `Run.log_artifact`, `Run.use_artifact`, and `Run.link_artifact` methods, respectively (@tonyyli-wandb in [TODO: PR link])

### Fixed

- Fixed `Run.__exit__` type annotations to accept `None` values, which are passed when no exception is raised (@moldhouse in https://github.com/wandb/wandb/pull/11100)
- Fixed `Invalid Client ID digest` error when creating artifacts after calling `random.seed()`. Client IDs could collide when random state was seeded deterministically. (@pingleiwandb in https://github.com/wandb/wandb/pull/11039)
- Fixed CLI error when listing empty artifacts (@ruhiparvatam in https://github.com/wandb/wandb/pull/11157)
- Fixed regression for calling `api.run()` on a Sweeps run (@willtryagain in https://github.com/wandb/wandb/pull/11088 and @kelu-wandb in https://github.com/wandb/wandb/pull/11097)
- Fixed the "View run at" message printed at the end of a run which sometimes did not include a URL (@timoffex in https://github.com/wandb/wandb/pull/11113)
- runs queried from `wandb.Api()` shows the string representation in notebooks running in VSCode rather than a broken HTML window (@jacobromero in https://github.com/wandb/wandb/pull/11040)
