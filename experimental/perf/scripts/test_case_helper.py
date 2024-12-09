from pathlib import Path

from bench_run_log import run_experiment
from process_sar_helper import process_sar_files
from setup_helper import capture_sar_metrics


def bench_log(root_folder: str, loop_count: int, step: int = 2000) -> None:
    """Runs a set of load tests with the same parameter.

    The goal is to measure the performance of a baseline test with reliable
    and repeatable averages and max computed.

    Args:
        root_folder (str): The root directory where results will be stored.
        loop_count (int): Number of iterations to test
        step (int, optional): Number of step in each iteration. Defaults to 2000.
    """
    mc = 100

    for sort_key, loop in enumerate(range(1, loop_count + 1), start=1):
        run_experiment_helper(loop, step, mc, root_folder, sort_key)


def bench_log_scale_step(root_folder: str, list_of_steps: list[int]) -> None:
    """Runs a set of load tests with increasing # of steps.

    The goal is to measure the performance impact of runs with more steps.

    Args:
        root_folder (str): The root directory where results will be stored.
        list_of_steps (list[int]): The list of steps used in the testing.
    """
    loop = 1
    mc = 100

    for sort_key, step in enumerate(list_of_steps):
        run_experiment_helper(loop, step, mc, root_folder, sort_key)


def bench_log_scale_metric(root_folder: str, list_of_metric_count: list[int]) -> None:
    """Runs a set of load tests with increasing # of metrics per step.

    The goal is to measure the performance impact of more metrics logged per step.

    Args:
        root_folder (str): The root directory where results will be stored.
        list_of_metric_count (list[int]): The list of metric counts used in the testing.
    """
    loop = 1
    step = 1000

    for sort_key, mc in enumerate(list_of_metric_count):
        run_experiment_helper(loop, step, mc, root_folder, sort_key)


def run_experiment_helper(
    loop: int,
    step: int,
    mc: int,
    root_folder: str,
    sort_key: int,
    output_file: str = "results.json",
) -> None:
    """A helper to do the standard perf test setup.

    1) create a folder for this particular load test iteration
    2) start capturing resource metrics
    3) run the actual load tests
    4) end the resource metrics and compute the summary stats

    Args:
        loop (int): The current loop iteration number.
        step (int): Number of steps within the loop.
        mc (int): Number of metrics to log per step.
        root_folder (str): The root directory where results will be stored.
        sort_key (str): A key used for sorting the test data (for naming the folder).
        output_file (str, optional): The name of the file to store the results. Defaults to "results.json".

    Returns:
        None: This function does not return any value. It performs file and metric operations.

    """
    log_folder = Path(root_folder) / f"loop{loop}_step{step}_metriccount{mc}_{sort_key}"

    log_folder.mkdir(parents=True, exist_ok=True)

    capture_sar_metrics(log_folder)

    run_experiment(loop, step, mc, output_file=str(log_folder / output_file))

    process_sar_files(log_folder)
