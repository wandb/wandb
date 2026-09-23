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

- It is now possible to use resume="must" for offline runs. Syncing will fail if there's no run to resume. (@geoffhardy in https://github.com/wandb/wandb/pull/12110)
- `wandb logout` ends a browser login, revoking it at the server so that copies taken from this machine stop working. (@ckacal)


### Changed

- `wandb login` with no arguments now logs in through your browser instead of asking for an API key. It uses the session you already have, so it works the same whether your organization signs in with SAML, OIDC, or a password, and the credentials it stores are scoped to one organization and renewed for you until the login expires. `wandb login <key>` still stores that key, credentials already on the machine are still reused, and where no browser is available -- CI, a remote shell, an older server -- it still asks for an API key. Use `--no-browser` to ask for one anyway. (@ckacal)
- Runs now write data to disk every 15 seconds, so that wandb leet updates sooner for runs that don't log a lot of data (@dmitryduev in https://github.com/wandb/wandb/pull/12742)

### Fixed

- Changing system metrics grid rows or columns in LEET, including `wandb leet symon`, no longer crashes and takes effect immediately without waiting for new data (@dmitryduev in https://github.com/wandb/wandb/pull/12763)
