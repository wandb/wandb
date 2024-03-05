#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-mod-tidy.sh

cd core
go mod tidy -v $@
if [ $? -ne 0 ]; then
  exit 2
fi

git diff --exit-code go.* &> /dev/null
if [ $? -ne 0 ]; then
    echo "go.mod or go.sum differs, please re-add it to your commit"
    exit 3
fi
