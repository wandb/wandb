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

### Fixed

- `wandb.Image()` no longer prints a deprecation warning (@jacobromero in https://github.com/wandb/wandb/pull/10880)
- `Registry.description` and `ArtifactCollection.description` no longer reject empty strings (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10891)
- `wandb.Run.save()` now falls back to hardlinks and, if needed, copying (downgrading the 'live' file policy to 'now', if applicable) when symlinks are disabled or unavailable (e.g., cross‑volume or no Developer Mode on Windows) (@dmitryduev in https://github.com/wandb/wandb/pull/10894)
- Artifact collection aliases are now fetched lazily on accessing `artifact_collection.aliases`, instead of on instantiation, improving performance of `Api.artifact_collections()`, `Api.registries().collections()`, etc. (@tonyyli-wandb in https://github.com/wandb/wandb/pull/10731)
