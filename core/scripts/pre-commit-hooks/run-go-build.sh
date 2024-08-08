#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-build.sh

# shellcheck disable=SC2164
cd core
FILES=$(go list ./...  | grep -v /vendor/)
COMMIT=$(git rev-parse HEAD)
exec go build -ldflags "-X main.commit=$COMMIT" $FILES
