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

- The `reinit` setting can be set to `"default"` (@timoffex in https://github.com/wandb/wandb/pull/9569)
- Added support for building artifact file download urls using the new url scheme, with artifact collection membership context (@ibindlish in https://github.com/wandb/wandb/pull/9560)

### Changed

- Boolean values for the `reinit` setting are deprecated; use "return_previous" and "finish_previous" instead (@timoffex in https://github.com/wandb/wandb/pull/9557)
- The "wandb" logger is configured with `propagate=False` at import time, whereas it previously happened when starting a run. This may change the messages observed by the root logger in some workflows (@timoffex in https://github.com/wandb/wandb/pull/9540)
- Metaflow now requires `plum-dispatch` package. (@jacobromero in https://github.com/wandb/wandb/pull/9599)
- Relaxed the `pydantic` version requirement to support both v1 and v2 (@dmitryduev in https://github.com/wandb/wandb/pull/9605)
- Existing `pydantic` types have been adapted to be compatible with Pydantic v1 (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9623)
- `wandb.init(dir=...)` now creates any nonexistent directories in `dir` if it has a parent directory that is writeable (@ringohoffman in https://github.com/wandb/wandb/pull/9545)
- The server now supports fetching artifact files by providing additional collection information; updated the artifacts api to use the new endpoints instead (@ibindlish in https://github.com/wandb/wandb/pull/9551)
- Paginated methods (and underlying paginators) that accept a `per_page` argument now only accept `int` values. Default `per_page` values are set directly in method signatures, and explicitly passing `None` is no longer supported (@tonyyli-wandb in https://github.com/wandb/wandb/pull/9201)
- Upgrade go version for `wandb-core` from 1.23.x to 1.24.x (@kptkin in https://github.com/wandb/wandb/pull/9590)

### Fixed

- Calling `wandb.init()` in a notebook finishes previous runs as previously documented (@timoffex in https://github.com/wandb/wandb/pull/9569)
  - Bug introduced in 0.19.0
- Fixed an error being thrown when logging `jpg`/`jpeg` images containing transparency data (@jacobromero in https://github.com/wandb/wandb/pull/9527)
- `wandb.init(resume_from=...)` now works without explicitly specifying the run's `id` (@kptkin in https://github.com/wandb/wandb/pull/9572)
- Deleting files with the Public API works again (@jacobromero in https://github.com/wandb/wandb/pull/9604)
  - Bug introduced in 0.19.1
- Fixed media files not displaying in the UI when logging to a run with a custom storage bucket (@jacobromero in https://github.com/wandb/wandb/pull/9661)
