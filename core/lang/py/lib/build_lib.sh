#!/bin/bash

set -e
BASE=../../
DEST=py/lib/
cd $BASE/
./scripts/base-build.sh
mkdir -p $DEST/wandb/lib
cp export/lib/libwandb_core.so $DEST/wandb/lib
