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
     log_scalar
     log_scale_step
     log_scale_step_large
     log_scale_metric
     log_scale_metric_large
     log_audio
     mltraq
     mltraq_scale_step
  -k Wandb API key (optional)
  -m online|offline  Wandb logging mode (optional, default: online)

Example: python run_load_tests.py -t log_scalar
"""
    )


def run_test_case(
    test_case: str, log_folder: str, num_of_parallel_runs: int, data_type: str
):
    if test_case == "log_scalar":
        test_case_helper.run_perf_tests(
            loop_count=4,
            step_count=[20000],
            metric_count=[100],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type="scalar",
        )

    elif test_case == "log_scalar_step_1M":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[1000000],
            metric_count=[100],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type="scalar",
        )

    elif test_case == "log_scale_step":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[1000, 2000, 4000, 8000],
            metric_count=[100],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "log_scale_step_large":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[10000, 20000, 40000, 80000],
            metric_count=[100],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "log_scalar_metrics_1M":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[1],
            metric_count=[1000000],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type="scalar",
        )

    elif test_case == "log_scalar_metrics_100K":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[10],
            metric_count=[100000],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type="scalar",
        )

    elif test_case == "log_scalar_100Ksteps_100Kmetrics":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[100000],
            metric_count=[100000],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type="scalar",
        )

    elif test_case == "log_scale_metric":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[1000],
            metric_count=[1000, 2000, 4000, 8000],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "log_scale_metric_large":
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[10],
            metric_count=[10000, 20000, 40000, 80000, 160000],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "log_media":
        test_case_helper.run_perf_tests(
            loop_count=4,
            step_count=[2000],
            metric_count=[10],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "mltraq_scale_step":
        # this test simulate what MLTraq did on
        # https://github.com/elehcimd/mltraq/blob/devel/notebooks/07%20Tracking%20speed%20-%20Benchmarks%20rev1.ipynb
        # setup: log different # of steps, each step with 1 metric
        test_case_helper.run_perf_tests(
            loop_count=1,
            step_count=[10000, 50000, 100000, 500000],
            metric_count=[1],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    elif test_case == "mltraq":
        # this test simulate MLTraq's looping experiement
        # setup: measure total time of 10 experiments, with 100 steps, each step with 1 metric
        test_case_helper.run_perf_tests(
            loop_count=10,
            step_count=[100],
            metric_count=[1],
            root_folder=log_folder,
            num_of_processes=num_of_parallel_runs,
            data_type=data_type,
        )

    else:
        logger.error(f"Unrecognized test case: {test_case}")
        exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run load tests.")
    parser.add_argument(
        "-t",
        "--testcase",
        type=str,
        required=True,
        help="log_scalar | log_scalar_scale_step | log_scalar_scale_metric | log_media",
    )
    parser.add_argument(
        "-d",
        "--data_type",
        type=str,
        help='wandb data type to log. Default "None" means scalar.',
        default="scalar",
    )
    parser.add_argument(
        "-n",
        "--num_of_parallel_runs",
        type=int,
        default=1,
        help="Number of parallel tests to run (default: 1)",
    )

    args = parser.parse_args()

    testcase = args.testcase
    num_of_parallel_runs = args.num_of_parallel_runs
    data_type = args.data_type

    if not testcase:
        logger.error("Test case (-t) is required but not provided.")
        print_help()
        exit(1)

    # Create root folder for test logs
    log_folder = datetime.datetime.now().strftime("%m%d%YT%H%M%S")
    os.makedirs(log_folder, exist_ok=True)

    start_time = time.time()

    # Run the specified test case
    run_test_case(testcase, log_folder, num_of_parallel_runs, data_type)

    end_time = time.time()
    total_time = end_time - start_time
    logger.info(f"Test completed in {total_time:.2f}s.")
    logger.info(f"Logs saved to {os.getcwd()}/{log_folder}")


if __name__ == "__main__":
    main()
