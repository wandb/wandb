#!/bin/bash
# Example usage:
# ./tools/tox-loop.sh --num 2 -e py38 -- tests/test_sender.py -k test_save_live_glob_multi_write

DATE=`date +%Y%m%d_%H%M%S`
RESULTS="tox-results"
set -e
mkdir -p $RESULTS
mkdir -p $RESULTS/$DATE
NUM=5
if [ "x$1" == "x--num" ]; then
  shift
  NUM=$1
  shift
fi
for n in `seq $NUM`; do
  echo "Running: $n"
  tox $* 2>&1 | tee $RESULTS/$DATE/out-$n.txt
done
