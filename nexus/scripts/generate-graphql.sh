#!/usr/bin/env bash

set -e

# make sure we are running from the nexus dir
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE/api/graphql

if [ ! -f "schemas/schema-latest.graphql" ]; then
    echo "ERROR: Not generating graphql as there is no schema-latest."
    exit 1
fi
go run github.com/Khan/genqlient genqlient.yaml
