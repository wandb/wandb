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

### Notable Changes

This version drops compatibility with server versions older than 0.65.0.

### Added

- High-resolution image rendering in terminals supporting the Kitty protocol with ANSI fallback in the W&B LEET TUI media pane (`wandb leet` command) (@dmitryduev in https://github.com/wandb/wandb/pull/11806)
- Synced scrubbing in the W&B LEET media pane: press `l` to link scrubbing, then the scrub keys (`←/→/↑/↓/home/end`) move a shared cursor over the union step timeline and every image tile follows it (@dmitryduev in https://github.com/wandb/wandb/pull/12033)
- Basic remote-run support in W&B LEET TUI (`wandb leet <run-url>` command) (@jacobromero in https://github.com/wandb/wandb/pull/11261)
- The following paginated artifacts and registry API methods now accept an optional `order` string as a keyword argument: `Api.artifacts()`, `Api.artifact_collections()`, `Api.registries()`, `Api.registries().collections()`, `Registry.collections()` (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11990)

### Changed

- W&B LEET, the terminal UI for viewing W&B runs, is now generally available as `wandb leet`; `wandb beta leet` is kept as an alias (@dmitryduev in https://github.com/wandb/wandb/pull/12028)
- `wandb.Api().runs()` no longer loads Sweeps for each run by default to improve query performance. Sweep data is loaded on first access of the `sweep` property (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/12019)
- Lists of images logged under a single key are now displayed in the W&B LEET media pane, one tile per image (@dmitryduev in https://github.com/wandb/wandb/pull/12033)

### Fixed

- `File.download()` no longer fails after a hardcoded 5-second timeout; downloads go through wandb-core and respect the file transfer settings (@dmitryduev in https://github.com/wandb/wandb/pull/12039)
- `wandb.Api().viewer` (and `Api().user()` / `Api().users()`) no longer fail with `WandbApiFailedError: relogin required` for some API keys, a regression in `0.27.1` (@dmitryduev in https://github.com/wandb/wandb/pull/12009)
- When a `wandb.Image` carrying multiple `box` or `mask` layers with distinct `class_labels` is logged inside a `wandb.Table`, each layer's labels are now preserved in new `box_class_maps` / `mask_class_maps` fields in the `table.json`. Previously, there was only as single `class_map` that got incorrectly clobbered by each set of class labels. The next server release will contain a corresponding frontend fix that reads these per-layer fields. Legacy servers will retain the current behavior. (@kelu-wandb in https://github.com/wandb/wandb/pull/11901)
- Artifact file operations now consistently require normalized relative paths (@tonyyli-wandb in https://github.com/wandb/wandb/pull/11735)
- Logging an artifact (whether via `WandbLogger` or `run.log_artifact`) now writes the manifest file to the artifact's staging directory instead of the OS temp dir (`$TMPDIR`), avoiding silent failures when `$TMPDIR` is missing or unwritable (@ibindlish in https://github.com/wandb/wandb/pull/11958)
- Logging artifacts in shared mode works again, and in particular, `wandb.init(mode="shared")` with code-saving enabled no longer raises an error (@timoffex in https://github.com/wandb/wandb/pull/12017)
- `git_root` setting is now preferred for creating the `diff.patch` file, the `root_dir` setting is now used as a fallback (@TomSiegl in https://github.com/wandb/wandb/pull/11967)
- Apple system metrics (GPU, CPU, power, and temperature) are now collected on Apple M5 Macs (@dmitryduev in https://github.com/wandb/wandb/pull/12061)
- file download progress is now shown when using `wandb.Api().run(...).download_history_exports` (@jacobromero in https://github.com/wandb/wandb/pull/12063)
