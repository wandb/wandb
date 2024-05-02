#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-unit-tests.sh

set -e

fail() {
  echo "unit tests failed"
  exit 1
}

for f in $(echo $@| xargs -n1 dirname | sort -u); do
    # Temporary hack
    if [[ $f == "experiment"* ]]; then
        continue
    fi

    if [ "$f" == "core" ]; then
        continue
    fi
    base=$(echo $f | cut -d/ -f1)
    rest=$(echo $f | cut -d/ -f2-)
    cd $base
    mod=$(go list)
    go test -race -tags=unit -timeout 30s -short -v $mod/$rest || fail
    cd -
done
