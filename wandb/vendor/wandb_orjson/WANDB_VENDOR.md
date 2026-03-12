# Modifications made

This package has modifications made by the W&B team needed to fully implement Orjson into the W&B SDK.
Changes include:

- Added `OPT_FAIL_ON_INVALID_FLOAT`, which causes the library to raise an error when trying to serialize invalid floating point values (`NaN`, `Infinity`, `-Infinity`). Previously, these values were automatically converted to `null`/`None`.
    - The changes made are stored under `wandb_changes.patch` and can be recreated with `git apply wandb_changes.patch`

# Updating Orjson

Orjson is pulled into the wandb repo as a subtree, allowing updates and changes to files to be tracked in the main wandb repo.
To sync updates with Orjson, you can run (or see the process) in `vendor_scripts/update_orjson.sh`

## Updating the patch file

`vendor_scripts/wandb_changes.patch` contains an easy way to reapply the local changes if necessary using `git apply vendor_scripts/wandb_changes.patch`.

However if the changes cannot be cleanly applied (i.e. conflicts exist after updating orjson), the patch will need to be recreated after resolving any issues. This can be created with `vendor_scripts/update_changes_patch.sh`
