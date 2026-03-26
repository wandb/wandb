#!/usr/bin/env bash
# Generate Python protobuf bindings using a specific protoc version.
#
# Usage:
#   wandb/proto/generate-proto.sh <protoc_version> <output_dir>
#
# Example:
#   wandb/proto/generate-proto.sh 27.0 wandb/proto/v5
#
# Protoc binaries are cached in .protoc/<version>/ at the repo root.

set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <protoc_version> <output_dir>" >&2
    exit 1
fi

PROTOC_VER="$1"
OUT_DIR="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROTOC_CACHE="$REPO_ROOT/.protoc"
PROTOC="$PROTOC_CACHE/$PROTOC_VER/bin/protoc"

PROTO_FILES=(
    wandb_base.proto
    wandb_internal.proto
    wandb_settings.proto
    wandb_telemetry.proto
    wandb_server.proto
    wandb_sync.proto
    wandb_api.proto
)

# ---------------------------------------------------------------------------
# Ensure protoc is cached
# ---------------------------------------------------------------------------

if [ ! -x "$PROTOC" ]; then
    os="$(uname -s)"
    arch="$(uname -m)"
    if [ "$os" = "Darwin" ]; then
        if [ "$arch" = "arm64" ]; then
            os_arch="osx-aarch_64"
        else
            os_arch="osx-x86_64"
        fi
    else
        os_arch="linux-x86_64"
    fi

    echo "[INFO] Downloading protoc $PROTOC_VER..."
    fname="protoc-${PROTOC_VER}-${os_arch}.zip"
    url="https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VER}/${fname}"

    mkdir -p "$PROTOC_CACHE/$PROTOC_VER"
    curl -fsSL -o "/tmp/${fname}" "$url"
    unzip -qo "/tmp/${fname}" -d "$PROTOC_CACHE/$PROTOC_VER"
    rm -f "/tmp/${fname}"
fi

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

echo "[INFO] $("$PROTOC" --version) → $OUT_DIR"

mkdir -p "$OUT_DIR"

for proto_file in "${PROTO_FILES[@]}"; do
    "$PROTOC" \
        -I "$REPO_ROOT" \
        "--python_out=$OUT_DIR" \
        "--pyi_out=$OUT_DIR" \
        "$REPO_ROOT/wandb/proto/${proto_file}"
done

# protoc mirrors the import path inside OUT_DIR; move files up.
if [ -d "$OUT_DIR/wandb/proto" ]; then
    mv -f "$OUT_DIR/wandb/proto/"*pb2* "$OUT_DIR/"
    rm -rf "$OUT_DIR/wandb"
fi
