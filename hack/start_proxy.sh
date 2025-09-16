#!/bin/bash

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
go run cmd/ws3proxy/main.go > logs/file_proxy.log 2>&1 &
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