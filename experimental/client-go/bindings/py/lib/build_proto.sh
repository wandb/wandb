#!/bin/bash

set -e
BASE=../../../..
DEST=core/lang/py/lib/
# cp $BASE/wandb/proto/*.proto wandb/proto/
cd $BASE/
protoc -I=. --python_out=$DEST wandb/proto/wandb_base.proto
protoc -I=. --python_out=$DEST wandb/proto/wandb_internal.proto
protoc -I=. --python_out=$DEST wandb/proto/wandb_telemetry.proto
protoc -I=. --python_out=$DEST wandb/proto/wandb_settings.proto
protoc -I=. --python_out=$DEST wandb/proto/wandb_server.proto
