from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from .bench_run_log import Experiment
from .process_sar_helper import capture_sar_metrics, process_sar_files

logger = logging.getLogger(__name__)


def run_perf_tests(
    loop_count: int,
    num_steps_options: list[int],
    num_metrics_options: list[int],
    root_folder: str,
    num_processes: int,
    data_type: Literal["scalar", "audio", "video", "image", "table"] = "scalar",
    metric_key_size: int = 10,
) -> None:
    """A helper to start a series of tests.

    Args:
        loop_count (int): The # of iterations to test repeatedly.
        num_steps_options: A list of number of steps to iterate over.
        num_metrics_options: A list of number of metrics to iterate over.
        root_folder (str): The root directory where results will be stored.
        num_processes (int): Number of parallel wandb runs to start.
        data_type (str): Wandb data type for the test payload

    Returns:
        None: This function does not return any value. It performs file and metric operations.

    """
    sort_key = 1
    for _ in range(loop_count):
        for num_steps in num_steps_options:
            for num_metrics in num_metrics_options:
                logger.info(
                    "##############################################################"
                )
                logger.info(f"The {sort_key}-th run:")
                logger.info(f"\tnumber of steps in each run: {num_steps}")
                logger.info(f"\tnumber of metrics in each step: {num_metrics}")
                logger.info(f"\tnumber of wandb processes: {num_processes}")
                logger.info(f"\tdata type of the payload: {data_type}")

                log_folder = (
                    Path(root_folder)
                    / f"step{num_steps}_metric_count{num_metrics}_datatype{data_type}_{sort_key}"
                )

                log_folder.mkdir(parents=True, exist_ok=True)

                capture_sar_metrics(str(log_folder))

                experiment = Experiment(
                    num_steps=num_steps,
                    num_metrics=num_metrics,
                    metric_key_size=metric_key_size,
                    data_type=data_type,
                )

                experiment.parallel_runs(num_processes)

                logger.info("All experiements have finished.")

                process_sar_files(str(log_folder))

                sort_key += 1
                time.sleep(10)  # sleep some time between run to let it finish flushing
