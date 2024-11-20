#!/bin/bash

# Prints the help message
print_help() {
    echo "Usage: ./run_load_tests.sh -t <test case> [options]"
    echo "  -t test case to run (required) "
    echo "     bench_log [optional] -f '<num_of_test_runs> <num_of_logging_steps_per_run>'"
    echo "       e.g run_load_tests.sh -t bench_log -f '4 10000'"
    echo "     bench_log_scale_step [optional] -f 'a list of steps'" 
    echo "       e.g run_load_tests.sh -t bench_log_scale_step -f '1000 2000 4000 8000 16000'"
    echo "     bench_log_scale_metric [optional] -f 'a list of metric counts'"
    echo "       e.g run_load_tests.sh -t bench_log_scale_metric -f '100 200 400 800 1600'"
    echo "  -f test case flags"
    echo "  -k Wandb API key (optional)"
    echo "  -m online|offline  Wandb logging mode (optional, default: online)"
    echo
    echo "Example: ./run_load_tests.sh -t bench_log -f '4 10000' -k abcde123 -m offline"
}

# Parse arguments
while getopts "k:m:t:f:h" arg; do
  case $arg in
    k) WANDB_API_KEY=$OPTARG ;;
    m) WANDB_MODE=$OPTARG ;;
    t) TESTCASE=$OPTARG ;;
    f) FLAGS=$OPTARG ;;
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

# Source the test cases
SCRIPT_DIR=$(dirname "$0")
source "$SCRIPT_DIR/test_case_helper.sh"

# Set wandb environment variables
export WANDB_API_KEY=$WANDB_API_KEY
export WANDB_MODE=$WANDB_MODE

# Create root folder for test logs
LOG_FOLDER=$(date +"%m%d%YT%H%M%S")
mkdir -p "$LOG_FOLDER"

# Start time for performance measurement
START_TIME=$(date +%s)

# Run the specified test case
case $TESTCASE in
    bench_log)
        if [ "$FLAGS" == "" ]; then
            bench_log "$LOG_FOLDER" 4 10000
        else
            bench_log "$LOG_FOLDER" $FLAGS
        fi
        ;;
    bench_log_scale_step)
        if [ "$FLAGS" == "" ]; then
            bench_log_scale_step "$LOG_FOLDER" "1000 2000 4000 8000"
        else
            bench_log_scale_step "$LOG_FOLDER" "$FLAGS"
        fi
        ;;
    bench_log_scale_metric)
        if [ "$FLAGS" == "" ]; then
            bench_log_scale_metric "$LOG_FOLDER" "100 200 400 800"
        else
            bench_log_scale_metric "$LOG_FOLDER" "$FLAGS"
        fi
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
