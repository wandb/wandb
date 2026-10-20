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

### Fixed

- `wandb leet symon` scaled the GPU PCIe and NVLink throughput charts and the Trainium memory charts by 1024³ on top of the bytes that the monitor reports, so their y-axis labels read like `7.67e+09GB/s` instead of `7.67GB/s` (@dmitryduev in https://github.com/wandb/wandb/pull/13191)
- System metrics were not collected when `TMPDIR` was longer than about 60 characters or on a filesystem without Unix socket support (@dmitryduev in https://github.com/wandb/wandb/pull/13200)
- System metrics were not collected when the temp directory was missing or not writable (@dmitryduev in https://github.com/wandb/wandb/pull/13204)
- The XGBoost and LightGBM callbacks now record the best value of metrics such as `ndcg@5`, `map@3`, `error@0.6` and LightGBM's `binary_error` in the run summary, instead of the last one (@David-Wu1119 in https://github.com/wandb/wandb/pull/13102)
