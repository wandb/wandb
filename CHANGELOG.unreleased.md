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

- `wandb login sso` logs in through your organization's identity provider in a browser, instead of an API key. On multi-tenant SaaS, pass `--org` together with `--issuer` and `--client-id`, which are checked against the identity provider that organization registered before anything is sent to it. Pass `--host` for a dedicated or self-hosted instance, which serves a single organization and resolves it automatically. The resulting credentials are saved to `identity_token.json` in the W&B config directory, one entry per account, and wandb-core refreshes them as they expire.

### Changed

- Setting both `WANDB_API_KEY` and `WANDB_IDENTITY_TOKEN_FILE` is no longer an error. Federated identity credentials take precedence and W&B warns that the API key is being ignored.
- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
