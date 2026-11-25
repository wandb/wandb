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

- `wandb.Api().artifact(...)` now defers fetching an artifact's collection membership aliases until `Artifact.aliases` is accessed, then fetches them in 1,000-alias pages (@ibindlish in https://github.com/wandb/wandb/pull/13183)

### Fixed

- A live run keeps uploading through a temporary outage in front of the W&B server, like a missing load balancer: a run data upload that gets a 404 without the server's `X-Wandb-Server` header is now retried for up to 2 hours instead of stopping uploads. This needs a server that advertises the `RESPONSE_ORIGIN_HEADER` feature (@guanw in https://github.com/wandb/wandb/pull/13461)
