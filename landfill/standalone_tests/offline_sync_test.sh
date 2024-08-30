#!/bin/bash
set -e
echo "Clean old files"
wandb sync --clean --include-offline --clean-force --clean-old-hours=0
echo "Make sure there are no files..."
offline=`ls -d wandb/offline-run-* 2>/dev/null | wc -l | xargs echo`
online=`ls -d wandb/run-* 2>/dev/null | wc -l | xargs echo`
if [ "$offline" != "0" ]; then
  echo "ERROR: Found offline runs: $offline"
  exit 1
fi
if [ "$online" != "0" ]; then
  echo "ERROR: Found online runs: $online"
  exit 1
fi
echo "Running job in offline mode..."
python offline_sync_train.py
echo "Sync directory"
wandb sync wandb/offline-run-*/
echo "done."
