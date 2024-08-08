#!/usr/bin/env bash
#
# Script used to configure core debug env variable which informs
# wandb/wandb to use this core dev dir through the _WANDB_CORE_PATH
# environment variable
#
# Usage:
#   source scripts/setup-core-path.sh
#   source scripts/setup-core-path.sh --unset

PROG="${BASH_SOURCE[0]:-$0}"
ARG=$1
BASE=$(dirname $(dirname $(readlink -f $PROG)))

if [ "x$ARG" = "x--unset" ]; then
    echo "[INFO]: Clearing core dev dir."
    unset _WANDB_CORE_PATH
else
    echo "[INFO]: Setting core dev dir to ${BASE}."
    export _WANDB_CORE_PATH=${BASE}/scripts/run-core.sh
    # run the rest of the commandline with the set environment
    if [ $# -ne 0 ]; then
        $@
    fi
fi
