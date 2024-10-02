#!/usr/bin/env bash
#
# Script used to start core from a go development directory.
#
# Usage in wandb:
#   1) manually setup the path
#     _WANDB_CORE_PATH=${core_DIR}/scripts/run-core.sh python require-core.py
#   2) set the environment variable in your shell
#      source ${core_DIR}/scripts/setup-core-path.sh
#      python ./require-core.py
#   3) setup core path for a single command
#      ${core_DIR}/scripts/setup-core-path.sh python require-core.py
#

set -e
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE
go run cmd/wandb-core/main.go $*
