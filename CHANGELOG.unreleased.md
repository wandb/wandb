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
- Identity token logins now stay signed in after the identity token has been used, when the JWT issuer is configured to allow it: the W&B server returns a refresh token that renews the access token until the issuer's session timeout (@ckacal in https://github.com/wandb/wandb/pull/13082)

### Fixed

- Tables with integer column names now preserve their column types when read from artifacts, allowing rows to be added and the table to be saved again.
- `Api.automations()` lists push notification automations (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/13282)
- Installing `wandb` from source on Android (Termux) now builds for Android instead of failing on a glibc Linux Rust target (@dmitryduev in https://github.com/wandb/wandb/pull/13289)
- Launch agents in secure mode now reject jobs with SageMaker or Vertex resource arguments (@nicholaspun-wandb in https://github.com/wandb/wandb/pull/13202)
- In LEET, a remote run opened before it logged any history did not update its state, summary or system metrics while it was running (@dmitryduev in https://github.com/wandb/wandb/pull/13221)
- `wandb leet symon` scaled the GPU PCIe and NVLink throughput charts and the Trainium memory charts by 1024³ on top of the bytes that the monitor reports, so their y-axis labels read like `7.67e+09GB/s` instead of `7.67GB/s` (@dmitryduev in https://github.com/wandb/wandb/pull/13191)
- System metrics were not collected when `TMPDIR` was longer than about 60 characters or on a filesystem without Unix socket support (@dmitryduev in https://github.com/wandb/wandb/pull/13200)
- System metrics were not collected when the temp directory was missing or not writable (@dmitryduev in https://github.com/wandb/wandb/pull/13204)
- Reduced artifact upload request batch sizes to lower the risk of backend timeouts when logging artifacts with many files (@pinglei in https://github.com/wandb/wandb/pull/13198).
- `File.download()` no longer fails with `invalid URL escape` when a file name contains a `%` (@jacobromero in https://github.com/wandb/wandb/pull/13177)
- `wandb.watch` histograms are now correctly displayed for parameters and gradients where all values are identical (@jacobromero in https://github.com/wandb/wandb/pull/13260)
