#!/bin/bash
set -e

script_dir=$(dirname "$(realpath "$0")")
pushd $script_dir

uwsgi --master --socket=0.0.0.0:6000 --protocol=http \
  -w flask_app:app --processes=2 --py-executable="$(which python)"&

# Wait for uwsgi to start
sleep 3

# Loop to make 3 curl requests
for i in {1..3}
do
    status_code=$(curl -s -w "%{http_code}" -o /dev/null http://localhost:6000/wandb)
    if [ $status_code -eq 200 ]; then
        echo "Curl request $i succeeded"
    else
        echo "Error: curl request $i failed"
        exit 1
    fi
done

# Kill the uwsgi process if not on ci
if [ -z "$CI" ]; then
    pkill -9 -f uwsgi
fi

popd
