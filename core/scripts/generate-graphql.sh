#!/usr/bin/env bash

set -e

# make sure we are running from the core dir
BASE=$(dirname $(dirname $(readlink -f $0)))

GQL_GEN_PATH="internal/gql"
PREVIOUS_FILE="gql_gen.go"
GENERATED_FILE="gql_gen.latest.go"

# generate graphql go code
# if successful, this will create a file called gql_gen.latest.go in internal/gql

cd $BASE/api/graphql

if [ ! -f "schemas/schema-latest.graphql" ]; then
    echo "ERROR: Not generating graphql as there is no schema-latest."
    exit 1
fi
go run $BASE/cmd/generate_gql genqlient.yaml


# - Bump version in case of a schema change with --schema-change flag.
# - Do not bump version if there is no schema change
#   and you are e.g. just adding a new query or mutation
#   against the schema that already supports it.
cd $BASE/$GQL_GEN_PATH

# Check for --schema-change flag
if [ "$1" == "--schema-change" ]; then
    # Find the highest current version number
    CURRENT_VERSION=$(ls -d v*/ | sed 's/v//;s/\///' | sort -nr | head -n1)

    # Check if no version directories exist
    if [ -z "$CURRENT_VERSION" ]; then
        CURRENT_VERSION=1
    fi

    # Calculate the next version number
    NEXT_VERSION=$((CURRENT_VERSION + 1))
    # Create next version directory and copy gql_gen.go there
    mkdir "v$NEXT_VERSION"
    mv "$PREVIOUS_FILE" "v$NEXT_VERSION/"
fi

# Rename the latest generated file to gql_gen.go
mv "$GENERATED_FILE" "$PREVIOUS_FILE"
