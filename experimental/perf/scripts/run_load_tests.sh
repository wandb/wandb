#!/bin/bash

# Prints the help message
print_help() {
    echo "Usage: ./run_load_tests.sh -t <testcase> [options]"
    echo "  -t <test case> The test case to run (required) "
    echo "     bench_log | bench_log_scale_step | bench_log_scale_metric "
    echo "  -k <WANDB_API_KEY>                   Wandb API key (optional)"
    echo "  -m online | offline                  Wandb logging mode (optional, default: online)"
    echo
    echo "Example: ./run_load_tests.sh -t bench_log -k abcde123 -m offline"
}

# Parse arguments
while getopts "k:m:t:h" arg; do
  case $arg in
    k) WANDB_API_KEY=$OPTARG ;;
    m) WANDB_MODE=$OPTARG ;;
    t) TESTCASE=$OPTARG ;;
    h) print_help; exit 0 ;;
    *) echo "Invalid option: -$OPTARG"; print_help; exit 1 ;;
  esac
done

# Validate required arguments and set defaults
if [ -z "$TESTCASE" ]; then
    echo "ERROR: Test case (-t) is required but not provided."
    print_help
    exit 1
fi

if [ -z "$WANDB_API_KEY" ]; then
    echo "WARNING: WANDB_API_KEY not provided. Pass it with -k or ensure it's set as an environment variable."
fi

WANDB_MODE=${WANDB_MODE:-online}

# Source helper script
SCRIPT_DIR=$(dirname "$0")
source "$SCRIPT_DIR/test_case_helper.sh"

# Set wandb environment variables
export WANDB_API_KEY=$WANDB_API_KEY
export WANDB_MODE=$WANDB_MODE

# Create folder for logs
LOG_FOLDER=$(date +"%m%d%YT%H%M%S")
mkdir -p "$LOG_FOLDER"

# Start time for performance measurement
START_TIME=$(date +%s)

# Run the specified test case
case $TESTCASE in
    bench_log)
        bench_log "$LOG_FOLDER" 5 1000
        ;;
    bench_log_scale_step)
        bench_log_scale_step "$LOG_FOLDER"
        ;;
    bench_log_scale_metric)
        bench_log_scale_metric "$LOG_FOLDER"
        ;;

    *)
        echo "ERROR: Unrecognized test case: $TESTCASE"
        exit 1
        ;;
esac

# End time and calculate test duration
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

echo "Test completed in ${TOTAL_TIME}s."
echo "Logs saved to $SCRIPT_DIR/$LOG_FOLDER"


