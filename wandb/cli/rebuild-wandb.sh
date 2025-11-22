#!/bin/bash

# W&B CLI Rebuild Script
# Run from anywhere with: ~/wandb/wandb/cli/rebuild-wandb.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the script's directory and find the repo root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WANDB_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}           W&B CLI Development Build Script              ${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo ""

# Parse arguments
SKIP_GPU=true
TEST_HELP=false
COMMAND_TO_TEST="offline"

while [[ $# -gt 0 ]]; do
    case $1 in
        --with-gpu)
            SKIP_GPU=false
            shift
            ;;
        --test-help)
            TEST_HELP=true
            shift
            ;;
        --test-command)
            TEST_HELP=true
            COMMAND_TO_TEST="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --with-gpu          Include GPU stats (requires Rust/cargo)"
            echo "  --test-help         Test 'wandb offline --help' after build"
            echo "  --test-command CMD  Test 'wandb CMD --help' after build"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                     # Quick rebuild, skip GPU stats"
            echo "  $0 --test-help         # Rebuild and test offline help"
            echo "  $0 --test-command sync # Rebuild and test sync help"
            echo "  $0 --with-gpu          # Full rebuild with GPU support"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Change to wandb directory
echo -e "${YELLOW}📂 W&B repository root: $WANDB_DIR${NC}"
cd "$WANDB_DIR"

# Check for Go installation
echo -e "${YELLOW}🔍 Checking Go installation...${NC}"
if command -v go &> /dev/null; then
    GO_VERSION=$(go version | cut -d' ' -f3)
    echo -e "${GREEN}   ✓ Go installed: $GO_VERSION${NC}"
    
    # Check Go version in go.mod
    if [ -f "core/go.mod" ]; then
        REQUIRED_GO=$(grep "^go " core/go.mod | awk '{print $2}')
        echo -e "${BLUE}   📋 go.mod requires: Go $REQUIRED_GO${NC}"
    fi
else
    echo -e "${RED}   ✗ Go not found! Please install Go first.${NC}"
    exit 1
fi

# Build command
BUILD_CMD="pip install -e . --force-reinstall --no-deps"
if [ "$SKIP_GPU" = true ]; then
    BUILD_CMD="WANDB_BUILD_SKIP_GPU_STATS=1 $BUILD_CMD"
    echo -e "${YELLOW}⚡ Skipping GPU stats build (no Rust required)${NC}"
else
    # Check for Rust if GPU build is requested
    if command -v cargo &> /dev/null; then
        echo -e "${YELLOW}🦀 Including GPU stats (Rust/cargo found)${NC}"
    else
        echo -e "${RED}   ⚠️  Rust/cargo not found!${NC}"
        echo -e "${YELLOW}   Falling back to skip GPU stats...${NC}"
        BUILD_CMD="WANDB_BUILD_SKIP_GPU_STATS=1 $BUILD_CMD"
        SKIP_GPU=true
    fi
fi

# Run the build
echo -e "${YELLOW}🔨 Building W&B CLI...${NC}"
echo -e "${BLUE}   Command: $BUILD_CMD${NC}"
echo ""

if eval $BUILD_CMD; then
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✅ W&B CLI build successful!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    
    # Show version
    echo ""
    echo -e "${BLUE}📦 Installed version:${NC}"
    wandb --version
    
    # Show which wandb is being used
    echo -e "${BLUE}📍 Using wandb from:${NC}"
    which wandb
    
    # Test help if requested
    if [ "$TEST_HELP" = true ]; then
        echo ""
        echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
        echo -e "${BLUE}📖 Testing: wandb $COMMAND_TO_TEST --help${NC}"
        echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
        echo ""
        wandb $COMMAND_TO_TEST --help
    fi
else
    echo ""
    echo -e "${RED}════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}❌ Build failed!${NC}"
    echo -e "${RED}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}Troubleshooting tips:${NC}"
    echo "  1. Check if Go version matches go.mod requirements"
    echo "  2. For GPU support, ensure Rust/cargo is installed"
    echo "  3. Check for any Python dependency issues"
    echo "  4. Try: pip install --upgrade pip hatchling"
    exit 1
fi

echo ""
echo -e "${GREEN}🎉 Done! You can now use the updated wandb CLI.${NC}"
echo ""
echo -e "${YELLOW}Quick commands:${NC}"
echo "  wandb --help           # Show main help"
echo "  wandb offline --help   # Show offline command help"
echo "  wandb online --help    # Show online command help"
echo "  wandb sync --help      # Show sync command help"
