#!/usr/bin/env bash

set -e

# Git and prek export repository-local variables such as GIT_DIR and
# GIT_WORK_TREE to hooks. Clear them so tests that create their own
# repositories don't operate on this checkout.
# See https://git-scm.com/docs/githooks
unset $(git rev-parse --local-env-vars)

cd core
go test -short -timeout 30s ./...
