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

- Support JWT authentication in wandb-core (@elainaRenee in https://github.com/wandb/wandb/pull/8431)
- Add support for logging nested custom charts. (@jacobromero in https://github.com/wandb/wandb/pull/8789)

### Fixed

- The stop button correctly interrupts runs whose main Python thread is running C code, sleeping, etc. (@timoffex in https://github.com/wandb/wandb/pull/9094)
- Remove unintentional print that occurs when inspecting `wandb.Api().runs()` (@tomtseng in https://github.com/wandb/wandb/pull/9101)
- Fix uploading large artifacts when using Azure Blob Storage. (@amulya-musipatla in https://github.com/wandb/wandb/pull/8946)
- Fix error when reinitializing a run, caused by accessing a removed attribute. (@MathisTLD in https://github.com/wandb/wandb/pull/8912)
