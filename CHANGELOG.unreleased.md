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

- Optimize artifacts downloads re-verification with checksum caching (@thanos-wandb in https://github.com/wandb/wandb/pull/10157)
- Lazy loading support for `Api().runs()` to improve performance when listing runs. The new `lazy=True` parameter (default) loads only essential metadata initially, with automatic on-demand loading of heavy fields like config and summary when accessed (@thanos-wandb in https://github.com/wandb/wandb/pull/10034)
- Add `storage_region` option when creating artifacts. Users can use [CoreWeave AI Object Storage](https://docs.coreweave.com/docs/products/storage/object-storage) by specifying `wandb.Artifact(storage_region="coreweave-us")` when using wandb.ai for faster artifact upload/download on CoreWeave's infrastructure. (@pingleiwandb in https://github.com/wandb/wandb/pull/10533)
