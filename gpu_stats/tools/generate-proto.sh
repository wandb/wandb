#!/usr/bin/env bash

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

# Run the Rust proto generation
echo "[INFO] generate-proto.sh: Generating Rust protobuf files"
cargo run --bin build_proto
