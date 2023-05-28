#!/usr/bin/env bash
# From: https://github.com/dnephin/pre-commit-golang/blob/master/run-go-build.sh


cd nexus
FILES=$(go list ./...  | grep -v /vendor/)
exec go build $FILES
