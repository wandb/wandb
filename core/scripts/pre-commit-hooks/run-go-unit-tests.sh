#!/usr/bin/env bash

set -e

cd core
go test -timeout 30s ./...
