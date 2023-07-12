#!/usr/bin/env bash
set -e
VER=$1

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
    exit 0
fi

OS_ARCH=$(get_os_arch)
PB_REL="https://github.com/protocolbuffers/protobuf/releases"
curl -LO $PB_REL/download/v${VER}/protoc-${VER}-${OS_ARCH}.zip
unzip -o protoc-${VER}-${OS_ARCH}.zip -d $HOME/.local
