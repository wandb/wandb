#!/usr/bin/env bash

set -e

# Some Go tests create temporary git repositories. Hooks run with
# repository-local variables such as GIT_DIR and GIT_WORK_TREE set, which
# make those tests operate on this checkout instead. Clear these variables
# before running the tests, using the method suggested by the official
# githooks docs:
# https://git-scm.com/docs/githooks#_description
unset $(git rev-parse --local-env-vars)

cd core
go test -short -timeout 30s ./...
