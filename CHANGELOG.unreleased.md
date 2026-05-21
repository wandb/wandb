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

### Removed

- Removed the unsupported `wandb.apis.importers` API (@dmitryduev in https://github.com/wandb/wandb/pull/11923)
- Removed stale OpenAI, Cohere, and LangChain LLM integrations, including legacy autologging and tracing APIs (@dmitryduev in https://github.com/wandb/wandb/pull/11925)
- Removed the deprecated Keras `WandbCallback` and the legacy `wandb.integration.yolov8` callback package (@dmitryduev in https://github.com/wandb/wandb/pull/11926)
