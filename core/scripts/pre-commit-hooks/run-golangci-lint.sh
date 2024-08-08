#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-golangci-lint.sh

set -eu -o pipefail

if ! command -v golangci-lint &> /dev/null ; then
    echo "golangci-lint not installed or available in the PATH" >&2
    echo "please check https://github.com/golangci/golangci-lint" >&2
    exit 1
fi

cd core
exec golangci-lint run "$@"
