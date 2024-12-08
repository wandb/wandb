import argparse
import datetime
import os
import time

import test_case_helper
from setup_helper import get_logger

logger = get_logger(__name__)


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
        loop_count = 4
        step_count = 10000
        logger.info(
            f"Load testing SDK logging in {loop_count} iterations, "
            f"each logging {step_count} steps, 100 metrics and metric key size of 10"
        )
        test_case_helper.bench_log(log_folder, loop_count, step_count)

    elif test_case == "bench_log_scale_step":
        steps = [1000, 2000, 4000, 8000]
        logger.info(
            f"Load testing SDK logging scaling through {steps} steps "
            "each logging 100 metrics with a metric key size of 10"
        )
        test_case_helper.bench_log_scale_step(log_folder, steps)

    elif test_case == "bench_log_scale_metric":
        metrics = [100, 200, 400, 800]
        logger.info(
            f"Load testing SDK logging scaling through {metrics} metrics, "
            "in each of the 1000 steps, and a metric key size of 10"
        )
        test_case_helper.bench_log_scale_metric(log_folder, metrics)

    else:
        logger.error(f"Unrecognized test case: {test_case}")
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
        logger.error("Test case (-t) is required but not provided.")
        print_help()
        exit(1)

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
    logger.info(f"Test completed in {total_time:.2f}s.")
    logger.info(f"Logs saved to {os.getcwd()}/{log_folder}")


if __name__ == "__main__":
    main()
