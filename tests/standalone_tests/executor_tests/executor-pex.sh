#!/bin/bash
set -e

# todo: remove the urllib3 pin once requests, sentry and others are updated
pex "urllib3<2.0.0" -r $1 -o wandb.pex
WANDB__EXECUTABLE=./wandb.pex ./wandb.pex -c "import wandb; import os; wandb.init(mode='offline'); wandb.finish()"
