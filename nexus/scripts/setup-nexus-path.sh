#!/usr/bin/env bash
#
# Script used to configure nexus debug env variable which informs
# wandb/wandb to use this nexus dev dir through the _WANDB_NEXUS_PATH
# environment variable
#
# Usage:
#   source scripts/setup-nexus-path.sh
#   source scripts/setup-nexus-path.sh --unset

PROG="${BASH_SOURCE[0]:-$0}"
ARG=$1
BASE=$(dirname $(dirname $(readlink -f $PROG)))

if [ "x$ARG" = "x--unset" ]; then
    echo "[INFO]: Clearing nexus dev dir."
    unset _WANDB_NEXUS_PATH
else
    echo "[INFO]: Setting nexus dev dir to ${BASE}."
    export _WANDB_NEXUS_PATH=${BASE}/scripts/run-nexus.sh
    # run the rest of the commandline with the set environment
    if [ $# -ne 0 ]; then
        $@
    fi
fi
