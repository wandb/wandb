#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-vet.sh

set -e
for f in $(echo $@|xargs -n1 dirname | sort -u); do
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
    echo "Running go vet on $mod/$rest"
    go vet $mod/$rest
    cd -
done
