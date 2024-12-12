import multiprocessing as mp
from pathlib import Path

from bench_run_log import run_experiment
from process_sar_helper import process_sar_files
from setup_helper import capture_sar_metrics, get_logger

import wandb

logger = get_logger(__name__)

def run_perf_tests(
    loop_count: int,
    step_count: list[int],
    metric_count: list[int],
    root_folder: str,
    num_of_processes: int,
    data_type: str = "scalar",
) -> None:
    """A helper to start a series of tests.

    Args:
        loop_count (int): The # of iterations to test repeatedly.
        step_count (list[int]): A list of step counts for each iteration.
        metric_count (list[int]): A list of metric counts for each iteration.
        root_folder (str): The root directory where results will be stored.
        num_of_processes (int): Number of parallel wandb runs to start.
        data_type (str): Wandb data type for the test payload

    Returns:
        None: This function does not return any value. It performs file and metric operations.

    """
    sort_key = 1
    for _ in range(loop_count):
        for step in step_count:
            for mc in metric_count:
                logger.info("##############################################################")
                logger.info(f"The {sort_key}-th run:")
                logger.info(f"  # of steps in each run: {step_count}")
                logger.info(f"  # of metrics in each step: {metric_count}")
                logger.info(f"  # of wandb processes: {num_of_processes}")
                logger.info(f"  data type of the payload: {data_type}")
                run_parallel_experiments_helper(
                    step, mc, root_folder, sort_key, num_of_processes, data_type
                )
                sort_key += 1


def run_parallel_experiments_helper(
    step: int,
    mc: int,
    root_folder: str,
    sort_key: int,
    num_of_processes: int,
    data_type: str = "scalar",
) -> None:
    """A helper to start multiple wandbs in parallel by calling the run_experiment().

    Args:
        step (int): Number of steps within the loop.
        mc (int): Number of metrics to log per step.
        root_folder (str): The root directory where results will be stored.
        sort_key (str): A key used for sorting the test data (for naming the folder).
        num_of_processes (int): Number of parallel wandb runs to start.
        data_type (str): Wandb data type for the test payload

    Returns:
        None: This function does not return any value. It performs file and metric operations.

    """
    log_folder = Path(root_folder) / f"step{step}_metriccount{mc}_datatype{data_type}_{sort_key}"

    log_folder.mkdir(parents=True, exist_ok=True)

    capture_sar_metrics(log_folder)

    # To ensure only 1 wandb-core process is launched to reduce overhead
    wandb.setup()

    processes = []
    for iter in range(1, num_of_processes + 1):
        p = mp.Process(
            target=run_experiment,
            kwargs=dict(
                step_count=step,
                metric_count=mc,
                output_file=str(log_folder / f"results.{iter}.json"),
                data_type=data_type
            ),
        )
        p.start()
        logger.info(f"The {iter}-th process (pid: {p.pid}) has started.")
        processes.append(p)

    # now wait for all processes to finish and exit
    for proc in processes:
        proc.join()

    logger.info("All experiements have finished.")

    process_sar_files(log_folder)
