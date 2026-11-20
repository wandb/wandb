#!/usr/bin/env bash

set -e

# Some Go tests create temporary git repositories. Hooks run with
# repository-local variables such as GIT_DIR and GIT_WORK_TREE set, which
# would make those tests operate on this checkout instead. Clear them, as
# githooks(5) advises for hooks that run git in another repository:
# https://git-scm.com/docs/githooks#_description
unset $(git rev-parse --local-env-vars)

cd core
go test -short -timeout 30s ./...
