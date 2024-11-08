#!/usr/bin/env bash

set -e

# make sure we are running from the core dir
BASE=$(dirname $(dirname $(dirname $(readlink -f $0))))

# go to the graphql dir
cd $BASE/api/graphql

# get the commit hash
COMMIT_HASH=$(cat schemas/commit.hash.txt)

# clean up the core dir
rm -rf core

echo "[INFO] Downloading latest schema for commit hash: $COMMIT_HASH"
# download the latest schema
git clone -n --depth=1 --filter=tree:0 https://github.com/wandb/core
cd core
git checkout $COMMIT_HASH services/gorilla/schema.graphql
mv services/gorilla/schema.graphql $BASE/api/graphql/schemas/schema-latest.graphql
cd ..
rm -rf core

# generate graphql go code
if ! go run $BASE/cmd/generate_gql genqlient.yaml; then
  echo "[ERROR] Failed to generate graphql code."
  echo "[ERROR] Verify the commit hash in $BASE/api/graphql/schemas/commit.hash.txt is correct."
  exit 1
fi

echo "[INFO] Successfully generated graphql code for commit hash: $COMMIT_HASH"
