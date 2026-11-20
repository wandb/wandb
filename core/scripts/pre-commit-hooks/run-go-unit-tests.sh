#!/usr/bin/env bash

set -e

# Git and prek export repository-local variables such as GIT_DIR and
# GIT_WORK_TREE to hooks. Clear them, as githooks(5) advises for hooks that
# run git in another repository, so tests that create their own repositories
# don't operate on this checkout:
# https://git-scm.com/docs/githooks#_description
unset $(git rev-parse --local-env-vars)

cd core
go test -short -timeout 30s ./...
