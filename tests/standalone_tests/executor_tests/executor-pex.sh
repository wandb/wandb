#!/bin/bash
set -e

script_dir=$(dirname "$(realpath "$0")")
pushd $script_dir

pex -r pex_requirements.txt -o pex_script.pex
./pex_script.pex -- ./flask_app.py --port=8000 &
flask_pid=$!

sleep 10

# Loop to make 3 curl requests
for i in {1..3}
do
    status_code=$(curl -s -w "%{http_code}" -o /dev/null http://localhost:8000/wandb)
    if [ $status_code -eq 200 ]; then
        echo "Curl request $i succeeded"
    else
        echo "Error: curl request $i failed"
        exit 1
    fi
done

# Kill the process
kill -9 $flask_pid
popd

exit 0
