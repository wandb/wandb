#!/usr/bin/env bash

set -e

# Ensure we're at the root directory of the repo
here=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(cd "$here" && git rev-parse --show-toplevel)

cd "$PROJECT_DIR"

INPUT_SCHEMA_PATH="$PROJECT_DIR/core/api/graphql/schemas/schema-latest.graphql"

if [ ! -f "$INPUT_SCHEMA_PATH" ]; then
    echo "ERROR: Not generating graphql as there is no schema-latest at: $INPUT_SCHEMA_PATH"
    exit 1
fi

# via ariadne-codegen
ariadne-codegen --config "$PROJECT_DIR/pyproject.toml"
