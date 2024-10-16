#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-unit-tests.sh

set -e

fail() {
  echo "unit tests failed"
  exit 1
}

# Change to the root of the repository
cd "$(dirname $(dirname $(dirname "$0")))" || fail

# Get the list of files to test
FILES=$(go list ./... | grep -v /vendor/) || fail

# Run the unit tests
go test -tags=unit -timeout 30s -short -v ${FILES} || fail
