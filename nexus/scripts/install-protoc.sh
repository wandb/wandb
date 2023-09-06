#!/usr/bin/env bash
set -e
VER=$1
COMMAND="protobuf"

if [ "x$VER" == "x" ]; then
    echo "ERROR: script requires desired protobuf version (for example \"23.4\")"
    exit 1
fi

function get_os_arch {
    OSTYPE=$(uname -o)
    CPUTYPE=$(uname -m)
    if [ "$OSTYPE" == "Darwin" ]; then
        if [ "$CPUTYPE" == "arm64" ]; then
            echo "osx-aarch_64"
        else
            echo "osx-x86_64"
        fi
    else
        echo "linux-x86_64"
    fi
}

LOCALVER=$($HOME/.local/bin/protoc --version | cut -d" " -f2)
if [ "x$VER" == "x$LOCALVER" ]; then
    echo "[INFO] install-protoc.sh: Not Updating \"$COMMAND\" (Found version $LOCALVER)"
    exit 0
fi

OS_ARCH=$(get_os_arch)
PB_REL="https://github.com/protocolbuffers/protobuf/releases"
FNAME="protoc-${VER}-${OS_ARCH}.zip"
curl -L -o /tmp/${FNAME} $PB_REL/download/v${VER}/${FNAME}
unzip -o /tmp/${FNAME} -d $HOME/.local
