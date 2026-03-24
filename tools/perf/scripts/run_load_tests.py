from __future__ import annotations

import argparse
import datetime
import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

from .setup_helper import setup_package_logger
from .test_case_helper import run_perf_tests

logger = logging.getLogger(__name__)


@dataclass
class Arguments:
    loop_count: int
    step_count: list[int]
    metric_count: list[int]
    root_folder: str
    num_of_processes: int
    data_type: Literal["scalar", "audio", "video", "image", "table"]


class TestCases:
    def __init__(
        self,
        log_folder: str | None = None,
        num_of_parallel_runs: int = 1,
        data_type: Literal["scalar", "audio", "video", "image", "table"] = "scalar",
    ):
        self.cases = {
            "log_scalar": Arguments(
                loop_count=4,
                step_count=[20_000],
                metric_count=[100],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scalar_step_1M": Arguments(
                loop_count=1,
                step_count=[1_000_000],
                metric_count=[100],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scale_step": Arguments(
                loop_count=1,
                step_count=[1_000, 2_000, 4_000, 8_000],
                metric_count=[100],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scale_step_large": Arguments(
                loop_count=1,
                step_count=[10_000, 20_000, 40_000, 80_000],
                metric_count=[100],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scalar_metrics_1M": Arguments(
                loop_count=1,
                step_count=[1],
                metric_count=[1_000_000],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scalar_metrics_100K": Arguments(
                loop_count=1,
                step_count=[10],
                metric_count=[100_000],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scalar_100Ksteps_100Kmetrics": Arguments(
                loop_count=1,
                step_count=[100_000],
                metric_count=[100_000],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scale_metric": Arguments(
                loop_count=1,
                step_count=[1_000],
                metric_count=[1_000, 2_000, 4_000, 8_000],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_scale_metric_large": Arguments(
                loop_count=1,
                step_count=[10],
                metric_count=[10_000, 20_000, 40_000, 80_000, 160_000],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type="scalar",
            ),
            "log_media": Arguments(
                loop_count=1,
                step_count=[2000],
                metric_count=[10],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type=data_type,
            ),
            # this test simulate what MLTraq did on
            # https://github.com/elehcimd/mltraq/blob/devel/notebooks/07%20Tracking%20speed%20-%20Benchmarks%20rev1.ipynb
            # setup: log different # of steps, each step with
            "mltraq_scale_step": Arguments(
                loop_count=1,
                step_count=[10_000, 50_000, 100_000, 500_000],
                metric_count=[1],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type=data_type,
            ),
            "mltraq": Arguments(
                loop_count=10,
                step_count=[100],
                metric_count=[1],
                root_folder=log_folder,
                num_of_processes=num_of_parallel_runs,
                data_type=data_type,
            ),
        }

    def run(self, test_case: str):
        if test_case not in self.cases:
            raise ValueError(f"Test case {test_case} is not found")

        argument = self.cases[test_case]
        run_perf_tests(
            loop_count=argument.loop_count,
            num_steps_options=argument.step_count,
            num_metrics_options=argument.metric_count,
            root_folder=argument.root_folder,
            num_processes=argument.num_of_processes,
            data_type=argument.data_type,
        )


if __name__ == "__main__":
    setup_package_logger()

    test_cases_instance = TestCases()

    parser = argparse.ArgumentParser(description="Run load tests.")
    parser.add_argument(
        "-t",
        "--test-case",
        type=str,
        required=True,
        choices=list(test_cases_instance.cases.keys()),
        help="The name of the test case to run",
    )
    parser.add_argument(
        "-d",
        "--data-type",
        type=str,
        default="scalar",
        choices=["scalar", "audio", "video", "image", "table"],
        help="The wandb data type to log. Default is 'scalar'.",
    )
    parser.add_argument(
        "-n",
        "--num-of-parallel-runs",
        type=int,
        default=1,
        help="Number of parallel tests to run. Default is 1.",
    )

    parser.add_argument(
        "-l",
        "--log-folder",
        type=str,
        default=None,
        help="The folder to save the logs. Default is current working directory.",
    )

    args = parser.parse_args()

    # Create root folder for test logs
    log_folder = args.log_folder
    if log_folder is None:
        log_folder = datetime.datetime.now().strftime("%m%d%YT%H%M%S")
    os.makedirs(log_folder, exist_ok=True)

    start_time = time.time()

    # Run the specified test case
    TestCases(
        log_folder=log_folder,
        num_of_parallel_runs=args.num_of_parallel_runs,
        data_type=args.data_type,
    ).run(args.test_case)

    logger.info(f"Test completed in {time.time() - start_time:.2f}s.")
    logger.info(f"Logs saved to {os.getcwd()}/{log_folder}")
