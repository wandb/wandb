.PHONY: build install clean test

# Determine OS and set library name accordingly
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    LIB_EXT := dylib
    TARGET_LIB := libarrow_rs_wrapper.dylib
    DEST_LIB := librust_parquet_ffi.dylib
else ifeq ($(UNAME_S),Linux)
    LIB_EXT := so
    TARGET_LIB := libarrow_rs_wrapper.so
    DEST_LIB := librust_parquet_ffi.so
else
    LIB_EXT := dll
    TARGET_LIB := arrow_rs_wrapper.dll
    DEST_LIB := rust_parquet_ffi.dll
endif

# Paths
TARGET_DIR := target/release
GO_DIR := ../../core/internal/runhistoryreader

# Default target
all: build

# Build the Rust library
build:
	@echo "Building Rust library..."
	cargo build --release
	@echo "Build complete: $(TARGET_DIR)/$(TARGET_LIB)"

# Install the library to the Go directory
install: build
	@echo "Installing library to $(GO_DIR)..."
	cp $(TARGET_DIR)/$(TARGET_LIB) $(GO_DIR)/$(DEST_LIB)
	@echo "Installation complete: $(GO_DIR)/$(DEST_LIB)"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	cargo clean
	rm -f $(GO_DIR)/$(DEST_LIB)
	@echo "Clean complete"

# Run tests
test:
	@echo "Running tests..."
	cargo test

# Build and install in one step
.DEFAULT_GOAL := install
