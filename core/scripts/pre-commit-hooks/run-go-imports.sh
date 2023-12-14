#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-imports.sh

#
# Capture and print stdout, since goimports doesn't use proper exit codes
#
set -e -o pipefail

if ! command -v goimports &> /dev/null ; then
    echo "goimports not installed or available in the PATH" >&2
    echo "please check https://pkg.go.dev/golang.org/x/tools/cmd/goimports" >&2
    exit 1
fi

output="$(goimports -l -w "$@")"
echo "$output"
[[ -z "$output" ]]
