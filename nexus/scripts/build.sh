#!/bin/bash

DIR="$(dirname "$(realpath "$0")")"
BASE="$(realpath ${DIR}/../..)"

build () {
    local os=$1
    local arch=$2

    echo "Build wandb-nexus ($os $arch)..."
    cd $BASE/nexus
    GOOS=$os GOARCH=$arch go build -ldflags="-s -w" -o bin/wandb-nexus-$os-$arch cmd/nexus_server/main.go
    # CPU=$(uname -m | tr "[:upper:]" "[:lower:]")
    # OS=$(uname -s | tr "[:upper:]" "[:lower:]")
    BINPATH="$BASE/wandb/bin/bin-${os}-${arch}"
    mkdir -p $BINPATH
    cp bin/wandb-nexus-$os-$arch ${BINPATH}/wandb-nexus
}

build darwin arm64
build darwin amd64
build linux amd64
build windows amd64
