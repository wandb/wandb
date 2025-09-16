#!/bin/bash

echo "Killing proxy servers..."

# Kill process on port 8181 (API proxy)
PID_8181=$(lsof -ti :8181)
if [ ! -z "$PID_8181" ]; then
    echo "Killing API proxy on port 8181 (PID: $PID_8181)"
    kill -9 $PID_8181
else
    echo "No process found on port 8181"
fi

# Kill process on port 8182 (File proxy)  
PID_8182=$(lsof -ti :8182)
if [ ! -z "$PID_8182" ]; then
    echo "Killing File proxy on port 8182 (PID: $PID_8182)"
    kill -9 $PID_8182
else
    echo "No process found on port 8182"
fi

echo "Done"