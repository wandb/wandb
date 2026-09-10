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

- `wandb login sso` logs in through your organization's identity provider in a browser, instead of an API key. Pass `--org` for a multi-tenant SaaS organization or `--host` for a dedicated or self-hosted instance. On a machine with no browser, `--use-device-code` prints a URL and a code to approve from a phone or another computer. The resulting credentials are saved to `identity_token.json` in the W&B config directory, one entry per account, and wandb-core refreshes them as they expire.

### Changed

- Setting both `WANDB_API_KEY` and `WANDB_IDENTITY_TOKEN_FILE` is no longer an error. Federated identity credentials take precedence and W&B warns that the API key is being ignored.
- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
