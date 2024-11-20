#!/bin/bash

# This file is a helper who invokes the actual python test cases.
# It is sourced by run_load_tests.sh

SCRIPT_DIR=$(dirname "$0")

# Function to display an error message and exit
error_exit() {
    echo "ERROR: $1" >&2
    exit 1
}

results_file="results.json"
metrics_file="metrics.json"

# Function to run a test log for a specific loop count and step count
bench_log() {
    local folder="$1"
    local loop_count="$2"
    local step="$3"

    for loop in `seq 1 $loop_count`; do
        local log_folder="${folder}/loop${loop}_step${step}"
        mkdir -p "$log_folder" || error_exit "Failed to create directory $log_folder"

        echo "Starting metrics capture for loop $loop, step $step in the background..."
        capture_metrics "$log_folder"

        python testfiles/bench_run_log.py -l "1" -s "$step" -o $results_file > "$log_folder/perftest.log" || error_exit "Performance test failed"
        mv $results_file $log_folder/

        wait # wait for background sar process to finish

        $SCRIPT_DIR/process_sar_helper.sh -d "$log_folder" -o $metrics_file >> "$log_folder/perftest.log"
    done
}

# Function to run test log() with increasing step count (i.e. epoch)
bench_log_scale_step() {
    local folder="$1"
    shift
    local list_of_steps="$@"
    local loop=1

    for step in $list_of_steps; do

        local log_folder="${folder}/loop${loop}_step${step}"
        mkdir -p "$log_folder" || error_exit "Failed to create directory $log_folder"

        echo "Starting metrics capture for loop $loop, step $step..."
        capture_metrics "$log_folder"

        python testfiles/bench_run_log.py -l "$loop" -s "$step" -o $results_file > "$log_folder/perftest.log" || error_exit "Performance test failed"
        mv $results_file $log_folder/

        wait

        $SCRIPT_DIR/process_sar_helper.sh -d "$log_folder" -o $metrics_file  >> "$log_folder/perftest.log"
    done
}

# Function to run test log() with increasing metric count
bench_log_scale_metric() {
    local folder="$1"
    shift
    local list_of_mc_count="$@"
    local loop=1
    local step=1000

    for metric_count in $list_of_mc_count; do
        local log_folder="${folder}/loop${loop}_step${step}_metriccount${metric_count}"
        mkdir -p "$log_folder" || error_exit "Failed to create directory $log_folder"

        echo "Starting metrics capture for loop $loop, step $step, metric_count $metric_count..."
        capture_metrics "$log_folder"

        python testfiles/bench_run_log.py -l "$loop" -s "$step" -n "$metric_count"  -o $results_file > "$log_folder/perftest.log" || error_exit "Performance test failed"
        mv $results_file $log_folder/

        wait
        $SCRIPT_DIR/process_sar_helper.sh -d "$log_folder"  -o $metrics_file >> "$log_folder/perftest.log"
    done
}

# Function to capture system metrics and save them to log files
capture_metrics() {
    local log_dir="$1"
    local iteration=8 # Number of seconds to capture metrics (customize if needed)

    sar -u ALL 1 "$iteration" > "$log_dir/cpu.log" &
    sar -r 1 "$iteration" > "$log_dir/mem.log" &
    sar -n SOCK 1 "$iteration" > "$log_dir/network.sock.log" &
    sar -n DEV 1 "$iteration" > "$log_dir/network.dev.log" &
    sar -B 1 "$iteration" > "$log_dir/paging.log" &
    sar -d -p 1 "$iteration" > "$log_dir/disk.log" &
}
