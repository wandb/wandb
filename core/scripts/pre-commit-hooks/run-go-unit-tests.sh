#!/usr/bin/env bash

set -e

# Git exports repository-local variables such as GIT_DIR to hooks. Clear them
# so tests that create their own repositories don't operate on this checkout.
unset $(git rev-parse --local-env-vars)

cd core
go test -short -timeout 30s ./...
