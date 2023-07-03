#!/usr/bin/env bash
#
# Install pinned versions of development packages
#
# Usage:
#   ./scripts/install-pinned.sh GOPACKAGESPEC
#
# Example:
#   ./scripts/install-pinned.sh google.golang.org/protobuf/cmd/protoc-gen-go

# make sure we are running from the nexus dir
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE

set -e
VERSION=`grep $1 scripts/install-pinned.txt | cut -d" " -f2`
go install $1@$VERSION
