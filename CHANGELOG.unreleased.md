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

### Fixed

- When a `wandb.Image` carrying multiple mask keys with distinct `class_labels` is logged inside a `wandb.Table`, each mask's labels are now preserved on disk via per-mask `classes-file` references in the artifact, rather than being merged into a single lossy classes-file at the image level. Frontend renderers using the per-mask data show the correct legend in table cells. (WB-26043)

### Changed

- An explicit `classes=` argument to `wandb.Image` is now used as the sole source for the image's top-level class set and is no longer merged with mask/box `class_labels`. Per-mask `class_labels` continue to be preserved separately as per-mask classes-file references.
