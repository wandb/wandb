import argparse
import datetime
import os
import time

import test_case_helper


def print_help():
    print(
        """
Usage: python run_load_tests.py -t <test case> [options]
  -t test case to run (required)
     bench_log
     bench_log_scale_step
     bench_log_scale_metric
  -k Wandb API key (optional)
  -m online|offline  Wandb logging mode (optional, default: online)

Example: python run_load_tests.py -t bench_log
"""
    )


def run_test_case(test_case, log_folder):
    if test_case == "bench_log":
        test_case_helper.bench_log(log_folder, 4, 10000)

    elif test_case == "bench_log_scale_step":
        test_case_helper.bench_log_scale_step(log_folder, [1000, 2000, 4000, 8000])

    elif test_case == "bench_log_scale_metric":
        test_case_helper.bench_log_scale_metric(log_folder, [100, 200, 400, 800])

    else:
        print(f"ERROR: Unrecognized test case: {test_case}")
        exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run load tests.")
    parser.add_argument(
        "-t",
        "--testcase",
        required=True,
        help="bench_log | bench_log_scale_step | bench_log_scale_metric",
    )
    parser.add_argument("-k", "--wandb_api_key", help="Wandb API key (optional)")
    parser.add_argument(
        "-m",
        "--wandb_mode",
        default="online",
        help="Wandb logging mode (default: online)",
    )
    args = parser.parse_args()

    testcase = args.testcase
    wandb_api_key = args.wandb_api_key
    wandb_mode = args.wandb_mode

    if not testcase:
        print("ERROR: Test case (-t) is required but not provided.")
        print_help()
        exit(1)

    if not wandb_api_key:
        print(
            "WARNING: WANDB_API_KEY not provided. Ensure it's set as an environment variable."
        )

    # Set Wandb environment variables
    os.environ["WANDB_API_KEY"] = wandb_api_key if wandb_api_key else ""
    os.environ["WANDB_MODE"] = wandb_mode

    # Create root folder for test logs
    log_folder = datetime.datetime.now().strftime("%m%d%YT%H%M%S")
    os.makedirs(log_folder, exist_ok=True)

    start_time = time.time()

    # Run the specified test case
    run_test_case(testcase, log_folder)

    end_time = time.time()
    total_time = end_time - start_time
    print(f"Test completed in {total_time:.2f}s.")
    print(f"Logs saved to {os.getcwd()}/{log_folder}")


if __name__ == "__main__":
    main()
