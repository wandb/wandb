#!/bin/bash
# Example usage:
# ./tools/loop.sh --loop-num 2 tox -e py38 -- tests/test_sender.py -k test_save_live_glob_multi_write

DATE=`date +%Y%m%d_%H%M%S`
RESULTS="loop-results"
set -e
mkdir -p $RESULTS
mkdir -p $RESULTS/$DATE
NUM=5
if [ "x$1" == "x--loop-num" ]; then
  shift
  NUM=$1
  shift
fi
for n in `seq $NUM`; do
  echo "Running: $n"
  $* > >(tee -a $RESULTS/$DATE/out-$n.txt) 2>&1
done
