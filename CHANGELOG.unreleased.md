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

- Regex support in metrics and run overview filters in W&B LEET TUI (@dmitryduev in https://github.com/wandb/wandb/pull/10919)
- Chart inspection in W&B LEET TUI: right-click and drag to show (x, y) at the nearest data point; hold Alt for synchronized inspection across all visible charts (@dmitryduev in https://github.com/wandb/wandb/pull/10989)
- The automations API now supports creating and editing automations that trigger on run states (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10848)
- The automations API now supports assigning `Registry` objects to an automation scope (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10867)
- The automations API now support basic zscore automation events (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10931)
- Simplified the syntax for creating z-score metric automation triggers in the automations API (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10953)
- `beta_history_scan` method to `Run` objects for client-side history parsing (@jacobromero in https://github.com/wandb/wandb/pull/10875)

### Changed

- `wandb.Api()` now raises a `UsageError` if `WANDB_IDENTITY_TOKEN_FILE` is set and an explicit API key is not provided (@timoffex in https://app.graphite.com/github/pr/wandb/wandb/10970)
  - `wandb.Api()` has only ever worked using an API key

### Deprecated

- Anonymous mode, including the `anonymous` setting, the `WANDB_ANONYMOUS` environment variable, `wandb.init(anonymous=...)`, `wandb login --anonymously` and `wandb.login(anonymous=...)` is deprecated and will emit warnings (@timoffex in https://github.com/wandb/wandb/pull/10909)

### Fixed

- `wandb.Image()` no longer prints a deprecation warning (@jacobromero in https://github.com/wandb/wandb/pull/10880)
- `Registry.description` and `ArtifactCollection.description` no longer reject empty strings (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10891)
- Instantiating `Artifact` objects is now significantly faster (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10819)
- `wandb.Run.save()` now falls back to hardlinks and, if needed, copying (downgrading the 'live' file policy to 'now', if applicable) when symlinks are disabled or unavailable (e.g., cross‑volume or no Developer Mode on Windows) (@dmitryduev in https://github.com/wandb/wandb/pull/10894)
- Artifact collection aliases are now fetched lazily on accessing `ArtifactCollection.aliases` instead of on instantiating `ArtifactCollection`, improving performance of `Api.artifact_collections()`, `Api.registries().collections()`, etc. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10731)
- Use explicitly provided API key in `wandb.init(settings=wandb.Settings(api_key="..."))` for login. Use the key from run when logging artifacts via `run.log_artifact` (@pingleiwandb in https://github.com/wandb/wandb/pull/10914)
- W&B LEET TUI correctly displays negative Y axis tick values and base/display units of certain system metrics (@dmitryduev in https://github.com/wandb/wandb/pull/10905)
- Fixed a rare infinite loop in `console_capture.py` (@timoffex in https://github.com/wandb/wandb/pull/10955)
- File upload/download now respects `WANDB_X_EXTRA_HTTP_HEADERS` except for [reference artifacts](https://docs.wandb.ai/models/artifacts/track-external-files)
