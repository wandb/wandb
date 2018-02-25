#!/bin/sh

pyenvs="py27 py35 py36"

# reduce to the set we need for this circle node, and interpserse with ","
pyenvs=$(echo $pyenvs \
        | tr " " "\n" \
        | awk "NR % ${CIRCLE_NODE_TOTAL} == ${CIRCLE_NODE_INDEX}" \
        | tr "\n" ",")

# trim trailing ","
TOXENV=${pyenvs%?}

echo "CIRCLE_NODE_INDEX: " $CIRCLE_NODE_INDEX
echo "CIRCLE_NODE_TOTAL: " $CIRCLE_NODE_TOTAL
echo "TOXENV: " $TOXENV

export TOXENV
tox -v --recreate
