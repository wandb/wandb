#!/bin/bash

# Check if WANDB_OBJECT_STORAGE_PREFIX is set
if [ -z "$WANDB_OBJECT_STORAGE_PREFIX" ]; then
    echo "Error: WANDB_OBJECT_STORAGE_PREFIX environment variable is not set."
    echo ""
    echo "Please set it to the object storage URL prefix:"
    echo "  For S3 (includes bucket in domain):"
    echo "    export WANDB_OBJECT_STORAGE_PREFIX=https://pinglei-byob-us-west-2.s3.us-west-2.amazonaws.com"
    echo "  For GCS (domain only, bucket is in path):"
    echo "    export WANDB_OBJECT_STORAGE_PREFIX=https://storage.googleapis.com"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo "Using object storage prefix: $WANDB_OBJECT_STORAGE_PREFIX"

# Kill any existing proxy servers
echo "Killing any existing proxy servers..."
./kill_proxy.sh

# Create log directory if it doesn't exist
mkdir -p logs

# Start API proxy with logging
echo "Starting API proxy on port 8181..."
go run cmd/wapiproxy/main.go > logs/api_proxy.log 2>&1 &
API_PID=$!
echo "API proxy started with PID: $API_PID"
echo "Logs: logs/api_proxy.log"

# Start file proxy with logging
echo "Starting file proxy on port 8182..."
(cd cmd/ws3proxy && WANDB_OBJECT_STORAGE_PREFIX="$WANDB_OBJECT_STORAGE_PREFIX" go run main.go > ../../logs/file_proxy.log 2>&1) &
FILE_PID=$!
echo "File proxy started with PID: $FILE_PID"
echo "Logs: logs/file_proxy.log"

# Wait a moment for servers to start
sleep 2

echo ""
echo "Proxy servers are running!"
echo "API Proxy: http://localhost:8181 (PID: $API_PID)"
echo "File Proxy: http://localhost:8182 (PID: $FILE_PID)"
echo ""
echo "To view logs in real-time:"
echo "  tail -f logs/api_proxy.log    # API proxy logs"
echo "  tail -f logs/file_proxy.log   # File proxy logs"
echo ""
echo "To stop servers:"
echo "  ./kill_proxy.sh"