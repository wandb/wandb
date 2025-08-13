#!/usr/bin/env bash
# Regenerates files created by https://github.com/google/wire

set -eu -o pipefail

cd core

go run github.com/google/wire/cmd/wire gen ./...
