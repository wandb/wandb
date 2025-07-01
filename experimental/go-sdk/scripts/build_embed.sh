#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Accept as an argument for the output file for the core binary, it should be
# relative to the root of this project
REL_OUTPUT_BIN=$1

# Get the absolute path of the script
PROJECT_ROOT=$(realpath "$(dirname "$0")/..")

# Change directory to the root of the wandb core project so we can build the
# core binary
cd $(realpath "${PROJECT_ROOT}/../../core")

# Build the embed core binary
go build -o ${PROJECT_ROOT}/${REL_OUTPUT_BIN} cmd/wandb-core/main.go
