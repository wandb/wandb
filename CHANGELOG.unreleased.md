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

- `wandb login sso` logs in through your organization's identity provider in a browser, instead of an API key. Pass `--org` for a multi-tenant SaaS organization or `--host` for a dedicated or self-hosted instance. The resulting credentials are saved to `identity_token.json` in the W&B config directory, one entry per account, and wandb-core refreshes them as they expire.

### Changed

- Setting both `WANDB_API_KEY` and `WANDB_IDENTITY_TOKEN_FILE` is no longer an error. Federated identity credentials take precedence and W&B warns that the API key is being ignored.

### Fixed

- File uploads and downloads no longer fail in some cases with `CommError: Failed to execute API request: the service process is busy and did not respond in time` when they take longer than 20 seconds. This was a regression in 0.29.0 (@dmitryduev in https://github.com/wandb/wandb/pull/12603)
