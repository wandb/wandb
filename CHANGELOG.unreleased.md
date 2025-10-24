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

- The automations API now supports creating and editing automations that trigger on run states (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10848)
- The automations API now support basic zscore automation events (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10931)
- Regex support in metrics and run overview filters in W&B LEET TUI (@dmitryduev in https://github.com/wandb/wandb/pull/10919)
- Simplified the syntax for creating z-score metric automation triggers in the automations API (@matthoare117-wandb in https://github.com/wandb/wandb/pull/10953)

### Changed

- `wandb.Api()` now raises a `UsageError` if `WANDB_IDENTITY_TOKEN_FILE` is set and an explicit API key is not provided (@timoffex in https://app.graphite.com/github/pr/wandb/wandb/10970)
  - `wandb.Api()` has only ever worked using an API key

### Deprecated

- Anonymous mode, including the `anonymous` setting, the `WANDB_ANONYMOUS` environment variable, `wandb.init(anonymous=...)`, `wandb login --anonymously` and `wandb.login(anonymous=...)` is deprecated and will emit warnings (@timoffex in https://github.com/wandb/wandb/pull/10909)

### Fixed

- `wandb.Image()` no longer prints a deprecation warning (@jacobromero in https://github.com/wandb/wandb/pull/10880)
- `Registry.description` and `ArtifactCollection.description` no longer reject empty strings (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10891)
- Apply http headers specified using `WANDB__EXTRA_HTTP_HEADERS` for file uploads using presigned url. (@pingleiwandb in https://github.com/wandb/wandb/pull/10761)
