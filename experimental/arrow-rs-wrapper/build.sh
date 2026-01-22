#!/bin/bash
set -e

# Build script for arrow-rs-wrapper
# This script builds the Rust library and installs it to the Go directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Arrow RS Wrapper Build Script ==="
echo ""

# Check if Rust is installed
if ! command -v cargo &> /dev/null; then
    echo "Error: Cargo not found. Please install Rust: https://rustup.rs/"
    exit 1
fi

echo "✓ Cargo found: $(cargo --version)"
echo ""

# Determine the build mode (default: release)
BUILD_MODE="${1:-release}"

if [ "$BUILD_MODE" = "debug" ]; then
    echo "Building in DEBUG mode..."
    cargo build
    TARGET_DIR="target/debug"
else
    echo "Building in RELEASE mode..."
    cargo build --release
    TARGET_DIR="target/release"
fi

echo ""

# Determine OS and library name
if [[ "$OSTYPE" == "darwin"* ]]; then
    LIB_NAME="libarrow_rs_wrapper.dylib"
    DEST_NAME="librust_parquet_ffi.dylib"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    LIB_NAME="libarrow_rs_wrapper.so"
    DEST_NAME="librust_parquet_ffi.so"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    LIB_NAME="arrow_rs_wrapper.dll"
    DEST_NAME="rust_parquet_ffi.dll"
else
    echo "Error: Unsupported operating system: $OSTYPE"
    exit 1
fi

# Check if the library was built
if [ ! -f "$TARGET_DIR/$LIB_NAME" ]; then
    echo "Error: Library not found at $TARGET_DIR/$LIB_NAME"
    exit 1
fi

echo "✓ Library built: $TARGET_DIR/$LIB_NAME"
LIB_SIZE=$(du -h "$TARGET_DIR/$LIB_NAME" | cut -f1)
echo "  Size: $LIB_SIZE"
echo ""

# Install to Go directory
GO_DIR="../../core/internal/runhistoryreader"
mkdir -p "$GO_DIR"

echo "Installing library to $GO_DIR/$DEST_NAME..."
cp "$TARGET_DIR/$LIB_NAME" "$GO_DIR/$DEST_NAME"

if [ -f "$GO_DIR/$DEST_NAME" ]; then
    echo "✓ Installation successful!"
    echo ""
    echo "The library is now available at:"
    echo "  $GO_DIR/$DEST_NAME"
else
    echo "Error: Installation failed"
    exit 1
fi

echo ""
echo "=== Build Complete ==="
