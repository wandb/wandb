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

- `wandb.Molecule` no longer drops the directory of a `pathlib.Path` input, so a path such as `Path('/data/mol.pdb')` is found instead of raising `FileNotFoundError` for `mol.pdb` (@sohailshk in https://github.com/wandb/wandb/pull/13383)
