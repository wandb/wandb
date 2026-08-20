#!/usr/bin/env bash

set -e

# Navigate one directory up to execute the cargo command
# from the root of the rust-sdk project.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

# Run the Rust proto generation.
echo "[INFO] generate-proto.sh: Generating Rust protobuf files for rust-sdk"
cargo run --bin build_proto --features proto-gen
