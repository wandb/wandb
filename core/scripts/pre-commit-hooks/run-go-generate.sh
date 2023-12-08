#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-generate.sh

set -eu -o pipefail

# Use passed in directory from arg1, or default to full tree
DIR=${1:-./...}

cd core
go generate $DIR
