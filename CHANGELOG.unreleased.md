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

- `wandb.Api()` no longer sends the `Use-Admin-Privileges` header by default. Pass `admin_privileges=True` when constructing `Api` if you need it (admin-only deployments and admin-only methods). This unblocks non-admin keys on deployments that reject the header (@kmikowicz-wandb in https://github.com/wandb/wandb/pull/11877)
