#!/bin/bash
set -e
echo "Running grpc-server in the background..."
wandb grpc-server &
echo "Starting grpc client..."
python grpc-client.py
echo "done."
