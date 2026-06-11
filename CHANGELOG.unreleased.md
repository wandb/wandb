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

### Added

- High-resolution image rendering in terminals supporting the Kitty protocol with ANSI fallback in the W&B LEET TUI media pane (`wandb beta leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11806)
- Basic remote-run support in W&B LEET TUI (`wandb beta leet <run-url>` command) (@jacobromero in https://github.com/wandb/wandb/pull/11261)

### Changed
- Added type annotations to `wandb.Table` based on existing runtime checks. No runtime behavior change. (@kelu-wandb in https://github.com/wandb/wandb/pull/12016)

### Fixed

- `wandb.Api().viewer` (and `Api().user()` / `Api().users()`) no longer fail with `WandbApiFailedError: relogin required` for some API keys, a regression in `0.27.1` (@dmitryduev in https://github.com/wandb/wandb/pull/12009)
- When a `wandb.Image` carrying multiple `box` or `mask` layers with distinct `class_labels` is logged inside a `wandb.Table`, each layer's labels are now preserved in new `box_class_maps` / `mask_class_maps` fields in the `table.json`. Previously, there was only as single `class_map` that got incorrectly clobbered by each set of class labels. The next server release will contain a corresponding frontend fix that reads these per-layer fields. Legacy servers will retain the current behavior. (@kelu-wandb in https://github.com/wandb/wandb/pull/11901)
- Artifact file operations now consistently require normalized relative paths (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11735)
- Logging an artifact (whether via `WandbLogger` or `run.log_artifact`) now writes the manifest file to the artifact's staging directory instead of the OS temp dir (`$TMPDIR`), avoiding silent failures when `$TMPDIR` is missing or unwritable (@ibindlish in https://github.com/wandb/wandb/pull/11958)
- Logging artifacts in shared mode works again, and in particular, `wandb.init(mode="shared")` with code-saving enabled no longer raises an error (@timoffex in https://github.com/wandb/wandb/pull/12017)
