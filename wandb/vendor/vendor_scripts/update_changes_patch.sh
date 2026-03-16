#!/bin/bash

# cd into git root
cd $(git rev-parse --show-toplevel)

# Overwrite patch file
git format-patch -1 HEAD --stdout > wandb/vendor/wandb_orjson/vendor_scripts/wandb_changes.patch
