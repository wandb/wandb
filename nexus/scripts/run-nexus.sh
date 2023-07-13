#!/usr/bin/env bash
#
# Script used to start nexus from a go development directory.
#
# Usage in wandb:
#   _WANDB_NEXUS_PATH=${NEXUS_DIR}/scripts/run-nexus.sh ./require-nexus.py

set -e
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE
go run cmd/nexus/main.go $*
