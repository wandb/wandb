#!/usr/bin/env bash

set -e

# From ariadne-codegen, we don't currently need the generated httpx client,
# exceptions, etc., so drop the modules generated for these, in favor of
# the existing internal GQL client.
IGNORED_MODULES=(
  "base_client.py"
  "async_base_client.py"
  "client.py"
  "exceptions.py"
)

HERE=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(cd "$HERE" && git rev-parse --show-toplevel)

# Ensure we're at the root directory of the repo
cd "$PROJECT_DIR"

# Reuse the schema that's already used to generate for wandb-core (Go)
INPUT_SCHEMA_PATH="$PROJECT_DIR/core/api/graphql/schemas/schema-latest.graphql"

OUTPUT_DIR="$PROJECT_DIR/wandb/sdk/automations/_generated"

CODEGEN_CONFIG="$PROJECT_DIR/tools/pydantic_codegen/codegen-automations.toml"
PROJECT_CONFIG="$PROJECT_DIR/pyproject.toml"

if [ ! -f "$INPUT_SCHEMA_PATH" ]; then
    echo "ERROR: Not generating graphql as there is no schema-latest at: $INPUT_SCHEMA_PATH"
    exit 1
fi

# TODO: Backup the existing output directory
# Create the target directory if needed and replace its contents
mkdir -pv "$OUTPUT_DIR"
rm -rvf "${OUTPUT_DIR:?}"/*

# Generate only necessary python types and code from the GraphQL schemas and queries
printf "\n========== Generating Python code from GraphQL definitions ==========\n"
PYTHONPATH="$PROJECT_DIR/tools/" ariadne-codegen --config "$CODEGEN_CONFIG"

# Apply ruff formatting to the generated modules
printf "\n========== Reformatting generated code ==========\n"
ruff check --fix --unsafe-fixes --config "$PROJECT_CONFIG" "$OUTPUT_DIR"
ruff format --config "$PROJECT_CONFIG" "$OUTPUT_DIR"

# Remove the generated modules we don't need
printf "\n========== Removing unnecessary files ==========\n"
for file_path in "$OUTPUT_DIR"/*; do
    file_name=$(basename "$file_path")
    if [[ ${IGNORED_MODULES[*]} =~ $file_name ]]; then
        rm -v "$file_path"
    fi
done
