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

### Removed

- Removed the unsupported `wandb.apis.importers` API (@dmitryduev in https://github.com/wandb/wandb/pull/11923)
- Removed stale OpenAI, Cohere, and LangChain LLM integrations, including legacy autologging and tracing APIs (@dmitryduev in https://github.com/wandb/wandb/pull/11925)
- Removed the deprecated Keras `WandbCallback` and the legacy `wandb.integration.yolov8` callback package (@dmitryduev in https://github.com/wandb/wandb/pull/11926)

### Changed

- `Run.scan_history()` now reads from exported parquet history when available, which can significantly improve throughput for runs with large history (@jacobromero in https://github.com/wandb/wandb/pull/11797)
    - This was introduced under `beta_scan_history` in `v0.23.1`

### Fixed

- When a `wandb.Image` carrying multiple `box` or `mask` layers with distinct `class_labels` is logged inside a `wandb.Table`, each layer's labels are now preserved in new `box_class_maps` / `mask_class_maps` fields in the `table.json`. Previously, there was only as single `class_map` that got incorrectly clobbered by each set of class labels. The next server release will contain a corresponding frontend fix that reads these per-layer fields. Legacy servers will retain the current behavior. (@kelu-wandb in https://github.com/wandb/wandb/pull/11901)
