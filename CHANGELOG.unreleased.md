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

### Fixed

- `wandb.Api(api_key=...)` now prioritizes the explicitly provided API key over thread-local cached credentials (@pingleiwandb in https://github.com/wandb/wandb/pull/10657)
