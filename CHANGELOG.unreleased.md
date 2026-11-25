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

- `wandb.Api().artifact(...)` now defers fetching an artifact's collection membership aliases until `Artifact.aliases` is accessed, then fetches them in 1,000-alias pages (@ibindlish in https://github.com/wandb/wandb/pull/13183)

### Added

- `Registry.import_from_huggingface()` imports a Hugging Face model repo into a registry collection server-side, with `Api.check_huggingface_source()`, `Api.huggingface_import()`, and `Api.huggingface_imports()` to check, monitor, and list imports. (@gdecarvalhovaz-lgtm in https://github.com/wandb/wandb/pull/13352)
