#!/bin/bash
set -e

pex -r $1 -o wandb.pex
WANDB__EXECUTABLE=./wandb.pex ./wandb.pex -c "import wandb; import os; wandb.init(mode='offline'); wandb.finish()"
