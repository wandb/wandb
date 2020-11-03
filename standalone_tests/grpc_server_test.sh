#!/bin/bash
# hack until we fix debug-cli.log
mkdir -p wandb
echo "Stopping all old grpc-server"
set +e
(ps auxw | grep "wandb grpc-server" | grep -v grep | awk '{print $2}' | xargs kill) 2>/dev/null
set -e
echo "Wait for servers to be gone..."
sleep 1
echo "Running grpc-server in the background..."
pyenv exec wandb grpc-server &
echo "Wait for server to be up..."
sleep 1
echo "Starting grpc client..."
pyenv exec python grpc_client.py
echo "done."
