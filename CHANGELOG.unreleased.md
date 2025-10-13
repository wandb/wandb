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

- `wandb.Api(api_key=...)` now prioritizes the explicitly provided API key over thread-local cached credentials (@pingleiwandb in https://github.com/wandb/wandb/pull/10657)
- Fixed a rare deadlock in `console_capture.py` (@timoffex in https://github.com/wandb/wandb/pull/10683)
  - If you dump thread tracebacks during the deadlock and see the `wandb-AsyncioManager-main` thread stuck on a line in `console_capture.py`: this is now fixed.
- Fixed uploading GCS folder references via `artifact.add_reference` (@amusipatla-wandb in https://github.com/wandb/wandb/pull/10679)
