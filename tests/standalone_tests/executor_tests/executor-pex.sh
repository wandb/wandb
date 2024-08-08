#!/bin/bash
set -e

# get current directory
dir="$(dirname "${BASH_SOURCE[0]}")"

# todo: remove the urllib3 pin once requests, sentry and others are updated
pex "urllib3<2.0.0" -r $dir/requirements.txt -o wandb.pex
WANDB__EXECUTABLE=./wandb.pex ./wandb.pex -c "import wandb; import os; wandb.init(mode='offline'); wandb.finish()"
