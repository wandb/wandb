#!/bin/bash

# Builds and runs the basic example against a real wandb-core.
#
# wandb-core is taken from WANDB_CORE_PATH, then from an installed wandb
# Python package, then from the binary built into the wandb package in this
# repo, and is otherwise built from source.

set -e

cd "$(dirname "$0")/../.."
repo_root="$(cd ../.. && pwd)"

if [ -z "${WANDB_CORE_PATH:-}" ]; then
    core_bin="$(python -c 'from wandb.util import get_core_path; print(get_core_path())' 2>/dev/null || true)"
    if [ ! -x "$core_bin" ]; then
        core_bin="$repo_root/wandb/bin/wandb-core"
    fi
    if [ ! -x "$core_bin" ]; then
        core_bin="$PWD/target/wandb-core"
        echo "Building wandb-core..."
        (cd "$repo_root/core" && go build -mod=vendor -o "$core_bin" cmd/wandb-core/main.go)
    fi
    export WANDB_CORE_PATH="$core_bin"
fi

echo "Running basic example with wandb-core at $WANDB_CORE_PATH..."
cargo run --example basic
