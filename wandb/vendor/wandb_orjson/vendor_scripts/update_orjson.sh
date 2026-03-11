#!/bin/bash

# This script provides a convient way to update the orjson version in the vendor subtree.
# It does so by pulling the latest release tag from the orjson upstream,
# then reapplying the local changes from the wandb_changes.patch file.

# cd into git root
cd $(git rev-parse --show-toplevel)

# Add orjson-upstream as a remote
git remote add orjson-upstream https://github.com/ijl/orjson.git

# Get the latest release tag from orjson upstream
latest_tag=$(git ls-remote --tags --sort="v:refname" orjson-upstream | tail -n 1)
tag_name=$(echo $latest_tag | cut -d/ -f3)

# Checkout the tag only for the vendor subtree
echo "Updating orjson to $tag_name"
git subtree pull \
    --prefix=wandb/vendor/wandb_orjson \
    orjson-upstream $tag_name \
    --squash \
    -m "Update orjson to $tag_name"


# Reapply changes
echo "Reapplying local changes"
git apply wandb/vendor/wandb_orjson/vendor_scripts/wandb_changes.patch
echo "Changes applied, please verify there are no conflicts and commit the changes."
