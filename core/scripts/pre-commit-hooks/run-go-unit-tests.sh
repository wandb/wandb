#!/usr/bin/env bash

set -e

cd core
go test -short -timeout 30s ./...
