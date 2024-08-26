#!/usr/bin/env bash

# Run this in the root directory like:
# ./scripts/proto-build.sh

# NOTE: this needs to be reworked.
# proto files should be unmodified from wandb/wandb repo
# and the following calls to protoc shouldn't need to be so hardcoded

# Other notes
# go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
# mkdir -p proto
#cp ~/work/wb/wandb/wandb/proto/*.proto proto/

set -e

# make sure we are running from the core dir
BASE=$(dirname $(dirname $(dirname $(readlink -f $0))))
cd $BASE

# hack to make sure we use our local protoc
export PATH="$HOME/.local/bin:$PATH"

./core/scripts/update-dev-env.sh protocolbuffers/protobuf
./core/scripts/update-dev-env.sh protoc-gen-go

MOD=core/pkg/service_go_proto/

protoc \
    --go_opt=Mwandb/proto/wandb_internal.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_base.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_telemetry.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_settings.proto=$MOD \
    --go_out=. --proto_path=. wandb/proto/wandb_internal.proto

protoc \
    --go_opt=Mwandb/proto/wandb_base.proto=$MOD \
    --go_out=. --proto_path=. wandb/proto/wandb_base.proto

protoc \
    --go_opt=Mwandb/proto/wandb_base.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_telemetry.proto=$MOD \
    --go_out=. --proto_path=. wandb/proto/wandb_telemetry.proto

protoc \
    --go_opt=Mwandb/proto/wandb_settings.proto=$MOD \
    --go_out=. --proto_path=. wandb/proto/wandb_settings.proto

protoc \
    --go_opt=Mwandb/proto/wandb_base.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_telemetry.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_settings.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_internal.proto=$MOD \
    --go_opt=Mwandb/proto/wandb_server.proto=$MOD \
    --go_out=. --proto_path=. wandb/proto/wandb_server.proto
