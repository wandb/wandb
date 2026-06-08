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

- `wandb.Api().viewer` (and `Api().user()` / `Api().users()`) no longer fail with `WandbApiFailedError: relogin required` for some API keys, a regression in `0.27.1` (@dmitryduev in https://github.com/wandb/wandb/pull/12009)
- When a `wandb.Image` carrying multiple `box` or `mask` layers with distinct `class_labels` is logged inside a `wandb.Table`, each layer's labels are now preserved in new `box_class_maps` / `mask_class_maps` fields in the `table.json`. Previously, there was only as single `class_map` that got incorrectly clobbered by each set of class labels. The next server release will contain a corresponding frontend fix that reads these per-layer fields. Legacy servers will retain the current behavior. (@kelu-wandb in https://github.com/wandb/wandb/pull/11901)
