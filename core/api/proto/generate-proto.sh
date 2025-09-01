#!/usr/bin/env bash

set -e

__SCRIPT__=$(readlink -f "$0")
__DIR__=$(dirname "$__SCRIPT__")
cd $__DIR__
./install-protoc.sh 23.4
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# make sure we are running from the root of the repo
BASE=$(dirname $(dirname $(dirname $(dirname "$__SCRIPT__"))))
cd $BASE

echo "[INFO] generate-proto.sh: Generating protobuf files"
# hack to make sure we use our local protoc
export PATH="$HOME/.local/bin:$PATH"

protoc --go_out=. --go-grpc_out=. --proto_path=. wandb/proto/*.proto
