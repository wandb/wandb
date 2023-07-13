#!/usr/bin/env bash
#
# Script used to start nexus from a go development directory.
#
# Usage in wandb:
#   1) manually setup the path
#     _WANDB_NEXUS_PATH=${NEXUS_DIR}/scripts/run-nexus.sh python require-nexus.py
#   2) set the environment variable in your shell
#      source ${NEXUS_DIR}/scripts/setup-nexus-path.sh
#      python ./require-nexus.py
#   3) setup nexus path for a single command
#      ${NEXUS_DIR}/scripts/setup-nexus-path.sh python require-nexus.py
#

set -e
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE
go run cmd/nexus/main.go $*
