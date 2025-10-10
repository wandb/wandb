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

### Fixed

- Critical regression where `run.config` returned string instead of dict when using `artifact.logged_by()` in v0.22.1 (@thanos-wandb in #TBD)
- Threading deadlock in lazy loading implementation that could cause training jobs to hang when upgrading runs from lazy to full mode (@thanos-wandb in #TBD)
- `wandb.Api(api_key=...)` now prioritizes the explicitly provided API key over thread-local cached credentials (@pingleiwandb in https://github.com/wandb/wandb/pull/10657)
