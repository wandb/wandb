#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-vet.sh

set -e

fail() {
  echo "unit tests failed"
  exit 1
}

cd $(dirname $(dirname $(dirname "$0")))

pkg=$(go list ./... | grep -v /vendor/)

go vet $pkg || fail
