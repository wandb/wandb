#!/bin/bash
set -e

pex . -o wandb.pex
./wandb.pex -c "import wandb; import os; wandb.init(mode='offline'); wandb.finish()"
