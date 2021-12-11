#!/bin/bash
# hack until we fix debug-cli.log
mkdir -p wandb
echo "Stopping all old grpc-server"
set +e
(ps auxw | grep "wandb-service" | grep -v grep | awk '{print $2}' | xargs kill) 2>/dev/null
set -e
echo "Wait for servers to be gone..."
sleep 1
echo "Running wandb service in the background..."
pyenv exec wandb service --grpc-port 50051 --serve-grpc &
echo "Wait for server to be up..."
sleep 1
echo "Starting grpc client..."
pyenv exec python grpc_client.py
echo "done."
