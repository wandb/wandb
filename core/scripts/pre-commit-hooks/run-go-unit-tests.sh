#!/usr/bin/env bash

set -e

# Git exports repository-local variables such as GIT_DIR to hooks. Clear them
# so tests that create their own repositories don't operate on this checkout.
# Keep the two that carry config, as git does when entering another repository:
# https://github.com/git/git/blob/v2.56.0/run-command.c#L1995-L2004
unset $(git rev-parse --local-env-vars | grep -vxE '(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT)')

cd core
go test -short -timeout 30s ./...
