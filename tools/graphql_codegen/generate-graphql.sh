#!/usr/bin/env bash

# This script generates **Python** code from GraphQL schemas and queries.

set -e

# Path variables etc.
PROJECT_DIR=$(git rev-parse --show-toplevel)

CODEGEN_CONFIGS=(
    # Append more codegen configs here as needed
    "$PROJECT_DIR/tools/graphql_codegen/automations/automations.toml"
    "$PROJECT_DIR/tools/graphql_codegen/utils/utils.toml"
    "$PROJECT_DIR/tools/graphql_codegen/artifacts/artifacts.toml"
    "$PROJECT_DIR/tools/graphql_codegen/projects/projects.toml"
)

# Reuse the schema that's already used to generate for wandb-core (Go)
SCHEMA_DIR="$PROJECT_DIR/core/api/graphql/schemas"
SCHEMA_COMMIT=$(cat "$SCHEMA_DIR/commit.hash.txt")  # get the commit hash

SCHEMA_PATH="$SCHEMA_DIR/schema-latest-${SCHEMA_COMMIT}.graphql"
SCHEMA_SYMLINK_PATH="$SCHEMA_DIR/schema-latest.graphql"

if [ ! -f "$SCHEMA_PATH" ]; then
    echo "[INFO] Schema file does not exist: $SCHEMA_PATH"
    (
        # Fetch the schema
        # Create a temporary directory to clone into, but ensure it's cleaned up on exit
        TEMP_DIR=$(mktemp -d)
        function cleanup() {
            rm -rf $TEMP_DIR
        }
        trap cleanup EXIT SIGINT SIGQUIT SIGTERM
        cd $TEMP_DIR

        # download the latest schemaa
        repo_dir=core
        repo_schema_path=services/gorilla/schema.graphql
        echo "[INFO] Downloading latest schema for commit hash: $SCHEMA_COMMIT"
        git clone -n --depth=1 --filter=tree:0 https://github.com/wandb/core "$repo_dir"
        (
            cd "$repo_dir"
            git checkout "$SCHEMA_COMMIT" "$repo_schema_path"

            # Remove any existing schema files before copying the new one
            rm -vf "$SCHEMA_DIR/schema-latest*.graphql"
            mv "$repo_schema_path" "$SCHEMA_PATH"
        )
        rm -rf "$repo_dir"
    )
    ln -svf "$SCHEMA_PATH" "$SCHEMA_SYMLINK_PATH"
else
    echo "[INFO] Schema file already exists, skipping download: $SCHEMA_PATH"
fi

(
    # Ensure we're at the root directory of the repo
    cd "$PROJECT_DIR"

    # Generate only necessary python types and code from the GraphQL schemas and queries
    for codegen_config in "${CODEGEN_CONFIGS[@]}"; do
        printf "\n========== Generating Python code from GraphQL definitions for: $codegen_config ==========\n"
        PYTHONPATH="$PROJECT_DIR/tools" ariadne-codegen --config "$codegen_config"
    done

    printf "\n========== Successfully generated graphql code for commit hash: $SCHEMA_COMMIT ==========\n"
)
