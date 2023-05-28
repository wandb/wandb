#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-generate.sh

set -eu -o pipefail

cd nexus
go generate ./...
