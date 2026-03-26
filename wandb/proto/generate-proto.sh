#!/usr/bin/env bash
# Generate Python protobuf bindings for all supported protobuf major versions.
#
# Usage:
#   wandb/proto/generate-proto.sh          # generate all versions
#   wandb/proto/generate-proto.sh 5 7      # generate only v5 and v7
#
# Protoc binaries are cached in .protoc/<version>/ at the repo root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROTOC_CACHE="$REPO_ROOT/.protoc"

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
# protoc version ↔ protobuf Python major version mapping
#
# protobuf X.Y.Z uses protoc Y.Z
# See https://protobuf.dev/support/version-support/
# ---------------------------------------------------------------------------

declare -A PROTOC_VERSIONS=(
    [4]="23.4"
    [5]="27.0"
    [6]="32.1"
    [7]="34.1"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

get_os_arch() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"

    if [ "$os" = "Darwin" ]; then
        if [ "$arch" = "arm64" ]; then
            echo "osx-aarch_64"
        else
            echo "osx-x86_64"
        fi
    else
        echo "linux-x86_64"
    fi
}

# Ensure a specific protoc version is available in .protoc/<ver>/bin/protoc.
ensure_protoc() {
    local ver="$1"
    local dest="$PROTOC_CACHE/$ver"

    if [ -x "$dest/bin/protoc" ]; then
        return
    fi

    echo "[INFO] Downloading protoc $ver..."
    local os_arch fname url
    os_arch="$(get_os_arch)"
    fname="protoc-${ver}-${os_arch}.zip"
    url="https://github.com/protocolbuffers/protobuf/releases/download/v${ver}/${fname}"

    mkdir -p "$dest"
    curl -fsSL -o "/tmp/${fname}" "$url"
    unzip -qo "/tmp/${fname}" -d "$dest"
    rm -f "/tmp/${fname}"
    echo "[INFO] Installed protoc $ver → $dest/bin/protoc"
}

# Generate Python protobuf bindings for a single major version.
generate() {
    local pb_major="$1"
    local protoc_ver="$2"
    local protoc="$PROTOC_CACHE/$protoc_ver/bin/protoc"
    local out_dir="$REPO_ROOT/wandb/proto/v${pb_major}"

    echo "[INFO] Generating Python bindings for protobuf v${pb_major} (protoc ${protoc_ver})"

    mkdir -p "$out_dir"

    for proto_file in "${PROTO_FILES[@]}"; do
        "$protoc" \
            -I "$REPO_ROOT" \
            "--python_out=$out_dir" \
            "--pyi_out=$out_dir" \
            "$REPO_ROOT/wandb/proto/${proto_file}"
    done

    # protoc mirrors the import path inside out_dir: move files up.
    if [ -d "$out_dir/wandb/proto" ]; then
        mv -f "$out_dir/wandb/proto/"*pb2* "$out_dir/"
        rm -rf "$out_dir/wandb"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# If arguments given, treat them as specific pb major versions to generate.
# Otherwise generate all.
if [ $# -gt 0 ]; then
    requested=("$@")
else
    requested=(4 5 6 7)
fi

# Download all needed protoc versions first (fast if already cached).
for pb in "${requested[@]}"; do
    protoc_ver="${PROTOC_VERSIONS[$pb]:-}"
    if [ -z "$protoc_ver" ]; then
        echo "ERROR: Unknown protobuf major version: $pb" >&2
        echo "  Supported: ${!PROTOC_VERSIONS[*]}" >&2
        exit 1
    fi
    ensure_protoc "$protoc_ver"
done

# Generate.
for pb in "${requested[@]}"; do
    generate "$pb" "${PROTOC_VERSIONS[$pb]}"
done

echo "[INFO] Done."
